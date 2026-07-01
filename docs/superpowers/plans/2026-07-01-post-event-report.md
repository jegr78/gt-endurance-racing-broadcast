# Post-Event-Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a self-contained HTML post-event report from the relay's Health DB (uptime, per-feed reliability, incident log, on-air-per-commentator, stream/OBS quality), viewable in the Control Center and manually sendable to the league Discord as an attachment.

**Architecture:** A pure stdlib module (`report_build.py`) does all aggregation over the Health DB rows and renders a self-contained HTML document; a `racecast report` CLI is the headless core; a Control Center "Report" view wraps it; a `racecast report send` (and a CC button) posts the `.html` to Discord via a new `http_util.post_multipart`. No Health-DB schema change — producer-handover overlap is handled with the existing `takeover` event markers + bucket de-duplication.

**Tech Stack:** Python 3 stdlib only (`sqlite3` via the existing `health_store`, `html`, `csv`, `time`, `urllib` via `http_util`). No new runtime dependency.

## Global Constraints

- **Edit only under `src/` and `tests/`** (plus `docs/` for the plan/spec). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all code, docs, comments, and user-facing strings.
- **No secrets / machine paths / real IPs** in committed files. Tailscale test IPs are the `100.64.0.0/10` range only.
- **Outbound HTTP goes through `src/scripts/http_util.py`** (covered side: `racecast.py`, `ui_server.py`, `src/scripts/*`). `tests/test_http_util.py` fails if a covered file uses `urlopen`/`urllib.request` directly. `post_multipart` lives INSIDE `http_util.py`, so it may use the module-level `urlopen`.
- **Use "commentator", never "talent"** everywhere.
- **stdlib only** — no `pip`/vendored deps. The report artifact is self-contained HTML (no PDF engine, no external assets).
- **Self-contained HTML** = the rendered document contains NO `http://`/`https://` references and NO external `src=`/`href=` (all CSS inline, system-font stack, inline SVG only).
- **Cross-platform** (the CI matrix includes Windows): never build a fixed-OS path with `os.path.join`; only join paths for the current machine.
- **A new Control Center view is screenshot-blocking** (CLAUDE.md hard rule): `src/docs/wiki/images/cc-report.png` MUST be regenerated from a local dev build in the same PR (Task 4).
- **Redaction:** the report must never contain stream URLs. Name resolution reads `/schedule/data` but uses only the `name` field (the `url` field is ignored).
- Health-DB constants (from `src/scripts/health_store.py`): `SAMPLE_INTERVAL_S = 30`, `GAP_S = 95`. Reuse `health_store.collapse_bands`, `health_store.derive_incidents`, `health_store.query_range`, `health_store.query_events`, `health_store.open_db`, `health_store.migrate`.

## Plan refinements vs. spec (owned decisions — not open questions)

- **Name resolution is relay-only** (`GET http://127.0.0.1:8088/schedule/data`), not a direct Sheet-CSV fetch. Reason: the schedule CSV parser (header/positional modes, `is_channel` guard) lives only in the relay and is subtle; duplicating it would risk drift (DRY). When the relay is unreachable, names degrade to `Stint N` labels and the report prints a caveat. This narrows the spec's "else fetch the Sheet CSV directly" fallback to a graceful no-names degrade.
- **Feed-reliability covers feeds A and B only.** POV has no `pov_down` column (no drop signal) and is paused by design, so a "POV drops" number would be misleading. The rendered section carries a one-line note that POV (optional PiP) is not tracked for reliability. This refines the spec's "per A/B/POV".

## File Structure

- **Create `src/scripts/report_build.py`** — pure aggregation + rendering (no I/O). Owns `SESSION_GAP_S`, `select_session`, `bucket_samples`, `build_report`, `render_html`, `render_summary_text`, `report_filename`. Depends only on `health_store` (for `collapse_bands`/`derive_incidents`) + stdlib.
- **Modify `src/scripts/http_util.py`** — add `post_multipart`.
- **Modify `src/racecast.py`** — add `report_cmd` + core helpers (`_build_report_file`, `_send_report_core`, `_reports_dir`, `_latest_report`, `_report_name_map`, `_report_event_title`), UI providers (`report_generate_data`, `report_send_data`), the `route()`/`main()` branches, the `ctx` entries, and `USAGE` lines.
- **Modify `src/ui/ui_server.py`** — add `POST /api/report/generate` and `POST /api/report/send` route branches.
- **Modify `src/ui/control-center.html`** — add the nav button, the `data-view="report"` view, and its JS.
- **Create `tests/test_report_build.py`** — pure-module unit checks (runnable-script style).
- **Create `tests/test_report.py`** — CLI `report_cmd` generate/send integration checks.
- **Modify `tests/test_http_util.py`** — add a `post_multipart` unit check.
- **Modify `tests/test_ui_server.py`** — add the two report route checks.
- **Modify `README.md` + `src/docs/wiki/*`** — document the commands + the Control Center view (Task 5).

---

### Task 1: Pure report-build core (`report_build.py`)

**Files:**
- Create: `src/scripts/report_build.py`
- Test: `tests/test_report_build.py`

**Interfaces:**
- Consumes: `health_store.collapse_bands(points, gap_s)`, `health_store.derive_incidents(samples, gap_s)` (both already exist).
- Produces (used by Task 3 & Task 4):
  - `SESSION_GAP_S = 1800`
  - `select_session(sample_ts: list[float], gap_s=SESSION_GAP_S) -> (float|None, float|None)`
  - `bucket_samples(samples: list[dict], bucket_s=30) -> list[dict]`
  - `build_report(samples, events, name_for_stint: dict[int,str], event_title: str, window: tuple, now: float) -> dict`
  - `render_html(report: dict) -> str`
  - `render_summary_text(report: dict) -> str`
  - `report_filename(event_title: str, date_str: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_build.py`:

