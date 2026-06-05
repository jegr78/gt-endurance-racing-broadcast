# Discord in install-apps + first binary release + operator docs on the `iro` binary

**Date:** 2026-06-05
**Status:** approved design

## Goal

Three connected changes that finish the operator-facing story of the standalone
`iro` binary:

1. `iro install-apps` also installs **Discord** (interview audio) on all three OSes.
2. Cut the **first GitHub release** (`v0.1.0`) and change the release assets so the
   binary is named `iro` on every OS with zero rename/chmod steps for operators.
3. Rework **all operator documentation** (wiki + shipped docs + README operator
   part) to use the release binary (`iro …`) instead of `python3 src/iro.py …`.
   Dev/build documentation keeps Python.

## Part 1 — Discord in `iro install-apps`

Package sources (verified 2026-06-05):

| OS | Source | Verified |
|---|---|---|
| Windows | winget `Discord.Discord` | manifests exist in microsoft/winget-pkgs, actively maintained |
| macOS | brew cask `discord` | `brew info --cask discord` → 0.0.393, official homebrew-cask |
| Linux | official `.deb` from `https://discord.com/api/download?platform=linux&format=deb` | chosen over the snap (snap publisher is Snapcrafters — community, not Discord Inc.) |

Changes in `src/scripts/install_apps.py`:

- `APPS = ("obs", "companion", "tailscale", "discord")`.
- `WINGET_APP_IDS["discord"] = "Discord.Discord"`, `BREW_CASKS["discord"] = "discord"`.
- Presence detection (`app_present`):
  - Windows: `%LOCALAPPDATA%\Discord\Update.exe` (Squirrel per-user install;
    `Update.exe` is the version-stable path — `app-x.y.z\Discord.exe` moves on
    every update).
  - macOS: `/Applications/Discord.app`.
  - Linux: `/usr/share/discord`, `/usr/bin/discord` (what the .deb installs).
- Linux install: new step kind `('deb', url)` in `linux_install_steps()` —
  download the .deb over HTTPS (cert-verified) to a temp file, then run
  `sudo apt-get install -y <tmpfile>` **visibly** (same security model as the
  existing vendor scripts: no pipe-to-shell, explicit operator confirmation).
  Download helper lives in `installer_common.py` next to `run_remote_script()`.
- `apps_manual_guide()`: add Discord lines (macOS/Windows: discord.com/download;
  Linux: the .deb command).
- First-run notes at the end of `main()`: add a Discord line (sign in; used for
  interview audio).
- Tests (`tests/test_install_apps.py`): APPS contents, winget/brew commands
  include discord, the deb step appears in `linux_install_steps`, presence
  candidates per OS. Mocked like the existing tests; no network in tests.

## Part 2 — First release + asset naming

Problem: release assets share one namespace per GitHub release, so macOS `iro`
and Linux `iro` would collide — that is the only reason the current asset names
carry OS suffixes. The built binary is already named `iro`/`iro.exe`.

Changes in `.github/workflows/release.yml`:

| OS | Asset | Content |
|---|---|---|
| Windows | `iro-windows.zip` | `iro.exe` + `.env.example` |
| macOS | `iro-macos.tar.gz` | `iro` + `.env.example` (executable bit preserved by tar) |
| Linux | `iro-linux.tar.gz` | `iro` + `.env.example` (executable bit preserved by tar) |

Every archive ships `.env.example`: the frozen binary auto-loads
`<exe-dir>/.env` but does **not** create it, and its error messages reference
`.env.example` — which a binary-only user would otherwise not have. Extracting
the archive also naturally creates the binary's "own folder" (`.env` and
`runtime/` live next to it).

No rename and no chmod for operators. The one-time Gatekeeper/SmartScreen
"run anyway" confirmation remains (unsigned binaries — accepted, documented).

`CLAUDE.md` (Standalone binary section) is updated to the new asset names.

Version management: **git tags drive everything** (already wired): pushing
`v*` runs tests on all 3 OSes, builds, stamps the tag into the binary
(`iro --version`), creates the release with generated notes and uploads the
assets. First release: **`v0.1.0`**, tagged after Parts 1+2 are merged and CI
is green. Convention going forward: semver tags, `releases/latest` is the
operator-facing download link.

## Part 3 — Operator docs on the binary

Convention documented once (setup page) and used everywhere: download from
GitHub **Releases → latest**, put `iro` in **its own folder** (`.env` and
`runtime/` are created next to it), every command is `iro …`.

| Document | Change |
|---|---|
| `src/docs/wiki/Set-up-the-broadcast-PC.md` | Restructure: Step 1 = get the binary (replaces "Install Python"). Step 2 = `iro install-apps` (now incl. Discord). Step 3 = `iro install-tools`. Manual install tables/commands stay as collapsible `<details>` fallback ("run from source" incl. Python). Remaining steps: command swap to `iro …`. |
| `Run-an-event.md`, `If-something-goes-wrong.md`, `Relay-Mode.md`, `OBS-Setup.md`, `Configuration.md`, `Static-Mode.md` | Command swap `python3 src/iro.py …` → `iro …`. Relay-Mode drops the repo/package dual line (one `iro` line + short dev note). |
| `Home.md` | Point newcomers at the release download. |
| `Build-and-maintenance.md` | **Keeps Python** (dev/build). Add: release/tagging process (semver `v*` tag → CI release) and a note that operator docs use the release binary. |
| `src/docs/README_SETUP.md`, `IRO_Broadcast_Setup_Guide.md`, `IRO_cheat_sheets.html` | Command swap to `iro …`; setup guide gets the binary download section. |
| root `README.md` | Operator quickstart on the binary; tests/build/dev sections keep `python3`. |

## Order of execution

1. Part 1 (Discord) + Part 2 (release.yml) — code + tests, full suite,
   `tools/build.py` verify, push, CI green.
2. Tag `v0.1.0` → release workflow → verify the three assets exist and
   `iro --version` prints `v0.1.0`.
3. Part 3 (docs) — written against the now-real release URLs, push, CI green.
4. `tools/sync-wiki.py` to publish the wiki; visual check of the live pages.

## Out of scope

- Code signing (accepted: unsigned + one-time OS warning).
- Snap/flatpak distribution of Discord.
- Any change to the relay, Companion logic, or the zip package layout.
