# Producer Schedule + one-click takeover from the Control Center Home

**Date:** 2026-06-23
**Status:** Design — approved for planning

## Problem

Producer takeover today is too manual. To hand off between producers, the
incoming producer (B) has to know A's MagicDNS host, type it into the Home-view
takeover field, toggle Funnel, and trigger. There is no shared, league-level view
of *who produces which part* and *from which machine* — that knowledge lives in
people's heads or a side channel.

We want the league owner/admin to maintain a **producer schedule per event**
directly in the league's Google Sheet, and the Control Center to render it on the
Home view so a producer can trigger a takeover with one click against the right
machine — while being prevented from "taking over from themselves".

## Goals

- A read-only **`Producer`** tab in the league Sheet: `Part | Producer | MagicDNS`,
  maintained by the league owner/admin per event.
- The Control Center **Home view** shows this schedule.
- Each row has a **Take over** action that runs the existing
  `event takeover <MagicDNS> --funnel` op.
- A producer **cannot trigger a takeover against their own machine** (MagicDNS
  self-match) — that row's action is disabled.
- **Duplicates are first-class:** one producer may do two consecutive parts → two
  rows with the same MagicDNS. Every row renders independently.

## Non-goals (YAGNI)

- No new relay endpoint. The schedule is read directly by the Control Center from
  the active profile's `SHEET_ID` (the takeover happens *before* B's relay is
  running, so it must not depend on a running relay).
- No write-back / editing of the Producer tab from the UI — it is admin-owned,
  read-only.
- No new CLI command — the takeover reuses the existing `event-takeover` op.
- No "which part is live" correlation. The operator picks the row of the machine
  they are taking over from; the on-air stint is auto-derived from A's status by
  the existing takeover path.
- No Tailnet takeover variant from the schedule. The `MagicDNS` column always
  drives a **Funnel** takeover (one code path; see Decisions).

## Key decisions (resolved during brainstorming)

1. **Takeover path: always Funnel.** A row's Take-over runs
   `event takeover <MagicDNS> --funnel`. One code path, consistent with the
   `MagicDNS` column. Precondition (same as today's Funnel takeover): A's Funnel is
   on, and B's active profile carries the league `CONSOLE_SECRET` (identical across
   the league) for the step-up. The secret is read server-side by the CLI, never
   from the browser — unchanged from commit e57ff5f.
2. **Self-match: exact FQDN** (case-insensitive, trailing dot ignored). The admin
   must enter the full `*.ts.net` name in the sheet. The Home card displays the
   machine's own FQDN ("Your MagicDNS: …") so the admin/operator knows the exact
   string to enter.
3. **Self-name unknown (Tailscale off/logged out): lock everything.** Without our
   own identity the self-guard can't apply, so **all** Take-over buttons are
   disabled with a hint to connect Tailscale.
4. **Header required, no positional fallback.** Unlike Schedule/Crew, this new tab
   demands a recognizable header row (`Part | Producer | MagicDNS`). Missing/
   unrecognized headers → empty list → the card hides itself (graceful degrade).
5. **Data source: Control Center reads the Sheet directly** via `http_util` (the
   covered side), on demand (not in the 3 s status poll), with a short cache.

## Architecture

### A. Data & parsing

- **Header constants** (new, alongside the existing `SCHEDULE_*`/`CREW_*` sets):
  - `PRODUCER_PART_HEADERS = ("part",)`
  - `PRODUCER_PRODUCER_HEADERS = ("producer",)`
  - `PRODUCER_MAGICDNS_HEADERS = ("magicdns", "magic-dns", "magicdns name", "magic dns")`

- **Pure parser** `parse_producer_rows(text)` — unit-testable, no I/O:
  - Parses the gviz CSV.
  - Locates columns case-insensitively against the header constants. **Header
    required**: if any of the three columns is not found, return `[]`.
  - Returns `[(part, producer, magicdns), …]` preserving order and **duplicates**.
  - Trims cells; rows with an empty MagicDNS are kept (rendered, action disabled).

- **Self-match helper** `producer_row_is_self(magicdns, self_name)` — pure:
  - Returns `False` when `self_name` is empty/None.
  - Compares case-insensitively, stripping a trailing `.` from both sides; **exact
    FQDN** equality only.

  Placement: these pure helpers live in a small module so they're importable by
  tests without importing the relay. Candidate: extend `src/scripts/tailscale.py`
  for the self-match (it already owns `detect_magicdns_name`/`parse_magicdns_name`),
  and put `parse_producer_rows` in a new `src/scripts/producer.py` (pure, stdlib
  `csv`). The planner picks the exact home; the constraint is *pure + unit-tested +
  no relay import*.

