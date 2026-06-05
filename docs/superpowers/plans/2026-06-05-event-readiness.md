# Event-Day Readiness Check (`iro event`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `iro event status|start|stop` (event-day readiness report + one-command bring-up/shutdown) and a preflight "Applications" section, per the approved spec `docs/superpowers/specs/2026-06-05-event-readiness-design.md`.

**Architecture:** New pure-logic module `src/scripts/event.py` (process probes, per-OS launch commands, asset checks, classifiers) wired by `src/iro.py` — same split as `companion_common.py`. Reuses `preflight.Result`/`report` for output, `install_apps` path candidates for app detection/launch, `companion_common.detect_tailscale_ip()` for Tailscale, and the Assets-tab parsing from `get-graphics.py`/`get-media.py` (loaded by path, hyphenated filenames). In the frozen binary, `event`/`preflight`/`install_apps` become real frozen modules (hidden-imports), exactly like `services`/`companion_common` today.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest), discovered by `tools/run-tests.py` via the `tests/test_*.py` glob — a new file needs no registration.

**Conventions that apply to every task:**
- Code/docs/comments in **English**. Edit only under `src/`, `tests/`, `tools/`, docs.
- No `.sh`/`.bat`. No secrets/machine paths in committed files.
- Run a test file directly: `python3 tests/test_event.py` → expect `ALL PASS`.

---

### Task 1: `install_apps.app_path_candidates` (shared path table accessor)

`event.launch_command` needs the per-OS install-path candidates that today live inside `app_present`. Extract a public accessor; `app_present` keeps its behavior.

**Files:**
- Modify: `src/scripts/install_apps.py:84-96`
- Test: `tests/test_install_apps.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_apps.py` (before the `if __name__ == "__main__":` block; this file loads the module as `m` via `spec_from_file_location` at the top — check the header, reuse its loader):

```python
def t_app_path_candidates():
    env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86",
           "LOCALAPPDATA": r"C:\LAD"}
    cands = m.app_path_candidates("obs", "win32", env)
    assert r"C:\PF\obs-studio\bin\64bit\obs64.exe" in cands
    assert r"C:\PF86\obs-studio\bin\64bit\obs64.exe" in cands
    assert m.app_path_candidates("discord", "win32", env) == [r"C:\LAD\Discord\Update.exe"]
    assert m.app_path_candidates("obs", "darwin") == ["/Applications/OBS.app"]
    assert m.app_path_candidates("obs", "linux") == []   # PATH fallback only
    assert m.app_path_candidates("bogus", "darwin") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_install_apps.py`
Expected: `AttributeError: module 'install_apps' has no attribute 'app_path_candidates'`

- [ ] **Step 3: Implement**

In `src/scripts/install_apps.py`, replace the existing `app_present` (lines 84–96) with:

```python
def app_path_candidates(app, platform, env=None):
    """Expanded well-known install paths for `app` on `platform` (may be empty —
    Linux mostly relies on the PATH fallback in app_present)."""
    env = os.environ if env is None else env
    if platform.startswith("win"):
        return [_expand_windows(p, env) for p in _WINDOWS_APP_PATHS.get(app, ())]
    if platform == "darwin":
        return list(_DARWIN_APP_PATHS.get(app, ()))
    return list(_LINUX_APP_PATHS.get(app, ()))


def app_present(app, platform, env=None, exists=os.path.exists, which=shutil.which):
    """True iff the app is already installed (well-known paths, then PATH)."""
    for path in app_path_candidates(app, platform, env):
        if not path.startswith("\\") and exists(path):
            return True
    return bool(which(app))  # CLI fallback (e.g. tailscale on PATH)
```

