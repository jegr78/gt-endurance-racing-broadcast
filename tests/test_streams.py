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
loop = _load("loopstream", os.path.join("src", "scripts", "loopstream.py"))
feeds_x = _load("feeds_x", os.path.join("src", "relay", "racecast-feeds.py"))


def t_feed_argv_repo_uses_python():
    argv = start.feed_argv(False, "python3", os.path.join("x", "loopstream.py"),
                           "UC123", "53001")
    assert argv == ["python3", os.path.join("x", "loopstream.py"), "UC123", "53001"]


def t_feed_argv_frozen_reinvokes_binary():
    argv = start.feed_argv(True, os.path.join("apps", "racecast"), "ignored", "UC123", "53001")
    assert argv == [os.path.join("apps", "racecast"), "streams", "run-feed", "UC123", "53001"]


def t_state_dirs_match():
    repo = os.path.join(ROOT, "src", "scripts")
    assert start.state_dir(repo) == stop.state_dir(repo)
    dist = os.path.join("pkg", "scripts")  # distributed-package layout
    assert start.state_dir(dist) == stop.state_dir(dist) == dist


def t_feed_env_repo_inherits():
    assert start.feed_env(False, {"A": "1"}) is None  # None -> Popen inherits


def t_feed_env_frozen_resets_pyinstaller():
    env = start.feed_env(True, {"A": "1"})
    assert env["A"] == "1"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def t_feed_process_matchers():
    # POSIX `ps -o command=` lines
    assert stop.looks_like_feed("python3 /x/loopstream.py UC1 53001")
    assert stop.looks_like_feed("/usr/local/bin/streamlink --player-external-http ...")
    assert stop.looks_like_feed("/apps/racecast streams run-feed UC1 53001")  # frozen child
    assert not stop.looks_like_feed("/usr/bin/vim notes.txt")
    assert not stop.looks_like_feed("python3 some_other_tool.py")  # bare python on POSIX is NOT a feed
    # Windows `tasklist` CSV-ish output
    assert stop.looks_like_feed('"python.exe","123",...', windows=True)
    assert stop.looks_like_feed('"streamlink.exe","123",...', windows=True)
    assert stop.looks_like_feed('"racecast.exe","123",...', windows=True)   # frozen child
    assert not stop.looks_like_feed('"notepad.exe","123",...', windows=True)


def t_load_feeds_falls_back_to_builtin():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert start.load_feeds(d) == start.FEEDS        # no streams.json -> built-in


def t_load_feeds_reads_config():
    import json, tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "streams.json"), "w") as fh:
            json.dump([{"label": "X", "channel": "UC9", "port": "53005"},
                       {"channel": "UC8", "port": "53006"}], fh)
        assert start.load_feeds(d) == [("UC9", "53005"), ("UC8", "53006")]


def t_load_feeds_skips_incomplete_and_bad_json():
    import json, tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "streams.json")
        with open(p, "w") as fh:
            json.dump([{"channel": "UC9", "port": ""},      # no port -> skip
                       {"channel": "", "port": "53006"},    # no channel -> skip
                       {"channel": "UC7", "port": "53007"}], fh)
        assert start.load_feeds(d) == [("UC7", "53007")]
        with open(p, "w") as fh:
            fh.write("not json")                            # malformed -> FEEDS
        assert start.load_feeds(d) == start.FEEDS


def t_loop_no_window_kwargs_per_os():
    # A static feed runs DETACHED (no console — start_streams' spawn_kwargs), so
    # its streamlink child would otherwise pop a PERSISTENT terminal window on
    # Windows. CREATE_NO_WINDOW only on Windows; no-op elsewhere.
    assert loop.no_window_kwargs("nt") == {"creationflags": 0x08000000}
    assert loop.no_window_kwargs("posix") == {}
    assert loop.no_window_kwargs("java") == {}


def t_loop_streamlink_argv_serves_the_port():
    argv = loop.streamlink_argv("https://www.youtube.com/channel/UC9/live", "53005")
    assert argv[0] == "streamlink"
    assert "https://www.youtube.com/channel/UC9/live" in argv
    assert "--player-external-http-port" in argv and "53005" in argv


def t_loop_serve_once_passes_no_window():
    # The feed's stdout is redirected to a log by start_streams, so the flag
    # suppresses the window without losing logged output.
    captured = {}

    def fake_call(argv, **kw):
        captured["argv"], captured["kw"] = argv, kw
        return 0

    assert loop.serve_once("https://x/live", "53005", call=fake_call) == 0
    assert captured["argv"][0] == "streamlink"
    for k, v in loop.no_window_kwargs().items():
        assert captured["kw"].get(k) == v


def t_loop_youtube_argv_unchanged():
    argv = loop.streamlink_argv("https://www.youtube.com/channel/UC123/live", "53001")
    assert "--twitch-low-latency" not in argv
    assert "1080p60,1080p,720p60,720p" in argv          # static's YouTube quality preserved
    assert "--hls-live-edge" in argv and argv[argv.index("--hls-live-edge")+1] == "4"


def t_loop_twitch_argv():
    argv = loop.streamlink_argv("https://www.twitch.tv/chan", "53002", platform="twitch")
    assert "--twitch-low-latency" in argv
    assert argv[argv.index("--hls-live-edge")+1] == "2"
    assert "--twitch-disable-ads" not in argv
    assert argv[-2:] == ["https://www.twitch.tv/chan", "best"]
    assert "--" in argv and argv.index("--") < argv.index("https://www.twitch.tv/chan")


def t_loop_twitch_argv_token():
    argv = loop.streamlink_argv("https://www.twitch.tv/chan", "53002",
                                platform="twitch", twitch_token="abc123")
    i = argv.index("--twitch-api-header")
    assert argv[i+1] == "Authorization=OAuth abc123"
    assert i < argv.index("--")


def t_loop_channel_url_and_platform():
    assert loop.channel_url("UC123").startswith("https://www.youtube.com/channel/UC123/live")
    assert loop.channel_url("https://www.twitch.tv/x") == "https://www.twitch.tv/x"
    assert loop.platform_of("https://www.twitch.tv/x") == "twitch"
    assert loop.platform_of("UCabc") == "youtube"   # bare id -> no scheme -> host empty -> youtube


def t_loop_crosscheck_relay():
    # anti-divergence: the duplicated Twitch bits must equal the relay's
    assert loop.STREAMLINK_TWITCH == feeds_x.STREAMLINK_TWITCH
    for u in ["https://www.youtube.com/watch?v=a", "https://youtu.be/a",
              "https://www.twitch.tv/c", "https://m.twitch.tv/c", "https://twitch.tv@evil.com/"]:
        assert loop.platform_of(u) == feeds_x.platform_of(u)
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "twitch-cookies.txt")
    with open(p, "w") as f:
        f.write(".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\tdeadbeef\n")
    assert loop.twitch_oauth_from_cookies(p) == feeds_x.twitch_oauth_from_cookies(p) == "deadbeef"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
