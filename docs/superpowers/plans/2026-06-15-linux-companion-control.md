# Linux Companion Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `racecast companion start|stop|status`, `event start` step 5, and the Control Center companion ops control the companion-pi systemd service on native Linux, binding the Tailscale IP (or 127.0.0.1) — never `0.0.0.0`.

**Architecture:** A new pure+thin-I/O module `src/scripts/companion_linux.py` holds the companion-pi control commands, systemd-unit detection, the content of a systemd `ExecStart` drop-in + a root bind-helper + a visudo-validated sudoers file, and the idempotent `enable_control()` orchestration. `src/racecast.py` gains a Linux branch in `_companion_cmds`/`companion_start`/`companion_stop` and a new `companion enable-control` verb. `install_apps.py` invokes `enable_control()` after a Linux Companion install. The bind address is computed by the existing pure `companion_common.desired_bind_ip()`.

**Tech Stack:** Python 3 stdlib only (subprocess, shutil, os, getpass, ipaddress, tempfile). Tests are runnable scripts (no pytest), one assert-function per behavior, executed by `tools/run-tests.py`.

**Spec:** `docs/superpowers/specs/2026-06-15-linux-companion-control-design.md`

**Important constraints (from CLAUDE.md):**
- Edit only under `src/`. The bind helper is a *string written at runtime* to `/usr/local/sbin/` on the target machine — do NOT create a `.sh`/`.bat` file in the repo (the build fails if any shell script ships).
- Tests must run on the Windows/macOS/Linux CI matrix with injected fakes — no real `systemctl`/`sudo`/machine paths. Linux absolute paths in fixtures are plain string constants, fine on any OS (they are compared as strings, never `os.path.join`-ed).
- Run `python3 tools/lint.py` after changing any Python file.

---

## File Structure

- **Create:** `src/scripts/companion_linux.py` — companion-pi control: path constants, `control_commands(unit)`, `detect_unit(...)`, `is_valid_bind_ip(ip)`, content builders, `is_enabled(...)`, `enable_control(...)`.
- **Create:** `tests/test_companion_linux.py` — unit checks for the above.
- **Modify:** `src/racecast.py` — `_companion_cmds` Linux branch; `companion_start`/`companion_stop` Linux branches; `companion_enable_control`; `_companion_unsupported_msg` Linux text; `EXTRA_VERBS`, `DISPATCH`, usage string.
- **Modify:** `tests/test_racecast.py` — route test for the new verb.
- **Modify:** `src/scripts/install_apps.py` — call `enable_control()` after a Linux Companion install; a decision helper.
- **Modify:** `tests/test_install_apps.py` — decision-helper test.
- **Modify:** `CLAUDE.md`, `README.md` — doc the new Linux behavior + `enable-control` verb.
- **Modify:** `tools/run-tests.py` — register the new test file (if it enumerates explicitly).

---

## Task 1: companion_linux path constants, IP validation, content builders

**Files:**
- Create: `src/scripts/companion_linux.py`
- Test: `tests/test_companion_linux.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_companion_linux.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the Linux companion-pi control helpers.
Run: python3 tests/test_companion_linux.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import companion_linux as cl


# --- is_valid_bind_ip --------------------------------------------------------
def t_valid_ipv4():
    assert cl.is_valid_bind_ip("100.64.10.20") is True
    assert cl.is_valid_bind_ip("127.0.0.1") is True
    assert cl.is_valid_bind_ip("0.0.0.0") is True   # explicit operator override is allowed


def t_valid_ipv6():
    assert cl.is_valid_bind_ip("::1") is True


def t_invalid_ip_rejected():
    assert cl.is_valid_bind_ip("not-an-ip") is False
    assert cl.is_valid_bind_ip("100.64.10.20; rm -rf /") is False
    assert cl.is_valid_bind_ip("") is False


# --- bind_env_content --------------------------------------------------------
def t_bind_env_content_writes_var():
    assert cl.bind_env_content("100.64.10.20") == "RACECAST_ADMIN_ADDRESS=100.64.10.20\n"


def t_bind_env_content_rejects_bad_ip():
    raised = False
    try:
        cl.bind_env_content("$(reboot)")
    except ValueError:
        raised = True
    assert raised


# --- bind_dropin_content -----------------------------------------------------
def t_dropin_resets_and_sets_execstart_with_admin_address():
    c = cl.bind_dropin_content()
    assert "[Service]\n" in c
    assert f"EnvironmentFile=-{cl.BIND_ENV}\n" in c
    assert "ExecStart=\n" in c                       # reset the vendor ExecStart first
    assert "--admin-address \"${RACECAST_ADMIN_ADDRESS:-127.0.0.1}\"" in c
    assert "/opt/companion/main.js" in c
    assert "--extra-module-path /opt/companion-module-dev" in c


# --- sudoers_dropin_content --------------------------------------------------
def t_sudoers_content_narrow_nopasswd():
    c = cl.sudoers_dropin_content("jegr", "/usr/bin/systemctl")
    assert c.endswith(
        "jegr ALL=(root) NOPASSWD: /usr/local/sbin/racecast-companion-bind, "
        "/usr/bin/systemctl stop companion\n")


# --- bind_helper_content -----------------------------------------------------
def t_helper_validates_and_restarts():
    c = cl.bind_helper_content()
    assert c.startswith("#!/bin/bash\n")
    assert "systemctl restart companion" in c
    assert cl.BIND_ENV in c
    assert "exit 2" in c                             # rejects a bad ip argument


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_companion_linux.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'companion_linux'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/companion_linux.py`:

```python
"""Linux companion-pi control for the `racecast companion` adapter.

companion-pi runs Bitfocus Companion as a systemd service (user `companion`,
launched by /usr/local/src/companionpi/launch.sh, which passes no bind flag so
Companion binds 0.0.0.0). Companion 3.x headless takes the bind only as the CLI
flag `--admin-address`; config.json is ignored. To enforce the toolkit's
"never 0.0.0.0 — Tailscale IP or 127.0.0.1" rule we override the service's
ExecStart via a systemd drop-in that reads the address from an EnvironmentFile,
and set that file (per start) through a narrow root helper. enable_control()
installs the drop-in, the helper, and a visudo-validated NOPASSWD sudoers rule.

Pure logic (content builders, validation, idempotency) is unit-tested; the I/O
in enable_control() takes injected `run`/`read_text`/`write_temp` seams so the
command sequence is testable without root.

This module ships NO shell-script file — bind_helper_content() is a string
written to /usr/local/sbin at enable_control() time on the target machine.
"""
import ipaddress, os, shutil, subprocess, sys, tempfile, getpass

UNIT = "companion"
DROPIN_DIR = "/etc/systemd/system/companion.service.d"
DROPIN_CONF = DROPIN_DIR + "/racecast-bind.conf"
BIND_ENV = DROPIN_DIR + "/racecast-bind.env"
HELPER_PATH = "/usr/local/sbin/racecast-companion-bind"
SUDOERS_PATH = "/etc/sudoers.d/racecast-companion"
SERVICE_UNIT_FILE = "/etc/systemd/system/companion.service"
LEGACY_2X_DIR = "/usr/local/src/companion"   # companion-pi 2.x layout (headless_ip.js)


def is_valid_bind_ip(ip):
    """True iff `ip` is a literal IPv4/IPv6 address (defends the helper's argv)."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def bind_env_content(ip):
    """EnvironmentFile body pinning the admin bind address. Raises on a bad ip."""
    if not is_valid_bind_ip(ip):
        raise ValueError(f"invalid bind ip: {ip!r}")
    return f"RACECAST_ADMIN_ADDRESS={ip}\n"


def bind_dropin_content():
    """systemd drop-in: reset the vendor ExecStart, relaunch with --admin-address
    from the EnvironmentFile (default 127.0.0.1). Node-path detection mirrors
    companion-pi's launch.sh."""
    return (
        "[Service]\n"
        f"EnvironmentFile=-{BIND_ENV}\n"
        "ExecStart=\n"
        "ExecStart=/bin/bash -c 'cd /opt/companion && "
        "NODE=$([ -d /opt/companion/node-runtime ] && "
        "echo /opt/companion/node-runtime/bin/node || "
        "echo /opt/companion/node-runtimes/main/bin/node); "
        "exec \"$NODE\" /opt/companion/main.js "
        "--admin-address \"${RACECAST_ADMIN_ADDRESS:-127.0.0.1}\" "
        "--extra-module-path /opt/companion-module-dev'\n"
    )


def bind_helper_content():
    """Root helper (written to HELPER_PATH): validate an IP arg, pin it in the
    EnvironmentFile, restart Companion. The single privileged action behind the
    NOPASSWD rule — it cannot do anything but set a validated bind + restart."""
    return (
        "#!/bin/bash\n"
        "# Managed by racecast (companion enable-control). Sets the Companion admin\n"
        "# bind address and restarts the service. Do not edit by hand.\n"
        "set -euo pipefail\n"
        'ip="${1:-}"\n'
        'if ! printf "%s" "$ip" | grep -Eq '
        "'^([0-9]{1,3}\\.){3}[0-9]{1,3}$|^[0-9A-Fa-f:]+$'; then\n"
        '  echo "racecast-companion-bind: invalid ip: $ip" >&2\n'
        "  exit 2\n"
        "fi\n"
        f'printf "RACECAST_ADMIN_ADDRESS=%s\\n" "$ip" > {BIND_ENV}\n'
        f"exec systemctl restart {UNIT}\n"
    )


def sudoers_dropin_content(user, systemctl_path):
    """NOPASSWD for exactly the bind helper (start path) + `systemctl stop`."""
    return (
        "# Managed by racecast (companion enable-control). Passwordless start (via\n"
        "# the bind helper) + stop of the Companion service for the operator.\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER_PATH}, {systemctl_path} stop {UNIT}\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_companion_linux.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/companion_linux.py tests/test_companion_linux.py
git commit -m "feat(companion): Linux companion-pi content builders + IP validation"
```

---