- **Status provider** `producer_schedule_data()` in `src/racecast.py`:
  - Builds the gviz CSV URL from the **active profile** `SHEET_ID`:
    `https://docs.google.com/spreadsheets/d/<SHEET_ID>/gviz/tq?tqx=out:csv&sheet=Producer`
    (`PRODUCER_TAB = "Producer"` constant).
  - Fetches via `http_util` (covered side — required by the repo's outbound-HTTP
    rule; the relay's dependency-light exception does not apply here).
  - Calls `parse_producer_rows`, computes the own FQDN once via
    `detect_magicdns_name()`, tags each row `self: bool` via
    `producer_row_is_self`.
  - Returns:
    ```json
    {
      "rows": [{"part": "1", "producer": "Alice",
                "magicdns": "producer-a.tailXXXX.ts.net", "self": false}, …],
      "self_name": "producer-b.tailXXXX.ts.net",
      "self_known": true
    }
    ```
  - Network/parse failure or missing tab → `{"rows": [], "self_name": …,
    "self_known": …}` (never raises; the card hides).

### B. UI server route

- New **on-demand** GET endpoint `/api/producer-schedule` in `src/ui/ui_server.py`,
  wired to `ctx["producer_schedule"]` (the provider above). Not part of the 3 s
  `/api/status` poll.
- Short server-side cache (~30 s) to avoid hammering the Sheet on repeated Home
  loads; a manual refresh in the UI bypasses/refreshes it.

### C. Home view (`src/ui/control-center.html`)

- New section `#home-producers` beneath the readiness tiles.
- Card header: **"Your MagicDNS: `<self_name>`"**, or "— (Tailscale offline)" when
  `self_known` is false.
- Table columns: **Part | Producer | MagicDNS | (action)**.
- Per row, a **Take over** button:
  - Disabled + **"you"** badge when `row.self` is true.
  - Disabled when `magicdns` is empty.
  - Disabled for **all** rows when `self_known` is false; the card shows a hint
    "Connect Tailscale to take over from the schedule".
- The card renders only when `rows.length >= 1`; otherwise it is hidden.
- Fetched when the Home view is shown + on a manual refresh control.

### D. Takeover wiring

- The Take-over button calls the **existing** op:
  `op('event-takeover', true, {ip: <magicdns>, funnel: true})`
  → argv `["event", "takeover", "<magicdns>", "--funnel"]`.
- Confirmation modal as today. The on-air stint is auto-derived from A's
  `/console/takeover/status` (no `--stint` passed from the row).
- `_ip_arg`'s charset (`^[A-Za-z0-9.\-]{1,253}\Z`) already accepts MagicDNS hosts —
  no validator change.

## Error handling / edge cases

- **Missing `Producer` tab / no headers** → empty `rows`, card hidden. No error
  surfaced (graceful, like Crew).
- **Tailscale off** → `self_known=false` → all actions locked + hint.
- **Empty MagicDNS cell** → row shown, its action disabled.
- **Duplicate rows (same producer/MagicDNS)** → each row rendered and evaluated
  independently; both self-rows disabled.
- **Funnel preconditions unmet at runtime** (A's Funnel off / wrong secret) → the
  existing `event takeover --funnel` path already fails loudly (HTTP 403 / network
  fallback). No new handling here; the job output streams the error as today.

## Testing

- **`tests/test_producer.py`** (new, pure):
  - `parse_producer_rows`: happy path; header synonyms (`magic-dns`, `magicdns name`);
    **missing header → []**; reordered columns located by header; duplicate rows
    preserved; empty MagicDNS cell preserved; blank/whitespace trimming.
  - `producer_row_is_self`: exact FQDN match (case-insensitive, trailing dot);
    short-name **no** match (exact-FQDN policy); empty `self_name` → False.
- **`tests/test_ui_server.py`**: `/api/producer-schedule` route returns the provider
  payload; cache behavior smoke.
- `tests/test_ui_ops.py` already covers `event-takeover --funnel` (commit e57ff5f);
  no change needed.
- Full suite via `python3 tools/run-tests.py`; `python3 tools/lint.py` after Python
  edits.

## Docs / wiki (same-change requirements)

- **Home view changed → regenerate the matching `cc-*.png`** wiki screenshot in the
  same change (repo hard-rule), captured from a local dev build.
- Add a short note to the Sheet-setup / `Sheet-Webhook` wiki page describing the
  `Producer` tab (`Part | Producer | MagicDNS`, full `*.ts.net` FQDN required,
  read-only/admin-owned, duplicates allowed).

## Out of scope / future

- Exposing the producer schedule on `/console` (remote directors) — only the local
  Control Center Home view is in scope now.
- Tailnet (non-Funnel) takeover from the schedule.
- Auto-correlating the schedule with the live on-air part.
