# Ad-hoc Stream Substitution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-record an ad-hoc on-air stream substitution (the producer swaps the on-air commentator stream to a different URL mid-stint), announce it on Discord, let directors attach a reason from the Director Panel (over Funnel), and surface substitutions in the post-event report.

**Architecture:** Detection is a pure predicate evaluated in `Relay.reload()` by comparing the on-air feed's URL before vs after the schedule refresh (a same-stint URL change = a substitution). Capture records a `feed_substitution` Health-DB event (feed + stint only — no raw URLs) and fires a best-effort Discord post. A director-gated `/substitution/note` annotates the latest event; the report aggregates them like `takeover` events.

**Tech Stack:** Python 3 stdlib only. Relay = self-contained `src/relay/racecast-feeds.py`; pure helpers in `src/scripts/{notify,health_store,report_build,console_policy}.py`; Director Panel = `src/director/director-panel.html`. Tests are plain runnable scripts (no pytest).

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `src/docs/wiki/images/`). Never touch `dist/`/`runtime/`.
- **stdlib only** — no new dependencies. The relay must NOT import new third-party modules.
- **All code/comments/docs English only.**
- **Store feed + stint only — never raw stream URLs** in the event metadata or the report (avoids leaking unlisted links into a shareable Discord report).
- **Discord post on capture is `ping=False`** (the outage already pinged `@here`; the substitution is a follow-up recovery marker).
- **The note endpoints are director-gated and Funnel-reachable** under `/console` (directors control everything and act over Funnel), mirroring `/cues/*`.
- Tests run on any machine/CI — no real IPs/URLs/paths; use existing fixtures.
- Run `python3 tools/run-tests.py` + `python3 tools/lint.py` before the final commit; run `python3 tools/build.py` in the final task. **Run every test command in the FOREGROUND — never background a test run.**
- Spec: `docs/superpowers/specs/2026-07-03-ad-hoc-stream-substitution-design.md`.

### Reference: running tests
Full file: `python3 tests/test_pov.py`. Whole suite: `python3 tools/run-tests.py`. One function:
`python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_name()"`.

---

### Task 1: Pure helpers (Discord payload, detection predicate, reason sanitizer)

**Files:**
- Modify: `src/scripts/notify.py` (add a color constant + `substitution_discord_payload`, after `obs_stream_discord_payload` ~line 65)
- Modify: `src/relay/racecast-feeds.py` (add `is_substitution` + `sanitize_reason` + `SUBSTITUTION_REASON_MAX`, immediately after `stint_start_indices`/the slot helpers, ~line 3296)
- Test: `tests/test_notify.py`, `tests/test_pov.py`

**Interfaces:**
- Produces:
  - `notify.substitution_discord_payload(feed, stint, producer, event_title="") -> dict`
  - `is_substitution(served_url, served_idx, new_url, new_idx) -> bool`
  - `sanitize_reason(text) -> str`, `SUBSTITUTION_REASON_MAX = 200`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_notify.py`:

```python
def t_substitution_payload():
    p = m.substitution_discord_payload("A", 3, "JeGr", event_title="6h Spa")
    assert p["username"] == m.USERNAME
    assert "content" not in p                       # ping=False: no @here
    e = p["embeds"][0]
    assert e["color"] == m.COLOR_SUBSTITUTION
    assert "Feed A" in e["description"] and "stint 3" in e["description"]
    assert e["footer"]["text"] == "6h Spa · JeGr"   # event_title · producer
```

Add to `tests/test_pov.py`:

```python
def t_is_substitution():
    assert m.is_substitution("uA", 1, "uB", 1) is True      # same stint, new URL
    assert m.is_substitution("uA", 1, "uA", 1) is False     # same URL -> reconnect, not a swap
    assert m.is_substitution("uA", 1, "uB", 2) is False     # different stint -> handover, not a swap
    assert m.is_substitution("", 1, "uB", 1) is False       # no prior served URL
    assert m.is_substitution("uA", 1, "", 1) is False       # cleared URL, not a swap