(The `not path.startswith("\\")` guard keeps the existing behavior: an
unexpanded `%VAR%` with an empty env value leaves a leading backslash.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_apps.py`
Expected: `ALL PASS` (all pre-existing `t_*` plus the new one)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_apps.py tests/test_install_apps.py
git commit -m "refactor(install-apps): expose app_path_candidates for reuse"
```

---

### Task 2: `event.py` — module skeleton + process probes

**Files:**
- Create: `src/scripts/event.py`
- Create: `tests/test_event.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the event-day readiness logic (src/scripts/event.py).
Run: python3 tests/test_event.py"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "src", "scripts")
# event.py imports its siblings (preflight, install_apps) as plain modules.
sys.path.insert(0, SCRIPTS)
spec = importlib.util.spec_from_file_location("event", os.path.join(SCRIPTS, "event.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_probe_command_per_platform():
    assert m.probe_command("OBS", "darwin") == ["pgrep", "-x", "OBS"]
    assert m.probe_command("obs", "linux") == ["pgrep", "-x", "obs"]
    assert m.probe_command("obs64.exe", "win32") == \
        ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"]


def t_parse_probe_posix_uses_returncode():
    assert m.parse_probe("darwin", 0, "", "OBS") is True
    assert m.parse_probe("linux", 1, "", "obs") is False


def t_parse_probe_windows_matches_stdout():
    # tasklist exits 0 even when nothing matches — only the output counts.
    assert m.parse_probe("win32", 0, "obs64.exe   1234 Console", "obs64.exe") is True
    assert m.parse_probe("win32", 0, "INFO: No tasks are running...", "obs64.exe") is False
    assert m.parse_probe("win32", 0, "OBS64.EXE 1", "obs64.exe") is True  # case-insensitive
    assert m.parse_probe("win32", 0, None, "obs64.exe") is False


def t_process_names_cover_obs_and_discord():
    for app in ("obs", "discord"):
        for plat in ("darwin", "win32", "linux"):
            assert m._names(app, plat), (app, plat)


def t_app_running_returns_bool():
    # Smoke on the current platform: must not raise, must return a bool.
    assert m.app_running("obs") in (True, False)


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_event.py`
Expected: `FileNotFoundError` (no `src/scripts/event.py` yet)

- [ ] **Step 3: Implement**

Create `src/scripts/event.py`:

```python
"""Event-day readiness logic behind `iro event status|start|stop`.

Pure(-ish) building blocks wired by iro.py — process probes for the GUI apps
(OBS, Discord), per-OS launch commands, asset-completeness checks against the
Sheet's Assets tab, and classifiers turning raw facts into preflight Result
lines. Reuses preflight's Result/report model and install_apps' path
candidates. Spec: docs/superpowers/specs/2026-06-05-event-readiness-design.md.
Tests: tests/test_event.py."""
import csv, io, os, shutil, subprocess, sys

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
    a failing probe counts as not running, never raises)."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): process probes for OBS/Discord (event.py skeleton)"
```

---

### Task 3: `event.py` — per-OS launch commands

**Files:**
- Modify: `src/scripts/event.py`
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event.py` (above the `_raises` helper):

```python
def t_launch_command_darwin():
    assert m.launch_command("obs", "darwin") == (["open", "-a", "OBS"], None)
    assert m.launch_command("discord", "darwin") == (["open", "-a", "Discord"], None)
    assert m.launch_command("tailscale", "darwin") == (["open", "-a", "Tailscale"], None)


def t_launch_command_windows_obs_sets_cwd():
    env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86",
           "LOCALAPPDATA": r"C:\LAD"}
    obs = r"C:\PF\obs-studio\bin\64bit\obs64.exe"
    argv, cwd = m.launch_command("obs", "win32", env, exists=lambda p: p == obs)
    assert argv == [obs]
    assert cwd == r"C:\PF\obs-studio\bin\64bit"   # obs64 needs cwd at its bin dir


def t_launch_command_windows_discord_squirrel():
    env = {"ProgramFiles": "", "ProgramFiles(x86)": "", "LOCALAPPDATA": r"C:\LAD"}
    upd = r"C:\LAD\Discord\Update.exe"
    argv, cwd = m.launch_command("discord", "win32", env, exists=lambda p: p == upd)
    assert argv == [upd, "--processStart", "Discord.exe"]
    assert cwd is None


def t_launch_command_windows_tailscale_gui():
    gui = r"C:\Program Files\Tailscale\tailscale-ipn.exe"
    argv, cwd = m.launch_command("tailscale", "win32", {}, exists=lambda p: p == gui)
    assert argv == [gui] and cwd is None


def t_launch_command_windows_missing_is_none():
    assert m.launch_command("obs", "win32", {}, exists=lambda p: False) is None


