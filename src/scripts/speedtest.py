#!/usr/bin/env python3
"""Opt-in Ookla bandwidth speed test for the GT Endurance Racing broadcast setup.

Wraps the Ookla `speedtest` CLI: runs it, parses its --format=json output into a
small record, appends that record to a machine-level JSONL history (trimmed to the
last HISTORY_LIMIT runs), and classifies the latest record against the documented
minimum/recommended bandwidth for `racecast preflight`.

NEVER runs automatically — it is invoked only by `racecast speedtest` and the
Control Center button. Pure Python 3 standard library (the `speedtest` binary is
the only external dependency, installed via `racecast install-tools`).
"""
import json
import os          # noqa: F401  (used in Tasks 2-4: history_path, makedirs, path helpers)
import shutil      # noqa: F401  (used in Task 4: shutil.which injected into run())
import subprocess  # noqa: F401  (used in Task 4: default runner in run())
import time        # noqa: F401  (used in Task 4: main() stamps time.time())

from preflight import PASS, WARN, INFO, Result   # noqa: F401  (used in Tasks 3-4: classify/render)

SPEEDTEST_BIN = "speedtest"
# Thresholds mirror src/docs/wiki/Set-up-the-broadcast-PC.md (the single source).
MIN_DOWN_MBPS, MIN_UP_MBPS = 25.0, 10.0
REC_DOWN_MBPS, REC_UP_MBPS = 50.0, 20.0
DEFAULT_MAX_AGE_DAYS = 7
HISTORY_LIMIT = 10
HISTORY_NAME = "speedtest-history.jsonl"


class SpeedtestUnavailable(RuntimeError):
    """The Ookla speedtest CLI is not on PATH."""


class SpeedtestFailed(RuntimeError):
    """The speedtest CLI ran but did not produce a usable result."""


def run_argv():
    """argv for one measurement. The --accept-* flags are passed on EVERY run so
    the CLI's interactive first-run license/GDPR prompt never blocks us."""
    return [SPEEDTEST_BIN, "--format=json", "--accept-license", "--accept-gdpr"]


def _mbps(bandwidth_bytes_per_sec):
    """Ookla reports bandwidth in BYTES per second -> Mbps."""
    return round(float(bandwidth_bytes_per_sec) * 8 / 1_000_000, 1)


def _round_or_none(value):
    return None if value is None else round(float(value), 1)


def parse_result(json_text, now):
    """Parse a `speedtest --format=json` payload into a persisted record.
    Raises ValueError on malformed JSON or a missing download/upload section."""
    data = json.loads(json_text)            # ValueError on bad JSON
    if not isinstance(data, dict) or "download" not in data or "upload" not in data:
        raise ValueError("unexpected speedtest JSON (no download/upload section)")
    ping = data.get("ping") or {}
    server = data.get("server") or {}
    result = data.get("result") or {}
    server_str = " — ".join(s for s in (server.get("name"), server.get("location")) if s)
    return {
        "ts": int(now),
        "download_mbps": _mbps(data["download"]["bandwidth"]),
        "upload_mbps": _mbps(data["upload"]["bandwidth"]),
        "ping_ms": _round_or_none(ping.get("latency")),
        "jitter_ms": _round_or_none(ping.get("jitter")),
        "packet_loss": _round_or_none(data.get("packetLoss")),
        "server": server_str,
        "isp": data.get("isp") or "",
        "result_url": result.get("url") or None,
    }


def history_path(runtime_dir):
    return os.path.join(runtime_dir, HISTORY_NAME)


def _read_all(runtime_dir):
    """All valid records in file (chronological) order. Tolerates a missing file
    and skips individual corrupt lines so one bad write can't lose the history."""
    out = []
    try:
        with open(history_path(runtime_dir), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue   # skip a corrupt line, keep the rest
    except FileNotFoundError:
        return []
    return out


def load_history(runtime_dir, limit=HISTORY_LIMIT):
    """Up to `limit` recent records, NEWEST-FIRST (for the Control Center table)."""
    recent = _read_all(runtime_dir)[-limit:]
    recent.reverse()
    return recent


def load_latest(runtime_dir):
    """The most recent record, or None when nothing has been measured yet."""
    recs = _read_all(runtime_dir)
    return recs[-1] if recs else None


def append_record(record, runtime_dir):
    """Append one record and rewrite the file trimmed to the last HISTORY_LIMIT."""
    os.makedirs(runtime_dir, exist_ok=True)
    kept = (_read_all(runtime_dir) + [record])[-HISTORY_LIMIT:]
    with open(history_path(runtime_dir), "w", encoding="utf-8") as fh:
        for rec in kept:
            fh.write(json.dumps(rec) + "\n")
    return record


def _fmt_age(age_days):
    if age_days < 1 / 24:
        return "just now"
    if age_days < 1:
        return f"{int(age_days * 24)} h ago"
    return f"{int(age_days)} d ago"


def _summary(record, age_days):
    parts = [f"↓{record.get('download_mbps', 0.0):.1f} "
             f"↑{record.get('upload_mbps', 0.0):.1f} Mbps",
             f"measured {_fmt_age(age_days)}"]
    if record.get("server"):
        parts.append(record["server"])
    if record.get("isp"):
        parts.append(record["isp"])
    return " · ".join(parts)


def classify(record, now, max_age_days=DEFAULT_MAX_AGE_DAYS):
    """Latest record -> a preflight.Result. Below-minimum and stale both WARN
    (never FAIL); the worse of download/upload governs the level."""
    if not record:
        return Result(INFO, "bandwidth",
                      "not measured yet — run `racecast speedtest` "
                      "(or the Control Center's Speed test button)")
    dl = record.get("download_mbps", 0.0)
    ul = record.get("upload_mbps", 0.0)
    age = max(0.0, (now - record.get("ts", now)) / 86_400.0)
    where = _summary(record, age)
    if age > max_age_days:
        return Result(WARN, "bandwidth",
                      f"{where} — stale (older than {int(max_age_days)} d); "
                      "re-measure before the event")
    if dl < MIN_DOWN_MBPS or ul < MIN_UP_MBPS:
        return Result(WARN, "bandwidth",
                      f"{where} — below the {MIN_DOWN_MBPS:.0f}/{MIN_UP_MBPS:.0f} "
                      "Mbps minimum")
    if dl < REC_DOWN_MBPS or ul < REC_UP_MBPS:
        return Result(WARN, "bandwidth",
                      f"{where} — meets the minimum, below the "
                      f"{REC_DOWN_MBPS:.0f}/{REC_UP_MBPS:.0f} Mbps recommended")
    return Result(PASS, "bandwidth",
                  f"{where} — meets the recommended "
                  f"{REC_DOWN_MBPS:.0f}/{REC_UP_MBPS:.0f} Mbps")


def default_runtime_dir(here):
    """Match the relay/get-cookies helper: repo layout (src/scripts/) ->
    <repo>/runtime ; distributed package (scripts/) -> here. Only used for a
    standalone `python3 speedtest.py` run; the CLI passes --runtime-dir."""
    if os.path.basename(here) == "scripts" and \
            os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime")
    return here
