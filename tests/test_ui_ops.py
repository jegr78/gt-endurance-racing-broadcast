#!/usr/bin/env python3
"""Stdlib checks for the Control Center's structured status providers in iro.py.
Run: python3 tests/test_ui_ops.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import iro
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_ops


# ---------- relay ----------

def t_relay_status_data_running():
    d = iro.relay_status_data(read_pid=lambda p: 4242,
                              alive=lambda pid: True,
                              http_ok=lambda: True)
    assert d == {"pid": 4242, "alive": True, "port": 8088, "http_ok": True}


def t_relay_status_data_stopped_skips_http_probe():
    probed = []
    d = iro.relay_status_data(read_pid=lambda p: None,
                              alive=lambda pid: False,
                              http_ok=lambda: probed.append(1) or True)
    assert d == {"pid": None, "alive": False, "port": 8088, "http_ok": False}
    assert probed == []   # never probe HTTP for a dead relay


def t_relay_extra_text_ok_with_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": True}
    text = iro._relay_extra_text(d, "100.64.0.7")
    assert "control http://127.0.0.1:8088/status OK" in text
    assert "tablet/panel http://100.64.0.7:8088/panel" in text


def t_relay_extra_text_port_down_no_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": False}
    text = iro._relay_extra_text(d, None)
    assert text == "(port 8088 not responding)"


def t_relay_extra_text_ok_no_tailscale():
    d = {"pid": 1, "alive": True, "port": 8088, "http_ok": True}
    assert iro._relay_extra_text(d, None) == "control http://127.0.0.1:8088/status OK"


# ---------- companion ----------

def t_companion_payload_running_with_config():
    d = iro.companion_status_payload(True, True,
                                     {"bind_ip": "100.64.0.7", "http_port": 8000})
    assert d == {"supported": True, "running": True,
                 "url": "http://100.64.0.7:8000/tablet", "why": ""}


def t_companion_payload_running_no_config():
    d = iro.companion_status_payload(True, True, None)
    assert d["running"] is True and d["url"] is None


def t_companion_payload_unsupported():
    d = iro.companion_status_payload(False, False, None, "(manual on linux)")
    assert d == {"supported": False, "running": False, "url": None,
                 "why": "(manual on linux)"}


# ---------- streams ----------

def t_streams_status_data_labels(tmp):
    p1 = os.path.join(tmp, "feed_53001.pid")
    with open(p1, "w") as fh:
        fh.write(str(os.getpid()))          # a live PID -> alive True
    p2 = os.path.join(tmp, "feed_53002.pid")
    with open(p2, "w") as fh:
        fh.write("garbage")                 # unreadable -> pid None, alive False
    feeds = iro.streams_status_data(pidfiles=[p1, p2])
    assert feeds == [
        {"label": "53001", "pid": os.getpid(), "alive": True},
        {"label": "53002", "pid": None, "alive": False}]


def t_streams_status_data_empty():
    assert iro.streams_status_data(pidfiles=[]) == []


# ---------- aggregate payload ----------

def t_ui_status_payload_shape():
    payload = iro.ui_status_payload(
        relay=lambda: {"alive": False}, companion=lambda: {"running": False},
        streams=lambda: [], tailscale=lambda: None,
        cookies=lambda: {"level": "WARN", "detail": "x"})
    assert payload == {"version": iro.version(), "relay": {"alive": False},
                       "companion": {"running": False}, "streams": [],
                       "tailscale_ip": None,
                       "cookies": {"level": "WARN", "detail": "x"}}


# ---------- ui_ops registry ----------

def t_ops_registry_shape():
    assert ui_ops.OPS["relay-start"] == ["relay", "start"]
    assert ui_ops.OPS["obs-refresh"] == ["obs", "refresh"]
    for name, argv in ui_ops.OPS.items():
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), name


def t_job_argv_repo_mode():
    argv = ui_ops.job_argv(["relay", "start"], frozen=False,
                           executable="/usr/bin/python3", iro_script="/repo/src/iro.py")
    assert argv == ["/usr/bin/python3", "/repo/src/iro.py", "relay", "start"]


def t_job_argv_frozen_reinvokes_binary():
    argv = ui_ops.job_argv(["relay", "stop"], frozen=True,
                           executable="/opt/iro/iro", iro_script="/ignored")
    assert argv == ["/opt/iro/iro", "relay", "stop"]


def t_ops_registry_routes_in_iro():
    # every registry entry must be a valid iro invocation (service verb,
    # oneshot, or export) — route() raises ValueError on anything unknown
    for name, argv in ui_ops.OPS.items():
        action = iro.route(list(argv))
        assert action["kind"] in ("service", "oneshot", "export"), name


def t_build_argv_plain_and_unknown():
    assert ui_ops.build_argv("relay-start") == ["relay", "start"]
    try:
        ui_ops.build_argv("not-an-op")
        raise AssertionError("unknown op accepted")
    except ValueError:
        pass


def t_build_argv_cookies_browser():
    assert ui_ops.build_argv("cookies", {"browser": "firefox"}) == ["cookies", "firefox"]
    assert ui_ops.build_argv("cookies") == ["cookies"]        # browser optional
    try:
        ui_ops.build_argv("cookies", {"browser": "lynx; rm -rf /"})
        raise AssertionError("invalid browser accepted")
    except ValueError:
        pass


def t_build_argv_event_stint():
    assert ui_ops.build_argv("event-start", {"stint": "4"}) == \
        ["event", "start", "--stint", "4"]
    assert ui_ops.build_argv("event-start", {"stint": ""}) == ["event", "start"]
    for bad in ("0", "-1", "abc", "1.5", "٤", "²"):
        try:
            ui_ops.build_argv("event-start", {"stint": bad})
            raise AssertionError(f"invalid stint accepted: {bad}")
        except ValueError:
            pass


def t_build_argv_update_flag():
    assert ui_ops.build_argv("install-tools", {"update": True}) == \
        ["install-tools", "--yes", "--update"]
    assert ui_ops.build_argv("install-tools", {"update": False}) == \
        ["install-tools", "--yes"]
    assert ui_ops.build_argv("install-apps", {"update": True}) == \
        ["install-apps", "--yes", "--update"]
    assert ui_ops.build_argv("install-apps", {"update": False}) == \
        ["install-apps", "--yes"]


def t_build_argv_rejects_unknown_params():
    try:
        ui_ops.build_argv("relay-start", {"stint": "4"})
        raise AssertionError("param on paramless op accepted")
    except ValueError:
        pass


# ---------- readiness data ----------

def t_cookies_status_data_shape():
    class R:
        level, detail = "PASS", "fresh (1 h old)"
    d = iro.cookies_status_data(status=lambda: R())
    assert d == {"level": "PASS", "detail": "fresh (1 h old)"}


def t_cookies_status_data_never_raises():
    def boom():
        raise RuntimeError("probe broke")
    d = iro.cookies_status_data(status=boom)
    assert d["level"] == "WARN" and "probe broke" in d["detail"]


def t_assets_status_data_complete(tmp):
    d = iro.assets_status_data(state=lambda ev: (tmp, tmp, [], []))
    assert d["ok"] is True
    assert d["graphics"]["level"] == "PASS" and d["media"]["level"] == "PASS"


def t_assets_status_data_missing_and_unverified(tmp):
    # graphics: sheet readable, one file missing -> FAIL with the filename;
    # media: sheet unreadable (None) + empty local dir -> its severity (WARN)
    d = iro.assets_status_data(state=lambda ev: (tmp, tmp, ["Overlay.png"], None))
    assert d["graphics"]["level"] == "FAIL"
    assert "Overlay.png" in d["graphics"]["detail"]
    assert d["media"]["level"] == "WARN"


def t_assets_status_data_error():
    def boom(ev):
        raise RuntimeError("no sheet")
    d = iro.assets_status_data(state=boom)
    assert d["ok"] is False and "no sheet" in d["error"]


# ---------- tools / apps / preflight readiness ----------

def t_tools_status_data_mixed():
    d = iro.tools_status_data(
        which=lambda n: "/usr/bin/" + n if n in ("yt-dlp", "ffmpeg") else None,
        version=lambda n: n + " 1.2.3")
    assert d["ok"] is True
    by = {t["name"]: t for t in d["tools"]}
    assert by["yt-dlp"]["installed"] is True and by["yt-dlp"]["version"] == "yt-dlp 1.2.3"
    assert by["streamlink"]["installed"] is False and by["streamlink"]["version"] is None
    # every canonical tool is represented
    assert {t["name"] for t in d["tools"]} >= {"yt-dlp", "streamlink", "ffmpeg", "deno"}


def t_tools_status_data_error():
    def boom(n):
        raise RuntimeError("which broke")
    d = iro.tools_status_data(which=boom)
    assert d["ok"] is False and "which broke" in d["error"]


def t_apps_status_data_shape():
    d = iro.apps_status_data(present=lambda app: app == "obs")
    assert d["ok"] is True
    by = {a["name"]: a["installed"] for a in d["apps"]}
    assert by["obs"] is True and by["companion"] is False
    assert {a["name"] for a in d["apps"]} >= {"obs", "companion", "tailscale", "discord"}


def t_apps_status_data_error():
    def boom(app):
        raise RuntimeError("probe broke")
    d = iro.apps_status_data(present=boom)
    assert d["ok"] is False and "probe broke" in d["error"]


def t_preflight_data_sections():
    class R:
        def __init__(self, level, name, detail):
            self.level, self.name, self.detail = level, name, detail
    fake = [("Hardware", [R("PASS", "RAM", "32 GB"), R("WARN", "Swap", "in use")]),
            ("Tool chain", [R("FAIL", "ffmpeg", "missing")])]
    d = iro.preflight_data(gather=lambda: fake)
    assert d["ok"] is True
    assert d["sections"][0]["title"] == "Hardware"
    assert d["sections"][0]["results"][0] == {"level": "PASS", "name": "RAM", "detail": "32 GB"}
    assert d["sections"][1]["results"][0]["level"] == "FAIL"


def t_preflight_data_error():
    def boom():
        raise RuntimeError("no preflight")
    d = iro.preflight_data(gather=boom)
    assert d["ok"] is False and "no preflight" in d["error"]


def t_assets_files_data_lists(tmp):
    g = os.path.join(tmp, "graphics")
    m = os.path.join(tmp, "media")
    os.makedirs(g)
    os.makedirs(m)
    open(os.path.join(g, "Overlay.png"), "w").close()
    open(os.path.join(g, "Standings.png"), "w").close()
    open(os.path.join(g, "notes.txt"), "w").close()      # non-image: ignored
    open(os.path.join(m, "intro.mp4"), "w").close()
    d = iro.assets_files_data(roots={"graphics": g, "media": m})
    assert d["ok"] is True
    assert d["graphics"] == ["Overlay.png", "Standings.png"]   # sorted, .txt dropped
    assert d["media"] == ["intro.mp4"]


def t_assets_files_data_missing_dirs(tmp):
    d = iro.assets_files_data(roots={"graphics": os.path.join(tmp, "nope"),
                                     "media": os.path.join(tmp, "nope2")})
    assert d["ok"] is True and d["graphics"] == [] and d["media"] == []


def t_assets_files_data_error():
    d = iro.assets_files_data(roots={})        # missing keys -> KeyError, caught
    assert d["ok"] is False and "error" in d


if __name__ == "__main__":
    import inspect, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                # parameterized tests get exactly one positional arg: the tempdir
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
