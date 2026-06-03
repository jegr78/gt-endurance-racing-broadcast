# Pre-Flight Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A cross-platform `preflight.py` that a producer runs before an event to confirm the machine is ready (hardware, tools, ports, cookies), printing a traffic-light report and returning a non-zero exit code on any FAIL.

**Architecture:** One pure-stdlib Python script in `src/scripts/`. Platform-specific readers (RAM/swap/disk) are isolated behind small functions; pure classifier functions turn raw numbers into PASS/WARN/FAIL `Result`s (so the logic is unit-testable); socket probes check ports; `main()` orchestrates and prints sections. `tools/build.py` already copies `src/scripts/` into the package, so no build change is required. A "System Requirements" section is added to `README_SETUP.md`.

**Tech Stack:** Python 3 standard library only (`os`, `sys`, `shutil`, `socket`, `subprocess`, `ctypes`, `argparse`, `time`, `dataclasses`). Tests follow the existing `tests/test_pov.py` pattern (importlib load + `t_*` functions, run via `python3 tests/test_preflight.py`).

> **NOTE — git:** This working dir is **not yet a git repo**. The Commit steps below assume one exists. Before starting, either run `git init && git add -A && git commit -m "snapshot before preflight"` once, or skip every "Commit" step. Do not change this decision mid-plan.

> **Threshold reference (single source of truth for all classifiers):**
> RAM: FAIL `<16`, WARN `16–<32`, PASS `≥32` (GB). CPU logical cores: FAIL `<6`, WARN `6–7`, PASS `≥8`. Free disk: FAIL `<2`, WARN `<5`, PASS `≥5` (GB). Swap used: WARN `>1` GB else PASS (never FAIL). Cookies: WARN if missing, `>12 h` old, or no login marker; else PASS.

---

### Task 1: `Result` type + pure classifiers

**Files:**
- Create: `src/scripts/preflight.py`
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_preflight.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for preflight.py. Run: python3 tests/test_preflight.py"""
import importlib.util, os, socket, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "preflight", os.path.join(ROOT, "src", "scripts", "preflight.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_classify_ram_boundaries():
    assert m.classify_ram(15.9).level == "FAIL"
    assert m.classify_ram(16).level == "WARN"
    assert m.classify_ram(31.9).level == "WARN"
    assert m.classify_ram(32).level == "PASS"


def t_classify_cpu_boundaries():
    assert m.classify_cpu(5).level == "FAIL"
    assert m.classify_cpu(6).level == "WARN"
    assert m.classify_cpu(7).level == "WARN"
    assert m.classify_cpu(8).level == "PASS"


def t_classify_disk_boundaries():
    assert m.classify_disk(1).level == "FAIL"
    assert m.classify_disk(4).level == "WARN"
    assert m.classify_disk(5).level == "PASS"


def t_classify_swap_boundaries():
    assert m.classify_swap(0.5).level == "PASS"
    assert m.classify_swap(2).level == "WARN"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `FileNotFoundError`/`spec` error or `AttributeError: module ... has no attribute 'classify_ram'` (preflight.py does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/preflight.py`:

```python
#!/usr/bin/env python3
"""Pre-flight readiness check for the IRO broadcast setup.

Run before an event to confirm this machine can run OBS + the relay:
hardware, tool chain, ports, and YouTube cookies. Prints a traffic-light
report; exit code is 0 if nothing FAILs, 1 otherwise.

