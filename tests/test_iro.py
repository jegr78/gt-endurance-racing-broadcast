#!/usr/bin/env python3
"""Stdlib checks for the racecast dispatcher routing. Run: python3 tests/test_iro.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("iro", os.path.join(ROOT, "src", "racecast.py"))
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


def t_obs_refresh_route():
    assert m.route(["obs", "refresh"]) == \
        {"kind": "service", "command": "obs", "verb": "refresh", "rest": []}


def t_obs_bad_verb_raises():
    _raises(lambda: m.route(["obs"]))
    _raises(lambda: m.route(["obs", "bogus"]))


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
        seen.append(p); return "/Users/x/IRO/iro-ui.app/Contents/MacOS/iro-ui"
    tl = "/private/var/folders/pk/T/AppTranslocation/UUID/d/iro-ui.app/Contents/MacOS/iro-ui"
    assert m._untranslocate(tl, frozen=False, platform="darwin", resolver=resolver) == tl
    assert m._untranslocate(tl, frozen=True, platform="linux", resolver=resolver) == tl
    assert seen == []
    # frozen + macOS: map the translocated path back to its real on-disk location.
    assert m._untranslocate(tl, frozen=True, platform="darwin", resolver=resolver) == \
        "/Users/x/IRO/iro-ui.app/Contents/MacOS/iro-ui"
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
    assert m._runtime_base(True, os.path.join("apps", "iro"), "ignored") == \
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
    text = "# comment\nRACECAST_SHEET_ID=abc\nIRO_TIMER_URL='http://x'\n\nnot a pair\n"
    assert m.parse_env_text(text) == {"RACECAST_SHEET_ID": "abc", "IRO_TIMER_URL": "http://x"}


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
    R = os.path.join("x", "runtime", "iro")   # profile runtime
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
    assert m._oneshot_extra("update", [], "/rt/iro", "/rt") == []


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
    m.sv.stop_pid = lambda pid, path: (calls.append("stop_pid"), True)[1]
    m._release_obs_feeds = lambda: calls.append("obs")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m.relay_stop([])
        assert calls == ["stop_pid", "obs"]
    finally:
        m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds = old


def t_relay_stop_skips_obs_release_when_kill_failed():
    # Relay may still be alive -> a rebuild would reconnect. Don't release.
    import io, contextlib
    calls = []
    old = (m.sv.read_pid, m.sv.pid_alive, m.sv.stop_pid, m._release_obs_feeds)
    m.sv.read_pid = lambda path: 4242
    m.sv.pid_alive = lambda pid: True
    m.sv.stop_pid = lambda pid, path: (calls.append("stop_pid"), False)[1]
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
    assert m._env_base(True, "/opt/iro/iro", "/tmp/_MEIxx/src") == "/opt/iro"
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
    pages = {"/hud": b"HUD", "/timer": b"TIMER"}
    expected = hashlib.sha256(b"HUDTIMER").hexdigest()
    assert m.served_pages_hash(fetch=lambda p: pages[p]) == expected


def t_served_pages_hash_none_when_any_fetch_fails():
    def fetch(path):
        if path == "/timer":
            raise OSError("connection refused")
        return b"HUD"
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
    rd = os.path.join("R", "iro")   # profile runtime
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
        profile="iro", name="IRO", sheet_id="abc",
        sheet_push_url="", intro_url="https://i", outro_url="")
    assert m._profile_env_vars(rc) == {
        "RACECAST_SHEET_ID": "abc", "RACECAST_INTRO_URL": "https://i"}


def t_profile_env_vars_includes_obs_collection():
    rc = m.pcfg.ResolvedConfig(profile="iro", name="IRO Endurance", sheet_id="abc",
                               obs_collection="IRO Broadcast")
    out = m._profile_env_vars(rc)
    assert out["RACECAST_OBS_COLLECTION"] == "IRO Broadcast"


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
    assert m._profile_runtime("/r", "iro") == os.path.join("/r", "iro")
    assert m._profile_runtime("/r", "erf") == os.path.join("/r", "erf")
    assert m._profile_runtime("/r", None) == "/r"


def t_profiles_data_lists_active_and_available():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "iro"))
        os.makedirs(os.path.join(prof, "erf"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "iro", "profile.env"), "w") as fh:
            fh.write("NAME=IRO Endurance\nSHEET_ID=abc\n")
        with open(os.path.join(prof, "erf", "profile.env"), "w") as fh:
            fh.write("NAME=ERF\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True
        assert d["active"] == "iro"
        names = {p["name"]: p for p in d["profiles"]}
        assert names["iro"]["display"] == "IRO Endurance"
        assert names["iro"]["sheet_set"] is True
        assert names["erf"]["sheet_set"] is False


def t_profile_use_data_switches_pointer():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("SHEET_ID=abc\n")
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_use_data("iro")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d == {"ok": True, "active": "iro"}
        with open(os.path.join(td, "runtime", "active-profile")) as fh:
            assert fh.read().strip() == "iro"


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


def t_profile_new_data_bad_name_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "profiles", "example"))
        open(os.path.join(td, ".env.example"), "w").close()
        open(os.path.join(td, "profiles", "example", "profile.env"), "w").close()
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("../evil", "example")
        finally:
            m._env_base = orig_b
        assert d["ok"] is False and d["error"]


def t_profile_env_entries_data_reads_active():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# comment\nSHEET_ID=abc\nNAME=IRO\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_entries_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True and d["active"] == "iro"
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
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# keep me\nSHEET_ID=old\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
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
