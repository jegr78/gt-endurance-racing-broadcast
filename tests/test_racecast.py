#!/usr/bin/env python3
"""Stdlib checks for the racecast dispatcher routing. Run: python3 tests/test_racecast.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("racecast", os.path.join(ROOT, "src", "racecast.py"))
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


def t_tailscale_verbs():
    for verb in ("up", "down", "status"):
        assert m.route(["tailscale", verb]) == \
            {"kind": "service", "command": "tailscale", "verb": verb, "rest": []}


def t_tailscale_bad_verb_raises():
    _raises(lambda: m.route(["tailscale"]))
    _raises(lambda: m.route(["tailscale", "restart"]))


def t_tailscale_login_hint_linux_points_to_cli_not_a_gui_app():
    # Linux has no Tailscale GUI app — the first sign-in is `sudo tailscale up`
    # + the printed browser URL, NOT "open the app". Regression for the misleading
    # "open the Tailscale app and sign in" on Linux. (Whole-string equality, not a
    # substring `in` check — the latter trips CodeQL's URL-sanitization query.)
    hint = m._tailscale_login_hint("linux")
    assert hint == ("run `sudo tailscale up` in a terminal, then open the printed "
                    "https://login.tailscale.com/… URL in a browser to sign in")
    assert "sudo tailscale up" in hint        # the actual command to run (not a URL)
    assert "app" not in hint.lower()          # never tells Linux users to "open the app"


def t_tailscale_login_hint_desktop_uses_the_gui_app():
    for plat in ("darwin", "win32"):
        assert m._tailscale_login_hint(plat) == "open the Tailscale app and sign in"


def t_tailscale_operator_hint_linux_points_to_one_time_operator_fix():
    # `tailscale up/down` need root on Linux ("prefs write access denied"); the
    # durable fix that makes the Control Center buttons work without sudo is the
    # one-time `tailscale set --operator`.
    hint = m._tailscale_operator_hint("down", "linux")
    assert "--operator=$USER" in hint
    assert "sudo tailscale down" in hint        # immediate workaround for this verb
    assert "sudo tailscale up" in m._tailscale_operator_hint("up", "linux")


def t_tailscale_operator_hint_empty_off_linux():
    for plat in ("darwin", "win32"):
        assert m._tailscale_operator_hint("up", plat) == ""


def t_obs_refresh_route():
    assert m.route(["obs", "refresh"]) == \
        {"kind": "service", "command": "obs", "verb": "refresh", "rest": []}


def t_obs_bad_verb_raises():
    _raises(lambda: m.route(["obs"]))
    _raises(lambda: m.route(["obs", "bogus"]))


def t_sheet_routes():
    for verb in ("url", "open"):
        assert m.route(["sheet", verb]) == \
            {"kind": "service", "command": "sheet", "verb": verb, "rest": []}


def t_sheet_bad_verb_raises():
    _raises(lambda: m.route(["sheet"]))
    _raises(lambda: m.route(["sheet", "bogus"]))


def t_sheet_url_cmd_exits_without_sheet_id():
    old = m._active_sheet_url
    m._active_sheet_url = lambda: ""
    try:
        try:
            m.sheet_url_cmd([])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "no SHEET_ID" in str(e.code)
    finally:
        m._active_sheet_url = old


def t_sheet_url_cmd_prints_url(capsys=None):
    old_url, old_open = m._active_sheet_url, m._open_url
    opened = []
    m._active_sheet_url = lambda: "https://docs.google.com/spreadsheets/d/X/edit"
    m._open_url = lambda u: opened.append(u)
    try:
        m.sheet_open_cmd([])
        assert opened == ["https://docs.google.com/spreadsheets/d/X/edit"]
    finally:
        m._active_sheet_url, m._open_url = old_url, old_open


def t_obs_refresh_cmd_exits_when_relay_down():
    old = m._relay_http_ok
    m._relay_http_ok = lambda: False
    try:
        try:
            m.obs_refresh_cmd([])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "relay not responding" in str(e.code)
    finally:
        m._relay_http_ok = old


def t_http_url():
    assert m._http_url("127.0.0.1", 8088, "/panel") == "http://127.0.0.1:8088/panel"
    assert m._http_url("100.64.10.20", 8000, "/tablet") == "http://100.64.10.20:8000/tablet"


def t_src_base_modes():
    assert m._src_base(False, "", os.path.join("repo", "src")) == os.path.join("repo", "src")
    assert m._src_base(True, os.path.join("tmp", "_MEI1"), "x") == \
        os.path.join("tmp", "_MEI1", "src")


def t_untranslocate_app_translocation():
    # macOS App Translocation only affects a frozen .app launched from Finder, so
    # both guards must short-circuit BEFORE the (macOS-only) resolver is consulted.
    seen = []
    def resolver(p):
        seen.append(p); return "/Users/x/racecast/racecast-ui.app/Contents/MacOS/racecast-ui"
    tl = "/private/var/folders/pk/T/AppTranslocation/UUID/d/racecast-ui.app/Contents/MacOS/racecast-ui"
    assert m._untranslocate(tl, frozen=False, platform="darwin", resolver=resolver) == tl
    assert m._untranslocate(tl, frozen=True, platform="linux", resolver=resolver) == tl
    assert seen == []
    # frozen + macOS: map the translocated path back to its real on-disk location.
    assert m._untranslocate(tl, frozen=True, platform="darwin", resolver=resolver) == \
        "/Users/x/racecast/racecast-ui.app/Contents/MacOS/racecast-ui"
    # best-effort: a resolver that fails (None / raises) falls back to the input.
    assert m._untranslocate(tl, frozen=True, platform="darwin",
                            resolver=lambda p: None) == tl
    def boom(p):
        raise OSError("Security framework unavailable")
    assert m._untranslocate(tl, frozen=True, platform="darwin", resolver=boom) == tl


def t_runtime_base_modes():
    assert m._runtime_base(False, "python3", os.path.join("repo", "src")) == \
        os.path.join("repo", "runtime")
    assert m._runtime_base(False, "python3", "pkg") == os.path.join("pkg", "runtime")
    assert m._runtime_base(True, os.path.join("apps", "racecast"), "ignored") == \
        os.path.join("apps", "runtime")


def t_force_utf8_io_reconfigures_and_is_safe():
    calls = []
    class Stream:
        def reconfigure(self, **kw):
            calls.append(kw)
    class NoReconfigure:                      # py<3.7 / an exotic stream
        pass
    class Raises:
        def reconfigure(self, **kw):
            raise OSError("console detached")
    # None models a --windowed app whose PyInstaller build has no stdout — must
    # never raise; non-reconfigurable / raising streams are skipped, not fatal.
    m._force_utf8_io([Stream(), NoReconfigure(), Raises(), None, Stream()])
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 2


def t_parse_env_text():
    text = "# comment\nRACECAST_SHEET_ID=abc\nOTHER_TIMER_URL='http://x'\n\nnot a pair\n"
    assert m.parse_env_text(text) == {"RACECAST_SHEET_ID": "abc", "OTHER_TIMER_URL": "http://x"}


def t_ensure_env_file_creates_once():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, ".env.example"), "w", encoding="utf-8") as fh:
            fh.write("RACECAST_SHEET_ID=\n")
        # not frozen -> no-op
        assert m.ensure_env_file(d, frozen=False) is False
        assert not os.path.exists(os.path.join(d, ".env"))
        # frozen + template + no .env -> created from the template
        assert m.ensure_env_file(d, frozen=True) is True
        with open(os.path.join(d, ".env"), encoding="utf-8") as fh:
            assert fh.read() == "RACECAST_SHEET_ID=\n"
        # existing .env is never overwritten
        with open(os.path.join(d, ".env"), "w", encoding="utf-8") as fh:
            fh.write("RACECAST_SHEET_ID=real\n")
        assert m.ensure_env_file(d, frozen=True) is False
        with open(os.path.join(d, ".env"), encoding="utf-8") as fh:
            assert fh.read() == "RACECAST_SHEET_ID=real\n"


def t_cleanup_old_binary():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        old = os.path.join(d, "racecast-old.exe")
        with open(old, "wb") as fh:
            fh.write(b"x")
        # only frozen windows cleans up
        assert m.cleanup_old_binary(d, frozen=False, platform="win32") is False
        assert m.cleanup_old_binary(d, frozen=True, platform="darwin") is False
        assert os.path.exists(old)
        assert m.cleanup_old_binary(d, frozen=True, platform="win32") is True
        assert not os.path.exists(old)
        # absent file -> quiet False
        assert m.cleanup_old_binary(d, frozen=True, platform="win32") is False


def t_cleanup_old_binary_also_removes_ui():
    # install_ui renames a locked, running racecast-ui.exe aside to
    # racecast-ui-old.exe during a self-update; cleanup must sweep that too, not
    # only the main binary's racecast-old.exe.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ui_old = os.path.join(d, "racecast-ui-old.exe")
        with open(ui_old, "wb") as fh:
            fh.write(b"x")
        assert m.cleanup_old_binary(d, frozen=True, platform="win32") is True
        assert not os.path.exists(ui_old)


def t_ensure_example_profile_seeds_once():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        bundled = os.path.join(d, "bundled-example")
        os.makedirs(bundled)
        with open(os.path.join(bundled, "profile.env"), "w", encoding="utf-8") as fh:
            fh.write("NAME=Example League\nSHEET_ID=\n")
        home = os.path.join(d, "home")
        os.makedirs(home)
        # not frozen -> no-op
        assert m.ensure_example_profile(home, frozen=False, bundled=bundled) is False
        assert not os.path.exists(os.path.join(home, "profiles", "example"))
        # frozen + bundled template + no profiles/example -> seeded next to the binary
        assert m.ensure_example_profile(home, frozen=True, bundled=bundled) is True
        seeded = os.path.join(home, "profiles", "example", "profile.env")
        assert os.path.isfile(seeded)
        # existing profiles/example is never clobbered
        with open(seeded, "w", encoding="utf-8") as fh:
            fh.write("NAME=Edited\n")
        assert m.ensure_example_profile(home, frozen=True, bundled=bundled) is False
        with open(seeded, encoding="utf-8") as fh:
            assert fh.read() == "NAME=Edited\n"


def t_ensure_example_profile_without_bundle():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        home = os.path.join(d, "home")
        os.makedirs(home)
        missing = os.path.join(d, "nope")
        assert m.ensure_example_profile(home, frozen=True, bundled=missing) is False
        assert not os.path.exists(os.path.join(home, "profiles", "example"))


def t_ensure_env_file_without_template():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert m.ensure_env_file(d, frozen=True) is False
        assert not os.path.exists(os.path.join(d, ".env"))


def t_ensure_env_file_copy_failure():
    import tempfile
    def boom(src, dst):
        raise OSError("boom")
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, ".env.example"), "w", encoding="utf-8") as fh:
            fh.write("RACECAST_SHEET_ID=\n")
        orig = m.shutil.copyfile
        m.shutil.copyfile = boom
        try:
            assert m.ensure_env_file(d, frozen=True) is False
        finally:
            m.shutil.copyfile = orig
        assert not os.path.exists(os.path.join(d, ".env"))


def t_pick_ca_bundle():
    ex = lambda paths: (lambda p: p in paths)
    # build's own cafile exists -> trust it, no override
    assert m.pick_ca_bundle("/build/cert.pem", None, ("/etc/a",), exists=ex({"/build/cert.pem"})) is None
    # build's capath exists -> trust it
    assert m.pick_ca_bundle(None, "/build/certs", ("/etc/a",), exists=ex({"/build/certs"})) is None
    # neither exists -> first existing candidate
    assert m.pick_ca_bundle("/build/cert.pem", "/build/certs", ("/etc/a", "/etc/b"),
                            exists=ex({"/etc/b"})) == "/etc/b"
    # nothing exists anywhere -> None (leave things alone)
    assert m.pick_ca_bundle(None, None, ("/etc/a",), exists=ex(set())) is None


def t_augment_path():
    ex = lambda paths: (lambda p: p in paths)
    sep = os.pathsep
    # a missing-from-PATH tool dir that exists gets prepended (Homebrew wins)
    assert m.augment_path("/usr/bin", ("/opt/homebrew/bin", "/usr/local/bin"),
                          exists=ex({"/opt/homebrew/bin"})) == "/opt/homebrew/bin" + sep + "/usr/bin"
    # already on PATH -> nothing to add (no duplicate)
    assert m.augment_path("/opt/homebrew/bin" + sep + "/usr/bin",
                          ("/opt/homebrew/bin",), exists=ex({"/opt/homebrew/bin"})) is None
    # candidate doesn't exist on disk -> left alone
    assert m.augment_path("/usr/bin", ("/opt/homebrew/bin",), exists=ex(set())) is None
    # several existing+missing dirs keep candidate order, ahead of the old PATH
    assert m.augment_path("/usr/bin", ("/opt/homebrew/bin", "/usr/local/bin"),
                          exists=ex({"/opt/homebrew/bin", "/usr/local/bin"})) \
        == sep.join(("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"))
    # empty PATH -> just the existing candidates
    assert m.augment_path("", ("/opt/homebrew/bin", "/usr/local/bin"),
                          exists=ex({"/opt/homebrew/bin"})) == "/opt/homebrew/bin"


def t_ensure_tool_path_adds_managed_bin():
    """install-tools drops direct-download tools (deno on Linux, the Ookla
    speedtest CLI on mac/Linux) into runtime/bin — never on the user's shell
    PATH. _ensure_tool_path() must prepend it so preflight + the spawned relay
    resolve them."""
    import tempfile
    td = tempfile.mkdtemp()
    binr = os.path.join(td, "runtime", "bin")
    os.makedirs(binr)
    orig_rt, orig_path = m._runtime_base_dir, os.environ.get("PATH", "")
    m._runtime_base_dir = lambda: os.path.join(td, "runtime")
    try:
        os.environ["PATH"] = os.path.join("/usr", "bin")
        m._ensure_tool_path()
        parts = os.environ["PATH"].split(os.pathsep)
        assert parts[0] == binr            # prepended ahead of the old PATH
    finally:
        m._runtime_base_dir = orig_rt
        os.environ["PATH"] = orig_path


def t_ensure_tool_path_noop_when_bin_absent():
    import tempfile
    td = tempfile.mkdtemp()                # runtime/bin does NOT exist here
    orig_rt, orig_path = m._runtime_base_dir, os.environ.get("PATH", "")
    m._runtime_base_dir = lambda: os.path.join(td, "runtime")
    try:
        os.environ["PATH"] = os.path.join("/usr", "bin")
        m._ensure_tool_path()
        assert os.environ["PATH"] == os.path.join("/usr", "bin")   # unchanged
    finally:
        m._runtime_base_dir = orig_rt
        os.environ["PATH"] = orig_path


def t_script_invocation_repo():
    import sys as _sys
    kind, argv, _ = m._script_invocation("scripts/preflight.py", ["--quick"], False)
    assert kind == "subprocess"
    assert argv[0] == _sys.executable
    assert argv[1].endswith(os.path.join("scripts", "preflight.py"))
    assert argv[-1] == "--quick"


def t_script_invocation_frozen():
    kind, path, args = m._script_invocation("relay/racecast-feeds.py", ["--no-pov"], True,
                                            base=os.path.join("MEI", "src"))
    assert kind == "inprocess"
    assert path == os.path.join("MEI", "src", "relay", "racecast-feeds.py")
    assert args == ["--no-pov"]


def t_relay_daemon_argv():
    import sys as _sys
    repo = m._relay_daemon_argv(["--no-pov"], False)
    assert repo[0] == _sys.executable and repo[1].endswith("racecast-feeds.py")
    assert "--runtime-dir" in repo and repo[-1] == "--no-pov"
    assert m._relay_daemon_argv(["--no-pov"], True) == \
        [_sys.executable, "relay", "run", "--no-pov"]


def t_oneshot_extra():
    # new signature: (command, rest, runtime_dir, base_dir)
    # --out is always injected now (profile-scoped, not only when frozen)
    R = os.path.join("x", "runtime", "demo")   # profile runtime
    B = os.path.join("x", "runtime")           # base runtime
    assert m._oneshot_extra("preflight", [], R, B) == ["--runtime-dir", B]
    assert m._oneshot_extra("graphics", [], R, B) == \
        ["--out", os.path.join(R, "graphics")]
    assert m._oneshot_extra("media", [], R, B) == ["--out", os.path.join(R, "media")]
    # setup INJECTS media/graphics dirs into the collection -- always profile-scoped.
    assert m._oneshot_extra("setup", [], R, B) == \
        ["--out", os.path.join(R, "GT_Endurance.import.json"),
         "--media", os.path.join(R, "media"),
         "--graphics", os.path.join(R, "graphics")]
    assert m._oneshot_extra("setup", ["--media", "m"], R, B) == \
        ["--out", os.path.join(R, "GT_Endurance.import.json"),
         "--graphics", os.path.join(R, "graphics")]
    assert m._oneshot_extra(
        "setup", ["--out", "z", "--media", "m", "--graphics", "g"], R, B) == []
    assert m._oneshot_extra("graphics", ["--out", "z"], R, B) == []


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


def t_export_companion_default_into_runtime():
    # No --out -> runtime/ (same home as the localized OBS collection), and the
    # dir is created on demand — NOT the caller's cwd.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        old = m._runtime_dir
        m._runtime_dir = lambda: os.path.join(td, "runtime")
        try:
            m.export_companion([])
            out = os.path.join(td, "runtime", "racecast-buttons.companionconfig")
            assert os.path.getsize(out) > 0
        finally:
            m._runtime_dir = old


def t_install_apps_oneshot():
    assert m.route(["install-apps"]) == \
        {"kind": "oneshot", "command": "install-apps", "rest": []}


def t_update_routes_as_oneshot():
    a = m.route(["update", "--check"])
    assert a == {"kind": "oneshot", "command": "update", "rest": ["--check"]}, a


def t_update_oneshot_extra_injects_nothing():
    # update needs no runtime-dir/--out injection; --current is added in oneshot()
    assert m._oneshot_extra("update", [], "/rt/demo", "/rt") == []


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


def t_stint_args_extraction():
    # event_start forwards only the --stint flag to the relay launch
    assert m._stint_args([]) == []
    assert m._stint_args(["--no-color"]) == []
    assert m._stint_args(["--stint", "4"]) == ["--stint", "4"]
    assert m._stint_args(["--no-color", "--stint=7"]) == ["--stint", "7"]
    assert m._stint_args(["--stint"]) == []          # missing value: let relay default


def t_stint_args_rejects_garbage():
    # fail fast BEFORE a daemon is spawned (its error would only hit the log)
    for bad in (["--stint", "abc"], ["--stint=0"], ["--stint", "-3"]):
        try:
            m._stint_args(bad)
            raise AssertionError(f"accepted {bad}")
        except SystemExit:
            pass


def t_relay_start_warns_when_running_and_stint_ignored():
    # already-running + --stint: must tell the operator the flag was ignored
    import io, contextlib
    old_read, old_alive = m.sv.read_pid, m.sv.pid_alive
    m.sv.read_pid = lambda path: 4242
    m.sv.pid_alive = lambda pid: True
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.relay_start(["--stint", "5"])
        out = buf.getvalue()
        assert "already running" in out
        assert "--stint ignored" in out and "/set/stint/5" in out
    finally:
        m.sv.read_pid, m.sv.pid_alive = old_read, old_alive


def t_relay_stop_releases_obs_feeds_after_kill():
    # AFTER the kill: a source rebuild against a live relay would reconnect.
    # Against the dead relay it just drops the half-dead connection, freeing
    # the feed ports (otherwise FIN_WAIT_1 -> preflight "port in use").
    import io, contextlib
    calls = []
    old = (m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds)
    m.sv.read_pid = lambda path: 4242
    m.sv.pid_alive = lambda pid: True
    m.sv.stop_pid = lambda pid, path, is_target=None: (
        calls.append(("stop_pid", is_target)), True)[1]
    m._release_obs_feeds = lambda: calls.append("obs")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m.relay_stop([])
        # the relay stop must verify process identity before killing (#102)
        assert calls == [("stop_pid", m.sv.pid_is_relay), "obs"]
    finally:
        m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds = old


def t_relay_stop_skips_obs_release_when_kill_failed():
    # Relay may still be alive -> a rebuild would reconnect. Don't release.
    import io, contextlib
    calls = []
    old = (m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds)
    m.sv.read_pid = lambda path: 4242
    m.sv.pid_alive = lambda pid: True
    m.sv.stop_pid = lambda pid, path, is_target=None: (calls.append("stop_pid"), False)[1]
    m._release_obs_feeds = lambda: calls.append("obs")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m.relay_stop([])
        assert calls == ["stop_pid"]
    finally:
        m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds = old


def t_relay_stop_skips_obs_when_relay_not_running():
    import io, contextlib, tempfile
    calls = []
    old = (m.sv.read_pid, m.sv.pid_alive, m._release_obs_feeds, m._relay_pid_path)
    with tempfile.TemporaryDirectory() as tmp:
        m._relay_pid_path = lambda: os.path.join(tmp, "relay.pid")
        m.sv.read_pid = lambda path: None
        m.sv.pid_alive = lambda pid: False
        m._release_obs_feeds = lambda: calls.append("obs")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                m.relay_stop([])
            assert calls == []                  # nothing ran -> nothing to release
        finally:
            m.sv.read_pid, m.sv.pid_alive, m._release_obs_feeds, m._relay_pid_path = old


def t_streams_stop_releases_obs_feeds_when_feeds_exist():
    import io, contextlib, tempfile
    calls = []
    old = (m._release_obs_feeds, m._run_script, m._streams_static_dir)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "feed_53001.pid"), "w") as fh:
            fh.write("1")
        m._streams_static_dir = lambda: tmp
        m._release_obs_feeds = lambda: calls.append("obs")
        m._run_script = lambda rel, args: (calls.append("run_script"), 0)[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                m.streams_stop([])
            assert calls == ["run_script", "obs"]   # release AFTER the feeds die
        finally:
            m._release_obs_feeds, m._run_script, m._streams_static_dir = old


def t_streams_stop_skips_obs_without_feed_pids():
    import io, contextlib, tempfile
    calls = []
    old = (m._release_obs_feeds, m._run_script, m._streams_static_dir)
    with tempfile.TemporaryDirectory() as tmp:
        m._streams_static_dir = lambda: tmp
        m._release_obs_feeds = lambda: calls.append("obs")
        m._run_script = lambda rel, args: (calls.append("run_script"), 0)[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                m.streams_stop([])
            assert calls == ["run_script"]
        finally:
            m._release_obs_feeds, m._run_script, m._streams_static_dir = old


def t_init_routes_with_rest():
    assert m.route(["init"]) == {"kind": "init", "rest": []}
    assert m.route(["init", "--force", "--browser", "chrome"])["rest"] == \
        ["--force", "--browser", "chrome"]


def t_env_base_per_mode():
    # mirrors _runtime_base: frozen -> next to the binary; repo -> repo root;
    # package -> the package dir itself
    assert m._env_base(True, "/opt/racecast/racecast", "/tmp/_MEIxx/src") == "/opt/racecast"
    assert m._env_base(False, "", "/repo/src") == "/repo"
    assert m._env_base(False, "", "/pkg") == "/pkg"


def t_refresh_decision():
    assert m.refresh_decision(None, None) == "skip-no-pages"
    assert m.refresh_decision(None, "abc") == "skip-no-pages"
    assert m.refresh_decision("abc", "abc") == "skip-unchanged"
    assert m.refresh_decision("abc", "old") == "refresh"
    assert m.refresh_decision("abc", None) == "refresh"          # first run
    assert m.refresh_decision("abc", "abc", force=True) == "refresh"


def t_served_pages_hash_concatenates_in_order():
    import hashlib
    pages = {p: p.encode() for p in m.OBS_PAGE_PATHS}
    expected = hashlib.sha256(b"".join(pages[p] for p in m.OBS_PAGE_PATHS)).hexdigest()
    assert m.served_pages_hash(fetch=lambda p: pages[p]) == expected


def t_served_pages_hash_none_when_any_fetch_fails():
    def fetch(path):
        if path == "/hud":
            raise OSError("connection refused")
        return b"HUD"
    assert m.served_pages_hash(fetch=fetch) is None


def t_served_pages_hash_none_when_override_css_fetch_fails():
    def fetch(path):
        if path == "/hud/override.css":
            raise OSError("connection refused")
        return b"x"
    assert m.served_pages_hash(fetch=fetch) is None


def t_served_pages_hash_none_when_first_fetch_fails():
    def fetch(path):
        raise OSError("connection refused")
    assert m.served_pages_hash(fetch=fetch) is None


def t_pages_hash_roundtrip_and_missing():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state", "obs-pages.hash")
        assert m.read_pages_hash(path) is None                   # missing file
        m.write_pages_hash(path, "abc123")                       # creates the dir
        assert m.read_pages_hash(path) == "abc123"


def t_wait_for_polls_until_deadline():
    ticks = iter([0, 1, 2, 3, 4, 5])
    slept = []
    ok = m.wait_for(lambda: False, 2, clock=lambda: next(ticks),
                    sleep=slept.append)
    assert ok is False
    assert slept                                                 # polled, not busy-spun
    assert m.wait_for(lambda: True, 0, clock=lambda: 0,
                      sleep=lambda s: None) is True               # checks at least once


def t_route_ui():
    assert m.route(["ui"]) == {"kind": "ui", "rest": []}
    assert m.route(["ui", "--no-browser"]) == {"kind": "ui", "rest": ["--no-browser"]}


def t_profile_routing():
    assert m.route(["profile", "list"]) == {"kind": "profile", "rest": ["list"]}
    assert m.route(["profile", "new", "erf", "--from", "example"]) == {
        "kind": "profile", "rest": ["new", "erf", "--from", "example"]}
    # an unknown profile verb is NOT validated at the route seam (parse_profile_args
    # does that) — route just hands the rest through:
    assert m.route(["profile", "bogus"]) == {"kind": "profile", "rest": ["bogus"]}


def t_oneshot_extra_paths():
    rd = os.path.join("R", "demo")   # profile runtime
    base = "R"                       # base runtime (cookies/preflight)
    assert m._oneshot_extra("graphics", [], rd, base) == [
        "--out", os.path.join(rd, "graphics")]
    assert m._oneshot_extra("media", [], rd, base) == [
        "--out", os.path.join(rd, "media")]
    assert m._oneshot_extra("setup", [], rd, base) == [
        "--out", os.path.join(rd, "GT_Endurance.import.json"),
        "--media", os.path.join(rd, "media"),
        "--graphics", os.path.join(rd, "graphics")]
    assert m._oneshot_extra("cookies", [], rd, base) == ["--runtime-dir", base]
    assert m._oneshot_extra("preflight", [], rd, base) == ["--runtime-dir", base]
    assert m._oneshot_extra("graphics", ["--out", "X"], rd, base) == []  # user override respected


def t_profile_env_vars_filters_empty():
    rc = m.pcfg.ResolvedConfig(
        profile="demo", name="Demo", sheet_id="abc",
        sheet_push_url="", intro_url="https://i", outro_url="")
    assert m._profile_env_vars(rc) == {
        "RACECAST_SHEET_ID": "abc", "RACECAST_INTRO_URL": "https://i"}


def t_profile_env_vars_includes_obs_collection():
    rc = m.pcfg.ResolvedConfig(profile="demo", name="Demo League", sheet_id="abc",
                               obs_collection="Demo Broadcast")
    out = m._profile_env_vars(rc)
    assert out["RACECAST_OBS_COLLECTION"] == "Demo Broadcast"


def t_profile_env_vars_includes_discord_webhook():
    rc = m.pcfg.ResolvedConfig(profile="demo", name="Demo", sheet_id="abc",
                               discord_webhook_url="https://discord.com/api/webhooks/1/x")
    assert m._profile_env_vars(rc)["RACECAST_DISCORD_WEBHOOK_URL"] == \
        "https://discord.com/api/webhooks/1/x"
    # empty -> filtered out (push disabled)
    rc2 = m.pcfg.ResolvedConfig(profile="demo", name="Demo", sheet_id="abc")
    assert "RACECAST_DISCORD_WEBHOOK_URL" not in m._profile_env_vars(rc2)


def t_active_obs_collection_falls_back_to_constant_without_profile():
    import tempfile
    import obs_ws
    saved = dict(os.environ)
    try:
        os.environ.pop("RACECAST_PROFILE", None)
        with tempfile.TemporaryDirectory() as td:
            orig = m._env_base
            m._env_base = lambda *a, **k: td      # empty root -> no profile resolves
            try:
                assert m._active_obs_collection() == obs_ws.EXPECTED_SCENE_COLLECTION
            finally:
                m._env_base = orig
    finally:
        os.environ.clear(); os.environ.update(saved)


def t_profile_runtime_scoping():
    assert m._profile_runtime("/r", "demo") == os.path.join("/r", "demo")
    assert m._profile_runtime("/r", "erf") == os.path.join("/r", "erf")
    assert m._profile_runtime("/r", None) == "/r"


def t_profiles_data_reports_active_logo_flag():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "demo"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "demo", "profile.env"), "w") as fh:
            fh.write("NAME=Demo League\nLOGO=logo.png\n")
        with open(os.path.join(prof, "demo", "logo.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\nFAKE")              # any bytes; isfile is what matters
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            with_logo = m.profiles_data()
            os.remove(os.path.join(prof, "demo", "logo.png"))   # file gone -> flag false
            without_logo = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert with_logo["ok"] is True and with_logo["logo"] is True
        assert without_logo["logo"] is False


def t_profiles_data_lists_active_and_available():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "demo"))
        os.makedirs(os.path.join(prof, "erf"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "demo", "profile.env"), "w") as fh:
            fh.write("NAME=Demo League\nSHEET_ID=abc\n")
        with open(os.path.join(prof, "erf", "profile.env"), "w") as fh:
            fh.write("NAME=ERF\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True
        assert d["active"] == "demo"
        names = {p["name"]: p for p in d["profiles"]}
        assert names["demo"]["display"] == "Demo League"
        assert names["demo"]["sheet_set"] is True
        assert names["erf"]["sheet_set"] is False


def t_profile_use_data_switches_pointer():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("SHEET_ID=abc\n")
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_use_data("demo")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d == {"ok": True, "active": "demo"}
        with open(os.path.join(td, "runtime", "active-profile")) as fh:
            assert fh.read().strip() == "demo"


def t_profile_use_data_unknown_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_use_data("nope")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is False and d["error"]


def t_profile_new_data_creates_from_example():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ex = os.path.join(td, "profiles", "example")
        os.makedirs(ex)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(ex, "profile.env"), "w") as fh:
            fh.write("NAME=Example\nSHEET_ID=\n")
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("gt3", "example")
        finally:
            m._env_base = orig_b
        assert d["ok"] is True and d["name"] == "gt3"
        assert os.path.isfile(os.path.join(td, "profiles", "gt3", "profile.env"))


def t_profile_new_data_spaced_name_returns_slug():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ex = os.path.join(td, "profiles", "example")
        os.makedirs(ex)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(ex, "profile.env"), "w") as fh:
            fh.write("NAME=Example\nSHEET_ID=\n")
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("Demo League", "example")
        finally:
            m._env_base = orig_b
        assert d["ok"] is True and d["name"] == "demo-league"   # slug, switchable via `use`
        assert os.path.isfile(os.path.join(td, "profiles", "demo-league", "profile.env"))


def t_profile_new_data_bad_name_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "profiles", "example"))
        open(os.path.join(td, ".env.example"), "w").close()
        open(os.path.join(td, "profiles", "example", "profile.env"), "w").close()
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("!!!", "example")   # slugifies to empty -> rejected
        finally:
            m._env_base = orig_b
        assert d["ok"] is False and d["error"]


def t_profile_env_entries_data_reads_active():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# comment\nSHEET_ID=abc\nNAME=Demo\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_entries_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True and d["active"] == "demo"
        keys = [e["key"] for e in d["entries"]]
        assert "SHEET_ID" in keys and "NAME" in keys


def t_profile_env_entries_data_no_profile_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_entries_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is False and d["error"]


def t_profile_env_write_data_persists_to_active():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# keep me\nSHEET_ID=old\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_write_data([{"key": "SHEET_ID", "value": "new"},
                                          {"key": "OBS_COLLECTION", "value": "GT3"}])
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True
        with open(os.path.join(prof, "profile.env")) as fh:
            text = fh.read()
        assert "SHEET_ID=new" in text and "OBS_COLLECTION=GT3" in text
        assert "# keep me" in text


def t_profile_env_write_data_no_profile_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_write_data([{"key": "SHEET_ID", "value": "x"}])
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is False and d["error"]
        # the machine .env must never be touched when no profile is active
        assert not os.path.exists(os.path.join(td, ".env"))


def t_overlay_read_absent_ok_empty():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(prof, "profile.env"), "w").close()
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.overlay_read_data("hud")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True and d["css"] == "" and d["page"] == "hud"


def t_overlay_write_then_read_roundtrip():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(prof, "profile.env"), "w").close()
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            w = m.overlay_write_data("hud", "#stint{left:5px}")
            d = m.overlay_read_data("hud")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert w["ok"] is True
        assert d["ok"] is True and d["css"] == "#stint{left:5px}"
        on_disk = os.path.join(td, "profiles", "demo", "overlay", "hud.css")
        assert os.path.exists(on_disk)


def t_overlay_rejects_unknown_page():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "demo")
        os.makedirs(prof)
        open(os.path.join(prof, "profile.env"), "w").close()
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            assert m.overlay_write_data("timer", "x")["ok"] is False
            assert m.overlay_write_data("panel", "x")["ok"] is False
            assert m.overlay_read_data("../etc")["ok"] is False
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r


def t_overlay_no_profile_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            assert m.overlay_read_data("hud")["ok"] is False
            assert m.overlay_write_data("hud", "x")["ok"] is False
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r


def _mk_active_profile(td):
    """Temp profile 'demo' + active pointer; returns the patched (env_base,
    runtime_base) restorers' originals via a tuple. Mirrors the overlay tests."""
    prof = os.path.join(td, "profiles", "demo")
    os.makedirs(prof)
    open(os.path.join(prof, "profile.env"), "w").close()
    open(os.path.join(td, ".env.example"), "w").close()
    os.makedirs(os.path.join(td, "runtime"))
    with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
        fh.write("demo\n")
    orig = (m._env_base, m._runtime_base_dir)
    m._env_base = lambda *a, **k: td
    m._runtime_base_dir = lambda: os.path.join(td, "runtime")
    return orig