Usage:  python3 scripts/preflight.py
Pure Python 3 standard library — no third-party dependencies.
"""
from dataclasses import dataclass

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


@dataclass
class Result:
    level: str
    name: str
    detail: str


def classify_ram(gb):
    if gb < 16:
        return Result(FAIL, "RAM", f"{gb:.1f} GB — below the 16 GB minimum")
    if gb < 32:
        return Result(WARN, "RAM",
                      f"{gb:.1f} GB — works; 32 GB recommended (OBS + 14 HUD "
                      f"browser sources + relay are memory-heavy)")
    return Result(PASS, "RAM", f"{gb:.1f} GB")


def classify_cpu(n):
    if n < 6:
        return Result(FAIL, "CPU cores", f"{n} logical cores — below the 6-core minimum")
    if n < 8:
        return Result(WARN, "CPU cores", f"{n} logical cores — works; 8+ recommended")
    return Result(PASS, "CPU cores", f"{n} logical cores")


def classify_disk(gb):
    if gb < 2:
        return Result(FAIL, "Free disk", f"{gb:.1f} GB free — below the 2 GB minimum")
    if gb < 5:
        return Result(WARN, "Free disk", f"{gb:.1f} GB free — low; 5 GB+ recommended")
    return Result(PASS, "Free disk", f"{gb:.1f} GB free")


def classify_swap(gb):
    if gb > 1:
        return Result(WARN, "Swap in use",
                      f"{gb:.1f} GB swapped — not a fresh boot / under memory "
                      f"pressure; reboot before the event")
    return Result(PASS, "Swap in use", f"{gb:.1f} GB swapped")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS — prints `ok t_classify_*` lines and `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): Result type + hardware classifiers"
```

---

### Task 2: Platform readers (RAM / swap / disk)

**Files:**
- Modify: `src/scripts/preflight.py`
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py` (before the `__main__` block):

```python
def t_readers_return_sane_values():
    assert m.read_ram_bytes() > 0
    assert m.disk_free_bytes(".") > 0
    assert m.read_swap_used_bytes() >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'read_ram_bytes'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/preflight.py` (after the imports — add `import ctypes, os, re, shutil, subprocess, sys` near the top, below the docstring):

```python
import ctypes
import os
import re
import shutil
import subprocess
import sys


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _win_memstatus():
    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat


def read_ram_bytes():
    if sys.platform == "darwin":
        return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
    if sys.platform.startswith("linux"):
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024  # kB -> bytes
        return 0
    if sys.platform.startswith("win"):
        return _win_memstatus().ullTotalPhys
    raise OSError(f"unsupported platform: {sys.platform}")


def read_swap_used_bytes():
    if sys.platform == "darwin":
        out = subprocess.check_output(["sysctl", "-n", "vm.swapusage"]).decode()
        match = re.search(r"used\s*=\s*([\d.]+)([KMG])", out)
        if not match:
            return 0
        mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[match.group(2)]
        return int(float(match.group(1)) * mult)
    if sys.platform.startswith("linux"):
        total = free = 0
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("SwapTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("SwapFree:"):
                    free = int(line.split()[1]) * 1024
        return max(0, total - free)
    if sys.platform.startswith("win"):
        stat = _win_memstatus()
        return max(0, stat.ullTotalPageFile - stat.ullAvailPageFile)
    return 0


def disk_free_bytes(path):
    return shutil.disk_usage(path).free
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS — `ok t_readers_return_sane_values` plus all prior tests, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): cross-platform RAM/swap/disk readers"
```

---

### Task 3: Socket + tool probes

**Files:**
- Modify: `src/scripts/preflight.py`
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py` (before the `__main__` block):

```python
def t_port_free_detects_used_and_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.listen(1)
    try:
        assert m.port_free(port) is False
    finally:
        s.close()
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(("127.0.0.1", 0)); free = s2.getsockname()[1]; s2.close()
    assert m.port_free(free) is True


def t_port_reachable():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.listen(1)
    try:
        assert m.port_reachable("127.0.0.1", port) is True
    finally:
        s.close()
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(("127.0.0.1", 0)); closed = s2.getsockname()[1]; s2.close()
    assert m.port_reachable("127.0.0.1", closed, timeout=0.3) is False


def t_tool_version_missing():
    assert m.tool_version("definitely-not-a-real-tool-xyz") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'port_free'`.

- [ ] **Step 3: Write minimal implementation**

Add `import socket` to the import block in `src/scripts/preflight.py`, then add:

```python
import socket


def port_free(port, host="127.0.0.1"):
    """True if nothing is bound to host:port (a fresh socket can bind it)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def port_reachable(host, port, timeout=0.5):
    """True if a TCP connection to host:port succeeds (a service is listening)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def tool_version(name):
    """Return the first line of `<name> --version`, or None if not on PATH."""
    path = shutil.which(name)
    if not path:
        return None
    try:
        out = subprocess.run([name, "--version"], capture_output=True,
                             text=True, timeout=10)
        lines = (out.stdout or out.stderr).strip().splitlines()
        return lines[0] if lines else path
    except Exception:
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS — `ok t_port_free_detects_used_and_free`, `ok t_port_reachable`, `ok t_tool_version_missing`, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): port + tool-version probes"
```

---

### Task 4: Cookies location + status

**Files:**
- Modify: `src/scripts/preflight.py`
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py` (before the `__main__` block):

```python
def t_resolve_cookies_overrides():
    assert m.resolve_cookies_path("/x/scripts/preflight.py", None,
                                  "/c/cookies.txt") == "/c/cookies.txt"
    assert m.resolve_cookies_path("/x/scripts/preflight.py", "/run",
                                  None) == os.path.join("/run", "cookies.txt")


def t_cookies_missing():
    with tempfile.TemporaryDirectory() as d:
        r = m.cookies_status(os.path.join(d, "nope.txt"))
        assert r.level == "WARN"


def t_cookies_old():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cookies.txt")
        open(p, "w").write("SAPISID\tval")
        old = time.time() - 20 * 3600
        os.utime(p, (old, old))
        r = m.cookies_status(p)
        assert r.level == "WARN" and "old" in r.detail.lower()


def t_cookies_fresh_with_marker():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cookies.txt")
        open(p, "w").write("host\tTRUE\t/\tTRUE\t0\tSAPISID\tval")
        r = m.cookies_status(p)
        assert r.level == "PASS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'resolve_cookies_path'`.

- [ ] **Step 3: Write minimal implementation**

Add `import time` to the import block in `src/scripts/preflight.py`, then add:

```python
import time

COOKIE_MARKERS = ("SAPISID", "__Secure-3PSID", "__Secure-1PSID", "LOGIN_INFO")


def resolve_cookies_path(preflight_file, runtime_dir=None, cookies_opt=None):
    """Locate cookies.txt the way the relay does.

    Priority: explicit --cookies, then --runtime-dir/cookies.txt, then the
    first existing candidate (package layout scripts/+relay/, repo layout
    src/scripts/+runtime/, or next to this script). Falls back to the
    package-expected path so the report names a sensible location.
    """
    if cookies_opt:
        return cookies_opt
    if runtime_dir:
        return os.path.join(runtime_dir, "cookies.txt")
    here = os.path.dirname(os.path.abspath(preflight_file))
    candidates = [
        os.path.join(here, "..", "relay", "cookies.txt"),          # package layout
        os.path.join(here, "..", "..", "runtime", "cookies.txt"),  # repo layout
        os.path.join(here, "cookies.txt"),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return os.path.abspath(candidates[0])


def cookies_status(path, max_age_hours=12, now=None):
    now = time.time() if now is None else now
    if not os.path.isfile(path):
        return Result(WARN, "cookies.txt",
                      f"not found at {path} — run get-cookies before the event")
    age_h = (now - os.path.getmtime(path)) / 3600
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        text = ""
    has_login = any(marker in text for marker in COOKIE_MARKERS)
    if age_h > max_age_hours:
        return Result(WARN, "cookies.txt",
                      f"{age_h:.0f} h old — cookies rotate; re-run get-cookies")
    if not has_login:
        return Result(WARN, "cookies.txt",
                      "present but no logged-in YouTube session markers found")
    return Result(PASS, "cookies.txt",
                  f"present, fresh ({age_h:.0f} h old), logged-in markers found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS — `ok t_resolve_cookies_overrides`, `ok t_cookies_missing`, `ok t_cookies_old`, `ok t_cookies_fresh_with_marker`, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): cookies.txt location + freshness check"
```

---

### Task 5: Reporter, CLI, and `main()`

**Files:**
- Modify: `src/scripts/preflight.py`
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py` (before the `__main__` block):

```python
def t_main_returns_int():
    rc = m.main([])
    assert rc in (0, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

Add `import argparse` to the import block in `src/scripts/preflight.py`, then add:

```python
import argparse

COLORS = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", INFO: "\033[36m"}
RESET = "\033[0m"

# ports the relay binds (must be FREE) and services we probe (should be REACHABLE)
FEED_PORTS = (53001, 53002, 53003, 8088)
SERVICE_PORTS = ((4455, "OBS WebSocket"), (8000, "Companion"))
REQUIRED_TOOLS = ("streamlink", "yt-dlp", "ffmpeg", "deno")


def enable_color(no_color):
    if no_color or not sys.stdout.isatty():
        return False
    if sys.platform.startswith("win"):
        try:
            kernel = ctypes.windll.kernel32
            kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


def fmt_result(result, color):
    tag = f"{COLORS.get(result.level, '')}{result.level}{RESET}" if color else result.level
    return f"  [{tag}] {result.name}: {result.detail}"


def gather(preflight_file, runtime_dir=None, cookies_opt=None):
    """Run every check and return a list of (section_title, [Result])."""
    hardware = [
        classify_ram(read_ram_bytes() / 1024 ** 3),
        classify_cpu(os.cpu_count() or 0),
        classify_disk(disk_free_bytes(os.getcwd()) / 1024 ** 3),
        classify_swap(read_swap_used_bytes() / 1024 ** 3),
    ]
    tools = []
    for name in REQUIRED_TOOLS:
        version = tool_version(name)
        tools.append(Result(PASS, name, version) if version
                     else Result(FAIL, name, "not found on PATH — required by the relay"))
    py = sys.version.split()[0]
    tools.append(Result(PASS, "python3", py) if sys.version_info >= (3, 8)
                 else Result(FAIL, "python3", f"{py} — need 3.8+"))
    ports = []
    for port in FEED_PORTS:
        ports.append(Result(PASS, f"port {port}", "free") if port_free(port)
                     else Result(WARN, f"port {port}",
                                 "in use — relay already running or a port conflict"))
    for port, svc in SERVICE_PORTS:
        ports.append(Result(PASS, f"port {port}", f"{svc} reachable")
                     if port_reachable("127.0.0.1", port)
                     else Result(WARN, f"port {port}",
                                 f"{svc} not reachable — start it before going live"))
    cookies = [cookies_status(resolve_cookies_path(preflight_file, runtime_dir, cookies_opt))]
    network = [Result(INFO, "bandwidth",
                      "OBS pushes the program to YouTube WHILE the relay pulls up to "
                      "3 live feeds. Use a wired connection with stable upload headroom "
                      "above your OBS bitrate.")]
    return [
        ("Hardware", hardware),
        ("Tool chain", tools),
        ("Ports", ports),
        ("YouTube cookies", cookies),
        ("Network", network),
    ]


def report(sections, color):
    fails = warns = 0
    for title, results in sections:
        print(f"\n{title}")
        for result in results:
            print(fmt_result(result, color))
            if result.level == FAIL:
                fails += 1
            elif result.level == WARN:
                warns += 1
    print(f"\nSummary: {fails} FAIL, {warns} WARN")
    if fails:
        print("NOT READY — resolve the FAIL items above.")
    elif warns:
        print("Usable, but review the WARN items "
              "(reboot to clear swap; start OBS/Companion; refresh cookies).")
    else:
        print("READY.")
    return 1 if fails else 0


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="Pre-flight readiness check for the IRO broadcast setup.")
    ap.add_argument("--runtime-dir", default=None,
                    help="Directory holding cookies.txt (mirrors the relay's --runtime-dir).")
    ap.add_argument("--cookies", default=None,
                    help="Explicit path to cookies.txt (overrides --runtime-dir).")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    color = enable_color(args.no_color)
    sections = gather(__file__, args.runtime_dir, args.cookies)
    return report(sections, color)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS — `main([])` prints a full report, returns 0 or 1; `ok t_main_returns_int`, then `ALL PASS`.

- [ ] **Step 5: Run the script end-to-end (manual smoke)**

Run: `python3 src/scripts/preflight.py`
Expected: a sectioned, colored report (Hardware / Tool chain / Ports / YouTube cookies / Network) ending in a `Summary:` line and a verdict. Exit code: `echo $?` is 0 or 1.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): reporter, CLI args, and main orchestration"
```

---

### Task 6: System Requirements section in README_SETUP.md

**Files:**
- Modify: `src/docs/README_SETUP.md`

- [ ] **Step 1: Read the file and find the insertion point**

Run: `sed -n '1,40p' src/docs/README_SETUP.md`
Identify the end of the intro (just after the title / first paragraph, before the first numbered setup step). Insert the new section there.

- [ ] **Step 2: Insert the section**

Add this block (English, team-facing) after the intro:

```markdown
## System Requirements

Run `python3 scripts/preflight.py` on the producer machine before every event —
it checks all of the below and your tool chain, ports, and YouTube cookies.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU       | 6-core modern (Intel 12th-gen i5 / AMD Ryzen 5) | 8-core+ (i7 / Ryzen 7) |
| RAM       | 16 GB | 32 GB |
| GPU       | hardware encoder (NVIDIA NVENC / Apple Silicon / Intel QSV) | dedicated NVIDIA GPU w/ NVENC |
| Disk      | SSD, ≥ 5 GB free | SSD |
| OS        | Windows 10/11 64-bit or macOS 13+ | — |
| Network   | wired; stable upload headroom for the YouTube push + up to 3 feed pulls | wired gigabit |

**Before each event:** reboot the machine (clears swap and frees RAM), then run
the pre-flight check and resolve any FAIL/WARN before going live. OBS runs 14 HUD
browser sources plus the live feeds, so RAM is the most common bottleneck.
```

- [ ] **Step 3: Verify it reads correctly**

Run: `grep -n "System Requirements" src/docs/README_SETUP.md`
Expected: one match, in the intro area.

- [ ] **Step 4: Commit**

```bash
git add src/docs/README_SETUP.md
git commit -m "docs(readme): add System Requirements + pre-flight usage"
```

---

### Task 7: Build the package and verify

**Files:**
- Modify: `tools/build.py` (optional verify check)

- [ ] **Step 1 (optional): Add a build-verify check**

In `src/../tools/build.py`, in the `checks` dict inside `main()` (around line 87-93), add one entry:

```python
        "preflight shipped": os.path.isfile(os.path.join(PKG, "scripts", "preflight.py")),
```

- [ ] **Step 2: Run the build**

Run: `python3 tools/build.py`
Expected: prints `Built .../IRO_Broadcast_Package`, the ZIP size, and `[OK]` for every check (including `no .sh/.bat shipped` and, if added, `preflight shipped`). No `BUILD VERIFY FAILED`.

- [ ] **Step 3: Confirm the file landed in the package**

Run: `ls -l dist/IRO_Broadcast_Package/scripts/preflight.py`
Expected: the file exists.

- [ ] **Step 4: Run the packaged copy as a final smoke test**

Run: `python3 dist/IRO_Broadcast_Package/scripts/preflight.py --no-color`
Expected: full report prints; exit code 0 or 1.

- [ ] **Step 5: Commit**

```bash
git add tools/build.py
git commit -m "build: verify preflight.py is shipped in the package"
```

---

## Notes for the executor

- Run the **whole** test file each step (`python3 tests/test_preflight.py`); it runs every `t_*` function and stops at the first failing assert.
- Keep all imports at the top of `preflight.py` even though tasks introduce them incrementally — consolidate into a single import block (`argparse, ctypes, os, re, shutil, socket, subprocess, sys, time` + `from dataclasses import dataclass`).
- Do not add third-party dependencies. Stdlib only.
- If git is not initialized, skip every Commit step (see the git note in the header).
