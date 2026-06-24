# Relay Dead-Stint Backoff & Idle — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming)
**Component:** `src/relay/racecast-feeds.py` (`Feed.run`)

## Problem

A single test session on 2026-06-18 produced a **632 MB** `feed_A.log`: 234 126 lines,
of which **220 696 (94 %)** were `Unable to fetch new streams: … 403 Forbidden` and a
further **11 603** were `429 Too Many Requests`.

Root cause, confirmed from the log sequence
(`serving stint 1 → Stream ended → re-resolve same videoId → 403 storm`): when the
YouTube live stream of a stint **ends** (commentator goes offline / live → VOD),
`yt-dlp -g` keeps returning an **expired/forbidden** manifest URL. Streamlink serves it,
hits 403 on every segment/playlist reload, emits ~100 `403`s, then exits. The relay's
`Feed.run` loop sleeps a **fixed** `RETRY_SLEEP` (10 s) and re-spawns — **forever**, with
no escalating backoff and no give-up. Unattended, this hammers YouTube hard enough to get
the producer's IP/cookies **rate-limited** (the 11 603 self-inflicted 429s) and grows the
log without bound.

PR #318 (log throttle + URL shortening) made the **log** survivable but deliberately did
**not** change this retry behaviour — the network hammering and the never-give-up loop are
untouched. This design fixes the root cause in the relay loop.

A secondary, related symptom in the same logs — `error: No plugin can handle URL:
…googlevideo.com/videoplayback?…itag=18…` — is the **same** event (the ended stream became
a VOD, so yt-dlp returned a progressive `itag=18` URL streamlink cannot serve). It is
covered by the same fix: it is a fast-dying serve like any other.

## Goal

When a stint's source persistently fails **after having resolved**, the relay must stop
hammering: back off with an escalating, capped delay, and after a small number of
consecutive failures go **idle** until the operator advances (`/next`) or reloads
(`/reload`). A source that is merely **not yet live** (resolve returns no URL — normal
pre-roll, waiting for a commentator to start) must **keep waiting** unchanged, so the
pre-roll workflow is preserved.

## Two failure paths (the core distinction)

`Feed.run` already separates these; the fix treats them differently:

| Path | Today's signal | Today's behaviour | New behaviour |
|------|----------------|-------------------|---------------|
| **A — not yet live** | `resolve_hls` returns no URL (`not hls`) | `time.sleep(RESOLVE_RETRY)` (15 s), loop | **Unchanged.** Fixed 15 s keeps pre-roll maximally responsive (a commentator going live is picked up within ≤15 s). This path was never the storm source — one yt-dlp call per 15 s is not a flood. |
| **B — was live, now dead** | serve completed but `serve_elapsed < HEALTH_SERVED_OK_S` (10 s) — the 403/VOD case | `time.sleep(RETRY_SLEEP)` (10 s), loop forever | **Escalating backoff** (10 s → 20 s → 40 s … capped at 300 s), then **idle** after `DEAD_SERVE_IDLE_AFTER` consecutive dead serves. |

Reset: a serve that lasts `>= HEALTH_SERVED_OK_S` (the existing `served_ok = True` line) is a
real picture → reset the dead-serve counter to 0. Operator `set_index()`/`reload()` (new
source) also resets it.

## New constants

Next to the existing timing constants (~line 123 of `racecast-feeds.py`):

```python
DEAD_SERVE_BACKOFF_CAP = 300   # s — max delay between re-attempts of a fast-dying serve
DEAD_SERVE_IDLE_AFTER  = 5     # consecutive dead serves -> go idle until the operator acts
```

`RESOLVE_RETRY` (15 s) and `RETRY_SLEEP` (10 s) keep their current values; `RETRY_SLEEP`
becomes the **base** of the escalating backoff.

## New per-feed state

In `Feed.__init__`: `self.dead_serves = 0` — count of consecutive "was-live-then-died-fast"
serves. Reset to 0 on a real serve, on `set_index()`, and on `reload()`.

## Pure helpers (unit-testable, mirroring `feed_fast_exit_error` / `serve_exit_is_drop`)

