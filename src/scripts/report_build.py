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


def _fill_gaps(bands, gap_s=hs.GAP_S):
    """Return NEW bands where each band's end extends to the next band's start —
    but only across a normal sampling interval. A hole larger than gap_s means the
    relay was down (collapse_bands split there); that gap is NOT bridged, so a
    blackout is correctly excluded from the pre-gap state's duration. Does not
    mutate the input."""
    out = [dict(b) for b in bands]
    for i in range(len(out) - 1):
        nxt = out[i + 1]["from"]
        if nxt - out[i]["to"] <= gap_s:
            out[i]["to"] = nxt
    return out


def _uptime_pct(filled_bands, duration_s):
    if duration_s <= 0:
        return 0.0
    green = sum(b["to"] - b["from"] for b in filled_bands if b["state"] == "green")
    return round(green / duration_s * 100, 1)


def _feed_stats(samples, down_field):
    bands = _fill_gaps(hs.collapse_bands(
        [(s["ts"], 1 if s.get(down_field) else 0) for s in samples]))
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
    bands = _fill_gaps(hs.collapse_bands([(s["ts"], s.get("live_stint")) for s in samples]))
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
    health_bands = _fill_gaps(hs.collapse_bands(
        [(s["ts"], s.get("health_level")) for s in samples]))
    on_air = _on_air(samples, name_for_stint)
    on_air["resolved_at"] = now
    feeds = [{"feed": "A", **_feed_stats(samples, "feed_a_down")},
             {"feed": "B", **_feed_stats(samples, "feed_b_down")}]
    handovers = []
    substitutions = []
    for e in events:
        if e.get("type") == "takeover":
            md = e.get("metadata") or {}
            handovers.append({"ts": e.get("ts"), "from": md.get("from") or "",
                              "to": e.get("producer") or "", "stint": md.get("stint")})
        elif e.get("type") == "feed_substitution":
            md = e.get("metadata") or {}
            substitutions.append({"ts": e.get("ts"), "feed": md.get("feed") or "",
                                  "stint": md.get("stint"),
                                  "streamer": name_for_stint.get(md.get("stint")) or "",
                                  "reason": md.get("reason") or ""})
    return {
        "header": {"event_title": event_title or "", "start": frm, "end": to,
                   "duration_s": round(duration_s, 1),
                   "uptime_pct": _uptime_pct(health_bands, duration_s)},
        "on_air": on_air,
        "feeds": feeds,
        "incidents": hs.derive_incidents(samples),
        "quality": _quality(samples),
        "producer_handovers": handovers,
        "substitutions": substitutions,
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
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _fmt_clock(ts):
    if ts is None:
        return "—"
    return time.strftime("%H:%M:%S", time.localtime(ts))


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

    # Stream substitutions
    if report.get("substitutions"):
        parts.append("<h2>Stream substitutions</h2>")
        parts.append("<p class='note'>Ad-hoc on-air stream swaps (the on-air feed was "
                     "pointed at an alternative source mid-stint).</p>")
        srows = [(_fmt_clock(s["ts"]), s["feed"],
                  s["stint"] if s["stint"] is not None else "—",
                  s["streamer"], s["reason"])
                 for s in report["substitutions"]]
        parts.append(_table(["Time", "Feed", "Stint", "Commentator", "Reason"], srows))

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
