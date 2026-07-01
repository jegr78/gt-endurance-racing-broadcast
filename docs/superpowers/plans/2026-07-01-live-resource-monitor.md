# Live Resource Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the producer machine's CPU / RAM / Net / Disk live in the Control Center and as history in the `/health-monitor` charts, stdlib-only (no psutil).

**Architecture:** A new pure `src/scripts/resources.py` (per-OS counter readers + pure parsers + delta math + a `ResourceSampler` that owns previous counters + a threaded `ResourceMonitor`). The Control Center UI process runs a `ResourceMonitor` for a live "System" card (`/api/resources`); the relay heartbeat owns a `ResourceSampler` and writes five new `sys_*` columns (health-DB schema v4→v5) that the existing uPlot pipeline charts automatically.

**Tech Stack:** Python 3 stdlib only — `subprocess`, `ctypes` (Windows), `shutil`, `threading`, `/proc` reads (Linux). No new dependency.

## Global Constraints

- **Edit only under `src/` and `tests/`** (plus `docs/` for plan/spec). `dist/`/`runtime/` are generated.
- **English only**; **stdlib only** — no `psutil`, no pip, no vendored dep.
- **No secrets / machine paths / real IPs** in committed files. Tailscale test IPs are `100.64.0.0/10` only.
- **Never raises:** every reader/sampler path degrades to `None` for an unreadable metric; it must never break a request or the relay heartbeat.
- **Cross-platform (CI matrix includes Windows).** Per-OS `_read_*` wrappers are OS-gated and are NOT exercised with real OS calls in tests; the pure parsers + the sampler (via an injected reader map) are the tested surface, so the suite runs on any OS. Any subprocess passes `preflight.no_window_kwargs()` (Windows console-less requirement). Never run `os.path.join` on a fixed-OS path.
- **Redaction:** the `sys_*` health columns are pure numbers — no URLs — so the health-monitor payload / Funnel / takeover-pull stay redaction-safe.
- **Thresholds (color):** CPU green<75 / yellow 75–90 / red ≥90. RAM% green<80 / yellow 80–92 / red ≥92. Disk mirrors `preflight.classify_disk` (red <2 GB, yellow <5 GB, else green). **Net has no color.**
- Test files end with a bare `run()` under `if __name__ == "__main__":` — **never** `sys.exit(run())` (trips `py/procedure-return-value-used`).
- Screenshot hard rule: the Control Center **Home** view changes → `src/docs/wiki/images/cc-home.png` refreshed in the same PR.
- Health-DB constants: `SAMPLE_INTERVAL_S=30`, `SCHEMA_VERSION` currently `4`. The migration ALTER pattern is `_V3_COLUMNS`; add a parallel `_V5_COLUMNS`.

## File Structure

- **Create `src/scripts/resources.py`** — pure parsers, delta math, per-OS readers, `ResourceSampler`, `ResourceMonitor`, color-level helpers, `to_health_fields`.
- **Modify `src/scripts/health_store.py`** — five `sys_*` columns; `_V5_COLUMNS`; `SCHEMA_VERSION=5`; `NUMERIC_FIELDS`.
- **Modify `src/relay/racecast-feeds.py`** — `import resources`; a relay-side `ResourceSampler`; merge `to_health_fields(...)` into `_health_snapshot`.
- **Modify `src/console/health-monitor.html`** — five entries in the `NUMERIC_FIELDS` chart array (group "System (machine)").
- **Modify `src/racecast.py`** — `import resources`; `resources_data()`; a module-level `ResourceMonitor` started in `run_ui`; `ctx["resources"]`.
- **Modify `src/ui/ui_server.py`** — `GET /api/resources` route.
- **Modify `src/ui/control-center.html`** — a "System" card in the Home view + a 2 s poll.
- **Create `tests/test_resources.py`**; **modify** `tests/test_health_store.py`, `tests/test_ui_server.py`.
- **Modify** `README.md`? No CLI verb — wiki only: `src/docs/wiki/Control-Center.md`, `src/docs/wiki/Health-Monitor.md`.

---

### Task 1: Pure resource reader + sampler (`resources.py`)

**Files:**
- Create: `src/scripts/resources.py`
- Test: `tests/test_resources.py`

**Interfaces produced (used by Tasks 3 & 4):**
- `parse_proc_stat_cpu(text) -> (busy,total)|None`, `parse_proc_net_dev(text) -> (rx,tx)`, `parse_netstat_ib(text) -> (rx,tx)`, `parse_top_cpu(text) -> pct|None`, `parse_vm_stat(text) -> used_bytes|None`, `parse_typeperf_net(text) -> (up_bps,down_bps)|None`
- `cpu_pct_from_delta(prev,cur) -> pct|None`, `rate_from_delta(prev,cur,dt) -> bps|None`
- `class ResourceSampler(readers=None)` with `.sample(now=None) -> {ts,cpu_pct,mem_used,mem_total,mem_pct,net_up_bps,net_down_bps,disk_free}`
- `class ResourceMonitor(interval=2.0, sampler=None)` with `.start()`, `.latest() -> dict|None`, `.stop()`
- `cpu_level(pct)`, `mem_level(pct)`, `disk_level(free_bytes)` → `"green"|"yellow"|"red"|None`
- `to_health_fields(snap) -> {sys_cpu_pct, sys_mem_pct, sys_net_up_kbps, sys_net_down_kbps, sys_disk_free_mb}`

