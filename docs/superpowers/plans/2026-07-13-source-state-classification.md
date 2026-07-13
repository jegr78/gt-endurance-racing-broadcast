# Source-state Classification + Notification (#495 core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify a feed's source-not-live state (Twitch offline / YouTube ended) and surface it distinctly — a clear health reason instead of a generic drop, and no `@here` churn spam for an expected-unstable source.

**Architecture:** A pure `classify_source_state(text)` maps yt-dlp/streamlink diagnostics to `not_live_yet` / `ended` / `None`. A new `Feed.source_state` is set from the YouTube resolve error and the Twitch streamlink line, cleared on a successful serve. It enriches the `/status` per-feed block, the `aggregate_health` reason text (severity unchanged — not_live_yet stays yellow, ended stays red), and suppresses the churn `@here` for classified sources.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest) under `tests/`, loaded via `importlib` as `m` (`tests/test_health.py` for the pure health helpers, `tests/test_pov.py` for relay/status).

## Global Constraints

- **Edit only under `src/`** (`dist/`/`runtime/` generated). Tests under `tests/`.
- **English only** in code/comments/log lines/docs.
- **Python stdlib only** — no new dependencies.
- **Severity is unchanged** — `not_live_yet` stays yellow/DEGRADED (already so via `served_ok`); `ended` stays red. This PR changes only the **reason text**, the `/status` field, and the churn `@here` suppression. `feed_health_state`/`aggregate_health`'s level logic is NOT altered.
- **The classifier states are exactly:** `"not_live_yet"`, `"ended"`, `None`.
- After a relay change run `python3 tests/test_health.py` + `python3 tests/test_pov.py`; before finishing run `python3 tools/run-tests.py` + `python3 tools/lint.py`.
- No secrets/machine-paths/real-IPs in tests.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Spec: `docs/superpowers/specs/2026-07-13-source-state-classification-design.md`. Issue #495 (core slice; on-air slate + failover source are the deferred follow-up).

---

### Task 1: `classify_source_state` + `Feed.source_state` + `/status` field

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add the classifier + signature tables near `serve_exit_is_drop` (~line 230); `Feed.source_state` init (~line 5024, near `self.on_recovery`); set it on the YouTube resolve-fail (~line 5200) and in `_observe_streamlink_line` (~line 5064); clear it in `_clear_drop_health` (~line 5056); add `source_state` to the `/status` per-feed block (~line 5612).
- Test: `tests/test_health.py` (pure classifier), `tests/test_pov.py` (status field).

**Interfaces:**
- Produces: `classify_source_state(text) -> "not_live_yet" | "ended" | None`; `Feed.source_state` (str|None); `/status` `feeds[X]["source_state"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health.py` (auto-discovered `t_*`; module `m`):

```python
def t_classify_source_state():
    # Twitch: channel offline / not live yet.
    assert m.classify_source_state(
        "error: No playable streams found on this URL: twitch.tv/kekko") == "not_live_yet"
    # yt-dlp YouTube: channel not currently live.
    assert m.classify_source_state("ERROR: [youtube] abc: The channel is not currently live") == "not_live_yet"
    assert m.classify_source_state("not live?") == "not_live_yet"          # resolve fallback
    # YouTube: broadcast over.
    assert m.classify_source_state("ERROR: [youtube] sgoDA5E4aJ0: This live event has ended.") == "ended"
    # Generic / transient -> None (unchanged behaviour).
    assert m.classify_source_state("HTTP Error 429: Too Many Requests") is None
    assert m.classify_source_state("HTTP Error 403: Forbidden") is None
    assert m.classify_source_state("") is None
    assert m.classify_source_state(None) is None
```

Append to `tests/test_pov.py`:

```python
def t_status_exposes_feed_source_state():
    rows = [("uA", "A", "S1", 1), ("uB", "B", "S2", 2)]
    r = m.Relay(_StubSource(["uA", "uB"], rows), (53001, 53002), LOGDIR)
    assert r.A.source_state is None
    st = r.status()
    assert st["feeds"]["A"]["source_state"] is None
    r.A.source_state = "not_live_yet"
    assert r.status()["feeds"]["A"]["source_state"] == "not_live_yet"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_health.py`  → FAIL (`no attribute 'classify_source_state'`).
