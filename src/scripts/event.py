"""Event-day readiness logic behind `iro event status|start|stop`.

Pure(-ish) building blocks wired by iro.py — process probes for the GUI apps
(OBS, Discord), per-OS launch commands, asset-completeness checks against the
Sheet's Assets tab, and classifiers turning raw facts into preflight Result
lines. Reuses preflight's Result/report model and install_apps' path
candidates. Spec: docs/superpowers/specs/2026-06-05-event-readiness-design.md.
Tests: tests/test_event.py."""
import csv, io, ntpath, os, shutil, subprocess, sys, time

# Plain sibling imports: scripts/ is on sys.path in repo+package mode (iro.py
# injects it; standalone tests insert it), and the frozen binary ships these
# as real frozen modules (hidden-imports in tools/build-binary.py).
import install_apps
import preflight

PASS, WARN, FAIL, INFO = preflight.PASS, preflight.WARN, preflight.FAIL, preflight.INFO
Result = preflight.Result

# Process image names per app/OS for the running probe. Tailscale is probed
# via detect_tailscale_ip() (connected beats running) and Companion via the
# existing iro.py probe — only the plain GUI apps live here.
PROCESS_NAMES = {
    "obs": {"darwin": ("OBS",), "win": ("obs64.exe",), "linux": ("obs",)},
    "discord": {"darwin": ("Discord",), "win": ("Discord.exe",), "linux": ("Discord",)},
}


def _names(app, platform):
    table = PROCESS_NAMES[app]
    if platform.startswith("win"):
        return table["win"]
    return table["darwin"] if platform == "darwin" else table["linux"]


def probe_command(name, platform):
    """argv that probes whether a process image named `name` is running."""
    if platform.startswith("win"):
        return ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"]
    return ["pgrep", "-x", name]


def parse_probe(platform, returncode, stdout, name):
    """Interpret a probe_command() run. Windows tasklist exits 0 even with no
    match — the image name must appear in the output (decode with
    errors='replace'; the names we match are pure ASCII, same OEM-codepage
    caveat as iro.py's _companion_running)."""
    if platform.startswith("win"):
        return name.lower() in (stdout or "").lower()
    return returncode == 0


