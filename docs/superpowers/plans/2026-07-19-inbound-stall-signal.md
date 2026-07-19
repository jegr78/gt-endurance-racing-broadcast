# Inbound feed-stall signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface inbound source-jitter that the current stack misses — record each feed's max inter-arrival gap per heartbeat, flip health to a **quiet yellow** (no Discord `@here`) when a gap exceeds the #533 reserve, and expose it in the DB, health monitor, and post-event report.

**Architecture:** The feed write loop tracks a per-feed max inbound gap; the heartbeat reads+resets it once per tick, computes a `feeds_jittery` set, and derives a **display** health (jitter yellow) plus a **notify** health (jitter excluded → never pages). Pure decisions in the relay module; DB columns via health_store's additive migration; a report row and health-monitor charts.

**Tech Stack:** Python 3 stdlib. Tests are stdlib runnable scripts (`t_*` auto-run). Health monitor is plain HTML/JS (uPlot).

## Global Constraints

- Edit only under `src/` (+ `tests/`, `docs/`, `.env.example`, committed wiki images). Never `dist/`/`runtime/`.
- Python + stdlib only; no new deps. English only. FeedRing "writer never blocks" invariant intact.
- The max-gap is **read+reset exactly once per heartbeat** (in the heartbeat loop). `_health_facts`/`_health_snapshot` (also called by `/status` every 2 s) must consume CACHED values, never reset.
- Quiet yellow: `aggregate_health` shows the jitter reason (display); the heartbeat pages on a **notify** level computed with `feeds_jittery` emptied. `health_should_notify`/`discord_health_payload` unchanged. Red/`@here` behavior unchanged.
- Threshold: `max_gap > max(prebuffer_s, floor_s)`; `feed_prebuffer_s` is #533's `feed_prebuffer_s(os.environ)`.
- `python3 tools/run-tests.py` + `python3 tools/lint.py` green at the end.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Pure decision, config, and the per-feed max-gap accumulator

**Files:**
- Modify: `src/relay/racecast-feeds.py` — constants + config helpers near `feed_prebuffer_s` (~line 371); a pure `feed_inbound_degraded` + `update_max_gap`; the feed `__init__` (`self.last_byte_ts = None`, ~line 5582) + the write loop (~line 5772)
- Modify: `.env.example`
- Test: `tests/test_fanout.py`

**Interfaces:**
- Produces:
  - `FEED_STALL_FLOOR_S = 1.0`
  - `feed_stall_floor_s(environ) -> float` (via `_env_float`, default `FEED_STALL_FLOOR_S`)
  - `feed_stall_signal_enabled(environ) -> bool` (default True; falsey token disables — mirror `fanout_enabled`)
  - `feed_inbound_degraded(max_gap_s, prebuffer_s, floor_s) -> bool` = `max_gap_s > max(prebuffer_s, floor_s)`
  - `update_max_gap(prev_max, last_byte_ts, now) -> float` — `prev_max` if `last_byte_ts is None`, else `max(prev_max, now - last_byte_ts)`
  - Feed attr `self._max_inbound_gap: float` + `take_max_inbound_gap() -> float` (returns and resets to 0.0)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fanout.py`)

```python
def t_feed_inbound_degraded_thresholds():
    # gap must exceed BOTH the reserve and the floor
    assert m.feed_inbound_degraded(0.5, 3.0, 1.0) is False   # below both
    assert m.feed_inbound_degraded(2.0, 3.0, 1.0) is False   # below the 3s reserve
    assert m.feed_inbound_degraded(3.5, 3.0, 1.0) is True    # above the reserve
    assert m.feed_inbound_degraded(1.5, 0.0, 1.0) is True    # prebuffer off -> floor governs
    assert m.feed_inbound_degraded(0.9, 0.0, 1.0) is False   # below the floor


def t_update_max_gap_tracks_and_ignores_none():
    assert m.update_max_gap(0.0, None, 100.0) == 0.0         # no prior byte -> unchanged
    assert m.update_max_gap(0.0, 98.0, 100.0) == 2.0         # 2s gap
    assert m.update_max_gap(2.0, 99.5, 100.0) == 2.0         # smaller gap keeps the max


