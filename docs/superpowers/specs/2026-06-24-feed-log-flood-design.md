# Feed-log flood — throttle + URL-shorten the streamlink pump

**Date:** 2026-06-24
**Status:** Design (approved)
**Area:** logging (`src/scripts/logsetup.py` — `pump_subprocess`), affects the relay feeds (`src/relay/racecast-feeds.py`) and static streams (`src/scripts/loopstream.py`) that pump through it.

## Problem

A real test session produced a **662 MB** `feed_A.log.2026-06-18` (234,126 lines) in a single day. Breakdown of the lines:

| Count | Line |
|---|---|
| 220,696 | `[cli][error] Unable to fetch new streams: Unable to open URL: <URL> (403 Client Error: Forbidden …)` |
| 11,603 | `… (429 Client Error: Too Many Requests …)` |

When streamlink loses access to the live HLS manifest mid-stream (the googlevideo URL expires / is blocked / the stream ended), it retries fetching "new streams" in a tight loop. Each retry line carries the **full ~2.8 KB googlevideo manifest URL**, so 220k retries × 2.8 KB ≈ 662 MB. Two design facts make this dangerous:

1. `logsetup.pump_subprocess` writes **every** subprocess line verbatim — no dedup, no rate limit.
2. Log rotation is **time-based only** (`TimedRotatingFileHandler`, `when="midnight"`, no size cap), so a single day's file is unbounded and can fill the disk during a live event before midnight rotation ever runs.

Secondary issue: the manifest URL embeds short-lived signature tokens (`sig`, `lsig`) — secrets that should not be written to a log at all.

## Goal

Stop the streamlink pump from flooding a feed log (and from writing manifest tokens), while keeping the signal: the first occurrence of an error, periodic counts of how often it is repeating, and all distinct diagnostic lines under normal operation.

## Non-goals

- No size-cap / size-based rotation (decided YAGNI): throttle + URL-shortening already cut the observed volume by ~99.9%; rotation stays purely time-based.
- No change to log format, rotation, retention, or the `[tag]` prefixing.
- No new dependency; stdlib only.
- No change to `classify_subproc_line`'s level heuristics or to `on_line` quality parsing (every line still reaches `on_line`).

## Decisions (resolved during brainstorming)

- **Throttle = dedup AND rate-limit combined** (both mechanisms).
- **Shorten long URLs in ALL pumped lines** (info and error alike) — cuts line size and strips the `sig`/`lsig` tokens; keeps `itag` for diagnostics.
- **No size cap.**

## Approach

Put the fix at the single choke point — `logsetup.pump_subprocess` — so both the relay feeds and static streams benefit with no duplication. Extract the decision logic into **pure, independently testable units**; `pump_subprocess` only wires them together. The throttle state is local to each `pump_subprocess` call, so it is naturally per-feed and thread-isolated (one pump thread per subprocess).

## Design

### Unit 1 — `shorten_urls(text, max_len=120)` (pure)

Replace any `http(s)://…` substring longer than `max_len` with a compact form:

```
https://manifest.googlevideo.com/…(itag 301, +2614 chars elided)
```

- Keeps `scheme://host`; elides the path+query (where `sig`/`lsig` live).
- If the original contains `itag/<n>` or `itag=<n>`, append `(itag <n>, +<elided> chars elided)`; otherwise `(+<elided> chars elided)`.
- URLs at or below `max_len`, and non-URL text, are returned unchanged.
- Multiple URLs in one line are each shortened.
- Pure function of its input; no I/O.

### Unit 2 — `normalize_for_dedup(text)` (pure)

Produce a dedup key that ignores the volatile parts of a repeated line:

- Replace every `http(s)://…` URL run with `<url>`.
- Replace every run of digits with `<n>`.
- Return the result.

So `… Unable to open URL: <expired-url-A> (403 …)` and `… Unable to open URL: <expired-url-B> (403 …)` map to the same key. Pure; no I/O.

### Unit 3 — `LineThrottle` (pure, clock injected)

One instance per `pump_subprocess` call. Combines dedup and rate-limiting and returns the records to actually log.

```python
class LineThrottle:
    def __init__(self, rate_max=30, window_s=10.0, summary_s=30.0):
        ...
    def emit(self, level, text, now):
        """Return a list of (level, text) records to log for this incoming line.
        `text` is already URL-shortened by the caller. `now` is a monotonic
        float (injected for tests). The list is 0, 1, or 2 records."""
```

State: `last_key`, `last_level`, `dup_count`, `last_summary_at`, plus rate-limit window fields (`window_start`, `window_count`, `dropped_in_window`).

Algorithm for an incoming `(level, text, now)` with `key = normalize_for_dedup(text)`:

1. **Duplicate of the previous line** (`key == last_key`):
   - `dup_count += 1`; suppress the line itself.
   - If `now - last_summary_at >= summary_s`: emit one `(last line repeated ×<dup_count>)` at `last_level`, set `last_summary_at = now`.
   - Return the (0 or 1) summary records.
2. **New, distinct line** (`key != last_key`):
   - If `dup_count > 0`: first emit `(previous line repeated ×<dup_count>)` at `last_level`; reset `dup_count = 0`.
   - Set `last_key = key`, `last_level = level`, `last_summary_at = now`.
   - **Rate limit:** if `now - window_start >= window_s`, roll the window — and if `dropped_in_window > 0`, emit `(suppressed <dropped_in_window> lines)` at WARNING and reset the drop counter; reset `window_count = 0`, `window_start = now`.
   - If `window_count < rate_max`: `window_count += 1`; emit `(level, text)`.
   - Else: `dropped_in_window += 1` (the line is dropped; its count surfaces on the next window roll).
   - Return the accumulated records (a flush summary and/or the line, or a drop with nothing).

Properties: the **first** occurrence of any line is always emitted; a sustained identical flood collapses to one real line plus ≤ one summary per `summary_s`, at the flood's own level (an ERROR storm stays visible as ERROR); a flood of *distinct* lines is capped at `rate_max` per `window_s` with periodic `(suppressed N lines)` notices.

### Unit 4 — `pump_subprocess` (wiring only)

Current body logs every line verbatim. New body:

```python
def pump_subprocess(stream, logger, tag, on_line=None, now=time.monotonic):
    throttle = LineThrottle()
    try:
        for raw in iter(stream.readline, ""):
            line = raw.rstrip("\n").rstrip("\r")
            if on_line is not None:
                try:
                    on_line(line)            # every line — quality parsing unchanged
                except Exception:            # noqa: BLE001 — observer is best-effort
                    pass
            try:
                level = classify_subproc_line(line)   # on the ORIGINAL line
                for lvl, text in throttle.emit(level, shorten_urls(line), now()):
                    logger.log(lvl, "[%s] %s", tag, text)
            except Exception:                # noqa: BLE001 — throttling must never break the pump
                logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
    except (ValueError, OSError):
        pass  # pipe closed mid-read — end the thread, never the daemon
```

- `on_line` still runs for **every** line, before throttling — quality parsing is unaffected.
- `classify_subproc_line` runs on the **original** line so its hints (`forbidden`, `403`, `retry`, …) are not lost to shortening (those tokens live in the message text, not the URL).
- A throttle/shorten failure falls back to logging the raw line — the pump's best-effort contract (never break the daemon thread) is preserved.
- `now` is injectable so tests are deterministic; production uses `time.monotonic`.

### Constants

`rate_max=30`, `window_s=10.0`, `summary_s=30.0`, `max_len=120` — module-level named constants in `logsetup.py`. Normal streamlink output is a handful of lines per stint, well under the rate limit; the values only bite a genuine flood. No env override (YAGNI).

## Security

The manifest `sig`/`lsig` tokens are in the URL query, which `shorten_urls` elides — so they are no longer written to any feed log. This is a net reduction in what the logs contain; no new exposure.

## Testing (TDD — failing test first)

All in `tests/test_logs.py` (which already covers `pump_subprocess`):

- `shorten_urls`: a real ~2.8 KB googlevideo URL → compact form, `sig`/`lsig` absent, `itag` preserved; a short URL unchanged; non-URL text unchanged; two URLs in one line both shortened.
- `normalize_for_dedup`: two 403 lines with different expired URLs and timestamps → identical key; two genuinely different messages → different keys.
- `LineThrottle` (injected clock):
  - 1000 identical-after-normalize lines → far fewer than 1000 emitted records; the first real line is present; the repeat count totals 999 across summaries; summaries carry the original level.
  - A flood of distinct lines within one window → capped at `rate_max`, with a `(suppressed N lines)` summary on the next window roll.
  - A pattern change flushes the pending `(previous line repeated ×N)` summary before the new line.
- `pump_subprocess` integration: a fake stream of N identical flood lines + a fake clock + a capturing logger → the logger receives few records, none containing the URL query/token, at least one `(…repeated ×…)` summary; and `on_line` was called once per input line.

## Files touched

- `src/scripts/logsetup.py` — add `shorten_urls`, `normalize_for_dedup`, `LineThrottle`; rewire `pump_subprocess` (+ `now` param).
- `tests/test_logs.py` — coverage per above.
- No change to `racecast-feeds.py` / `loopstream.py` (they call `pump_subprocess` unchanged).