def t_sanitize_reason():
    assert m.sanitize_reason("  stream A dropped  ") == "stream A dropped"
    assert m.sanitize_reason("line1\nline2\tx") == "line1 line2 x"   # control chars -> single spaces
    assert m.sanitize_reason(None) == "" and m.sanitize_reason(123) == ""
    assert len(m.sanitize_reason("x" * 500)) == m.SUBSTITUTION_REASON_MAX
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_notify.py` and `python3 tests/test_pov.py`
Expected: FAIL with `AttributeError` on the missing names.

- [ ] **Step 3: Implement**

In `src/scripts/notify.py`, after `obs_stream_discord_payload`:

```python
COLOR_SUBSTITUTION = 0xF59E0B  # amber — an ad-hoc on-air stream swap (recovery marker)


def substitution_discord_payload(feed, stint, producer, event_title=""):
    """Announce an ad-hoc on-air stream substitution: the producer swapped the
    on-air commentator stream to an alternative mid-stint. `feed` is "A"/"B",
    `stint` is 1-based. Amber, NO @here — the outage that prompted the swap already
    pinged; this is a follow-up recovery marker. Pure."""
    desc = (f"The on-air stream on Feed {feed} was substituted mid-stint "
            f"(stint {stint}).")
    return _payload("🔁 Stream substituted", desc, COLOR_SUBSTITUTION, ping=False,
                    event_title=event_title, producer=producer)
```

In `src/relay/racecast-feeds.py`, after `stint_start_indices`/the slot helpers:

```python
SUBSTITUTION_REASON_MAX = 200


def is_substitution(served_url, served_idx, new_url, new_idx):
    """True when the on-air feed swaps to a DIFFERENT non-empty URL at the SAME
    stint index (an operator reload after editing the on-air URL) — an ad-hoc
    stream substitution. A same-URL reconnect or a stint change is not one. Pure."""
    return (bool(new_url) and bool(served_url)
            and new_idx == served_idx and new_url != served_url)


def sanitize_reason(text):
    """Clean a free-text substitution reason: non-str -> ''; strip control chars,
    collapse all whitespace to single spaces, trim, cap at SUBSTITUTION_REASON_MAX.
    Rendered via textContent client-side, but sanitized here too (defense in depth).
    Pure."""
    if not isinstance(text, str):
        return ""
    kept = "".join(ch for ch in text if ch >= " ")   # drop \n\t and other controls
    return " ".join(kept.split())[:SUBSTITUTION_REASON_MAX].strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_notify.py` and `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py` (clean), then:

```bash
git add src/scripts/notify.py src/relay/racecast-feeds.py tests/test_notify.py tests/test_pov.py
git commit -m "feat(relay): pure helpers for stream-substitution capture (payload/detect/sanitize)"
```

---

### Task 2: `health_store.annotate_latest_event` + HealthStore wrapper

**Files:**
- Modify: `src/scripts/health_store.py` (add `annotate_latest_event`, after `query_events` ~line 197)
- Modify: `src/relay/racecast-feeds.py` (add a `HealthStore.annotate_latest_event` wrapper, next to `events`/`record_event` ~line 2215)
- Test: `tests/test_health_store.py`

**Interfaces:**
- Produces:
  - `health_store.annotate_latest_event(conn, event_type, patch) -> dict | None`
  - `HealthStore.annotate_latest_event(self, event_type, patch) -> dict | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_health_store.py` (use the module's existing open/temp-db pattern; if a helper like `_db()` exists, reuse it — otherwise open an in-memory db as shown):

```python
def t_annotate_latest_event():
    import sqlite3
    conn = m.open_db(":memory:"); m.migrate(conn)
    m.record_event(conn, 100.0, "feed_substitution", metadata={"feed": "A", "stint": 2})
    m.record_event(conn, 200.0, "feed_substitution", metadata={"feed": "B", "stint": 4})
    m.record_event(conn, 300.0, "takeover", metadata={"stint": 5})
    out = m.annotate_latest_event(conn, "feed_substitution", {"reason": "A dropped"})
    assert out["ts"] == 200.0 and out["metadata"] == {"feed": "B", "stint": 4, "reason": "A dropped"}
    # only the latest substitution got the reason; the earlier one is untouched
    evs = m.query_events(conn, 0, 1e12)
    subs = [e for e in evs if e["type"] == "feed_substitution"]
    assert subs[0]["metadata"] == {"feed": "A", "stint": 2}       # no reason
    assert subs[1]["metadata"].get("reason") == "A dropped"
    # the takeover event is untouched
    assert [e for e in evs if e["type"] == "takeover"][0]["metadata"] == {"stint": 5}
    # None when no such event
    assert m.annotate_latest_event(conn, "nope", {"reason": "x"}) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL with `AttributeError: module ... has no attribute 'annotate_latest_event'`.