```python
#!/usr/bin/env python3
"""Unit checks for the pure post-event report builder (stdlib only)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# report_build imports health_store by module name, so put src/scripts on sys.path.
import sys
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
rb = _load("report_build", ("src", "scripts", "report_build.py"))


def _sample(ts, **kw):
    row = {"ts": ts, "kind": "periodic", "health_level": "green",
           "health_reasons": [], "feed_a_down": 0, "feed_b_down": 0,
           "live_stint": None, "live_feed": None}
    row.update(kw)
    return row


def t_select_session_single_run():
    ts = [100.0, 130.0, 160.0, 190.0]
    assert rb.select_session(ts, gap_s=1800) == (100.0, 190.0)


def t_select_session_splits_on_big_gap():
    # two runs separated by a 2000s gap (> SESSION_GAP_S) -> only the last run
    ts = [100.0, 130.0, 5000.0, 5030.0, 5060.0]
    assert rb.select_session(ts, gap_s=1800) == (5000.0, 5060.0)


def t_select_session_handover_gap_stays_one_session():
    # a 4-min handover gap (< 1800s) does NOT split the event
    ts = [100.0, 130.0, 400.0, 430.0]
    assert rb.select_session(ts, gap_s=1800) == (100.0, 430.0)


def t_select_session_empty():
    assert rb.select_session([], gap_s=1800) == (None, None)


def t_bucket_samples_collapses_concurrent():
    # two machines sampling ~same 30s window -> one row per 30s bucket (last wins)
    samples = [_sample(0.0, health_level="green"), _sample(10.0, health_level="yellow"),
               _sample(30.0, health_level="green"), _sample(40.0, health_level="red")]
    out = rb.bucket_samples(samples, bucket_s=30)
    assert [s["ts"] for s in out] == [10.0, 40.0], out


def t_build_report_uptime_and_feeds():
    samples = [_sample(0.0), _sample(30.0, health_level="yellow", feed_a_down=1),
               _sample(60.0, health_level="green"), _sample(90.0)]
    rep = rb.build_report(samples, [], {}, "Test Event", (0.0, 90.0), now=1000.0)
    assert rep["header"]["duration_s"] == 90.0
    # green for [0-30] and [60-90] = 60s of 90s -> 66.7%
    assert rep["header"]["uptime_pct"] == 66.7, rep["header"]
    feed_a = next(f for f in rep["feeds"] if f["feed"] == "A")
    assert feed_a["drops"] == 1, rep["feeds"]


def t_build_report_on_air_names_and_fallback():
    samples = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1),
               _sample(60.0, live_stint=2)]
    rep = rb.build_report(samples, [], {1: "Alice", 2: "Bob"},
                          "E", (0.0, 60.0), now=1000.0)
    names = {c["name"]: c["seconds"] for c in rep["on_air"]["commentators"]}
    assert names.get("Alice") == 60.0, rep["on_air"]
    assert "Bob" in names, rep["on_air"]
    assert rep["on_air"]["resolved"] is True
    # empty map -> "Stint N" fallback + resolved False
    rep2 = rb.build_report(samples, [], {}, "E", (0.0, 60.0), now=1000.0)
    assert any(c["name"] == "Stint 1" for c in rep2["on_air"]["commentators"]), rep2
    assert rep2["on_air"]["resolved"] is False


def t_build_report_producer_handover_from_events():
    samples = [_sample(0.0), _sample(30.0)]
    events = [{"ts": 15.0, "type": "takeover", "producer": "B",
               "metadata": {"from": "A", "stint": 2}}]
    rep = rb.build_report(samples, events, {}, "E", (0.0, 30.0), now=1000.0)
    assert rep["overlap_approximate"] is True
    assert rep["producer_handovers"] == [{"ts": 15.0, "from": "A", "to": "B", "stint": 2}]


def t_build_report_quality_none_when_empty():
    samples = [_sample(0.0), _sample(30.0)]  # no v3 quality columns set
    rep = rb.build_report(samples, [], {}, "E", (0.0, 30.0), now=1000.0)
    assert rep["quality"] is None
    samples2 = [_sample(0.0, stream_kbps=6000.0), _sample(30.0, stream_kbps=4000.0)]
    rep2 = rb.build_report(samples2, [], {}, "E", (0.0, 30.0), now=1000.0)
    assert rep2["quality"]["stream_kbps_peak"] == 6000.0, rep2["quality"]


def t_render_html_is_self_contained():
    samples = [_sample(0.0, live_stint=1), _sample(30.0, live_stint=1, feed_a_down=1),
               _sample(60.0, health_level="red")]
    rep = rb.build_report(samples, [], {1: "Alice"}, "Grand Prix", (0.0, 60.0), now=1000.0)
    html = rb.render_html(rep)
    assert html.startswith("<!doctype html>")
    assert "Grand Prix" in html
    assert "Alice" in html
    # self-contained: no external references (dotless marker avoids the CodeQL
    # incomplete-url-substring rule that has bitten test asserts before)
    assert "http" + "://" not in html, "external URL leaked into report"
    assert "https" + "://" not in html
    assert "Feed reliability" in html
    assert "Incident" in html


def t_render_summary_text():
    samples = [_sample(0.0), _sample(30.0)]
    rep = rb.build_report(samples, [], {}, "My Event", (0.0, 30.0), now=1000.0)
    txt = rb.render_summary_text(rep)
    assert "My Event" in txt
    assert "uptime" in txt.lower()


def t_report_filename():
    assert rb.report_filename("Grand Prix #3", "2026-07-01") == "2026-07-01-grand-prix-3.html"
    assert rb.report_filename("", "2026-07-01") == "2026-07-01-report.html"


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_report_build.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'report_build'` (or `AttributeError` once the file is stubbed).

- [ ] **Step 3: Write the implementation**

Create `src/scripts/report_build.py`:

```python
#!/usr/bin/env python3
"""Pure aggregation + rendering for the post-event report (stdlib only, no I/O).

Reads the Health-DB sample/event dicts (as returned by health_store.query_range /
query_events), aggregates a session into a structured report dict, and renders a
SELF-CONTAINED HTML document (all CSS inline, system fonts, inline SVG — no external
references, so it opens identically anywhere, offline). Redaction by construction:
no stream URLs ever enter the report (name resolution passes in a stint->name map).
"""
import html as _html
import time

import health_store as hs

# Coarse session gap: separates DISTINCT events in a long-retention DB. Much larger
# than health_store.GAP_S (95s, band continuity) so a producer handover — where B's
# relay is already running and mirroring — never splits one event into two reports.
SESSION_GAP_S = 1800


def select_session(sample_ts, gap_s=SESSION_GAP_S):
    """The last contiguous run of ascending sample timestamps. A gap larger than
    gap_s ends a session. Returns (start, end) or (None, None) for no data."""
    ts = sorted(t for t in sample_ts if t is not None)
    if not ts:
        return (None, None)
    start = ts[-1]
    for i in range(len(ts) - 1, 0, -1):
        if ts[i] - ts[i - 1] <= gap_s:
            start = ts[i - 1]
        else:
            break
    return (start, ts[-1])


def bucket_samples(samples, bucket_s=hs.SAMPLE_INTERVAL_S):
    """One sample per floor(ts/bucket_s) bucket, keeping the last by ts. For a single
    producer (~30s spacing) this is ~identity; during a handover overlap it halves the
    two-machine density. `samples` must be ascending by ts."""
    out, cur_key = [], None
    for s in samples:
        ts = s.get("ts")
        if ts is None:
            continue
        key = int(ts // bucket_s)
        if key == cur_key and out:
            out[-1] = s
        else:
            out.append(s)
            cur_key = key
    return out


def _uptime_pct(bands, duration_s):
    if duration_s <= 0:
        return 0.0
    green = sum(b["to"] - b["from"] for b in bands if b["state"] == "green")
    return round(green / duration_s * 100, 1)


def _feed_stats(samples, down_field):
    bands = hs.collapse_bands([(s["ts"], 1 if s.get(down_field) else 0) for s in samples])
    down = [b for b in bands if b["state"] == 1]
    downtime = sum(b["to"] - b["from"] for b in down)
    longest = max((b["to"] - b["from"] for b in down), default=0.0)
    return {"drops": len(down), "downtime_s": round(downtime, 1),
            "longest_outage_s": round(longest, 1)}


def _num(samples, field):
    return [s.get(field) for s in samples if s.get(field) is not None]


def _avg(xs):
    return round(sum(xs) / len(xs), 1) if xs else None


def _peak(xs):
    return round(max(xs), 1) if xs else None


def _quality(samples):
    kbps = _num(samples, "stream_kbps")
    dropped = _num(samples, "stream_dropped_pct")
    cong = _num(samples, "stream_congestion")
    cpu = _num(samples, "obs_cpu_pct")
    fps = _num(samples, "obs_fps")
    rskip = _num(samples, "obs_render_skipped_pct")
    if not any([kbps, dropped, cong, cpu, fps, rskip]):
        return None
    return {"stream_kbps_avg": _avg(kbps), "stream_kbps_peak": _peak(kbps),
            "dropped_pct_avg": _avg(dropped), "dropped_pct_peak": _peak(dropped),
            "congestion_avg": _avg(cong),
            "obs_cpu_avg": _avg(cpu), "obs_cpu_peak": _peak(cpu),
            "obs_fps_avg": _avg(fps), "render_skipped_pct_peak": _peak(rskip)}


def _on_air(samples, name_for_stint):
    bands = hs.collapse_bands([(s["ts"], s.get("live_stint")) for s in samples])
    agg = {}          # name -> [seconds, set(stints)]
    resolved = bool(name_for_stint)
    for b in bands:
        st = b["state"]
        if st is None:
            continue
        st = int(st)
        name = name_for_stint.get(st) or f"Stint {st}"
        entry = agg.setdefault(name, [0.0, set()])
        entry[0] += b["to"] - b["from"]
        entry[1].add(st)
    non_null = [int(b["state"]) for b in bands if b["state"] is not None]
    handovers = sum(1 for i in range(1, len(non_null)) if non_null[i] != non_null[i - 1])
    commentators = sorted(
        ({"name": n, "seconds": round(v[0], 1), "stints": len(v[1])} for n, v in agg.items()),
        key=lambda c: -c["seconds"])
    return {"commentators": commentators, "stint_handovers": handovers,
            "resolved": resolved}


def build_report(samples, events, name_for_stint, event_title, window, now):
    """Aggregate ONE session (already bucket-deduplicated) into the report dict.
    `window` = (from_ts, to_ts). `samples` is assumed non-empty (the caller guards)."""
    frm, to = window
    duration_s = max(0.0, (to or 0) - (frm or 0))
    health_bands = hs.collapse_bands([(s["ts"], s.get("health_level")) for s in samples])
    on_air = _on_air(samples, name_for_stint)
    on_air["resolved_at"] = now
    feeds = [{"feed": "A", **_feed_stats(samples, "feed_a_down")},
             {"feed": "B", **_feed_stats(samples, "feed_b_down")}]
    handovers = []
    for e in events:
        if e.get("type") == "takeover":
            md = e.get("metadata") or {}
            handovers.append({"ts": e.get("ts"), "from": md.get("from") or "",
                              "to": e.get("producer") or "", "stint": md.get("stint")})
    return {
        "header": {"event_title": event_title or "", "start": frm, "end": to,
                   "duration_s": round(duration_s, 1),
                   "uptime_pct": _uptime_pct(health_bands, duration_s)},
        "on_air": on_air,
        "feeds": feeds,
        "incidents": hs.derive_incidents(samples),
        "quality": _quality(samples),
        "producer_handovers": handovers,
        "overlap_approximate": bool(handovers),
        "health_bands": health_bands,
    }


# ---- rendering ----

_HEALTH_COLORS = {"green": "#2e7d32", "yellow": "#f9a825", "red": "#c62828"}


def _fmt_dur(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _fmt_clock(ts):
    if ts is None:
        return "—"
    return time.strftime("%H:%M", time.localtime(ts))


def _fmt_date(ts):
    if ts is None:
        return "—"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _esc(x):
    return _html.escape("" if x is None else str(x))


def _svg_health_strip(bands, frm, to):
    """A thin inline-SVG band strip (no JS, no external refs) colouring the session
    by aggregate health. Returns '' when there is nothing to draw."""
    span = (to or 0) - (frm or 0)
    if span <= 0 or not bands:
        return ""
    w, h = 720, 20
    rects = []
    for b in bands:
        x = (b["from"] - frm) / span * w
        bw = max(0.5, (b["to"] - b["from"]) / span * w)
        color = _HEALTH_COLORS.get(b["state"], "#9e9e9e")
        rects.append(f'<rect x="{x:.1f}" y="0" width="{bw:.1f}" height="{h}" fill="{color}"/>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'preserveAspectRatio="none" role="img" aria-label="Health timeline">'
            + "".join(rects) + "</svg>")


def _table(headers, rows):
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_STYLE = """
:root{color-scheme:light}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 margin:0;padding:32px;background:#f5f6f8;color:#1c1e21;line-height:1.45}
.wrap{max-width:820px;margin:0 auto;background:#fff;border-radius:12px;padding:32px;
 box-shadow:0 1px 3px rgba(0,0,0,.12)}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px;
 border-bottom:2px solid #eceef1;padding-bottom:6px}
.sub{color:#65676b;font-size:13px;margin:0 0 20px}
.kpis{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0}
.kpi{background:#f5f6f8;border-radius:8px;padding:12px 16px;min-width:120px}
.kpi .n{font-size:22px;font-weight:700}.kpi .l{font-size:12px;color:#65676b}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #eceef1}
th{color:#65676b;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
.caveat{font-size:12px;color:#65676b;font-style:italic;margin-top:8px}
.note{font-size:12px;color:#65676b;margin-top:6px}
.sev-red{color:#c62828;font-weight:700}.sev-yellow{color:#b26a00;font-weight:600}
"""


def render_html(report):
    """A single self-contained HTML document: inline <style>, inline SVG, no external
    references. Safe to attach to Discord / open offline anywhere."""
    hd = report["header"]
    oa = report["on_air"]
    parts = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             f"<title>Post-event report — {_esc(hd['event_title'] or 'Event')}</title>",
             f"<style>{_STYLE}</style></head><body><div class='wrap'>"]
    parts.append(f"<h1>{_esc(hd['event_title'] or 'Post-event report')}</h1>")
    parts.append(f"<p class='sub'>{_esc(_fmt_date(hd['start']))} · "
                 f"{_esc(_fmt_clock(hd['start']))}–{_esc(_fmt_clock(hd['end']))} · "
                 f"{_esc(_fmt_dur(hd['duration_s']))}</p>")
    parts.append("<div class='kpis'>"
                 f"<div class='kpi'><div class='n'>{hd['uptime_pct']}%</div>"
                 "<div class='l'>Uptime</div></div>"
                 f"<div class='kpi'><div class='n'>{_esc(_fmt_dur(hd['duration_s']))}</div>"
                 "<div class='l'>Session length</div></div>"
                 f"<div class='kpi'><div class='n'>{len(report['incidents'])}</div>"
                 "<div class='l'>Incidents</div></div></div>")
    strip = _svg_health_strip(report["health_bands"], hd["start"], hd["end"])
    if strip:
        parts.append(strip)

    # On air per commentator
    parts.append("<h2>On air per commentator</h2>")
    rows = [(c["name"], _fmt_dur(c["seconds"]), c["stints"]) for c in oa["commentators"]]
    parts.append(_table(["Commentator", "On air", "Stints"], rows) if rows
                 else "<p class='note'>No on-air data recorded.</p>")
    if oa["resolved"]:
        parts.append(f"<p class='caveat'>Names resolved from the schedule as of "
                     f"{_esc(_fmt_clock(oa['resolved_at']))}; a later running-order edit "
                     f"could change them.</p>")
    else:
        parts.append("<p class='caveat'>Commentator names were unavailable (relay not "
                     "running at report time) — shown by stint index.</p>")

    # Producer handovers
    if report["producer_handovers"]:
        parts.append("<h2>Producer handovers</h2>")
        hrows = [(_fmt_clock(h["ts"]), f"{h['from'] or '—'} → {h['to'] or '—'}",
                  h["stint"] if h["stint"] is not None else "—")
                 for h in report["producer_handovers"]]
        parts.append(_table(["Time", "Handover", "Stint"], hrows))

    # Feed reliability
    parts.append("<h2>Feed reliability</h2>")
    frows = [(f["feed"], f["drops"], _fmt_dur(f["downtime_s"]), _fmt_dur(f["longest_outage_s"]))
             for f in report["feeds"]]
    parts.append(_table(["Feed", "Drops", "Downtime", "Longest outage"], frows))
    parts.append("<p class='note'>POV (optional picture-in-picture) is not tracked for "
                 "reliability — it has no drop signal and is paused by design.</p>")

    # Incident log
    parts.append("<h2>Incident log</h2>")
    if report["incidents"]:
        irows = []
        for inc in report["incidents"]:
            sev = inc.get("severity") or ""
            irows.append((f"{_fmt_clock(inc['ts'])}–{_fmt_clock(inc['end'])}",
                          sev.upper(), _fmt_dur(inc["duration_s"]), inc.get("label") or ""))
        parts.append(_table(["Window", "Severity", "Duration", "Reason"], irows))
    else:
        parts.append("<p class='note'>No incidents — green the whole session.</p>")

    # Stream & OBS quality
    q = report["quality"]
    if q is not None:
        parts.append("<h2>Stream &amp; OBS quality</h2>")
        qrows = [("Stream bitrate (kbps)", q["stream_kbps_avg"], q["stream_kbps_peak"]),
                 ("Dropped frames (%)", q["dropped_pct_avg"], q["dropped_pct_peak"]),
                 ("Congestion", q["congestion_avg"], "—"),
                 ("OBS CPU (%)", q["obs_cpu_avg"], q["obs_cpu_peak"]),
                 ("OBS FPS", q["obs_fps_avg"], "—"),
                 ("Render skipped (%)", "—", q["render_skipped_pct_peak"])]
        parts.append(_table(["Metric", "Average", "Peak"],
                            [(m, a if a is not None else "—", p if p is not None else "—")
                             for m, a, p in qrows]))

    if report["overlap_approximate"]:
        parts.append("<p class='caveat'>A producer handover occurred during this session; "
                     "metrics inside the overlap window are approximate (concurrent, "
                     "source-untagged samples from two machines).</p>")
    parts.append("</div></body></html>")
    return "".join(parts)


def render_summary_text(report):
    """A short plaintext headline block for CLI stdout."""
    hd = report["header"]
    lines = [f"Post-event report — {hd['event_title'] or 'Event'}",
             f"  {_fmt_date(hd['start'])} {_fmt_clock(hd['start'])}–{_fmt_clock(hd['end'])} "
             f"({_fmt_dur(hd['duration_s'])})",
             f"  Uptime {hd['uptime_pct']}% · {len(report['incidents'])} incident(s)"]
    for f in report["feeds"]:
        lines.append(f"  Feed {f['feed']}: {f['drops']} drop(s), "
                     f"{_fmt_dur(f['downtime_s'])} down")
    return "\n".join(lines)


def report_filename(event_title, date_str):
    """<date>-<slug>.html; empty title -> <date>-report.html."""
    slug = "".join(c if c.isalnum() else "-" for c in (event_title or "").lower())
    slug = "-".join(p for p in slug.split("-") if p)
    return f"{date_str}-{slug or 'report'}.html"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_report_build.py`