## Task 2: control_commands + systemd-unit detection

**Files:**
- Modify: `src/scripts/companion_linux.py`
- Test: `tests/test_companion_linux.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_companion_linux.py` (before the `__main__` block):

```python
# --- control_commands --------------------------------------------------------
def t_control_commands_shape():
    c = cl.control_commands("companion")
    assert c["start"] == ["sudo", "-n", cl.HELPER_PATH]      # caller appends the ip
    assert c["quit"] == ["sudo", "-n", "systemctl", "stop", "companion"]
    assert c["running"] == ["systemctl", "is-active", "companion"]


# --- detect_unit -------------------------------------------------------------
def t_detect_unit_none_on_windows_or_macos():
    assert cl.detect_unit(platform="win32") is None
    assert cl.detect_unit(platform="darwin") is None


def t_detect_unit_none_without_systemctl():
    assert cl.detect_unit(platform="linux", which=lambda n: None) is None


def t_detect_unit_via_systemctl_cat():
    class P:
        returncode = 0
    got = cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                         run=lambda *a, **k: P(), exists=lambda p: False)
    assert got == "companion"


def t_detect_unit_via_unit_file_when_cat_fails():
    class P:
        returncode = 1
    got = cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                         run=lambda *a, **k: P(),
                         exists=lambda p: p == cl.SERVICE_UNIT_FILE)
    assert got == "companion"


def t_detect_unit_none_when_absent():
    class P:
        returncode = 1
    assert cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                          run=lambda *a, **k: P(), exists=lambda p: False) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_companion_linux.py`
Expected: FAIL — `AttributeError: module 'companion_linux' has no attribute 'control_commands'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/companion_linux.py`:

```python
def control_commands(unit):
    """Start/quit/running argv for the companion-pi systemd service. `start` is a
    template — the caller appends the validated bind IP (see racecast
    companion_start). `running`/`quit` are complete."""
    return {
        "start": ["sudo", "-n", HELPER_PATH],
        "quit": ["sudo", "-n", "systemctl", "stop", unit],
        "running": ["systemctl", "is-active", unit],
    }


def detect_unit(platform=None, which=None, run=None, exists=None):
    """The companion-pi systemd unit name on this Linux host, or None. None for
    Windows/macOS, for hosts without systemd, and for WSL/Docker/manual installs
    where no local companion.service exists (Companion is on the host)."""
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    exists = os.path.exists if exists is None else exists
    if platform.startswith("win") or platform == "darwin":
        return None
    if not which("systemctl"):
        return None
    try:
        if run(["systemctl", "cat", UNIT], capture_output=True,
               text=True).returncode == 0:
            return UNIT
    except Exception:    # noqa: BLE001 — systemctl missing/odd -> fall through to file check
        pass
    return UNIT if exists(SERVICE_UNIT_FILE) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_companion_linux.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/companion_linux.py tests/test_companion_linux.py
git commit -m "feat(companion): Linux control commands + systemd unit detection"
```

---

## Task 3: is_enabled idempotency check

**Files:**
- Modify: `src/scripts/companion_linux.py`
- Test: `tests/test_companion_linux.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_companion_linux.py`:

```python
# --- is_enabled (idempotency) ------------------------------------------------
def _reader_for(files):
    return lambda path: files.get(path)


def t_is_enabled_true_when_all_match():
    files = {
        cl.DROPIN_CONF: cl.bind_dropin_content(),
        cl.HELPER_PATH: cl.bind_helper_content(),
        cl.SUDOERS_PATH: cl.sudoers_dropin_content("jegr", "/usr/bin/systemctl"),
    }
    assert cl.is_enabled(_reader_for(files), "jegr", "/usr/bin/systemctl") is True


def t_is_enabled_false_when_missing():
    assert cl.is_enabled(_reader_for({}), "jegr", "/usr/bin/systemctl") is False


def t_is_enabled_false_when_sudoers_user_differs():
    files = {
        cl.DROPIN_CONF: cl.bind_dropin_content(),
        cl.HELPER_PATH: cl.bind_helper_content(),
        cl.SUDOERS_PATH: cl.sudoers_dropin_content("other", "/usr/bin/systemctl"),
    }
    assert cl.is_enabled(_reader_for(files), "jegr", "/usr/bin/systemctl") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_companion_linux.py`
Expected: FAIL — `AttributeError: ... 'is_enabled'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/companion_linux.py`:

```python
def is_enabled(read_text, user, systemctl_path):
    """True iff the drop-in, helper, and sudoers files already match the expected
    content for `user`. `read_text(path)` returns the file's text or None."""
    return (read_text(DROPIN_CONF) == bind_dropin_content()
            and read_text(HELPER_PATH) == bind_helper_content()
            and read_text(SUDOERS_PATH) == sudoers_dropin_content(user, systemctl_path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_companion_linux.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/companion_linux.py tests/test_companion_linux.py
git commit -m "feat(companion): Linux enable-control idempotency check"
```

---

## Task 4: enable_control orchestration (install + validate + rollback)