- [ ] **Step 1: Write the failing test** — create `tests/test_resources.py`:

```python
#!/usr/bin/env python3
"""Unit checks for the machine resource reader/sampler (pure, stdlib only)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


import sys
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
r = _load("resources", ("src", "scripts", "resources.py"))


def t_parse_proc_stat_cpu():
    text = "cpu  100 0 100 700 100 0 0\ncpu0 ...\n"
    busy, total = r.parse_proc_stat_cpu(text)
    # idle = fields[3]+fields[4] = 700+100 = 800; total = 1100; busy = 300
    assert (busy, total) == (300, 1100), (busy, total)
    assert r.parse_proc_stat_cpu("no cpu line") is None


def t_parse_proc_net_dev():
    text = ("Inter-|   Receive ...\n"
            " face |bytes ...\n"
            "    lo: 100 0 0 0 0 0 0 0 100 0 0 0 0 0 0 0\n"
            "  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n")
    assert r.parse_proc_net_dev(text) == (1000, 2000)   # lo excluded, rx=field0 tx=field8


def t_parse_netstat_ib():
    text = ("Name  Mtu  Network  Address  Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
            "lo0   16384 <Link#1>          10 0 500 10 0 500 0\n"
            "en0   1500  <Link#2>          20 0 3000 20 0 4000 0\n"
            "en0   1500  1.2.3.4  1.2.3.4  20 0 3000 20 0 4000 0\n")   # dup row same iface
    assert r.parse_netstat_ib(text) == (3000, 4000)   # lo0 excluded, en0 counted once


def t_parse_top_cpu():
    text = ("CPU usage: 5.0% user, 5.0% sys, 90.00% idle\n"
            "CPU usage: 12.0% user, 8.0% sys, 80.00% idle\n")
    assert r.parse_top_cpu(text) == 20.0   # last line: 100 - 80


def t_parse_vm_stat():
    text = ("Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages free: 100.\nPages active: 200.\nPages inactive: 50.\n"
            "Pages wired down: 100.\nPages occupied by compressor: 50.\n")
    # used = (active + wired + compressor) * page = (200+100+50)*4096
    assert r.parse_vm_stat(text) == 350 * 4096, r.parse_vm_stat(text)


def t_parse_typeperf_net():
    text = ('"(PDH-CSV 4.0)","\\\\PC\\Network Interface(x)\\Bytes Received/sec","\\\\PC\\Network Interface(x)\\Bytes Sent/sec"\n'
            '"07/01/2026 10:00:00.000","1000.0","2000.0"\n')
    assert r.parse_typeperf_net(text) == (2000.0, 1000.0)   # (up=Sent, down=Received)


def t_cpu_pct_from_delta():
    assert r.cpu_pct_from_delta((300, 1100), (400, 1300)) == 50.0   # db=100 dt=200
    assert r.cpu_pct_from_delta(None, (1, 2)) is None
    assert r.cpu_pct_from_delta((5, 10), (5, 10)) is None           # dt=0
    assert r.cpu_pct_from_delta((5, 100), (4, 200)) is None         # busy went backwards


def t_rate_from_delta():
    assert r.rate_from_delta(1000, 3000, 2.0) == 1000.0
    assert r.rate_from_delta(1000, 3000, 0) is None
    assert r.rate_from_delta(5000, 1000, 2.0) is None               # counter reset


def _fake_readers(seq):
    """seq: list of dicts per tick with keys cpu/net/mem/disk. Returns a readers map
    whose calls pop the next tick's value."""
    ticks = list(seq)
    state = {"i": 0}

    def nextt():
        t = ticks[min(state["i"], len(ticks) - 1)]
        return t

    def adv():
        state["i"] += 1

    return {
        "cpu": lambda: nextt()["cpu"],
        "net": lambda: nextt()["net"],
        "mem": lambda: nextt()["mem"],
        "disk": lambda: (nextt()["disk"], adv())[0],   # disk called last each tick -> advance
    }


def t_sampler_counter_deltas():
    readers = _fake_readers([
        {"cpu": ("counter", 300, 1100), "net": ("counter", 1000, 2000),
         "mem": (8 * 1024**3, 16 * 1024**3), "disk": 100 * 1024**3},
        {"cpu": ("counter", 400, 1300), "net": ("counter", 3000, 6000),
         "mem": (8 * 1024**3, 16 * 1024**3), "disk": 100 * 1024**3},
    ])
    s = r.ResourceSampler(readers=readers)
    first = s.sample(now=1000.0)
    assert first["cpu_pct"] is None and first["net_up_bps"] is None   # no prev yet
    assert first["mem_pct"] == 50.0 and first["disk_free"] == 100 * 1024**3
    second = s.sample(now=1002.0)                                     # dt=2s
    assert second["cpu_pct"] == 50.0, second                          # db=100 dt=200
    # rx 1000->3000 over 2s = 1000/s (down); tx 2000->6000 over 2s = 2000/s (up)
    assert second["net_down_bps"] == 1000.0 and second["net_up_bps"] == 2000.0, second


def t_sampler_percent_and_rate_passthrough():
    readers = _fake_readers([
        {"cpu": ("percent", 42.0), "net": ("rate", 500.0, 700.0),
         "mem": (4 * 1024**3, 8 * 1024**3), "disk": 50 * 1024**3},
    ])
    s = r.ResourceSampler(readers=readers)
    snap = s.sample(now=1.0)
    assert snap["cpu_pct"] == 42.0
    assert snap["net_up_bps"] == 500.0 and snap["net_down_bps"] == 700.0   # (up,down)


def t_sampler_none_on_reader_failure():
    readers = _fake_readers([{"cpu": None, "net": None, "mem": (None, None), "disk": None}])
    snap = r.ResourceSampler(readers=readers).sample(now=1.0)
    assert snap["cpu_pct"] is None and snap["net_up_bps"] is None
    assert snap["mem_pct"] is None and snap["disk_free"] is None


def t_levels():
    assert (r.cpu_level(10), r.cpu_level(80), r.cpu_level(95)) == ("green", "yellow", "red")
    assert (r.mem_level(50), r.mem_level(85), r.mem_level(95)) == ("green", "yellow", "red")
    assert r.cpu_level(None) is None
    assert r.disk_level(1 * 1024**3) == "red"      # <2 GB
    assert r.disk_level(3 * 1024**3) == "yellow"   # <5 GB
    assert r.disk_level(50 * 1024**3) == "green"


def t_to_health_fields():
    snap = {"cpu_pct": 42.0, "mem_pct": 55.0, "net_up_bps": 2000.0,
            "net_down_bps": 1000.0, "disk_free": 100 * 1024 * 1024}
    f = r.to_health_fields(snap)
    assert f == {"sys_cpu_pct": 42.0, "sys_mem_pct": 55.0,
                 "sys_net_up_kbps": 2.0, "sys_net_down_kbps": 1.0,
                 "sys_disk_free_mb": 100.0}, f
    # None-safe
    empty = r.to_health_fields({"cpu_pct": None, "mem_pct": None, "net_up_bps": None,
                                "net_down_bps": None, "disk_free": None})
    assert set(empty.values()) == {None}


def t_monitor_latest_none_then_sampled():
    calls = {"n": 0}

    class _S:
        def sample(self, now=None):
            calls["n"] += 1
            return {"ts": now, "cpu_pct": 1.0, "mem_used": 1, "mem_total": 2,
                    "mem_pct": 50.0, "net_up_bps": None, "net_down_bps": None, "disk_free": 3}
    m = r.ResourceMonitor(interval=0.02, sampler=_S())
    assert m.latest() is None
    m.start()
    import time as _t
    for _ in range(50):
        if m.latest() is not None:
            break
        _t.sleep(0.02)
    m.stop()
    assert m.latest() is not None and calls["n"] >= 1


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

Run: `python3 tests/test_resources.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'resources'`.

- [ ] **Step 3: Write the implementation** — create `src/scripts/resources.py`:

```python
#!/usr/bin/env python3
"""Machine resource sampling — CPU %, RAM, network throughput, free disk (stdlib only).

Pure parsers + delta math are unit-tested with fixture strings; `ResourceSampler` owns the
previous cumulative counters and computes deltas; `ResourceMonitor` runs a sampler on a
background thread and caches the latest snapshot. Per-OS reads mirror preflight.py (Linux
/proc, Windows ctypes, macOS subprocess). Never raises — an unreadable metric is None.
"""
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from preflight import no_window_kwargs
except ImportError:                                  # pragma: no cover - path fallback
    def no_window_kwargs(os_name=None):
        import os as _os
        if (os_name or _os.name) == "nt":
            return {"creationflags": 0x08000000}
        return {}

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ---------- pure parsers ----------