def t_overlay_layout_write_compiles_and_persists():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            w = m.overlay_layout_write_data(
                "hud", {"page": "hud",
                        "slots": {"stint": {"left": 800, "top": 30, "fontSize": 44}}})
            r = m.overlay_layout_read_data("hud")
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert w["ok"] is True and "left: 800px" in w["css"] and "font-size: 44px" in w["css"]
        od = os.path.join(td, "profiles", "demo", "overlay")
        assert os.path.exists(os.path.join(od, "hud.css"))
        assert os.path.exists(os.path.join(od, "layout-hud.json"))
        # relay serves the generated hud.css verbatim -> the compiled CSS is on disk
        with open(os.path.join(od, "hud.css"), encoding="utf-8") as fh:
            assert "left: 800px" in fh.read()
        assert r["ok"] and r["migrated"] is False
        assert r["layout"]["slots"]["stint"]["left"] == 800


def t_overlay_layout_read_migrates_handwritten_css():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        od = os.path.join(td, "profiles", "demo", "overlay")
        os.makedirs(od)
        with open(os.path.join(od, "hud.css"), "w", encoding="utf-8") as fh:
            fh.write("#stint{left:999px}/* mine */")
        try:
            r = m.overlay_layout_read_data("hud")    # no layout-hud.json yet
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert r["ok"] and r["migrated"] is True
        assert r["layout"]["customCss"] == "#stint{left:999px}/* mine */"
        assert r["layout"]["slots"] == {}


