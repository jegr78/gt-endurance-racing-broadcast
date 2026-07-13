# Report streamer-attribution fix (#500) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the post-event report so a same-URL back-to-back stint is attributed as two distinct stints (correct count + duration), and annotate a report window where a #494 ping-pong desync was active as unreliable.

**Architecture:** The relay samples the on-air stint into the per-profile health-history SQLite each heartbeat. Today it records the physical **pull index**; the report resolves per-commentator totals from it. We switch the sample to the **display stint** (`on_air_row_idx()+1`, already continuation-aware) so same-URL back-to-backs split into distinct stint bands, and we add a lossless health_store **v6** `desync_active` column that the relay samples from `self._desync` and the report surfaces as a `desync_seconds`-driven warning badge.

**Tech Stack:** Python 3 stdlib only. Tests are stdlib runnable scripts (`t_*` functions, no pytest). SQLite via `src/scripts/health_store.py`.

## Global Constraints

- **Edit only under `src/`.** `dist/`/`runtime/` are generated. `tests/` for tests.
- **English only** in all code/docs/comments.
- **Tests are stdlib runnable scripts** — run a whole file with `python3 tests/test_X.py`; run one function with `python3 -c "import sys; sys.path.insert(0,'tests'); import test_X as t; t.t_name()"`. No pytest.
- **Run `python3 tools/lint.py` after changing any Python file** (mirrors CI ruff).
- **`live_stint` has exactly one consumer** (`report_build._on_air`); it is charted **nowhere** in the Health-Monitor (absent from `health_store.BAND_FIELDS`/`NUMERIC_FIELDS`/`STATE_KEY_FIELDS`). The pull index stays reconstructable from `feed_a_stint`/`feed_b_stint` + `live_feed`.
- **Health-history is a schema-ish change** — the v6 migration must be lossless (old DBs get the column via `ALTER TABLE`, read `NULL`), and every new read must be NULL-tolerant. Old DBs keep pull-index `live_stint` values (historical events cannot be healed — documented, not fixed).
- **In `_health_snapshot`, `self._desync["active"]` is fresh:** `_heartbeat_loop` calls `_refresh_health` (→ `_compute_desync`) before `_health_snapshot` on the same `now`.

---

### Task 1: Core fix — sample the DISPLAY stint into `live_stint`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (the `_health_snapshot` `live_stint` line, ~5598)
- Test: `tests/test_pov.py` (relay snapshot shape), `tests/test_report_build.py` (report attribution)

**Interfaces:**
- Consumes: `Relay.on_air_row_idx()` → 0-based display row, continuation-aware, clamped. `Relay._health_snapshot(now)` → flat sample dict.
- Produces: `_health_snapshot(now)["live_stint"]` now equals `on_air_row_idx() + 1` (the display stint).

- [ ] **Step 1: Write the failing relay-snapshot test**

Add to `tests/test_pov.py` (reuse the continuation setup from `t_status_live_stint_reports_display_row_on_continuation`, ~line 405):

```python
def t_health_snapshot_live_stint_is_display_row_on_continuation():
    # Same-URL back-to-back: the DISPLAY stint (on_air_row_idx) is one ahead of the
    # still-parked physical pull. _health_snapshot must sample the display stint so the
    # report counts the continuation as a distinct stint (#500).
    rows = [("uA", "A", "Stint 1", 1), ("uB", "B", "Stint 2", 2),
            ("uB", "B", "Stint 3", 3), ("uD", "D", "Stint 4", 4)]
    rc = m.Relay(_StubSource(["uA", "uB", "uB", "uD"], rows), (53001, 53002), LOGDIR)
    rc._reflect = lambda live, cut: None
    for f in rc.feeds.values():
        f.phase = "serving"
    rc.next_auto()                                   # stint 2, real handover
    rc.next_auto()                                   # stint 3, continuation
    assert rc.on_air_row_idx() == 2                   # display row = stint 3
    assert rc.feeds[rc.live_feed()].idx != rc.on_air_row_idx()   # the divergence
    snap = rc._health_snapshot(123.0)
    assert snap["live_stint"] == rc.on_air_row_idx() + 1 == 3, snap["live_stint"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_health_snapshot_live_stint_is_display_row_on_continuation()"`
Expected: `AssertionError` — current code samples the pull index (`3` expected, `2` actual).

- [ ] **Step 3: Change the sample to the display stint**

In `src/relay/racecast-feeds.py::_health_snapshot`, replace the line:

```python
                "live_feed": live, "live_stint": self.feeds[live].idx + 1,
```

with:

```python
                # live_stint = the DISPLAY stint (who is on screen), continuation-aware
                # via on_air_row_idx() — NOT the physical pull index, so a same-URL
                # back-to-back counts as two distinct stints in the report (#500). The
                # pull index stays reconstructable from feed_a/b_stint + live_feed.
                "live_feed": live, "live_stint": self.on_air_row_idx() + 1,
```

