# Docs Restructure — Control Center First — Design

**Date:** 2026-06-08
**Status:** Approved

## Problem

The operator documentation (wiki + shipped guides + README + cheat sheet) is
**terminal-first**: `Set-up-the-broadcast-PC` and `Run-an-event` lead with `iro`
commands; the Control Center (`iro-ui`) appears only as a post-Phase-3 "Prefer a
UI?" aside. Now that the Control Center is a complete, shipped first-class
entrypoint, the docs should lead with it and keep the CLI as a documented
alternative.

## Decisions (settled with the user)

| Question | Decision |
|---|---|
| Scope | **Full restructure incl. cheat-sheet rework.** Wiki (new hub page + reframed Set-up/Run/Home/Sidebar) + the two shipped operator guides (`README_SETUP.md`, `IRO_Broadcast_Setup_Guide.md`, also rendered in the Help panel) + repo `README.md` (light) + `IRO_cheat_sheets.html` (Control Center quick-reference). |
| CLI positioning | **Inline alternative line** under each UI step: `CLI alternative: \`iro …\``. Both visible, scannable, renders everywhere (no `<details>`). |
| Screenshots | **Every Control Center view**: Home, Setup (wizard), Preflight, Relay, Static Streams, Apps, Tools, Assets, Settings, Logs, Help. Captured from a **sanitized demo instance** (fake `.env`, neutral `/tmp` path, services stopped); every shot reviewed for secrets/machine-paths before commit (public wiki). |
| CLI docs retention | The CLI stays fully documented (it is the Linux path and the power-user/maintainer path). Reframed as the alternative, never removed. |

## Principle

Every operator onboarding/operation step reads: **"Open the Control Center →
click X."** with `CLI alternative: \`iro …\`` directly beneath. Technical-reference
wiki pages (Architecture, Relay, Timer, OBS, Companion, Configuration, Static,
Build) keep their current developer-facing framing. The repo `README.md` keeps
its full CLI command reference (maintainer-facing) but its "Get started" leads
with the Control Center.

## Changes

### New
- `src/docs/wiki/Control-Center.md` — the hub page. What it is; how to launch
  (double-click `iro-ui` / `iro-ui.app`, Linux `iro ui`); single-instance + Quit
  behaviour; a tour of every view with a screenshot each; the localhost-only
  security note; pointer to Set-up and Run-an-event.
- `src/docs/wiki/images/cc-*.png` — one screenshot per view (sanitized).

### Reframed (UI-first, CLI inline alternative)
- `src/docs/wiki/Home.md` — "Get the tool" → download + double-click `iro-ui`;
  add Control Center to "Pick your path".
- `src/docs/wiki/Set-up-the-broadcast-PC.md` — lead each step with the Setup
  wizard / the relevant CC view; CLI alternative beneath.
- `src/docs/wiki/Run-an-event.md` — lead with the CC Home dashboard + one-click
  service control; CLI alternative beneath.
- `src/docs/wiki/_Sidebar.md` — add **Control Center** as the first "For
  operators" entry.
- `src/docs/README_SETUP.md` + `src/docs/IRO_Broadcast_Setup_Guide.md` — same
  UI-first reframe (these render in the Help panel too).
- `README.md` (root) — "Get started" leads with the Control Center; CLI command
  reference retained below.
- `src/docs/IRO_cheat_sheets.html` — add a Control Center quick-reference
  section/column; keep the CLI cheat columns.

### Untouched
- Technical-reference wiki pages (Architecture, Relay-Mode, Race-Timer,
  Sheet-Webhook, OBS-Setup, Companion, Configuration, Static-Mode,
  Build-and-maintenance). They may gain a one-line "controllable from the
  Control Center" pointer where natural, but keep their framing.
- Director pages (already UI-forward).

## Screenshot capture (sanitized)

- Run the shipped `iro` binary from a throwaway dir (e.g. `/tmp/iro-cc-demo/`)
  with a fake `.env` (`IRO_SHEET_ID=DEMO…`, no push URL, no real secrets), on a
  non-default port, services stopped — neutral state, no username/sheet/tailnet
  leakage. Paths shown are `/tmp/iro-cc-demo/…` (no PII).
- Capture each view full-view via Playwright. **Review every PNG** for: real
  sheet IDs, Tailscale IPs (`100.64.x.x`), OBS-ws passwords, `/Users/<name>/`
  paths, stream URLs. Settings values must render masked (verify). Crop/redo any
  leak before commit.
- Store as `src/docs/wiki/images/cc-<view>.png`; `sync-wiki.py` publishes the
  `images/` dir automatically. Reference as `![…](images/cc-<view>.png)`.

## House rules

English-only; describe **mechanism** only — no invented broadcast procedure;
no secrets/machine-paths/real IPs in committed images or text; wiki is
generated from `src/docs/wiki/` (never hand-edit on GitHub) and published with
`tools/sync-wiki.py` (maintainer runs it — out of scope here).

## Out of scope

- Running `sync-wiki.py` (publishing) — the maintainer does that after review.
- Restructuring the technical-reference pages' content.
- Video/GIF captures.
