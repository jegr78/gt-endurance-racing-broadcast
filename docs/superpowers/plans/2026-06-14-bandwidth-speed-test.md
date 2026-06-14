# Bandwidth Speed Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Ookla bandwidth speed test (CLI + Control Center) whose results are logged locally, and have `racecast preflight` read the latest result and warn when the documented minimum (25↓/10↑ Mbps) is not met or the measurement is stale.

**Architecture:** A new pure-logic module `src/scripts/speedtest.py` wraps the Ookla `speedtest` CLI: it builds the argv, parses the `--format=json` output into a record, persists a 10-entry JSONL history under the machine-level `runtime/`, and classifies the latest record into a `preflight.Result`. `racecast speedtest` is a one-shot wrapper; the Control Center runs it as a streaming job and reads `/api/speedtest`. Preflight's existing `Network` section gains the measured result ahead of the static advisory. `install-tools` learns to install the Ookla CLI (winget / brew-tap; Linux manual).

**Tech Stack:** Python 3 standard library only (`json`, `subprocess`, `urllib`-free), the existing no-pytest test harness (`tests/test_*.py` runnable scripts), Ookla Speedtest CLI as an external runtime tool.

**Spec:** `docs/superpowers/specs/2026-06-14-bandwidth-speed-test-design.md`

---

## File Structure

- **Create `src/scripts/speedtest.py`** — the whole feature's logic: constants (thresholds mirror the wiki table), `run_argv`, `parse_result`, the JSONL history store (`append_record`/`load_latest`/`load_history`, trimmed to `HISTORY_LIMIT`), `classify` (→ `preflight.Result`), the `run` runner (subprocess seam), and `main`/`render` for the standalone one-shot.
- **Create `tests/test_speedtest.py`** — stdlib checks for every pure helper, no real network.
- **Modify `src/scripts/preflight.py`** — `gather()` reads `speedtest.load_latest()` + `classify()` into the `Network` section; add `_speedtest_max_age()` env reader. (`Result`/level constants already live here and are imported by `speedtest.py`.)
- **Modify `src/racecast.py`** — register `speedtest` as a one-shot (`ONESHOTS`, `ONESHOT_MAP`, `RUNTIME_DIR_ONESHOTS`, `USAGE`); add the `speedtest_data` UI provider and register it.
- **Modify `src/scripts/install_tools.py`** — Ookla install/update command builders + `manual_guide` lines + a `main()` call.
- **Modify `src/ui/ui_ops.py`** — register the `speedtest` op.
- **Modify `src/ui/ui_server.py`** — serve `GET /api/speedtest`.
- **Modify `src/ui/control-center.html`** — Speed-test card in the Preflight view + JS.
- **Modify `tools/build-binary.py`** — `--hidden-import speedtest` (preflight + the UI provider import it).
- **Modify** `tests/test_install_tools.py`, `tests/test_racecast.py`, `tests/test_ui_server.py`, `tests/test_preflight.py` — coverage for the new seams.
- **Modify** `.env.example`, `src/docs/wiki/Set-up-the-broadcast-PC.md`, `CLAUDE.md`, `README.md` — config knob + docs.
- **Regenerate** `src/docs/wiki/images/cc-preflight.png`.

---

## Task 1: speedtest.py — constants, argv, JSON parsing