```python
def dead_serve_backoff(count, base=RETRY_SLEEP, cap=DEAD_SERVE_BACKOFF_CAP):
    """Escalating sleep (seconds) after the count-th consecutive dead serve:
    base, 2×base, 4×base … capped at cap. count is the number of dead serves so far
    (>=1); count<1 yields base. Pure so the schedule is unit-testable."""
    return min(base * (2 ** max(count - 1, 0)), cap)

def should_idle_dead_serves(count, limit=DEAD_SERVE_IDLE_AFTER):
    """True when consecutive dead serves reached the limit -> stop re-spawning until
    the operator advances/reloads."""
    return count >= limit
```

Schedule with the defaults: 10, 20, 40, 80, then **idle** at the 5th (since
`DEAD_SERVE_IDLE_AFTER = 5`). (The 160/320→cap values exist for completeness/tests but are
only reached if `DEAD_SERVE_IDLE_AFTER` is raised.)

## Loop integration (`Feed.run`, the post-`proc.wait()` tail, ~lines 3319-3342)

After the existing stop/advance checks and the `serve_elapsed >= HEALTH_SERVED_OK_S`
served_ok line:

```python
if serve_elapsed >= HEALTH_SERVED_OK_S:
    self.served_ok = True
    self.dead_serves = 0                      # real picture -> reset
# … existing dropped/dropped_since bookkeeping, stop/advance handling unchanged …
if self.stop:
    break
if self.advance.is_set():
    self.advance.clear()
    self.dead_serves = 0                      # operator moved/reloaded -> fresh source
    continue
err = feed_fast_exit_error(serve_elapsed, serve_rc)
if err:
    self.last_error = err
if serve_elapsed < HEALTH_SERVED_OK_S:
    self.dead_serves += 1
    if should_idle_dead_serves(self.dead_serves):
        self._set_phase("idle")
        self.last_error = ("stint source unavailable — paused after "
                           f"{self.dead_serves} attempts; /next or /reload to retry")
        # stop hammering: wait for operator /next or /reload (which set advance) or shutdown
        while not self.stop and not self.advance.is_set():
            self.advance.wait(1.0)
        continue                              # top of loop re-evaluates; advance/stop handled there
    time.sleep(dead_serve_backoff(self.dead_serves))
    continue
time.sleep(RETRY_SLEEP)                        # served_ok serve that simply ended normally
```

Notes:
- The idle wait blocks on `self.advance` (set by `set_index`/`reload`) so the operator
  wakes it instantly; the 1 s timeout bounds the stop-check latency.
- `shutdown()` sets `self.stop = True` and kills the proc; the idle loop’s `not self.stop`
  guard exits within ≤1 s. (No change to `shutdown` required.)
- A `served_ok` serve that ends normally (e.g. a stint that genuinely ran and the stream
  closed) takes the final `RETRY_SLEEP` branch — behaviour unchanged for the healthy case.

## Counter reset in operator actions (`set_index`, `reload`)

Both already call `self._clear_drop_health()`. Add `self.dead_serves = 0` alongside, so a
director repositioning or reloading a feed starts the dead-serve count fresh.

## Out of scope (YAGNI / risk)

- **Streamlink internal retry flags** (limiting per-run segment/open attempts). A single
  dead serve still emits its ~100 internal 403s (throttled in the log by #318); `idle-after-5`
  hard-caps the number of such runs. Touching streamlink's flags would also clip **legitimate**
  transient recovery on a real live stream (a momentary 403 blip), so it is deliberately left
  out.
- Any change to the not-yet-live (Path A) retry cadence.
- Any change to the health/drop model (#278) or the Twitch path.

## Testing

`tests/test_pov.py` (the relay pure-helper suite), in the style of the existing
`feed_fast_exit_error` / `serve_exit_is_drop` tests:

- `dead_serve_backoff`: escalation (10, 20, 40, 80), cap at 300, `count<1` → base.
- `should_idle_dead_serves`: false below limit, true at/above limit; respects a custom limit.

The loop integration stays thin enough that the pure helpers carry the logic; the thread
loop itself is not unit-tested (consistent with the existing relay test strategy).

## Files

- Modify: `src/relay/racecast-feeds.py` — constants, `Feed.__init__` state,
  two pure helpers, `Feed.run` tail, `set_index`/`reload` reset.
- Test: `tests/test_pov.py` — helper unit tests.