Expected: prints `ok t_...` for every check and `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: exit 0 (no ruff findings).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/report_build.py tests/test_report_build.py
git commit -m "feat(report): pure post-event report builder"
```

---

### Task 2: `http_util.post_multipart`

**Files:**
- Modify: `src/scripts/http_util.py`
- Test: `tests/test_http_util.py`

**Interfaces:**
- Produces (used by Task 3): `http_util.post_multipart(url, fields: dict|None, files: list|None, *, headers=None, timeout=DEFAULT_TIMEOUT) -> bytes`. `files` items are `(field_name, filename, content_bytes_or_str, content_type)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_http_util.py` (a new test function alongside the existing ones — keep the file's existing `run()`/dispatch style; do NOT introduce `sys.exit(run())`):

```python
def t_post_multipart_frames_body_and_ua():
    import http_util
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"

    def _fake_urlopen(req, timeout=None):
        captured["ct"] = req.headers.get("Content-type")
        captured["ua"] = req.headers.get("User-agent")
        captured["body"] = req.data
        return _Resp()

    orig = http_util.urlopen
    http_util.urlopen = _fake_urlopen
    try:
        out = http_util.post_multipart(
            "https://example.invalid/hook",
            fields={"payload_json": '{"content":"hi"}'},
            files=[("files[0]", "report.html", b"<!doctype html>", "text/html")])
    finally:
        http_util.urlopen = orig
    assert out == b"ok"
    assert captured["ua"] == "racecast/1.0", captured
    assert captured["ct"].startswith("multipart/form-data; boundary="), captured
    body = captured["body"]
    assert b'name="payload_json"' in body
    assert b'{"content":"hi"}' in body
    assert b'filename="report.html"' in body
    assert b"<!doctype html>" in body
```

Note: the existing `tests/test_http_util.py` UA-guard scan asserts that *covered files* don't call `urlopen` directly. `http_util.py` itself is the helper and is exempt — adding `post_multipart` there does not trip the guard. Confirm the guard's allowlist already excludes `http_util.py` (it does — the guard exists to force callers through this module).

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_http_util.py`
Expected: FAIL — `AttributeError: module 'http_util' has no attribute 'post_multipart'`.

- [ ] **Step 3: Write the implementation**

In `src/scripts/http_util.py`, add `import uuid` at the top (with the other imports) and append this function:

```python
def post_multipart(url, fields=None, files=None, *, headers=None, timeout=DEFAULT_TIMEOUT):
    """POST a multipart/form-data body (RACECAST_UA always set — Discord is
    Cloudflare-fronted and 403s the default urllib UA). `fields` is {name: str};
    `files` is [(field_name, filename, content_bytes_or_str, content_type)]."""
    boundary = "----racecast" + uuid.uuid4().hex
    body = bytearray()

    def _w(text):
        body.extend(text.encode("utf-8"))

    for name, value in (fields or {}).items():
        _w(f"--{boundary}\r\n")
        _w(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        _w(f"{value}\r\n")
    for field_name, filename, content, ctype in (files or []):
        _w(f"--{boundary}\r\n")
        _w(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n')
        _w(f"Content-Type: {ctype}\r\n\r\n")
        body.extend(content.encode("utf-8") if isinstance(content, str) else content)
        _w("\r\n")
    _w(f"--{boundary}--\r\n")

    merged = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if headers:
        merged.update(headers)
    with open_url(url, data=bytes(body), headers=merged, method="POST", timeout=timeout) as r:
        return r.read()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_http_util.py`
Expected: `ALL PASS` (the new test and all existing ones, including the UA-guard scan).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/http_util.py tests/test_http_util.py
git commit -m "feat(http): multipart/form-data POST helper for file uploads"
```

---

### Task 3: `racecast report` CLI (generate + send)

**Files:**
- Modify: `src/racecast.py` (add `import report_build as rbuild` near the other `src/scripts` imports at the top; add helpers + `report_cmd`; add the `route()` and `main()` branches; add `USAGE` lines)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `report_build.*` (Task 1), `http_util.post_multipart` (Task 2), `health_store` (`hsmod`), `_active_discord_webhook()`, `_relay_fetch_json`, `_health_db_path()`, `_runtime_dir()`, `RELAY_PORT`.
- Produces (used by Task 4): `_build_report_file(frm=None, to=None, gap=None, out=None) -> dict` (`{"path","html","summary"}`; raises `ValueError` on no data); `_send_report_core(path) -> None` (raises on failure); `report_generate_data()`/`report_send_data(path=None)` (dict wrappers).

- [ ] **Step 1: Write the failing test**

Create `tests/test_report.py`:

```python
#!/usr/bin/env python3
"""Integration checks for the `racecast report` CLI (generate + send)."""
import importlib.util
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load("racecast", ("src", "racecast.py"))
hs = _load("health_store", ("src", "scripts", "health_store.py"))


def _seed_db(path):
    conn = hs.open_db(path)
    hs.migrate(conn)
    now = 1_700_000_000.0
    for i in range(4):
        hs.record(conn, {"ts": now + i * 30, "health_level": "green",
                         "feed_a_down": 0, "feed_b_down": 0, "live_stint": 1,
                         "health_reasons": []}, "periodic")
    conn.close()


def t_generate_writes_file(monkeypatch=None):
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "health-history.db")
        _seed_db(db)
        reports = os.path.join(d, "reports")
        orig_db, orig_dir = rc._health_db_path, rc._runtime_dir
        orig_map, orig_title = rc._report_name_map, rc._report_event_title
        rc._health_db_path = lambda: db
        rc._runtime_dir = lambda: d
        rc._report_name_map = lambda: {1: "Alice"}
        rc._report_event_title = lambda: "Unit Event"
        try:
            rc.report_cmd(["generate"])
        finally:
            rc._health_db_path, rc._runtime_dir = orig_db, orig_dir
            rc._report_name_map, rc._report_event_title = orig_map, orig_title
        files = os.listdir(reports)
        assert files and files[0].endswith(".html"), files
        html = open(os.path.join(reports, files[0]), encoding="utf-8").read()
        assert "Unit Event" in html and "Alice" in html


def t_generate_no_data_exits():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "health-history.db")
        conn = hs.open_db(db); hs.migrate(conn); conn.close()   # empty DB
        orig_db, orig_dir = rc._health_db_path, rc._runtime_dir
        rc._health_db_path = lambda: db
        rc._runtime_dir = lambda: d
        try:
            raised = False
            try:
                rc.report_cmd(["generate"])
            except SystemExit:
                raised = True
            assert raised, "expected SystemExit on empty DB"
        finally:
            rc._health_db_path, rc._runtime_dir = orig_db, orig_dir


def t_send_no_webhook_exits():
    with tempfile.TemporaryDirectory() as d:
        reports = os.path.join(d, "reports")
        os.makedirs(reports)
        p = os.path.join(reports, "2026-07-01-x.html")
        open(p, "w").write("<!doctype html><html></html>")
        orig_dir, orig_hook = rc._runtime_dir, rc._active_discord_webhook
        rc._runtime_dir = lambda: d
        rc._active_discord_webhook = lambda: ("", "")
        try:
            raised = False
            try:
                rc.report_cmd(["send"])
            except SystemExit:
                raised = True
            assert raised, "expected SystemExit when no webhook configured"
        finally:
            rc._runtime_dir, rc._active_discord_webhook = orig_dir, orig_hook


def t_send_posts_multipart():
    with tempfile.TemporaryDirectory() as d:
        reports = os.path.join(d, "reports")
        os.makedirs(reports)
        p = os.path.join(reports, "2026-07-01-x.html")
        open(p, "w").write("<!doctype html><html>hi</html>")
        sent = {}

        def _fake_post(url, fields=None, files=None, **kw):
            sent["url"] = url
            sent["fields"] = fields
            sent["files"] = files
            return b"ok"

        orig_dir = rc._runtime_dir
        orig_hook = rc._active_discord_webhook
        orig_post = rc.http_util.post_multipart
        rc._runtime_dir = lambda: d
        rc._active_discord_webhook = lambda: ("https://discord.invalid/webhook", "My League")
        rc.http_util.post_multipart = _fake_post
        try:
            rc.report_cmd(["send"])
        finally:
            rc._runtime_dir = orig_dir
            rc._active_discord_webhook = orig_hook
            rc.http_util.post_multipart = orig_post
        assert sent["url"] == "https://discord.invalid/webhook"
        assert "payload_json" in sent["fields"]
        assert sent["files"][0][1] == "2026-07-01-x.html"


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_report.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute 'report_cmd'`.

- [ ] **Step 3: Write the implementation**

3a. At the top of `src/racecast.py`, next to `import health_store as hsmod`, add:

```python
import report_build as rbuild
```

3b. Add the helpers + command near `health_cmd` (after the `health_cmd` function, before `_cues_path`):

```python
REPORT_VERBS = ("generate", "send")


def _reports_dir():
    return os.path.join(_runtime_dir(), "reports")


def _report_event_title():
    """Active profile's event title from runtime/<profile>/event.json ('' if absent)."""
    try:
        with open(os.path.join(_runtime_dir(), "event.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("title") or "").strip()
    except (OSError, ValueError):
        return ""


def _report_name_map():
    """{stint_index (1-based): commentator name} from the LOCAL relay's /schedule/data
    (which runs the canonical schedule parser). Only the `name` field is used — the
    `url` is ignored (redaction). Empty dict when the relay is unreachable."""
    try:
        data = _relay_fetch_json(f"http://127.0.0.1:{RELAY_PORT}/schedule/data")
        return {r["row"]: (r.get("name") or "").strip()
                for r in (data.get("rows") or [])
                if isinstance(r.get("row"), int) and (r.get("name") or "").strip()}
    except Exception:  # noqa: BLE001 — best-effort; names degrade gracefully
        return {}


def _build_report_file(frm=None, to=None, gap=None, out=None):
    """Core generator. Returns {'path','html','summary'}. Raises ValueError when the
    selected window has no samples."""
    gap = rbuild.SESSION_GAP_S if gap is None else gap
    conn = hsmod.open_db(_health_db_path())
    hsmod.migrate(conn)
    try:
        if frm is None or to is None:
            all_ts = [r["ts"] for r in
                      conn.execute("SELECT ts FROM samples ORDER BY ts ASC").fetchall()]
            s, e = rbuild.select_session(all_ts, gap)
            frm = s if frm is None else frm
            to = e if to is None else to
        if frm is None or to is None:
            raise ValueError("no health data for that window")
        samples = hsmod.query_range(conn, frm, to)
        events = hsmod.query_events(conn, frm, to)
    finally:
        conn.close()
    if not samples:
        raise ValueError("no health data for that window")
    bucketed = rbuild.bucket_samples(samples)
    title = _report_event_title()
    report = rbuild.build_report(bucketed, events, _report_name_map(), title,
                                 (frm, to), time.time())
    html = rbuild.render_html(report)
    os.makedirs(_reports_dir(), exist_ok=True)
    date_str = time.strftime("%Y-%m-%d", time.localtime(frm))
    path = out or os.path.join(_reports_dir(), rbuild.report_filename(title, date_str))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return {"path": path, "html": html, "summary": rbuild.render_summary_text(report)}


def _latest_report():
    try:
        files = [os.path.join(_reports_dir(), f) for f in os.listdir(_reports_dir())
                 if f.endswith(".html")]
    except OSError:
        return None
    return max(files, key=os.path.getmtime) if files else None


def _send_report_core(path):
    """Attach the report .html to the league Discord. Raises on any failure."""
    if not path:
        raise ValueError("no report found — run `racecast report` first")
    with open(path, "rb") as fh:
        content = fh.read()
    webhook, league = _active_discord_webhook()
    if not webhook:
        raise ValueError("No DISCORD_WEBHOOK_URL configured for this league")
    title = _report_event_title() or league or "Event"
    fields = {"payload_json": json.dumps({"content": f"\U0001F4CA Post-event report — {title}"})}
    files = [("files[0]", os.path.basename(path), content, "text/html")]
    http_util.post_multipart(webhook, fields=fields, files=files, timeout=15)


def report_generate_data():
    try:
        r = _build_report_file()
        return {"ok": True, "path": r["path"], "html": r["html"], "summary": r["summary"]}
    except Exception as exc:  # noqa: BLE001 — surface the message to the UI
        return {"ok": False, "error": str(exc)}


def report_send_data(path=None):
    try:
        _send_report_core(path or _latest_report())
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — surface the message to the UI
        return {"ok": False, "error": str(exc)}


def _report_parse_args(args):
    frm = to = out = None
    gap = None

    def _num(flag):
        i = args.index(flag)
        try:
            return args[i + 1]
        except IndexError:
            sys.exit(f"racecast: {flag} requires a value")

    if "--from" in args:
        try:
            frm = float(_num("--from"))
        except ValueError:
            sys.exit("racecast: --from requires a numeric epoch value")
    if "--to" in args:
        try:
            to = float(_num("--to"))
        except ValueError:
            sys.exit("racecast: --to requires a numeric epoch value")
    if "--session-gap" in args:
        try:
            gap = float(_num("--session-gap"))
        except ValueError:
            sys.exit("racecast: --session-gap requires a numeric seconds value")
    if "--out" in args:
        out = _num("--out")
    return frm, to, gap, out


def report_cmd(rest):
    """`racecast report [generate] [--from TS --to TS --session-gap S --out PATH]`
    | `racecast report send [FILE]` — generate/send the post-event report."""
    verb = rest[0] if rest and rest[0] in REPORT_VERBS else "generate"
    args = rest[1:] if (rest and rest[0] in REPORT_VERBS) else rest

    if verb == "send":
        path = args[0] if args and not args[0].startswith("--") else _latest_report()
        try:
            _send_report_core(path)
        except (OSError, ValueError) as exc:
            sys.exit(f"racecast: {exc}")
        except Exception as exc:  # noqa: BLE001 — network/HTTP
            sys.exit(f"racecast: Discord send failed — {type(exc).__name__}: {exc}")
        print(f"Sent {os.path.basename(path)} to the league Discord.")
        return None

    frm, to, gap, out = _report_parse_args(args)
    try:
        result = _build_report_file(frm, to, gap, out)
    except ValueError as exc:
        sys.exit(f"racecast: {exc} — nothing to report.")
    print(result["summary"])
    print(f"Report written -> {result['path']}")
    return None
```

3c. In `route()`, add next to the `health` branch (near `if cmd == "health":`):

```python
    if cmd == "report":
        return {"kind": "report", "rest": rest}
```

3d. In `main()`, add next to the `health` dispatch (near `if action["kind"] == "health":`):

```python
    if action["kind"] == "report":
        return report_cmd(action["rest"])
```

3e. In the `USAGE` string (top of the file), add two lines in the health/maintenance area:

```
  racecast report                            # generate the post-event report (last session) -> runtime/<profile>/reports/
  racecast report send [FILE]                # send the newest (or given) report to the league Discord as an attachment
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_report.py`
Expected: `ok t_...` for each and `ALL PASS`.

- [ ] **Step 5: Routing + lint regression**

Run: `python3 tests/test_racecast.py && python3 tools/lint.py`
Expected: both pass / exit 0 (routing still valid; no ruff findings).

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_report.py
git commit -m "feat(report): racecast report generate|send CLI"
```

---

### Task 4: Control Center "Report" view + screenshot

**Files:**
- Modify: `src/racecast.py` (register `report_generate`/`report_send` in the `ctx` dict at ~line 5427)
- Modify: `src/ui/ui_server.py` (two POST route branches)
- Modify: `src/ui/control-center.html` (nav button + view + JS)
- Add: `src/docs/wiki/images/cc-report.png`
- Test: `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `report_generate_data()`, `report_send_data(path=None)` (Task 3).
- Produces: `POST /api/report/generate` -> `{ok, html, path, summary}|{ok:false,error}`; `POST /api/report/send` -> `{ok}|{ok:false,error}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui_server.py` (follow the file's existing harness — it builds a `ctx` with stub providers and drives the handler; mirror the closest existing POST-route test such as the event-title or profile/use one):

```python
def t_report_generate_and_send_routes():
    # Uses the file's existing helper to build a server with a stub ctx + POST a body.
    # (Mirror the existing POST test harness in this file — same _make_server/_post
    #  helpers, same CSRF header the other POST tests pass.)
    calls = {}
    ctx = _base_ctx()   # the helper the other tests use to assemble a minimal ctx
    ctx["report_generate"] = lambda: {"ok": True, "html": "<!doctype html><html></html>",
                                      "path": "/x/r.html", "summary": "sum"}
    ctx["report_send"] = lambda path=None: calls.setdefault("send", path) or {"ok": True}
    srv, base = _make_server(ctx)
    try:
        code, body = _post(base, "/api/report/generate", {})
        assert code == 200 and body["ok"] is True and "<!doctype html>" in body["html"]
        code, body = _post(base, "/api/report/send", {"path": "/x/r.html"})
        assert code == 200 and body["ok"] is True
        assert calls["send"] == "/x/r.html"
    finally:
        srv.shutdown()
```

If the existing test file does not expose `_base_ctx`/`_make_server`/`_post` helpers under those exact names, adapt this test to the harness actually present (the implementer must read `tests/test_ui_server.py` first and match its conventions — this test asserts the two new routes dispatch to `ctx["report_generate"]`/`ctx["report_send"]` and return their payloads).

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the `/api/report/*` routes 404 / the assertion on `body["html"]` fails.

- [ ] **Step 3: Implement the routes**

In `src/ui/ui_server.py`, inside `do_POST` (after an existing branch such as `/api/event-title`), add:

```python
            if path == "/api/report/generate":
                try:
                    return self._json(ctx["report_generate"]())
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not generate report: {exc}"},
                                      code=500)
            if path == "/api/report/send":
                body = self._body_json()
                if body is None:
                    return self._json({"ok": False, "error": "malformed JSON body"},
                                      code=400)
                try:
                    result = ctx["report_send"](body.get("path"))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not send report: {exc}"},
                                      code=500)
                return self._json(result, code=200 if result.get("ok") else 400)
```

- [ ] **Step 4: Register the providers**

In `src/racecast.py`, in the `ctx = {` dict (~line 5427), add two entries alongside the existing providers:

```python
        "report_generate": report_generate_data,
        "report_send": report_send_data,
```

- [ ] **Step 5: Front-end view**

In `src/ui/control-center.html`:

5a. Add a nav button next to the existing ones (e.g. after the `logs` navitem):

```html
      <button class="navitem" data-nav="report" onclick="showView('report')">
        Report</button>
```

5b. Add the view block (place it alongside the other `<div class="view" ...>` blocks):

```html
      <div class="view" data-view="report" hidden>
        <div class="viewhead"><h2>Post-Event Report</h2></div>
        <p class="muted">Generate a report of the last session from the health history —
          uptime, feed reliability, incidents, on-air time per commentator. Send it to the
          league Discord as an attachment.</p>
        <div class="row">
          <button id="report-gen" class="btn" onclick="reportGenerate()">Generate report</button>
          <a id="report-dl" class="btn" download hidden>Download .html</a>
          <button id="report-send" class="btn" onclick="reportSend()" hidden>Send to Discord</button>
        </div>
        <p id="report-msg" class="muted"></p>
        <iframe id="report-frame" title="Report preview"
                style="width:100%;height:70vh;border:1px solid #ddd;border-radius:8px;background:#fff"
                hidden></iframe>
      </div>
```

5c. Add the JS (in the page's script section, near the other view handlers). Use the page's existing POST helper if there is one (e.g. `api('/api/...', body)`); the snippet below uses `fetch` directly with the same CSRF/JSON conventions the other actions use — the implementer must match the file's established helper:

```javascript
let _reportPath = null;
async function reportGenerate() {
  const btn = document.getElementById('report-gen');
  const msg = document.getElementById('report-msg');
  btn.disabled = true; msg.textContent = 'Generating…';
  try {
    const r = await fetch('/api/report/generate', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:'{}'});
    const data = await r.json();
    if (!data.ok) { msg.textContent = 'Error: ' + (data.error||'failed'); return; }
    _reportPath = data.path;
    const frame = document.getElementById('report-frame');
    frame.srcdoc = data.html; frame.hidden = false;
    const dl = document.getElementById('report-dl');
    dl.href = 'data:text/html;charset=utf-8,' + encodeURIComponent(data.html);
    dl.download = (data.path||'report.html').split('/').pop();
    dl.hidden = false;
    document.getElementById('report-send').hidden = false;
    msg.textContent = 'Written to ' + data.path;
  } catch (e) { msg.textContent = 'Error: ' + e; }
  finally { btn.disabled = false; }
}
async function reportSend() {
  const msg = document.getElementById('report-msg');
  msg.textContent = 'Sending…';
  try {
    const r = await fetch('/api/report/send', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path:_reportPath})});
    const data = await r.json();
    msg.textContent = data.ok ? 'Sent to Discord.' : ('Error: ' + (data.error||'failed'));
  } catch (e) { msg.textContent = 'Error: ' + e; }
}
```

- [ ] **Step 6: Run the UI tests + lint**

Run: `python3 tests/test_ui_server.py && python3 tools/lint.py`
Expected: `ALL PASS` / exit 0.

- [ ] **Step 7: Capture the screenshot (blocking hard rule)**

Use the `wiki-screenshots` skill (Control Center from a **local dev build** so the version badge reads "dev"). Populate the demo profile's health DB so the report has content, then capture the Report view:

```bash
python3 src/racecast.py profile use demo
# seed a small synthetic health history so the report renders content:
python3 - <<'PY'
import importlib.util, os, tempfile, time
spec = importlib.util.spec_from_file_location("hs", "src/scripts/health_store.py")
hs = importlib.util.module_from_spec(spec); spec.loader.exec_module(hs)
db = os.path.join("runtime", "demo", "health-history.db")
os.makedirs(os.path.dirname(db), exist_ok=True)
conn = hs.open_db(db); hs.migrate(conn)
now = time.time() - 3600
for i in range(60):
    lvl = "yellow" if i in (20, 21) else "green"
    hs.record(conn, {"ts": now + i*30, "health_level": lvl, "feed_a_down": 1 if i in (20,21) else 0,
                     "feed_b_down": 0, "live_stint": 1 if i < 30 else 2, "live_feed": "A",
                     "health_reasons": ["feed A byte stall"] if i in (20,21) else []}, "periodic")
conn.close(); print("seeded", db)
PY
RACECAST_UI_PORT=8090 python3 src/racecast.py ui --no-browser &
# (optional) start the demo relay so on-air names resolve; if so, revert profile.env after:
```

Drive the Playwright MCP to `http://127.0.0.1:8090/#report` (or click the Report nav item), click **Generate report**, and take a screenshot of the Report view. Save it to `src/docs/wiki/images/cc-report.png`. Then clean up:

```bash
pkill -f "racecast.py ui" ; python3 src/racecast.py relay stop 2>/dev/null || true
git checkout -- profiles/demo/profile.env   # revert CONSOLE_SECRET if the demo relay ran
rm -f runtime/demo/health-history.db        # the synthetic seed is scratch, not committed
```

Confirm no scratch PNGs are left in the repo root; only `src/docs/wiki/images/cc-report.png` is committed.

- [ ] **Step 8: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py src/ui/control-center.html \
        tests/test_ui_server.py src/docs/wiki/images/cc-report.png
git commit -m "feat(ui): Control Center post-event report view"
```

---

### Task 5: Docs

**Files:**
- Modify: `README.md`
- Modify: `src/docs/wiki/` (the Control-Center page + the CLI/command reference page; cross-reference `DISCORD_WEBHOOK_URL`)

- [ ] **Step 1: README command list**

Add to the command list in `README.md`, near the `racecast health …` entries:

```
racecast report                 # generate the post-event report (last session) into runtime/<profile>/reports/
racecast report send [FILE]     # send the newest (or given) report to the league Discord as an attachment
```

- [ ] **Step 2: Wiki — Control Center page**

In the Control-Center wiki page (the one that lists the views), add a **Post-Event Report** subsection describing: Generate → preview → Download .html / Send to Discord; that the artifact is self-contained HTML; that Discord shows it as a downloadable attachment (opened in a browser). Reference `src/docs/wiki/images/cc-report.png`. Follow the Control-Center-first ordering convention.

- [ ] **Step 3: Wiki — command/CLI reference + Discord prerequisite**

Document `racecast report` / `racecast report send` in the CLI reference page. Note that `report send` requires the league's `DISCORD_WEBHOOK_URL` (the same profile key used for health alerts) — cross-reference the existing Sheet-Webhook / Discord section rather than duplicating it. State the name-resolution behaviour: names come from the running relay's schedule; with the relay stopped the report falls back to stint indices.

- [ ] **Step 4: Validate wiki links**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (no broken links/anchors introduced).

- [ ] **Step 5: Commit**

```bash
git add README.md src/docs/wiki
git commit -m "docs(report): document the post-event report + Discord send"
```

---

## Final verification (before opening the PR)

- [ ] `python3 tools/run-tests.py` — the whole suite green (includes the new `test_report_build.py`, `test_report.py`, and the modified `test_http_util.py`/`test_ui_server.py`).
- [ ] `python3 tools/lint.py` — exit 0.
- [ ] `python3 tools/build.py` — exit 0 (verify step: tokenization, no secrets, no shell scripts).
- [ ] `src/docs/wiki/images/cc-report.png` committed; `profiles/demo/profile.env` reverted (no `CONSOLE_SECRET`); no scratch files staged.

## Self-Review (author checklist — completed)

1. **Spec coverage:** surface (CLI+CC+Discord) → Tasks 3/4; self-contained HTML → Task 1 (`render_html` + self-containment test); auto last-session window + overrides → Task 1 `select_session` + Task 3 arg parsing; name resolution + caveat → Task 1 `_on_air`/render + Task 3 `_report_name_map`; handover marker-segmentation + bucket dedup + disclosure → Task 1 `bucket_samples`/`producer_handovers`/`overlap_approximate` + render caveat; content (header/on-air/feeds/incidents/quality) → Task 1; Discord multipart → Task 2 + Task 3 `_send_report_core`; screenshot → Task 4; docs → Task 5. Two owned refinements (relay-only names; A/B feeds) recorded above.
2. **Placeholder scan:** no TBD/TODO; all code steps carry complete code. The Task-4 front-end/test snippets explicitly instruct matching the existing `control-center.html`/`test_ui_server.py` helpers because those conventions must be read from the files — the behaviour asserted is concrete.
3. **Type consistency:** `build_report` returns the dict consumed by `render_html`/`render_summary_text`; `_build_report_file` returns `{path,html,summary}` consumed by `report_generate_data` and the CC view; `post_multipart(url, fields, files)` signature matches its call in `_send_report_core` and the tests.
