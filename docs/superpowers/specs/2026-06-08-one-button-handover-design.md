# One-Button Handover — Design

**Date:** 2026-06-08
**Status:** Approved (design), ready for implementation planning
**Scope:** Make the relay the single source of truth for feed state and have it
reflect that state into OBS, so a driver-swap handover is **one button (NEXT)** with
**no operator awareness of Feed A vs Feed B and no special cases** — including the
common "start with one link, add the second mid-event" workflow.

---

## 1. Goal

Today's A/B "ping-pong" (Feed A = odd stints on port 53001, Feed B = even stints on
53002; the off-air feed pre-warms the next stint, the director cuts between them) is
correct but exposes A/B to the operator and has a sharp edge: when the schedule
starts with **one** link, both feeds clamp to the same stint (`A.idx == B.idx`), so
the first `/next` advances the **on-air** feed and the documented "cut to the *other*
feed" rule is off-by-one until it self-corrects. The team wants this **simple for
everyone, no exception / workaround / per-operator procedure**.

A/B is **not the goal** — it is only the technique that keeps the on-air OBS media
source's URL constant (OBS shows a black reconnect when a media source URL changes).
We keep that benefit (and pre-warm + fallback) but **hide A/B entirely behind the
relay** and remove the cold-start special case at its root.

**Target operator experience at a handover, every time, identical:**
1. Cut to **Splitscreen**.
2. Press **NEXT**. Done.

The relay advances the feed, makes the new commentator visible in the **Stint**
scene, switches the audio, and cuts the program to **Stint** — over obs-websocket.

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| Operator model | **One scene + one button.** Operator never thinks about A/B. |
| Who orchestrates | **The relay** (single source of truth for feed state), via the existing `src/scripts/obs_ws.py` client. Companion + panel just call `/next`. |
| Cut on NEXT | **NEXT auto-cuts** Splitscreen → Stint (program scene), not only feed routing. |
| Audio on NEXT | **NEXT switches audio**: new live feed unmuted, off-air feed muted. POV + Discord stay separate/manual. |
| Splitscreen audio | **Only the outgoing commentator audible** during the split (falls out naturally — the off-air feed is muted throughout pre-warm; NEXT unmutes the new feed at the cut). |
| Splitscreen video | **Unchanged** — both feeds side by side. |
| Cold-start root fix | Off-air feed **idles on its own slot** (next stint) and shows a **black tile** when no link yet — instead of clamping onto the live feed's stint. Makes the ping-pong invariant. |
| obs-websocket failure | **Both:** `preflight` / `event status` verify the connection up-front (mandatory check), **and** a runtime break-glass fallback (manual panel/Companion buttons stay; `/status` shows which feed is live). |
| Instant panel availability | **Included as an optional, bounded piece** (§7): a successful panel schedule-write injects the row into the relay's in-memory schedule immediately, so the off-air feed adopts it in ~3 s instead of waiting up to one poll. |
| Out of scope | POV feed, Discord audio, HUD/timer/graphics, yt-dlp/streamlink pull pipeline — unchanged. |

## 3. The two coupled changes

The simplification needs **both**. Change 1 alone keeps A/B exposed; change 2 alone
still flashes on cold-start. Together: simple **and** robust.

### Change 1 — Invariant relay index (the actual "other approach")

The cold-start off-by-one comes from clamping: `stint_start_indices(1, 1) → (0, 0)`
(`src/relay/iro-feeds.py:736-742`) and `current_channel()` doing
`i = min(self.idx, len(sched)-1)` (`iro-feeds.py:1114`). Both feeds end up on the
same stint, creating the `A.idx == B.idx` tie that `next_auto()` resolves to the
on-air feed.

**New behavior:** the off-air feed sits on **its own slot** (the next stint) and
**idles** (serves nothing → black tile in the split) when that slot has no link yet,
rather than duplicating the live stint. This yields the universal invariant:

> **New live feed = the feed that `/next` did *not* advance** — always: full
> schedule, single link, or mid-event takeover.

This holds through the last real handover. Pressing `/next` *past* the last stint drives
both feeds to the idle sentinel (a benign tie); the cut guard — and the fact that the
reflection itself only fires when the incoming feed is `serving` — ensure no wrong-feed
program cut and no on-air visibility flip in that case.