def t_overlay_layout_folds_legacy_timer_css():
    import tempfile, json as _json
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        od = os.path.join(td, "profiles", "demo", "overlay")
        os.makedirs(od)
        # Write a layout-hud.json so migration path is skipped (we test the fold path)
        with open(os.path.join(od, "layout-hud.json"), "w", encoding="utf-8") as fh:
            _json.dump({"page": "hud", "slots": {}, "fonts": [], "customCss": ""}, fh)
        # Write a real timer.css with actual CSS rules
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as fh:
            fh.write("#clock { color: #f4f4f4; }")
        try:
            d = m.overlay_layout_read_data("hud")
            # Idempotency: re-reading must not accumulate another copy of the timer CSS.
            d2 = m.overlay_layout_read_data("hud")
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert d["ok"] is True
        assert "#clock { color: #f4f4f4; }" in (d["layout"].get("customCss") or "")
        assert (d2["layout"].get("customCss") or "").count("#clock") == 1


def t_overlay_layout_ignores_comment_only_timer_css():
    import tempfile, json as _json
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        od = os.path.join(td, "profiles", "demo", "overlay")
        os.makedirs(od)
        # Write a layout-hud.json
        with open(os.path.join(od, "layout-hud.json"), "w", encoding="utf-8") as fh:
            _json.dump({"page": "hud", "slots": {}, "fonts": [], "customCss": ""}, fh)
        # Write a comment-only timer.css (default scaffold — no real rules)
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as fh:
            fh.write("/* just the template, no rules */\n")
        try:
            d = m.overlay_layout_read_data("hud")
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert d["ok"] is True
        assert "template" not in (d["layout"].get("customCss") or "")


