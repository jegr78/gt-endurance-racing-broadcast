# IRO Native Binary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the unified `iro` CLI as a standalone PyInstaller binary for Windows (primary), macOS, and Linux — producers need no Python — while keeping the repo mode (`python3 src/iro.py`) fully working.

**Architecture:** The whole `src/` tree ships as PyInstaller data under `sys._MEIPASS/src/`, so the scripts' existing here-relative path resolution keeps working unchanged. In frozen mode, `iro.py` runs the bundled scripts **in-process** (importlib + patched `sys.argv`) and background daemons **re-invoke the binary itself** (`iro relay run`, hidden `iro streams run-feed`). `services.py` and `companion_common.py` get real Windows code paths (the current `os.kill(pid, 0)` probe would *kill* the process on Windows). GitHub Actions builds, tests, smoke-tests and releases the three binaries on `v*` tags.

**Tech Stack:** Python stdlib only in shipped code (project rule); PyInstaller as a maintainer/CI build tool; GitHub Actions (`windows-latest`, `macos-latest`, `ubuntu-latest`).

**Spec:** `docs/superpowers/specs/2026-06-04-iro-native-binary-design.md` — read it first.

**Project test convention:** no pytest. Each `tests/test_*.py` is a runnable script with `t_*` functions and prints `ALL PASS`. Run as `python3 tests/test_iro.py`. All code/docs/comments in English.

**File map (whole plan):**

| File | Change |
|---|---|
| `src/iro.py` | frozen helpers, in-process runner, new verbs (`install-tools`, `export companion`, `--version`, hidden `streams run-feed`) |
| `src/scripts/services.py` | Windows-safe pid probe / spawn flags / taskkill stop |
| `src/scripts/companion_common.py` | Windows + Linux adapter, exe discovery, running-output parser |
| `src/scripts/start-streams.py`, `stop-streams.py` | `--state-dir` flag; frozen-aware feed spawn |
| `src/scripts/install_tools.py` | **new** — winget/brew/apt installer for yt-dlp/streamlink/ffmpeg/deno |
| `tests/test_iro.py`, `tests/test_services.py`, `tests/test_companion.py` | extended |
| `tests/test_streams.py`, `tests/test_install_tools.py` | **new** |
| `tools/build-binary.py`, `tools/run-tests.py` | **new** maintainer tools (not shipped) |
| `.github/workflows/ci.yml`, `.github/workflows/release.yml` | **new** |
| `tools/build.py`, `CLAUDE.md`, `README.md` | ship-checks + docs |

---

### Task 1: Frozen-mode helpers in `src/iro.py`

