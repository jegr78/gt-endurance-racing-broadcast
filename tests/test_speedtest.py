#!/usr/bin/env python3
"""Stdlib checks for the Ookla speed-test helpers. Run: python3 tests/test_speedtest.py"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import speedtest as m   # noqa: E402
import preflight as pf  # noqa: E402,F401  (used in Task 3 classify tests)

# A captured `speedtest --format=json` payload (clean round numbers):
#   download.bandwidth 6_000_000 B/s -> 48.0 Mbps ; upload 2_750_000 -> 22.0 Mbps
OOKLA_JSON = json.dumps({
    "type": "result",
    "ping": {"jitter": 1.2, "latency": 11.5},
    "download": {"bandwidth": 6_000_000, "bytes": 50_000_000, "elapsed": 3000},
    "upload": {"bandwidth": 2_750_000, "bytes": 20_000_000, "elapsed": 3000},
    "packetLoss": 0,
    "isp": "Deutsche Telekom",
    "server": {"id": 1234, "name": "Telekom", "location": "Berlin"},
    "result": {"id": "abc", "url": "https://www.speedtest.net/result/c/abc"},
})


def t_run_argv_accepts_license_and_gdpr():
    argv = m.run_argv()
    assert argv[0] == "speedtest"
    assert "--format=json" in argv
    # Regression guard: dropping these reintroduces the blocking first-run prompt.
    assert "--accept-license" in argv and "--accept-gdpr" in argv


def t_parse_result_converts_bandwidth_to_mbps():
    rec = m.parse_result(OOKLA_JSON, now=1_000_000)
    assert rec["ts"] == 1_000_000
    assert rec["download_mbps"] == 48.0
    assert rec["upload_mbps"] == 22.0
    assert rec["ping_ms"] == 11.5
    assert rec["jitter_ms"] == 1.2
    assert rec["packet_loss"] == 0.0
    assert rec["server"] == "Telekom — Berlin"
    assert rec["isp"] == "Deutsche Telekom"
    assert rec["result_url"] == "https://www.speedtest.net/result/c/abc"


def t_parse_result_tolerates_missing_optional_fields():
    rec = m.parse_result(json.dumps({
        "download": {"bandwidth": 3_125_000},   # 25.0 Mbps
        "upload": {"bandwidth": 1_250_000},     # 10.0 Mbps
    }), now=5)
    assert rec["download_mbps"] == 25.0 and rec["upload_mbps"] == 10.0
    assert rec["ping_ms"] is None and rec["packet_loss"] is None
    assert rec["result_url"] is None and rec["server"] == "" and rec["isp"] == ""


def t_parse_result_rejects_garbage():
    for bad in ("", "not json", json.dumps({"download": {"bandwidth": 1}})):
        try:
            m.parse_result(bad, now=1)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