Run: `python3 tests/test_pov.py`  → FAIL (`AttributeError: 'Feed' object has no attribute 'source_state'` or `KeyError: 'source_state'`).

- [ ] **Step 3: Implement the classifier**

In `src/relay/racecast-feeds.py`, add right after `serve_exit_is_drop` (~line 230):

```python
# Source-not-live signatures (#495) — matched case-insensitively as substrings against
# the yt-dlp/streamlink diagnostic text. ENDED is checked first (more specific).
_SOURCE_ENDED = ("this live event has ended",)
_SOURCE_NOT_LIVE_YET = (
    "no playable streams found",     # Twitch: channel offline / not live yet
    "not currently live",            # yt-dlp YouTube: channel not live
    "will begin in",                 # YouTube: scheduled premiere not started
    "not live?",                     # resolve_hls fallback line
)


def classify_source_state(text):
    """Classify a feed's yt-dlp/streamlink diagnostic *text* into a source-not-live
    state, or None for a generic drop/error (#495). Case-insensitive substring match.
    Pure → unit-tested.
      "not_live_yet" — source offline / not started (Twitch 'No playable streams
                       found', yt-dlp 'not currently live', the 'not live?' fallback).
      "ended"        — source's live broadcast is over (YouTube 'This live event has
                       ended').
      None           — anything else (429/403/network/generic) — unchanged behaviour."""
    if not text:
        return None
    low = text.lower()
    if any(s in low for s in _SOURCE_ENDED):
        return "ended"
    if any(s in low for s in _SOURCE_NOT_LIVE_YET):
        return "not_live_yet"
    return None
```

- [ ] **Step 4: Wire `Feed.source_state` (init, set, clear) + `/status`**

In `Feed.__init__`, near `self.on_recovery = None` (~line 5024), add:

```python
        self.source_state = None      # #495: "not_live_yet"/"ended"/None (why the feed isn't serving)
```

In `_clear_drop_health` (~line 5056), add the clear (runs on every serve-start + operator action, all AFTER the recovery callback fires):

```python
        self.source_state = None      # a fresh serve/reposition: the drop's cause no longer applies
```

In the YouTube resolve-fail branch (~line 5200, `if not hls:`), set it:

```python
                if not hls:
                    self.last_error = err
                    self.source_state = classify_source_state(err)
                    time.sleep(RESOLVE_RETRY); continue
```

In `_observe_streamlink_line` (~line 5064), classify the Twitch line too:

```python
    def _observe_streamlink_line(self, line):
        q = parse_stream_quality(line)
        if q:
            self.quality = q
        st = classify_source_state(line)
        if st is not None:
            self.source_state = st
```

In `status()`'s per-feed block (~line 5612, next to `"last_error"`), add:

```python
                               "source_state": f.source_state,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_health.py`  → PASS.
Run: `python3 tests/test_pov.py`  → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_health.py tests/test_pov.py
git commit -m "feat(relay): classify_source_state + Feed.source_state + /status field (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Distinct health reason (enrich `aggregate_health` via `feed_source_states`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `_health_facts` adds a `feed_source_states` map (~line 5472); `aggregate_health` uses it for the `feeds_down`/`feeds_connecting_long` reason text (~line 467 + ~line 487).
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `Feed.source_state` (Task 1).
- Produces: `aggregate_health` facts gain an optional `"feed_source_states": {name: state}`; the reason strings for a not_live_yet connecting feed and an ended down feed change (level unchanged).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health.py` (`_facts(**kw)` merges kwargs over the base):

```python
def t_aggregate_health_not_live_yet_distinct_reason():
    h = m.aggregate_health(_facts(feeds_connecting_long=["A"],
                                  feed_source_states={"A": "not_live_yet"}))
    assert h["level"] == "yellow"                              # severity unchanged
    assert any("source not live yet" in r for r in h["reasons"])
    assert not any("stuck connecting" in r for r in h["reasons"])


def t_aggregate_health_ended_distinct_reason():
    h = m.aggregate_health(_facts(feeds_down=["A"], feed_source_states={"A": "ended"}))
    assert h["level"] == "red"                                # ended is still a genuine loss
    assert any("live stream ENDED" in r for r in h["reasons"])
    assert not any("lost the live stream" in r for r in h["reasons"])