def app_running(app, platform=None):
    """True iff one of the app's process names is running (best effort —
    a failing probe counts as not running, never raises for known app keys)."""
    platform = sys.platform if platform is None else platform
    for name in _names(app, platform):
        try:
            out = subprocess.run(probe_command(name, platform), capture_output=True,
                                 text=True, errors="replace", timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if parse_probe(platform, out.returncode, out.stdout, name):
            return True
    return False


def wait_until_up(probes, timeout=60, interval=5, clock=time.monotonic,
                  sleep=time.sleep):
    """Poll `probes` ({name: callable -> bool}) until all pass or `timeout`
    seconds elapse; returns {name: bool} with the final state. A probe that
    turned True stays True (no re-poll). Used by `iro event start` so the
    closing readiness report does not race the just-launched services —
    static problems (missing graphics, stale cookies) are deliberately NOT
    waited on; they never self-heal."""
    deadline = clock() + timeout
    status = {name: False for name in probes}
    while True:
        for name, probe in probes.items():
            if not status[name]:
                status[name] = bool(probe())
        if all(status.values()) or clock() >= deadline:
            return status
        sleep(interval)


# macOS app names for `open -a` (callers gate on install_apps.app_present
# first — `open -a` on a missing app would error).
_DARWIN_OPEN_NAMES = {"obs": "OBS", "discord": "Discord", "tailscale": "Tailscale"}
# Windows: the Tailscale tray/GUI app. install_apps probes tailscale.exe (the
# CLI) for PRESENCE, but exec'ing the CLI bare does nothing — launch the GUI.
_WIN_TAILSCALE_GUI = (r"C:\Program Files\Tailscale\tailscale-ipn.exe",)
_LINUX_PATH_NAMES = {"obs": "obs", "discord": "discord"}


def launch_command(app, platform, env=None, exists=os.path.exists, which=shutil.which):
    """(argv, cwd) that launches `app` on `platform`, or None when there is
    nothing to exec (binary not found, or Linux tailscale — a daemon: the hint
    is `sudo tailscale up`). Windows obs64.exe must run with cwd at its bin
    directory or it cannot find its bundled resources."""
    env = os.environ if env is None else env
    if platform == "darwin":
        return ["open", "-a", _DARWIN_OPEN_NAMES[app]], None
    if platform.startswith("win"):
        cands = (_WIN_TAILSCALE_GUI if app == "tailscale"
                 else install_apps.app_path_candidates(app, platform, env))
        path = next((p for p in cands if p and not p.startswith("\\") and exists(p)), None)
        if path is None:
            return None
        if app == "obs":
            return [path], ntpath.dirname(path)
        if app == "discord":
            return [path, "--processStart", "Discord.exe"], None
        return [path], None
    if app == "tailscale":
        return None
    name = _LINUX_PATH_NAMES.get(app)
    if not name:
        return None
    exe = which(name)
    return ([exe], None) if exe else None


def check_assets(required_files, directory):
    """Sorted names from `required_files` missing in `directory` (an absent or
    unreadable directory misses everything)."""
    try:
        have = set(os.listdir(directory))
    except OSError:
        have = set()
    return sorted(f for f in required_files if f not in have)


def local_count(directory):
    """Number of entries in `directory` (0 when absent/unreadable)."""
    try:
        return len(os.listdir(directory))
    except OSError:
        return 0


def fetch_assets_rows(gg, sheet_id, timeout=5, tab="Assets"):
    """Assets-tab CSV rows via get-graphics' fetcher, or None when there is no
    sheet id or the fetch fails (callers fall back to the local-only check)."""
    if not sheet_id:
        return None
    try:
        return list(csv.reader(io.StringIO(gg.fetch_assets_csv(sheet_id, tab,
                                                               timeout=timeout))))
    except Exception:
        return None


def required_graphics(gg, rows):
    """Filenames the Assets tab demands (Sheet label IS the filename).
    `rows` may be None/empty -> []."""
    if not rows:
        return []
    names = (gg.safe_filename(lbl) for lbl in gg.graphics_from_csv(rows))
    return sorted(n for n in names if n)


def required_media(gm, rows):
    """intro.mp4/outro.mp4 for each media row found in the Assets tab; both
    when the sheet defines none or is unreadable (the OBS Intro/Outro scenes
    reference both)."""
    if rows is None:
        return ["intro.mp4", "outro.mp4"]
    keys = sorted(gm.media_urls_from_csv(rows)) or ["intro", "outro"]
    return [f"{k}.mp4" for k in keys]


def classify_app(app, running):
    """OBS is broadcast-critical (FAIL); Discord only carries interview audio."""
    if app == "obs":
        return (Result(PASS, "OBS", "running") if running else
                Result(FAIL, "OBS", "not running — launch OBS (or `iro event start`)"))
    return (Result(PASS, "Discord", "running") if running else
            Result(WARN, "Discord", "not running — interview audio unavailable; launch Discord"))


def classify_tailscale(ip):
    if ip:
        return Result(PASS, "Tailscale", f"connected ({ip})")
    return Result(WARN, "Tailscale",
                  "no tailnet IP — remote panel/tablet unreachable; sign in to Tailscale")


def classify_relay(alive, http_ok, port=8088):
    if alive and http_ok:
        return Result(PASS, "Relay", f"running — control http://127.0.0.1:{port}/status OK")
    if alive:
        return Result(FAIL, "Relay",
                      f"process alive but port {port} not responding — check `iro relay logs`")
    return Result(FAIL, "Relay", "not running — `iro relay start` (or `iro event start`)")


def classify_companion(running, supported, unsupported_detail=""):
    """Companion is WARN-level: the broadcast works without the buttons."""
    if not supported:
        return Result(WARN, "Companion",
                      unsupported_detail or "no automated probe on this OS — check manually")
    if running:
        return Result(PASS, "Companion", "running")
    return Result(WARN, "Companion", "not running — `iro companion start`")


def classify_assets(label, missing, count, severity, fix):
    """`missing` is the check_assets() list when the sheet was readable, or
    None when only the local fallback could run. `severity` is the not-OK
    level for this asset kind (Graphics: FAIL — a missing file is a black
    source in OBS; Media: WARN)."""
    if missing is None:
        if count:
            return Result(WARN, label,
                          f"sheet unreachable — {count} local file(s) present, "
                          f"completeness not verified")
        return Result(severity, label, f"none present — {fix}")
    if missing:
        return Result(severity, label, f"missing: {', '.join(missing)} — {fix}")
    return Result(PASS, label, f"complete ({count} file(s))")


def classify_env(sheet_id, timer_url):
    missing = [name for name, val in
               (("IRO_SHEET_ID", sheet_id), ("IRO_TIMER_URL", timer_url)) if not val]
    if missing:
        return Result(FAIL, ".env", "missing: " + ", ".join(missing) +
                      " — fill them in (.env next to the binary / repo root)")
    return Result(PASS, ".env", "IRO_SHEET_ID and IRO_TIMER_URL set")


GO_LIVE_REMINDER = Result(
    INFO, "HUD overlay",
    "Before going LIVE: refresh the HUD overlay browser source in OBS once "
    "(right-click the source -> Refresh) — its auto-refresh is not fully reliable.")
