# Event Stop → Report flow + report fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ending the last broadcast part auto-generates the post-event report, posts it to Discord, and stops the racecast services — and the report itself is corrected (seconds, real incident durations, broadcast timeline, intentional off-air excluded) and posts as a proper "GT Racecast" embed with a download-only attachment.

**Architecture:** The reporting + Discord logic stays in ONE place (the `racecast` CLI). The relay only detects the last part and spawns a detached `racecast event stop`, which generates+sends the report while the relay is still up (names resolve), then tears the services down. Report aggregation stays pure (`report_build.py` + `health_store.py`); the relay records `part_start`/`part_end` markers that define the intended on-air windows.

**Tech Stack:** Pure Python 3 stdlib (no framework, no deps). Tests are runnable scripts under `tests/` (no pytest). `sqlite3` health store, `zipfile`/`io` for the attachment, `subprocess` for the detached spawn.

## Global Constraints

- **Edit only under `src/`** (+ `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code, docs, and user-facing strings.
- **No hardcoded secrets/paths.** Discord webhook via `_active_discord_webhook()`.
- **Tests must run on any machine + CI** — no real IPs/paths; stdlib-only; TDD (failing test first).
- **Relay stays dependency-light** — the relay may import `src/scripts/*` pure modules (it already imports `notify`, `parts`, `health_store`), but must NOT import the CLI (`racecast.py`); it *spawns* it as a subprocess.
- **Discord username is `notify.USERNAME` = "GT Racecast"** — verbatim, all posts.
- **Backward compatibility:** old Health DBs without `part_*`/`obs_stream_*` events must still render a report (whole-session fallback), never empty.
- **UI change → refresh the wiki screenshot in the SAME change:** the Director Panel change requires regenerating `src/docs/wiki/images/director-panel.png` (via the `wiki-screenshots` skill).
- Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` before finishing.

**Sample cadence facts (from `health_store.py`):** `SAMPLE_INTERVAL_S = 30`, `GAP_S = 95` (a hole larger than this is a relay-down gap and must never be bridged).

---

### Task 1: Always show seconds in the report (`report_build.py`)

**Files:**
- Modify: `src/scripts/report_build.py` (`_fmt_clock` at :190, `_fmt_dur` at :179)
- Test: `tests/test_report_build.py`

**Interfaces:**
- Produces: `_fmt_clock(ts)` → `"%H:%M:%S"` string; `_fmt_dur(seconds)` → includes seconds at every scale (`"1h 2m 5s"`, `"2m 5s"`, `"5s"`).

- [ ] **Step 1: Write the failing test** — append to `tests/test_report_build.py`:

```python
def t_fmt_seconds():
    import time as _t
    # _fmt_dur keeps seconds even at hour scale
    assert rb._fmt_dur(3725) == "1h 2m 5s"
    assert rb._fmt_dur(125) == "2m 5s"
    assert rb._fmt_dur(5) == "5s"
    # _fmt_clock shows HH:MM:SS
    ts = _t.mktime((2026, 7, 5, 15, 17, 9, 0, 0, -1))
    assert rb._fmt_clock(ts) == "15:17:09"
    assert rb._fmt_clock(None) == "—"
```

Register it in the file's `__main__` runner list (follow the existing pattern at the bottom of the file — every `t_*` function is called there).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_report_build.py`
Expected: FAIL — `_fmt_dur(3725)` returns `"1h 2m"`, `_fmt_clock` returns `"15:17"`.

- [ ] **Step 3: Implement**

Replace `_fmt_dur` body's hour branch and `_fmt_clock`:

```python
def _fmt_dur(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _fmt_clock(ts):
    if ts is None:
        return "—"
    return time.strftime("%H:%M:%S", time.localtime(ts))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_report_build.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/report_build.py tests/test_report_build.py
git commit -m "fix(report): always show seconds in durations and clock times"
```

---

### Task 2: Recovery-based incident duration (`health_store.py`)

**Files:**
- Modify: `src/scripts/health_store.py` (`derive_incidents` at :250)
- Test: `tests/test_health_store.py`

**Interfaces:**
- Produces: `derive_incidents(samples, gap_s=GAP_S)` — each non-green band's `end`/`duration_s` extend to the recovering sample (next band's `from`) when within `gap_s`, else by one `SAMPLE_INTERVAL_S`. A one-sample blip → `duration_s == SAMPLE_INTERVAL_S`, never 0.

- [ ] **Step 1: Write the failing test** — append to `tests/test_health_store.py`:

```python
def t_incident_recovery_duration():
    def s(ts, lvl):
        return {"ts": ts, "health_level": lvl, "health_reasons": ["off air"] if lvl == "red" else []}
    # single-sample red between greens -> lasts until recovery (30s), not 0s
    inc = hs.derive_incidents([s(1000, "green"), s(1030, "red"), s(1060, "green")])
    assert len(inc) == 1
    assert inc[0]["ts"] == 1030 and inc[0]["end"] == 1060 and inc[0]["duration_s"] == 30
    # multi-sample red -> extends to the recovering sample
    inc = hs.derive_incidents([s(1000, "green"), s(1030, "red"), s(1060, "red"), s(1090, "green")])
    assert inc[0]["duration_s"] == 60 and inc[0]["end"] == 1090
    # trailing red with no recovery -> extend by one interval (not 0)
    inc = hs.derive_incidents([s(1000, "green"), s(1030, "red")])
    assert inc[0]["duration_s"] == hs.SAMPLE_INTERVAL_S and inc[0]["end"] == 1030 + hs.SAMPLE_INTERVAL_S
    # never bridge a relay-down hole (> GAP_S) to the next band
    inc = hs.derive_incidents([s(1000, "red"), s(1000 + hs.GAP_S + 100, "green")])
    assert inc[0]["duration_s"] == hs.SAMPLE_INTERVAL_S
```

Register `t_incident_recovery_duration` in the file's `__main__` runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — first case `duration_s == 0`, `end == 1030`.

- [ ] **Step 3: Implement** — replace `derive_incidents`:

```python
def derive_incidents(samples, gap_s=GAP_S):
    """Every non-green aggregate-health band becomes an incident. Its duration runs
    until recovery: the next band's start (the recovering sample) when that gap is
    <= gap_s, else the band is extended by one SAMPLE_INTERVAL_S. This never bridges
    a relay-down hole (> gap_s) and never reports a zero-width single-sample blip."""
    reasons_at = {s["ts"]: s.get("health_reasons") or [] for s in samples}
    bands = collapse_bands([(s["ts"], s.get("health_level")) for s in samples], gap_s)
    out = []
    for i, b in enumerate(bands):
        if b["state"] == "green" or b["state"] is None:
            continue
        nxt = bands[i + 1]["from"] if i + 1 < len(bands) else None
        if nxt is not None and (nxt - b["to"]) <= gap_s:
            end = nxt
        else:
            end = b["to"] + SAMPLE_INTERVAL_S
        out.append({"ts": b["from"], "end": end, "duration_s": end - b["from"],
                    "severity": b["state"],
                    "label": _incident_label(b["state"], reasons_at.get(b["from"]))})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_health_store.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "fix(report): incident duration runs until recovery, never 0s"
```

---

### Task 3: On-air windows, timeline, and intentional-off-air exclusion (`report_build.py`)

**Files:**
- Modify: `src/scripts/report_build.py` (`build_report` at :135, `render_html` at :251)
- Test: `tests/test_report_build.py`

**Interfaces:**
- Produces:
  - `on_air_windows(events, session_end) -> list[(start,end)] | None` — pairs `part_start`→`part_end`; falls back to `obs_stream_start`→`obs_stream_stop`; `None` when neither exists.
  - `windows_total_s(windows) -> float`
  - `broadcast_timeline(events) -> list[{"ts","label"}]`
  - `build_report(...)` result header gains `"on_air_s"`; result gains `"broadcast_timeline"`; when windows exist, uptime/on_air/feeds/quality/incidents are computed over the on-air-clipped samples and uptime's denominator is `on_air_s`.
- Consumes: Task 1's `_fmt_clock`/`_fmt_dur`; Task 2's `hs.derive_incidents`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_report_build.py`:

```python
def t_on_air_windows_and_exclusion():
    # part events define the on-air window; obs_stream is the fallback
    ev = [{"ts": 100, "type": "part_start", "metadata": {"index": 1}},
          {"ts": 400, "type": "part_end", "metadata": {"index": 1}}]
    assert rb.on_air_windows(ev, 500) == [(100, 400)]
    assert rb.windows_total_s([(100, 400)]) == 300
    ev2 = [{"ts": 100, "type": "obs_stream_start"}, {"ts": 300, "type": "obs_stream_stop"}]
    assert rb.on_air_windows(ev2, 500) == [(100, 300)]
    assert rb.on_air_windows([], 500) is None
    # unclosed part_start closes at session_end
    assert rb.on_air_windows([{"ts": 100, "type": "part_start"}], 500) == [(100, 500)]


def t_build_report_excludes_off_air():
    def s(ts, lvl):
        return {"ts": ts, "health_level": lvl, "health_reasons": [],
                "live_stint": 1, "feed_a_down": 0, "feed_b_down": 0}
    # off-air red BEFORE the part window must not count; in-window green = 100% uptime
    samples = [s(50, "red"), s(100, "green"), s(130, "green"), s(160, "green")]
    events = [{"ts": 100, "type": "part_start", "metadata": {"index": 1}},
              {"ts": 160, "type": "part_end", "metadata": {"index": 1}}]
    rep = rb.build_report(samples, events, {}, "T", (50, 160), 200)
    assert rep["header"]["uptime_pct"] == 100.0
    assert rep["header"]["on_air_s"] == 60
    assert rep["incidents"] == []          # the pre-window red is excluded
    # timeline lists the part boundaries
    tl = rep["broadcast_timeline"]
    assert [(r["ts"], r["label"]) for r in tl] == [(100, "Part 1 started"), (160, "Part 1 ended")]


def t_build_report_legacy_no_windows():
    # no part/obs_stream events -> whole-session behaviour (off-air counts)
    def s(ts, lvl):
        return {"ts": ts, "health_level": lvl, "health_reasons": ["off air"],
                "live_stint": 1, "feed_a_down": 0, "feed_b_down": 0}
    samples = [s(0, "green"), s(30, "red"), s(60, "green")]
    rep = rb.build_report(samples, [], {}, "T", (0, 60), 100)
    assert rep["header"]["on_air_s"] == 60          # falls back to full duration
    assert len(rep["incidents"]) == 1               # off-air still counted
```

Register the three `t_*` functions in the `__main__` runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_report_build.py`
Expected: FAIL — `on_air_windows` undefined; `header` has no `on_air_s`; `broadcast_timeline` missing.

- [ ] **Step 3: Implement** — add the pure helpers above `build_report` in `report_build.py`:

```python
def _pair_windows(events, start_type, end_type, session_end):
    wins, open_s = [], None
    for e in sorted(events, key=lambda x: x.get("ts") or 0):
        t, ts = e.get("type"), e.get("ts")
        if ts is None:
            continue
        if t == start_type and open_s is None:
            open_s = ts
        elif t == end_type and open_s is not None:
            wins.append((open_s, ts))
            open_s = None
    if open_s is not None and session_end is not None:
        wins.append((open_s, session_end))
    return wins


def on_air_windows(events, session_end):
    """Intended on-air windows: part_start->part_end pairs (preferred), else
    obs_stream_start->obs_stream_stop pairs, else None (legacy whole-session)."""
    for start_t, end_t in (("part_start", "part_end"),
                           ("obs_stream_start", "obs_stream_stop")):
        wins = _pair_windows(events, start_t, end_t, session_end)
        if wins:
            return wins
    return None


def windows_total_s(windows):
    return sum(max(0.0, e - s) for s, e in windows)


def _in_windows(ts, windows):
    return any(s <= ts <= e for s, e in windows)


def _clip_samples(samples, windows):
    return [s for s in samples
            if s.get("ts") is not None and _in_windows(s["ts"], windows)]


def broadcast_timeline(events):
    """Chronological part (preferred) or OBS-stream start/stop rows for the report's
    Broadcast-timeline section — the reference points for the OBS-downtime figures."""
    have_parts = any(e.get("type") in ("part_start", "part_end") for e in events)
    starts = ("part_start", "part_end") if have_parts else ("obs_stream_start", "obs_stream_stop")
    rows = []
    for e in sorted(events, key=lambda x: x.get("ts") or 0):
        t = e.get("type")
        if t not in starts:
            continue
        idx = (e.get("metadata") or {}).get("index")
        if have_parts and idx is not None:
            label = f"Part {idx} {'started' if t == 'part_start' else 'ended'}"
        else:
            label = "OBS stream started" if t.endswith("start") else "OBS stream stopped"
        rows.append({"ts": e.get("ts"), "label": label})
    return rows
```

Then edit `build_report` — after computing `duration_s`, derive windows and pick the sample set the metrics run on:

```python
    frm, to = window
    duration_s = max(0.0, (to or 0) - (frm or 0))
    windows = on_air_windows(events, to)
    metric_samples = _clip_samples(samples, windows) if windows else samples
    on_air_s = windows_total_s(windows) if windows else duration_s
    # Full-session health bands drive the SVG strip (off-air visible as context);
    # the metric bands (on-air only) drive Uptime.
    health_bands = _fill_gaps(hs.collapse_bands(
        [(s["ts"], s.get("health_level")) for s in samples]))
    metric_bands = _fill_gaps(hs.collapse_bands(
        [(s["ts"], s.get("health_level")) for s in metric_samples]))
    on_air = _on_air(metric_samples, name_for_stint)
```

Change the aggregations that follow to use `metric_samples`, and the header:

```python
    feeds = [{"feed": "A", **_feed_stats(metric_samples, "feed_a_down")},
             {"feed": "B", **_feed_stats(metric_samples, "feed_b_down")}]
```

```python
        "header": {"event_title": event_title or "", "start": frm, "end": to,
                   "duration_s": round(duration_s, 1),
                   "on_air_s": round(on_air_s, 1),
                   "uptime_pct": _uptime_pct(metric_bands, on_air_s)},
        ...
        "incidents": hs.derive_incidents(metric_samples),
        "quality": _quality(metric_samples),
        ...
        "broadcast_timeline": broadcast_timeline(events),
        "health_bands": health_bands,
```

(Keep `producer_handovers`/`substitutions` reading from `events` as-is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_report_build.py`
Expected: PASS (all existing tests too — legacy path unchanged when no windows).

- [ ] **Step 5: Render the timeline + On-air KPI** — in `render_html`, add the "On air" KPI and the Broadcast-timeline section. Change the KPI block to insert an On-air tile after Session length, and add the section just before "Incident log":

```python
    parts.append("<div class='kpis'>"
                 f"<div class='kpi'><div class='n'>{hd['uptime_pct']}%</div>"
                 "<div class='l'>Uptime</div></div>"
                 f"<div class='kpi'><div class='n'>{_esc(_fmt_dur(hd['on_air_s']))}</div>"
                 "<div class='l'>On air</div></div>"
                 f"<div class='kpi'><div class='n'>{_esc(_fmt_dur(hd['duration_s']))}</div>"
                 "<div class='l'>Session length</div></div>"
                 f"<div class='kpi'><div class='n'>{len(report['incidents'])}</div>"
                 "<div class='l'>Incidents</div></div></div>")
```

```python
    # Broadcast timeline (part / OBS-stream start & stop — context for downtime)
    tl = report.get("broadcast_timeline") or []
    if tl:
        parts.append("<h2>Broadcast timeline</h2>")
        parts.append(_table(["Time", "Event"],
                            [(_fmt_clock(r["ts"]), r["label"]) for r in tl]))
        parts.append("<p class='note'>Uptime and the incident log below cover on-air "
                     "time only; intentional off-air (before start, between parts, "
                     "after the final stop) is excluded.</p>")
```

Add a rendering assertion to `t_build_report_excludes_off_air` (same test file), then re-run:

```python
    html = rb.render_html(rep)
    assert "Broadcast timeline" in html and "Part 1 started" in html
    assert ">On air<" in html
```

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_report_build.py && python3 tools/lint.py`
Expected: PASS / clean.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/report_build.py tests/test_report_build.py
git commit -m "feat(report): on-air windows exclude intentional off-air + broadcast timeline"
```

---

### Task 4: Discord report embed builders (`notify.py` + `report_build.py`)

**Files:**
- Modify: `src/scripts/notify.py`
- Modify: `src/scripts/report_build.py`
- Test: `tests/test_notify.py`, `tests/test_report_build.py`

**Interfaces:**
- Produces:
  - `report_build.report_discord_fields(report) -> list[(name, value)]` — pre-formatted KPI strings (Uptime, On air, Incidents, Session length, Window).
  - `notify.report_discord_payload(title, fields) -> dict` — `{"username": "GT Racecast", "embeds": [{title, color, fields:[{name,value,inline:True}]}]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_build.py`:

```python
def t_report_discord_fields():
    rep = {"header": {"uptime_pct": 98.0, "on_air_s": 3600, "duration_s": 7200,
                      "start": 0, "end": 7200}, "incidents": [1, 2]}
    f = dict(rb.report_discord_fields(rep))
    assert f["Uptime"] == "98.0%"
    assert f["On air"] == "1h 0m 0s"
    assert f["Incidents"] == "2"
    assert f["Session length"] == "2h 0m 0s"
    assert "Window" in f
```

Append to `tests/test_notify.py`:

```python
def t_report_payload():
    p = notify.report_discord_payload("Test Event", [("Uptime", "98.0%"), ("Incidents", "2")])
    assert p["username"] == "GT Racecast"
    assert p["embeds"][0]["title"].endswith("Test Event")
    names = [f["name"] for f in p["embeds"][0]["fields"]]
    assert names == ["Uptime", "Incidents"]
    assert all(f["inline"] for f in p["embeds"][0]["fields"])
```

Register both in their runners.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_notify.py; python3 tests/test_report_build.py`
Expected: FAIL — `report_discord_payload`/`report_discord_fields` undefined.

- [ ] **Step 3: Implement**

In `report_build.py`:

```python
def report_discord_fields(report):
    """Pre-formatted KPI (name, value) pairs for the Discord report embed."""
    hd = report["header"]
    return [("Uptime", f"{hd['uptime_pct']}%"),
            ("On air", _fmt_dur(hd.get("on_air_s", hd["duration_s"]))),
            ("Incidents", str(len(report["incidents"]))),
            ("Session length", _fmt_dur(hd["duration_s"])),
            ("Window", f"{_fmt_clock(hd['start'])}–{_fmt_clock(hd['end'])}")]
```

In `notify.py` (add a color constant near the others, and the builder):

```python
COLOR_REPORT = 0x3B82F6        # blue — a post-event report


def report_discord_payload(title, fields):
    """Post-event report embed: headline KPI fields as the useful inline content.
    `fields` is a list of (name, value) strings. Pure — the caller attaches the
    zipped HTML separately. Posts as GT Racecast; no @here (not time-critical)."""
    embed = {"title": f"📊 Post-event report — {title or 'Event'}",
             "color": COLOR_REPORT,
             "fields": [{"name": n, "value": v, "inline": True} for n, v in fields]}
    return {"username": USERNAME, "embeds": [embed]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_notify.py && python3 tests/test_report_build.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/notify.py src/scripts/report_build.py tests/test_notify.py tests/test_report_build.py
git commit -m "feat(report): Discord report embed builder (GT Racecast, KPI fields)"
```

---

### Task 5: Report send — embed + zip + username, and expose the report dict (`racecast.py`)

**Files:**
- Modify: `src/racecast.py` (`_build_report_file` at :1316, `_send_report_core` at :1359, `report_send_data` at :1382)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: Task 4's `notify.report_discord_payload`, `rbuild.report_discord_fields`.
- Produces:
  - `_build_report_file(...)` return dict gains `"report"` (the structured report dict).
  - `_send_report_core(path, report=None)` — posts a GT-Racecast embed (KPI fields when `report` given) with the HTML zipped as `<slug>.zip` (`application/zip`).

- [ ] **Step 1: Write the failing test** — extend `tests/test_report.py`. It already asserts `payload_json` is present in the multipart fields; add assertions for the username, the zip attachment, and that a report dict yields KPI fields. Follow the existing test's monkeypatch of `http_util.post_multipart` (it captures `fields`/`files`). Add:

```python
def t_send_report_embed_zip():
    import json, io, zipfile
    captured = {}

    def fake_post(url, fields=None, files=None, timeout=None):
        captured["fields"] = fields
        captured["files"] = files

    # ... reuse the file's existing harness to point _active_discord_webhook at a
    # dummy webhook and write a small report .html to a temp path (mirror the
    # existing t_send_* test in this file); then:
    rc._send_report_core(path, report={"header": {"uptime_pct": 99.0, "on_air_s": 60,
        "duration_s": 60, "start": 0, "end": 60}, "incidents": []})
    payload = json.loads(captured["fields"]["payload_json"])
    assert payload["username"] == "GT Racecast"
    assert payload["embeds"][0]["fields"][0]["name"] == "Uptime"
    fname, content, ctype = captured["files"][0][1], captured["files"][0][2], captured["files"][0][3]
    assert fname.endswith(".zip") and ctype == "application/zip"
    # the zip contains the .html
    names = zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert any(n.endswith(".html") for n in names)
```

Match the exact monkeypatch/harness style already in `tests/test_report.py` (it patches `rc.http_util.post_multipart` and `rc._active_discord_webhook`). Register the test in the runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_report.py`
Expected: FAIL — no `username`; attachment is `.html`/`text/html`; `_send_report_core` takes no `report` kwarg.

- [ ] **Step 3: Implement** — add the stdlib imports at the top of `racecast.py` if absent (`io`, `zipfile` — check the existing import block first), then replace `_send_report_core`:

```python
def _send_report_core(path, report=None):
    """Post the report to the league Discord as a GT-Racecast embed with the HTML
    zipped as a download-only attachment. Raises on any failure."""
    if not path:
        raise ValueError("no report found — run `racecast report` first")
    with open(path, "rb") as fh:
        content = fh.read()
    webhook, league = _active_discord_webhook()
    if not webhook:
        raise ValueError("No DISCORD_WEBHOOK_URL configured for this league")
    title = _report_event_title() or league or "Event"
    fields_kv = rbuild.report_discord_fields(report) if report else []
    payload = notify.report_discord_payload(title, fields_kv)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(os.path.basename(path), content)
    zip_name = os.path.splitext(os.path.basename(path))[0] + ".zip"
    fields = {"payload_json": json.dumps(payload)}
    files = [("files[0]", zip_name, buf.getvalue(), "application/zip")]
    http_util.post_multipart(webhook, fields=fields, files=files, timeout=15)
```

In `_build_report_file`, add the report dict to the return:

```python
    return {"path": path, "html": html, "summary": rbuild.render_summary_text(report),
            "report": report}
```

Leave `report_send_data(path=None)` calling `_send_report_core(path or _latest_report())` — it re-sends an existing file with no report dict (title-only embed), which is correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_report.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_report.py
git commit -m "feat(report): post as GT Racecast embed with a zipped download-only report"
```

---

### Task 6: `event stop` generates + sends the report by default (`racecast.py`)

**Files:**
- Modify: `src/racecast.py` (`event_stop` at :3274)
- Test: `tests/test_event.py`

**Interfaces:**
- Consumes: Task 5's `_build_report_file` (returns `"report"`), `_send_report_core(path, report)`.
- Produces: `event_stop(rest)` runs the report step first (default-on), then the existing teardown. `--no-report` skips it. Report/Discord failures are non-fatal (teardown always proceeds).

- [ ] **Step 1: Write the failing test** — append to `tests/test_event.py`. Monkeypatch the report + teardown functions on the `rc` module and assert ordering/flag behaviour:

```python
def t_event_stop_reports_then_tears_down():
    calls = []
    rc._build_report_file = lambda: (calls.append("build"),
                                     {"path": "/tmp/r.html", "report": {"x": 1}})[1]
    rc._send_report_core = lambda p, report=None: calls.append("send")
    rc.relay_stop = lambda a: calls.append("relay_stop")
    rc.companion_stop = lambda a: calls.append("companion_stop")
    rc.streams_stop = lambda a: calls.append("streams_stop")
    rc._streams_static_dir = lambda: "/nonexistent-streams-dir"   # no feed pids

    rc.event_stop([])
    assert calls.index("send") < calls.index("relay_stop")   # report BEFORE teardown
    assert "build" in calls and "relay_stop" in calls

    calls.clear()
    rc.event_stop(["--no-report"])
    assert "build" not in calls and "send" not in calls
    assert "relay_stop" in calls


def t_event_stop_report_failure_still_tears_down():
    calls = []
    def boom():
        raise RuntimeError("no health data")
    rc._build_report_file = boom
    rc.relay_stop = lambda a: calls.append("relay_stop")
    rc.companion_stop = lambda a: calls.append("companion_stop")
    rc.streams_stop = lambda a: None
    rc._streams_static_dir = lambda: "/nonexistent-streams-dir"
    rc.event_stop([])                       # must not raise
    assert "relay_stop" in calls
```

(Restore patched attributes at end of each test if the file's other tests rely on them — mirror the existing save/restore pattern in `tests/test_event.py`; if it has none, set them back to the originals captured at the top of the test.) Register both in the runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_event.py`
Expected: FAIL — `event_stop` does no report; `--no-report` unhandled.

- [ ] **Step 3: Implement** — replace `event_stop`:

```python
def event_stop(rest):
    """Stop racecast-managed services only — never the GUI apps (a mistyped command
    must not be able to kill a live broadcast). Generates + sends the post-event
    report BEFORE the teardown (default-on; --no-report skips) — while the relay is
    still up, so commentator names resolve. Report failure is non-fatal."""
    if "--no-report" not in rest:
        try:
            r = _build_report_file()
            print(r["summary"])
            try:
                _send_report_core(r["path"], report=r.get("report"))
                print("Report sent to Discord.")
            except Exception as exc:  # noqa: BLE001 — best-effort; still tear down
                print(f"report: Discord send failed ({exc}).")
        except Exception as exc:  # noqa: BLE001 — no health data etc.; still tear down
            print(f"report: skipped ({exc}).")
    relay_stop([])
    try:
        companion_stop([])
    except SystemExit as exc:
        print(exc.code if isinstance(exc.code, str)
              else f"companion: stop failed (exit {exc.code}).")
    if glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")):
        streams_stop([])
    print("OBS/Discord/Tailscale keep running — quit them manually if needed.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_event.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_event.py
git commit -m "feat(event): event stop generates + sends the report before teardown (--no-report opts out)"
```

---

### Task 7: Relay records part events, detects the last part, and spawns event stop (`racecast-feeds.py`)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`/parts/start` at :7392, `/parts/end` at :7419; add helpers)
- Test: `tests/test_health.py` (relay pure helpers), `tests/test_parts.py` (last-part condition)

**Interfaces:**
- Consumes: `parts_mod.parts_view_model` (last = `live and index == count`); `health_store.record_event`.
- Produces:
  - Pure `event_stop_argv(frozen, exe, rel_here)` — the argv to spawn a detached `racecast event stop` in frozen (`[exe, "event", "stop"]`) or source (`[exe, <rel_here>/../racecast.py, "event", "stop"]`) mode.
  - `/parts/start` records a `part_start` event; `/parts/end` records `part_end` and, when the just-ended part was the last, responds `{ok, index, final: True}` and spawns the detached `event stop`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parts.py` (assert the last-part detection the relay will use):

```python
def t_last_part_condition():
    rows = [{"part": "P1"}, {"part": "P2"}]
    vm = parts.parts_view_model(rows, {"index": 2, "live": True}, stream_active=True)
    assert vm["live"] and vm["index"] == vm["count"]      # last part is live
    vm1 = parts.parts_view_model(rows, {"index": 1, "live": True}, stream_active=True)
    assert not (vm1["index"] == vm1["count"])             # not the last part
```

Append to `tests/test_health.py` (the relay pure-helper test file — it already imports the relay module; mirror how it loads `racecast-feeds.py`):

```python
def t_event_stop_argv():
    # frozen: re-invoke the binary itself
    assert relay.event_stop_argv(True, "/opt/racecast", "/ignored") == \
        ["/opt/racecast", "event", "stop"]
    # source: python runs ../racecast.py relative to the relay script dir
    argv = relay.event_stop_argv(False, "/usr/bin/python3", "/repo/src/relay")
    assert argv[0] == "/usr/bin/python3" and argv[1].endswith("racecast.py")
    assert argv[-2:] == ["event", "stop"]
    assert "src/relay/../racecast.py".split("/")[-1] in argv[1]
```

Register both in their runners.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_parts.py; python3 tests/test_health.py`
Expected: `test_parts` PASS on the new one only if condition holds (it will — this documents intent); `test_health` FAIL — `event_stop_argv` undefined.

- [ ] **Step 3: Implement the pure helper** — add near the other module-level relay helpers in `racecast-feeds.py` (e.g. beside `stream_event_log_line`):

```python
def event_stop_argv(frozen, exe, rel_here):
    """Argv to spawn a detached `racecast event stop`. Frozen: re-invoke the binary
    itself (like the relay/streams daemons). Source: python runs ../racecast.py
    relative to the relay script dir. Pure — I/O is in _spawn_event_stop."""
    if frozen:
        return [exe, "event", "stop"]
    return [exe, os.path.join(rel_here, os.pardir, "racecast.py"), "event", "stop"]
```

Add the I/O wrapper (best-effort, detached — a new session so killing our own relay process does not cascade to the child; `PYINSTALLER_RESET_ENVIRONMENT=1` when frozen, mirroring `_frozen_child_env`):

```python
    def _spawn_event_stop(self):
        """Detached `racecast event stop` — generates+sends the report (we are still
        up, so names resolve) then tears racecast down (kills us by PID). Detach into
        a new session so our own teardown cannot cascade-kill the child. Best-effort."""
        try:
            frozen = bool(getattr(sys, "frozen", False))
            argv = event_stop_argv(frozen, sys.executable, _REL_HERE)
            env = os.environ.copy()
            if frozen:
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                      "stderr": subprocess.DEVNULL, "env": env}
            if os.name == "nt":
                kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                           | subprocess.CREATE_NEW_PROCESS_GROUP)
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(argv, **kwargs)
            LOG.info("Last part ended — spawned `event stop` (report + teardown).")
        except Exception:      # noqa: BLE001 — best-effort
            LOG.exception("failed to spawn event stop")
```

Confirm `subprocess`, `sys`, `os` are imported at the top of the relay (they are) and that `_REL_HERE` is the relay script dir constant used near line 79 (it is). If the constant has a different name, use that name.

- [ ] **Step 4: Record part events + wire the last-part branch** — in `/parts/start`, after `part_store.mark_live(idx)`:

```python
                    part_store.mark_live(idx)
                    if self.server.relay.health_store is not None:
                        try:
                            self.server.relay.health_store.record_event(
                                time.time(), "part_start",
                                label=f"Part {idx} started",
                                producer=self.server.relay.producer_name,
                                metadata={"index": idx})
                        except Exception:   # noqa: BLE001 — best-effort
                            pass
                    return self._send({"ok": True, "index": idx})
```

In `/parts/end`, compute last-ness BEFORE `part_store.end()`, then branch after it:

```python
                    ok2, note = _obs_ws.set_stream(False)
                    if not ok2:
                        return self._send({"ok": False, "error": note}, 503)
                    rows = producer_source.get() if producer_source is not None else []
                    pre_vm = parts_mod.parts_view_model(rows, part_store.get(),
                                                        stream_active=True)
                    is_last = bool(pre_vm.get("live")
                                   and pre_vm.get("count")
                                   and pre_vm.get("index") == pre_vm.get("count"))
                    part_store.end()
                    if self.server.relay.health_store is not None:
                        try:
                            self.server.relay.health_store.record_event(
                                time.time(), "part_end",
                                label=f"Part {res} ended",
                                producer=self.server.relay.producer_name,
                                metadata={"index": res})
                        except Exception:   # noqa: BLE001 — best-effort
                            pass
                    if is_last:
                        self._send({"ok": True, "index": res, "final": True})
                        self.server.relay._spawn_event_stop()
                        return
                    return self._send({"ok": True, "index": res})
```

Verify the accessor for the `Relay` instance inside the handler: the existing code reaches the relay/obs via closure/`self.server` — match whatever the surrounding handlers use to reach `health_store`, `producer_name`, and instance methods (e.g. `self.server.relay` vs a closed-over `relay`). Use the SAME accessor the nearby `_on_stream_transition`/health code uses; the snippets above assume `self.server.relay` — adjust to the actual name if it differs.

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_health.py && python3 tests/test_parts.py && python3 tools/lint.py`
Expected: PASS / clean.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_health.py tests/test_parts.py
git commit -m "feat(relay): record part events; last part end spawns event stop (report + teardown)"
```

---

### Task 8: Director Panel final-part confirmation (`director-panel.html`)

**Files:**
- Modify: `src/director/director-panel.html` (`openPartModal` at :1112, `submitPart` at :1128)
- Test: `tests/test_director_panel.py`
- Wiki: `src/docs/wiki/images/director-panel.png` (regenerate)

**Interfaces:**
- Consumes: `/parts/data` view model (`d.action`, `d.index`, `d.count`); the `/parts/end` response's new `final` flag.
- Produces: a distinct final-confirmation copy when ending the last part; a terminal "Event ending — report sent" state on a `{final:true}` response.

- [ ] **Step 1: Write the failing test** — `tests/test_director_panel.py` asserts on the HTML source (this file's tests grep the file for required markers — mirror the existing assertions there). Add:

```python
def t_final_part_confirmation_present():
    html = _read_panel()      # use the file's existing loader
    # last-part detection in the modal + the final-confirm copy
    assert "d.index === d.count" in html or "d.index == d.count" in html
    assert "ends the broadcast" in html.lower()
    # the panel reacts to the relay's {final:true} response
    assert "res.final" in html
```

Register it in the runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_director_panel.py`
Expected: FAIL — markers absent.

- [ ] **Step 3: Implement** — in `openPartModal`, branch the body copy for the last part:

```javascript
function openPartModal(d){
  partModalData = d;   // freeze the acted-on Part; submitPart uses this snapshot
  const isEnd = d.action === "end";
  const isFinal = isEnd && d.index === d.count;
  $("#partModalTitle").textContent =
    (isEnd ? (isFinal ? "⚠ END EVENT — " : "⚠ END ") : "GO LIVE — START ")
    + `PART ${d.index} of ${d.count}`;
  $("#partModalBody").textContent = isFinal
    ? `This ends the broadcast — OBS stream stops, the post-event report is `
      + `generated and sent to Discord, and all racecast services stop.`
    : isEnd
      ? `This STOPS the live broadcast (Part ${d.index}). Viewers see the stream end.`
      : `This GOES LIVE (Part ${d.index}${d.current_label ? " — " + d.current_label : ""}).`;
  $("#partModalPhrase").textContent = d.confirm_phrase;
  const inp = $("#partModalInput"), ok = $("#partModalConfirm");
  inp.value = ""; ok.disabled = true;
  inp.oninput = () => { ok.disabled = normIntent(inp.value) !== d.confirm_phrase; };
  $("#partModal").showModal();
  setTimeout(() => inp.focus(), 50);
}
```

In `submitPart`, handle the `final` response (after `$("#partModal").close();`):

```javascript
  $("#partModal").close();
  if (!res.ok){ log("Part: " + (res.error || "failed"), "err"); }
  else if (res.final){
    log("Event ending — report generated & sent to Discord; services stopping.", "ok");
    const status = $("#partStatus");
    status.textContent = "Event ending — report sent, services stopping…";
    status.className = "partstatus done";
    $("#partActionBtn").hidden = true;
    return;   // the relay is tearing down; further polling will fail (expected)
  }
  // After a transition, drop the cached OBS state so the next /parts/data
  // self-reads the fresh stream truth instead of the pre-action value (N2).
  lastStreamActive = null;
  obsStatePoll(); partsPoll();
```

- [ ] **Step 4: Run test + lint**

Run: `python3 tests/test_director_panel.py && python3 tools/lint.py`
Expected: PASS / clean.

- [ ] **Step 5: Visual verification** — REQUIRED before marking done: use the `ui-visual-verification` skill to render the Director Panel, open the part modal on a last part, and confirm the final-confirm copy reads correctly and nothing overflows.

- [ ] **Step 6: Regenerate the wiki screenshot** — use the `wiki-screenshots` skill to recapture `src/docs/wiki/images/director-panel.png` (demo profile + `tools/obs-sim.py` stand-in per the skill). Commit the refreshed image with the code.

- [ ] **Step 7: Commit**

```bash
git add src/director/director-panel.html tests/test_director_panel.py src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): final-part confirmation ends the event (report + teardown)"
```

---

### Task 9: Full suite + manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all green (this is exactly what CI runs).

- [ ] **Step 2: Build self-verify**

Run: `python3 tools/build.py`
Expected: PASS (tokenization, blanked password, no secrets — the closest local check to CI).

- [ ] **Step 3: Manual end-to-end (real-league dev build)** — use the `racecast-local-uat` skill to stand up a real-league dev build, then:
  1. Start the relay + OBS stand-in; start Part 1, stop it, start the last part.
  2. End the last part via the Director Panel → confirm: the `final` modal copy shows; a "GT Racecast" report embed with KPI fields + a `.zip` attachment appears in Discord (no raw-HTML preview); the report's incident log shows seconds and no `0s` singleton; the Broadcast-timeline section lists the parts; Uptime reflects on-air time only.
  3. Confirm relay/companion/streams are stopped afterward (`racecast status`).
  4. Verify `racecast event stop --no-report` at the terminal skips the report.

- [ ] **Step 4: Final commit (if any verification tweaks were needed)**

```bash
git add -A && git commit -m "test: end-to-end verification for the event-stop report flow"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- §A CLI `event stop` report-then-teardown → **Task 6** (+ Task 5 for the send internals).
- §B Relay last-part detection + spawn + part events → **Task 7**.
- §C Director Panel final confirmation (+ wiki image) → **Task 8**.
- §D Health store `part_*` events + recovery incidents → **Task 2** (incidents), **Task 7** (events).
- §E Report windows / seconds / timeline / legacy fallback → **Task 1** (seconds), **Task 3** (windows/timeline/exclusion/fallback).
- §F Discord username + embed + zip → **Task 4** (builders) + **Task 5** (wiring).
- Testing matrix → each task ships its tests; **Task 9** runs the full suite + manual E2E.

**Placeholder scan:** every code step contains real code; the one deliberately-referential spot (Task 5's test harness) points at the existing `tests/test_report.py` monkeypatch pattern with the concrete assertions spelled out. No "TBD"/"handle edge cases".

**Type consistency:** `event_stop_argv(frozen, exe, rel_here)`, `on_air_windows(events, session_end)`, `windows_total_s(windows)`, `broadcast_timeline(events)`, `report_discord_fields(report)`, `report_discord_payload(title, fields)`, `_send_report_core(path, report=None)`, `_build_report_file()` → `{path,html,summary,report}` are used with identical names/arities across tasks. Header keys `on_air_s`/`uptime_pct` and the report key `broadcast_timeline` match between Task 3 (producer) and Tasks 4/5 (consumers).