def t_overlay_layout_write_rejects_unknown_page():
    assert m.overlay_layout_write_data("panel", {"page": "panel"})["ok"] is False


def t_overlay_slots_data_from_real_hud():
    r = m.overlay_slots_data("hud")
    assert r["ok"] is True
    assert any(s["id"] == "stint" for s in r["slots"])
    assert "#stint" in r["css"] and r["sample"]["stint"]


def t_overlay_fonts_upload_then_list_and_serve():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            up = m.overlay_font_upload_data("League.woff2", b"OTTOfontbytes")
            bad = m.overlay_font_upload_data("../evil.woff2", b"x")
            badext = m.overlay_font_upload_data("League.exe", b"x")
            listing = m.overlay_fonts_list_data()
            served = m.overlay_font_serve("League.woff2")
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert up["ok"] is True and up["name"] == "League.woff2"
        assert bad["ok"] is False and badext["ok"] is False
        assert listing["ok"] and listing["fonts"] == ["League.woff2"]
        assert served and served[1] == "font/woff2"
        assert os.path.basename(served[0]) == "League.woff2"


def t_machine_font_download_into_library():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        css = ('@font-face{font-family:Oswald;'
               'src:url(https://fonts.gstatic.com/s/oswald/v1/x.woff2) format("woff2")}')
        try:
            d = m.machine_font_download_data(
                "Oswald", css_fetch=lambda u: css, bin_fetch=lambda u: b"WOFF2DATA")
            lib = m.machine_fonts_list_data()
            ov = m.overlay_fonts_list_data()
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert d["ok"] is True and d["name"] == "Oswald.woff2"
        # lands in the machine-wide library, NOT the profile, until used
        assert os.path.exists(os.path.join(td, "runtime", "fonts", "Oswald.woff2"))
        assert "Oswald.woff2" in lib["fonts"] and "catalog" not in lib
        assert "Oswald.woff2" in ov["library"] and "Oswald.woff2" not in ov["fonts"]


