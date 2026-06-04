# IRO Native Binary (Standalone `iro` CLI) — Design

**Date:** 2026-06-04
**Status:** Approved direction (brainstormed with maintainer)

## Goal

Ship the unified `iro` CLI as a **standalone native executable** for Windows,
macOS, and Linux so producers do not need Python installed. **Windows is the
primary platform** (the production streaming PC runs Windows); macOS is the
secondary, fully supported platform; Linux is provided for completeness
(expected use: WSL on Windows or Docker on macOS).

The repo mode (`python3 src/iro.py …`) stays fully functional for development
and tests — the binary is an additional delivery form, not a replacement.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Packaging tech | **PyInstaller `--onefile`** (mature, pure-stdlib codebase → no dependency issues, ~15–25 MB) |
| External tools (yt-dlp, streamlink, ffmpeg, deno) | **Stay external**, checked by `iro preflight`; new **`iro install-tools`** installs them via the OS package manager |
| Build & distribution | **GitHub Actions release workflow**: on tag `v*`, a 3-OS matrix runs tests → builds → smoke-tests → attaches binaries to a GitHub Release |
| Non-script assets (OBS template, Companion config, HUD page + flags/brands) | **Embedded in the binary**; `iro setup` localizes the OBS collection as today, new **`iro export companion`** writes the Companion config for import |
| macOS-specific calls | **Must go.** Companion control becomes a per-platform adapter; Windows gets first-class start/stop/status |
| Linux Companion control | Deliberately **manual** (clear message): in the WSL/Docker scenario Companion runs on the *host*, so local automation would be wrong |

## Architecture

### 1. Frozen-mode awareness

A single module-level predicate distinguishes the two run modes:

- **Repo mode:** `sys.frozen` absent → behave exactly as today
  (`python3 src/iro.py`, scripts under `src/`).
- **Frozen mode:** `getattr(sys, "frozen", False)` is true (PyInstaller) →
  resources resolve from `sys._MEIPASS`, child processes re-invoke the binary.

Two small helpers carry this through the codebase:

- **`resource_path(relpath)`** — returns `<repo>/src/<relpath>` in repo mode,
  `sys._MEIPASS/<relpath>` in frozen mode. Used by the relay (hud.html,
  `assets/flags`, `assets/brands`), `iro setup` (OBS template), and
  `iro export companion` (Companion config).
- **`child_argv(verb_args)`** — returns
  `[sys.executable, <script>, …]` in repo mode and
  `[<iro-binary>, <verb>, …]` in frozen mode. **All** child-process spawning
  goes through it (relay daemon, static-stream feeds).

### 2. Child processes: the binary re-invokes itself

There is no `python3` on a producer machine, so every background process is a
re-invocation of the `iro` executable:

- `iro relay start` → `start_detached(child_argv(["relay", "run", …]))` —
  `iro relay run` already exists as the foreground entrypoint.
- `iro streams start` → per-feed children become an internal
  `iro streams run-feed <args>` verb (replacing the direct
  `python3 loopstream.py` spawn). The verb is routed but not advertised in
  `iro help`.

