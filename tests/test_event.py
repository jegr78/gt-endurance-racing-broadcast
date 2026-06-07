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
    assert m.launch_command("companion", "linux") is None   # not a PATH-launched app


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
    assert m.required_graphics(gg, None) == []
    # unsafe labels (path separators) are dropped, never become filenames
    rows_bad = [["../evil", "https://drive.google.com/file/d/CCC3/view"]]
    assert m.required_graphics(gg, rows_bad) == []


def t_required_media_from_assets_rows():
    gm = _load_relay("get-media.py")
    rows = [["Intro Video", "https://youtu.be/xyz"]]
    assert m.required_media(gm, rows) == ["intro.mp4"]
    # No media rows in the sheet -> require both (the OBS scenes reference both).
    assert m.required_media(gm, [["Overlay", "u"]]) == ["intro.mp4", "outro.mp4"]
    assert m.required_media(gm, None) == ["intro.mp4", "outro.mp4"]


def t_fetch_assets_rows_handles_failure():
    gg = _load_relay("get-graphics.py")
    assert m.fetch_assets_rows(gg, None) is None          # no sheet id
    boom = type("GG", (), {"fetch_assets_csv":
                           staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("net")))})
    assert m.fetch_assets_rows(boom, "SHEET") is None     # fetch failure -> None
    ok = type("GG", (), {"fetch_assets_csv": staticmethod(lambda *a, **k: "A,B\nC,D\n")})
    assert m.fetch_assets_rows(ok, "SHEET") == [["A", "B"], ["C", "D"]]


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
    assert m.classify_env("sheet", "http://push").level == "PASS"
    r = m.classify_env("sheet", "")          # push URL optional -> WARN, not FAIL
    assert r.level == "WARN" and "IRO_SHEET_PUSH_URL" in r.detail
    r = m.classify_env("", "http://push")
    assert r.level == "FAIL" and "IRO_SHEET_ID" in r.detail


def t_go_live_reminder():
    assert m.GO_LIVE_REMINDER.level == "INFO"
    assert "refresh" in m.GO_LIVE_REMINDER.detail.lower()
    assert "HUD" in m.GO_LIVE_REMINDER.detail


def t_wait_until_up():
    elapsed = {"n": 0}
    clock = lambda: elapsed["n"]            # fake monotonic: sleeps advance it
    def sleep(secs):
        elapsed["n"] += secs
    # all up immediately -> returns without sleeping
    st = m.wait_until_up({"relay": lambda: True}, timeout=60, interval=5,
                         clock=clock, sleep=sleep)
    assert st == {"relay": True} and elapsed["n"] == 0
    # comes up on the third poll -> exactly two sleeps
    polls = {"k": 0}
    def flaky():
        polls["k"] += 1
        return polls["k"] >= 3
    st = m.wait_until_up({"obs": flaky}, timeout=60, interval=5,
                         clock=clock, sleep=sleep)
    assert st == {"obs": True} and elapsed["n"] == 10
    # never up -> stops at the deadline, reports the loser as False
    elapsed["n"] = 0
    st = m.wait_until_up({"relay": lambda: False, "obs": lambda: True},
                         timeout=60, interval=5, clock=clock, sleep=sleep)
    assert st == {"relay": False, "obs": True}
    assert elapsed["n"] == 60
    # a probe that turned True is cached, not re-polled
    polls["k"] = 0
    elapsed["n"] = 0
    m.wait_until_up({"obs": flaky, "relay": lambda: False},
                    timeout=10, interval=5, clock=clock, sleep=sleep)
    assert polls["k"] == 3                  # True after 3 polls, then cached


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