def t_machine_font_download_rejects_unsafe_name():
    # SSRF gate: a name with path/host tricks is rejected before any fetch.
    hit = {"n": 0}
    d = m.machine_font_download_data(
        "../etc/passwd", css_fetch=lambda u: hit.__setitem__("n", 1) or "x",
        bin_fetch=lambda u: b"x")
    assert d["ok"] is False and "invalid" in d["error"] and hit["n"] == 0


def t_machine_font_download_allows_uncurated_name():
    # Any syntactically valid family (not just the catalog) is fetchable.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            d = m.machine_font_download_data(
                "Big Shoulders Display",
                css_fetch=lambda u: "url(https://fonts.gstatic.com/x.woff2)",
                bin_fetch=lambda u: b"DATA")
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert d["ok"] is True and d["name"] == "BigShouldersDisplay.woff2"


def t_machine_font_download_no_woff2_is_error():
    d = m.machine_font_download_data(
        "Oswald", css_fetch=lambda u: "/* nothing */", bin_fetch=lambda u: b"")
    assert d["ok"] is False


def t_machine_font_delete_removes_from_library():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            m.machine_font_download_data(
                "Oswald", css_fetch=lambda u: "url(https://fonts.gstatic.com/x.woff2)",
                bin_fetch=lambda u: b"DATA")
            before = m.machine_fonts_list_data()["fonts"]
            d = m.machine_font_delete_data("Oswald.woff2")
            after = m.machine_fonts_list_data()["fonts"]
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert "Oswald.woff2" in before and d["ok"] is True
        assert "Oswald.woff2" not in after


