# One-command producer takeover

## Problem

An endurance race is split across producers (12 h = 2, 24 h = 3); producer **B**
takes over from **A** mid-race. Today that handover is piecemeal — B runs several
commands and has to find the current stint by hand:

| Element | Today |
| --- | --- |
| Race timer | carries automatically — Sheet "newest-wins" on B's relay start (needs `SHEET_PUSH_URL`) |
| Chat | `racecast chat pull <A-ip>` |
| Current stint | B reads it off the panel, then `racecast event start --stint N` |
| Profile / cookies / assets | B's own, set up before the event (the #185 pre-flight gate already checks these) |
| Broadcast output (OBS stream key) | crew procedure — A stops streaming, B starts |

There is no single "take over the broadcast" command, and the current-stint step
is manual and error-prone.

## Goal

`racecast event takeover <A-ip> [--stint N] [--qualifying] [--port P] [--force]`
— one command on B's machine that:

1. reads A's live state over the tailnet and derives the on-air **stint + mode**,
2. **guards against a league mismatch** — aborts if A's league (`SHEET_ID`) is not
   B's active league, unless `--force`,
3. **warns if the timer will not carry over** (B has no `SHEET_PUSH_URL`),
4. pulls A's **chat** history (best-effort),
5. brings B's stack up at that stint via the existing `event start` path (which
   adopts the Sheet timer and runs the #185 pre-flight gate),
6. prints a clear "you are set to stint N — go on air per your crew procedure"
   note.

It is also a one-click action in the **Control Center** Home view — pick A from a
**tailnet-device dropdown** (read live from `tailscale status`, so no typing IPs)
and hit "Take over" — so a GUI-driven producer gets the same handover.

Non-goals (stated, not invented): the **broadcast-output switch** (stream key) is
crew procedure, never automated; cookies/assets are B-local and pre-event (the
gate checks them); profile selection stays explicit (B's active profile is the
league — `--profile` / `profile use` as usual).

## Where "current stint" comes from

The relay already knows the on-air feed: `live_feed()` = the feed on the lower
(earlier) stint index; the other pre-warms the next stint. So:

- **Primary:** B fetches A's `/status` and reads the live feed's stint. `/status`
  gains a top-level `live` block so B never has to guess from two feed numbers:
  `out["live"] = {"feed": <"A"|"B">, "stint": <idx+1>, "mode": <"race"|"qualifying">}`.
- **Fallback:** if A is unreachable (already shut down) **or** `--stint N` is
  given, use the explicit/override stint. `--stint` always wins over A's value.
- The **timer** is independent of A — it comes from the shared Sheet, so timer
  continuity does not depend on A still running.

## Components

### 1. `/status` `live` + league key — `src/relay/racecast-feeds.py`

`status()` adds `out["live"] = {"feed", "stint", "mode"}` from `live_feed()` and
that feed's index, plus a top-level `out["league"] = {"sheet_id": <A's SHEET_ID>}`
so B can verify it is taking over the same league. (`SHEET_ID` is already the
league's identity and the tailnet is the trust boundary, like the stream URLs
`/status` already exposes.) The relay receives its `SHEET_ID` (it builds the CSV
URLs from it); pass it to `Relay` so `status()` can surface it. Version-skew safe:
an older relay lacks both → takeover falls back to `--stint` and skips the league
guard (with a note).

### 2. `takeover_plan(status, stint_override=None, qualifying_flag=False)` — pure

Decides the bring-up parameters from A's `/status` (a dict or `None` when A was
unreachable) plus the operator overrides. Returns
`{"stint": int|None, "qualifying": bool, "source": "relay"|"override"|"sheet"}`.
Rules:

- `stint_override` set → use it (`source="override"`), `qualifying` = the flag.
- else A reachable with a `live` block → `stint` = `live.stint`,
  `qualifying` = `live.mode == "qualifying"` (`source="relay"`).
- else (A unreachable, no override) → `stint=None` (`source="sheet"`): the CLI
  turns this into a clear error asking for `--stint N` (we never silently start
  at stint 1 mid-race).
- `--qualifying` flag forces qualifying regardless of A.

Pure → unit-tested (all four branches + override-beats-relay + qualifying).

### 2b. `league_guard(a_sheet_id, b_sheet_id, force)` — pure

Returns a block message (string) or `None`. Blocks when both ids are present and
differ and `not force` ("A is league X, you are league Y — wrong profile? re-run
with --force"). Returns `None` (allow) when they match, when `force`, or when
either id is unknown (older relay / unset — allow but the CLI notes it could not
verify). Pure → unit-tested.

### 3. CLI `event takeover` — `src/racecast.py`

`racecast event takeover <ip> [--stint N] [--qualifying] [--port P] [--force]`:

1. fetch `http://<ip>:<port>/status` (default port = `RELAY_PORT`, short timeout;
   any failure → treat A as unreachable, not fatal).
