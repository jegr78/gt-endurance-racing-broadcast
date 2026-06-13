#!/usr/bin/env python3
"""Stdlib checks for the spawned-service daemon helper. Run: python3 tests/test_services.py"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import services as sv


def t_read_pid_valid(tmp):
    p = os.path.join(tmp, "x.pid")
    with open(p, "w") as fh:
        fh.write("4321\n")
    assert sv.read_pid(p) == 4321


def t_read_pid_missing_or_garbage(tmp):
    assert sv.read_pid(os.path.join(tmp, "nope.pid")) is None
    p = os.path.join(tmp, "g.pid")
    with open(p, "w") as fh:
        fh.write("not-a-pid")
    assert sv.read_pid(p) is None


def t_pid_alive_self_and_dead():
    assert sv.pid_alive(os.getpid()) is True
    assert sv.pid_alive(0) is False
    assert sv.pid_alive(2_000_000_000) is False   # implausibly high → not alive


def t_status_line_running_and_stopped():
    assert sv.status_line("relay", 99, True).startswith("relay")
    assert "RUNNING (pid 99)" in sv.status_line("relay", 99, True)
    assert "stopped" in sv.status_line("relay", None, False)


def t_start_detached_then_stop(tmp):
    log = os.path.join(tmp, "logs", "svc.log")
    pidf = os.path.join(tmp, "svc.pid")
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    pid = sv.start_detached(argv, log, pidf)
    assert sv.pid_alive(pid) is True
    assert sv.read_pid(pidf) == pid
    assert sv.stop_pid(pid, pidf, timeout=5) is True
    assert sv.pid_alive(pid) is False
    assert not os.path.exists(pidf)   # pid file removed on stop


def t_looks_like_relay():
    # frozen binary running `relay run`
    assert sv.looks_like_relay("/opt/racecast/racecast relay run --runtime /x")
    # repo mode: python running the relay script
    assert sv.looks_like_relay("python3 /a/src/relay/racecast-feeds.py --runtime /x")
    # Windows tasklist gives only the image name (no argv)
    assert sv.looks_like_relay('"racecast.exe","1234","Console"', windows=True)
    assert sv.looks_like_relay('"python.exe","1234","Console"', windows=True)
    # unrelated processes must NOT match
    assert not sv.looks_like_relay("/usr/bin/vim notes.txt")
    assert not sv.looks_like_relay('"notepad.exe","1234","Console"', windows=True)
    assert not sv.looks_like_relay("")


def t_stop_pid_skips_foreign_pid(tmp):
    # A stale/recycled PID file naming an unrelated live process must NOT be
    # killed: stop_pid drops the pid file and reports gone without signalling.
    pidf = os.path.join(tmp, "relay.pid")
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    pid = sv.start_detached(argv, os.path.join(tmp, "l.log"), pidf)
    try:
        assert sv.pid_alive(pid) is True
        assert sv.stop_pid(pid, pidf, timeout=5, is_target=lambda _p: False) is True
        assert sv.pid_alive(pid) is True          # NOT killed — it wasn't ours
        assert not os.path.exists(pidf)           # stale pid file cleared
    finally:
        sv.stop_pid(pid, pidf, timeout=5)         # real cleanup


def t_stop_pid_kills_verified_target(tmp):
    pidf = os.path.join(tmp, "relay2.pid")
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    pid = sv.start_detached(argv, os.path.join(tmp, "l2.log"), pidf)
    assert sv.pid_alive(pid) is True
    assert sv.stop_pid(pid, pidf, timeout=5, is_target=lambda _p: True) is True
    assert sv.pid_alive(pid) is False


def t_spawn_kwargs_per_os():
    assert sv.spawn_kwargs("posix") == {"start_new_session": True}
    # Windows daemon spawn: CREATE_NO_WINDOW (0x08000000), NOT DETACHED_PROCESS.
    # A frozen onefile relay is a two-process tree (bootloader -> app); under
    # DETACHED_PROCESS the bootloader has NO console, so the inner app process is
    # given a fresh VISIBLE console that stays open for the whole event. A hidden
    # console (CREATE_NO_WINDOW) is inherited by the inner process instead.
    # CREATE_NEW_PROCESS_GROUP keeps Ctrl+C isolation; the child still outlives us.
    assert sv.spawn_kwargs("nt") == {"creationflags": 0x08000000 | 0x00000200}
    assert sv.spawn_kwargs("java") == {}


def t_no_window_kwargs_per_os():
    # CREATE_NO_WINDOW only on Windows; a no-op (empty kwargs) everywhere else so
    # the same call site stays cross-platform.
    assert sv.no_window_kwargs("nt") == {"creationflags": 0x08000000}
    assert sv.no_window_kwargs("posix") == {}
    assert sv.no_window_kwargs("java") == {}


def t_stop_commands_per_os():
    assert sv.stop_commands("posix", 123, force=False) is None
    assert sv.stop_commands("posix", 123, force=True) is None
    assert sv.stop_commands("nt", 123, force=False) == ["taskkill", "/PID", "123"]
    assert sv.stop_commands("nt", 123, force=True) == \
        ["taskkill", "/F", "/T", "/PID", "123"]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                import inspect
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