**Files:**
- Modify: `src/scripts/companion_linux.py`
- Test: `tests/test_companion_linux.py`

**Design of `enable_control`:** all privileged actions go through one injected
`run(argv) -> CompletedProcess`. Files are staged to a temp path (injected
`write_temp(content) -> path`) then placed with `sudo install`. The sudoers file
is validated with `sudo visudo -cf <tmp>` before install. After installing, it
sets the bind to 127.0.0.1 via the helper and checks `systemctl is-active`; on
failure it removes the drop-in, reloads, restarts the vendor unit, and reports.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_companion_linux.py`:

```python
# --- enable_control ----------------------------------------------------------
class _FakeRun:
    """Records argv and returns a scripted returncode per matched command."""
    def __init__(self, rc_for=None):
        self.calls = []
        self.rc_for = rc_for or {}
    def __call__(self, argv, **kw):
        self.calls.append(argv)
        rc = 0
        for needle, code in self.rc_for.items():
            if needle in " ".join(argv):
                rc = code
        class P:
            returncode = rc
            stdout = ""
            stderr = ""
        return P()


def _cmds(fake):
    return [" ".join(c) for c in fake.calls]


def t_enable_control_unsupported_returns_nonzero():
    run = _FakeRun()
    rc = cl.enable_control(platform="darwin", run=run, which=lambda n: "/usr/bin/" + n,
                           getuser=lambda: "jegr", read_text=lambda p: None,
                           write_temp=lambda c: "/tmp/x", log=lambda *a: None)
    assert rc != 0
    assert run.calls == []          # nothing privileged attempted off Linux


def t_enable_control_already_enabled_is_noop():
    files = {
        cl.DROPIN_CONF: cl.bind_dropin_content(),
        cl.HELPER_PATH: cl.bind_helper_content(),
        cl.SUDOERS_PATH: cl.sudoers_dropin_content("jegr", "/usr/bin/systemctl"),
    }
    run = _FakeRun()
    rc = cl.enable_control(platform="linux", run=run, which=lambda n: "/usr/bin/" + n,
                           getuser=lambda: "jegr", read_text=lambda p: files.get(p),
                           write_temp=lambda c: "/tmp/x", exists=lambda p: False,
                           log=lambda *a: None)
    assert rc == 0
    # detect_unit may probe systemctl, but NO install/visudo/daemon-reload writes:
    assert not any("install" in c or "visudo" in c for c in _cmds(run))


def t_enable_control_happy_path_installs_and_validates():
    run = _FakeRun()    # all rc 0 incl. systemctl is-active -> active
    rc = cl.enable_control(platform="linux", run=run, which=lambda n: "/usr/bin/" + n,
                           getuser=lambda: "jegr", read_text=lambda p: None,
                           write_temp=lambda c: "/tmp/stage", exists=lambda p: False,
                           log=lambda *a: None)
    cmds = _cmds(run)
    assert any("visudo -cf" in c for c in cmds)                       # validate sudoers
    assert any("install" in c and cl.HELPER_PATH in c for c in cmds)  # helper placed
    assert any("install" in c and cl.DROPIN_CONF in c for c in cmds)  # drop-in placed
    assert any("install" in c and cl.SUDOERS_PATH in c for c in cmds) # sudoers placed
    assert any("daemon-reload" in c for c in cmds)
    assert any("is-active" in c for c in cmds)                        # post-install probe
    assert rc == 0


def t_enable_control_rolls_back_when_service_fails_to_start():
    # is-active returns non-zero -> validation fails -> rollback
    run = _FakeRun(rc_for={"is-active": 3})
    rc = cl.enable_control(platform="linux", run=run, which=lambda n: "/usr/bin/" + n,
                           getuser=lambda: "jegr", read_text=lambda p: None,
                           write_temp=lambda c: "/tmp/stage", exists=lambda p: False,
                           log=lambda *a: None)
    cmds = _cmds(run)
    assert any("rm" in c and cl.DROPIN_CONF in c for c in cmds)   # drop-in removed
    assert rc != 0


