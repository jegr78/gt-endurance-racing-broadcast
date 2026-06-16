#!/usr/bin/env python3
"""Stdlib checks for the Discord-web/browser capture decision helpers.
Run: python3 tests/test_discord_web.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dw = _load("discord_web", "src", "scripts", "discord_web.py")

def t_use_web_override_wins():
    # 1/true/on -> web even on a non-Linux platform; 0/off -> never web even on Linux.
    for val in ("1", "true", "on", "YES"):
        assert dw.use_web("darwin", {"RACECAST_DISCORD_WEB": val}) is True
    for val in ("0", "false", "off", "no"):
        assert dw.use_web("linux", {"RACECAST_DISCORD_WEB": val},
                          native_installed_fn=lambda p: False) is False


def t_use_web_auto_linux_depends_on_native():
    # auto (no override): Linux + no native Discord -> web; Linux + native -> not web.
    assert dw.use_web("linux", {}, native_installed_fn=lambda p: False) is True
    assert dw.use_web("linux", {}, native_installed_fn=lambda p: True) is False


def t_use_web_non_linux_never_auto():
    assert dw.use_web("darwin", {}, native_installed_fn=lambda p: False) is False
    assert dw.use_web("win32", {}, native_installed_fn=lambda p: False) is False


def t_native_installed_non_linux_true():
    assert dw.native_installed("darwin") is True
    assert dw.native_installed("win32") is True


def t_native_installed_linux_probes_path_and_binary():
    # binary on PATH -> True
    assert dw.native_installed("linux", which=lambda n: "/usr/bin/discord"
                               if n == "discord" else None,
                               exists=lambda p: False) is True
    # no binary, but a known install path exists -> True
    assert dw.native_installed("linux", which=lambda n: None,
                               exists=lambda p: p == "/usr/share/discord") is True
    # neither -> False (the ARM64 case)
    assert dw.native_installed("linux", which=lambda n: None,
                               exists=lambda p: False) is False


def t_resolve_browser_override_then_running_then_default():
    assert dw.resolve_browser({"RACECAST_DISCORD_WEB_BROWSER": "Chromium"}) == "Chromium"
    assert dw.resolve_browser({}, running="Firefox") == "Firefox"
    assert dw.resolve_browser({}) == dw.DEFAULT_BROWSER == "Firefox"


def t_detect_running_browser_matches_first_hit():
    class R:
        def __init__(self, rc): self.returncode = rc
    # firefox running -> "Firefox"
    assert dw.detect_running_browser(
        run=lambda argv, **kw: R(0 if argv[-1] == "firefox" else 1)) == "Firefox"
    # nothing running -> None
    assert dw.detect_running_browser(run=lambda argv, **kw: R(1)) is None
    # a probe that raises (e.g. pgrep missing) is skipped -> None
    def boom(argv, **kw):
        raise OSError("pgrep not found")
    assert dw.detect_running_browser(run=boom) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
