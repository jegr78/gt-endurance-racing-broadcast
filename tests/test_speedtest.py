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


def _rec(ts, dl=30.0, ul=12.0):
    return {"ts": ts, "download_mbps": dl, "upload_mbps": ul, "ping_ms": 10.0,
            "jitter_ms": 1.0, "packet_loss": 0.0, "server": "S", "isp": "I",
            "result_url": None}


def t_history_roundtrip_and_latest(tmp=None):
    import tempfile
    d = tempfile.mkdtemp()
    assert m.load_latest(d) is None
    assert m.load_history(d) == []
    m.append_record(_rec(100), d)
    m.append_record(_rec(200), d)
    assert m.load_latest(d)["ts"] == 200            # newest
    hist = m.load_history(d)
    assert [r["ts"] for r in hist] == [200, 100]    # newest-first for the UI


def t_history_trims_to_limit():
    import tempfile
    d = tempfile.mkdtemp()
    for ts in range(1, 15):                          # 14 runs
        m.append_record(_rec(ts), d)
    hist = m.load_history(d)
    assert len(hist) == m.HISTORY_LIMIT == 10
    assert hist[0]["ts"] == 14 and hist[-1]["ts"] == 5   # only the last 10 kept


def t_history_skips_corrupt_lines():
    import tempfile
    d = tempfile.mkdtemp()
    with open(m.history_path(d), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_rec(1)) + "\n")
        fh.write("{ not json\n")                      # corrupt line ignored
        fh.write(json.dumps(_rec(2)) + "\n")
    assert [r["ts"] for r in m.load_history(d)] == [2, 1]
    assert m.load_latest(d)["ts"] == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
