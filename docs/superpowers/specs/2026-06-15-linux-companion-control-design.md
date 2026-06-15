# Linux Companion start/stop control (companion-pi) with dynamic bind

**Date:** 2026-06-15
**Status:** Design approved, pending implementation plan

## Problem

On Linux the Control Center Apps-View **Start/Stop** button for Companion (and
`racecast event start` step 5, and `racecast companion start/stop` on the CLI) does
nothing useful: `companion_control_commands()` returns `None` for any non-Windows,
non-macOS platform, so the adapter prints

> companion: automated control supports Windows and macOS. On Linux (WSL/Docker),
> run and bind Companion on the host instead.

This was a deliberate choice made when the original assumption held: "in WSL/Docker
setups Companion runs on the HOST, so local automation would target the wrong
machine." But the production machine runs Companion **natively** on the same Linux
host, installed by `racecast install-apps` as the **companion-pi systemd service**
(`/etc/systemd/system/companion.service`, runs as user `companion`, launched by
`/usr/local/src/companionpi/launch.sh`). There, local automation is correct and the
operator wants the button to work.

## Goal

Make `racecast companion start|stop|status`, `event start` step 5, and the Control
Center companion ops control the companion-pi systemd service on native Linux —
**without weakening the bind-security posture** the rest of the toolkit enforces.

## Non-goals

- No change to how Companion is installed.
- No control for setups without a local `companion.service` (WSL/Docker where
  Companion is on the host; manual AppImage installs). Those keep the existing
  "manual" message.
- No `0.0.0.0` exposure by default (see Security below).
- No Control Center op for `enable-control` (it is a one-time, root-level CLI setup;
  the UI start/stop buttons use it transitively once it is in place).

## Key findings (verified on the production machine)

1. **companion-pi is a systemd service.** `companion.service` is `enabled` and runs as
   user `companion`. `systemctl start/stop companion` needs root; `systemctl is-active
   companion` does not.
2. **The bind is a launch-time CLI flag, not config.json.** Companion 3.x headless
   accepts `--admin-address <ip>` (default **`0.0.0.0`**), `--admin-interface
   <iface>`, `--admin-port`. The macOS/Windows trick (edit `config.json` `bind_ip`,
   the GUI launcher reads it as `--admin-address`) **does not apply** — headless
   ignores `config.json` for the bind. companion-pi's `launch.sh` passes **no**
   address flag, so Companion binds `0.0.0.0` (LAN-exposed) by default.
3. **`launch.sh` is root-owned and replaced on companion-pi updates.** companion-pi
   offers no supported mechanism (no EnvironmentFile, no `/boot/companion`, nothing in
   `tools/`/`update-prompt/`) to inject the admin address. The only lever is a systemd
   drop-in overriding `ExecStart`.
4. **The companion-pi data dir is `~companion/.config/companion-nodejs`**, owned by the
   `companion` user — not readable/writable by the producer's login, and not the path
   `companion_config_path()` returns. Confirms config.json editing is not the path on
   Linux.
5. The production machine has **passwordless sudo** globally, but the design must not
   assume that on every machine.

## Gate

Linux **and** a local `companion.service` unit is detected → systemd control. Anything
else → the existing manual message. Absence of a local unit naturally covers WSL/Docker
(Companion on the host) and manual installs, so no explicit WSL detection is needed.

## Architecture

### Bind security model

The toolkit's rule — established for the relay (`--bind auto`) and for Companion on
macOS/Windows — is: **never bind `0.0.0.0`**. Bind the Tailscale IP when the tailnet is
up, else `127.0.0.1` (local-only). The tailnet is the trust boundary; `0.0.0.0` would
expose the unauthenticated admin/tablet on the venue LAN.

On companion-pi the bind is the `--admin-address` flag, so the dynamic bind is enforced
through a systemd `ExecStart` drop-in plus a small per-start environment file. The
chosen address comes from the **existing pure helper** `desired_bind_ip(bind_arg,
tailscale_ip)` — identical Tailscale-or-localhost logic as macOS/Windows.