- [ ] **Step 3: Implement**

In `src/scripts/health_store.py`, after `query_events`:

```python
def annotate_latest_event(conn, event_type, patch):
    """Merge dict `patch` into the metadata of the MOST RECENT event of
    `event_type` (by ts, then rowid). Returns the updated event as a dict (metadata
    parsed back), or None when no such event exists. Used to attach a reason to the
    latest stream substitution."""
    row = conn.execute(
        "SELECT rowid, ts, type, label, producer, metadata FROM events "
        "WHERE type=? ORDER BY ts DESC, rowid DESC LIMIT 1", (event_type,)).fetchone()
    if row is None:
        return None
    rowid, ts, etype, label, producer, raw = row
    md = json.loads(raw) if raw else {}
    md.update(patch)
    conn.execute("UPDATE events SET metadata=? WHERE rowid=?", (json.dumps(md), rowid))
    conn.commit()
    return {"ts": ts, "type": etype, "label": label or "",
            "producer": producer or "", "metadata": md}
```

In `src/relay/racecast-feeds.py`, in the `HealthStore` class after `events`:

```python
    def annotate_latest_event(self, event_type, patch):
        with self.lock:
            return health_store.annotate_latest_event(self.conn, event_type, patch)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_health_store.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/health_store.py src/relay/racecast-feeds.py tests/test_health_store.py
git commit -m "feat(health): annotate_latest_event to attach metadata to the newest event of a type"
```

---

### Task 3: Relay capture in `reload` + Discord + read/annotate methods

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.reload` (~line 5319); add `Relay._record_substitution`, `Relay.latest_substitution`, `Relay.annotate_substitution_reason` (next to `reload`)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `is_substitution`, `sanitize_reason` (Task 1); `notify.substitution_discord_payload` (Task 1); `HealthStore.record_event/events/annotate_latest_event` (Task 2); `Relay.live_feed`, `Feed.current_channel`, `self._discord_post`, `self._event_title`, `self.producer_name`, `self.health_store` (default `None`).
- Produces:
  - `Relay.latest_substitution() -> {"ts","feed","stint","reason"} | None`
  - `Relay.annotate_substitution_reason(reason) -> {"ts",...} | {"error": str}`
  - capture side effect inside `Relay.reload`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pov.py` (extends the existing `_StubSource`/`_relay` fixtures with a staged-URL stub and a real temp `HealthStore`):