def t_aggregate_health_reasons_unchanged_without_source_states():
    # No feed_source_states -> the existing generic reasons (backward compat).
    assert any("lost the live stream" in r
               for r in m.aggregate_health(_facts(feeds_down=["A"]))["reasons"])
    assert any("stuck connecting" in r
               for r in m.aggregate_health(_facts(feeds_connecting_long=["B"]))["reasons"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health.py`
Expected: FAIL — the distinct-reason asserts fail (the generic strings are still produced).

- [ ] **Step 3: Enrich `aggregate_health`**

In `aggregate_health`, replace the `feeds_down` loop (~line 467):

```python
    sstates = facts.get("feed_source_states") or {}
    for name in facts.get("feeds_down") or []:
        if sstates.get(name) == "ended":
            red.append(f"Feed {name} — source's live stream ENDED "
                       f"(no auto-recovery — switch source)")
        else:
            red.append(f"Feed {name} down — lost the live stream")
```

And the `feeds_connecting_long` loop (~line 487):

```python
    for name in facts.get("feeds_connecting_long") or []:
        if sstates.get(name) == "not_live_yet":
            yellow.append(f"Feed {name} — commentator source not live yet (connecting)")
        else:
            yellow.append(f"Feed {name} stuck connecting")
```

- [ ] **Step 4: Populate `feed_source_states` in `_health_facts`**

In `_health_facts`, build the map while iterating the feeds (the loop that fills `feeds_down`/`connecting_long`, ~line 5440), and add it to the returned dict. Add before the loop:

```python
        feed_source_states = {}
```

Inside the loop, after the `state = feed_health_state(...)` line, record the feed's source_state (only meaningful for a not-ok feed, but harmless to always record):

```python
            if f.source_state is not None:
                feed_source_states[name] = f.source_state
```

And add to the returned dict (next to `"feeds_connecting_long"`):

```python
                "feed_source_states": feed_source_states,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 tests/test_health.py`
Expected: PASS (incl. the three new tests and the pre-existing `aggregate_health` tests).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_health.py
git commit -m "feat(relay): distinct health reason for not-live-yet / ended sources (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Churn `@here` suppression for classified sources + full suite + lint

**Files:**
- Modify: `src/relay/racecast-feeds.py` — pure `churn_at_here_suppressed` (near `feed_recovery_churn`, ~line 386); pass `source_state` through the `on_recovery` callback (fire site ~line 5213, `Feed.on_recovery` doc ~line 5024); `_record_feed_recovery` (~line 6219) + `_maybe_notify_recovery_churn` (~line 6237) accept/use it.
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `Feed.source_state` (Task 1).
- Produces: `churn_at_here_suppressed(source_state) -> bool`; `on_recovery(feed, stint, downtime_s, source_state)` (4-arg); `_record_feed_recovery(self, feed, stint, downtime_s, source_state=None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_health.py`:

```python
def t_churn_at_here_suppressed_predicate():
    assert m.churn_at_here_suppressed("not_live_yet") is True
    assert m.churn_at_here_suppressed("ended") is True
    assert m.churn_at_here_suppressed(None) is False       # genuine churn still notifies
    assert m.churn_at_here_suppressed("serving") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health.py`
Expected: FAIL — `no attribute 'churn_at_here_suppressed'`.

- [ ] **Step 3: Add the pure predicate**

In `src/relay/racecast-feeds.py`, right after `feed_recovery_churn` (~line 386):

```python
def churn_at_here_suppressed(source_state):
    """True when a feed-recovery-churn @here should be SUPPRESSED because the feed's
    source is a known not-(yet)-live state (#495): a source that is offline or has
    ended and keeps flapping while the relay retries is expected churn, not a relay
    fault. Genuine churn (source_state None) still pages. Pure → unit-tested."""
    return source_state in ("not_live_yet", "ended")
```

- [ ] **Step 4: Thread `source_state` through the recovery callback**

At the `on_recovery` fire site (~line 5213), pass the feed's current `source_state` (still set — `_clear_drop_health` clears it later, during the serve that follows):

```python
                    self.on_recovery(self.name, i + 1, max(0.0, down), self.source_state)
```

Update the `Feed.on_recovery` doc comment (~line 5024) to note the 4th arg:

```python
        self.on_recovery = None       # relay-set callback(feed, stint, downtime_s, source_state) on a drop-recovery
```

In `_record_feed_recovery` (~line 6219), accept the new arg and forward it:

```python
    def _record_feed_recovery(self, feed, stint, downtime_s, source_state=None):
```

and change its final line from `self._maybe_notify_recovery_churn(feed, now)` to:

```python
        self._maybe_notify_recovery_churn(feed, now, source_state)
```

In `_maybe_notify_recovery_churn` (~line 6237), add the parameter and an early return at the top of the method body (after the docstring, before the `if self.health_store is None:` check):

```python
    def _maybe_notify_recovery_churn(self, feed, now, source_state=None):
        """... (unchanged docstring) ..."""
        if churn_at_here_suppressed(source_state):
            return                    # #495: expected churn from a not-(yet)-live source
        if self.health_store is None:
            return
        ...
```

- [ ] **Step 5: Add a churn-suppression behaviour test**

Append to `tests/test_health.py` (verified against the file's helpers: `_mk_relay(td, items)` builds a relay but does NOT wire a store, so set one explicitly like the other store tests do — `r.health_store = m.HealthStore(os.path.join(td, "h.db"))`; `HealthStore` has `.record_event(ts, type, producer="", metadata=None)`, `.events(frm, to)`, `.close()`; `_discord_post(self, payload, what)`):

```python
def t_churn_at_here_suppressed_for_not_live_source():
    with tempfile.TemporaryDirectory() as td:
        r = _mk_relay(td, ["a", "b"])
        r.health_store = m.HealthStore(os.path.join(td, "h.db"))
        posts = []
        r._discord_post = lambda payload, what: posts.append(what)
        now = 1000.0
        try:
            # Make Feed A churn: >= threshold feed_recovery events inside the window.
            for k in range(m.FEED_CHURN_THRESHOLD):
                r.health_store.record_event(now - 10 + k, "feed_recovery",
                                            metadata={"feed": "A"})
            # A not-live-yet source -> the @here is suppressed.
            r._maybe_notify_recovery_churn("A", now, "not_live_yet")
            assert posts == []
            # Genuine churn (source_state None) -> the @here still fires.
            r._maybe_notify_recovery_churn("A", now, None)
            assert "feed-recovery-churn" in posts
        finally:
            r.health_store.close()
```

The early-return in `_maybe_notify_recovery_churn` runs BEFORE the per-feed cooldown bookkeeping, so the first (suppressed) call does not block the second call. If `HealthStore.record_event`'s parameter names differ from the above, match the file's existing `record_event` usage.

- [ ] **Step 6: Run the covering test + full suite + lint**

Run: `python3 tests/test_health.py`  → PASS.
Run: `python3 tools/run-tests.py`
Expected: all test files pass (exit 0).
Run: `python3 tools/lint.py`
Expected: `All checks passed`.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_health.py
git commit -m "feat(relay): suppress feed-churn @here for not-live-yet / ended sources (#495)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §1 pure classifier → Task 1.
- §2 `Feed.source_state` set (YouTube resolve, Twitch `_observe`) + clear (`_clear_drop_health`) → Task 1.
- §3 `/status` field → Task 1; distinct health reason via `feed_source_states` → Task 2 (severity unchanged — not_live_yet yellow, ended red).
- §4 churn `@here` suppression for not_live_yet/ended → Task 3.
- §5 tests → Task 1 (classifier + status), Task 2 (reason enrichment + backward compat), Task 3 (predicate + suppression behaviour).
- Out of scope (slate, failover source) → not built; noted.

**Placeholder scan:** none. Task 3 Step 5 says "reuse the file's churn harness / nearest churn test's construction" — that is a locate-and-match of an existing fixture (the churn tests already build a relay with a store), with the concrete assertion given; it is not a logic placeholder. The exact `record_event`/`_relay_with_store` shape must match what `tests/test_health.py` already uses.

**Type consistency:** `classify_source_state(text) -> str|None` with states exactly `"not_live_yet"`/`"ended"`/`None`, used identically in `Feed.source_state`, `feed_source_states` map values, `churn_at_here_suppressed`, and the aggregate reasons. `on_recovery(feed, stint, downtime_s, source_state)` 4-arg matches `_record_feed_recovery(self, feed, stint, downtime_s, source_state=None)`. `feed_source_states` is `{name: state}` in both `_health_facts` and `aggregate_health`.
