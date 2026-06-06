# `iro init` — guided first-time setup wizard

**Date:** 2026-06-06
**Status:** Approved design

## Problem

Setting up a fresh producer machine currently means running eight `iro` commands
in the right order (`install-tools`, `install-apps`, `cookies`, `media`,
`graphics`, `setup`, `export companion`, `preflight`), interleaved with manual
steps the docs describe but nothing enforces: filling in `.env`, logging into
YouTube in the browser, importing the generated OBS collection and Companion
config. Easy to get wrong, hard to remember a season later.

## Goal

One command — `iro init` — that walks the operator through first-time setup as
a **guided wizard**: it runs every automatable step in dependency order, pauses
at the genuinely manual gates, skips what is already done, and ends with the
preflight report plus a printed list of the remaining manual steps.

Explicitly **not** in scope: launching OBS/Companion/Discord/Tailscale (that is
`iro event start`'s job — init prepares the machine, event start brings it up),
performing the GUI imports, or any new install logic (init only orchestrates
the existing one-shots).

## Behavior model

- **Wizard with pauses.** Interactive single run; the operator stays at the
  terminal. Pauses (`input()`) happen only at manual gates, never between
  ordinary steps.
- **Auto + detected skipping.** Before each step the wizard checks whether the
  step's outcome already exists and skips it with a one-line note. Re-running
  `iro init` is therefore cheap and is the standard recovery path.
- **Stop on hard error.** A step exiting non-zero stops the wizard with
  "fix this, then run `iro init` again — completed steps will be skipped".
  No best-effort continuation: the steps build on each other (no tools → no
  cookies; no graphics → black OBS scenes).
- **Non-TTY fallback.** When stdin is not a TTY (CI, piped), a gate degrades to
  checkpoint-and-exit: print the instruction, exit 1.

## Step sequence

| # | Step | Done-detection (→ skip) | Gate before step |
|---|------|------------------------|------------------|
| 1 | `.env` present + filled | `IRO_SHEET_ID` and `IRO_TIMER_URL` set (env or `.env`) | **Pause:** "Fill in `.env`, then press Enter" — wizard re-reads `.env` afterwards |
| 2 | `install-tools --yes` | all four tools on PATH (`shutil.which`: yt-dlp, streamlink, ffmpeg, deno) | – |
| 3 | `install-apps --yes` | all four apps present (`install_apps.app_present`) | – |
| 4 | `cookies <browser>` | `cookies.txt` present + fresh (`preflight.cookies_status`) | **Pause:** "Log into YouTube in <browser>, then press Enter" (only when cookies are missing/stale) |
| 5 | `graphics` | every Assets-tab graphic exists locally (`event.required_graphics` + `event.check_assets`) | – |
| 6 | `media` | Intro/Outro clips exist locally (`event.required_media` + `event.check_assets`) | – |
| 7 | `setup` | import JSON exists **and** is newer than both the source collection and `.env` | – |
| 8 | `export companion` | `iro-buttons.companionconfig` exists in `runtime/` | – |
| 9 | `preflight` | never skipped — it is the closing verification | – |

`.env` is step 1 (before the installs) so the operator does not sit through the
install wait twice, and because half the chain is pointless without a sheet ID.

Steps 5/6 reuse the same sheet-driven asset checks as `iro event status`; a
sheet fetch failure during done-detection counts as "not done" (the step runs
and produces the real error message).

## Output

One line per step in the existing CLI style:

```
[1/9] .env … OK (already configured)
[2/9] install-tools … running
[4/9] cookies … SKIP (cookies.txt fresh, 2 days old)
```

After the preflight report, a fixed **Manual next steps** list with concrete
paths — the things no script can do:

1. Import the OBS collection: `<path to generated import JSON>` (Scene
   Collection → Import; do not move the file afterwards).
2. Import the Companion config: `<path to exported .companionconfig>`
   (Import / Export → Import). Launch Companion once first if this is its
   first run.
3. Sign into Tailscale in the Tailscale app (one-time).

## CLI

```
iro init [--browser NAME] [--skip-installs] [--force]
```

- `--browser` (default `firefox`) — forwarded to the cookies step. Firefox is
  the documented recommendation (Windows Chrome/Edge exports are blocked by
  app-bound encryption).
- `--force` — ignore done-detection, run every step.
- `--skip-installs` — skip steps 2–3 (machines without admin rights).

No further flags (YAGNI).

## Architecture

Follows the `event.py`/`preflight.py` pattern: pure, testable logic in a module;
a thin dispatch in `iro.py`.

- **`src/scripts/init_setup.py`** — the logic module:
  - step-plan construction (ordered list of step descriptors: number, label,
    done-check, gate, action),
  - done-detection per step as pure functions taking injected probes
    (which-lookups, file stats, env dict) so tests never touch the system,
  - gate classification (interactive pause vs non-TTY checkpoint-and-exit),
  - result formatting (the `[n/9] label … verdict` lines).
- **`src/iro.py`** — `init` becomes a top-level command in `route()` (own
  `kind: "init"`); the handler iterates the plan and invokes the existing
  one-shot/export functions (`oneshot(...)`, `export_companion(...)`) — no
  duplicated install/download logic. Frozen mode works unchanged: the one-shots
  already run in-process with the runtime-dir redirection from
  `_oneshot_extra()`.
- Docstring/`USAGE`, README quickstart, and the wiki onboarding page gain the
  new command.

## Error handling

- Hard error (step exit ≠ 0): stop, print the re-run hint, exit with that code.
- Done-detection probe failure (e.g. sheet unreachable): treat as "not done",
  run the step, let the step's own error surface.
- Gate in non-TTY mode: print instruction, exit 1.
- `--force` never bypasses gates — manual prerequisites stay manual.

## Testing

`tests/test_init.py`, stdlib-only like the rest of the suite:

- step-plan construction (order, numbering, flag effects: `--skip-installs`
  removes steps 2–3, `--force` disables skipping),
- done-detection per step against mocked probes (no installs, no downloads,
  no network),
- gate classification incl. non-TTY behavior,
- output formatting of skip/run/fail lines.

CI needs no new jobs; `tools/run-tests.py` picks the file up automatically.
