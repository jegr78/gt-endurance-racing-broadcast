# Producer Handover — Start Relay at a Given Stint — Design

**Date:** 2026-06-05
**Status:** Approved (design), ready for implementation planning
**Scope:** Let a producer who takes over mid-event (12h/24h races, multiple broadcast
parts) start a fresh relay positioned at the stint that is currently on air, instead
of at stint 1 — plus a runtime correction endpoint and a documented handover flow.

---

## 1. Problem

Long events are split into broadcast parts run by different producers, each on their
own machine with their own relay + OBS + YouTube stream key. The relay keeps its
stint position **in memory only** and always starts at the top of the schedule
(Feed A = index 0, Feed B = index 1). When Producer 2 takes over at, say, stint 4,
their fresh relay would serve stint 1 — and the operator would have to reposition
both feeds by hand via the raw 0-based `/set/A/<idx>` + `/set/B/<idx>` endpoints,
including working out which feed carries which stint.

## 2. Key insight (simplifies everything)

The "Feed A = odd stints, Feed B = even stints" parity is **not a rule** — it is
merely a consequence of starting at stint 1. The ping-pong (`/next` advances the
lower-index feed by +2) works correctly from *any* starting pair. Since each
producer runs their own OBS, the new producer does **not** need to continue the
previous producer's parity. `--stint N` simply starts the same ping-pong at
stint N (served on Feed A, next stint preloaded on Feed B) — no parity
arithmetic, and no operational rule about which feed is on air when going live:
that depends on the takeover moment (mid-stint vs. at a stint boundary) and on
`/next` presses between bring-up and go-live.

*(Amended after review with the producer: an earlier revision phrased this as a
crew rule — "after every takeover you go on air with Feed A" — which
over-promised; real handovers happen near part boundaries, e.g. a 12h event
with 6 stints switching after stint 3, or 24h events with 3×4 stints.)*

## 3. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| Handover topology | Separate machines, each with its own relay/OBS/stream key; YouTube end-of-stream redirect carries viewers to the next part |
| Overlap | A few minutes of deliberate double-broadcast; fixed handover times ruled out |
| Stint source | **Manual stint number** (operator knows it from the sheet/Discord). Time-based and peer-relay-sync approaches rejected (overlap makes times unreliable; peer sync is fragile exactly at handover) |
| Start semantics | `--stint N` means "**stint N is on air right now**": Feed A → stint N, Feed B → stint N+1. During the overlap both broadcasts show the same commentator; the part transition is a normal `/next` |
| Input surfaces | CLI flag on `iro relay start`, `iro relay run`, and `iro event start` (passed through), **plus** HTTP endpoint `/set/stint/<n>` for correction |
| Same-producer next part | No relay action needed — relay keeps running; producer only restarts the OBS stream with the next stream key |
| Scope extras | Handover checklist in operator docs/wiki. **Not** in scope: panel UI input, Companion button, event-readiness warning |

## 4. Design

### 4.1 Relay: `--stint N` start argument (`src/relay/iro-feeds.py`)

- New argparse option `--stint N`, **1-based** (matches the sheet and `/status`
  output), default `1` (today's behaviour, bit-for-bit).
- A pure helper computes the start indices, clamped to the schedule length:

  ```
  stint_start_indices(stint, schedule_len) -> (a_idx, b_idx)
  # stint 3, len 8  -> (2, 3)
  # stint 1, len 8  -> (0, 1)      # default, unchanged behaviour
  # stint 9, len 8  -> (7, 7)      # clamp + warning
  # stint 8, len 8  -> (7, 7)      # last stint: B clamps onto A (same as 1-stint schedules today)
  ```

- `Relay.__init__` uses the helper for the initial `Feed` indices.
- Startup log states the positioning explicitly, e.g.
  `starting at stint 3 (Feed A on air, Feed B preloads stint 4)`, and warns when
  the requested stint was clamped.
- POV feed is unaffected.

### 4.2 CLI passthrough (`src/iro.py`, `src/scripts/services.py`, `src/scripts/event.py`)

- `iro relay start --stint N` and `iro relay run --stint N` append `--stint N` to
  the relay argv (daemon and foreground modes).
- `iro event start --stint N` forwards the flag to the relay launch, covering the
  "takeover = full event bring-up on a fresh machine" path.
- Invalid values (non-integer, < 1) fail fast with a clear message before anything
  is spawned.

### 4.3 Runtime correction endpoint: `GET /set/stint/<n>`

- **1-based** stint number — deliberately different from the existing 0-based
  `/set/A/<idx>` endpoints; the help text / docs call this out explicitly.
- Atomically positions **both** feeds: A → stint n, B → stint n+1 (same clamping
  helper as 4.1). Responds with the usual `/status` JSON.
- Purpose: fix a typo or a forgotten `--stint` **before going on air**. Like the
  existing `/set` endpoints it tears a running feed off its stream, so the docs
  state plainly: not for mid-program use.
- Reachable like every other control endpoint (browser, Companion Generic-HTTP),
  e.g. `http://127.0.0.1:8088/set/stint/3`.

### 4.4 Visibility

- `/status` already reports a 1-based `stint` per feed — no change needed.
- The relay's startup output (and therefore `iro relay logs`) shows the positioning
  message from 4.1 so the producer immediately sees the flag took effect.

### 4.5 Operator documentation — producer handover checklist

New wiki page (or section in the event-day material; English, like all shipped
docs):

1. Producer 2: `iro event start --stint <N>` — N = the stint currently on air
   (from the sheet / Discord); at a stint boundary, the stint that is starting.
2. Verify Feed A shows the expected commentator (`/status` or OBS preview).
3. Start the OBS stream with the next part's stream key (overlap begins).
4. Share the new panel/tablet URLs with the directors (the CLI already prints
   them — just forward).
5. Producer 1 stops their stream → the YouTube redirect takes effect; afterwards
   Producer 1 runs `iro event stop`.
6. Same-producer-next-part special case: only stop + restart the OBS stream with
   the new key — the relay keeps running, no `--stint` needed.

## 5. Error handling

| Case | Behaviour |
|---|---|
| `--stint` non-integer or < 1 | CLI fails fast with a clear message |
| Stint beyond schedule length | Clamp to last stint + warning (start log / endpoint response) |
| Stint = last stint | B clamps onto the same index as A (existing short-schedule behaviour) |
| `/set/stint/<n>` while a feed is serving | Allowed, tears the feed (same as existing `/set`); documented as pre-go-live tool |
| Two relays pulling the same YouTube stream during overlap | Fine — independent HLS consumers |

## 6. Testing

Stdlib runnable-script style, like the rest of the suite:

- `stint_start_indices()` unit checks (default, normal, clamp, last-stint) — in a
  new `tests/test_stint.py` or folded into `tests/test_pov.py`, wired into
  `tools/run-tests.py`.
- `/set/stint/<n>` routing check (handler dispatch, 1-based mapping).
- `iro relay start --stint` / `iro event start --stint` argv passthrough checks,
  following the `tests/test_iro.py` pattern.

## 7. Out of scope (deliberate)

- Panel UI input field for the stint number.
- Companion button for `/set/stint` (needs a number — impractical on a button).
- Event-readiness report warning about feeds still at stint 1/2.
- Any state transfer between producer machines (peer sync, shared state cell).
