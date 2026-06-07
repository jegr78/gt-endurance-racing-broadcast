# Live Failure Visibility — Design

**Date:** 2026-06-07
**Status:** Approved

## Problem

When something fails during a live event, the people who need to know find out
last — or never:

- **Cookies expire mid-event.** Preflight checks cookie age *before* the event
  (WARN at 12 h), but during a 24 h race the cookies age while the relay runs.
  The next handover then fails with a yt-dlp error that only lands in
  `runtime/feed_X.log` — nobody is warned beforehand.
- **Feed state is invisible.** `/status` exposes a state for POV only; Feeds
  A/B report port/index/channel but not whether streamlink is actually serving
  or yt-dlp has been retrying for a minute. The director cannot distinguish
  "stream not live yet" from "URL is wrong" — the yt-dlp error text never
  leaves the log file.
- **Panel errors hide in the log box.** Failures (relay unreachable, sheet
  write failed) appear only in the 90 px monospace log at the bottom of
  `/panel` — below the fold on a tablet. A director under live pressure looks
  at the buttons, not the log.
- **Risky actions are unevenly guarded.** SET STINT confirms; RELOAD A/B/ALL
  (tears a running pull → dead air if on-air) does not. A double-press on NEXT
  advances two stints.
- **"Stint" means two things on one panel.** FEEDS row "SET STINT…" (feed
  index, interrupts pulls) vs. HUD row "STINT (HUD LABEL)" (display text,
  harmless). The wiki explains the difference; the panel itself does not.

This feature makes failures visible where the operator is looking, before they
go on air. Persona review (producer/director, non-technical) drove the scope.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Cookie staleness policy | Single-stage, same 12 h threshold as preflight (one source of truth). Age computed live on every `/status` call (mtime-based), not only at startup — a 24 h event must cross the threshold while the relay runs. Plus a one-time `WARN:` line at relay startup when already stale. |
| Where health state lives | In the `Feed` object, maintained by the existing `run()` loop (approach 1). A separate health-monitor thread (approach 2) and panel-side inference (approach 3) were rejected: the loop already knows its phases, and the panel cannot distinguish resolving from serving nor see yt-dlp errors. |
| Panel error surfaces | Hybrid: persistent **state banner** under the header for ongoing conditions (relay unreachable, sheet sync failed, cookies stale) — self-clearing, not dismissible — plus **toasts** (~6 s, top-right) for one-off action failures. The log box stays as history. |
| Feed health display | Both surfaces: header strip pills get state color + short text (`A S3 · LIVE` green, `B S4 · CONN` amber); a detail line in the FEEDS section shows state, duration, and a plain-language warning after 30 s connecting ("stream may not be live yet"). POV appears in the detail line only when not stopped. |
| Action guards | `confirm()` on RELOAD A/B/ALL; NEXT disabled for 3 s after a press (double-press guard). POV RELOAD/STOP stay unguarded (routine actions). |
| Stint terminology | FEEDS button renamed to `FEEDS → STINT…` (tag `correction`), prompt reworded to "Which stint is ON AIR right now? (e.g. 3)". HUD dropdown label `STINT (HUD LABEL)` → `STINT LABEL`. Companion buttons untouched (separate export artifact). |
| Preflight sheet check | New "Google Sheet" section: WARN when `IRO_SHEET_ID` is unset; with an ID, fetch the Schedule-tab CSV (10 s timeout) — PASS on CSV with ≥ 1 data row, FAIL on timeout/HTTP error/HTML body (the Google login page = the classic "not shared" case) with a sharing hint. |
| `/status` compatibility | The existing `"cookies": bool` key stays; `cookies_health` is added as a sibling. No new endpoints — the panel's existing 2 s polls carry everything. |

## Architecture

```
Feed.run() loop (existing)                       /status (every 2 s, panel poll)
  ├─ resolving via yt-dlp   → phase="connecting"   ├─ feeds.A/B: state, state_age_s,
  │    └─ failure           → last_error=<yt-dlp     │             last_error
  │                            stderr line>          ├─ pov: state (as today) + state_age_s
  ├─ streamlink serving     → phase="serving",      ├─ cookies_health: {present, age_h,
  │                            last_error=None      │                   stale}   ← computed
  └─ proc exits / advance   → phase="connecting"    │     on demand from cookies.txt mtime
                                                    ▼
                                            /panel JS (render only)
                                              ├─ state banner (relay/sync/cookies)
                                              ├─ toasts (action failures)
                                              ├─ strip pills + FEEDS health line
                                              └─ guards (confirm / 3 s disable)
```

### 1. Relay: feed health in the `Feed` object

`Feed` gains three attributes, updated exactly where the loop writes its log
lines today:

- `phase` — `"connecting"` (resolving / waiting for retry), `"serving"`
  (streamlink child alive), `"idle"` (no channel / empty schedule). Paused
  feeds (POV off) keep reporting `"stopped"` — the existing POV state
  derivation in `Relay.status()` is replaced by the new attributes with
  identical observable behavior.
- `phase_since` — epoch timestamp of the last phase change (set only when the
  phase actually changes, so duration accumulates across resolve retries).
- `last_error` — the last yt-dlp error line (today written only to
  `feed_X.log`). Cleared on successful serve. `resolve_hls()` returns
  `(url, error)` instead of `url` to carry the text (internal signature,
  three call sites; log writing stays as is).

### 2. Relay: cookie health + status contract

Pure helper (relay-local, stdlib only):

