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