Consequences:
- No `A.idx == B.idx` tie → no off-by-one → no special case.
- No on-air flash: the new live feed is always the pre-warmed (or visibly-black)
  off-air feed, never the on-air feed changing its own URL.
- **Enables the auto-pickup of late links** (see §3.3): an idling feed re-reads the
  schedule every 3 s; a clamped feed is busy in `proc.wait()` and would not.

Implementation notes for the plan: feeds must treat `idx >= len(schedule)` as **idle**
(return `None` from `current_channel`) instead of clamping to the last stint; the
initial off-air index must not be clamped down onto the live stint. Exact index
bounds (allowing "one past the end" = idle, keeping `idx` bounded) are a TDD detail.
The "fewer than 2 stints" `WARN` (`iro-feeds.py:1671`) changes meaning: the off-air
feed idles rather than mirroring — update the message accordingly. This drops the
incidental "hot-standby duplicate" when only one link exists (acceptable; the relay
already auto-retries a dead feed, and a black second tile is clearer feedback).

### Change 2 — Relay reflects feed state into OBS

On every feed-state change (startup, `/next`, `/set/stint`), the relay pushes the
correct OBS state over obs-websocket (`src/scripts/obs_ws.py` — its `request()` is
generic and already speaks v5):

- In scene **Stint**: enable the live feed's source (`SetSceneItemEnabled`), disable
  the other.
- Audio: unmute the live feed input (`SetInputMute false`), mute the off-air feed.
- **On `/next` only:** also `SetCurrentProgramScene("Stint")` — the automatic cut
  from Splitscreen to single.

**Auto-cut guard:** on `/next`, the relay holds **both** the program cut and the
visibility/audio reflection until the incoming feed is confirmed `serving`; if it is
not yet resolved (e.g. a link entered seconds earlier), the relay still advances the
feed indices but neither flips the Stint-scene source visibility/audio nor cuts the
program scene — never touching the on-air picture when the incoming feed is
black/buffering.

The orchestration is split into a **pure planner** (`feed_state → list of obs
requests`) and a thin best-effort **apply** (the I/O), so the planner is unit-testable
and the apply mirrors the existing best-effort pattern in `obs_ws.py`.

Companion buttons collapse: a single NEXT (Generic-HTTP `GET /next`) now does
everything; the per-feed "STINT A"/"STINT B" combos become the manual fallback (§5),
not the normal path.

### 3.3 How a late link reaches the off-air feed (no button needed)

Two existing loops already deliver this once Change 1 lets the off-air feed idle:

- **Background poller** (`poller`, `iro-feeds.py:1433-1435`, started `:1680`) calls
  `source.refresh()` every `--poll` seconds (**default 30 s**, `:1507`), replacing the
  in-memory schedule under lock (`:807-821`).
- **Idle feed re-check** (`run()`, `iro-feeds.py:1156-1159`): an idling feed re-reads
  `current_channel()` (→ `source.get()`) every **3 s**.

Chain: link saved → ≤ 30 s (poll) → ≤ 3 s (idle re-check) → yt-dlp resolve (a few s)
→ off-air feed pre-warming, black tile lights up on its own. `/next` and `/reload`
additionally do a synchronous `source.refresh(timeout=6)` (`:1245,:1271`) as a
belt-and-suspenders at the critical moment. With links known ~20–30 min ahead, the
30 s poll has ample margin; §7 removes even that delay for extreme cases.

## 4. Operator flow — before / after

**Before (per handover):** cut to Splitscreen → press NEXT → know whether A or B is
live → cut **STINT A** *or* **STINT B** → and mind the cold-start special case.

**After (every handover, identical):** cut to **Splitscreen** → press **NEXT**. The
relay does feed handover + Stint visibility + audio + the cut to Stint.