```python
COOKIE_MAX_AGE_H = 12   # keep in sync with preflight.py cookies_status()

def cookie_health(path, now=None, max_age_hours=COOKIE_MAX_AGE_H):
    -> {"present": bool, "age_h": float|None, "stale": bool}
```

Computed on demand in `Relay.status()` (an `os.path.getmtime` per call is
negligible at the panel's 2 s poll rate). When the relay runs without a
cookies file (`path` is None or the file is gone), the helper reports
`{"present": false, "age_h": null, "stale": false}` — running cookie-less is
a legitimate configuration (public streams), so it never raises the banner. The relay stays import-free /
standalone — the threshold is duplicated with a sync comment, same convention
as `detect_tailscale_ip`. At startup, after the existing cookies-file check,
print once when already stale:
`WARN: cookies.txt is N h old — cookies rotate; run 'iro cookies firefox' before the event.`

`/status` additions (the contract the panel renders):

```json
"feeds": { "A": { "...existing...": "...", "state": "serving",
                  "state_age_s": 5528.1, "last_error": null },
           "B": { "...": "...", "state": "connecting", "state_age_s": 47.3,
                  "last_error": "ERROR: This live event will begin in ..." } },
"pov":   { "...existing...": "...", "state_age_s": 12.0 },
"cookies_health": { "present": true, "age_h": 14.2, "stale": true }
```

### 3. Panel: banner, toasts, health line, guards, rename

All rendering-only — durations and staleness are computed by the relay so the
untested client JS stays thin.

- **Banner area** (`#banners`, directly under the header): rebuilt from the
  existing poll results each cycle; a banner shows while its condition holds
  and disappears when it resolves. Conditions: relay unreachable (relayPoll
  catch) — red; sheet sync failed (`/setup/data` `push:"failed"` or timer
  `sync.push:"failed"`) — red; cookies stale (`/status cookies_health.stale`)
  — amber, text `COOKIES N H OLD — next handover may fail · run 'iro cookies
  firefox' on the producer machine`.
- **Toasts**: stacked top-right, auto-hide ~6 s, for one-off action failures:
  `relayCall`/`timerCall` errors and catches, failed schedule/POV saves,
  failed HUD sets. Same messages keep going to the log box (history).
- **Feed health**: strip pills gain a state suffix and color class
  (`A S3 · LIVE` / `B S4 · CONN` / unchanged for idle); the FEEDS bus gains a
  health line per feed — `A · serving stint 3 (since 1:32:08)`, amber
  `B · connecting to stint 4 for 0:47 — stream may not be live yet` once
  `state_age_s` > 30 while connecting, appending the relay-reported
  `last_error` when present. POV joins the line only when not stopped.
- **Guards**: `confirm("Reconnect feed X — brief interruption if it is on
  air. Continue?")` on RELOAD A/B/ALL; NEXT disabled for 3 s after a press.
- **Rename**: FEEDS button `SET STINT…` → `FEEDS → STINT…`, tag `correction`,
  prompt "Which stint is ON AIR right now? (e.g. 3)"; HUD dropdown label →
  `STINT LABEL`.

### 4. Preflight: Google Sheet section

New section after "YouTube cookies". `iro preflight` loads `.env` first via
the same bounded-loader route `iro event status` uses; a direct script run
without the env degrades to WARN.

- `IRO_SHEET_ID` unset → WARN `IRO_SHEET_ID not set — fill it in .env`.
- Set → fetch the Schedule-tab gviz CSV (same URL form as the relay,
  10 s timeout):
  - PASS: CSV with ≥ 1 data row → `reachable (N rows in 'Schedule')`
  - FAIL: timeout / HTTP error / HTML body → `not readable — check sharing:
    Share → 'Anyone with the link: Viewer' (or no network)`
- `classify_sheet(...)` is a pure classifier separated from the fetch,
  testable offline like the existing classifiers.

### 5. Small message fixes

| Location | Today | New |
|---|---|---|
| `iro-feeds.py` bind failure (~1645) | `Could not bind the control server on … port ….` | append ` — port may already be in use: run 'iro preflight' or 'iro status' to see what holds it.` |
| `event.py` Tailscale WARN (~186) | `no tailnet IP — remote panel/tablet unreachable; sign in to Tailscale` | `Tailscale not connected — directors cannot reach the panel/tablet remotely; sign in to Tailscale` |
| `preflight.py` port in use (~323) | `in use — relay already running or a port conflict` | append `; 'iro status' shows whether that is the relay` |

## Testing

- **New `tests/test_health.py`**: `cookie_health()` (missing file / fresh /
  stale via tmp file with forced mtime), feed phase attributes and
  `Relay.status()` shape (Feed objects without running threads, attributes set
  directly — same pattern as the POV tests), `resolve_hls` error propagation.
- **`tests/test_preflight.py`**: `classify_sheet` cases (CSV ok, HTML body,
  fetch error, ID unset).
- **Existing suite stays green** — the POV state derivation moves into the
  Feed attributes with identical behavior; `test_pov.py` adjusted if needed.
- Panel JS has no test suite by convention — hence relay-side computation of
  `state_age_s`/`stale`. Manual check: `iro relay run` + browser.
- Wrap-up: `tools/lint.py`, `tools/run-tests.py`, `tools/build.py` (verify
  step).

## Out of scope (deliberate)

- Wiki/docs updates describing the new banner and health line — bundled into
  the director-onboarding and docs-consolidation features that follow.
- Companion button renames (separate export artifact; its labels already
  differ from the panel's).
- QR-code URL sharing, undo, multi-director presence — reviewed and dropped as
  overkill for this crew size.