def t_enable_control_refuses_2x_layout():
    run = _FakeRun()
    rc = cl.enable_control(platform="linux", run=run, which=lambda n: "/usr/bin/" + n,
                           getuser=lambda: "jegr", read_text=lambda p: None,
                           write_temp=lambda c: "/tmp/x",
                           exists=lambda p: p == cl.LEGACY_2X_DIR, log=lambda *a: None)
    assert rc != 0
    assert not any("install" in c for c in _cmds(run))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_companion_linux.py`
Expected: FAIL — `AttributeError: ... 'enable_control'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/companion_linux.py`:

```python
def _default_read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _default_write_temp(content):
    fd, path = tempfile.mkstemp(prefix="racecast-companion-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _install_file(run, write_temp, content, dest, mode):
    """Stage `content` to a temp file and place it at `dest` (root) with `mode`."""
    tmp = write_temp(content)
    return run(["sudo", "install", "-m", mode, "-o", "root", "-g", "root", tmp, dest])


def enable_control(platform=None, run=None, which=None, getuser=None,
                   read_text=None, write_temp=None, exists=None, log=print):
    """Idempotently install the systemd bind drop-in, the root bind helper, and a
    visudo-validated NOPASSWD sudoers rule, then validate the service still starts
    (rolling back the drop-in if not). Returns 0 on success, non-zero otherwise.

    All privileged actions run through `run(argv)`; file staging via `write_temp`.
    These seams keep the command sequence unit-testable without root."""
    platform = sys.platform if platform is None else platform
    run = subprocess.run if run is None else run
    which = shutil.which if which is None else which
    getuser = getpass.getuser if getuser is None else getuser
    read_text = _default_read_text if read_text is None else read_text
    write_temp = _default_write_temp if write_temp is None else write_temp
    exists = os.path.exists if exists is None else exists

    unit = detect_unit(platform=platform, which=which, run=run, exists=exists)
    if not unit:
        log("companion enable-control: no companion.service found on this Linux host "
            "(WSL/host or manual install) — nothing to enable.")
        return 1
    if exists(LEGACY_2X_DIR):
        log("companion enable-control: companion-pi 2.x layout detected "
            f"({LEGACY_2X_DIR}); unsupported. Update Companion to 3.x first.")
        return 1

    user = getuser()
    systemctl = which("systemctl") or "/usr/bin/systemctl"
    if is_enabled(read_text, user, systemctl):
        log("companion enable-control: already enabled.")
        return 0

    # Validate the sudoers content before touching anything live.
    sudoers = sudoers_dropin_content(user, systemctl)
    tmp_sudoers = write_temp(sudoers)
    if run(["sudo", "visudo", "-cf", tmp_sudoers]).returncode != 0:
        log("companion enable-control: sudoers validation failed; aborting (no changes).")
        return 1

    run(["sudo", "mkdir", "-p", DROPIN_DIR])
    _install_file(run, write_temp, bind_helper_content(), HELPER_PATH, "0755")
    _install_file(run, write_temp, bind_dropin_content(), DROPIN_CONF, "0644")
    _install_file(run, write_temp, sudoers, SUDOERS_PATH, "0440")
    run(["sudo", "systemctl", "daemon-reload"])

    # Validate: apply a safe local bind and confirm the unit comes up.
    run(["sudo", "-n", HELPER_PATH, "127.0.0.1"])
    if run(["systemctl", "is-active", unit], capture_output=True,
           text=True).returncode != 0:
        log("companion enable-control: service did not start with the new drop-in; "
            "rolling back.")
        run(["sudo", "rm", "-f", DROPIN_CONF])
        run(["sudo", "systemctl", "daemon-reload"])
        run(["sudo", "systemctl", "restart", unit])
        return 1

    log("companion enable-control: enabled. Start/Stop now works without a password.")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_companion_linux.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/companion_linux.py tests/test_companion_linux.py
git commit -m "feat(companion): Linux enable-control orchestration with rollback"
```

---

## Task 5: racecast `_companion_cmds` Linux branch + unsupported message

**Files:**
- Modify: `src/racecast.py:1228-1237` (`_companion_cmds`, `_companion_unsupported_msg`)
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py` (before any `__main__`/runner block):

```python
def t_companion_cmds_linux_uses_systemd_when_unit_present(monkey=None):
    import companion_linux as cl
    orig_platform = m.sys.platform
    orig_detect = cl.detect_unit
    try:
        m.sys.platform = "linux"
        cl.detect_unit = lambda *a, **k: "companion"
        cmds = m._companion_cmds(m._companion())
        assert cmds["running"] == ["systemctl", "is-active", "companion"]
    finally:
        m.sys.platform = orig_platform
        cl.detect_unit = orig_detect


def t_companion_cmds_linux_none_without_unit():
    import companion_linux as cl
    orig_platform = m.sys.platform
    orig_detect = cl.detect_unit
    try:
        m.sys.platform = "linux"
        cl.detect_unit = lambda *a, **k: None
        assert m._companion_cmds(m._companion()) is None
    finally:
        m.sys.platform = orig_platform
        cl.detect_unit = orig_detect


def t_unsupported_msg_linux_is_no_service_wording():
    orig = m.sys.platform
    try:
        m.sys.platform = "linux"
        msg = m._companion_unsupported_msg()
        assert "no companion.service" in msg.lower()
    finally:
        m.sys.platform = orig
```

Note: `companion_linux` must be importable from the test. `test_racecast.py` loads
`racecast.py` which puts `src/scripts` on `sys.path`, so `import companion_linux`
works after `racecast` has loaded. If not, add at the top of the test file:
`import sys, os; sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — current `_companion_cmds` returns `None` on Linux (no systemd dict), and `_companion_unsupported_msg` still says "automated control supports Windows and macOS".

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`, replace `_companion_cmds` and the Linux branch of `_companion_unsupported_msg` (lines ~1228-1237):

```python
def _companion_cmds(cc):
    if sys.platform.startswith("win"):
        return cc.companion_control_commands(sys.platform, cc.find_companion_exe())
    if sys.platform == "darwin":
        return cc.companion_control_commands(sys.platform)
    import companion_linux as cl
    unit = cl.detect_unit()
    return cl.control_commands(unit) if unit else None

def _companion_unsupported_msg():
    if sys.platform.startswith("win"):
        return ("companion: Companion.exe not found. Set RACECAST_COMPANION_EXE in .env "
                "to its full path and retry.")
    if sys.platform == "darwin":
        return "companion: Companion control is unavailable on this macOS setup."
    return ("companion: no companion.service found (WSL/host or manual install) — "
            "run and bind Companion yourself.")
```

Note: the previous `_companion_cmds` computed `exe` only on Windows via
`cc.find_companion_exe() if sys.platform.startswith("win") else None`; the new
version preserves that (Windows passes the discovered exe, macOS passes none).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(companion): route Linux companion control through systemd"
```

---

## Task 6: racecast `companion_start`/`companion_stop` Linux branches

**Files:**
- Modify: `src/racecast.py:1250-1317` (`companion_start`, `companion_stop`)
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py`:

```python
def _linux_companion_env(detect="companion", helper_exists=True, ts="100.64.1.2",
                         run_calls=None):
    """Set up monkeypatches for the Linux companion_start/stop branch. Returns a
    teardown thunk. `run_calls` (a list) collects argv passed to subprocess.run."""
    import companion_linux as cl
    saved = {
        "platform": m.sys.platform, "detect": cl.detect_unit,
        "ts": m._tailscale_ip, "run": m.subprocess.run,
        "exists": os.path.exists, "running": m._companion_running,
    }
    m.sys.platform = "linux"
    cl.detect_unit = lambda *a, **k: detect
    m._tailscale_ip = lambda: ts
    m._companion_running = lambda cc: False

    class P:
        returncode = 0
    def fake_run(argv, **kw):
        (run_calls if run_calls is not None else []).append(argv)
        return P()
    m.subprocess.run = fake_run

    def teardown():
        m.sys.platform = saved["platform"]
        cl.detect_unit = saved["detect"]
        m._tailscale_ip = saved["ts"]
        m.subprocess.run = saved["run"]
        m._companion_running = saved["running"]
    return teardown, cl


def t_companion_start_linux_calls_helper_with_tailscale_ip():
    calls = []
    teardown, cl = _linux_companion_env(ts="100.64.1.2", run_calls=calls)
    try:
        orig_exists = m.os.path.exists
        m.os.path.exists = lambda p: True   # helper present (enable-control done)
        try:
            m.companion_start(["auto"])
        finally:
            m.os.path.exists = orig_exists
    finally:
        teardown()
    assert ["sudo", "-n", cl.HELPER_PATH, "100.64.1.2"] in calls


def t_companion_start_linux_falls_back_to_localhost_without_tailscale():
    calls = []
    teardown, cl = _linux_companion_env(ts=None, run_calls=calls)
    try:
        orig_exists = m.os.path.exists
        m.os.path.exists = lambda p: True
        try:
            m.companion_start(["auto"])
        finally:
            m.os.path.exists = orig_exists
    finally:
        teardown()
    assert ["sudo", "-n", cl.HELPER_PATH, "127.0.0.1"] in calls


def t_companion_start_linux_guides_when_not_enabled():
    calls = []
    teardown, cl = _linux_companion_env(run_calls=calls)
    try:
        orig_exists = m.os.path.exists
        m.os.path.exists = lambda p: False  # helper absent -> enable-control needed
        raised = False
        try:
            try:
                m.companion_start(["auto"])
            except SystemExit:
                raised = True
        finally:
            m.os.path.exists = orig_exists
    finally:
        teardown()
    # No helper call attempted; the operator is told to run enable-control.
    assert not any(cl.HELPER_PATH in " ".join(c) for c in calls)
    assert raised


def t_companion_stop_linux_runs_systemctl_stop():
    calls = []
    teardown, cl = _linux_companion_env(run_calls=calls)
    try:
        m._companion_running = lambda cc: True
        m.companion_stop([])
    finally:
        teardown()
    assert ["sudo", "-n", "systemctl", "stop", "companion"] in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `companion_start`/`companion_stop` have no Linux-systemd branch yet (they fall into the macOS/Windows config.json path or sys.exit on unsupported).

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`, add a Linux-systemd branch at the TOP of `companion_start` and `companion_stop`. Insert into `companion_start` immediately after `cc = _companion()` (line ~1251):

```python
def companion_start(rest):
    cc = _companion()
    import companion_linux as cl
    if not sys.platform.startswith("win") and sys.platform != "darwin":
        unit = cl.detect_unit()
        if unit:
            return _companion_start_linux(cc, cl, unit, rest)
    cmds = _companion_cmds(cc)
    if cmds is None:
        sys.exit(_companion_unsupported_msg())
    # ... existing macOS/Windows bind-editing body unchanged ...
```

Add the helper functions (place them just above `companion_start`):

```python
def _companion_start_linux(cc, cl, unit, rest):
    """Linux companion-pi: set the bind via the root helper, then it restarts the
    service. No config.json editing (headless ignores it; companion-pi binds via
    the --admin-address flag we inject through the systemd drop-in)."""
    if not os.path.exists(cl.HELPER_PATH):
        sys.exit("companion: control not set up yet — run `racecast companion "
                 "enable-control` once (installs the systemd bind helper + sudoers).")
    bind_arg = rest[0] if rest else "auto"
    ts = _tailscale_ip()
    ip = cc.desired_bind_ip(bind_arg, ts)
    if bind_arg == "auto" and not ts:
        print("companion: no Tailscale IP — binding 127.0.0.1 (this machine only).")
    rc = subprocess.run(["sudo", "-n", cl.HELPER_PATH, ip]).returncode
    if rc != 0:
        sys.exit("companion: passwordless start failed. Run `racecast companion "
                 "enable-control`, or start manually: `sudo systemctl start companion`.")
    print(f"companion: started, admin/tablet bound to {ip}:8000.")
    print("  Admin GUI shares this port — restrict who reaches it with a Tailscale ACL.")