def t_launch_command_linux():
    assert m.launch_command("obs", "linux", which=lambda n: "/usr/bin/obs") == \
        (["/usr/bin/obs"], None)
    assert m.launch_command("discord", "linux", which=lambda n: None) is None
    # tailscale on Linux is a daemon — nothing to exec, hint instead.
    assert m.launch_command("tailscale", "linux") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_event.py`
Expected: `AttributeError: module 'event' has no attribute 'launch_command'`

- [ ] **Step 3: Implement**

Append to `src/scripts/event.py`:

```python
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
            return [path], os.path.dirname(path)
        if app == "discord":
            return [path, "--processStart", "Discord.exe"], None
        return [path], None
    if app == "tailscale":
        return None
    exe = which(_LINUX_PATH_NAMES[app])
    return ([exe], None) if exe else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): per-OS launch commands for OBS/Discord/Tailscale"
```

---

### Task 4: `event.py` — asset-completeness helpers

**Files:**
- Modify: `src/scripts/event.py`
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event.py`. The required-* tests load the REAL relay
scripts (integration with their parsing, no fakes):

```python
def _load_relay(name):
    path = os.path.join(ROOT, "src", "relay", name)
    s = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], path)
    mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
    return mod


def t_check_assets():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "Overlay.png"), "w").close()
        assert m.check_assets(["Overlay.png"], d) == []
        assert m.check_assets(["Overlay.png", "Standby.png"], d) == ["Standby.png"]
        assert m.check_assets(["x.png"], os.path.join(d, "absent")) == ["x.png"]
        assert m.local_count(d) == 1
        assert m.local_count(os.path.join(d, "absent")) == 0


def t_required_graphics_from_assets_rows():
    gg = _load_relay("get-graphics.py")
    rows = [["Overlay", "https://drive.google.com/file/d/AAA1/view"],
            ["Intro Video", "https://youtu.be/xyz"],            # non-Drive: skipped
            ["Standby", "https://drive.google.com/file/d/BBB2/view"]]
    assert m.required_graphics(gg, rows) == ["Overlay.png", "Standby.png"]


def t_required_media_from_assets_rows():
    gm = _load_relay("get-media.py")
    rows = [["Intro Video", "https://youtu.be/xyz"]]
    assert m.required_media(gm, rows) == ["intro.mp4"]
    # No media rows in the sheet -> require both (the OBS scenes reference both).
    assert m.required_media(gm, [["Overlay", "u"]]) == ["intro.mp4", "outro.mp4"]


def t_fetch_assets_rows_handles_failure():
    gg = _load_relay("get-graphics.py")
    assert m.fetch_assets_rows(gg, None) is None          # no sheet id
    boom = type("GG", (), {"fetch_assets_csv":
                           staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("net")))})
    assert m.fetch_assets_rows(boom, "SHEET") is None     # fetch failure -> None
    ok = type("GG", (), {"fetch_assets_csv": staticmethod(lambda *a, **k: "A,B\nC,D\n")})
    assert m.fetch_assets_rows(ok, "SHEET") == [["A", "B"], ["C", "D"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_event.py`
Expected: `AttributeError: module 'event' has no attribute 'check_assets'`

- [ ] **Step 3: Implement**

Append to `src/scripts/event.py`:

```python
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


def fetch_assets_rows(gg, sheet_id, timeout=5):
    """Assets-tab CSV rows via get-graphics' fetcher, or None when there is no
    sheet id or the fetch fails (callers fall back to the local-only check)."""
    if not sheet_id:
        return None
    try:
        return list(csv.reader(io.StringIO(gg.fetch_assets_csv(sheet_id, "Assets",
                                                               timeout=timeout))))
    except Exception:
        return None


def required_graphics(gg, rows):
    """Filenames the Assets tab demands (Sheet label IS the filename)."""
    names = (gg.safe_filename(lbl) for lbl in gg.graphics_from_csv(rows))
    return sorted(n for n in names if n)


def required_media(gm, rows):
    """intro.mp4/outro.mp4 for each media row found in the Assets tab; both
    when the sheet defines none (the OBS Intro/Outro scenes reference both)."""
    keys = sorted(gm.media_urls_from_csv(rows)) or ["intro", "outro"]
    return [f"{k}.mp4" for k in keys]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): asset-completeness helpers (sheet compare + local fallback)"
```

---

### Task 5: `event.py` — readiness classifiers + go-live reminder

**Files:**
- Modify: `src/scripts/event.py`
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event.py`:

```python
def t_classify_app_levels():
    assert m.classify_app("obs", True).level == "PASS"
    r = m.classify_app("obs", False)
    assert r.level == "FAIL" and r.name == "OBS"
    r = m.classify_app("discord", False)
    assert r.level == "WARN" and "interview audio" in r.detail


