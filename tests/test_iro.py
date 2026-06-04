#!/usr/bin/env python3
"""Stdlib checks for the iro dispatcher routing. Run: python3 tests/test_iro.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("iro", os.path.join(ROOT, "src", "iro.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_service_start():
    assert m.route(["relay", "start"]) == \
        {"kind": "service", "command": "relay", "verb": "start", "rest": []}


def t_relay_run_forwards_rest():
    r = m.route(["relay", "run", "--no-pov"])
    assert r["kind"] == "service" and r["verb"] == "run" and r["rest"] == ["--no-pov"]


def t_companion_and_streams_verbs():
    assert m.route(["companion", "logs"])["verb"] == "logs"
    assert m.route(["streams", "restart"])["verb"] == "restart"


def t_aggregate_status():
    assert m.route(["status"]) == {"kind": "aggregate"}


def t_oneshot_with_args():
    assert m.route(["cookies", "chrome"]) == \
        {"kind": "oneshot", "command": "cookies", "rest": ["chrome"]}
    assert m.route(["preflight"])["command"] == "preflight"


def t_help_when_empty():
    assert m.route([])["kind"] == "help"


def t_run_only_valid_for_relay():
    _raises(lambda: m.route(["companion", "run"]))


def t_bad_verb_and_unknown_command_raise():
    _raises(lambda: m.route(["relay", "bogus"]))
    _raises(lambda: m.route(["nonsense"]))


def t_relay_open_verbs():
    for verb in ("open-panel", "open-hud", "open-status"):
        assert m.route(["relay", verb])["verb"] == verb


def t_companion_open_verbs():
    for verb in ("open-tablet", "open-admin"):
        assert m.route(["companion", verb])["verb"] == verb


def t_open_verbs_are_not_cross_service():
    _raises(lambda: m.route(["companion", "open-panel"]))
    _raises(lambda: m.route(["relay", "open-tablet"]))
    _raises(lambda: m.route(["streams", "open-hud"]))


def t_http_url():
    assert m._http_url("127.0.0.1", 8088, "/panel") == "http://127.0.0.1:8088/panel"
    assert m._http_url("100.81.234.4", 8000, "/tablet") == "http://100.81.234.4:8000/tablet"


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


def t_run_module_exit_codes():
    import contextlib, io, sys as _sys, tempfile
    with tempfile.TemporaryDirectory() as td:
        script = os.path.join(td, "fake-tool.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("import sys\n"
                     "def main():\n"
                     "    if sys.argv[1:] == ['--fail']:\n"
                     "        return 3\n"
                     "    if sys.argv[1:] == ['--exit-str']:\n"
                     "        sys.exit('boom guide')\n"
                     "    return None\n")
        before = list(_sys.argv)
        assert m._run_module(script, ["--fail"]) == 3
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert m._run_module(script, ["--exit-str"]) == 1
        assert "boom guide" in err.getvalue()  # sys.exit(str) must reach stderr
        assert m._run_module(script, []) == 0
        assert _sys.argv == before


def t_run_module_missing_main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        script = os.path.join(td, "no-main.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("X = 1\n")
        assert m._run_module(script, []) == 1


def t_streams_run_feed_hidden():
    assert m.route(["streams", "run-feed", "UC1", "53001"])["verb"] == "run-feed"
    try:
        m.route(["streams", "bogus"])
    except ValueError as e:
        assert "run-feed" not in str(e)  # hidden verb is not advertised
    else:
        raise AssertionError("expected ValueError")


def t_install_tools_oneshot():
    assert m.route(["install-tools"]) == \
        {"kind": "oneshot", "command": "install-tools", "rest": []}


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


def t_install_apps_oneshot():
    assert m.route(["install-apps"]) == \
        {"kind": "oneshot", "command": "install-apps", "rest": []}


def _raises(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