`--admin-interface tailscale0` was rejected: when the tailnet is down the interface
does not exist and Companion fails to start at all. The `--admin-address` +
`127.0.0.1`-fallback model degrades gracefully (Companion stays usable locally).

### One-time setup: `racecast companion enable-control` (Linux only, idempotent)

Installs the root-owned machinery, with interactive sudo allowed at setup time:

1. **systemd drop-in** `/etc/systemd/system/companion.service.d/racecast-bind.conf`:

   ```ini
   [Service]
   EnvironmentFile=-/etc/systemd/system/companion.service.d/racecast-bind.env
   ExecStart=
   ExecStart=/bin/bash -c 'cd /opt/companion && NODE=$([ -d /opt/companion/node-runtime ] && echo /opt/companion/node-runtime/bin/node || echo /opt/companion/node-runtimes/main/bin/node); exec "$NODE" /opt/companion/main.js --admin-address "${RACECAST_ADMIN_ADDRESS:-127.0.0.1}" --extra-module-path /opt/companion-module-dev'
   ```

   The node-binary detection mirrors `launch.sh` exactly. `EnvironmentFile=-` (leading
   `-`) makes the env file optional, so a missing file falls back to the `:-127.0.0.1`
   default rather than failing the unit. Followed by one `systemctl daemon-reload`.

2. **Privileged helper** `/usr/local/sbin/racecast-companion-bind <ip>` (0755 root):
   validates `<ip>` is a literal IPv4/IPv6 address (reject anything else), writes
   `RACECAST_ADMIN_ADDRESS=<ip>` to `racecast-bind.env`, then `systemctl restart
   companion`. This is the narrow, auditable privilege boundary: a NOPASSWD caller can
   only set a *validated bind IP and restart* — not run arbitrary commands or write
   arbitrary content.

3. **sudoers drop-in** `/etc/sudoers.d/racecast-companion` (0440 root:root,
   **validated with `visudo -cf` before install**): `NOPASSWD` for exactly
   `/usr/local/sbin/racecast-companion-bind` and `/usr/bin/systemctl stop companion`
   (absolute paths). A broken sudoers file disables sudo entirely, so the visudo gate
   is mandatory and the file is written atomically (temp file → validate → install).

4. **Validation with rollback.** After installing, run the helper with `127.0.0.1`,
   confirm `systemctl is-active companion`, and restore the prior running state. On any
   failure, remove `racecast-bind.conf`, `daemon-reload`, restart the vendor
   `ExecStart`, and report — so Companion is never left unstartable.

5. **Idempotent.** If the drop-in, helper, and sudoers file already exist and match the
   expected content, report "already enabled" and make no changes.

`enable-control` on a non-Linux OS, or when no `companion.service` exists, prints a
friendly explanation and exits 0 (not an error).

### Per-command runtime behavior (`racecast.py`)

- `_linux_companion_unit()` (impure adapter): returns `"companion"` when on Linux,
  `shutil.which("systemctl")` exists, and (`systemctl cat companion` returns 0 **or**
  `/etc/systemd/system/companion.service` exists); else `None`.
- `_companion_cmds(cc)` passes `linux_unit=_linux_companion_unit()`. With a unit it now
  returns a non-`None` dict on Linux, which automatically flips `supported` (racecast.py
  ~line 1568), enables the `event start` readiness probe (~line 1781), and makes
  `companion status` report correctly.
- `companion_start([bind])` — Linux-with-unit branch (skips the macOS/Windows
  config.json/bind-editing path entirely):
  - If the setup machinery is absent → print guidance to run `racecast companion
    enable-control` and exit.
  - Compute `ip = desired_bind_ip(bind or "auto", tailscale_ip)`.
  - Run `sudo -n /usr/local/sbin/racecast-companion-bind <ip>`. On a sudo/`-n` failure,
    print one-line guidance (run `enable-control`, or `sudo systemctl start companion`
    manually). Never block on a password prompt (`-n` guarantees no prompt — required
    because Control Center jobs have no stdin).
- `companion_stop()` — Linux-with-unit branch: `sudo -n systemctl stop companion`, same
  failure guidance.
- `companion status`/running probe: `systemctl is-active companion` (no sudo).
  `parse_running` already returns `rc == 0` for non-Windows, which matches `is-active`.