def t_google_font_catalog_parses_metadata():
    meta = ('{"familyMetadataList":[{"family":"Oswald"},{"family":"Big Shoulders Display"},'
            '{"family":"Bad/Name"},{"family":"Roboto"}]}')
    d = m.google_font_catalog_data(fetch=lambda: meta)
    assert d["ok"] is True and d["source"] == "google"
    assert "Oswald" in d["families"] and "Big Shoulders Display" in d["families"]
    assert "Bad/Name" not in d["families"]                 # unfetchable names filtered out
    assert d["families"] == sorted(d["families"])          # sorted for the typeahead


def t_google_font_catalog_falls_back_to_curated():
    def boom():
        raise OSError("offline")
    d = m.google_font_catalog_data(fetch=boom)
    assert d["ok"] is True and d["source"] == "curated"
    assert d["families"] == list(m.ob.GOOGLE_FONTS)


def t_overlay_save_copies_referenced_library_font_into_profile():
    # Copy-on-save: a design that references a library font copies it into the
    # profile (portable export) and emits its @font-face in the generated CSS.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            m.machine_font_download_data(
                "Oswald", css_fetch=lambda u: "url(https://fonts.gstatic.com/x.woff2)",
                bin_fetch=lambda u: b"DATA")
            w = m.overlay_layout_write_data(
                "hud", {"page": "hud",
                        "slots": {"stint": {"fontFamily": "Oswald"}}})
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert w["ok"] is True
        copied = os.path.join(td, "profiles", "demo", "overlay", "fonts", "Oswald.woff2")
        assert os.path.exists(copied)                 # copied into the profile
        assert "@font-face" in w["css"] and 'font-family: "Oswald"' in w["css"]
        assert 'url(/overlay/fonts/Oswald.woff2)' in w["css"]


def t_overlay_bg_path_present_and_absent():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        orig = _mk_active_profile(td)
        try:
            assert m.overlay_bg_path() is None         # no Overlay.png yet
            g = os.path.join(td, "runtime", "demo", "graphics")
            os.makedirs(g)
            with open(os.path.join(g, "Overlay.png"), "wb") as fh:
                fh.write(b"\x89PNG")
            hit = m.overlay_bg_path()
        finally:
            m._env_base, m._runtime_base_dir = orig
        assert hit and hit.endswith("Overlay.png")


def t_obs_page_paths_include_overrides():
    assert m.OBS_PAGE_PATHS == ("/hud", "/hud/override.css",
                                "/splitscreen", "/splitscreen/override.css")


def t_relay_runtime_args_adds_overlay_when_dir_exists():
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        od = os.path.join(tmp, "overlay"); os.makedirs(od)
        assert m._overlay_relay_args(od) == ["--overlay-dir", od]


def t_relay_runtime_args_omits_overlay_when_absent():
    assert m._overlay_relay_args(None) == []
    assert m._overlay_relay_args("/no/such/overlay/dir") == []


def t_servable_logo_path_allows_web_images_only():
    for p in ("a/logo.png", "a/logo.JPG", "x.jpeg", "x.webp", "x.gif", "brand.svg"):
        assert m.servable_logo_path(p) == p          # web image -> passed through
    for p in ("", "profile.env", "notes.txt", "clip.mp4", "a/logo", "x.PNG.bak"):
        assert m.servable_logo_path(p) == ""          # not a web image -> blanked