```python
def t_reload_records_substitution_on_url_swap():
    import tempfile
    # a stub whose refresh() applies a staged URL change (mimics the operator
    # editing the on-air row's URL then pressing Reload)
    class _Staged(_StubSource):
        def __init__(self, items):
            super().__init__(items)
            self._pending = None
        def stage(self, idx, url): self._pending = (idx, url)
        def refresh(self, timeout=6):
            if self._pending:
                i, u = self._pending
                self._items[i] = u
                self._rows[i] = (u,) + tuple(self._rows[i][1:])
                self._pending = None
            return True

    td = tempfile.mkdtemp()
    r = m.Relay(_Staged(["uA", "uB"]), (53001, 53002), LOGDIR)
    r._reflect = lambda live, cut: None
    posts = []
    r._discord_post = lambda payload, what: posts.append((what, payload))
    r.health_store = m.HealthStore(os.path.join(td, "h.db"))
    try:
        assert r.live_feed() == "A"                    # A (uA, idx0) on air
        r.source.stage(0, "uALT")                      # on-air row gets a new URL
        r.reload()                                     # operator force-reload
        subs = [e for e in r.health_store.events(0, 1e12) if e["type"] == "feed_substitution"]
        assert len(subs) == 1
        assert subs[0]["metadata"] == {"feed": "A", "stint": 1}   # feed+stint only, NO url
        assert posts and posts[0][0] == "feed-substitution"       # Discord fired
        # a same-URL reload records nothing more
        r.reload()
        subs2 = [e for e in r.health_store.events(0, 1e12) if e["type"] == "feed_substitution"]
        assert len(subs2) == 1
    finally:
        r.health_store.close()


def t_latest_and_annotate_substitution():
    import tempfile
    td = tempfile.mkdtemp()
    r = _relay(["uA", "uB"])
    r.health_store = m.HealthStore(os.path.join(td, "h.db"))
    try:
        assert r.latest_substitution() is None
        assert r.annotate_substitution_reason("x")["error"]        # nothing to annotate
        r.health_store.record_event(111.0, "feed_substitution", metadata={"feed": "A", "stint": 1})
        assert r.latest_substitution() == {"ts": 111.0, "feed": "A", "stint": 1, "reason": ""}
        out = r.annotate_substitution_reason("  stream A\ndropped  ")
        assert out["reason"] == "stream A dropped"                  # sanitized
        assert r.latest_substitution()["reason"] == "stream A dropped"
    finally:
        r.health_store.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL (`AttributeError` on `latest_substitution`; the reload test finds no `feed_substitution` event).

- [ ] **Step 3: Implement**

Replace `Relay.reload` (currently `~5319-5326`) with the capture-aware version:

```python
    def reload(self, which=None):
        # Detect an ad-hoc on-air stream substitution: the operator edited the
        # on-air feed's URL then pressed Reload, so the on-air feed's URL changes
        # at the SAME stint across the schedule refresh. Captured before feeds
        # actually reconnect; best-effort, never blocks the reload.
        live = self.live_feed()
        old_url, old_idx = self.feeds[live].current_channel()
        self.source.refresh(timeout=6)
        new_url, new_idx = self.feeds[live].current_channel()
        if (which is None or which.upper() == live) and \
                is_substitution(old_url, old_idx, new_url, new_idx):
            self._record_substitution(live, new_idx)
        targets = [which.upper()] if which else list(self.feeds)
        for t in targets:
            if t in self.feeds: self.feeds[t].reload()
        LOG.info("reload: schedule re-read (%d stints), feeds %s",
                 len(self.source.get()), ",".join(targets))
        return {"reloaded": targets, **self.status()}

    def _record_substitution(self, feed, idx):
        """Record + announce an ad-hoc on-air stream substitution (best-effort):
        a discrete Health event (feed + 1-based stint only, NO url) plus a Discord
        post. A missing health_store or webhook is a silent no-op."""
        stint = idx + 1
        if self.health_store is not None:
            try:
                self.health_store.record_event(
                    time.time(), "feed_substitution", producer=self.producer_name,
                    metadata={"feed": feed, "stint": stint})
            except Exception:                # noqa: BLE001 — best-effort
                pass
        self._discord_post(
            notify.substitution_discord_payload(feed, stint, self.producer_name,
                                                 self._event_title()),
            "feed-substitution")
        LOG.info("stream substitution recorded: Feed %s stint %d", feed, stint)

    def latest_substitution(self):
        """The most recent feed_substitution event as
        {"ts","feed","stint","reason"}, or None. Read side for the Director Panel's
        substitution section."""
        if self.health_store is None:
            return None
        try:
            events = self.health_store.events(0, time.time())
        except Exception:                    # noqa: BLE001 — best-effort read
            return None
        subs = [e for e in events if e.get("type") == "feed_substitution"]
        if not subs:
            return None
        e = subs[-1]                         # events() is ascending -> last = newest
        md = e.get("metadata") or {}
        return {"ts": e.get("ts"), "feed": md.get("feed") or "",
                "stint": md.get("stint"), "reason": md.get("reason") or ""}

    def annotate_substitution_reason(self, reason):
        """Attach a sanitized free-text reason to the latest feed_substitution
        event (director action from the panel). Returns the updated
        latest_substitution() shape, or {"error": ...} when disabled/absent."""
        if self.health_store is None:
            return {"error": "health history disabled"}
        updated = self.health_store.annotate_latest_event(
            "feed_substitution", {"reason": sanitize_reason(reason)})
        if updated is None:
            return {"error": "no substitution to annotate"}
        return self.latest_substitution()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: PASS. Also confirm the existing reload test (if any) still passes.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): capture + announce ad-hoc on-air stream substitution on reload"