### Pure helpers (`companion_common.py`)

All testable without real systemctl/sudo:

- `companion_control_commands(platform, exe=None, linux_unit=None)` — extend the
  Linux branch: with `linux_unit`, return
  `{"start": [...helper...], "quit": ["sudo","-n","systemctl","stop",unit],
  "running": ["systemctl","is-active",unit]}`; without it, `None` (unchanged).
- `LINUX_COMPANION_UNIT = "companion"`, and path constants for the drop-in dir, the
  `.conf`, the `.env`, the helper, and the sudoers file.
- Content builders: `bind_dropin_content()`, `bind_helper_content()`,
  `sudoers_dropin_content(user, systemctl_path)`, `bind_env_content(ip)`.
- `is_valid_bind_ip(ip)` — IPv4/IPv6 literal validation (reused by the helper's
  expectations and the CLI).
- Idempotency matchers comparing existing file content to expected.

`desired_bind_ip` and `parse_running` are reused unchanged. `plan_companion_action`
and `config_with_bind_ip` stay macOS/Windows-only.

### install-apps integration

`_install_linux` calls `enable-control` automatically after a Linux Companion install
(same confirmation gate as the install steps). Because already-installed machines skip
the install step, `enable-control` is also a standalone command so this machine — where
Companion is already installed — can enable control without reinstalling.

## Error handling

- `sudo -n` failure (no passwordless sudo, setup not run): one-line actionable guidance,
  never a hang.
- `visudo -cf` failure during `enable-control`: abort without installing the sudoers
  file.
- `ExecStart` override invalid (e.g. stale after a structural companion-pi update):
  caught by the `enable-control` validation step, which rolls back to the vendor
  `ExecStart`.
- companion-pi 2.x (`/usr/local/src/companion` present, `headless_ip.js`): detect and
  refuse with a clear message rather than installing a 3.x-shaped override.

## Security

- Default bind is Tailscale IP (tailnet up) or `127.0.0.1` — never `0.0.0.0`. An
  explicit `racecast companion start 0.0.0.0` remains an operator override (deliberate,
  audited), matching macOS/Windows/relay behavior.
- NOPASSWD surface is two absolute-path commands only; the bind helper validates its IP
  argument, so it cannot be coerced into arbitrary action.
- sudoers file is 0440 root:root, visudo-validated, written atomically.
- The bind controls only *where* Companion listens; it does not separate `/tablet` from
  the admin GUI (one port, one shared socket). Restricting *who* on the tailnet reaches
  the port remains a Tailscale-ACL job, as documented for macOS/Windows.

## Operational note (documented for operators)

The `ExecStart` override reproduces companion-pi's node-launch line, so a **structural**
companion-pi update can make it stale. After `sudo companion-update`, run `racecast
companion enable-control` once to re-validate/refresh the drop-in. This matches the
existing "unsupported-but-stable; re-check after Companion upgrades" stance for the
config.json edits on macOS.

## Testing

- `tests/test_companion.py`: `companion_control_commands` Linux+unit vs none; content
  builders; `is_valid_bind_ip`; idempotency matchers; `parse_running` for `is-active`;
  `desired_bind_ip` reuse on Linux.
- `tests/test_racecast.py`: `_linux_companion_unit` with mocked `which`/`systemctl`/
  `exists`; companion subcommand routing including `enable-control`; the
  Linux-`companion_start`/`stop` branches with a fake runner.
- `tests/test_install_apps.py`: the decision to invoke `enable-control` after a Linux
  Companion install.
- All tests run on the Windows/macOS/Linux CI matrix with injected fakes — no real
  systemctl, sudo, or machine paths.

## Docs to update

- `CLAUDE.md`: the Companion sections (no longer "Linux manual by design" wholesale —
  native Linux with a companion-pi service is now controlled; bind is via the systemd
  drop-in; `enable-control` is the one-time setup).
- `_companion_unsupported_msg()` Linux text: shown only when no service is found —
  reword to the "WSL/host/manual install — run & bind Companion yourself" case.
- README / CLI usage strings for the new `companion enable-control` verb.