def _companion_stop_linux(cc, cl, unit):
    if not _companion_running(cc):
        print("companion is not running.")
        return
    rc = subprocess.run(["sudo", "-n", "systemctl", "stop", unit]).returncode
    if rc != 0:
        sys.exit("companion: passwordless stop failed. Run `racecast companion "
                 "enable-control`, or stop manually: `sudo systemctl stop companion`.")
    print("companion stopped.")
```

Insert into `companion_stop` immediately after `cc = _companion()` (line ~1301):

```python
def companion_stop(rest):
    cc = _companion()
    import companion_linux as cl
    if not sys.platform.startswith("win") and sys.platform != "darwin":
        unit = cl.detect_unit()
        if unit:
            return _companion_stop_linux(cc, cl, unit)
    cmds = _companion_cmds(cc)
    if cmds is None:
        sys.exit(_companion_unsupported_msg())
    # ... existing macOS/Windows body unchanged ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(companion): Linux start/stop via systemd bind helper"
```

---

## Task 7: `companion enable-control` CLI verb

**Files:**
- Modify: `src/racecast.py:648-650` (`EXTRA_VERBS`), `:1883-1893` (`DISPATCH`), `:8` (usage), and add `companion_enable_control`
- Test: `tests/test_racecast.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py`:

```python
def t_companion_enable_control_routes():
    assert m.route(["companion", "enable-control"])["verb"] == "enable-control"


