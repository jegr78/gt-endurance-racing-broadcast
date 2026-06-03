# Pre-Flight Check — Design Spec

**Date:** 2026-06-03
**Status:** Approved (design) — ready for implementation plan

## Purpose

A single cross-platform script a producer runs **before an event** to confirm the
machine is ready to run the IRO broadcast setup, and that also serves as the
executable definition of the **system requirements** for any producer's machine.

Motivation: on the dev Mac, OBS lag during testing traced to **swap thrashing**
(16 GB RAM full, swap ~98 % used, 46-day uptime) — a memory/fresh-boot problem,
not leftover processes. Production will run on a separate Streaming PC (Windows)
and on other producers' machines, so the check and the requirements must be
cross-platform and self-documenting.

## Scope

In scope: hardware checks, tool-chain checks, port checks, cookies check, a static
network-bandwidth advisory, a traffic-light report, and a "System Requirements"
section in `README_SETUP.md`.

Out of scope (YAGNI): live network speed test, auto-fixing/installing anything,
GUI, JSON output, continuous monitoring, `--strict` mode.

## Placement & Packaging

- File: **`src/scripts/preflight.py`** — pure Python 3 stdlib, no third-party deps,
  no `.sh`/`.bat` launcher (matches the project's all-Python convention; the build
  even verifies "no .sh/.bat shipped").
- `tools/build.py` already does `cp("scripts", "scripts")`, so the file is packaged
  automatically to `IRO_Broadcast_Package/scripts/preflight.py` — **no build.py
  change required**. (Optional nicety: add a build-verify check that the file is
  present.)
- Invocation: `python3 scripts/preflight.py` (from the package root) or
  `python3 src/scripts/preflight.py` (repo).
- CLI options (mirror the relay where relevant): `--runtime-dir <dir>` and
  `--cookies <path>` for locating `cookies.txt`; `--no-color` to force plain text.

## Output Model

Each check returns a `Result(level, name, detail)`. Levels:

- **PASS** — meets the recommended bar.
- **WARN** — works but sub-optimal / advisory / can't confirm.
- **FAIL** — will likely break production.
- **INFO** — advisory text, no judgement (used for the network guideline).

Checks are printed grouped by section with a colored tag (`[PASS]/[WARN]/[FAIL]/[INFO]`).
ANSI color auto-disables when stdout is not a TTY or `--no-color` is set; on Windows
the script attempts to enable VT processing, falling back to plain text.

A final summary prints counts and an overall verdict.
**Exit code: 0 if no FAIL, 1 if any FAIL** (so it can gate a launch script later).

## Checks

### Section 1 — Hardware

| Check | FAIL | WARN | PASS |
|---|---|---|---|
| RAM total | < 16 GB | 16 – < 32 GB | ≥ 32 GB |
| CPU logical cores | < 6 | 6 – 7 | ≥ 8 |
| Free disk (working volume) | < 2 GB | < 5 GB | ≥ 5 GB |
| Swap in use | — (never FAIL) | notable (> ~1 GB) → "not a fresh boot / under memory pressure" | low |

Platform readers (isolated, each returns a raw number):
- RAM total — macOS: `sysctl -n hw.memsize`; Linux: `/proc/meminfo` `MemTotal`;
  Windows: `ctypes` `GlobalMemoryStatusEx().ullTotalPhys`.
- Swap used — macOS: `sysctl -n vm.swapusage` (parse `used`); Linux: `/proc/meminfo`
  `SwapTotal - SwapFree`; Windows: `GlobalMemoryStatusEx` page-file commit
  (`ullTotalPageFile - ullAvailPageFile`, approximate — advisory only).
- CPU — `os.cpu_count()`. Disk — `shutil.disk_usage`.

### Section 2 — Tool chain

For each of **streamlink, yt-dlp, ffmpeg, deno**: `shutil.which`; if found, run
`<tool> --version` (short timeout) and report the version line. **FAIL if missing**
(the relay requires all four). Also report `python3` version from `sys.version`
(FAIL if < 3.8).

### Section 3 — Ports