**Cold-start walk-through (the team's normal case — start with one link):**
- Start: Stint shows Feed A (stint 1); Feed B idles on the empty stint-2 slot (black
  tile in the split).
- ~20–30 min before the swap: someone enters stint 2's link in the sheet → Feed B
  pre-warms by itself; the black tile goes live. Visible feedback, no index math.
- Cut to Splitscreen (both commentators; only the outgoing audible) → press NEXT →
  relay shows Feed B (stint 2), audio follows, Feed A pre-warms stint 3 (or idles
  until its link arrives).

## 5. obs-websocket failure handling (both layers)

- **Up-front (mandatory check):** `iro preflight` and `iro event status` verify the
  obs-websocket connection (password auto-discovered from OBS config; `.env`
  `IRO_OBS_WS_PASSWORD` overrides) and warn loudly if absent — same classifier style
  as `tests/test_preflight.py`.
- **Runtime break-glass:** if obs-websocket is unreachable when NEXT fires, the relay
  still advances the feed internally (audio logic stays consistent), and `/status`
  exposes an `obs_unreachable` signal that the panel renders as a clear banner
  ("OBS not reachable — cut the scene manually"). The existing manual panel/Companion
  controls (Feed A/B visibility, scene switch, mute) remain as the fallback; `/status`
  shows which feed is live so the manual path is guided. Nothing ever goes dead.

## 6. What does NOT change

POV feed (53003, PiP) and Discord audio (separate, manual); the **Splitscreen** scene
(both feeds visible); the **Stint** scene structure (both feeds present — only *who*
toggles visibility changes); HUD / timer / graphics; the yt-dlp → streamlink pull
pipeline; `/reload` (same feed, same stint → no OBS identity change → no reflection).

## 7. Optional, bounded piece — instant availability on panel schedule-write

**Problem:** `SetupControl.schedule_set` (`iro-feeds.py:1031-1058`) only pushes the
URL to the sheet via the webhook; it holds no reference to `ScheduleSource`
(`:985`), so a panel-entered link is visible to the relay only after the next poll
(≤ 30 s) or a `/next`/`/reload` refresh. This mirrors the deliberate split where
**Setup fields** get an optimistic local override (`HudSource`, 30 s TTL,
`:1010-1028`) but **schedule URLs** do not.

**Enhancement:** on a successful schedule-URL push, the relay **injects the row into
its in-memory schedule immediately** (`source.items`/`source.rows`), so an idling
off-air feed adopts it within ~3 s without waiting for a poll. The next poll reads the
same (now-in-sheet) row back and reconciles — no conflict.

Bounded implementation notes:
- **Row mapping:** `source.rows` is keyed by physical sheet row; the inject must use
  the same key so poll and inject coincide (headers/blank rows are skipped by
  `_parse_rows`, `:758-782`).
- **Inject, not immediate `refresh()`:** an instant re-fetch can outrun gviz CSV
  propagation (Google caches the export for a few seconds) and read stale data; a
  local inject is both faster and more reliable.
- **Limit:** in the extreme case this only removes the ≤ 30 s poll delay — yt-dlp
  resolution still needs its few seconds before the feed is `serving`.

This piece is independent of Changes 1–2 and can be sequenced/deferred separately in
the implementation plan.

## 8. Testing (TDD, stdlib, per repo convention)

- **Index invariant** (pure logic) → extend `tests/test_pov.py`: cold-start indices,
  idle-past-end (no clamp), and the "new live = non-advanced feed" invariant over a
  multi-handover sequence **with links added late**.
- **OBS reflection planner** (pure function `feed_state → obs requests`) →
  `tests/test_obsws.py`: visibility/mute/scene requests for each state, plus the
  auto-cut guard (no program cut while the new live feed is not `serving`).
- **obs-websocket reachability** classifier → `tests/test_preflight.py`-style check.
- **Break-glass surface:** `/status` sets `obs_unreachable`; panel shows the banner.
- **Instant-inject (§7):** `tests/test_setup.py` — a successful schedule push injects
  the correctly-keyed row into the in-memory schedule and survives the next poll
  without duplication/revert.

Failing test first, then the change (CLAUDE.md). After relay changes run
`python3 tests/test_pov.py`; before shipping run `python3 tools/build.py`.

## 9. Risks / open considerations

- **obs-websocket becomes load-bearing** for the primary handover path. Mitigated by
  the §5 up-front check + break-glass fallback. Connection strategy (per-action like
  today's refresh vs. a kept-warm connection for snappier cuts) is an implementation
  choice for the plan.
- **Loss of the one-link hot-standby duplicate** (Change 1) — accepted; the black
  second tile is clearer and the relay already retries dead feeds.
- **Auto-cut timing:** NEXT cuts to Stint at press time; the director controls *when*
  to enter the split and *when* to press NEXT, so timing control is preserved.
- **Side alternation in the split** (incoming commentator alternates L/R) already
  exists today and is unchanged; HUD names follow the sheet, not the port.