- [ ] **Step 4: Run the relay-snapshot test — expect PASS**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_health_snapshot_live_stint_is_display_row_on_continuation()"`
Expected: no output (pass).

- [ ] **Step 5: Write the failing report back-to-back test**

Add to `tests/test_report_build.py` (near `t_build_report_on_air_names_and_fallback`, ~line 125):

```python
def t_on_air_back_to_back_same_url_counts_two_stints():
    # Display-stint samples: stint 1 then stint 2, the SAME commentator across a
    # same-URL back-to-back -> credited as TWO stints for that commentator, full
    # duration preserved (#500 Problem 1).
    samples = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1),
               _sample(60.0, live_stint=2), _sample(90.0, live_stint=2)]
    rep = rb.build_report(samples, [], {1: "Alice", 2: "Alice"},
                          "E", (0.0, 90.0), now=1000.0)
    alice = next(c for c in rep["on_air"]["commentators"] if c["name"] == "Alice")
    assert alice["stints"] == 2, rep["on_air"]
    assert alice["seconds"] == 90.0, rep["on_air"]
```

- [ ] **Step 6: Run it — expect PASS (report already reads `live_stint` correctly)**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_report_build as t; t.t_on_air_back_to_back_same_url_counts_two_stints()"`
Expected: no output (pass). This test locks in that the report attributes distinct display stints as distinct commentator stints — the behaviour the Task 1 sampling change now feeds it live.

- [ ] **Step 7: Run both full test files + lint**

Run: `python3 tests/test_pov.py && python3 tests/test_report_build.py && python3 tools/lint.py`
Expected: all pass, lint clean.

- [ ] **Step 8: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py tests/test_report_build.py
git commit -m "fix(report): sample the display stint into live_stint so same-URL back-to-backs count distinctly (#500)"
```

---

### Task 2: Persist `desync_active` — health_store v6 schema + relay sampling

**Files:**
- Modify: `src/scripts/health_store.py` (`SCHEMA_VERSION`, `COLUMNS`, `_CREATE`, add `_V6_COLUMNS`, `migrate`)
- Modify: `src/relay/racecast-feeds.py` (`_health_snapshot` — emit `desync_active`)
- Test: `tests/test_health_store.py` (v6 migration + round-trip), `tests/test_pov.py` (snapshot carries it)

**Interfaces:**
- Consumes: `Relay._desync` → `{"active": bool, ...}` (fresh per heartbeat ordering).
- Produces: health_store column `desync_active INTEGER`; `_health_snapshot(now)["desync_active"]` ∈ {0, 1}. Old DBs / old samples read `desync_active is None`.

- [ ] **Step 1: Write the failing v6 migration + round-trip test**

Add to `tests/test_health_store.py`:

```python
def t_migrate_adds_desync_active_v6_lossless():
    import tempfile, os, sqlite3
    d = tempfile.mkdtemp()
    path = os.path.join(d, "h.db")
    # A v5 DB by hand: full column set MINUS desync_active, user_version=5, one row.
    c = sqlite3.connect(path)
    try:
        c.executescript(
            "CREATE TABLE samples (ts REAL NOT NULL, kind TEXT NOT NULL, "
            "health_level TEXT, live_stint INTEGER);")   # minimal legacy subset
        c.execute("PRAGMA user_version=5")
        c.execute("INSERT INTO samples (ts, kind, health_level, live_stint) "
                  "VALUES (?,?,?,?)", (1000.0, "tick", "green", 7))
        c.commit()
    finally:
        c.close()
    conn = hs.open_db(path)
    try:
        hs.migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
        cols = {r[1] for r in conn.execute("PRAGMA table_info(samples)").fetchall()}
        assert "desync_active" in cols
        row = conn.execute("SELECT live_stint, desync_active FROM samples").fetchone()
        assert row[0] == 7 and row[1] is None      # legacy row lossless, new col NULL
    finally:
        conn.close()


def t_desync_active_round_trips():
    import tempfile, os
    d = tempfile.mkdtemp()
    conn = hs.open_db(os.path.join(d, "h.db"))
    try:
        hs.migrate(conn)
        hs.record(conn, {"ts": 5.0, "health_level": "green", "desync_active": 1}, "tick")
        got = hs.query_range(conn, 0, 10)[0]
        assert got["desync_active"] == 1, got
    finally:
        conn.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_health_store as t; t.t_migrate_adds_desync_active_v6_lossless()"`
Expected: `AssertionError` on `"desync_active" in cols` (column not added yet).

- [ ] **Step 3: Add the v6 column + bump the schema version**

In `src/scripts/health_store.py`:

1. Bump the version:
```python
SCHEMA_VERSION = 6
```

2. Add `"desync_active"` to the `COLUMNS` tuple, immediately after `"live_stint"`:
```python
    "mode", "live_feed", "live_stint", "desync_active",
```

3. Add `desync_active INTEGER,` to the `_CREATE` table body, on the line with `live_stint`:
```python
    mode TEXT, live_feed TEXT, live_stint INTEGER, desync_active INTEGER,
```

4. Add the v6 column tuple after `_V5_COLUMNS`:
```python
_V6_COLUMNS = (
    ("desync_active", "INTEGER"),
)
```

5. Include it in the `migrate` ALTER loop:
```python
    for name, decl in _V3_COLUMNS + _V5_COLUMNS + _V6_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE samples ADD COLUMN {name} {decl}")
```

- [ ] **Step 4: Run the health_store tests — expect PASS**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_health_store as t; t.t_migrate_adds_desync_active_v6_lossless(); t.t_desync_active_round_trips()"`
Expected: no output (pass).

- [ ] **Step 5: Write the failing snapshot-emit test**

Add to `tests/test_pov.py`:

```python
def t_health_snapshot_carries_desync_active():
    r = _make_min_relay()
    r._desync = {"active": True, "since_s": 20.0}
    assert r._health_snapshot(123.0)["desync_active"] == 1
    r._desync = {"active": False}
    assert r._health_snapshot(123.0)["desync_active"] == 0
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_health_snapshot_carries_desync_active()"`
Expected: `KeyError: 'desync_active'` (not emitted yet).

- [ ] **Step 7: Emit `desync_active` from the snapshot**

In `src/relay/racecast-feeds.py::_health_snapshot`, add the field directly after the `live_feed`/`live_stint` line (the one edited in Task 1):

```python
                "live_feed": live, "live_stint": self.on_air_row_idx() + 1,
                "desync_active": 1 if self._desync.get("active") else 0,
```

- [ ] **Step 8: Run the snapshot test + the COLUMNS-completeness guard**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_health_snapshot_carries_desync_active(); t.t_health_snapshot_carries_new_fields()"`
Expected: no output (pass). `t_health_snapshot_carries_new_fields` asserts every `COLUMNS` key is present in the snapshot — it now covers `desync_active` too.

- [ ] **Step 9: Run both full test files + lint**

Run: `python3 tests/test_health_store.py && python3 tests/test_pov.py && python3 tools/lint.py`
Expected: all pass, lint clean.

- [ ] **Step 10: Commit**

```bash
git add src/scripts/health_store.py src/relay/racecast-feeds.py tests/test_health_store.py tests/test_pov.py
git commit -m "feat(health): persist desync_active (health_store v6 + relay sample) (#500)"
```

---

### Task 3: Report desync annotation — `desync_seconds` + HTML warning badge

**Files:**
- Modify: `src/scripts/report_build.py` (`_on_air` returns `desync_seconds`; `render_html` renders the badge)
- Test: `tests/test_report_build.py`

**Interfaces:**
- Consumes: per-group samples each carrying `desync_active` ∈ {0, 1, None}; `hs.collapse_bands`, `_fill_gaps` (already imported/defined in `report_build.py`); `_esc`, `_fmt_dur`, the `caveat` CSS class (already used in `render_html`).
- Produces: `_on_air(...)["desync_seconds"]` → float total seconds a desync was active within the on-air-clipped groups; a `<p class='caveat'>` badge in the HTML when `> 0`.

- [ ] **Step 1: Write the failing `desync_seconds` test**

Add to `tests/test_report_build.py`:

```python
def t_on_air_desync_seconds_from_desync_active_bands():
    # A desync_active band contributes its (gap-filled) duration; a clean event -> 0;
    # old samples without the key -> 0 (NULL-tolerant).
    samples = [_sample(0.0, live_stint=1, desync_active=1),
               _sample(30.0, live_stint=1, desync_active=1),
               _sample(60.0, live_stint=1, desync_active=0)]
    rep = rb.build_report(samples, [], {1: "Alice"}, "E", (0.0, 60.0), now=1000.0)
    assert rep["on_air"]["desync_seconds"] > 0, rep["on_air"]

    clean = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1)]
    rep2 = rb.build_report(clean, [], {1: "Alice"}, "E", (0.0, 30.0), now=1000.0)
    assert rep2["on_air"]["desync_seconds"] == 0, rep2["on_air"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_report_build as t; t.t_on_air_desync_seconds_from_desync_active_bands()"`
Expected: `KeyError: 'desync_seconds'`.

- [ ] **Step 3: Compute `desync_seconds` in `_on_air`**

In `src/scripts/report_build.py::_on_air`, add a `desync_seconds` accumulator and return it. The full function becomes:

```python
def _on_air(sample_groups, name_for_stint):
    # Per-window bands (never bridged across an off-air stop/restart gap), so a
    # commentator's on-air seconds can never exceed the on-air window total.
    agg = {}          # name -> [seconds, set(stints)]
    resolved = bool(name_for_stint)
    non_null = []
    desync_seconds = 0.0
    for samples in sample_groups:
        bands = _fill_gaps(hs.collapse_bands(
            [(s["ts"], s.get("live_stint")) for s in samples]))
        for b in bands:
            st = b["state"]
            if st is None:
                continue
            st = int(st)
            name = name_for_stint.get(st) or f"Stint {st}"
            entry = agg.setdefault(name, [0.0, set()])
            entry[0] += b["to"] - b["from"]
            entry[1].add(st)
        non_null += [int(b["state"]) for b in bands if b["state"] is not None]
        # #500: total time a ping-pong desync (#494) was active within this window —
        # the report flags it as an "attribution may be unreliable" caveat. NULL/missing
        # desync_active (old DBs) collapses to a non-active band -> contributes 0.
        dbands = _fill_gaps(hs.collapse_bands(
            [(s["ts"], 1 if s.get("desync_active") else 0) for s in samples]))
        desync_seconds += sum(b["to"] - b["from"] for b in dbands if b["state"])
    handovers = sum(1 for i in range(1, len(non_null)) if non_null[i] != non_null[i - 1])
    commentators = sorted(
        ({"name": n, "seconds": round(v[0], 1), "stints": len(v[1])} for n, v in agg.items()),
        key=lambda c: -c["seconds"])
    return {"commentators": commentators, "stint_handovers": handovers,
            "resolved": resolved, "desync_seconds": round(desync_seconds, 1)}
```

- [ ] **Step 4: Run the `desync_seconds` test — expect PASS**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_report_build as t; t.t_on_air_desync_seconds_from_desync_active_bands()"`
Expected: no output (pass).

- [ ] **Step 5: Write the failing HTML-badge test**

Add to `tests/test_report_build.py`:

```python
def t_render_html_shows_desync_caveat_when_present():
    samples = [_sample(0.0, live_stint=1, desync_active=1),
               _sample(30.0, live_stint=1, desync_active=1),
               _sample(60.0, live_stint=1, desync_active=0)]
    rep = rb.build_report(samples, [], {1: "Alice"}, "GP", (0.0, 60.0), now=1000.0)
    assert "desync" in rb.render_html(rep).lower(), "desync caveat missing"
    # Clean event -> no desync caveat.
    clean = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1)]
    rep2 = rb.build_report(clean, [], {1: "Alice"}, "GP", (0.0, 30.0), now=1000.0)
    assert "desync" not in rb.render_html(rep2).lower()
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_report_build as t; t.t_render_html_shows_desync_caveat_when_present()"`
Expected: `AssertionError: desync caveat missing`.

- [ ] **Step 7: Render the badge in `render_html`**

In `src/scripts/report_build.py::render_html`, in the "On air per commentator" section, add the badge right after the existing resolved/unresolved caveat block (after the `else:` branch that appends the "Commentator names were unavailable" caveat):

```python
    if oa.get("desync_seconds", 0) > 0:
        parts.append(f"<p class='caveat'>&#9888; A ping-pong desync was active for "
                     f"{_esc(_fmt_dur(oa['desync_seconds']))} of this event — "
                     f"per-commentator attribution during those windows may be "
                     f"unreliable.</p>")
```

- [ ] **Step 8: Run the badge test + the self-contained-HTML guard**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_report_build as t; t.t_render_html_shows_desync_caveat_when_present(); t.t_render_html_is_self_contained()"`
Expected: no output (pass) — the badge uses only `&#9888;` (ASCII entity), no external URL.

- [ ] **Step 9: Run the full report test file + lint**

Run: `python3 tests/test_report_build.py && python3 tools/lint.py`
Expected: all pass, lint clean.

- [ ] **Step 10: Run the broader report + e2e-adjacent suites to catch consumers**

Run: `python3 tests/test_report.py && python3 tests/test_health_store.py && python3 tests/test_pov.py`
Expected: all pass (no consumer of the `_on_air` shape regressed by the added key).

- [ ] **Step 11: Commit**

```bash
git add src/scripts/report_build.py tests/test_report_build.py
git commit -m "feat(report): flag desync-active windows as unreliable attribution (#500)"
```

---

## Final verification (after all tasks)

- [ ] Run the whole suite exactly as CI does:

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all green, lint clean.

- [ ] Confirm no shipped `.sh`/`.bat` introduced and the build self-verify passes:

Run: `python3 tools/build.py`
Expected: builds `dist/` and passes its verify step (tokenization, no secrets, preflight present, no shell scripts).