```

---

### Task 4: Endpoints (`/substitution/latest`, `/substitution/note`) + console gating

**Files:**
- Modify: `src/scripts/console_policy.py` — add a `substitution` rule in `min_capability` (next to the `cues` rule ~line 100)
- Modify: `src/relay/racecast-feeds.py` — a root GET `/substitution/latest` (next to `crew/data` ~line 6754) and a root POST `/substitution/note` (next to `cues/send` ~line 6942)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `Relay.latest_substitution`, `Relay.annotate_substitution_reason` (Task 3).
- Produces: `min_capability(["substitution", ...]) -> Requirement(DIRECTOR, False)`; the two routes.

**Coverage note:** the two routes are one-line delegations to the Task-3 relay methods (unit-tested) gated by the Task-4 `console_policy` rule (unit-tested here). The task reviewer verifies the two-line wiring; no separate HTTP integration test is added (the delegation carries no logic of its own).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_console.py` (mirrors the existing `min_capability`/`Requirement` assertions):

```python
def t_substitution_is_director_gated():
    assert m.min_capability(["substitution", "latest"]) == m.Requirement(m.DIRECTOR, False)
    assert m.min_capability(["substitution", "note"], "POST") == m.Requirement(m.DIRECTOR, False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL — `min_capability` returns None (route not recognized), so the assertion fails.

- [ ] **Step 3: Implement**

In `src/scripts/console_policy.py`, in `min_capability`, immediately after the `cues` rule (`if p and p[0] == "cues": return Requirement(DIRECTOR, False)`):

```python
    if p and p[0] == "substitution":            # /substitution/latest (GET) + /note (POST)
        return Requirement(DIRECTOR, False)
```

In `src/relay/racecast-feeds.py`, add the GET route next to `crew/data`:

```python
                if p == ["substitution", "latest"]:
                    # Director-panel read side for the ad-hoc stream-substitution
                    # section. Root path; mirrored at /console/substitution/latest
                    # (director-gated) via console_policy + the gate's ALLOW
                    # fall-through, so a director reaches it over the Funnel.
                    return self._send({"substitution": relay.latest_substitution()})
```

And the POST route next to `cues/send` (in the POST dispatch, where `body` is available):

```python
                if p == ["substitution", "note"]:
                    return self._send(relay.annotate_substitution_reason(body.get("reason")))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_console.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py src/relay/racecast-feeds.py tests/test_console.py
git commit -m "feat(relay): director-gated /substitution/{latest,note} endpoints (Funnel-reachable)"
```

---

### Task 5: Report aggregation + rendering

**Files:**
- Modify: `src/scripts/report_build.py` — collect substitutions in `build_report` (~line 146) + a render section in `render_html` (after the incidents section ~line 306)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: the `feed_substitution` event shape `{ts, type, metadata:{feed, stint, reason?}}`; `name_for_stint` — a **dict** `{stint: name}` keyed by **1-based stint** (NOT a callable; the file accesses it as `name_for_stint.get(st)` in `_on_air`, and our stored `stint = idx+1` uses the same 1-based key).
- Produces: `report["substitutions"]` list; a "Stream substitutions" HTML section.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_report.py` (mirror the existing `build_report`/`render_html` tests — reuse their sample/name-resolver fixtures; the snippet below shows the minimal shape):

```python
def t_report_collects_and_renders_substitutions():
    samples = [{"ts": 100.0, "health_level": "green"}, {"ts": 160.0, "health_level": "green"}]
    events = [
        {"ts": 130.0, "type": "feed_substitution", "metadata": {"feed": "A", "stint": 2, "reason": "A dropped"}},
        {"ts": 150.0, "type": "feed_substitution", "metadata": {"feed": "B", "stint": 3}},
        {"ts": 140.0, "type": "takeover", "producer": "B", "metadata": {"from": "A", "stint": 2}},
    ]
    names = {2: "Ann", 3: "Bob"}                    # name_for_stint is a DICT, keyed 1-based
    rep = m.build_report(samples, events, names, "6h Spa", (100.0, 160.0), 200.0)
    subs = rep["substitutions"]
    assert [s["feed"] for s in subs] == ["A", "B"]
    assert subs[0] == {"ts": 130.0, "feed": "A", "stint": 2, "streamer": "Ann", "reason": "A dropped"}
    assert subs[1]["streamer"] == "Bob" and subs[1]["reason"] == ""
    html = m.render_html(rep)
    assert "Stream substitutions" in html and "Ann" in html and "A dropped" in html
    # empty case renders no section
    rep0 = m.build_report(samples, [], {}, "", (100.0, 160.0), 200.0)
    assert rep0["substitutions"] == []
    assert "Stream substitutions" not in m.render_html(rep0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_report.py`