def t_feed_stall_config():
    assert m.feed_stall_floor_s({}) == 1.0
    assert m.feed_stall_floor_s({"RACECAST_FEED_STALL_FLOOR_S": "0.5"}) == 0.5
    assert m.feed_stall_signal_enabled({}) is True
    assert m.feed_stall_signal_enabled({"RACECAST_FEED_STALL_SIGNAL": "0"}) is False
```

- [ ] **Step 2: Run — confirm RED**

Run: `python3 tests/test_fanout.py`
Expected: FAIL — `AttributeError: ... 'feed_inbound_degraded'`.

- [ ] **Step 3: Implement**

(a) Constants + config near `feed_prebuffer_s` (~line 371):
```python
FEED_STALL_FLOOR_S = 1.0          # #535: min inbound gap (s) that can count as a stall (prebuffer=0 guard)


def feed_stall_floor_s(environ):
    """Floor for the inbound-stall signal (#535). Pure."""
    return _env_float(environ, "RACECAST_FEED_STALL_FLOOR_S", FEED_STALL_FLOOR_S)


def feed_stall_signal_enabled(environ):
    """True unless RACECAST_FEED_STALL_SIGNAL is an explicit falsey token (#535). Default ON.
    When off the gap is still sampled to the DB but never contributes the yellow reason. Pure."""
    return str(environ.get("RACECAST_FEED_STALL_SIGNAL", "")).strip().lower() not in _FANOUT_FALSEY


def feed_inbound_degraded(max_gap_s, prebuffer_s, floor_s):
    """#535: an interval's max inbound inter-arrival gap is a stutter risk when it exceeds
    BOTH the #533 reserve (prebuffer_s — a gap the prebuffer absorbed is fine) and the floor
    (so prebuffer=0 still needs a real gap). Pure."""
    return max_gap_s > max(prebuffer_s, floor_s)


def update_max_gap(prev_max, last_byte_ts, now):
    """Fold one inter-arrival gap into the running per-interval max (#535). Pure: no prior
    byte -> unchanged; else max(prev, now-last_byte_ts)."""
    if last_byte_ts is None:
        return prev_max
    return max(prev_max, now - last_byte_ts)
```

(b) Feed `__init__`, after `self.last_byte_ts = None` (~line 5582):
```python
        self._max_inbound_gap = 0.0   # #535: largest inter-arrival gap this heartbeat interval
```

(c) The feed write loop (~line 5772-5774), fold the gap in BEFORE updating `last_byte_ts` (only while serving — this loop runs only while serving, and `last_byte_ts is None` guards the first byte / post-restart):
```python
                first = self.last_byte_ts is None
                _now = time.monotonic()
                self._max_inbound_gap = update_max_gap(self._max_inbound_gap, self.last_byte_ts, _now)
                self.ring.write(chunk)
                self.last_byte_ts = _now
```

(d) Add the take/reset method on the feed class (near `last_byte_ts` usage / a small method area):
```python
    def take_max_inbound_gap(self):
        """Return the largest inter-arrival gap seen since the last call, and reset (#535).
        Called once per heartbeat so a transient stall between 30 s ticks is still captured."""
        g = self._max_inbound_gap
        self._max_inbound_gap = 0.0
        return g
```

(e) `.env.example`, near the other `RACECAST_FEED_*`:
```bash
# RACECAST_FEED_STALL_SIGNAL=0           # #535: disable the inbound-stall yellow (gap still sampled to the DB)
# RACECAST_FEED_STALL_FLOOR_S=1.0        # #535: min inbound gap (s) that can count as a stall
```

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_fanout.py`
Expected: PASS.
```bash
git add src/relay/racecast-feeds.py .env.example tests/test_fanout.py
git commit -m "feat(relay): inbound feed-stall signal — pure decision + per-feed max-gap (#535)"
```

---

