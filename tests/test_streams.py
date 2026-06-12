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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