Expected: FAIL — `report["substitutions"]` KeyError / no section in HTML.

- [ ] **Step 3: Implement**

In `src/scripts/report_build.py`, inside `build_report`, alongside the `handovers` loop (extend the SAME `for e in events` loop or add a parallel comprehension):

```python
    substitutions = []
    for e in events:
        if e.get("type") == "feed_substitution":
            md = e.get("metadata") or {}
            substitutions.append({"ts": e.get("ts"), "feed": md.get("feed") or "",
                                  "stint": md.get("stint"),
                                  "streamer": name_for_stint.get(md.get("stint")) or "",
                                  "reason": md.get("reason") or ""})
```

and add `"substitutions": substitutions,` to the returned report dict.

In `render_html`, after the incidents section, add (matching the surrounding `_table`/section style):

```python
    if report.get("substitutions"):
        parts.append("<h2>Stream substitutions</h2>")
        parts.append("<p class='note'>Ad-hoc on-air stream swaps (the on-air feed was "
                     "pointed at an alternative source mid-stint).</p>")
        srows = [(_fmt_clock(s["ts"]), s["feed"], s["stint"],
                  _esc(s["streamer"]), _esc(s["reason"]))
                 for s in report["substitutions"]]
        parts.append(_table(["Time", "Feed", "Stint", "Commentator", "Reason"], srows))
```