def t_classify_tailscale():
    assert m.classify_tailscale("100.64.1.2").level == "PASS"
    assert "100.64.1.2" in m.classify_tailscale("100.64.1.2").detail
    assert m.classify_tailscale(None).level == "WARN"


def t_classify_relay():
    assert m.classify_relay(True, True).level == "PASS"
    r = m.classify_relay(True, False)
    assert r.level == "FAIL" and "8088" in r.detail   # alive but port dead
    r = m.classify_relay(False, False)
    assert r.level == "FAIL" and "iro relay start" in r.detail


def t_classify_companion():
    assert m.classify_companion(True, True).level == "PASS"
    r = m.classify_companion(False, True)
    assert r.level == "WARN" and "iro companion start" in r.detail
    r = m.classify_companion(False, False, "manual on linux")
    assert r.level == "WARN" and "manual on linux" in r.detail


def t_classify_assets():
    # sheet readable, complete
    assert m.classify_assets("Graphics", [], 9, "FAIL", "run `iro graphics`").level == "PASS"
    # sheet readable, files missing -> severity, names listed
    r = m.classify_assets("Graphics", ["Standby.png"], 8, "FAIL", "run `iro graphics`")
    assert r.level == "FAIL" and "Standby.png" in r.detail and "iro graphics" in r.detail
    r = m.classify_assets("Media", ["outro.mp4"], 1, "WARN", "run `iro media`")
    assert r.level == "WARN"
    # sheet unreachable (missing=None) -> local fallback
    r = m.classify_assets("Graphics", None, 9, "FAIL", "run `iro graphics`")
    assert r.level == "WARN" and "not verified" in r.detail
    r = m.classify_assets("Graphics", None, 0, "FAIL", "run `iro graphics`")
    assert r.level == "FAIL"      # nothing local at all


def t_classify_env():
    assert m.classify_env("sheet", "http://t").level == "PASS"
    r = m.classify_env(None, "http://t")
    assert r.level == "FAIL" and "IRO_SHEET_ID" in r.detail
    r = m.classify_env("", "")
    assert "IRO_SHEET_ID" in r.detail and "IRO_TIMER_URL" in r.detail


def t_go_live_reminder():
    assert m.GO_LIVE_REMINDER.level == "INFO"
    assert "refresh" in m.GO_LIVE_REMINDER.detail.lower()
    assert "HUD" in m.GO_LIVE_REMINDER.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_event.py`
Expected: `AttributeError: module 'event' has no attribute 'classify_app'`

- [ ] **Step 3: Implement**

Append to `src/scripts/event.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): readiness classifiers and go-live HUD reminder"
```

---

### Task 6: preflight "Applications" section

**Files:**
- Modify: `src/scripts/preflight.py` (new section between "Tool chain" and "Ports" in `gather()`, helpers above the reporter block)
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_preflight.py` (this file loads preflight as `m` via
`spec_from_file_location`; `ROOT` is defined in its header):

```python
def t_apps_section_levels():
    rs = m.apps_section(lambda app: True)
    assert [r.level for r in rs] == ["PASS"] * 4
    rs = m.apps_section(lambda app: False)
    by = {r.name: r for r in rs}
    assert by["OBS Studio"].level == "FAIL"          # no broadcast without OBS
    assert by["Companion"].level == "WARN"
    assert by["Tailscale"].level == "WARN"
    assert by["Discord"].level == "WARN"
    assert "iro install-apps" in by["Discord"].detail


def t_install_apps_module_loads():
    ia = m._install_apps_module(os.path.join(ROOT, "src", "scripts"))
    assert callable(ia.app_present)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_preflight.py`
Expected: `AttributeError: module 'preflight' has no attribute 'apps_section'`

- [ ] **Step 3: Implement**

In `src/scripts/preflight.py`, insert after the Cookies block (after
`cookies_status`, before the "Reporter / CLI / orchestration" comment):

```python
# --------------------------------------------------------------------------
# Applications installed? (presence only — `iro event status` covers running)
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
                                  f"not installed — {consequence}; run `iro install-apps`"))
    return results
```

Then in `gather()` (currently `preflight.py:260-297`): add the section. After
the `tools` block and before `ports`, insert:

```python
    here = os.path.dirname(os.path.abspath(preflight_file))
    try:
        ia = _install_apps_module(here)
        apps = apps_section(lambda app: ia.app_present(app, sys.platform))
    except Exception as exc:  # never let a probe break the report
        apps = [Result(WARN, "applications", f"check failed: {exc}")]
```

and extend the returned list:

```python
    return [
        ("Hardware", hardware),
        ("Tool chain", tools),
        ("Applications", apps),
        ("Ports", ports),
        ("YouTube cookies", cookies),
        ("Network", network),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_preflight.py`
Expected: `ALL PASS`

- [ ] **Step 5: Sanity-run the real report**

Run: `python3 src/iro.py preflight`
Expected: a new "Applications" section listing OBS Studio / Companion /
Tailscale / Discord (PASS on this machine — all four are installed). Exit
code may be non-zero from unrelated WARN/FAILs; only the section presence
matters here.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): Applications section — are the producer apps installed"
```

---

### Task 7: `iro.py` routing for `iro event`

**Files:**
- Modify: `src/iro.py` (route(), constants)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iro.py` (above `_raises`):

```python
def t_event_routes():
    assert m.route(["event", "status"]) == \
        {"kind": "service", "command": "event", "verb": "status", "rest": []}
    assert m.route(["event", "start"])["verb"] == "start"
    assert m.route(["event", "stop"])["verb"] == "stop"
    assert m.route(["event", "status", "--no-color"])["rest"] == ["--no-color"]
    _raises(lambda: m.route(["event"]))
    _raises(lambda: m.route(["event", "restart"]))   # no restart/logs for event
    _raises(lambda: m.route(["event", "logs"]))


def t_event_dispatch_wired():
    for verb in ("status", "start", "stop"):
        assert ("event", verb) in m.DISPATCH
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: `AssertionError` in `t_event_routes` (route raises "unknown command: event")

- [ ] **Step 3: Implement routing**

In `src/iro.py`, below the `ONESHOTS` constant (line ~241), add:

```python
EVENT_VERBS = ("status", "start", "stop")
```

In `route()`, before the `if cmd in ONESHOTS:` line, add:

```python
    if cmd == "event":
        verb = rest[0] if rest else None
        if verb not in EVENT_VERBS:
            raise ValueError(f"usage: iro event {{{'|'.join(EVENT_VERBS)}}}")
        return {"kind": "service", "command": "event", "verb": verb, "rest": rest[1:]}
```

(Reusing `kind: "service"` means `main()` needs no change — dispatch goes
through the existing `DISPATCH` lookup.)

Add placeholder dispatch entries at the end of the `DISPATCH` dict (real
functions arrive in Task 8 — define minimal stubs ABOVE the dict so the
module imports):

```python
def event_status(rest):
    raise SystemExit("iro: event status not implemented yet")

def event_start(rest):
    raise SystemExit("iro: event start not implemented yet")

def event_stop(rest):
    raise SystemExit("iro: event stop not implemented yet")
```

and in `DISPATCH`:

```python
    ("event", "status"): event_status, ("event", "start"): event_start,
    ("event", "stop"): event_stop,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): route iro event status|start|stop"
```

---

### Task 8: `iro.py` wiring — event status / start / stop

**Files:**
- Modify: `src/iro.py` (replace the Task-7 stubs; extend the module docstring)

- [ ] **Step 1: Replace the three stubs with the real implementation**

Replace the Task-7 stub functions in `src/iro.py` with the block below
(placed after `companion_open_admin`, before `DISPATCH`). Also refactor
`_relay_extra` to use the new `_relay_http_ok` so the probe isn't duplicated:

```python
def _relay_http_ok():
    """True iff the relay control server answers on localhost."""
    try:
        import urllib.request
        # .read() drains the socket; we only care whether the request succeeds
        urllib.request.urlopen(f"http://127.0.0.1:{RELAY_PORT}/status", timeout=3).read()
        return True
    except Exception:
        return False


def _event_modules():
    """event/preflight are plain sibling modules of services (scripts/ is on
    sys.path; frozen: hidden-imports in tools/build-binary.py)."""
    import event as ev
    import preflight as pf
    return ev, pf