def t_companion_enable_control_is_dispatchable():
    assert ("companion", "enable-control") in m.DISPATCH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `enable-control` is not in `EXTRA_VERBS["companion"]` (route raises) and not in `DISPATCH`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`:

1. Extend `EXTRA_VERBS` (line ~648):

```python
EXTRA_VERBS = {
    "relay": ("run", "open-panel", "open-hud", "open-status"),
    "companion": ("open-tablet", "open-admin", "enable-control"),
}
```
(Keep the existing `relay` entry exactly as-is — only append `"enable-control"` to the companion tuple.)

2. Add the command function (near the other companion commands, e.g. after `companion_restart`):

```python
def companion_enable_control(rest):
    import companion_linux as cl
    raise SystemExit(cl.enable_control())
```

3. Register in `DISPATCH` (in the companion block, line ~1893):

```python
    ("companion", "enable-control"): companion_enable_control,
```

4. Update the usage banner (line 8):

```python
#  racecast companion start|stop|restart|status|logs|enable-control|open-tablet|open-admin
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(companion): add `racecast companion enable-control` verb"
```

---

## Task 8: install-apps auto-invokes enable-control after Linux Companion install

**Files:**
- Modify: `src/scripts/install_apps.py:481-531` (`_install_linux`)
- Test: `tests/test_install_apps.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install_apps.py` (before the `__main__` block):

```python
def t_should_enable_companion_control_only_on_companion_linux():
    # decision is pure: companion present in the just-installed set, no failures
    assert m.should_enable_companion_control(["companion"], failed=[]) is True
    assert m.should_enable_companion_control(["obs"], failed=[]) is False
    assert m.should_enable_companion_control(["companion"], failed=["companion ..."]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_install_apps.py`
Expected: FAIL — `AttributeError: ... 'should_enable_companion_control'`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/install_apps.py`, add the pure decision helper (near `linux_install_steps`):

```python
def should_enable_companion_control(installed, failed):
    """True iff Companion was just installed on Linux without a failed step, so
    `racecast companion enable-control` should run to wire up the Start/Stop button."""
    return "companion" in installed and not failed
```

Then in `_install_linux`, after the `if "companion" in missing:` notice (line ~526), before the `if failed:` block:

```python
    if should_enable_companion_control(missing, failed):
        print("Enabling passwordless Companion start/stop (systemd bind helper + sudoers)…")
        try:
            import companion_linux as cl
            cl.enable_control()
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! enable-control skipped: {exc} "
                  "(run `racecast companion enable-control` later).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_install_apps.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/install_apps.py tests/test_install_apps.py
git commit -m "feat(install-apps): enable Companion control after Linux install"
```

---

## Task 9: Docs + full suite + build verify

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `tools/run-tests.py` (if it lists test files explicitly)

- [ ] **Step 1: Register the new test file with the suite**

Check whether `tools/run-tests.py` enumerates test files explicitly or globs `tests/test_*.py`.

Run: `grep -n "test_" tools/run-tests.py | head`

If it lists files explicitly, add `test_companion_linux.py` in the same style next to `test_companion.py`. If it globs, no change is needed.

- [ ] **Step 2: Update CLAUDE.md**

In the Companion sections (the "Companion remote-access helpers" block and the "Standalone binary" per-OS control note), replace the blanket "Linux manual by design" with the new behavior. Add after the existing macOS/Windows description:

```markdown
On native Linux, Companion is the companion-pi **systemd service**. `racecast
companion start/stop` control it via `systemctl` (start goes through a root bind
helper that pins `--admin-address` to the Tailscale IP, or `127.0.0.1` when the
tailnet is down — never `0.0.0.0`, matching the relay/`--bind auto` rule). This
needs a one-time `racecast companion enable-control` (installs a systemd
`ExecStart` drop-in, the `/usr/local/sbin/racecast-companion-bind` helper, and a
visudo-validated NOPASSWD sudoers rule for the start helper + `systemctl stop`).
`install-apps` runs it after a Linux Companion install. The `ExecStart` override
reproduces companion-pi's node-launch line, so re-run `enable-control` after a
structural `sudo companion-update`. Setups without a local `companion.service`
(WSL/Docker on the host, manual AppImage) keep the manual path. Logic:
`src/scripts/companion_linux.py`, tests `tests/test_companion_linux.py`.
```

- [ ] **Step 3: Update README.md**

Add the new verb to the companion command list:

```bash
python3 src/racecast.py companion enable-control  # Linux only: one-time setup so the Start/Stop button (and `companion start/stop`) can control the companion-pi systemd service without a password
```

- [ ] **Step 4: Run the whole suite**

Run: `python3 tools/run-tests.py`
Expected: every test file prints `ALL PASS` / the suite reports success (including `test_companion_linux.py`, `test_racecast.py`, `test_install_apps.py`).

- [ ] **Step 5: Lint everything**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 6: Build verify**

Run: `python3 tools/build.py`
Expected: build succeeds; the verify step passes (tokenization, blanked password, no secrets, preflight present, **no shell scripts shipped** — confirms `companion_linux.py` ships no `.sh`).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md README.md tools/run-tests.py
git commit -m "docs(companion): document Linux companion-pi control + enable-control"
```

---

## Self-Review

**Spec coverage:**
- Gate (Linux + local companion.service) → `detect_unit` (Task 2), used by `_companion_cmds` (Task 5) and the start/stop branches (Task 6). ✓
- Dynamic bind via `desired_bind_ip` (Tailscale or 127.0.0.1, never 0.0.0.0) → `_companion_start_linux` (Task 6). ✓
- systemd `ExecStart` drop-in + EnvironmentFile → `bind_dropin_content` (Task 1), installed by `enable_control` (Task 4). ✓
- Privileged bind helper with IP validation → `bind_helper_content` + `is_valid_bind_ip` (Task 1). ✓
- visudo-validated NOPASSWD sudoers (helper + systemctl stop) → `sudoers_dropin_content` (Task 1), `enable_control` visudo gate (Task 4). ✓
- Validation with rollback → `enable_control` is-active probe + rollback (Task 4). ✓
- Idempotency → `is_enabled` (Task 3) used in `enable_control` (Task 4). ✓
- `companion status`/readiness/`event start` step 5 follow automatically from `_companion_cmds` returning a dict (Task 5) — no extra code; `_companion_running` uses the `running` command + existing `parse_running` (rc==0). ✓
- `enable-control` CLI verb (Task 7); install-apps auto-invoke (Task 8). ✓
- 2.x refusal, no-service message → `enable_control` (Task 4), `_companion_unsupported_msg` (Task 5). ✓
- Docs (Task 9). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type/name consistency:** `detect_unit`, `control_commands`, `is_valid_bind_ip`, `bind_env_content`, `bind_dropin_content`, `bind_helper_content`, `sudoers_dropin_content`, `is_enabled`, `enable_control`, `should_enable_companion_control`, `_companion_start_linux`, `_companion_stop_linux`, `companion_enable_control` are referenced consistently across tasks. Constants `UNIT`, `DROPIN_DIR`, `DROPIN_CONF`, `BIND_ENV`, `HELPER_PATH`, `SUDOERS_PATH`, `SERVICE_UNIT_FILE`, `LEGACY_2X_DIR` defined in Task 1/2 and reused. ✓

**Note for the implementer:** `_companion_running` (racecast.py) runs `_companion_cmds(cc)["running"]` then `cc.parse_running(sys.platform, rc, stdout)`. On Linux `running` is `systemctl is-active companion`; `parse_running` returns `rc == 0` for non-Windows, which matches `is-active` (0 ⟺ active). No change to `parse_running` or `companion_common.py` is required.