def t_profile_logo_returns_active_servable_path():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "demo"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "demo", "profile.env"), "w") as fh:
            fh.write("NAME=Demo\nLOGO=logo.svg\n")
        logo = os.path.join(prof, "demo", "logo.svg")
        with open(logo, "wb") as fh:
            fh.write(b"<svg/>")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("demo\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            got = m.profile_logo()
            os.remove(logo)                # file gone -> None
            gone = m.profile_logo()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert got == logo
        assert gone is None


def t_route_backup():
    assert m.route(["backup", "list"]) == {"kind": "backup", "rest": ["list"]}
    assert m.route(["backup", "create", "Winter"]) == {"kind": "backup", "rest": ["create", "Winter"]}


def _raises(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def t_event_start_gate_blocks_without_force():
    # A static-precondition FAIL aborts bring-up (exit 1) BEFORE any service is
    # launched, when --force is absent.
    ev = m._event_modules()[0]
    orig = m._event_gate_results
    m._event_gate_results = lambda e, p: [ev.Result(ev.FAIL, ".env", "missing RACECAST_SHEET_ID")]
    try:
        try:
            m.event_start([])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert e.code == 1
    finally:
        m._event_gate_results = orig


def t_event_start_force_skips_gate():
    # --force bypasses the gate even with a FAIL present: event_start proceeds to
    # step 1 (_tailscale_connect), which we stub to prove the gate was skipped.
    ev = m._event_modules()[0]
    orig_gate, orig_ts = m._event_gate_results, m._tailscale_connect

    class _Reached(Exception):
        pass

    m._event_gate_results = lambda e, p: [ev.Result(ev.FAIL, ".env", "x")]
    def _boom(_ev):
        raise _Reached()
    m._tailscale_connect = _boom
    try:
        try:
            m.event_start(["--force"])
            raise AssertionError("expected to reach _tailscale_connect")
        except _Reached:
            pass                                # got past the gate
        except SystemExit:
            raise AssertionError("--force should have skipped the gate") from None
    finally:
        m._event_gate_results, m._tailscale_connect = orig_gate, orig_ts


def t_takeover_plan_relay_reachable_race():
    st = {"live": {"feed": "A", "stint": 5, "mode": "race"}}
    p = m.takeover_plan(st)
    assert p == {"stint": 5, "qualifying": False, "source": "relay"}


def t_takeover_plan_relay_reachable_qualifying():
    st = {"live": {"feed": "A", "stint": 1, "mode": "qualifying"}}
    assert m.takeover_plan(st)["qualifying"] is True


def t_takeover_plan_override_beats_relay():
    st = {"live": {"feed": "A", "stint": 5, "mode": "race"}}
    p = m.takeover_plan(st, stint_override=8)
    assert p == {"stint": 8, "qualifying": False, "source": "override"}


def t_takeover_plan_qualifying_flag_forces_mode():
    st = {"live": {"feed": "A", "stint": 5, "mode": "race"}}
    assert m.takeover_plan(st, qualifying_flag=True)["qualifying"] is True
    # override + flag
    assert m.takeover_plan(None, stint_override=3, qualifying_flag=True) == {
        "stint": 3, "qualifying": True, "source": "override"}


def t_takeover_plan_unreachable_no_override_is_sheet_none():
    assert m.takeover_plan(None) == {"stint": None, "qualifying": False, "source": "sheet"}
    # a status dict from an older relay without a live block also yields None
    assert m.takeover_plan({"feeds": {}})["stint"] is None


def t_league_guard():
    # same league -> allowed
    assert m.league_guard("SHEET1", "SHEET1", force=False) is None
    # mismatch -> blocked with a message naming both
    msg = m.league_guard("SHEETA", "SHEETB", force=False)
    assert msg and "SHEETA" in msg and "SHEETB" in msg
    # --force overrides
    assert m.league_guard("SHEETA", "SHEETB", force=True) is None
    # unknown id (older relay / unset) -> cannot verify, allow
    assert m.league_guard(None, "SHEETB", force=False) is None
    assert m.league_guard("SHEETA", "", force=False) is None


def t_event_takeover_routing():
    r = m.route(["event", "takeover", "100.64.1.2", "--stint", "5"])
    assert r["verb"] == "takeover" and r["rest"] == ["100.64.1.2", "--stint", "5"]


def _with_env(**kv):
    """Set env keys (None deletes), return a restore callable."""
    saved = dict(os.environ)
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return lambda: (os.environ.clear(), os.environ.update(saved))


def t_event_takeover_blocks_league_mismatch():
    orig = m._relay_fetch_json
    restore = _with_env(RACECAST_SHEET_ID="SHEET_B")
    m._relay_fetch_json = lambda url, timeout=3: {
        "league": {"sheet_id": "SHEET_A"}, "live": {"feed": "A", "stint": 3, "mode": "race"}}
    try:
        try:
            m.event_takeover(["100.64.1.2"])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "league mismatch" in str(e.code)
    finally:
        m._relay_fetch_json = orig
        restore()


def t_event_takeover_unreachable_without_stint_errors():
    orig = m._relay_fetch_json
    restore = _with_env(RACECAST_SHEET_ID=None, RACECAST_SHEET_PUSH_URL="x")
    def _boom(url, timeout=3):
        raise OSError("refused")
    m._relay_fetch_json = _boom
    try:
        try:
            m.event_takeover(["100.64.1.2"])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "--stint" in str(e.code)
    finally:
        m._relay_fetch_json = orig
        restore()


def t_event_takeover_success_calls_event_start():
    orig_fetch, orig_es, orig_chat = m._relay_fetch_json, m.event_start, m.chat_cmd
    restore = _with_env(RACECAST_SHEET_ID="S", RACECAST_SHEET_PUSH_URL="https://push")
    m._relay_fetch_json = lambda url, timeout=3: {
        "league": {"sheet_id": "S"}, "live": {"feed": "B", "stint": 7, "mode": "race"}}
    m.chat_cmd = lambda rest: None
    captured = {}
    m.event_start = lambda a: captured.__setitem__("args", a)
    try:
        m.event_takeover(["100.64.1.2"])
        assert captured["args"] == ["--stint", "7"]
    finally:
        m._relay_fetch_json, m.event_start, m.chat_cmd = orig_fetch, orig_es, orig_chat
        restore()


def t_event_takeover_qualifying_and_override_forwarded():
    orig_fetch, orig_es, orig_chat = m._relay_fetch_json, m.event_start, m.chat_cmd
    restore = _with_env(RACECAST_SHEET_ID="S", RACECAST_SHEET_PUSH_URL="https://push")
    m._relay_fetch_json = lambda url, timeout=3: {
        "league": {"sheet_id": "S"}, "live": {"feed": "A", "stint": 2, "mode": "race"}}
    m.chat_cmd = lambda rest: None
    captured = {}
    m.event_start = lambda a: captured.__setitem__("args", a)
    try:
        m.event_takeover(["100.64.1.2", "--stint", "9", "--qualifying"])
        assert captured["args"] == ["--stint", "9", "--qualifying"]   # override wins, mode forced
    finally:
        m._relay_fetch_json, m.event_start, m.chat_cmd = orig_fetch, orig_es, orig_chat
        restore()


def t_chat_routing():
    # verb is passed through in rest; route() does not validate it (chat_cmd does)
    assert m.route(["chat", "clear"]) == {"kind": "chat", "rest": ["clear"]}
    assert m.route(["chat", "export", "--out", "/tmp/x.json"]) == {
        "kind": "chat", "rest": ["export", "--out", "/tmp/x.json"]}
    assert m.route(["chat", "pull", "100.64.1.2"]) == {
        "kind": "chat", "rest": ["pull", "100.64.1.2"]}
    # bare "chat" (no verb) routes correctly; chat_cmd handles the usage error
    assert m.route(["chat"]) == {"kind": "chat", "rest": []}


def t_route_cockpit():
    assert m.route(["cockpit", "links"]) == {"kind": "cockpit", "rest": ["links"]}
    assert m.route(["cockpit", "enable"]) == {"kind": "cockpit", "rest": ["enable"]}
    assert m.route(["cockpit", "token", "revoke", "Alpha"]) == {
        "kind": "cockpit", "rest": ["token", "revoke", "Alpha"]}
    # cockpit validates the verb at route() time (unlike chat)
    for bad in (["cockpit"], ["cockpit", "bogus"]):
        try:
            m.route(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def t_cookies_twitch_routing():
    # "twitch" as the first token selects the Twitch export
    args = m._cookies_oneshot_args(["twitch", "firefox"])
    assert "--platform" in args and args[args.index("--platform") + 1] == "twitch"
    assert "firefox" in args
    # no leading "twitch" -> YouTube flow unchanged (no --platform injected)
    args2 = m._cookies_oneshot_args(["firefox"])
    assert "--platform" not in args2 and "firefox" in args2
    # empty list is unchanged
    assert m._cookies_oneshot_args([]) == []


def t_freeport_route():
    assert m.route(["freeport"]) == {"kind": "freeport", "rest": []}
    assert m.route(["freeport", "53001", "--force"]) == \
        {"kind": "freeport", "rest": ["53001", "--force"]}


def t_freeport_parse_args_defaults_and_flags():
    assert m.parse_freeport_args([]) == ([53001, 53002, 53003], False)
    assert m.parse_freeport_args(["53001"]) == ([53001], False)
    assert m.parse_freeport_args(["53002", "--force"]) == ([53002], True)
    assert m.parse_freeport_args(["-f", "53003"]) == ([53003], True)


def t_freeport_parse_args_rejects_bad_tokens():
    _raises(lambda: m.parse_freeport_args(["nope"]))
    _raises(lambda: m.parse_freeport_args(["70000"]))      # out of range
    _raises(lambda: m.parse_freeport_args(["--what"]))


def t_freeport_owner_running_relay_owns_feed_and_control_ports():
    assert m.freeport_owner(53001, relay_alive=True, static_alive_ports=set()) == "relay"
    assert m.freeport_owner(m.RELAY_PORT, relay_alive=True, static_alive_ports=set()) == "relay"
    # relay down -> not owned by the relay
    assert m.freeport_owner(53001, relay_alive=False, static_alive_ports=set()) is None


def t_freeport_owner_static_feed():
    assert m.freeport_owner(53002, relay_alive=False, static_alive_ports={53002}) == "streams"
    assert m.freeport_owner(53003, relay_alive=False, static_alive_ports={53002}) is None


def t_overlay_asset_serve_resolves_and_guards():
    # The builder canvas previews bundled HUD flags/brands offline (no relay).
    flag = m.overlay_asset_serve("flags", "belgium")
    assert flag and os.path.exists(flag[0]) and flag[1] == "image/svg+xml"
    brand = m.overlay_asset_serve("brands", "bmw")
    assert brand and os.path.exists(brand[0]) and brand[1] == "image/png"
    # strict key + subdir whitelist -> traversal / unknown sub / missing -> None
    assert m.overlay_asset_serve("flags", "../config") is None
    assert m.overlay_asset_serve("evil", "bmw") is None
    assert m.overlay_asset_serve("brands", "definitely-not-a-brand") is None
    assert m.overlay_asset_serve("flags", "Bel/gium") is None


def t_route_speedtest_is_oneshot():
    assert m.route(["speedtest"]) == {"kind": "oneshot", "command": "speedtest", "rest": []}
    assert m.route(["speedtest", "--json"]) == \
        {"kind": "oneshot", "command": "speedtest", "rest": ["--json"]}


def t_speedtest_is_a_runtime_dir_oneshot():
    # It must receive --runtime-dir <base> so history lands at the machine-level runtime.
    assert "speedtest" in m.RUNTIME_DIR_ONESHOTS
    assert m.ONESHOT_MAP["speedtest"] == "scripts/speedtest.py"


def t_speedtest_op_registered():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "ui"))
    import ui_ops
    assert ui_ops.OPS["speedtest"] == ["speedtest"]


def t_speedtest_data_shape():
    import tempfile
    d = tempfile.mkdtemp()
    # seed one record through the speedtest module the provider reads
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "scripts"))
    import speedtest as st
    st.append_record({"ts": 1, "download_mbps": 50.0, "upload_mbps": 20.0,
                      "ping_ms": 9.0, "jitter_ms": 1.0, "packet_loss": 0.0,
                      "server": "S", "isp": "I", "result_url": None}, d)
    out = m.speedtest_data(base_dir=d)
    assert out["ok"] is True
    assert out["latest"]["download_mbps"] == 50.0
    assert len(out["history"]) == 1
    # thresholds travel with the response so the UI badge can't drift from them
    assert out["thresholds"] == {"min_down": 25.0, "min_up": 10.0,
                                 "rec_down": 50.0, "rec_up": 20.0}


