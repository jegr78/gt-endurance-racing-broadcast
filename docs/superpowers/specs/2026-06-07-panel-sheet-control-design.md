# Panel Sheet Control — Design

**Date:** 2026-06-07
**Status:** Approved

## Problem

During an event the stream director must edit the Google Sheet directly for
everything except the race timer: the Setup tab dropdowns (Stint label,
Streamer, Session, Race Control) and the feed/POV URLs (Schedule tab, POV tab).
The director panel (`/panel`) already controls feeds, scenes, graphics, timer,
and audio — sheet edits are the last reason to leave it. Sheet editing is
error-prone on a tablet and slower than a dropdown on the panel.

Goal: control all during-event sheet values from the panel. Pre-event
preparation (Round, Country, Teams 1–3, Configuration vocabulary, Assets)
stays in the sheet — that is a deliberate scope cut, not an omission.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Source of truth | Sheet stays authoritative. Panel writes go to the sheet via webhook; the relay applies an **optimistic echo** locally so the HUD updates instantly while the sheet catches up. Full relay-authoritative state (timer model) was rejected: humans edit the Setup tab and leave no timestamp, so newest-wins cannot arbitrate, and Overlay is formula-derived from Setup. |
| Setup fields on the panel | Stint, Streamer, Session, Race Control. Round/Country/Teams 1–3 are one-time pre-event prep — excluded. |
| Schedule editing scope | Full list: every row's name + URL editable, rows appendable. |
| Auto-reload after URL edit | Never. URL saves only write the sheet; feeds pick changes up on the existing RELOAD/NEXT (and POV RELOAD) actions. Matches the relay rule that a running feed is never torn off unrequested. |
| Free-text values | No. Setup dropdowns are strictly limited to the Configuration-tab vocabulary (same as the sheet's data validation). New streamers/messages are added to the Configuration tab; the panel reloads options continuously. |
| Webhook structure | One generalized Apps Script webhook (v2 of the timer script): one deployment, one key, one env var. |
| Env var | `IRO_SHEET_PUSH_URL` **replaces** `IRO_TIMER_PUSH_URL` — hard rename, no fallback (no production users yet). |

**Terminology guard:** the Setup-tab field "Stint" is the *HUD display label*
(e.g. "Stint 4", "Intro"). It has no relationship to the relay's *feed stint
index* (`/set/stint/<n>`, NEXT). Panel layout and docs keep the two separate.

## Architecture

```
Panel dropdown change
  └─ GET /setup/set/<field>/<value>          (relay)
       ├─ validate value against Configuration vocabulary
       ├─ set pending override → /hud/data shows it immediately (~0 s)
       ├─ POST webhook {action:"setup", fields:{...}}   (Apps Script writes Setup tab)
       └─ trigger one immediate Overlay poll (don't wait for the 5 s tick)
            └─ poll returns the new value → override confirmed & cleared
               (or 30 s timeout → override expires, HUD reverts to sheet truth,
                panel shows sync failed)
```

URL writes (Schedule rows, POV cell) have no local echo target — their effect
only materializes when a feed reloads from the sheet — so they are
**synchronous**: the relay answers only after the webhook confirmed, which
also removes any race between "save URL" and "press RELOAD".

### 1. Apps Script webhook v2

The documented timer script becomes a general sheet-write webhook. Same
deployment model (web app, execute as Me, access Anyone, `?key=` secret),
one paste-able file. The JSON payload gains an `action` discriminator:

| `action` | Payload | Writes |
|---|---|---|
| missing / `timer` | `end`, `duration`, `visible`, `remaining` (unchanged) | Timer tab (existing behavior) |
| `setup` | `{"fields": {"Race Control": "...", ...}}` | Setup tab: for each field, find the header cell by text (whitelist: `Stint`, `Streamer`, `Session`, `Race Control`; case-insensitive) and write the cell **below** it. No hardcoded coordinates. |
| `schedule` | `{"row": N, "url": "...", "name": "..."}` (url/name each optional) | Schedule tab row N (1-based). `N = lastRow+1` appends. Guard: `1 ≤ N ≤ lastRow+1`. |
| `pov` | `{"url": "..."}` | POV tab `A2` |

- All writes use `setNumberFormat('@')` (plain text, no auto-conversion) —
  same as the v1 timer writes.
- Response: `{"ok": true, "action": "<action>", "v": 2}`. The relay checks
  the `action` echo on non-timer writes: a v1 script answers `ok` without an
  echo, which the relay reports as "webhook script outdated — redeploy"
  instead of a silent false success.
- `setup` validation: all field names are checked against the whitelist and
  located before anything is written; an unknown/missing header aborts the
  whole write and names the header in the error response.
- Setup cells carry the sheet's own dropdown data validation; the panel only
  offers vocabulary values, so webhook writes never trip it.

Redeploy instruction (documented prominently): **Manage deployments → Edit →
New version** keeps the `/exec` URL stable — no `.env` change needed when
updating the script.

### 2. Relay (`src/relay/iro-feeds.py`)

**Vocabulary for free:** `HudSource.refresh()` already fetches the
Configuration tab (for brands). The parser additionally extracts the columns
`Stints`, `Streamers`, `Session`, `Race Control` as option lists — no extra
network fetch, same last-good caching.

**Optimistic echo:** `HudSource` gains per-field pending overrides
`{value, expires}`. `data()` lays overrides over the sheet-derived data. An
override clears itself when the Overlay poll returns the same value
(confirmed) or after a 30 s timeout (webhook down → HUD reverts to sheet
truth). After each push the relay triggers one immediate poll instead of
waiting for the 5 s tick. Time is injectable (`now=` parameter) for tests.

**Shared push helper:** the webhook POST + `{"ok": true}` check +
`push_status` bookkeeping is extracted from `TimerStore` into a small shared
helper used by both the timer and the new writes (no duplication).

**New endpoints:**

| Endpoint | Method | Behavior |
|---|---|---|
| `/setup/data` | GET | current field values (overrides applied) + option lists + pending/push status |
| `/setup/set/<field>/<value>` | GET (URL-encoded value) | set one field; strict vocabulary validation; async-optimistic. GET so Companion buttons (e.g. Race Control presets) can call it directly. |
| `/setup/clear/racecontrol` | GET | empty Race Control (empty = HUD hides the banner) |
| `/schedule/data` | GET | all rows (index, name, url) + which row is live on Feed A/B + sheet health |
| `/schedule/set` | POST (JSON `{row, url, name}`) | write/append a row; synchronous (answers after webhook confirm) |
| `/pov/set` | POST (JSON `{url}`) | write POV `A2`; synchronous; no feed action |

The control server gains a `do_POST` handler (currently GET-only).
Field keys map `stint|streamer|session|racecontrol` → HUD data keys
(`stint`, `streamer`, `session`, `raceControl`) → Setup headers (`Stint`,
`Streamer`, `Session`, `Race Control`).

**ScheduleSource:** `_parse_csv` additionally captures the name column
(heuristic: the column right of the detected URL column) so `/schedule/data`
can show names. `items` (URL list) and all feed behavior stay unchanged —
URL edits take effect on RELOAD/NEXT exactly as today.

### 3. Panel UI (`src/director/director-panel.html`)

**SETUP row** (between FEEDS and SCN·VIS): four dropdowns — STINT, STREAMER,
SESSION, RACE CONTROL — plus a CLEAR RC button.

- Options + current values come from `/setup/data`, folded into the existing
  2 s status poll.
- A change fires immediately (`onchange` → `/setup/set/…`) — the same
  semantics as the sheet dropdowns today. The field shows a pending state
  (amber outline) until the sheet confirms, red + message on sync failure.
- While a dropdown is open/focused the poll does not overwrite its selection.

**URLS section**: a collapsible `<details>` block below the rows (collapsed
by default — used less often and taller than a row):

- Schedule table: one line per stint — number, `A`/`B` badge when live on a
  feed, name input, URL input, per-row SAVE (synchronous: spinner in the
  button, then a green check), `+ ADD ROW` at the bottom. After saving an
  on-air row: hint "applies on RELOAD A/B / NEXT" — never an auto-reload.
- POV line: one URL input + SAVE; hint "applies on POV RELOAD".
- Inputs the user has edited but not saved are marked dirty; the poll leaves
  them alone.

**Status strip:** gains a `setup sync: ok / failed / no webhook` indicator
analogous to the timer line.

### 4. Error handling

| Case | Behavior |
|---|---|
| No push URL in `.env` | `/setup/set` and URL writes answer `{"error": "webhook not configured"}`; panel renders SETUP row + URLS read-only with a notice. Read endpoints keep working. |
| Webhook down / no `ok` | Setup fields: override expires after 30 s → HUD shows sheet truth again; panel `sync: failed`. URL saves: synchronous error at the button. Director fallback: sheet dropdowns as before. |
| v1 script still deployed | Missing `action` echo → "webhook script outdated — redeploy", not a false success. |
| Setup header renamed | Apps Script names the missing header in its response; panel surfaces it. |
| Configuration tab unreachable | Dropdowns keep last-good options (existing HudSource cache). |
| Value not in vocabulary | Server rejects (strict-dropdown decision) — also guards Companion/curl calls against typos. |

The unauthenticated-control-server trust model is unchanged: the tailnet is
the boundary; these endpoints add sheet-write capability inside it, the
webhook key never leaves the relay.

### 5. Tests (repo style: stdlib, pure logic)

New `tests/test_setup.py` + extensions to `tests/test_hud.py`:

- Vocabulary parsing from Configuration CSV (column discovery, blank cells,
  missing column).
- Override logic: apply → confirmed-by-poll → cleared; timeout expiry;
  injectable time, no sleeps.
- Field mapping + validation (unknown field / non-vocabulary value rejected;
  empty Race Control allowed via clear).
- Payload builders for `setup` / `schedule` / `pov` including the
  `action`-echo check (v1 response → "outdated").
- ScheduleSource parser: URL+name pairs, name-column heuristic.
- Router: new GET paths + `do_POST` dispatch.

The Apps Script itself is not testable in-repo; it stays minimal and the
payload contracts are tested relay-side.

### 6. Env var rename (hard, no fallback)

`IRO_TIMER_PUSH_URL` → `IRO_SHEET_PUSH_URL` everywhere that is alive
(no production users yet). Per the repo rule, the full grep sweep — the
rename touches: `src/relay/iro-feeds.py`, `src/iro.py`,
`src/scripts/event.py` (event-readiness `.env` check),
`src/director/director-panel.html`, `tests/test_event.py`, `.env.example`,
`CLAUDE.md`, `src/docs/README_SETUP.md`,
`src/docs/IRO_Broadcast_Setup_Guide.md`, `src/docs/wiki/Race-Timer.md`,
`src/docs/wiki/Configuration.md`, `src/docs/wiki/Set-up-the-broadcast-PC.md`.
Historical specs/plans under `docs/superpowers/` are records and stay
untouched.

### 7. Docs & deployment

- **Wiki:** the webhook section moves out of `Race-Timer.md` into a new
  `Sheet-Webhook.md` (v2 script listing, deploy guide incl. the
  "Edit deployment → New version keeps the URL" note); `Race-Timer.md` links
  there. `Director-Panel` / `Run-an-event` pages document the new controls,
  keeping *Setup fields = HUD display* clearly separate from *feed control =
  NEXT/RELOAD*. Mechanism only — no crew procedure is invented.
- **`.env.example`:** `IRO_SHEET_PUSH_URL` with a comment that it powers both
  the timer sync and the panel's sheet controls.
- **Companion:** no new buttons in this feature, but `/setup/set/...` is
  deliberately GET so Race-Control preset buttons can be added later.

## Out of scope

- Round / Country / Teams 1–3 / Configuration vocabulary / Assets editing
  (pre-event prep stays in the sheet).
- Free-text field values.
- Any auto-reload of feeds after URL changes.
- Companion buttons for the new endpoints.
- Auth on the control server (unchanged trust model).