def parse_proc_stat_cpu(text):
    """First 'cpu ' line of /proc/stat -> (busy, total) jiffies, or None."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            f = [int(x) for x in line.split()[1:]]
            idle = f[3] + (f[4] if len(f) > 4 else 0)     # idle + iowait
            total = sum(f)
            return (total - idle, total)
    return None


def parse_proc_net_dev(text):
    """/proc/net/dev -> (rx_bytes, tx_bytes) summed over non-loopback interfaces."""
    rx = tx = 0
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        f = rest.split()
        if name == "lo" or len(f) < 9:
            continue
        rx += int(f[0])
        tx += int(f[8])
    return (rx, tx)


def parse_netstat_ib(text):
    """macOS `netstat -ib` -> (rx_bytes, tx_bytes) over non-lo0 ifaces (one row per iface)."""
    lines = text.splitlines()
    if not lines:
        return (0, 0)
    hdr = lines[0].split()
    try:
        ri, ti = hdr.index("Ibytes"), hdr.index("Obytes")
    except ValueError:
        return (0, 0)
    rx = tx = 0
    seen = set()
    for line in lines[1:]:
        f = line.split()
        if len(f) <= max(ri, ti):
            continue
        name = f[0]
        if name.startswith("lo") or name in seen:
            continue
        seen.add(name)
        try:
            rx += int(f[ri]); tx += int(f[ti])
        except ValueError:
            continue
    return (rx, tx)


def parse_top_cpu(text):
    """macOS `top -l2 -s1 -n0` -> busy % from the LAST 'CPU usage' line (100 - idle)."""
    pct = None
    for line in text.splitlines():
        if "CPU usage" in line:
            m = re.search(r"([\d.]+)%\s*idle", line)
            if m:
                pct = round(100.0 - float(m.group(1)), 1)
    return pct


def parse_vm_stat(text):
    """macOS `vm_stat` -> bytes in use ((active+wired+compressor) * page_size), or None."""
    m = re.search(r"page size of (\d+) bytes", text)
    page = int(m.group(1)) if m else 4096

    def pages(label):
        mm = re.search(label + r":\s+(\d+)", text)
        return int(mm.group(1)) if mm else 0
    active = pages(r"Pages active")
    wired = pages(r"Pages wired down")
    comp = pages(r"Pages occupied by compressor")
    if not (active or wired):
        return None
    return (active + wired + comp) * page


def parse_typeperf_net(text):
    """Windows `typeperf` CSV -> (up_bps, down_bps) from the last data row, or None."""
    import csv
    import io
    hdr = None
    data = None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if any("Bytes" in c for c in row):
            hdr = row
        elif hdr and len(row) == len(hdr):
            data = row
    if not hdr or not data:
        return None
    up = down = 0.0
    got = False
    for i, col in enumerate(hdr):
        try:
            val = float(data[i])
        except (ValueError, IndexError):
            continue
        if "Received" in col:
            down += val; got = True
        elif "Sent" in col:
            up += val; got = True
    return (up, down) if got else None


# ---------- pure delta math ----------

def cpu_pct_from_delta(prev, cur):
    """(busy,total) pairs -> percent, or None (no prev / non-positive dt / counter reset)."""
    if not prev or not cur:
        return None
    db = cur[0] - prev[0]
    dt = cur[1] - prev[1]
    if dt <= 0 or db < 0:
        return None
    return round(min(100.0, max(0.0, db / dt * 100.0)), 1)


def rate_from_delta(prev, cur, dt):
    """Cumulative byte counters -> bytes/sec, or None (no prev / dt<=0 / reset)."""
    if prev is None or cur is None or dt <= 0 or cur < prev:
        return None
    return (cur - prev) / dt


# ---------- color levels ----------

def cpu_level(pct):
    if pct is None:
        return None
    return "red" if pct >= 90 else "yellow" if pct >= 75 else "green"


def mem_level(pct):
    if pct is None:
        return None
    return "red" if pct >= 92 else "yellow" if pct >= 80 else "green"


def disk_level(free_bytes):
    """Mirrors preflight.classify_disk thresholds (2 GB / 5 GB)."""
    if free_bytes is None:
        return None
    gb = free_bytes / (1024 ** 3)
    return "red" if gb < 2 else "yellow" if gb < 5 else "green"


# ---------- per-OS real readers (OS-gated; not unit-tested with real calls) ----------

def _read_cpu():
    """-> ('counter', busy, total) | ('percent', pct) | None."""
    try:
        if IS_LINUX:
            with open("/proc/stat") as fh:
                got = parse_proc_stat_cpu(fh.read())
            return ("counter", got[0], got[1]) if got else None
        if IS_WIN:
            import ctypes
            idle, kern, user = (ctypes.c_ulonglong(), ctypes.c_ulonglong(),
                                ctypes.c_ulonglong())
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),
                                                         ctypes.byref(kern),
                                                         ctypes.byref(user)):
                return None
            total = kern.value + user.value        # kernel time includes idle
            return ("counter", total - idle.value, total)
        if IS_MAC:
            out = subprocess.run(["top", "-l", "2", "-s", "1", "-n", "0"],
                                 capture_output=True, text=True, timeout=6,
                                 **no_window_kwargs()).stdout
            pct = parse_top_cpu(out)
            return ("percent", pct) if pct is not None else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _read_net():
    """-> ('counter', rx, tx) | ('rate', up_bps, down_bps) | None."""
    try:
        if IS_LINUX:
            with open("/proc/net/dev") as fh:
                rx, tx = parse_proc_net_dev(fh.read())
            return ("counter", rx, tx)
        if IS_MAC:
            out = subprocess.run(["netstat", "-ib"], capture_output=True, text=True,
                                 timeout=6, **no_window_kwargs()).stdout
            rx, tx = parse_netstat_ib(out)
            return ("counter", rx, tx)
        if IS_WIN:
            out = subprocess.run(
                ["typeperf", r"\Network Interface(*)\Bytes Received/sec",
                 r"\Network Interface(*)\Bytes Sent/sec", "-sc", "1"],
                capture_output=True, text=True, timeout=10, **no_window_kwargs()).stdout
            got = parse_typeperf_net(out)
            return ("rate", got[0], got[1]) if got else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _read_mem():
    """-> (used_bytes, total_bytes); either may be None."""
    try:
        if IS_LINUX:
            total = avail = None
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) * 1024
            used = (total - avail) if (total is not None and avail is not None) else None
            return (used, total)
        if IS_WIN:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MS()
            st.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return (st.ullTotalPhys - st.ullAvailPhys, st.ullTotalPhys)
        if IS_MAC:
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"],
                                                **no_window_kwargs()).strip())
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=6,
                                 **no_window_kwargs()).stdout
            return (parse_vm_stat(out), total)
    except (OSError, ValueError, subprocess.SubprocessError):
        return (None, None)
    return (None, None)


def _read_disk_free(path="."):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _default_readers():
    return {"cpu": _read_cpu, "net": _read_net, "mem": _read_mem, "disk": _read_disk_free}


# ---------- sampler + monitor ----------

class ResourceSampler:
    """Owns the previous cumulative CPU + net counters; each sample() computes deltas
    since the last call. Never raises — a failed metric is None. Inject `readers` (the
    default = the real per-OS readers) to unit-test the delta logic without OS calls."""

    def __init__(self, readers=None):
        self.readers = readers or _default_readers()
        self._prev_cpu = None      # (busy, total)
        self._prev_net = None      # (rx, tx)
        self._prev_ts = None

    def _cpu(self, reading):
        if not reading:
            return None
        if reading[0] == "percent":
            return reading[1]
        if reading[0] == "counter":
            cur = (reading[1], reading[2])
            pct = cpu_pct_from_delta(self._prev_cpu, cur)
            self._prev_cpu = cur
            return pct
        return None

    def _net(self, reading, now):
        if not reading:
            return (None, None)
        if reading[0] == "rate":
            return (reading[1], reading[2])           # (up_bps, down_bps)
        if reading[0] == "counter":
            cur = (reading[1], reading[2])            # (rx, tx)
            dt = (now - self._prev_ts) if self._prev_ts is not None else 0
            prev = self._prev_net
            down = rate_from_delta(prev[0] if prev else None, cur[0], dt)
            up = rate_from_delta(prev[1] if prev else None, cur[1], dt)
            self._prev_net = cur
            return (up, down)
        return (None, None)

    def sample(self, now=None):
        now = time.time() if now is None else now
        cpu_pct = None
        net_up = net_down = None
        mem_used = mem_total = None
        disk_free = None
        try:
            cpu_pct = self._cpu(self.readers["cpu"]())
        except Exception:  # noqa: BLE001 - never raise
            cpu_pct = None
        try:
            net_up, net_down = self._net(self.readers["net"](), now)
        except Exception:  # noqa: BLE001
            net_up = net_down = None
        try:
            mem_used, mem_total = self.readers["mem"]()
        except Exception:  # noqa: BLE001
            mem_used = mem_total = None
        try:
            disk_free = self.readers["disk"]()
        except Exception:  # noqa: BLE001
            disk_free = None
        mem_pct = (round(mem_used / mem_total * 100, 1)
                   if (mem_used and mem_total) else None)
        self._prev_ts = now
        return {"ts": now, "cpu_pct": cpu_pct,
                "mem_used": mem_used, "mem_total": mem_total, "mem_pct": mem_pct,
                "net_up_bps": net_up, "net_down_bps": net_down, "disk_free": disk_free}


class ResourceMonitor:
    """Runs a ResourceSampler on a daemon thread, caching the latest snapshot under a
    lock. `.latest()` is None until the first tick completes."""

    def __init__(self, interval=2.0, sampler=None):
        self.interval = interval
        self.sampler = sampler or ResourceSampler()
        self._latest = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                snap = self.sampler.sample()
                with self._lock:
                    self._latest = snap
            except Exception:  # noqa: BLE001 - keep the thread alive
                pass
            self._stop.wait(self.interval)

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def latest(self):
        with self._lock:
            return dict(self._latest) if self._latest else None

    def stop(self):
        self._stop.set()


def to_health_fields(snap):
    """Map a ResourceSampler snapshot to the health_store sys_* columns (%, kbps, MB).
    None-safe."""
    def kbps(bps):
        return round(bps / 1000.0, 1) if bps is not None else None

    def mb(b):
        return round(b / (1024 * 1024), 1) if b is not None else None
    return {"sys_cpu_pct": snap.get("cpu_pct"),
            "sys_mem_pct": snap.get("mem_pct"),
            "sys_net_up_kbps": kbps(snap.get("net_up_bps")),
            "sys_net_down_kbps": kbps(snap.get("net_down_bps")),
            "sys_disk_free_mb": mb(snap.get("disk_free"))}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_resources.py`
Expected: `ok t_...` for each and `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/resources.py tests/test_resources.py
git commit -m "feat(resources): stdlib machine resource reader + sampler"
```

---

### Task 2: Health-DB v5 columns + migration

**Files:**
- Modify: `src/scripts/health_store.py`
- Test: `tests/test_health_store.py`

**Interfaces produced (used by Task 3):** the five new columns exist in `COLUMNS`, are created by `migrate()`, and appear in `NUMERIC_FIELDS`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_health_store.py` (keep its bare-`run()` footer):

```python
def t_v5_sys_columns_present_and_charted():
    cols = set(hs.COLUMNS)
    for c in ("sys_cpu_pct", "sys_mem_pct", "sys_net_up_kbps",
              "sys_net_down_kbps", "sys_disk_free_mb"):
        assert c in cols, c
        assert c in hs.NUMERIC_FIELDS, c
    assert hs.SCHEMA_VERSION >= 5


def t_v5_migration_adds_sys_columns_losslessly():
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "old.db")
        # simulate a pre-v5 DB: create samples WITHOUT the sys_* columns, one row
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE samples (ts REAL NOT NULL, kind TEXT NOT NULL, "
                     "health_level TEXT)")
        conn.execute("INSERT INTO samples (ts, kind, health_level) VALUES (1.0,'periodic','green')")
        conn.commit(); conn.close()
        conn = hs.open_db(path)
        hs.migrate(conn)                                  # must add sys_* without loss
        try:
            have = {r["name"] for r in conn.execute("PRAGMA table_info(samples)").fetchall()}
            assert {"sys_cpu_pct", "sys_disk_free_mb"} <= have, have
            rows = conn.execute("SELECT ts, health_level FROM samples").fetchall()
            assert len(rows) == 1 and rows[0]["health_level"] == "green"   # old row survived
            assert conn.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
        finally:
            conn.close()


def t_v5_sys_fields_roundtrip_and_series():
    with tempfile.TemporaryDirectory() as d:
        conn = hs.open_db(os.path.join(d, "h.db")); hs.migrate(conn)
        try:
            hs.record(conn, _snap(ts=0.0) | {"sys_cpu_pct": 40.0, "sys_mem_pct": 55.0,
                                             "sys_net_up_kbps": 2.0, "sys_net_down_kbps": 1.0,
                                             "sys_disk_free_mb": 100.0}, "periodic")
            hs.record(conn, _snap(ts=30.0) | {"sys_cpu_pct": 60.0}, "periodic")
            rows = hs.query_range(conn, 0, 1e12)
            assert rows[0]["sys_cpu_pct"] == 40.0 and rows[0]["sys_disk_free_mb"] == 100.0
            series = hs.numeric_series(rows)
            assert series["sys_cpu_pct"]["v"] == [40.0, 60.0], series["sys_cpu_pct"]
        finally:
            conn.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_health_store.py`
Expected: FAIL — `sys_cpu_pct` not in `COLUMNS`.

- [ ] **Step 3: Implement** — in `src/scripts/health_store.py`:

3a. Bump the version: `SCHEMA_VERSION = 5`.

3b. Append the five columns to the `COLUMNS` tuple (after `"pov_quality",`, before the closing paren), with a comment:
```python
    # v5: machine (host) resources — distinct from the obs_* process stats above
    "sys_cpu_pct", "sys_mem_pct", "sys_net_up_kbps", "sys_net_down_kbps",
    "sys_disk_free_mb",
```

3c. Add them to the fresh-DB DDL in `_CREATE`, inside the `samples` table definition, right after the `feed_a_quality TEXT, feed_b_quality TEXT, pov_quality TEXT` line (add a trailing comma to that line):
```sql
    feed_a_quality TEXT, feed_b_quality TEXT, pov_quality TEXT,
    sys_cpu_pct REAL, sys_mem_pct REAL, sys_net_up_kbps REAL,
    sys_net_down_kbps REAL, sys_disk_free_mb REAL
```

3d. Add the v5 ALTER list after `_V3_COLUMNS`:
```python
_V5_COLUMNS = (
    ("sys_cpu_pct", "REAL"), ("sys_mem_pct", "REAL"),
    ("sys_net_up_kbps", "REAL"), ("sys_net_down_kbps", "REAL"),
    ("sys_disk_free_mb", "REAL"),
)
```

3e. In `migrate()`, extend the ALTER loop to also add the v5 columns — change the loop line
`    for name, decl in _V3_COLUMNS:` to:
```python
    for name, decl in _V3_COLUMNS + _V5_COLUMNS:
```

3f. Add them to `NUMERIC_FIELDS` (so `numeric_series` emits them), appending inside that tuple:
```python
                  "sys_cpu_pct", "sys_mem_pct", "sys_net_up_kbps",
                  "sys_net_down_kbps", "sys_disk_free_mb")
```
(Append these before the closing paren of the existing `NUMERIC_FIELDS = (...)`.)

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_health_store.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py` — exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/health_store.py tests/test_health_store.py
git commit -m "feat(health): v5 sys_* machine-resource columns + migration"
```

---

### Task 3: Relay heartbeat samples machine resources → history charts

**Files:**
- Modify: `src/relay/racecast-feeds.py` (import; a relay-side `ResourceSampler`; merge into `_health_snapshot`)
- Modify: `src/console/health-monitor.html` (chart entries)

**Interfaces:**
- Consumes: `resources.ResourceSampler`, `resources.to_health_fields` (Task 1); the `sys_*` columns (Task 2).

- [ ] **Step 1: Add the import.** In `src/relay/racecast-feeds.py`, near the other `src/scripts` imports (after `import event_notes`), add:
```python
import resources  # noqa: E402 - machine resource sampler (health history)
```

- [ ] **Step 2: Own a sampler on the relay.** In `Relay.__init__` (find where `self.health_store` / heartbeat state like `self._last_prune` is initialised), add:
```python
        self._resource_sampler = resources.ResourceSampler()
```

- [ ] **Step 3: Merge machine resources into the snapshot.** In `_health_snapshot(self, now)` (src/relay/racecast-feeds.py), just before the final `return { ... }` dict, compute the machine fields best-effort:
```python
        try:
            sys_res = resources.to_health_fields(self._resource_sampler.sample(now))
        except Exception:  # noqa: BLE001 - sampling is best-effort, never break the heartbeat
            sys_res = {}
```
and add `**sys_res,` as the last entry inside the returned dict (after `"pov_quality": ...`). Because the sampler's previous counters carry between heartbeats, the CPU %/net values are the average over the ~30 s heartbeat interval (None on the very first tick) — expected.

- [ ] **Step 4: Add the charts.** In `src/console/health-monitor.html`, append to the `NUMERIC_FIELDS` array (before the closing `];`):
```javascript
  ["sys_cpu_pct", "CPU %", "System (machine)"],
  ["sys_mem_pct", "Memory %", "System (machine)"],
  ["sys_net_up_kbps", "Net up (kbps)", "System (machine)"],
  ["sys_net_down_kbps", "Net down (kbps)", "System (machine)"],
  ["sys_disk_free_mb", "Disk free (MB)", "System (machine)"],
```

- [ ] **Step 5: Verify the relay still imports + POV unit checks pass.**

Run: `python3 tests/test_pov.py`
Expected: `ALL PASS` (the relay module imports `resources` cleanly and the snapshot builds).

Also sanity-check the module imports standalone:
Run: `python3 -c "import importlib.util,sys; sys.path.insert(0,'src/scripts'); s=importlib.util.spec_from_file_location('m','src/relay/racecast-feeds.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py` — exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py src/console/health-monitor.html
git commit -m "feat(relay): sample machine resources into health history + charts"
```

---

### Task 4: Control Center live "System" card

**Files:**
- Modify: `src/racecast.py` (import; `resources_data`; module-level `ResourceMonitor` started in `run_ui`; `ctx["resources"]`)
- Modify: `src/ui/ui_server.py` (`GET /api/resources`)
- Modify: `src/ui/control-center.html` (Home "System" card + 2 s poll)
- Test: `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `resources.ResourceMonitor`, `resources.cpu_level/mem_level/disk_level` (Task 1).
- Produces: `GET /api/resources -> {available:true, cpu_pct, cpu_level, mem_used, mem_total, mem_pct, mem_level, net_up_bps, net_down_bps, disk_free, disk_level} | {available:false}`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_ui_server.py` (match its real `_ctx`/`_serve`/`_get`-style harness — read the file first; the snippet below assumes a GET helper like the existing route tests use):

```python
def t_api_resources_route():
    ctx = _ctx()
    ctx["resources"] = lambda: {"available": True, "cpu_pct": 42.0, "cpu_level": "green",
                                "mem_used": 8, "mem_total": 16, "mem_pct": 50.0,
                                "mem_level": "green", "net_up_bps": 2000.0,
                                "net_down_bps": 1000.0, "disk_free": 100, "disk_level": "green"}
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/resources")          # use this file's real GET helper
        data = json.loads(body)
        assert code == 200 and data["available"] is True
        assert data["cpu_pct"] == 42.0 and data["disk_level"] == "green"
    finally:
        httpd.shutdown()
```
If `tests/test_ui_server.py` has no GET helper, add the route assertion using its established server harness (the important part: `GET /api/resources` returns `ctx["resources"]()`).

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — `/api/resources` 404s.

- [ ] **Step 3: Add the route.** In `src/ui/ui_server.py` `do_GET`, next to the `/api/status` branch:
```python
            if path == "/api/resources":
                try:
                    return self._json(ctx["resources"]())
                except Exception as exc:
                    return self._json({"available": False, "error": str(exc)}, code=500)
```

- [ ] **Step 4: Provider + monitor in `src/racecast.py`.**

4a. Add the import near `import report_build as rbuild`:
```python
import resources
```

4b. Add a module-level monitor + provider near the other `*_data` providers (e.g. after `ui_status_payload`):
```python
_resource_monitor = None


def resources_data():
    """Latest machine-resource snapshot + color levels for the Control Center System card.
    {available:false} until the monitor has a first sample; never raises."""
    if _resource_monitor is None:
        return {"available": False}
    snap = _resource_monitor.latest()
    if snap is None:
        return {"available": False}
    return {"available": True,
            "cpu_pct": snap["cpu_pct"], "cpu_level": resources.cpu_level(snap["cpu_pct"]),
            "mem_used": snap["mem_used"], "mem_total": snap["mem_total"],
            "mem_pct": snap["mem_pct"], "mem_level": resources.mem_level(snap["mem_pct"]),
            "net_up_bps": snap["net_up_bps"], "net_down_bps": snap["net_down_bps"],
            "disk_free": snap["disk_free"], "disk_level": resources.disk_level(snap["disk_free"])}
```

4c. Start the monitor in `run_ui` (before `srv.serve(...)`), using a `global`:
```python
    global _resource_monitor
    _resource_monitor = resources.ResourceMonitor(interval=2.0)
    _resource_monitor.start()
```

4d. Register in the `ctx` dict (near `"status": ui_status_payload,`):
```python
        "resources": resources_data,
```

- [ ] **Step 5: Front-end System card.** In `src/ui/control-center.html`:

5a. Add a card in the Home view (after the existing status `<section>` blocks, before the view's closing `</div>`):
```html
        <section id="home-system">
          <div class="viewhead"><h3>System</h3></div>
          <div class="row"><span class="name">CPU</span>
            <span class="badge" id="sys-cpu"><span class="dot"></span><span>…</span></span></div>
          <div class="row"><span class="name">Memory</span>
            <span class="badge" id="sys-mem"><span class="dot"></span><span>…</span></span></div>
          <div class="row"><span class="name">Network</span>
            <span class="dim" id="sys-net">…</span></div>
          <div class="row"><span class="name">Disk free</span>
            <span class="badge" id="sys-disk"><span class="dot"></span><span>…</span></span></div>
        </section>
```

5b. Add the poll + render JS (near the other poll setup, after `refresh()` is defined). Reuse the page's `setBadge`/`$` helpers if present; the badge tint follows the `*_level`:
```javascript
function _mbps(bps) { return bps == null ? '—' : (bps / 1e6).toFixed(2) + ' Mbps'; }
function _lvlText(el, level, text) {
  const b = $(el); if (!b) return;
  b.className = 'badge' + (level ? ' lvl-' + level : '');
  b.querySelector('span:last-child').textContent = text;
}
async function refreshResources() {
  let d;
  try { d = await (await fetch('/api/resources', {cache: 'no-store'})).json(); }
  catch (e) { return; }
  if (!d || !d.available) { return; }
  _lvlText('sys-cpu', d.cpu_level, d.cpu_pct == null ? '—' : d.cpu_pct.toFixed(0) + ' %');
  const memTxt = (d.mem_used && d.mem_total)
    ? (d.mem_used / 1073741824).toFixed(1) + ' / ' + (d.mem_total / 1073741824).toFixed(0)
      + ' GB · ' + (d.mem_pct == null ? '—' : d.mem_pct.toFixed(0) + '%')
    : '—';
  _lvlText('sys-mem', d.mem_level, memTxt);
  $('sys-net').textContent = '↑ ' + _mbps(d.net_up_bps) + '   ↓ ' + _mbps(d.net_down_bps);
  _lvlText('sys-disk', d.disk_level,
           d.disk_free == null ? '—' : (d.disk_free / 1073741824).toFixed(1) + ' GB free');
}
refreshResources();
setInterval(refreshResources, 2000);
```

5c. Add minimal level-tint CSS near the other badge styles (only if the page has no `.lvl-*` classes already — grep first):
```css
    .badge.lvl-green .dot { background: #2e7d32; }
    .badge.lvl-yellow .dot { background: #f9a825; }
    .badge.lvl-red .dot { background: #c62828; }
```

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_ui_server.py && python3 tests/test_racecast.py && python3 tools/lint.py`
Expected: `ALL PASS` / exit 0.

- [ ] **Step 7: Commit (code only — screenshot is Task 4b)**

```bash
git add src/racecast.py src/ui/ui_server.py src/ui/control-center.html tests/test_ui_server.py
git commit -m "feat(ui): Control Center live System resource card"
```

---

### Task 4b: Refresh `cc-home.png` (screenshot — blocking hard rule)

**Files:** Add/replace `src/docs/wiki/images/cc-home.png`

- [ ] **Step 1:** Use the `wiki-screenshots` skill. Start the dev-build Control Center on a free port so the version badge reads "dev" and the System card shows this machine's real (synthetic-free) values:
```bash
python3 src/racecast.py profile use demo
RACECAST_UI_PORT=8090 python3 src/racecast.py ui --no-browser &
```
- [ ] **Step 2:** Drive the Playwright MCP to `http://127.0.0.1:8090/` (Home view is default), wait ~3 s so `refreshResources` has run at least twice (CPU/net populate on the 2nd tick), take a **viewport** screenshot, save to `src/docs/wiki/images/cc-home.png`. The card shows real local CPU/RAM/Net/Disk — no Tailscale IP is in the card, so it is safe/reproducible.
- [ ] **Step 3:** Clean up: `pkill -f "racecast.py ui"`; `git checkout -- profiles/demo/profile.env` (only if a relay was started — it was not here, but check it stayed secret-free); remove any scratch PNG dropped in the repo root.
- [ ] **Step 4:** Commit:
```bash
git add src/docs/wiki/images/cc-home.png
git commit -m "docs: refresh Control Center Home screenshot with the System card"
```

---

### Task 5: Docs

**Files:** `src/docs/wiki/Control-Center.md`, `src/docs/wiki/Health-Monitor.md`

- [ ] **Step 1:** In `src/docs/wiki/Control-Center.md`, add a **System** subsection to the Home-view description: the card shows live CPU %, RAM used/total + %, Net ↑/↓, Disk free, color-coded (CPU 75/90, RAM 80/92, Disk 2/5 GB; Net is informational/uncolored). Reference `images/cc-home.png` if that page shows the Home screenshot (match the existing image-reference convention).
- [ ] **Step 2:** In `src/docs/wiki/Health-Monitor.md`, note the new **System (machine)** chart group (CPU %, Memory %, Net up/down kbps, Disk free MB), sampled every 30 s alongside the OBS stats; empty for history recorded before the upgrade.
- [ ] **Step 3:** Validate wiki links: `python3 tests/test_wiki.py` → `ALL PASS`.
- [ ] **Step 4:** Commit:
```bash
git add src/docs/wiki
git commit -m "docs(resources): document the System card + machine-resource charts"
```

---

## Final verification (before the PR)

- [ ] `python3 tools/run-tests.py` — whole suite green (new `test_resources.py`; modified `test_health_store.py` / `test_ui_server.py`; `test_pov.py`).
- [ ] `python3 tools/lint.py` — exit 0.
- [ ] `python3 tools/build.py` — exit 0.
- [ ] `cc-home.png` committed; `profiles/demo/profile.env` secret-free; no scratch files.

## Self-Review (author checklist — completed)

1. **Spec coverage:** reader/sampler + per-OS + delta → Task 1; both surfaces → Task 4 (live card) + Tasks 2/3 (history); metrics CPU/RAM/Net/Disk → Task 1 + card + columns; thresholds → `cpu_level/mem_level/disk_level` (Net uncolored) Task 1; two independent samplers → relay (Task 3) + UI monitor (Task 4); schema v4→v5 + migration → Task 2; charts → Task 3; screenshot → Task 4b; docs → Task 5; never-raises + no_window_kwargs + redaction (numbers only) covered in Task 1 + constraints.
2. **Placeholder scan:** none; every code step carries complete code. The Task-4 test + the front-end `setBadge`/`$` reuse explicitly say to match the real `control-center.html`/`test_ui_server.py` helpers (must be read from those files).
3. **Type consistency:** `ResourceSampler.sample()` keys (`cpu_pct/mem_used/mem_total/mem_pct/net_up_bps/net_down_bps/disk_free`) are consumed identically by `to_health_fields` (Task 1/3) and `resources_data` (Task 4). `to_health_fields` output keys equal the Task-2 `sys_*` columns. Net order is `(up, down)` everywhere. `cpu_level/mem_level/disk_level` signatures match their calls in `resources_data`.