def t_companion_cmds_linux_uses_systemd_when_unit_present():
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


def _linux_companion_env(detect="companion", ts="100.64.1.2", run_calls=None):
    """Monkeypatch racecast for the Linux companion_start/stop branch. Returns
    (teardown, cl). `run_calls` collects argv passed to subprocess.run."""
    import companion_linux as cl
    saved = {
        "platform": m.sys.platform, "detect": cl.detect_unit,
        "ts": m._tailscale_ip, "run": m.subprocess.run,
        "running": m._companion_running,
    }
    m.sys.platform = "linux"
    cl.detect_unit = lambda *a, **k: detect
    m._tailscale_ip = lambda: ts
    m._companion_running = lambda cc: False

    class P:
        returncode = 0
    def fake_run(argv, **kw):
        if run_calls is not None:
            run_calls.append(argv)
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
    orig_exists = m.os.path.exists
    try:
        m.os.path.exists = lambda p: True   # helper present (enable-control done)
        m.companion_start(["auto"])
    finally:
        m.os.path.exists = orig_exists
        teardown()
    assert ["sudo", "-n", cl.HELPER_PATH, "100.64.1.2"] in calls


def t_companion_start_linux_falls_back_to_localhost_without_tailscale():
    calls = []
    teardown, cl = _linux_companion_env(ts=None, run_calls=calls)
    orig_exists = m.os.path.exists
    try:
        m.os.path.exists = lambda p: True
        m.companion_start(["auto"])
    finally:
        m.os.path.exists = orig_exists
        teardown()
    assert ["sudo", "-n", cl.HELPER_PATH, "127.0.0.1"] in calls


def t_companion_start_linux_guides_when_not_enabled():
    calls = []
    teardown, cl = _linux_companion_env(run_calls=calls)
    orig_exists = m.os.path.exists
    raised = False
    try:
        m.os.path.exists = lambda p: False  # helper absent -> enable-control needed
        try:
            m.companion_start(["auto"])
        except SystemExit:
            raised = True
    finally:
        m.os.path.exists = orig_exists
        teardown()
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


def t_companion_enable_control_routes():
    assert m.route(["companion", "enable-control"])["verb"] == "enable-control"


def t_companion_enable_control_is_dispatchable():
    assert ("companion", "enable-control") in m.DISPATCH


def t_function_local_peer_imports_are_frozen():
    """Every peer module racecast.py imports INSIDE a function (lazy import) must be
    declared as a PyInstaller --hidden-import in tools/build-binary.py. PyInstaller's
    static scan misses function-local imports, so a missing one makes the frozen
    binary raise ModuleNotFoundError at runtime — and binary-smoke won't catch a
    lazily-imported, error-swallowed path (this is how companion_linux slipped)."""
    import ast
    src_dir = os.path.join(ROOT, "src")
    scripts_dir = os.path.join(src_dir, "scripts")

    def is_peer(name):
        return (os.path.exists(os.path.join(scripts_dir, name + ".py"))
                or os.path.exists(os.path.join(src_dir, name + ".py")))

    with open(os.path.join(src_dir, "racecast.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    local_imports = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Import):
                    local_imports |= {a.name for a in node.names if is_peer(a.name)}

    with open(os.path.join(ROOT, "tools", "build-binary.py"), encoding="utf-8") as fh:
        build_src = fh.read()
    missing = sorted(m for m in local_imports if f'"{m}"' not in build_src)
    assert not missing, ("peer modules imported function-locally in racecast.py but "
                         f"not --hidden-import in tools/build-binary.py: {missing}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
