#!/usr/bin/env python3
"""Pre-flight readiness check for the GT Endurance Racing broadcast setup.

Run before an event to confirm this machine can run OBS + the relay:
hardware, tool chain, ports, and YouTube cookies. Prints a traffic-light
report; exit code is 0 if nothing FAILs, 1 otherwise.

Usage:  python3 scripts/preflight.py
Pure Python 3 standard library — no third-party dependencies.
"""
import argparse
import csv
import ctypes
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import Request, urlopen

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


@dataclass
class Result:
    level: str
    name: str
    detail: str


# --------------------------------------------------------------------------
# Classifiers (pure — raw number -> Result). Single source of truth for the
# system-requirement thresholds.
# --------------------------------------------------------------------------
# Nominal 16/32 GB modules report ~0.1-1.5 GB lower (firmware/iGPU
# reservations) — without slack a physical 32 GB machine could never PASS.
RAM_SLACK_GB = 1.5


def classify_ram(gb):
    if gb < 16 - RAM_SLACK_GB:
        return Result(FAIL, "RAM", f"{gb:.1f} GB — below the 16 GB minimum")
    if gb < 32 - RAM_SLACK_GB:
        return Result(WARN, "RAM",
                      f"{gb:.1f} GB — works; 32 GB recommended "
                      f"(OBS + the relay feeds are memory-heavy)")
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


# --------------------------------------------------------------------------
# Platform readers (isolated per-OS; return raw numbers)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------
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


def no_window_kwargs(os_name=None):
    """Popen/run kwargs that stop a console child from flashing its own terminal
    window on Windows. tool_version() is called IN-PROCESS by the Control Center's
    `tools`/`preflight` status providers, and racecast-ui.exe is a --windowed
    (console-less) app, so every `<tool> --version` probe otherwise pops a
    transient terminal — one per tool (issue #23's class, missed for the version
    probes). CREATE_NO_WINDOW gives the child a hidden console; capture_output
    keeps the version text either way, so the flag is safe. Empty (no-op) off
    Windows so the same call site stays cross-platform. Mirrors
    services.no_window_kwargs — preflight imports nothing from its siblings (its
    test loads it standalone), so the flag is duplicated here, like the relay's
    racecast-feeds._no_window_kwargs copy."""
    os_name = os.name if os_name is None else os_name
    if os_name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def tool_version(name, run=subprocess.run, which=shutil.which):
    """Return the first line of `<name> --version`, or None if not on PATH.
    `run`/`which` are injectable seams for the unit test."""
    path = which(name)
    if not path:
        return None
    try:
        out = run([name, "--version"], capture_output=True,
                  text=True, errors="replace", timeout=10,
                  **no_window_kwargs())
        lines = (out.stdout or out.stderr).strip().splitlines()
        return lines[0] if lines else path
    except Exception:
        return path


# --------------------------------------------------------------------------
# Cookies
# --------------------------------------------------------------------------
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
                      f"not found at {path} — run `racecast cookies firefox` before the event")
    age_h = (now - os.path.getmtime(path)) / 3600
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        text = ""
    has_login = any(marker in text for marker in COOKIE_MARKERS)
    if age_h > max_age_hours:
        return Result(WARN, "cookies.txt",
                      f"{age_h:.0f} h old — cookies rotate; re-run `racecast cookies firefox`")
    if not has_login:
        return Result(WARN, "cookies.txt",
                      "present but no logged-in YouTube session markers found")
    return Result(PASS, "cookies.txt",
                  f"present, fresh ({age_h:.0f} h old), logged-in markers found")


# --------------------------------------------------------------------------
# Google Sheet (the schedule/HUD source — a shared production resource)
# --------------------------------------------------------------------------
SHEET_TAB = "Schedule"   # keep in sync with the relay's DEFAULT_SHEET_TAB