2. **league guard**: `league_guard(status.league.sheet_id, RACECAST_SHEET_ID, force)`
   — a non-None message aborts (exit 1) unless `--force`.
3. **timer warning**: if B has no `RACECAST_SHEET_PUSH_URL`, print a prominent
   "the race timer will NOT carry over — set SHEET_PUSH_URL in the profile" warning
   (does not abort).
4. `plan = takeover_plan(status, stint_override, qualifying_flag)`.
5. if `plan["stint"] is None` → exit with a clear message: A unreachable and no
   `--stint` given; re-run with `--stint N` (read it off A's panel).
6. `chat_pull(ip, port)` — best-effort (a chat failure must not abort the takeover).
7. delegate to `event_start` with the derived `--stint`/`--qualifying` (so the
   pre-flight gate, Tailscale/Discord/OBS/relay/Companion bring-up, Sheet-timer
   adoption, and director URLs all come for free).
8. print the "set to stint N; switch the broadcast output per your crew procedure"
   note.

`takeover` is thin orchestration over `league_guard` + `takeover_plan` +
`chat_pull` + `event_start`.

### 4. Tailnet peer list — `src/scripts/tailscale.py`

So the Control Center can offer a **device dropdown instead of a typed IP** (fewer
typos), add:

- `parse_tailscale_peers(output)` — pure → `[{"hostname", "ip", "online", "os"}]`
  from the `Peer` map of `tailscale status --json` (first CGNAT IPv4 per peer;
  skips peers with no CGNAT IP). Reuses the same JSON the existing
  `parse_tailscale_*` helpers already read. Unit-tested with a fixture (IPs in the
  `100.64.0.0/10` test range, never a real address — CLAUDE.md).
- `tailscale_peers(timeout=3)` — runs the CLI (same discovery/invocation as
  `tailscale_backend`) and returns `parse_tailscale_peers(...)`, or `[]` on any
  failure (CLI missing / tailnet down).

### 5. Control Center — `src/ui/` + `src/racecast_ui.py`

The Home view gains a small **Take over** control next to Start/Stop event: a
**device dropdown** for A (populated from the tailnet peers, label
`hostname — ip`, online peers first; an empty/"manual entry" option keeps free
text so it still works if peers can't be read) + a "Take over" button. The button
runs a new op `racecast event takeover <ip>` via the existing job-runner that
backs Start/Stop event; the existing `stint` field is the optional `--stint`
override. A league-mismatch / unreachable error surfaces in the job console like
any other op.

- new op in `ui_ops.py` → `["event", "takeover", <ip>]` (+ `--stint` when set);
- `GET /api/tailscale-peers` route in `ui_server.py` → `ctx["tailscale_peers"]()`
  (provider added in `racecast_ui.py`, wrapping `tailscale.tailscale_peers`);
- the dropdown + button + wiring in `control-center.html`.

## Testing

- `takeover_plan`: A-reachable race, A-reachable qualifying, A-unreachable+override,
  A-unreachable+no-override (→ stint None), override-beats-relay, `--qualifying`
  forces mode.
- `league_guard`: match → None; mismatch → message; mismatch+force → None;
  either id missing → None (cannot verify).
- `/status` `live` block + `league.sheet_id` reported (test_health/test_pov).
- CLI: `event takeover <ip>` parses ip/--stint/--qualifying/--port/--force;
  league mismatch without `--force` exits with the guard message; no
  `SHEET_PUSH_URL` prints the timer warning; unreachable-A + no-stint exits with
  the guidance message; the reachable+matching path calls `event_start` with the
  derived args (stub `event_start`/fetch, like the #185 gate tests).
- `parse_tailscale_peers`: fixture JSON (test IPs in `100.64.0.0/10`) → hostname/
  ip/online/os; peers without a CGNAT IP skipped; malformed/empty → `[]`.
- Control Center: the takeover op maps to `["event","takeover", ip]` (+ optional
  stint), the `/api/tailscale-peers` route wraps the provider, and both invoke
  correctly (test_ui_ops / test_ui_server).

The live bring-up (subprocesses) is not unit-tested; its decision logic is fully
covered by `takeover_plan` + `league_guard` + the routing tests, mirroring the
existing event-start tests.

## UI screenshots (CLAUDE.md hard rule)

The Home view gains a visible Take-over control, so `cc-home.png` changes and is
re-captured from a local dev build in the same change.

## Out of scope / explicit

- The broadcast-output (stream-key) switch — crew procedure (CLAUDE.md: never
  invent broadcast procedure).
- Transferring cookies/assets — B-local, pre-event; the #185 gate already blocks a
  takeover that is missing SHEET_ID/graphics and warns on stale cookies.
- Cross-machine profile transfer — that is `profile export/import`, a pre-event step.