PyInstaller sets `sys.frozen = True` and unpacks bundled data to `sys._MEIPASS`. Add pure, parameterized helpers (the project's testing seam style — see `route()`); thin wrappers read the real `sys` state.

**Files:**
- Modify: `src/iro.py` (around lines 22–37: `_runtime_dir`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_iro.py` (before `_raises`):

```python
def t_src_base_modes():
    assert m._src_base(False, "", os.path.join("repo", "src")) == os.path.join("repo", "src")
    assert m._src_base(True, os.path.join("tmp", "_MEI1"), "x") == \
        os.path.join("tmp", "_MEI1", "src")


def t_runtime_base_modes():
    assert m._runtime_base(False, "python3", os.path.join("repo", "src")) == \
        os.path.join("repo", "runtime")
    assert m._runtime_base(False, "python3", "pkg") == os.path.join("pkg", "runtime")
    assert m._runtime_base(True, os.path.join("apps", "iro"), "ignored") == \
        os.path.join("apps", "runtime")


def t_parse_env_text():
    text = "# comment\nIRO_SHEET_ID=abc\nIRO_TIMER_URL='http://x'\n\nnot a pair\n"
    assert m.parse_env_text(text) == {"IRO_SHEET_ID": "abc", "IRO_TIMER_URL": "http://x"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_iro.py`
Expected: `AttributeError: module 'iro' has no attribute '_src_base'` (or similar)

- [ ] **Step 3: Implement in `src/iro.py`** — replace the current `_runtime_dir()` (lines 22–26) with:

```python
# PyInstaller marks the frozen binary with sys.frozen and unpacks bundled data
# (the whole src/ tree) to sys._MEIPASS. Repo + package mode stay subprocess-based.
IS_FROZEN = bool(getattr(sys, "frozen", False))

def _src_base(frozen, meipass, here):
    """Root of the source tree: bundled data dir when frozen, else this dir."""
    return os.path.join(meipass, "src") if frozen else here

def resource_path(rel):
    """Absolute path of a bundled/checked-out source file, e.g. 'obs/hud.html'."""
    return os.path.join(_src_base(IS_FROZEN, getattr(sys, "_MEIPASS", ""), HERE), rel)

def _runtime_base(frozen, executable, here):
    """Machine-local state dir. Frozen: next to the binary (document: keep the
    binary in its own folder). Repo (src/) -> <repo>/runtime ; package -> <pkg>/runtime."""
    if frozen:
        return os.path.join(os.path.dirname(executable), "runtime")
    if os.path.basename(here) == "src":
        return os.path.join(os.path.dirname(here), "runtime")
    return os.path.join(here, "runtime")

def _runtime_dir():
    return _runtime_base(IS_FROZEN, sys.executable, HERE)

def parse_env_text(text):
    """Minimal .env parser (KEY=VALUE, '#' comments, optional quotes) — matches the
    semantics of the bounded load_dotenv() copies in the src/ scripts."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key:
            out[key] = val.strip().strip("'\"")
    return out

def _load_env_frozen():
    """Frozen binary: load <exe-dir>/.env into os.environ (existing env wins).
    The scripts' own load_dotenv() can't find it — their marker walk starts in
    the throwaway _MEIPASS dir — but they all let real env vars take precedence."""
    if not IS_FROZEN:
        return
    path = os.path.join(os.path.dirname(sys.executable), ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            pairs = parse_env_text(fh.read())
    except OSError:
        return
    for key, val in pairs.items():
        os.environ.setdefault(key, val)
```

Then add `_load_env_frozen()` as the **first line of `main()`** (before `route(argv)`).

- [ ] **Step 4: Run tests to verify pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): frozen-mode helpers (resource_path, runtime dir, exe-side .env)"
```

---

### Task 2: Script-invocation seam — in-process when frozen, subprocess otherwise

A frozen binary has no `python3`, so `iro` must run bundled scripts in-process and spawn daemons by re-invoking itself. One seam (`_script_invocation`) decides; one executor (`_run_script`) acts.

**Files:**
- Modify: `src/iro.py` (`relay_start` ~line 91, `relay_run` ~line 121, `oneshot` ~line 326)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_iro.py`:

```python
def t_script_invocation_repo():
    import sys as _sys
    kind, argv, _ = m._script_invocation("scripts/preflight.py", ["--quick"], False)
    assert kind == "subprocess"
    assert argv[0] == _sys.executable
    assert argv[1].endswith(os.path.join("scripts", "preflight.py"))
    assert argv[-1] == "--quick"


def t_script_invocation_frozen():
    kind, path, args = m._script_invocation("relay/iro-feeds.py", ["--no-pov"], True,
                                            base=os.path.join("MEI", "src"))
    assert kind == "inprocess"
    assert path == os.path.join("MEI", "src", "relay", "iro-feeds.py")
    assert args == ["--no-pov"]


def t_relay_daemon_argv():
    import sys as _sys
    repo = m._relay_daemon_argv(["--no-pov"], False)
    assert repo[0] == _sys.executable and repo[1].endswith("iro-feeds.py")
    assert "--runtime-dir" in repo and repo[-1] == "--no-pov"
    assert m._relay_daemon_argv(["--no-pov"], True) == \
        [_sys.executable, "relay", "run", "--no-pov"]


def t_oneshot_extra():
    R = os.path.join("x", "runtime")
    assert m._oneshot_extra("preflight", [], False, R) == ["--runtime-dir", R]
    assert m._oneshot_extra("graphics", [], False, R) == []
    assert m._oneshot_extra("graphics", [], True, R) == \
        ["--out", os.path.join(R, "graphics")]
    assert m._oneshot_extra("media", [], True, R) == ["--out", os.path.join(R, "media")]
    assert m._oneshot_extra("setup", [], True, R) == \
        ["--out", os.path.join(R, "IRO_Endurance.import.json")]
    assert m._oneshot_extra("graphics", ["--out", "z"], True, R) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_iro.py` — Expected: `AttributeError ... _script_invocation`

- [ ] **Step 3: Implement in `src/iro.py`** — add below the Task-1 helpers:

```python
def _script_invocation(rel, args, frozen, base=None):
    """How to run a src/ script: subprocess in repo/package mode; in-process when
    frozen (the .py files ship as bundled data, there is no python3 to exec)."""
    if frozen:
        base = base if base is not None else _src_base(True, getattr(sys, "_MEIPASS", ""), HERE)
        return ("inprocess", os.path.join(base, *rel.split("/")), list(args))
    return ("subprocess", [sys.executable, os.path.join(HERE, *rel.split("/"))] + list(args), None)

def _run_module(path, args):
    """Load a bundled script by file path and run its main() with patched argv.
    Returns an exit code (SystemExit from argparse/sys.exit is translated)."""
    import importlib.util
    name = os.path.splitext(os.path.basename(path))[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = [os.path.basename(path)] + list(args)
    try:
        spec.loader.exec_module(mod)
        mod.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = old_argv

def _run_script(rel, args):
    kind, target, extra = _script_invocation(rel, args, IS_FROZEN)
    if kind == "subprocess":
        return subprocess.call(target)
    return _run_module(target, extra)

def _relay_daemon_argv(rest, frozen):
    """Detached relay child: frozen -> the binary re-invokes itself in foreground
    mode; otherwise python3 runs the script directly (as before)."""
    if frozen:
        return [sys.executable, "relay", "run"] + list(rest)
    return [sys.executable, _relay_script(), "--runtime-dir", _runtime_dir()] + list(rest)

def _oneshot_extra(command, rest, frozen, runtime_dir):
    """Extra argv for a one-shot. --runtime-dir where the script supports it (see
    RUNTIME_DIR_ONESHOTS); when frozen, also redirect default output locations
    away from the throwaway _MEIPASS unpack dir (unless the user passed --out)."""
    extra = []
    if command in RUNTIME_DIR_ONESHOTS:
        extra += ["--runtime-dir", runtime_dir]
    if frozen and "--out" not in rest:
        out = {"graphics": os.path.join(runtime_dir, "graphics"),
               "media": os.path.join(runtime_dir, "media"),
               "setup": os.path.join(runtime_dir, "IRO_Endurance.import.json")}.get(command)
        if out:
            extra += ["--out", out]
    return extra
```

Rewire the three call sites:

```python
def relay_start(rest):
    pid = sv.read_pid(_relay_pid_path())
    if sv.pid_alive(pid):
        print(f"relay already running (pid {pid}).")
        return relay_status([])
    argv = _relay_daemon_argv(rest, IS_FROZEN)
    newpid = sv.start_detached(argv, _relay_log_path(), _relay_pid_path())
    print(f"relay started (pid {newpid}). Watch it: iro relay logs -f")
```

```python
def relay_run(rest):
    raise SystemExit(_run_script("relay/iro-feeds.py",
                                 ["--runtime-dir", _runtime_dir()] + rest))
```

```python
def oneshot(command, rest):
    extra = _oneshot_extra(command, rest, IS_FROZEN, _runtime_dir())
    raise SystemExit(_run_script(ONESHOT_MAP[command], list(rest) + extra))
```

- [ ] **Step 4: Run all tests and a live spot check**

Run: `python3 tests/test_iro.py` → `ALL PASS`; `python3 tests/test_services.py` → `ALL PASS`
Run: `python3 src/iro.py status` → prints the three status lines (repo mode unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): frozen dispatch — in-process one-shots, binary re-invocation for daemons"
```

---

### Task 3: Windows-safe `services.py` (pid probe, spawn flags, taskkill)

**The bug this fixes:** on Windows, `os.kill(pid, sig)` with any signal other than `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` unconditionally calls `TerminateProcess` — so the current `pid_alive()` "probe" would **kill the relay** when run on Windows.

**Files:**
- Modify: `src/scripts/services.py` (`pid_alive` lines 16–28, `start_detached` line 43, `stop_pid` lines 66–87)
- Test: `tests/test_services.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_services.py`:

```python
def t_spawn_kwargs_per_os():
    assert m.spawn_kwargs("posix") == {"start_new_session": True}
    assert m.spawn_kwargs("nt") == {"creationflags": 0x00000008 | 0x00000200}
    assert m.spawn_kwargs("java") == {}


def t_stop_commands_per_os():
    assert m.stop_commands("posix", 123, force=False) is None
    assert m.stop_commands("posix", 123, force=True) is None
    assert m.stop_commands("nt", 123, force=False) == ["taskkill", "/PID", "123"]
    assert m.stop_commands("nt", 123, force=True) == \
        ["taskkill", "/F", "/T", "/PID", "123"]
```

(If `tests/test_services.py` loads the module under a different name than `m`, match its existing loader convention.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_services.py` — Expected: `AttributeError ... spawn_kwargs`

- [ ] **Step 3: Implement in `src/scripts/services.py`**

Add the pure helpers:

```python
def spawn_kwargs(os_name):
    """Popen kwargs that detach the child from our session/console per OS."""
    if os_name == "posix":
        return {"start_new_session": True}
    if os_name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {}


def stop_commands(os_name, pid, force):
    """argv to stop a PID on Windows (taskkill), or None where POSIX signals apply.
    /T kills the child tree — the relay's streamlink/yt-dlp children must not be
    orphaned. The non-force form asks first (WM_CLOSE); console children usually
    ignore it, so stop_pid() falls through to the force form after the timeout."""
    if os_name != "nt":
        return None
    if force:
        return ["taskkill", "/F", "/T", "/PID", str(pid)]
    return ["taskkill", "/PID", str(pid)]
```

Split `pid_alive` (keep the POSIX body as-is, moved under the `posix` branch):

```python
def pid_alive(pid):
    """True iff a process with this PID currently exists."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid):
    """ctypes probe — os.kill(pid, 0) is NOT safe on Windows: any signal other
    than CTRL_C/CTRL_BREAK unconditionally TerminateProcess()es the target."""
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # exists, no access
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)
```

In `start_detached`, replace the kwargs line with:

```python
    kwargs = spawn_kwargs(os.name)
```

Rework `stop_pid` to route through one stop primitive:

```python
def _signal_stop(pid, force):
    cmd = stop_commands(os.name, pid, force)
    if cmd is not None:
        subprocess.run(cmd, capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        pass


def stop_pid(pid, pid_path=None, timeout=10):
    """Graceful stop, wait up to timeout, then force; remove pid_path. True if gone."""
    if pid_alive(pid):
        _signal_stop(pid, force=False)
        for _ in range(timeout * 2):
            _reap_zombie(pid)
            if not pid_alive(pid):
                break
            time.sleep(0.5)
        if pid_alive(pid):
            _signal_stop(pid, force=True)
            time.sleep(0.5)
            _reap_zombie(pid)
    if pid_path and os.path.exists(pid_path):
        os.remove(pid_path)
    return not pid_alive(pid)
```

(`signal.SIGKILL` does not exist on Windows — safe here because `_signal_stop` only reaches `os.kill` on POSIX.)

- [ ] **Step 4: Run tests** (includes the real spawn→stop integration test)

Run: `python3 tests/test_services.py` → `ALL PASS`
Run: `python3 tests/test_iro.py` → `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/services.py tests/test_services.py
git commit -m "fix(services): Windows-safe pid probe (os.kill would TerminateProcess), taskkill stop, detached spawn flags"
```

---

### Task 4: Cross-platform Companion adapter

**Files:**
- Modify: `src/scripts/companion_common.py` (lines 95–103), `src/iro.py` (companion functions, lines 126–223)
- Test: `tests/test_companion.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_companion.py` (match its module-loader variable name):

```python
def t_control_commands_windows():
    exe = os.path.join("C:" + os.sep, "Apps", "Companion.exe")
    cmds = m.companion_control_commands("win32", exe=exe)
    assert cmds["start"] == [exe]
    assert cmds["quit"] == ["taskkill", "/IM", "Companion.exe"]
    assert cmds["running"] == ["tasklist", "/FI", "IMAGENAME eq Companion.exe"]


def t_control_commands_windows_requires_exe():
    assert m.companion_control_commands("win32", exe=None) is None


def t_control_commands_linux_is_manual():
    assert m.companion_control_commands("linux") is None


def t_control_commands_darwin_unchanged():
    cmds = m.companion_control_commands("darwin")
    assert cmds["start"] == ["open", "-a", "Companion"]


def t_find_companion_exe_override_wins():
    path = os.path.join("D:" + os.sep, "Tools", "Companion.exe")
    assert m.find_companion_exe({"IRO_COMPANION_EXE": path}, exists=lambda p: True) == path
    assert m.find_companion_exe({"IRO_COMPANION_EXE": path}, exists=lambda p: False) is None


def t_find_companion_exe_candidates():
    local = os.path.join("C:" + os.sep, "Users", "x", "AppData", "Local")
    hit = local + r"\Programs\companion\Companion.exe"
    assert m.find_companion_exe({"LOCALAPPDATA": local}, exists=lambda p: p == hit) == hit
    assert m.find_companion_exe({}, exists=lambda p: False) is None


def t_parse_running():
    assert m.parse_running("win32", 0, "INFO: No tasks are running ...") is False
    assert m.parse_running("win32", 0, '"Companion.exe","4242","Console"') is True
    assert m.parse_running("darwin", 0, "") is True
    assert m.parse_running("darwin", 1, "") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_companion.py` — Expected: `TypeError`/`AttributeError` (new signature/functions missing)

- [ ] **Step 3: Implement in `src/scripts/companion_common.py`** — replace `companion_control_commands` (lines 95–103) with:

```python
# Default install locations of Companion.exe — a heuristic, validated on the
# Windows streaming PC before the first release. IRO_COMPANION_EXE overrides.
WINDOWS_COMPANION_CANDIDATES = (
    r"%LOCALAPPDATA%\Programs\companion\Companion.exe",
    r"C:\Program Files\Companion\Companion.exe",
    r"C:\Program Files (x86)\Companion\Companion.exe",
)


def find_companion_exe(env=None, exists=os.path.exists):
    """Path to Companion.exe on Windows, or None. IRO_COMPANION_EXE wins."""
    env = os.environ if env is None else env
    override = env.get("IRO_COMPANION_EXE")
    if override:
        return override if exists(override) else None
    for cand in WINDOWS_COMPANION_CANDIDATES:
        path = cand.replace("%LOCALAPPDATA%", env.get("LOCALAPPDATA", ""))
        if not path.startswith("\\") and exists(path):
            return path
    return None


def companion_control_commands(platform, exe=None):
    """Start/quit/running argv per platform. Windows needs the discovered exe.
    Linux returns None by design: in the WSL/Docker scenario Companion runs on
    the HOST — local automation would target the wrong machine."""
    if platform == "darwin":
        return {
            "start": ["open", "-a", "Companion"],
            "quit": ["osascript", "-e", 'quit app "Companion"'],
            "running": ["pgrep", "-f", "Companion.app/Contents/Resources/main.js"],
        }
    if platform.startswith("win"):
        if not exe:
            return None
        return {
            "start": [exe],
            "quit": ["taskkill", "/IM", "Companion.exe"],  # graceful WM_CLOSE first
            "running": ["tasklist", "/FI", "IMAGENAME eq Companion.exe"],
        }
    return None


def parse_running(platform, returncode, stdout):
    """Interpret the 'running' probe. tasklist exits 0 even with NO match, so on
    Windows the image name must appear in the output; elsewhere rc==0 suffices."""
    if platform.startswith("win"):
        return "Companion.exe" in stdout
    return returncode == 0
```

Also update the module docstring's "macOS-only" note to "Windows + macOS automated; Linux manual by design".

- [ ] **Step 4: Rewire `src/iro.py`** — replace `_companion_running` (lines 130–132) with:

```python
def _companion_cmds(cc):
    exe = cc.find_companion_exe() if sys.platform.startswith("win") else None
    return cc.companion_control_commands(sys.platform, exe)

def _companion_unsupported_msg():
    if sys.platform.startswith("win"):
        return ("companion: Companion.exe not found. Set IRO_COMPANION_EXE in .env "
                "to its full path and retry.")
    return ("companion: automated control supports Windows and macOS. On Linux "
            "(WSL/Docker), run and bind Companion on the host instead.")

def _companion_running(cc):
    cmds = _companion_cmds(cc)
    if not cmds:
        return False
    probe = subprocess.run(cmds["running"], capture_output=True, text=True)
    return cc.parse_running(sys.platform, probe.returncode, probe.stdout or "")
```

In `companion_start` (lines 134–176): replace the `cmds = cc.companion_control_commands(...)` + `if cmds is None: sys.exit(...)` block with:

```python
    cmds = _companion_cmds(cc)
    if cmds is None:
        sys.exit(_companion_unsupported_msg())
```

and replace the start invocation `subprocess.run(cmds["start"], capture_output=True)` with a non-blocking spawn (on Windows, running `Companion.exe` via `run()` would block until the app exits):

```python
        subprocess.Popen(cmds["start"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
```

In `companion_stop` (lines 178–193): same `cmds`/`sys.exit` replacement, and make the force-quit hint per-OS:

```python
    hint = ("taskkill /F /IM Companion.exe" if sys.platform.startswith("win")
            else "pkill -f Companion")
    print(f"companion may still be running. Force-quit: {hint}")
```

In `companion_status` (lines 199–214): replace the first check with:

```python
    cmds = _companion_cmds(cc)
    if cmds is None:
        why = ("(Companion.exe not found — set IRO_COMPANION_EXE in .env)"
               if sys.platform.startswith("win") else f"(manual on {sys.platform})")
        print(sv.status_line("companion", None, False, why))
        return
```

- [ ] **Step 5: Run tests + live macOS regression**

Run: `python3 tests/test_companion.py` → `ALL PASS`; `python3 tests/test_iro.py` → `ALL PASS`
Run: `python3 src/iro.py companion status` → same behavior as before on macOS

- [ ] **Step 6: Commit**

```bash
git add src/scripts/companion_common.py src/iro.py tests/test_companion.py
git commit -m "feat(companion): Windows control adapter (exe discovery, taskkill/tasklist), Linux manual by design"
```

---

### Task 5: Frozen-aware static streams + hidden `streams run-feed`

`start-streams.py` spawns `python3 loopstream.py` per feed — impossible in a frozen binary. The feed child becomes a re-invocation of the binary via a hidden verb; both stream scripts learn `--state-dir` so the binary can point them at the exe-side runtime dir.

**Files:**
- Modify: `src/scripts/start-streams.py`, `src/scripts/stop-streams.py`, `src/iro.py` (streams adapter lines 226–260, `route` lines 51–67)
- Create: `tests/test_streams.py`
- Test: `tests/test_streams.py`, `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streams.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the static-streams helpers. Run: python3 tests/test_streams.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


start = _load("start_streams", os.path.join("src", "scripts", "start-streams.py"))
stop = _load("stop_streams", os.path.join("src", "scripts", "stop-streams.py"))


def t_feed_argv_repo_uses_python():
    argv = start.feed_argv(False, "python3", os.path.join("x", "loopstream.py"),
                           "UC123", "53001")
    assert argv == ["python3", os.path.join("x", "loopstream.py"), "UC123", "53001"]


def t_feed_argv_frozen_reinvokes_binary():
    argv = start.feed_argv(True, os.path.join("apps", "iro"), "ignored", "UC123", "53001")
    assert argv == [os.path.join("apps", "iro"), "streams", "run-feed", "UC123", "53001"]


def t_state_dirs_match():
    here = os.path.join(ROOT, "src", "scripts")
    assert start.state_dir(here) == stop.state_dir(here)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

Append to `tests/test_iro.py`:

```python
def t_streams_run_feed_hidden():
    assert m.route(["streams", "run-feed", "UC1", "53001"])["verb"] == "run-feed"
    try:
        m.route(["streams", "bogus"])
    except ValueError as e:
        assert "run-feed" not in str(e)  # hidden verb is not advertised
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_streams.py` — Expected: `AttributeError ... feed_argv`
Run: `python3 tests/test_iro.py` — Expected: `ValueError` from the `run-feed` route

- [ ] **Step 3: Implement `src/scripts/start-streams.py`**

Add `import argparse` to the imports; add below `state_dir`:

```python
def feed_argv(frozen, executable, loop_path, channel, port):
    """Child argv for one feed. Frozen iro binary: re-invoke ourselves with the
    hidden `streams run-feed` verb (no python3 on producer machines); otherwise
    run loopstream.py with the current interpreter."""
    if frozen:
        return [executable, "streams", "run-feed", channel, port]
    return [executable, loop_path, channel, port]
```

In `main()`, parse `--state-dir` and use `feed_argv`:

```python
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=state_dir(here),
                    help="PID/log dir (iro passes <runtime>/static explicitly).")
    a = ap.parse_args()
    sdir = a.state_dir
    logdir = os.path.join(sdir, "logs")
    os.makedirs(logdir, exist_ok=True)
    if not shutil.which("streamlink"):
        sys.exit("streamlink not found (brew install streamlink / pip install -U streamlink).")
    loop = os.path.join(here, "loopstream.py")
    frozen = bool(getattr(sys, "frozen", False))
    for i, (ch, port) in enumerate(FEEDS, 1):
        log = open(os.path.join(logdir, f"feed_{port}.log"), "ab")
        p = subprocess.Popen(feed_argv(frozen, sys.executable, loop, ch, port),
                             stdout=log, stderr=subprocess.STDOUT)
        open(os.path.join(sdir, f"feed_{port}.pid"), "w").write(str(p.pid))
        print(f"Started Feed {i} -> channel {ch} on http://127.0.0.1:{port} (log: {logdir}/feed_{port}.log)")
    print("\nAll feeds launched. Point each OBS media source at its http://127.0.0.1:PORT.")
    print("Stop everything with:  iro streams stop")
```

- [ ] **Step 4: Implement `src/scripts/stop-streams.py`** — add `import argparse`; change `main()`'s first lines to:

```python
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=state_dir(here))
    a = ap.parse_args()
    pidfiles = glob.glob(os.path.join(a.state_dir, "feed_*.pid"))
```

(rest of `main()` unchanged)

- [ ] **Step 5: Implement `src/iro.py`** — next to `EXTRA_VERBS` add:

```python
# Internal verbs: routed but never advertised (frozen feed children use run-feed).
HIDDEN_VERBS = {"streams": ("run-feed",)}
```

In `route()`, change the verb check to:

```python
        valid = SERVICE_VERBS + EXTRA_VERBS.get(cmd, ())
        if verb not in valid + HIDDEN_VERBS.get(cmd, ()):
            raise ValueError(f"usage: iro {cmd} {{{'|'.join(valid)}}}")
```

Replace `streams_start`/`streams_stop` and add `streams_run_feed`:

```python
def streams_start(rest):
    raise SystemExit(_run_script("scripts/start-streams.py",
                                 ["--state-dir", _streams_static_dir()] + rest))

def streams_stop(rest):
    # No SystemExit: streams_restart() must continue into streams_start().
    _run_script("scripts/stop-streams.py",
                ["--state-dir", _streams_static_dir()] + rest)

def streams_run_feed(rest):
    raise SystemExit(_run_script("scripts/loopstream.py", rest))
```

Add to `DISPATCH`: `("streams", "run-feed"): streams_run_feed,`

- [ ] **Step 6: Run tests + live check**

Run: `python3 tests/test_streams.py` → `ALL PASS`; `python3 tests/test_iro.py` → `ALL PASS`
Run: `python3 src/iro.py streams status` → unchanged output

- [ ] **Step 7: Commit**

```bash
git add src/scripts/start-streams.py src/scripts/stop-streams.py src/iro.py tests/test_streams.py tests/test_iro.py
git commit -m "feat(streams): frozen-aware feed spawn via hidden 'streams run-feed', --state-dir flag"
```

---

### Task 6: `iro install-tools`

**Files:**
- Create: `src/scripts/install_tools.py`
- Modify: `src/iro.py` (ONESHOTS line 46, ONESHOT_MAP lines 312–318, USAGE docstring lines 1–12)
- Create: `tests/test_install_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_install_tools.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for install_tools decision helpers. Run: python3 tests/test_install_tools.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "install_tools", os.path.join(ROOT, "src", "scripts", "install_tools.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_pick_manager_per_platform():
    have_all = lambda name: "/usr/bin/" + name
    assert m.pick_manager("win32", which=have_all) == "winget"
    assert m.pick_manager("darwin", which=have_all) == "brew"
    assert m.pick_manager("linux", which=have_all) == "apt"
    assert m.pick_manager("win32", which=lambda n: None) is None


def t_missing_tools():
    assert m.missing_tools(which=lambda n: None) == list(m.TOOLS)
    assert m.missing_tools(which=lambda n: "/bin/" + n) == []
    only_ffmpeg = lambda n: "/bin/ffmpeg" if n == "ffmpeg" else None
    assert m.missing_tools(which=only_ffmpeg) == ["yt-dlp", "streamlink", "deno"]


def t_install_commands_winget_one_per_tool():
    cmds = m.install_commands("winget", ["yt-dlp", "deno"])
    assert len(cmds) == 2
    assert cmds[0][:3] == ["winget", "install", "--id"]
    assert cmds[0][3] == "yt-dlp.yt-dlp" and cmds[1][3] == "DenoLand.Deno"


def t_install_commands_brew_single_batch():
    assert m.install_commands("brew", ["ffmpeg", "deno"]) == \
        [["brew", "install", "ffmpeg", "deno"]]
    assert m.install_commands("brew", []) == []


def t_install_commands_apt_skips_deno():
    cmds = m.install_commands("apt", ["yt-dlp", "deno"])
    assert cmds == [["apt-get", "install", "-y", "yt-dlp"]]
    assert m.install_commands("apt", ["deno"]) == []


def t_manual_guide_mentions_deno_on_linux():
    assert "deno" in m.manual_guide("linux")
    assert "brew install" in m.manual_guide("darwin")
    assert "winget" in m.manual_guide("win32")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_install_tools.py` — Expected: `FileNotFoundError` (module missing)

- [ ] **Step 3: Create `src/scripts/install_tools.py`**

```python
#!/usr/bin/env python3
"""`iro install-tools` — install the external runtime tools (yt-dlp, streamlink,
ffmpeg, deno) via the platform's package manager: winget (Windows), brew (macOS),
apt (Linux). Never elevates privileges itself; failed installs end with a manual
guide. Pure decision helpers up top (unit-tested); main() performs the installs."""
import shutil, subprocess, sys

TOOLS = ("yt-dlp", "streamlink", "ffmpeg", "deno")

WINGET_IDS = {"yt-dlp": "yt-dlp.yt-dlp", "streamlink": "Streamlink.Streamlink",
              "ffmpeg": "Gyan.FFmpeg", "deno": "DenoLand.Deno"}
APT_PACKAGES = {"yt-dlp": "yt-dlp", "streamlink": "streamlink", "ffmpeg": "ffmpeg"}
# deno ships no apt package — Linux users get a pointer in manual_guide().


def pick_manager(platform, which=shutil.which):
    """Package manager for this platform, or None (-> manual guide)."""
    if platform.startswith("win"):
        return "winget" if which("winget") else None
    if platform == "darwin":
        return "brew" if which("brew") else None
    return "apt" if which("apt-get") else None


def missing_tools(which=shutil.which):
    return [t for t in TOOLS if not which(t)]


def install_commands(manager, tools):
    """The argv list(s) to install `tools` with `manager`."""
    if manager == "winget":
        return [["winget", "install", "--id", WINGET_IDS[t], "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]
                for t in tools]
    if manager == "brew":
        return [["brew", "install"] + list(tools)] if tools else []
    if manager == "apt":
        pkgs = [APT_PACKAGES[t] for t in tools if t in APT_PACKAGES]
        return [["apt-get", "install", "-y"] + pkgs] if pkgs else []
    return []


def manual_guide(platform):
    if platform.startswith("win"):
        return ("Install manually with winget (one per line):\n"
                + "\n".join(f"  winget install --id {WINGET_IDS[t]} -e" for t in TOOLS))
    if platform == "darwin":
        return "Install manually:  brew install yt-dlp streamlink ffmpeg deno"
    return ("Install manually:  sudo apt-get install -y yt-dlp streamlink ffmpeg\n"
            "deno has no apt package — see https://docs.deno.com/runtime/getting_started/installation/")


def main():
    missing = missing_tools()
    if not missing:
        print("All external tools already installed:", ", ".join(TOOLS))
        return
    print("Missing tools:", ", ".join(missing))
    manager = pick_manager(sys.platform)
    if manager is None:
        sys.exit("No supported package manager found.\n" + manual_guide(sys.platform))
    failed = []
    for cmd in install_commands(manager, missing):
        print("Running:", " ".join(cmd))
        if subprocess.call(cmd) != 0:
            failed.append(" ".join(cmd))
    if manager == "apt" and "deno" in missing:
        print("NOTE: deno is not packaged for apt — install it manually:")
        print("  https://docs.deno.com/runtime/getting_started/installation/")
    still = missing_tools()
    if failed or still:
        parts = ["Some installs did not complete."]
        if failed:
            parts.append("Failed: " + "; ".join(failed))
        if still:
            parts.append("Still missing: " + ", ".join(still))
        sys.exit("\n".join(parts) + "\n" + manual_guide(sys.platform))
    print("All tools installed. Run `iro preflight` to verify.")


if __name__ == "__main__":
    main()
```

(On Linux a permission failure from `apt-get` is reported, and the manual guide shows the `sudo` form — the script itself never calls `sudo`.)

- [ ] **Step 4: Wire into `src/iro.py`**

- `ONESHOTS = ("preflight", "cookies", "graphics", "media", "setup", "install-tools")`
- Add to `ONESHOT_MAP`: `"install-tools": "scripts/install_tools.py",`
- Add to the USAGE docstring's one-shot line: `… | install-tools`
- Append a routing test to `tests/test_iro.py`:

```python
def t_install_tools_oneshot():
    assert m.route(["install-tools"]) == \
        {"kind": "oneshot", "command": "install-tools", "rest": []}
```

- [ ] **Step 5: Run tests**

Run: `python3 tests/test_install_tools.py` → `ALL PASS`; `python3 tests/test_iro.py` → `ALL PASS`
Run: `python3 src/iro.py install-tools` → on this dev Mac everything is installed → prints "All external tools already installed: …"

- [ ] **Step 6: Commit**

```bash
git add src/scripts/install_tools.py tests/test_install_tools.py src/iro.py tests/test_iro.py
git commit -m "feat(cli): iro install-tools — winget/brew/apt installer for the external runtime tools"
```

---

### Task 7: `iro --version` and `iro export companion`

**Files:**
- Modify: `src/iro.py` (`route`, `main`, USAGE docstring)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_iro.py`:

```python
def t_version_route_and_dev_default():
    assert m.route(["--version"]) == {"kind": "version"}
    assert m.route(["-V"]) == {"kind": "version"}
    assert m.version() == "dev"  # repo checkout has no bundled VERSION file


def t_export_route():
    r = m.route(["export", "companion", "--out", "x"])
    assert r == {"kind": "export", "target": "companion", "rest": ["--out", "x"]}
    _raises(lambda: m.route(["export"]))
    _raises(lambda: m.route(["export", "obs"]))


def t_export_companion_writes_file():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "buttons.companionconfig")
        m.export_companion(["--out", dst])
        assert os.path.getsize(dst) > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_iro.py` — Expected: `ValueError: unknown command: --version`

- [ ] **Step 3: Implement in `src/iro.py`**

In `route()`, after the help check insert:

```python
    if argv[0] in ("--version", "-V"):
        return {"kind": "version"}
```

and before the final `raise ValueError`:

```python
    if cmd == "export":
        if rest[:1] != ["companion"]:
            raise ValueError("usage: iro export companion [--out PATH]")
        return {"kind": "export", "target": "companion", "rest": rest[1:]}
```

Add the functions (near `aggregate_status`):

```python
def version():
    """Build version: a VERSION file is stamped into the bundle by
    tools/build-binary.py; a repo checkout has none -> 'dev'."""
    try:
        with open(resource_path("VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"

def export_companion(rest):
    """Write the bundled (password-stripped) Companion config for import."""
    out = None
    if rest[:1] == ["--out"] and len(rest) == 2:
        out = rest[1]
    elif rest:
        sys.exit("usage: iro export companion [--out PATH]")
    dst = out or os.path.join(os.getcwd(), "iro-buttons.companionconfig")
    if os.path.isdir(dst):
        dst = os.path.join(dst, "iro-buttons.companionconfig")
    shutil.copyfile(resource_path("companion/iro-buttons.companionconfig"), dst)
    print(f"Wrote {dst} — import it in Companion (Import / Export -> Import).")
```

In `main()`, before the `service` branch:

```python
    if action["kind"] == "version":
        print(f"iro {version()}")
        return
    if action["kind"] == "export":
        return export_companion(action["rest"])
```

Add to the USAGE docstring:

```
  iro export companion [--out PATH]     # write the Companion button config
  iro --version
```

- [ ] **Step 4: Run tests + live check**

Run: `python3 tests/test_iro.py` → `ALL PASS`
Run: `python3 src/iro.py --version` → `iro dev`

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): iro --version and iro export companion"
```

---

### Task 8: Maintainer build tools — `tools/run-tests.py` + `tools/build-binary.py`

Maintainer-only (`tools/` is not shipped). `run-tests.py` is the cross-platform test runner CI uses (no shell globbing). `build-binary.py` runs PyInstaller and smoke-tests the produced binary.

**Files:**
- Create: `tools/run-tests.py`, `tools/build-binary.py`

- [ ] **Step 1: Create `tools/run-tests.py`**

```python
#!/usr/bin/env python3
"""Run every tests/test_*.py as its own process (the project's no-pytest
convention); exit non-zero if any fails. This is exactly what CI runs."""
import glob, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    failures = []
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
        print(f"== {os.path.basename(path)}", flush=True)
        if subprocess.call([sys.executable, path]) != 0:
            failures.append(os.path.basename(path))
    if failures:
        sys.exit("FAILED: " + ", ".join(failures))
    print("ALL TEST FILES PASS")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs the whole suite**

Run: `python3 tools/run-tests.py`
Expected: every suite prints `ALL PASS`, final line `ALL TEST FILES PASS`

- [ ] **Step 3: Create `tools/build-binary.py`**

```python
#!/usr/bin/env python3
"""Build the standalone `iro` binary with PyInstaller and smoke-test it.
One binary per OS — run this on the OS you are targeting (CI runs a 3-OS matrix).
Usage: python3 tools/build-binary.py [--version vX.Y.Z] [--skip-smoke]
Output: dist/bin/iro (dist/bin/iro.exe on Windows). The producer ZIP package is
a separate artifact built by tools/build.py."""
import argparse, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
# Bundled data, laid out under _MEIPASS/src/ so every script's here-relative
# path resolution (hud.html, assets/, OBS template) keeps working unchanged.
DATA = ["relay", "scripts", "obs", "assets", "companion", "director", "setup-assets.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev")
    ap.add_argument("--skip-smoke", action="store_true")
    a = ap.parse_args()
    if not shutil.which("pyinstaller"):
        sys.exit("pyinstaller not found (pip install pyinstaller / brew install pyinstaller).")
    workdir = tempfile.mkdtemp(prefix="iro-build-")
    version_file = os.path.join(workdir, "VERSION")
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(a.version + "\n")
    sep = ";" if os.name == "nt" else ":"
    cmd = ["pyinstaller", "--onefile", "--name", "iro", "--clean", "--noconfirm",
           "--distpath", os.path.join(ROOT, "dist", "bin"),
           "--workpath", os.path.join(workdir, "build"),
           "--specpath", workdir,
           # services/companion_common are real frozen modules (iro.py imports them)
           "--paths", os.path.join(SRC, "scripts"),
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--add-data", f"{version_file}{sep}src"]
    for rel in DATA:
        cmd += ["--add-data", f"{os.path.join(SRC, rel)}{sep}src/{rel}"]
    cmd.append(os.path.join(SRC, "iro.py"))
    print("Running:", " ".join(cmd), flush=True)
    if subprocess.call(cmd) != 0:
        sys.exit("pyinstaller failed.")
    binary = os.path.join(ROOT, "dist", "bin", "iro.exe" if os.name == "nt" else "iro")
    if not os.path.isfile(binary):
        sys.exit(f"expected binary missing: {binary}")
    print(f"Built {binary} ({os.path.getsize(binary) // (1024 * 1024)} MB)")
    if not a.skip_smoke:
        smoke(binary, a.version)


def smoke(binary, version):
    """The binary must self-report the version, print aggregate status, and export
    the Companion config — proves bundled data + frozen dispatch actually work."""
    def run(args):
        return subprocess.run([binary] + args, capture_output=True, text=True, timeout=60)

    out = run(["--version"])
    if out.returncode != 0 or version not in out.stdout:
        sys.exit(f"smoke --version FAILED: rc={out.returncode} out={out.stdout!r} err={out.stderr!r}")
    st = run(["status"])
    if st.returncode != 0 or "relay" not in st.stdout:
        sys.exit(f"smoke status FAILED: rc={st.returncode} out={st.stdout!r} err={st.stderr!r}")
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "iro-buttons.companionconfig")
        ex = run(["export", "companion", "--out", dst])
        if ex.returncode != 0 or not os.path.isfile(dst):
            sys.exit(f"smoke export FAILED: rc={ex.returncode} err={ex.stderr!r}")
    print("Smoke test OK (--version, status, export companion).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Build and smoke-test locally on macOS**

Run once: `brew install pyinstaller` (or `python3 -m pip install --user pyinstaller`)
Run: `python3 tools/build-binary.py --version dev-local`
Expected: PyInstaller output, then `Built …/dist/bin/iro (… MB)` and `Smoke test OK (…)`.

Then exercise the frozen daemon round-trip by hand (the real proof of `child_argv`-style re-invocation):

```bash
mkdir -p /tmp/iro-bin-test && cp dist/bin/iro /tmp/iro-bin-test/ && cp .env /tmp/iro-bin-test/
cd /tmp/iro-bin-test && ./iro relay start && sleep 5 && ./iro status && ./iro relay stop
```

Expected: `relay started (pid …)`, status shows `RUNNING` with the control URL, then `relay stopped.` Afterwards `cd` back to the repo.

- [ ] **Step 5: Commit**

```bash
git add tools/run-tests.py tools/build-binary.py
git commit -m "build: PyInstaller binary builder with smoke test + cross-platform test runner"
```

---

### Task 9: GitHub Actions — CI matrix + release workflow

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
defaults:
  run:
    shell: bash
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Run test suite
        run: python tools/run-tests.py
```

- [ ] **Step 2: Create `.github/workflows/release.yml`**

```yaml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
defaults:
  run:
    shell: bash
jobs:
  create-release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Create the GitHub release (idempotent)
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "${{ github.ref_name }}" --generate-notes || true
  build:
    needs: create-release
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            asset: iro-windows.exe
            built: dist/bin/iro.exe
          - os: macos-latest
            asset: iro-macos
            built: dist/bin/iro
          - os: ubuntu-latest
            asset: iro-linux
            built: dist/bin/iro
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Run test suite
        run: python tools/run-tests.py
      - name: Install PyInstaller
        run: python -m pip install pyinstaller
      - name: Build + smoke-test the binary
        run: python tools/build-binary.py --version "${{ github.ref_name }}"
      - name: Upload release asset
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          cp "${{ matrix.built }}" "${{ matrix.asset }}"
          gh release upload "${{ github.ref_name }}" "${{ matrix.asset }}" --clobber
```

- [ ] **Step 3: Validate the YAML parses**

Run: `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('YAML OK')"`
(If PyYAML is unavailable: `python3 -c "import json"` is no substitute — instead run `ruby -ryaml -e "Dir['.github/workflows/*.yml'].each{|f| YAML.load_file(f)}; puts 'YAML OK'"`, which is preinstalled on macOS.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "ci: 3-OS test matrix + tagged release workflow building the iro binaries"
```

**Note for the controller:** the workflows first *run* when this branch reaches GitHub. The Windows leg of `ci.yml` is the first real Windows execution of the test suite — if a test fails there, fix the product code or make the test platform-aware; never skip it silently.

---

### Task 10: Ship-checks + docs

**Files:**
- Modify: `tools/build.py` (checks dict, lines 117–137), `CLAUDE.md`, `README.md`

- [ ] **Step 1: Extend `tools/build.py` checks** — add to the `checks` dict:

```python
        "install-tools shipped": os.path.isfile(os.path.join(PKG, "scripts", "install_tools.py")),
```

- [ ] **Step 2: Run the package build to verify**

Run: `python3 tools/build.py`
Expected: all checks `[OK]`, including `install-tools shipped`.

- [ ] **Step 3: Update `CLAUDE.md`**

In the **Commands** section, add to the `iro` block:

```bash
python3 src/iro.py install-tools     # install yt-dlp/streamlink/ffmpeg/deno (winget/brew/apt)
python3 src/iro.py export companion  # write the Companion button config for import
python3 src/iro.py --version
```

add to the test list:

```bash
python3 tests/test_streams.py        # static-streams helpers (frozen feed spawn)
python3 tests/test_install_tools.py  # install-tools decision helpers
python3 tools/run-tests.py           # the whole suite (exactly what CI runs)
```

and after the `tools/build.py` line:

```bash
# Standalone binary (maintainer; one per OS — CI builds all three on tags v*)
python3 tools/build-binary.py        # -> dist/bin/iro (+ smoke test)
```

In the **Architecture** section, add a subsection after "Unified `iro` CLI":

```markdown
### Standalone binary (PyInstaller)
`tools/build-binary.py` freezes `src/iro.py` into one executable per OS; the whole
`src/` tree ships as bundled data under `sys._MEIPASS/src/`, so here-relative path
resolution keeps working. In frozen mode (`sys.frozen`), `iro` runs bundled scripts
**in-process** (importlib + patched argv) and daemons re-invoke the binary itself
(`iro relay run`, hidden `iro streams run-feed`); `runtime/` and `.env` live next to
the binary (keep it in its own folder). `services.py`/`companion_common.py` carry the
per-OS process control (Windows: ctypes PID probe — `os.kill(pid, 0)` would TERMINATE
the target there — taskkill/tasklist, Companion.exe discovery + `IRO_COMPANION_EXE`
override; Linux Companion control is manual by design). Releases: push a `v*` tag —
`.github/workflows/release.yml` tests, builds, smoke-tests and uploads
`iro-windows.exe` / `iro-macos` / `iro-linux`. CI (`ci.yml`) runs the test suite on
all three OSes for every PR.
```

- [ ] **Step 4: Update `README.md`** — add a short section under the operator quickstart:

```markdown
## Standalone binary (no Python needed)

Download your platform's binary from the GitHub **Releases** page
(`iro-windows.exe`, `iro-macos`, `iro-linux`), put it in **its own folder**
(it creates `runtime/` and reads `.env` next to itself), then:

    iro install-tools     # one-time: installs yt-dlp/streamlink/ffmpeg/deno
    iro preflight         # verify the machine is ready
    iro export companion  # write the Companion button config for import

First start: Windows SmartScreen / macOS Gatekeeper show a one-time warning for
unsigned binaries — choose "Run anyway" / right-click → Open.
```

- [ ] **Step 5: Run the full suite one last time**

Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
Run: `python3 tools/build.py` → all checks `[OK]`

- [ ] **Step 6: Commit**

```bash
git add tools/build.py CLAUDE.md README.md
git commit -m "docs+build: standalone binary docs, install-tools ship check"
```

---

## Post-plan validation (not part of the tasks)

- Native validation on the **Windows streaming PC** before the first `v*` tag: Companion.exe discovery paths, graceful `taskkill` close, relay start/stop/status end-to-end, `install-tools` via winget (spec "Validation plan").
- Wiki pages (SmartScreen/Gatekeeper screenshots, binary quickstart) need real screenshots from the Windows PC — separate follow-up, out of this plan.