def fetch_sheet_csv(sheet_id, tab=SHEET_TAB, timeout=10):
    """Network probe, kept apart from the pure classifier:
    ("ok", body_text) or ("error", message)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    try:
        req = Request(url, headers={"User-Agent": "racecast-preflight/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return "ok", resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — any network failure is the same FAIL
        return "error", f"{type(exc).__name__}: {exc}"


def classify_sheet(sheet_id, outcome=None, payload=""):
    """Pure classifier over the fetch outcome. An HTML body is Google's
    sign-in page — the classic 'sheet not shared' case."""
    if not sheet_id:
        return Result(WARN, "Google Sheet",
                      "RACECAST_SHEET_ID not set — set SHEET_ID in the active profile")
    if outcome == "error":
        return Result(FAIL, "Google Sheet",
                      f"not readable ({payload}) — check sharing: Share -> "
                      f"'Anyone with the link: Viewer' (or no network)")
    head = (payload or "").lstrip("﻿ \t\r\n")[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        return Result(FAIL, "Google Sheet",
                      "not readable (got a sign-in page) — check sharing: "
                      "Share -> 'Anyone with the link: Viewer'")
    rows = [r for r in csv.reader(io.StringIO(payload)) if any(c.strip() for c in r)]
    if not rows:
        return Result(FAIL, "Google Sheet",
                      f"reachable but tab '{SHEET_TAB}' is empty — correct tab name?")
    return Result(PASS, "Google Sheet",
                  f"reachable ({len(rows)} row(s) in '{SHEET_TAB}')")


# --------------------------------------------------------------------------
# Applications installed? (presence only — `racecast event status` covers running)
# --------------------------------------------------------------------------
# (app key, display name, level when missing, consequence)
APP_CHECKS = (
    ("obs", "OBS Studio", FAIL, "no broadcast without OBS"),
    ("companion", "Companion", WARN, "Stream Deck buttons unavailable"),
    ("tailscale", "Tailscale", WARN, "no remote access for director/tablet"),
    ("discord", "Discord", WARN, "interview audio unavailable"),
)


def _install_apps_module(here):
    """Load sibling install_apps.py by path — works in repo, package and
    frozen bundled-data modes alike (same pattern as install_apps' own
    installer_common loader)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "install_apps", os.path.join(here, "install_apps.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def apps_section(present):
    """Classify each producer app given `present(app) -> bool`."""
    results = []
    for app, pretty, miss_level, consequence in APP_CHECKS:
        if present(app):
            results.append(Result(PASS, pretty, "installed"))
        else:
            results.append(Result(miss_level, pretty,
                                  f"not installed — {consequence}; run `racecast install-apps`"))
    return results


# --------------------------------------------------------------------------
# Reporter / CLI / orchestration
# --------------------------------------------------------------------------
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
    here = os.path.dirname(os.path.abspath(preflight_file))
    try:
        ia = _install_apps_module(here)
        apps = apps_section(lambda app: ia.app_present(app, sys.platform))
    except Exception as exc:  # never let a probe break the report
        apps = [Result(WARN, "applications", f"check failed: {exc}")]
    ports = []
    for port in FEED_PORTS:
        # "In use" is normal once the relay/feeds are running (e.g. after event
        # start) — report it as INFO, not a warning. `racecast status` shows whether
        # the occupant is the relay; only a foreign app is a real conflict.
        ports.append(Result(PASS, f"port {port}", "free") if port_free(port)
                     else Result(INFO, f"port {port}",
                                 "in use — normal if the relay/feeds are running "
                                 "(`racecast status` confirms); a conflict only if another app owns it"))
    for port, svc in SERVICE_PORTS:
        if svc == "OBS WebSocket":
            ports.append(Result(PASS, f"port {port}",
                                "OBS WebSocket reachable — one-button handover ready")
                         if port_reachable("127.0.0.1", port)
                         else Result(WARN, f"port {port}",
                                     "OBS WebSocket not reachable — NEXT can't auto-cut; "
                                     "enable obs-websocket in OBS "
                                     "(Tools -> WebSocket Server Settings)"))
        else:
            # Not reachable just means it hasn't been launched yet (event start does
            # that) — INFO, not a warning the operator must chase down.
            ports.append(Result(PASS, f"port {port}", f"{svc} reachable")
                         if port_reachable("127.0.0.1", port)
                         else Result(INFO, f"port {port}",
                                     f"{svc} not reachable yet — it is launched at event start"))
    cookies = [cookies_status(resolve_cookies_path(preflight_file, runtime_dir, cookies_opt))]
    sheet_id = os.environ.get("RACECAST_SHEET_ID")
    if sheet_id:
        outcome, payload = fetch_sheet_csv(sheet_id)
        sheet = [classify_sheet(sheet_id, outcome, payload)]
    else:
        sheet = [classify_sheet(None)]
    network = [Result(INFO, "bandwidth",
                      "OBS pushes the program to YouTube WHILE the relay pulls up to "
                      "3 live feeds. Use a wired connection with stable upload headroom "
                      "above your OBS bitrate.")]
    return [
        ("Hardware", hardware),
        ("Tool chain", tools),
        ("Applications", apps),
        ("Ports", ports),
        ("YouTube cookies", cookies),
        ("Google Sheet", sheet),
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
        description="Pre-flight readiness check for the GT Endurance Racing broadcast setup.")
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