(Use the exact `_fmt_clock`, `_esc`, `_table` helpers already in the file. If the incidents KPI tile pattern is trivial to extend with a substitution count, do so next to it; otherwise the section alone satisfies the spec.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_report.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/report_build.py tests/test_report.py
git commit -m "feat(report): surface ad-hoc stream substitutions in the post-event report"
```

---

### Task 6: Director Panel "Stream substitutions" section (styling parity + wiki screenshot)

**Files:**
- Modify: `src/director/director-panel.html` — a new `<section class="bus">` + its poll/save JS
- Modify: `src/docs/wiki/images/director-panel.png` — refreshed screenshot
- Test: none (HTML/CSS/JS); verified visually.

**Interfaces:**
- Consumes: `GET /substitution/latest` (returns `{substitution: {ts,feed,stint,reason}|null}`), `POST /substitution/note` (body `{reason}`) from Task 4. Fetches use the panel's existing `RC_API(...)` shim so they resolve under `/console` over the Funnel (find how neighboring fetches like `/cues/data` are wrapped and match them).

- [ ] **Step 1: Add the section markup (styling parity)**

Add a section that matches the existing `<section class="bus">` blocks exactly (same `cap` label header as the Feeds/HUD/Scn·Vis sections, `src/director/director-panel.html`). Give it a stable id and hide it by default (self-hides when there is no substitution, like the broadcast-chat card):

```html
  <section class="bus" id="subSec" style="display:none">
    <div class="cap">Substitution</div>
    <div class="setrow">
      <span id="subInfo" class="muted"></span>
      <input id="subReason" type="text" maxlength="200" placeholder="reason (optional)">
      <button id="subSave">Save</button>
    </div>
  </section>
```

Match the existing input/button/`muted` classes and spacing used elsewhere in the panel — do NOT introduce new bespoke styles; reuse the panel's existing form control CSS. If the panel has no `.muted`/input styling that fits, use the same classes the Setup/HUD rows use.

- [ ] **Step 2: Wire the poll + save JS**

Mirror an existing polled section (e.g. how `/cues/data` or `/status` is polled and how `/cues/send` is POSTed). Render the info via `textContent` (XSS-safe). Self-hide when `substitution` is null:

```javascript
function subPoll(){
  fetch(RC_API("/substitution/latest")).then(r=>r.json()).then(d=>{
    var s = d && d.substitution;
    var sec = document.getElementById("subSec");
    if(!s){ sec.style.display="none"; return; }
    sec.style.display="";
    var when = new Date((s.ts||0)*1000).toLocaleTimeString();
    document.getElementById("subInfo").textContent =
      "Feed "+s.feed+" · "+when+" · Stint "+s.stint;
    var inp = document.getElementById("subReason");
    if(document.activeElement !== inp){ inp.value = s.reason || ""; }
  }).catch(function(){ /* Funnel/tailnet 404 or error -> leave as-is */ });
}
document.getElementById("subSave").addEventListener("click", function(){
  fetch(RC_API("/substitution/note"), {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({reason: document.getElementById("subReason").value})})
    .then(function(){ subPoll(); });
});
```

Hook `subPoll` into the panel's existing poll loop/interval (find where the other sections are polled and add it there — do NOT add a second independent timer if one already drives the sections).

- [ ] **Step 3: Verify it renders (ui-visual-verification)**

Invoke the `ui-visual-verification` skill: run a local dev build of the Director Panel with a staged substitution (record a `feed_substitution` event in the profile's health DB, or trigger a real reload URL swap), confirm the section appears, matches the surrounding sections' styling (cap label, spacing, input/button), the info line is correct, and Save persists the reason (re-poll shows it). Record the required verification marker.

- [ ] **Step 4: Refresh the wiki screenshot**

Regenerate `src/docs/wiki/images/director-panel.png` via the `wiki-screenshots` skill (demo profile + obs-sim recipe) so it shows the panel including the new section, and commit it alongside the HTML.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): Director Panel stream-substitution section + refreshed wiki shot"
```

---

### Task 7: Full regression, lint, build

**Files:** none (verification only).

- [ ] **Step 1: Whole suite** — `python3 tools/run-tests.py` → ALL TEST FILES PASS (watch `test_notify.py`, `test_pov.py`, `test_health_store.py`, `test_console.py`, `test_report.py`).
- [ ] **Step 2: Lint** — `python3 tools/lint.py` → no findings.
- [ ] **Step 3: Build self-verify** — `python3 tools/build.py` → verify passes (a benign "no Sheet ID" OBS-localize line is fine; build exits 0).
- [ ] **Step 4: Manual re-read** — confirm in `Relay.reload`: (a) the substitution check runs BEFORE the feeds reconnect and only for the on-air feed; (b) `metadata` carries `feed`+`stint` only (no URL); (c) the Discord payload is `ping=False`. These are the three spec invariants.
- [ ] **Step 5: Commit any fixups** — `git add -A && git commit -m "test: regression pass for stream substitution" || echo "nothing to commit"`.

---

## Self-Review

**Spec coverage:**
- Auto-detect + capture (spec §1) → Task 1 (`is_substitution`), Task 3 (`Relay.reload` + `_record_substitution`).
- No raw URLs, feed+stint only (spec §1/§Scope) → Task 3 metadata; asserted in `t_reload_records_substitution_on_url_swap`.
- Discord on capture, yellow/no-ping (spec §2) → Task 1 payload + Task 3 `_discord_post`; asserted in `t_substitution_payload`.
- Reason nachtragbar (spec §3) → Task 2 (`annotate_latest_event`), Task 3 (`annotate_substitution_reason`), Task 4 (endpoints), Task 6 (Panel).
- Director-gated + Funnel-reachable (spec §3, user correction) → Task 4 `console_policy` rule.
- Report rendering (spec §4) → Task 5.
- Multi-machine/takeover → no code (events ride the existing Health-DB pull); noted, not a task.
- Styling parity + wiki screenshot + visual verify (spec §3) → Task 6.

**Placeholder scan:** none — every code step shows complete code; Task 6 is HTML/JS with the exact markup + a stated "match neighbor" rule (unavoidable for CSS parity, bounded by ui-visual-verification).

**Type consistency:** `is_substitution(served_url, served_idx, new_url, new_idx) -> bool`; `sanitize_reason(str)->str`; `substitution_discord_payload(feed, stint, producer, event_title="")->dict`; `annotate_latest_event(conn, event_type, patch)->dict|None` (+ HealthStore wrapper same name); `latest_substitution()->dict|None`; `annotate_substitution_reason(reason)->dict`. Event type string is `"feed_substitution"` everywhere; metadata keys `feed`/`stint`/`reason` consistent across Tasks 3/5/6. HealthStore read method is `events(frm, to)` (not `query_events`).