### Task 2: Heartbeat integration + quiet-yellow display/notify split

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `aggregate_health` (~line 762, add `feeds_jittery`); `Relay.__init__` (config + `self._jittery_feeds`/`self._interval_max_gaps`); `_health_facts` (~6086, add `feeds_jittery`); `_refresh_health` (~6137, return notify level); the heartbeat loop (~6262, read+reset gaps, compute jittery, page on notify level)
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `feed_inbound_degraded`, `feed_stall_*`, `feed_prebuffer_s` (Task 1 / #533), `take_max_inbound_gap` (Task 1).
- Produces: `aggregate_health` honours `facts["feeds_jittery"]` (list) → a yellow reason `"Feed X inbound stall (gap N.N s exceeded the N.N s reserve)"`; `Relay._interval_max_gaps: dict`, `Relay._jittery_feeds: list`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_health.py`; it already imports the relay module — reuse its alias)

```python
def t_aggregate_health_jitter_is_yellow_reason():
    facts = {"feeds_jittery": ["A"]}
    h = m.aggregate_health(facts)
    assert h["level"] == "yellow", h
    assert any("inbound stall" in r.lower() for r in h["reasons"]), h


def t_aggregate_health_no_jitter_is_green():
    assert m.aggregate_health({"feeds_jittery": []})["level"] == "green"


def t_jitter_yellow_does_not_page_but_real_yellow_does():
    # display includes jitter (yellow); notify excludes it (green) -> no page
    facts = {"feeds_jittery": ["A"]}
    display = m.aggregate_health(facts)["level"]
    notify = m.aggregate_health({**facts, "feeds_jittery": []})["level"]
    assert display == "yellow" and notify == "green"
    assert m.health_should_notify(None, notify) is False       # green baseline -> no page
    # a real yellow (e.g. cookies) still pages even with jitter present
    real = m.aggregate_health({**facts, "feeds_jittery": [], "cookies_stale": True})["level"]
    assert real == "yellow" and m.health_should_notify("green", real) is True
```

- [ ] **Step 2: Run — confirm RED**

Run: `python3 tests/test_health.py`
Expected: FAIL — jitter reason absent (level green).

- [ ] **Step 3: Implement**

(a) In `aggregate_health` (after the existing yellow reasons are assembled, before the green/return), add:
```python
    for name in facts.get("feeds_jittery") or []:
        yellow.append(f"Feed {name} inbound stall — a gap exceeded the fan-out reserve (stutter risk)")
```
(Place it with the other `yellow.append(...)` lines so it rolls into the same level logic.)

(b) `Relay.__init__` (near the other #488/#533 config, ~line 6014):
```python
        self._stall_signal = feed_stall_signal_enabled(os.environ)
        self._stall_floor = feed_stall_floor_s(os.environ)
        self._interval_max_gaps = {}      # #535: last heartbeat's per-feed max inbound gap
        self._jittery_feeds = []          # #535: feeds whose last-interval gap tripped the signal
```

(c) `_health_facts` return dict — add:
```python
                "feeds_jittery": list(self._jittery_feeds),
```

(d) `_refresh_health` — compute the notify level (jitter excluded) and return it. Change it to compute facts once:
```python
    def _refresh_health(self, now):
        facts = self._health_facts(now)
        h = aggregate_health(facts)
        notify_level = aggregate_health({**facts, "feeds_jittery": []})["level"]  # #535: jitter never pages
        with self._health_lock:
            if h["level"] != self.health_level:
                self.health_level = h["level"]
                self.health_since = now
            self.health_reasons = h["reasons"]
        self._compute_desync(now)
        h["notify_level"] = notify_level
        return h
```

(e) The heartbeat loop (~6262-6278): read+reset the gaps ONCE, compute the jittery set BEFORE `_refresh_health`, and page on the notify level:
```python
            now = time.time()
            self._maybe_probe_obs(now)
            self._sample_connectivity()
            # #535: read+reset each feed's interval max gap once per tick, classify jitter.
            pb = self.feed_prebuffer_s
            gaps, jittery = {}, []
            for _nm, _f in self.feeds.items():
                g = _f.take_max_inbound_gap()
                gaps[_nm] = g
                if (self._stall_signal and not _f.paused and _f.phase == "serving"
                        and feed_inbound_degraded(g, pb, self._stall_floor)):
                    jittery.append(_nm)
            self._interval_max_gaps = gaps
            self._jittery_feeds = jittery
            h = self._refresh_health(now)
            level = h["level"]
            if self.health_store is not None:
                try:
                    self.health_store.record_tick(self._health_snapshot(now), now)
                except Exception:  # noqa: BLE001 — sampling is best-effort
                    pass
            if self.health_store is not None and (now - self._last_prune) > 86400:
                try:
                    self.health_store.prune(); self._last_prune = now
                except Exception:  # noqa: BLE001 — best-effort
                    pass
            if health_should_notify(self._notified_level, h["notify_level"]):
                self._send_health_webhook(h["notify_level"], self.health_reasons, self._notified_level)
                self._notified_level = h["notify_level"]
```
(Preserve the existing `_maybe_auto_failover(now)` / `_check_render_drift(now)` calls that follow.)

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_health.py` then `python3 tests/test_pov.py`
Expected: both PASS.
```bash
git add src/relay/racecast-feeds.py tests/test_health.py
git commit -m "feat(relay): quiet-yellow inbound-stall health (display vs notify split) (#535)"
```

---

### Task 3: DB columns + heartbeat snapshot sampling

**Files:**
- Modify: `src/scripts/health_store.py` — `NUMERIC_FIELDS` (~line 44), `COLUMNS`/`_MIGRATIONS` (~line 54/107), the `CREATE TABLE` DDL (~line 84)
- Modify: `src/relay/racecast-feeds.py` — `_health_snapshot` (~6150) add the two fields from `self._interval_max_gaps`
- Test: `tests/test_health_store.py`

**Interfaces:**
- Produces: DB columns `feed_a_max_gap_s`, `feed_b_max_gap_s` (REAL), sampled each heartbeat.

- [ ] **Step 1: Write the failing test** (append to `tests/test_health_store.py`, mirroring its existing insert/read round-trip helper)

```python
def t_max_gap_columns_round_trip():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    store = hs.HealthStore(_os.path.join(d, "h.db"))
    store.record_tick({"feed_a_max_gap_s": 2.5, "feed_b_max_gap_s": 0.0}, 100.0)
    rows = store.samples_since(0.0)
    assert rows and rows[-1]["feed_a_max_gap_s"] == 2.5 and rows[-1]["feed_b_max_gap_s"] == 0.0
```
(If `HealthStore`/`samples_since` have different names in the file, use the file's real API — read its existing round-trip test and copy the pattern exactly; do not invent methods.)

- [ ] **Step 2: Run — confirm RED**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — column/key missing.

- [ ] **Step 3: Implement**

- Add `"feed_a_max_gap_s"`, `"feed_b_max_gap_s"` to `NUMERIC_FIELDS` (~44) and `COLUMNS` (~54) in the same style as the neighbours.
- Add to the `CREATE TABLE` DDL (~84) next to `sys_disk_free_mb`: `feed_a_max_gap_s REAL, feed_b_max_gap_s REAL`.
- Add both to the `_MIGRATIONS`/additive `ALTER TABLE ADD COLUMN` list (~107-115) so existing DBs gain the columns.
- In `_health_snapshot` (racecast-feeds.py ~6150), add to the returned dict:
```python
                "feed_a_max_gap_s": self._interval_max_gaps.get("A"),
                "feed_b_max_gap_s": self._interval_max_gaps.get("B"),
```

- [ ] **Step 4: Run — confirm GREEN + commit**

Run: `python3 tests/test_health_store.py`
Expected: PASS.
```bash
git add src/scripts/health_store.py src/relay/racecast-feeds.py tests/test_health_store.py
git commit -m "feat(health): sample per-feed inbound max-gap into health-history.db (#535)"
```

---

### Task 4: Report row + health-monitor charts

**Files:**
- Modify: `src/scripts/report_build.py` — `_quality` (~108) + the qrows table (~488)
- Modify: `src/console/health-monitor.html` — the metric list (~503-518)
- Refresh: `src/docs/wiki/images/health-monitor.png` (if the chart grid visibly changes) — via `wiki-screenshots`
- Test: `tests/test_report_build.py`

**Interfaces:**
- Consumes: DB columns `feed_a_max_gap_s`/`feed_b_max_gap_s` (Task 3).

- [ ] **Step 1: Write the failing test** (append to `tests/test_report_build.py`)

```python
def t_quality_includes_inbound_gap_peak():
    samples = [_sample(0.0, feed_a_max_gap_s=0.5, feed_b_max_gap_s=0.0),
               _sample(30.0, feed_a_max_gap_s=3.4, feed_b_max_gap_s=2.1)]
    q = rb._quality(samples)
    assert q["inbound_gap_peak"] == 3.4, q           # worst gap across both feeds
    html = rb.render_html(rb.build_report(samples, [], {}, "E", (0.0, 30.0), now=1.0, host="BOX"))
    assert "Max inbound gap (s)" in html
```

- [ ] **Step 2: Run — confirm RED** → `python3 tests/test_report_build.py` (KeyError `inbound_gap_peak`).

- [ ] **Step 3: Implement**

In `report_build.py` `_quality`, gather both feeds' gaps and take the peak:
```python
    gaps = _num(samples, "feed_a_max_gap_s") + _num(samples, "feed_b_max_gap_s")
```
add to the `if not any([...])` guard list, and to the returned dict:
```python
            "inbound_gap_peak": _peak(gaps),
```
In the qrows table (~488), add after the host rows (Task #536 rows):
```python
                 ("Max inbound gap (s)", "—", q["inbound_gap_peak"])]
```

In `src/console/health-monitor.html`, add to the metric list (~514-518, next to the `sys_*` charts):
```javascript
  ["feed_a_max_gap_s", "Feed A max gap (s)", "Feed stalls"],
  ["feed_b_max_gap_s", "Feed B max gap (s)", "Feed stalls"],
```

- [ ] **Step 4: Run — confirm GREEN**

Run: `python3 tests/test_report_build.py`
Expected: PASS.

- [ ] **Step 5: Verify the health-monitor render + refresh its screenshot** — REQUIRED SUB-SKILL: `ui-visual-verification` (health-monitor is a watched surface). Confirm the two "Feed stalls" charts render; if the chart grid visibly changed, regenerate `health-monitor.png` via `wiki-screenshots`. Record the verification marker for `src/console/health-monitor.html`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/report_build.py src/console/health-monitor.html tests/test_report_build.py src/docs/wiki/images/health-monitor.png
git commit -m "feat(report+monitor): surface per-feed inbound max-gap (#535)"
```

---

### Task 5: Full-suite + lint + build gate

- [ ] `python3 tools/run-tests.py` → ALL PASS. `python3 tools/lint.py` → clean. `python3 tools/build.py` → verify passes. Commit any fixups only if needed.

## Self-Review

- Spec §1 max-gap + §2 pure decision → Task 1. ✅
- Spec §3 quiet-yellow display/notify split → Task 2 (aggregate_health jitter reason + `_refresh_health` notify level + heartbeat page-on-notify). ✅
- Spec §4 DB → Task 3; monitor + report → Task 4. ✅
- Spec §5 config (floor, kill-switch) → Task 1 (+ `.env.example`). ✅
- Spec §Scope no-new-auto-recovery → nothing added to the freeze detector; not a task. ✅
- Read+reset once per heartbeat (constraint) → Task 2 Step 3(e) reads in the loop; `_health_facts`/`_health_snapshot` consume `self._jittery_feeds`/`self._interval_max_gaps` (Task 2/3). ✅
- No placeholders; every code step shows code; every run step shows command + expected output.
- Type consistency: `feed_inbound_degraded(max_gap_s, prebuffer_s, floor_s)`, `update_max_gap(prev, last_byte_ts, now)`, `take_max_inbound_gap()`, `feeds_jittery` list, `_interval_max_gaps` dict, `inbound_gap_peak`, columns `feed_a/b_max_gap_s` — consistent across tasks.