**Files:**
- Create: `src/scripts/speedtest.py`
- Test: `tests/test_speedtest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_speedtest.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the Ookla speed-test helpers. Run: python3 tests/test_speedtest.py"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import speedtest as m   # noqa: E402
import preflight as pf  # noqa: E402

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_speedtest.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'speedtest'` (the module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/speedtest.py`:

```python
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
import os
import shutil
import subprocess
import time

from preflight import PASS, WARN, INFO, Result   # level constants + Result (single source)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_speedtest.py`
Expected: PASS — `ok t_parse_result_*`, `ok t_run_argv_*`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/speedtest.py tests/test_speedtest.py
git commit -m "feat(speedtest): Ookla argv + JSON result parsing"
```

---

## Task 2: speedtest.py — local JSONL history store (trimmed to 10)

**Files:**
- Modify: `src/scripts/speedtest.py`
- Test: `tests/test_speedtest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_speedtest.py` (before the `__main__` runner):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_speedtest.py`
Expected: FAIL — `AttributeError: module 'speedtest' has no attribute 'history_path'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/speedtest.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_speedtest.py`
Expected: PASS — all `t_history_*` print `ok`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/speedtest.py tests/test_speedtest.py
git commit -m "feat(speedtest): 10-entry JSONL history store"
```

---

## Task 3: speedtest.py — classify + standalone runtime-dir helper

**Files:**
- Modify: `src/scripts/speedtest.py`
- Test: `tests/test_speedtest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_speedtest.py`:

```python
NOW = 1_000_000           # fixed clock
DAY = 86_400


def t_classify_none_is_info():
    r = m.classify(None, now=NOW)
    assert r.level == pf.INFO and r.name == "bandwidth"
    assert "racecast speedtest" in r.detail


def t_classify_below_minimum_is_warn():
    r = m.classify(_rec(NOW, dl=20.0, ul=8.0), now=NOW)
    assert r.level == pf.WARN and "minimum" in r.detail


def t_classify_worse_side_governs():
    # download fine, upload below minimum -> WARN
    r = m.classify(_rec(NOW, dl=80.0, ul=8.0), now=NOW)
    assert r.level == pf.WARN


def t_classify_between_min_and_recommended_is_warn():
    r = m.classify(_rec(NOW, dl=48.0, ul=22.0), now=NOW)
    assert r.level == pf.WARN and "recommended" in r.detail


def t_classify_at_or_above_recommended_is_pass():
    r = m.classify(_rec(NOW, dl=55.0, ul=25.0), now=NOW)
    assert r.level == pf.PASS


def t_classify_stale_is_warn_regardless_of_value():
    old = _rec(NOW - 10 * DAY, dl=200.0, ul=100.0)   # great numbers, but 10 days old
    r = m.classify(old, now=NOW, max_age_days=7)
    assert r.level == pf.WARN and "stale" in r.detail


def t_default_runtime_dir_repo_layout():
    repo = os.path.join("X", "src", "scripts")
    assert m.default_runtime_dir(repo) == os.path.join("X", "runtime")
    assert m.default_runtime_dir("/some/dist/scripts") == "/some/dist/scripts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_speedtest.py`
Expected: FAIL — `AttributeError: module 'speedtest' has no attribute 'classify'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/speedtest.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_speedtest.py`
Expected: PASS — all `t_classify_*` and `t_default_runtime_dir_*` print `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/speedtest.py tests/test_speedtest.py
git commit -m "feat(speedtest): classify latest result vs documented thresholds"
```

---

## Task 4: speedtest.py — runner + standalone CLI (run/render/main)

**Files:**
- Modify: `src/scripts/speedtest.py`
- Test: `tests/test_speedtest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_speedtest.py`:

```python
def t_run_raises_when_binary_missing():
    try:
        m.run(now=NOW, runtime_dir="/tmp/nope", which=lambda n: None)
    except m.SpeedtestUnavailable as exc:
        assert "install-tools" in str(exc)
        return
    raise AssertionError("expected SpeedtestUnavailable")


def t_run_parses_and_appends(tmp=None):
    import tempfile
    d = tempfile.mkdtemp()

    class _Proc:
        returncode = 0
        stdout = OOKLA_JSON
        stderr = ""

    rec = m.run(now=NOW, runtime_dir=d,
                runner=lambda *a, **k: _Proc(), which=lambda n: "/usr/bin/speedtest")
    assert rec["download_mbps"] == 48.0
    assert m.load_latest(d)["ts"] == NOW           # persisted


def t_run_raises_on_nonzero_exit():
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Configuration - Could not retrieve"
    try:
        m.run(now=NOW, runtime_dir="/tmp/x",
              runner=lambda *a, **k: _Proc(), which=lambda n: "/usr/bin/speedtest")
    except m.SpeedtestFailed:
        return
    raise AssertionError("expected SpeedtestFailed")


def t_render_contains_key_lines():
    rec = m.parse_result(OOKLA_JSON, now=NOW)
    text = m.render(rec, now=NOW)
    assert "Download  48.0 Mbps" in text
    assert "Upload    22.0 Mbps" in text
    assert "speedtest.net/result" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_speedtest.py`
Expected: FAIL — `AttributeError: module 'speedtest' has no attribute 'run'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/speedtest.py`:

```python
def run(now, runtime_dir, runner=subprocess.run, which=shutil.which):
    """Run one measurement, append it to the history, and return the record.
    Raises SpeedtestUnavailable (binary missing) or SpeedtestFailed (run error)."""
    if which(SPEEDTEST_BIN) is None:
        raise SpeedtestUnavailable(
            "Ookla speedtest CLI not found — run `racecast install-tools` "
            "(or install it manually).")
    proc = runner(run_argv(), capture_output=True, text=True)
    out = (getattr(proc, "stdout", "") or "").strip()
    if getattr(proc, "returncode", 1) != 0 or not out:
        err = (getattr(proc, "stderr", "") or "").strip() or "no output"
        raise SpeedtestFailed(f"speedtest did not complete (no internet?): {err}")
    record = parse_result(out, now)
    append_record(record, runtime_dir)
    return record


def render(record, now):
    """Human-readable summary for the CLI."""
    c = classify(record, now)
    lines = ["Bandwidth speed test (Ookla)",
             f"  Download  {record['download_mbps']:.1f} Mbps   "
             f"(min {MIN_DOWN_MBPS:.0f} / rec {REC_DOWN_MBPS:.0f})",
             f"  Upload    {record['upload_mbps']:.1f} Mbps   "
             f"(min {MIN_UP_MBPS:.0f} / rec {REC_UP_MBPS:.0f})"]
    if record.get("ping_ms") is not None:
        extra = f"  Ping      {record['ping_ms']:.0f} ms"
        if record.get("jitter_ms") is not None:
            extra += f" · jitter {record['jitter_ms']:.0f} ms"
        if record.get("packet_loss") is not None:
            extra += f" · loss {record['packet_loss']:.0f}%"
        lines.append(extra)
    if record.get("server"):
        lines.append(f"  Server    {record['server']}")
    if record.get("isp"):
        lines.append(f"  ISP       {record['isp']}")
    if record.get("result_url"):
        lines.append(f"  Result    {record['result_url']}")
    lines.append(f"  => {c.level}: {c.detail}")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="speedtest",
        description="Opt-in Ookla bandwidth speed test; logs the result locally.")
    ap.add_argument("--runtime-dir", default=None,
                    help="Directory holding speedtest-history.jsonl "
                         "(default: the project runtime dir).")
    ap.add_argument("--json", action="store_true",
                    help="Print the stored record as JSON instead of a summary.")
    a = ap.parse_args(argv)
    runtime_dir = a.runtime_dir or default_runtime_dir(
        os.path.dirname(os.path.abspath(__file__)))
    print("Running Ookla speed test — this takes ~20–30 s…")
    try:
        rec = run(time.time(), runtime_dir)
    except SpeedtestUnavailable as exc:
        print(str(exc))
        return 2
    except SpeedtestFailed as exc:
        print(str(exc))
        return 1
    print(json.dumps(rec, indent=2) if a.json else render(rec, time.time()))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_speedtest.py`
Expected: PASS — all `t_run_*` and `t_render_*` print `ok`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/speedtest.py tests/test_speedtest.py
git commit -m "feat(speedtest): runner + standalone CLI (run/render/main)"
```

---

## Task 5: Wire `racecast speedtest` one-shot + binary hidden-import

**Files:**
- Modify: `src/racecast.py` (`USAGE` ~line 24, `ONESHOTS` ~line 647, `ONESHOT_MAP` ~line 1871, `RUNTIME_DIR_ONESHOTS` ~line 1885)
- Modify: `tools/build-binary.py:84`
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Write the failing test**

Find how `tests/test_racecast.py` exercises `route()` (it imports `racecast` and calls `route`). Add:

```python
def t_route_speedtest_is_oneshot():
    assert rc.route(["speedtest"]) == {"kind": "oneshot", "command": "speedtest", "rest": []}
    assert rc.route(["speedtest", "--json"]) == \
        {"kind": "oneshot", "command": "speedtest", "rest": ["--json"]}


def t_speedtest_is_a_runtime_dir_oneshot():
    # It must receive --runtime-dir <base> so history lands at the machine-level runtime.
    assert "speedtest" in rc.RUNTIME_DIR_ONESHOTS
    assert rc.ONESHOT_MAP["speedtest"] == "scripts/speedtest.py"
```

(Match the existing import alias in the file — it is `import racecast as rc` or similar; reuse whatever the file already uses.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `route(["speedtest"])` raises `ValueError: unknown command: speedtest`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`, add `speedtest` to the one-shot tuple (~line 647):

```python
ONESHOTS = ("preflight", "speedtest", "cookies", "graphics", "media", "setup", "install-tools", "install-apps", "update")
```

Add it to `ONESHOT_MAP` (~line 1871, after the `preflight` entry):

```python
    "preflight":     "scripts/preflight.py",
    "speedtest":     "scripts/speedtest.py",
```

Add it to `RUNTIME_DIR_ONESHOTS` (~line 1885) so the CLI passes `--runtime-dir <base>`:

```python
RUNTIME_DIR_ONESHOTS = ("preflight", "speedtest", "cookies")
```

Update the `USAGE` docstring line (~line 24) to advertise it:

```python
  racecast preflight | speedtest [--json] | cookies [twitch] [browser] | graphics | media | setup [--out PATH] | install-tools [--yes] [--update] | install-apps [--yes] [--update]
```

In `tools/build-binary.py` (~line 84), add the hidden import (preflight imports it lazily and the UI provider imports it):

```python
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "speedtest",
           "--hidden-import", "install_apps", "--hidden-import", "obs_ws",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS.

Also verify the CLI end-to-end (binary missing path is fine — it prints the install hint and exits 2):

Run: `python3 src/racecast.py speedtest`
Expected (if `speedtest` is not installed): prints "Running Ookla speed test …" then "Ookla speedtest CLI not found — run `racecast install-tools` …".

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tools/build-binary.py tests/test_racecast.py
git commit -m "feat(cli): racecast speedtest one-shot"
```

---

## Task 6: Preflight reads the latest result into the Network section

**Files:**
- Modify: `src/scripts/preflight.py` (`gather()` ~line 432; add `_speedtest_max_age()`)
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Find how `tests/test_preflight.py` loads the module (importlib as `m`/`pf`). Add tests that drive the new helper and the network section directly (no real history file needed for `_speedtest_max_age`; the section is covered via `speedtest.classify`, already tested — here we lock the env reader and that the static advisory survives):

```python
def t_speedtest_max_age_env(monkeypatch=None):
    import os
    os.environ.pop("RACECAST_SPEEDTEST_MAX_AGE_DAYS", None)
    assert m._speedtest_max_age() == 7.0                 # default
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "3"
    assert m._speedtest_max_age() == 3.0
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "junk"
    assert m._speedtest_max_age() == 7.0                 # bad value -> default
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "-1"
    assert m._speedtest_max_age() == 7.0                 # non-positive -> default
    os.environ.pop("RACECAST_SPEEDTEST_MAX_AGE_DAYS", None)


def t_network_section_has_bandwidth_and_advisory():
    import tempfile
    sections = dict(m.gather(m.__file__, runtime_dir=tempfile.mkdtemp()))
    net = sections["Network"]
    # first entry is the measured/INFO bandwidth result, advisory remains last
    assert net[0].name == "bandwidth"
    assert any("wired connection" in r.detail for r in net)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute '_speedtest_max_age'`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/preflight.py`, add the env reader near the other helpers (e.g. just above `gather`):

```python
def _speedtest_max_age():
    """Staleness window in days for the stored speed-test result.
    RACECAST_SPEEDTEST_MAX_AGE_DAYS overrides; bad/non-positive -> 7."""
    raw = os.environ.get("RACECAST_SPEEDTEST_MAX_AGE_DAYS", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 7.0
    return value if value > 0 else 7.0
```

Replace the existing `network = [Result(INFO, "bandwidth", ...)]` block (~lines 432-435) with a measured-first version. `speedtest` is imported lazily and wrapped best-effort so this feature can never crash the report:

```python
    advisory = Result(INFO, "bandwidth",
                      "OBS pushes the program to YouTube WHILE the relay pulls up to "
                      "3 live feeds. Use a wired connection with stable upload headroom "
                      "above your OBS bitrate.")
    try:
        import speedtest as st          # lazy: avoids an import cycle (st imports Result from us)
        st_dir = runtime_dir or st.default_runtime_dir(
            os.path.dirname(os.path.abspath(preflight_file)))
        network = [st.classify(st.load_latest(st_dir), time.time(), _speedtest_max_age()),
                   advisory]
    except Exception:   # never let the speed-test read break the report
        network = [advisory]
```

(`time` and `os` are already imported at the top of `preflight.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS.

Also smoke the whole report:

Run: `python3 src/racecast.py preflight`
Expected: the `Network` section now shows `[INFO] bandwidth   not measured yet — run \`racecast speedtest\`` followed by the wired-connection advisory.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): show the stored bandwidth measurement in Network"
```

---

## Task 7: install-tools learns the Ookla CLI

**Files:**
- Modify: `src/scripts/install_tools.py` (add builders + extend `manual_guide` + `main()` call)
- Test: `tests/test_install_tools.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_tools.py` (before the `__main__` runner):

```python
def t_speedtest_install_commands_per_manager():
    win = m.speedtest_install_commands("winget")
    assert win == [["winget", "install", "--id", "Ookla.Speedtest.CLI", "-e",
                    "--accept-package-agreements", "--accept-source-agreements"]]
    brew = m.speedtest_install_commands("brew", brew_path="/opt/homebrew/bin/brew")
    assert brew == [["/opt/homebrew/bin/brew", "tap", "teamookla/speedtest"],
                    ["/opt/homebrew/bin/brew", "install", "speedtest"]]
    assert m.speedtest_install_commands("apt") == []     # Ookla needs its own repo -> manual


def t_speedtest_update_commands_per_manager():
    assert m.speedtest_update_commands("winget")[0][:3] == ["winget", "upgrade", "--id"]
    assert m.speedtest_update_commands("brew", brew_path="b") == [["b", "upgrade", "speedtest"]]
    assert m.speedtest_update_commands("apt") == []


def t_manual_guide_mentions_speedtest():
    assert "Ookla.Speedtest.CLI" in m.manual_guide("win32")
    assert "teamookla/speedtest" in m.manual_guide("darwin")
    assert "speedtest" in m.manual_guide("linux")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_install_tools.py`
Expected: FAIL — `AttributeError: module 'install_tools' has no attribute 'speedtest_install_commands'`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/install_tools.py`, add the constants + builders (near `WINGET_IDS`):

```python
# The Ookla speedtest CLI is an OPTIONAL, opt-in tool (used only by
# `racecast speedtest`). It is deliberately NOT in TOOLS so its absence never
# turns the preflight tool-chain into a FAIL. Its install is non-uniform across
# OSes (mac needs a tap; Linux needs Ookla's own apt repo), so it has its own
# builders instead of the shared install_commands() dicts.
SPEEDTEST_WINGET_ID = "Ookla.Speedtest.CLI"
SPEEDTEST_BREW_TAP = "teamookla/speedtest"
SPEEDTEST_BREW_FORMULA = "speedtest"


def speedtest_install_commands(manager, brew_path="brew"):
    if manager == "winget":
        return [["winget", "install", "--id", SPEEDTEST_WINGET_ID, "-e",
                 "--accept-package-agreements", "--accept-source-agreements"]]
    if manager == "brew":
        return [[brew_path, "tap", SPEEDTEST_BREW_TAP],
                [brew_path, "install", SPEEDTEST_BREW_FORMULA]]
    return []   # apt: Ookla needs its own repo -> manual_guide()


def speedtest_update_commands(manager, brew_path="brew"):
    if manager == "winget":
        return [["winget", "upgrade", "--id", SPEEDTEST_WINGET_ID, "-e",
                 "--accept-package-agreements", "--accept-source-agreements"]]
    if manager == "brew":
        return [[brew_path, "upgrade", SPEEDTEST_BREW_FORMULA]]
    return []
```

Extend `manual_guide()` so each branch mentions speedtest:

```python
def manual_guide(platform):
    if platform.startswith("win"):
        return ("Install manually with winget (one per line):\n"
                + "\n".join(f"  winget install --id {WINGET_IDS[t]} -e" for t in TOOLS)
                + f"\n  winget install --id {SPEEDTEST_WINGET_ID} -e   # optional: bandwidth speed test")
    if platform == "darwin":
        return ("Install manually:  brew install yt-dlp streamlink ffmpeg deno\n"
                "  optional bandwidth speed test:  brew tap teamookla/speedtest && brew install speedtest")
    return ("Install manually:  sudo apt-get install -y yt-dlp streamlink ffmpeg\n"
            "deno has no apt package — see https://docs.deno.com/runtime/getting_started/installation/\n"
            "optional bandwidth speed test (Ookla speedtest CLI) — needs Ookla's apt repo:\n"
            "  see https://www.speedtest.net/apps/cli\n"
            "NOTE: apt's yt-dlp lags upstream; for a current build: pip install -U yt-dlp")
```

Wire it into `main()` — after the core-tool `cmds` are assembled and before they run, append the speedtest commands when the CLI is absent (or always on `--update`). Locate the `cmds += install_commands(...)` line in `main()` and add below it:

```python
    cmds += install_commands(manager, missing, brew_path=brew or "brew")
    # Optional Ookla speedtest CLI (opt-in feature; best-effort, never blocks the core tools).
    if shutil.which(SPEEDTEST_BIN_NAME) is None:
        cmds += speedtest_install_commands(manager, brew_path=brew or "brew")
    elif a.update:
        cmds += speedtest_update_commands(manager, brew_path=brew or "brew")
```

Add the binary-name constant near the others (kept separate from `TOOLS`):

```python
SPEEDTEST_BIN_NAME = "speedtest"
```

After the `cmds` loop, when `manager == "apt"`, print the manual speedtest note (next to the existing deno note):

```python
    if manager == "apt":
        print("NOTE: the Ookla speedtest CLI is not in apt — install it manually if you")
        print("      want `racecast speedtest`:  https://www.speedtest.net/apps/cli")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_install_tools.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_tools.py tests/test_install_tools.py
git commit -m "feat(install-tools): install the optional Ookla speedtest CLI"
```

---

## Task 8: Control Center — op, /api/speedtest, Preflight-view card

**Files:**
- Modify: `src/ui/ui_ops.py` (`OPS` ~line 36)
- Modify: `src/ui/ui_server.py` (route, near `/api/preflight` ~line 323)
- Modify: `src/racecast.py` (`speedtest_data` provider + register in the providers dict ~line 3617)
- Modify: `src/ui/control-center.html` (Preflight view ~line 743; JS near `runPreflight` ~line 1779)
- Test: `tests/test_ui_server.py`, `tests/test_racecast.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_racecast.py`, add a provider + op test:

```python
def t_speedtest_op_registered():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "ui"))
    import ui_ops
    assert ui_ops.OPS["speedtest"] == ["speedtest"]


def t_speedtest_data_shape(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp()
    # seed one record through the speedtest module the provider reads
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "scripts"))
    import speedtest as st
    st.append_record({"ts": 1, "download_mbps": 50.0, "upload_mbps": 20.0,
                      "ping_ms": 9.0, "jitter_ms": 1.0, "packet_loss": 0.0,
                      "server": "S", "isp": "I", "result_url": None}, d)
    out = rc.speedtest_data(base_dir=d)
    assert out["ok"] is True
    assert out["latest"]["download_mbps"] == 50.0
    assert len(out["history"]) == 1
```

In `tests/test_ui_server.py`, mirror the existing `/api/preflight` route test with a `speedtest` provider stub in the ctx and assert `GET /api/speedtest` returns it. (Follow the file's existing pattern for building `ctx` and issuing a request — reuse the same helper the `/api/preflight` test uses.)

```python
def t_api_speedtest_route():
    ctx = _ctx(speedtest=lambda: {"ok": True, "latest": None, "history": []})
    body = _get(ctx, "/api/speedtest")
    assert body == {"ok": True, "latest": None, "history": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py` and `python3 tests/test_ui_server.py`
Expected: FAIL — `KeyError: 'speedtest'` (OPS) / `AttributeError: speedtest_data` / route 404.

- [ ] **Step 3: Write minimal implementation**

`src/ui/ui_ops.py` — register the op after `"preflight": ["preflight"],` (~line 36):

```python
    "preflight": ["preflight"],
    "speedtest": ["speedtest"],
```

`src/racecast.py` — add the provider (near `preflight_data`, ~line 3125) and register it (~line 3617):

```python
def speedtest_data(base_dir=None):
    """Latest + recent speed-test history for the Control Center Preflight view.
    Read-only (the *run* goes through the `speedtest` op/job). Never raises."""
    try:
        import speedtest as st
        base = base_dir or _runtime_base_dir()
        return {"ok": True, "latest": st.load_latest(base), "history": st.load_history(base)}
    except Exception as exc:
        return {"ok": False, "error": f"speedtest read failed: {exc}"}
```

In the providers dict (after `"preflight": preflight_data,` ~line 3617):

```python
        "preflight": preflight_data,
        "speedtest": speedtest_data,
```

`src/ui/ui_server.py` — add the route after the `/api/preflight` block (~line 329):

```python
            if path == "/api/speedtest":
                try:
                    return self._json(ctx["speedtest"]())
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"speedtest read failed: {exc}"},
                                      code=500)
```

`src/ui/control-center.html` — add a Speed-test card inside the `data-view="preflight"` block, right after the `<div class="viewhead">…Run</div>` line (~line 748), before `<div id="pf-body">`:

```html
        <section id="pf-speedtest">
          <div class="row">
            <span class="name">Bandwidth speed test</span>
            <span class="badge" id="st-badge" hidden><span class="dot"></span><span></span></span>
            <span class="dim grow" id="st-latest">not measured yet</span>
            <button id="st-run" onclick="runSpeedtest()">
              <svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>Run speed test</button>
          </div>
          <div id="st-history" class="dim"></div>
          <p class="envhint">Runs the <b>Ookla speedtest CLI</b> (install via <b>install-tools</b>).
            It measures the line <b>idle</b> — a capability check; the true under-load picture is OBS's
            live stats while streaming. Ookla is closed-source and each run sends its result to Ookla
            (like a speedtest.net run in a browser).</p>
        </section>
```

Add the JS near `runPreflight` (~line 1779). `op()` already streams a job to the console; after it finishes we refresh the card from `/api/speedtest`:

```javascript
async function loadSpeedtest() {
  let d;
  try { d = await (await fetch('/api/speedtest', {cache: 'no-store'})).json(); }
  catch (e) { return; }
  if (!d || !d.ok) return;
  const latest = d.latest, el = $('st-latest'), badge = $('st-badge');
  if (!latest) { el.textContent = 'not measured yet'; badge.hidden = true; }
  else {
    const ageH = Math.round((Date.now()/1000 - latest.ts) / 3600);
    const age = ageH < 1 ? 'just now' : ageH < 24 ? ageH + ' h ago' : Math.round(ageH/24) + ' d ago';
    el.textContent = `↓${latest.download_mbps} ↑${latest.upload_mbps} Mbps · ${age}`
      + (latest.server ? ' · ' + latest.server : '');
    const ok = latest.download_mbps >= 50 && latest.upload_mbps >= 20;
    const min = latest.download_mbps >= 25 && latest.upload_mbps >= 10;
    badge.hidden = false;
    badge.className = 'badge ' + (ok ? 'ok' : min ? 'warn' : 'bad');
    badge.querySelector('span:last-child').textContent = ok ? 'OK' : min ? 'min' : 'low';
  }
  const rows = (d.history || []).map(r => {
    const t = new Date(r.ts * 1000).toLocaleString();
    return `<div class="row"><span class="mono grow">${t}</span>`
      + `<span class="mono">↓${r.download_mbps}</span> <span class="mono">↑${r.upload_mbps}</span>`
      + `<span class="mono">${r.ping_ms ?? '–'} ms</span></div>`;
  }).join('');
  $('st-history').innerHTML = rows;
}

async function runSpeedtest() {
  await op('speedtest', false);   // streams the Ookla output into the console job
  loadSpeedtest();
}
```

Call `loadSpeedtest()` when the Preflight view opens — extend the existing line ~943:

```javascript
  if (name === 'preflight' && !preflightRun) { preflightRun = true; runPreflight(); }
  if (name === 'preflight') loadSpeedtest();
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_racecast.py` and `python3 tests/test_ui_server.py`
Expected: PASS.

Manual check: `python3 src/racecast.py ui --no-browser`, open the Control Center, go to Preflight — the Speed-test card shows "not measured yet" and the "Run speed test" button is present. (Running it needs the Ookla CLI installed.)

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_ops.py src/ui/ui_server.py src/racecast.py src/ui/control-center.html tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(ui): speed test card in the Preflight view"
```

---

## Task 9: Config knob + docs

**Files:**
- Modify: `.env.example`, `src/docs/wiki/Set-up-the-broadcast-PC.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Add the staleness knob to `.env.example`**

Add (near the other `RACECAST_*` entries):

```bash
# Days before a stored bandwidth speed-test result is treated as stale by
# `racecast preflight` (WARN: "re-measure before the event"). Default 7.
RACECAST_SPEEDTEST_MAX_AGE_DAYS=7
```

- [ ] **Step 2: Document the command in the bandwidth section**

In `src/docs/wiki/Set-up-the-broadcast-PC.md`, in the "Internet — bandwidth and wiring" section (after the min/recommended table ~line 48), add a short subsection:

```markdown
### Measuring your line

Run an opt-in speed test and let preflight check it against the table above:

- **CLI:** `racecast speedtest` (add `--json` for machine-readable output).
- **Control Center:** Preflight view → **Run speed test**.

Each run is logged locally (the last 10 are kept). `racecast preflight` reads the
latest result and **warns** when download/upload is below the **25 / 10 Mbps**
minimum, or when the measurement is older than `RACECAST_SPEEDTEST_MAX_AGE_DAYS`
(default 7) — it never hard-blocks readiness. The test measures the line **idle**,
so treat it as a *capability* check; the true under-load picture is OBS's live
stats while streaming.

The speed test uses the **Ookla Speedtest CLI** (`racecast install-tools` installs
it on Windows/macOS; on Linux see <https://www.speedtest.net/apps/cli>). Ookla is
closed-source and each run sends its result to Ookla — the same data egress as
running speedtest.net in a browser.
```

- [ ] **Step 3: Add the command to `CLAUDE.md` and `README.md`**

In `CLAUDE.md`, in the unified-CLI command block (after the `racecast preflight` line), add:

```bash
python3 src/racecast.py speedtest          # opt-in Ookla bandwidth test; logs locally, preflight warns vs 25/10 Mbps
```

In `README.md`, add a matching one-line entry wherever `preflight` is listed for operators.

- [ ] **Step 4: Verify docs build/lint**

Run: `python3 tools/lint.py`
Expected: no new lint errors (docs are not linted, but this catches any stray Python edits).

- [ ] **Step 5: Commit**

```bash
git add .env.example src/docs/wiki/Set-up-the-broadcast-PC.md CLAUDE.md README.md
git commit -m "docs(speedtest): document racecast speedtest + the staleness knob"
```

---

## Task 10: Screenshot, full suite, lint, build verify

**Files:**
- Regenerate: `src/docs/wiki/images/cc-preflight.png`

- [ ] **Step 1: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: every `tests/test_*.py` passes (incl. the new `test_speedtest.py`). Cross-file enumerations (the OPS map, preflight sections, ONESHOTS) are exercised here — fix any breakage before continuing.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: clean (no new alerts). If `speedtest.py` has a bare `except Exception` in preflight, confirm it carries the explanatory comment already written (`# never let the speed-test read break the report`).

- [ ] **Step 3: Regenerate the Preflight screenshot**

The Preflight view changed (new Speed-test card), so `cc-preflight.png` is stale (CLAUDE.md hard rule). Recapture it by driving a running instance with the Playwright MCP:

1. `python3 src/racecast.py ui --no-browser`
2. Playwright MCP: navigate to `http://127.0.0.1:8089`, click the **Preflight** nav item, press **Run**, wait for the checklist + the Speed-test card to render.
3. Take an **element** screenshot of the Preflight view container (the `data-view="preflight"` block) so the framing matches the other `cc-*.png` images, and save to `src/docs/wiki/images/cc-preflight.png`.

- [ ] **Step 4: Build self-verify**

Run: `python3 tools/build.py`
Expected: the verify step passes (tokenization, blanked password, no secrets, preflight present, no shell scripts). This confirms `speedtest.py` ships in `dist/`.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/images/cc-preflight.png
git commit -m "docs(wiki): refresh cc-preflight.png with the speed-test card"
```

---

## Self-Review

**Spec coverage:**
- Decision 1 (Ookla) → Tasks 1, 4, 7. Decision 2 (opt-in, CLI+UI, never auto) → Tasks 5, 8 (preflight only *reads*, Task 6). Decision 3 (logged locally) → Task 2. Decision 4 (below-min = WARN, worse side governs, no FAIL) → Task 3. Decision 5 (staleness WARN, configurable window) → Tasks 3, 6, 9. Decision 6 (keep last 10) → Task 2.
- Spec §1 module → Tasks 1-4. §2 CLI → Task 5. §3 install-tools → Task 7. §4 preflight → Task 6. §5 Control Center → Task 8. §6 config/docs → Task 9. §7 tests → every task (TDD) + Task 10 full suite. Screenshot obligation → Task 10.
- Frozen-binary hidden import (not explicit in the spec but required by the architecture) → Task 5.

**Placeholder scan:** No "TBD"/"handle edge cases" — every code step shows complete code; every test shows real assertions; the one place that defers to an existing file pattern (the `/api/speedtest` route test ctx/helper in Task 8) names the exact analog (`/api/preflight`) to copy.

**Type consistency:** Record keys are identical everywhere (`ts`, `download_mbps`, `upload_mbps`, `ping_ms`, `jitter_ms`, `packet_loss`, `server`, `isp`, `result_url`). `classify(record, now, max_age_days=...)`, `run(now, runtime_dir, runner=..., which=...)`, `load_latest(runtime_dir)`, `load_history(runtime_dir, limit=...)`, `append_record(record, runtime_dir)`, `history_path(runtime_dir)`, `default_runtime_dir(here)` — signatures match across tasks and call sites (preflight Task 6, provider Task 8). Op id `speedtest` and provider key `speedtest` match `OPS`/providers/route. Thresholds `25/10/50/20` appear only as the named constants.