- Feed/control ports **53001, 53002, 53003, 8088** must be **FREE**. Test by binding
  a socket on `127.0.0.1:port`. Bind fails → **WARN** ("in use — relay already running
  or a port conflict"). Free → PASS.
- Service ports **4455** (OBS WebSocket) and **8000** (Companion) are **reachability
  probes**. Connect succeeds → PASS ("reachable"). Connection refused → **WARN**
  ("not reachable — start OBS + enable WebSocket" / "start Companion"). These are
  advisory because preflight may run before OBS/Companion are launched.

### Section 4 — Cookies

Locate `cookies.txt` the same way the relay does: `<runtime-dir>/cookies.txt`, where
`--runtime-dir` defaults to the relay's own default (next to `iro-feeds.py`, i.e.
the package's `relay/` dir); `--cookies` overrides. Checks:
- Missing → **WARN** ("run get-cookies before the event").
- Older than ~12 h → **WARN** ("cookies rotate — re-run get-cookies").
- Present, fresh, and contains a logged-in marker (`SAPISID` / `__Secure-*PSID` /
  `LOGIN_INFO`) → PASS. Marker absent → WARN ("no logged-in session detected").

### Section 5 — Network (advisory, INFO only)

No measurement. Print a fixed guideline: OBS pushes the program to YouTube **while**
the relay pulls up to 3 live feeds simultaneously, so a wired connection with stable
upload headroom above the OBS bitrate is required. Rule of thumb: sustained upload
≥ OBS bitrate + margin; wired strongly preferred over Wi-Fi.

## System Requirements (README_SETUP.md)

Add a "System Requirements" section near the top:

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 6-core modern (Intel 12th-gen i5 / AMD Ryzen 5) | 8-core+ (i7 / Ryzen 7) |
| RAM | 16 GB | 32 GB |
| GPU | hardware encoder (NVIDIA NVENC / Apple Silicon / Intel QSV) | dedicated NVIDIA GPU w/ NVENC |
| Disk | SSD, ≥ 5 GB free | SSD |
| OS | Windows 10/11 64-bit or macOS 13+ | — |
| Network | wired; stable upload headroom for YT push + 3 feed pulls | wired gigabit |

Plus operational guidance: **reboot before each event** (clears swap), then run
`python3 scripts/preflight.py` and resolve any FAIL/WARN before going live. Note the
14 HUD browser sources in OBS are memory-heavy — the RAM bar reflects that.

## Internal Structure (for isolation/testability)

- **Platform readers** — `read_ram_bytes()`, `read_swap_used_bytes()`,
  `disk_free_bytes(path)`: encapsulate per-OS branches, return raw numbers.
- **Classifiers (pure)** — `classify_ram(gb)`, `classify_cpu(n)`, `classify_disk(gb)`,
  `classify_swap(gb)` → return a `Result`. Trivially unit-testable.
- **Probes** — `port_free(port)`, `port_reachable(host, port)`, `tool_version(name)`,
  `cookies_status(path)`.
- **Reporter** — formats/colors `Result`s, prints sections + summary, computes exit code.
- **`main()`** — parse args, run sections in order, report.

## Testing

`tests/test_preflight.py` (stdlib `unittest`, matching `tests/test_pov.py`):
- Classifier boundary tests (e.g. 15.9/16/31.9/32 GB → FAIL/WARN/WARN/PASS; cores
  5/6/8; disk 1/4/5 GB; swap 0.5/2 GB).
- `port_free` against a port the test binds itself (deterministic).
- `cookies_status` against temp files (missing / old mtime / fresh-with-marker).
Platform readers are not unit-tested (OS-specific); classifiers consume their output
so the logic is covered.

## Build / Delivery

1. Implement `src/scripts/preflight.py`.
2. Add `tests/test_preflight.py`.
3. Add the System Requirements section to `src/docs/README_SETUP.md`.
4. (Optional) add a build-verify check for `scripts/preflight.py`.
5. Run `python3 tools/build.py` to rebuild `dist/` + the ZIP; confirm the verify
   checks (incl. "no .sh/.bat shipped") still pass.