def _load_relay_module(rel):
    """Load a relay script (hyphenated filename) as a module, repo + package +
    frozen alike — module-level code only defines functions, no side effects."""
    import importlib.util
    path = resource_path(rel)
    name = os.path.splitext(os.path.basename(path))[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _asset_dirs(gg, gm):
    """Where `iro graphics`/`iro media` put files in THIS run mode. Frozen:
    the oneshot injection redirects to runtime/ (see _oneshot_extra); repo and
    package follow the scripts' own defaults (runtime/ vs. package root)."""
    if IS_FROZEN:
        return (os.path.join(_runtime_dir(), "graphics"),
                os.path.join(_runtime_dir(), "media"))
    return (gg.graphics_dir(os.path.dirname(os.path.abspath(gg.__file__))),
            gm.media_dir(os.path.dirname(os.path.abspath(gm.__file__))))


def _event_sections(ev, pf):
    """Gather all event-day facts and classify them into report sections."""
    # Apps
    apps = [ev.classify_app("obs", ev.app_running("obs")),
            ev.classify_app("discord", ev.app_running("discord")),
            ev.classify_tailscale(_tailscale_ip())]
    # Services
    pid = sv.read_pid(_relay_pid_path())
    alive = sv.pid_alive(pid)
    cc = _companion()
    supported = _companion_cmds(cc) is not None
    services = [ev.classify_relay(alive, _relay_http_ok() if alive else False, RELAY_PORT),
                ev.classify_companion(_companion_running(cc) if supported else False,
                                      supported,
                                      "" if supported else _companion_unsupported_msg())]
    # Assets — get-graphics' load_dotenv also fills IRO_* for the repo/package
    # modes (frozen already loaded .env next to the binary at startup). A
    # broken probe must never traceback the report (spec: error behaviour).
    assets = [pf.cookies_status(os.path.join(_runtime_dir(), "cookies.txt"))]
    try:
        gg = _load_relay_module("relay/get-graphics.py")
        gm = _load_relay_module("relay/get-media.py")
        gg.load_dotenv(os.path.dirname(os.path.abspath(gg.__file__)))
        g_dir, m_dir = _asset_dirs(gg, gm)
        rows = ev.fetch_assets_rows(gg, os.environ.get("IRO_SHEET_ID"))
        missing_g = ev.check_assets(ev.required_graphics(gg, rows), g_dir) if rows else None
        missing_m = ev.check_assets(ev.required_media(gm, rows), m_dir) if rows else None
        assets += [ev.classify_assets("Graphics", missing_g, ev.local_count(g_dir),
                                      ev.FAIL, "run `iro graphics`"),
                   ev.classify_assets("Media", missing_m, ev.local_count(m_dir),
                                      ev.WARN, "run `iro media`")]
    except Exception as exc:
        assets.append(ev.Result(ev.WARN, "Graphics/Media", f"check failed: {exc}"))
    config = [ev.classify_env(os.environ.get("IRO_SHEET_ID"),
                              os.environ.get("IRO_TIMER_URL"))]
    return [("Apps", apps), ("Services", services), ("Assets", assets),
            ("Config", config), ("Go-live reminders", [ev.GO_LIVE_REMINDER])]


def event_status(rest):
    ev, pf = _event_modules()
    color = pf.enable_color("--no-color" in rest)
    raise SystemExit(pf.report(_event_sections(ev, pf), color))


def _event_launch(ev, app):
    """Best-effort GUI-app launch: report and continue on every failure path."""
    import install_apps
    if not install_apps.app_present(app, sys.platform):
        print(f"{app}: not installed — run `iro install-apps`.")
        return
    cmd = ev.launch_command(app, sys.platform)
    if cmd is None:
        hint = ("run `sudo tailscale up`" if app == "tailscale"
                else "launch it manually")
        print(f"{app}: cannot launch automatically — {hint}.")
        return
    argv, cwd = cmd
    print(f"{app}: launching…")
    try:
        subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
    except OSError as exc:
        print(f"{app}: launch failed ({exc}).")


def event_start(rest):
    """Bring the event stack up. Order matters: Tailscale first (the Companion
    bind needs its IP), relay before OBS (the HUD browser source then connects
    against a live relay on OBS's first load). Every step is best effort."""
    ev, pf = _event_modules()
    # 1. Tailscale
    if _tailscale_ip():
        print("tailscale: already connected.")
    else:
        _event_launch(ev, "tailscale")
        for _ in range(20):  # ~10 s for the tailnet to come up
            if _tailscale_ip():
                break
            time.sleep(0.5)
        if _tailscale_ip():
            print("tailscale: connected.")
        else:
            print("tailscale: no tailnet IP yet — sign in to Tailscale; "
                  "continuing local-only (OBS keeps working).")
    # 2. Discord
    if ev.app_running("discord"):
        print("discord: already running.")
    else:
        _event_launch(ev, "discord")
    # 3. Relay (before OBS — see docstring)
    relay_start([])
    # 4. OBS
    if ev.app_running("obs"):
        print("obs: already running.")
    else:
        _event_launch(ev, "obs")
    # 5. Companion (companion_start sys.exits on unsupported setups — keep going)
    try:
        companion_start(["auto"])
    except SystemExit as exc:
        print(exc.code if isinstance(exc.code, str)
              else f"companion: start failed (exit {exc.code}).")
    print("\nEvent readiness:")
    event_status(rest)  # exit code: 0 = ready, 1 = FAILs remain


def event_stop(rest):
    """Stop iro-managed services only — never the GUI apps (a mistyped command
    must not be able to kill a live broadcast)."""
    relay_stop([])
    try:
        companion_stop([])
    except SystemExit as exc:
        print(exc.code if isinstance(exc.code, str)
              else f"companion: stop failed (exit {exc.code}).")
    if glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")):
        streams_stop([])
    print("OBS/Discord/Tailscale keep running — quit them manually if needed.")
```

Also update `_relay_extra` (line ~278) to drop its duplicated probe:

```python
def _relay_extra():
    parts = []
    if _relay_http_ok():
        parts.append(f"control http://127.0.0.1:{RELAY_PORT}/status OK")
    else:
        parts.append(f"(port {RELAY_PORT} not responding)")
    ts = _tailscale_ip()
    if ts:
        parts.append(f"tablet/panel http://{ts}:{RELAY_PORT}/panel")
    return "  ".join(parts)
```

- [ ] **Step 2: Extend the module docstring (USAGE)**

In the `src/iro.py` docstring, after the `iro streams …` line, add:

```
  iro event     status|start|stop      # event-day readiness: check / bring-up / wind-down
```

- [ ] **Step 3: Run the routing + module tests**

Run: `python3 tests/test_iro.py && python3 tests/test_event.py && python3 tests/test_preflight.py`
Expected: `ALL PASS` three times (the stubs are gone; DISPATCH still wired)

- [ ] **Step 4: Manual smoke on this machine**

Run: `python3 src/iro.py event status`
Expected: a five-section report (Apps / Services / Assets / Config /
Go-live reminders) ending with the HUD-refresh INFO line and a summary.
Exit code 1 is EXPECTED when OBS/relay are not running — verify with
`echo $?` that it is 0 or 1, never a traceback.

Run: `python3 src/iro.py event stop`
Expected: "relay is not running." / "companion is not running." (or actual
stops), then the closing "OBS/Discord/Tailscale keep running" line.

Do NOT run `event start` blind on this machine if an OBS session with unsaved
work is open — it launches apps. Run it once deliberately and confirm the
order of the printed steps (tailscale → discord → relay → obs → companion)
and the closing status.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py
git commit -m "feat(iro): event status/start/stop — event-day readiness and bring-up"
```

---

### Task 9: frozen binary — hidden imports + smoke

**Files:**
- Modify: `tools/build-binary.py:62-64` (hidden imports), `tools/build-binary.py:88+` (smoke)

- [ ] **Step 1: Add the frozen modules**

In `tools/build-binary.py`, extend the hidden-import line (currently
`--hidden-import services --hidden-import companion_common`):

```python
           # services/companion_common/event (+ its imports preflight,
           # install_apps) are real frozen modules (iro.py imports them)
           "--paths", os.path.join(SRC, "scripts"),
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "install_apps",
```

- [ ] **Step 2: Extend the smoke test**

In `smoke()` (after the `status` check), add — `event status` exercises the
frozen `event`/`preflight`/`install_apps` imports plus the bundled relay
scripts, and legitimately exits 1 when nothing is running:

```python
    ev = run(["event", "status"])
    if ev.returncode not in (0, 1) or "Go-live" not in ev.stdout:
        sys.exit(f"smoke event status FAILED: rc={ev.returncode} "
                 f"out={ev.stdout!r} err={ev.stderr!r}")
```

- [ ] **Step 3: Verify locally (only if PyInstaller is installed; CI covers all OSes on tags)**

Run: `python3 tools/build-binary.py 2>/dev/null || echo "pyinstaller not installed — CI will cover this"`
Expected: either a successful build + smoke (including the new event-status
probe), or the fallback message.

- [ ] **Step 4: Commit**

```bash
git add tools/build-binary.py
git commit -m "build(binary): freeze event/preflight/install_apps; smoke event status"
```

---

### Task 10: docs — README, CLAUDE.md, wiki

**Files:**
- Modify: `README.md` ("Run it" section, line ~57)
- Modify: `CLAUDE.md` (Commands block)
- Modify: `src/docs/wiki/Run-an-event.md`

- [ ] **Step 1: README "Run it" section**

In `README.md`, at the top of the `## Run it` code block, add:

```
iro event start          # bring everything up: Tailscale, Discord, relay, OBS, Companion
iro event status         # event-day readiness report (apps, services, cookies, graphics, media)
iro event stop           # stop relay/Companion/streams — OBS & friends keep running
```

- [ ] **Step 2: CLAUDE.md command block**

In `CLAUDE.md`, in the "Unified operator CLI" command block (after the
`iro status` line), add:

```bash
python3 src/iro.py event status      # event-day readiness report (apps + services + assets)
python3 src/iro.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion)
python3 src/iro.py event stop        # stop iro services; GUI apps keep running
```

And in the tests list (after `tests/test_streams.py`), add:

```bash
python3 tests/test_event.py          # event readiness helpers (probes/launch/assets)
```

- [ ] **Step 3: Wiki page**

Read `src/docs/wiki/Run-an-event.md` first. Insert a short section near the
top of the event-day flow (adapt heading level to the page):

```markdown
## One-command bring-up

On the event day, start everything with:

    iro event start

This launches Tailscale, Discord, the relay, OBS and Companion (in that
order) and ends with a readiness report. Re-check any time with
`iro event status` — it verifies the apps and services are running and that
cookies, graphics and the intro/outro clips are present, and names the exact
fix command for anything missing.

> **Before going LIVE:** refresh the HUD overlay browser source in OBS once
> (right-click the source → Refresh) — its auto-refresh is not fully
> reliable.

After the broadcast, `iro event stop` stops the relay and Companion; OBS,
Discord and Tailscale stay running.
```

Adjust the page's existing step list so it references `iro event start`
instead of (or before) the individual `iro relay start` / `iro companion
start` steps, keeping the individual commands documented as the granular
alternative.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md src/docs/wiki/Run-an-event.md
git commit -m "docs: document iro event status/start/stop (README, CLAUDE.md, wiki)"
```

(Do NOT run `tools/sync-wiki.py` here — publishing the wiki is a separate,
outward-facing maintainer step; see Final verification.)

---

### Task 11: final verification

- [ ] **Step 1: Full test suite**

Run: `python3 tools/run-tests.py`
Expected: every `tests/test_*.py` listed (including the new
`test_event.py`), final line `ALL TEST FILES PASS`.

- [ ] **Step 2: Package build + verify**

Run: `python3 tools/build.py`
Expected: build completes; the verify step (tokenization, blanked password,
no secrets, preflight present, no shell scripts) passes. `event.py` ships
automatically (`scripts/` is copied wholesale).

- [ ] **Step 3: End-to-end status check**

Run: `python3 src/iro.py event status; echo "exit: $?"`
Expected: full report; exit 0 or 1 (no traceback). Spot-check that the
Graphics line reflects reality (this machine has `runtime/graphics/`
populated and `.env` filled, so with network it should compare against the
sheet and PASS, or list genuinely missing files).

- [ ] **Step 4: Commit any stragglers, then summarize**

```bash
git status   # should be clean except dist/ (gitignored)
```

Report results to the user. Remaining MANUAL/maintainer follow-ups (ask the
user — both are outward-facing):
1. `python3 tools/sync-wiki.py` to publish the updated Run-an-event wiki page.
2. Merge/release flow (release-please) when this lands on main.

---

## Spec deviations (agreed rationale, fold back if challenged)

- **Windows Tailscale launch** uses `tailscale-ipn.exe` (the tray/GUI app),
  not `tailscale.exe` (the CLI — exec'ing it bare does nothing). Presence
  detection still uses `tailscale.exe` via `install_apps`.
- **Go-live reminder** is implemented as a fifth report section
  ("Go-live reminders") so it reuses the section reporter unchanged.