One-shots (`preflight`, `cookies`, `graphics`, `media`, `setup`) run
**in-process** in frozen mode: the corresponding `src/` modules are bundled,
loaded via `importlib`, and their `main(argv)` is called directly. In repo
mode they keep running as subprocesses (today's behavior, unchanged).

### 3. Cross-platform process control (`services.py`)

`services.py` currently has POSIX-only mechanics **and one real Windows bug**:

- **Bug:** `pid_alive()` uses `os.kill(pid, 0)`. On Windows, `os.kill` with
  any signal other than `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` calls
  `TerminateProcess` — the "status check" would **kill** the relay.
  Fix: Windows path probes the PID via `ctypes`
  (`OpenProcess` + `GetExitCodeProcess` == `STILL_ACTIVE`); POSIX keeps the
  signal-0 probe.
- **Spawn:** `start_new_session` (POSIX) → on Windows use
  `creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`.
- **Stop:** SIGTERM→SIGKILL (POSIX) → on Windows `taskkill /PID <pid>`
  (graceful, WM_CLOSE) then `taskkill /F /PID <pid>` after the timeout.

All decision logic stays in pure, unit-testable functions
(`tests/test_services.py` extends to cover the per-OS argv/flag selection;
the platform is a parameter, never read implicitly inside the pure parts).

### 4. Companion control becomes a platform adapter

`companion_control_commands(platform)` in `companion_common.py` grows from
"darwin or None" into a real adapter table:

| Platform | Start | Stop | Running check |
|---|---|---|---|
| Windows | launch discovered `Companion.exe` | `taskkill /IM Companion.exe` (no `/F` — graceful close for the Electron app) | `tasklist /FI "IMAGENAME eq Companion.exe"` |
| macOS | `open -a Companion` | `osascript -e 'quit app "Companion"'` | `pgrep -f …/main.js` |
| Linux | clear "start Companion on the host" message (no automation by design) | — | — |

Windows executable discovery: a candidate-path list (per-user and
`Program Files` install locations) checked in order, overridable via
**`IRO_COMPANION_EXE`** in `.env`. The exact default paths and the graceful
`taskkill` behavior are **validated on the Windows streaming PC** before the
first release (see Validation below). `companion_config_path()` already
handles `%APPDATA%`/XDG and stays.

### 5. New CLI verbs

- **`iro install-tools [--yes]`** — detects the platform package manager and
  installs the four external tools: `winget` (Windows, tested first-class),
  `brew` (macOS), `apt` (Linux). On macOS without Homebrew, offers the
  official brew.sh installer (HTTPS download, explicit confirmation, `--yes`
  skips; brew is then invoked via its absolute path — a fresh bootstrap is not
  on the current process PATH). Without a package manager it prints a per-OS
  manual install guide and exits non-zero. Never elevates privileges itself; it
  surfaces the package manager's own prompts.
- **`iro install-apps [--yes]`** *(added during implementation)* — opt-in
  installer for the three producer applications: OBS Studio, Bitfocus
  Companion, Tailscale via `winget` (Windows) / `brew` casks (macOS) /
  official vendor paths (Linux, apt-based distros). On macOS without Homebrew,
  offers the official brew.sh installer (same HTTPS download + confirmation
  flow as `install-tools`; `--yes` skips). On Linux: OBS via the official PPA
  (`add-apt-repository`, Ubuntu) or plain apt (Debian); Tailscale and
  Companion via their official installer scripts (`tailscale.com/install.sh`
  and `companion-pi/install.sh`), downloaded over HTTPS and executed after an
  explicit operator confirmation (`--yes` skips the prompt for headless use) —
  sudo prompts go to the operator. Non-apt distros fall back to the manual
  guide (exit 0). Detection via well-known install paths (app bundles /
  `Program Files`), `which` fallback; never elevates privileges on
  Windows/macOS.
- **`iro export companion [--out PATH]`** — writes the embedded
  `iro-buttons.companionconfig` (password-stripped, as built) to disk for
  import into Companion. Default output: current directory.
- **`iro --version`** — prints the version stamped at build time (from the
  git tag in CI; `dev` in repo mode).

### 6. CI: build, test, release

A GitHub Actions workflow (`.github/workflows/release.yml`), triggered by
tags matching `v*`:

1. **Matrix:** `windows-latest`, `macos-latest`, `ubuntu-latest`.
2. **Per OS:** run the full stdlib test suite (all `tests/test_*.py`) →
   `pyinstaller` onefile build → **smoke test the produced binary**
   (`iro --version`, `iro status`, `iro export companion` to a temp dir) →
   upload `iro-windows.exe` / `iro-macos` / `iro-linux` as release assets.
3. Tests also run on the 3-OS matrix for pull requests (separate `ci.yml` or
   a shared job), so Windows correctness is continuously proven, not assumed.

The PyInstaller spec/config lives in `tools/` (maintainer-only, not shipped),
written in Python — no shell scripts (project rule); workflow steps call
`python3` directly.

### 7. What the producer downloads

A GitHub Release contains exactly three assets: `iro-windows.exe`,
`iro-macos`, `iro-linux`. Everything else (OBS template, Companion config,
HUD assets) is inside the binary; docs live in the GitHub wiki. The existing
`dist/` ZIP package keeps being built by `tools/build.py` during the
transition; retiring it is a later, separate decision.

## Known constraints (accepted)

- **Unsigned binaries:** macOS Gatekeeper and Windows SmartScreen show a
  one-time warning ("run anyway"). Documented in the wiki with screenshots;
  code signing is out of scope for now.
- **onefile startup delay:** ~1–2 s self-extraction on first start.
  Acceptable for an operator CLI.
- **yt-dlp freshness:** keeping the external tools out of the binary is
  deliberate — yt-dlp must be updatable independently (YouTube changes).

## Validation plan

- **Unit tests (every OS, CI matrix):** pure helpers — adapter selection,
  taskkill/tasklist argv construction, Windows PID-probe decision logic,
  `resource_path` / `child_argv` mode switching, route() for the new verbs.
- **CI smoke test (every release, every OS):** the real binary runs
  `--version`, `status`, `export companion`.
- **Native validation on the Windows streaming PC (before first release):**
  Companion.exe discovery paths, graceful `taskkill` close, relay
  start/stop/status end-to-end, `install-tools` via winget.

## Out of scope

- Code signing / notarization.
- Bundling ffmpeg/deno/yt-dlp/streamlink into the binary.
- Retiring the `dist/` ZIP package (transition: both are produced).
- Linux Companion automation (by design — host runs Companion).
