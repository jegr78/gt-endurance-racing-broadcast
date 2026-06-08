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
        cookies=lambda: {"level": "WARN", "detail": "x"},
        apps_running=lambda: {"obs": False, "discord": False})
    assert payload == {"version": iro.version(), "relay": {"alive": False},
                       "companion": {"running": False}, "streams": [],
                       "tailscale_ip": None,
                       "cookies": {"level": "WARN", "detail": "x"},
                       "apps_running": {"obs": False, "discord": False}}


def t_running_apps_data_probe():
    d = iro.running_apps_data(probe=lambda app: app == "obs")
    assert d == {"obs": True, "discord": False}


def t_running_apps_data_never_raises():
    def boom(app):
        raise RuntimeError("pgrep broke")
    d = iro.running_apps_data(probe=boom)
    assert d == {"obs": False, "discord": False}


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


# ---------- .env settings editor ----------

def t_env_entries_data_reads(tmp):
    p = os.path.join(tmp, ".env")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# comment\nIRO_SHEET_ID=abc\nIRO_UI_PORT=8090\n")
    d = iro.env_entries_data(path=p)
    assert d["ok"] is True and d["path"] == p
    assert d["entries"] == [{"key": "IRO_SHEET_ID", "value": "abc"},
                            {"key": "IRO_UI_PORT", "value": "8090"}]


def t_env_entries_data_missing_file(tmp):
    d = iro.env_entries_data(path=os.path.join(tmp, "nope.env"))
    assert d["ok"] is True and d["entries"] == []


def t_env_write_preserves_comments_and_round_trips(tmp):
    p = os.path.join(tmp, ".env")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# header\nIRO_SHEET_ID=old\n\n# port note\nIRO_UI_PORT=8089\n")
    res = iro.env_write_data([{"key": "IRO_SHEET_ID", "value": "new"},
                              {"key": "IRO_NEW", "value": "x"}], path=p)
    assert res["ok"] is True
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    assert "# header" in text and "# port note" in text     # comments kept
    assert "IRO_SHEET_ID=new" in text                       # updated in place
    assert "IRO_UI_PORT" not in text                        # removed
    assert "IRO_NEW=x" in text                              # appended
    back = iro.env_entries_data(path=p)["entries"]
    assert {"key": "IRO_SHEET_ID", "value": "new"} in back
    assert {"key": "IRO_NEW", "value": "x"} in back


def t_env_write_rejects_bad_key(tmp):
    res = iro.env_write_data([{"key": "bad key", "value": "x"}],
                             path=os.path.join(tmp, ".env"))
    assert res["ok"] is False and "invalid key" in res["error"]


def t_env_write_rejects_duplicate_and_newline(tmp):
    p = os.path.join(tmp, ".env")
    r1 = iro.env_write_data([{"key": "A", "value": "1"}, {"key": "A", "value": "2"}], path=p)
    assert r1["ok"] is False and "duplicate" in r1["error"]
    r2 = iro.env_write_data([{"key": "A", "value": "a\nb"}], path=p)
    assert r2["ok"] is False and "line break" in r2["error"]


def t_env_write_drops_blank_rows(tmp):
    p = os.path.join(tmp, ".env")
    res = iro.env_write_data([{"key": "", "value": ""},
                              {"key": "A", "value": "1"}], path=p)
    assert res["ok"] is True
    assert iro.env_entries_data(path=p)["entries"] == [{"key": "A", "value": "1"}]


# ---------- relay live stats (Home dashboard) ----------

def t_relay_live_data_safe_subset():
    # The relay /status carries channel/url fields per feed; relay_live_data
    # must surface ONLY the stint + state (screenshot/share safe).
    def fetch(url):
        if url.endswith("/status"):
            return {"schedule_len": 12, "feeds": {
                "A": {"stint": 3, "state": "serving", "channel": "secret-handle",
                      "index": 2, "port": 53001},
                "B": {"stint": 4, "state": "serving", "channel": "other"}}}
        return {"mode": "running", "visible": True, "end": 1000.0,
                "server_now": 940.0, "remaining_s": None, "duration_s": 3600}
    d = iro.relay_live_data(fetch=fetch, started=lambda: 100.0)
    assert d["ok"] is True and d["schedule_len"] == 12
    assert d["feeds"] == [{"feed": "A", "stint": 3, "state": "serving"},
                          {"feed": "B", "stint": 4, "state": "serving"}]
    blob = repr(d)
    assert "channel" not in blob and "secret-handle" not in blob
    assert d["timer"]["mode"] == "running" and d["timer"]["end"] == 1000.0
    assert isinstance(d["uptime_s"], int) and d["uptime_s"] >= 0


def t_relay_live_data_unreachable():
    def boom(url):
        raise OSError("connection refused")
    assert iro.relay_live_data(fetch=boom) == {"ok": False}


def t_relay_live_data_never_raises_on_garbage():
    assert iro.relay_live_data(fetch=lambda url: "not-a-dict") == {"ok": False}


# ---------- self-update check (UI wrapper over scripts/update.py) ----------

def _release(tag, with_asset=True):
    """A GitHub latest-release payload shaped like update.classify expects."""
    rel = {"tag_name": tag, "assets": []}
    if with_asset:
        rel["assets"] = [{"name": "iro-windows.zip", "browser_download_url": "u"},
                         {"name": "iro-macos.tar.gz", "browser_download_url": "u"},
                         {"name": "iro-linux.tar.gz", "browser_download_url": "u"}]
    return rel


def t_update_check_newer_available():
    d = iro.update_check_data(fetch=lambda: _release("v1.3.0"), current="v1.2.0",
                              platform="darwin")
    assert d["ok"] and d["update_available"] is True
    assert d["latest"] == "v1.3.0" and d["current"] == "v1.2.0"
    assert "releases/latest" in d["releases_url"]


def t_update_check_building_counts_as_available():
    # newer tag, platform asset not uploaded yet -> still "update available"
    d = iro.update_check_data(fetch=lambda: _release("v1.3.0", with_asset=False),
                              current="v1.2.0", platform="darwin")
    assert d["ok"] and d["update_available"] is True and d["latest"] == "v1.3.0"


def t_update_check_up_to_date():
    d = iro.update_check_data(fetch=lambda: _release("v1.2.0"), current="v1.2.0",
                              platform="darwin")
    assert d["ok"] and d["update_available"] is False and d["latest"] == "v1.2.0"


def t_update_check_dev_build_skips():
    d = iro.update_check_data(fetch=lambda: _release("v9.9.9"), current="dev")
    assert d["ok"] and d["update_available"] is False and d["latest"] is None


def t_update_check_offline_is_not_ok():
    def boom():
        raise OSError("offline")
    d = iro.update_check_data(fetch=boom, current="v1.2.0")
    assert d["ok"] is False and d["update_available"] is False


# ---------- static-streams config (Static Streams page) ----------

def t_streams_config_defaults_when_absent():
    d = iro.streams_config_data(path="/nope/streams.json",
                                default=lambda: [{"label": "Feed A",
                                                  "channel": "UC1", "port": "53001"}])
    assert d["ok"] and d["entries"][0]["port"] == "53001"


def t_streams_config_round_trip(tmp):
    p = os.path.join(tmp, "streams.json")
    res = iro.streams_config_write_data(
        [{"label": "Feed A", "channel": "UC9", "port": "53001"},
         {"label": "", "channel": "UC8", "port": "53002"}], path=p)
    assert res["ok"] is True
    back = iro.streams_config_data(path=p)["entries"]
    assert [e["channel"] for e in back] == ["UC9", "UC8"]
    assert [e["port"] for e in back] == ["53001", "53002"]


def t_streams_config_validation():
    ok, err = iro._validate_streams_entries(
        [{"channel": "UC1", "port": "53001"}, {"channel": "", "port": ""}])
    assert err is None and len(ok) == 1                 # blank row dropped
    _bad, err = iro._validate_streams_entries([{"channel": "UC1", "port": "x"}])
    assert err and "number" in err
    _bad, err = iro._validate_streams_entries([{"channel": "", "port": "53001"}])
    assert err and "channel" in err
    _bad, err = iro._validate_streams_entries(
        [{"channel": "UC1", "port": "53001"}, {"channel": "UC2", "port": "53001"}])
    assert err and "duplicate" in err


def t_streams_config_write_rejects_bad(tmp):
    p = os.path.join(tmp, "streams_reject.json")
    res = iro.streams_config_write_data([{"channel": "UC1", "port": "x"}], path=p)
    assert res["ok"] is False and "number" in res["error"]
    assert not os.path.exists(p)                        # nothing written on error


def t_obs_ws_link_data_from_config(tmp):
    import json
    cfg = os.path.join(tmp, "obs-ws-config.json")
    with open(cfg, "w") as fh:
        json.dump({"server_port": 4466, "server_password": "secret-pw",
                   "auth_required": True}, fh)
    d = iro.obs_ws_link_data(env={}, config_path=cfg)
    assert d["ok"] and d["ip"] == "127.0.0.1" and d["port"] == 4466
    assert d["password"] == "secret-pw" and d["auth_required"] is True


def t_obs_ws_link_data_env_override(tmp):
    import json
    cfg = os.path.join(tmp, "obs-ws-config2.json")
    with open(cfg, "w") as fh:
        json.dump({"server_port": 4455, "server_password": "stored"}, fh)
    d = iro.obs_ws_link_data(env={"IRO_OBS_WS_PASSWORD": "override"}, config_path=cfg)
    assert d["password"] == "override"          # env wins over the stored password


def t_obs_ws_link_data_missing_config():
    d = iro.obs_ws_link_data(env={}, config_path="/nope/obs.json")
    assert d["ok"] and d["port"] == 4455 and d["password"] is None


def t_docs_data_lists_present_only(tmp):
    # only docs that exist on disk are listed; wiki URLs always present
    base = os.path.join(tmp, "docs_data")
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "IRO_cheat_sheets.html"), "w").close()
    def resolve(rel):
        return os.path.join(base, os.path.basename(rel))
    d = iro.docs_data(resolve=resolve)
    keys = [x["key"] for x in d["local"]]
    assert keys == ["cheat-sheet"]                       # only the html exists
    assert d["local"][0]["kind"] == "html"
    assert "/wiki" in d["wiki_url"] and "Director-Setup" in d["director_url"]


def t_docs_file_path_allowlist(tmp):
    base = os.path.join(tmp, "docs_path")
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "IRO_cheat_sheets.html"), "w").close()
    def resolve(rel):
        return os.path.join(base, os.path.basename(rel))
    assert iro.docs_file_path("cheat-sheet", resolve=resolve).endswith(
        "IRO_cheat_sheets.html")
    assert iro.docs_file_path("setup-guide", resolve=resolve) is None  # not on disk
    assert iro.docs_file_path("../../etc/passwd", resolve=resolve) is None
    assert iro.docs_file_path("unknown", resolve=resolve) is None


def t_docs_content_html_passthrough_and_md_rendered(tmp):
    base = os.path.join(tmp, "docs_content")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "IRO_cheat_sheets.html"), "w") as fh:
        fh.write("<html><body>cheat</body></html>")
    with open(os.path.join(base, "README_SETUP.md"), "w") as fh:
        fh.write("# Title\n\n| A | B |\n|--|--|\n| 1 | 2 |\n")
    def resolve(rel):
        return os.path.join(base, os.path.basename(rel))
    ctype, body = iro.docs_content("cheat-sheet", resolve=resolve)
    assert ctype.startswith("text/html") and body == b"<html><body>cheat</body></html>"
    ctype, body = iro.docs_content("setup-readme", resolve=resolve)
    text = body.decode("utf-8")
    assert ctype.startswith("text/html")
    assert "<!doctype html>" in text and "<h1>Title</h1>" in text and "<table>" in text
    assert iro.docs_content("unknown", resolve=resolve) is None


def t_app_control_ops_route():
    for name in ("obs-start", "obs-stop", "discord-start", "discord-stop",
                 "tailscale-start", "tailscale-stop"):
        assert iro.route(list(ui_ops.OPS[name]))["kind"] == "service"


# ---------- init wizard providers ----------

def t_init_plan_data_shape_and_safety():
    steps = [
        {"key": "env", "label": ".env", "done": lambda: "IRO_SHEET_ID set"},
        {"key": "cookies", "label": "cookies", "done": lambda: None},
        {"key": "preflight", "label": "preflight", "done": lambda: None},
    ]
    out = iro.init_plan_data(steps, iro.ins.STEP_KINDS, browser="chrome",
                             next_steps=["import the OBS collection"])
    assert out["ok"] is True
    by_key = {s["key"]: s for s in out["steps"]}
    assert by_key["env"]["done"] is True
    assert by_key["env"]["kind"] == "gate"
    assert by_key["cookies"]["done"] is False
    assert by_key["cookies"]["op"] == "cookies"
    # browser is interpolated into the instruction
    assert "chrome" in by_key["cookies"]["instruction"]
    assert out["next_steps"] == ["import the OBS collection"]


def t_init_plan_data_never_raises_on_probe_error():
    def boom():
        raise RuntimeError("sheet down")
    steps = [{"key": "graphics", "label": "graphics", "done": boom}]
    out = iro.init_plan_data(steps, iro.ins.STEP_KINDS, browser="firefox",
                             next_steps=[])
    assert out["ok"] is True
    assert out["steps"][0]["done"] is False


def t_init_step_action_rejects_job_steps():
    res = iro.init_step_action_data("cookies")
    assert res["ok"] is False
    assert "cookies" in res["error"]


def t_iro_job_executable_frozen_uses_sibling():
    # frozen iro-ui must spawn the sibling `iro`, not itself
    posix = iro._iro_job_executable(frozen=True,
                                    executable="/opt/iro/iro-ui", win=False)
    assert posix == "/opt/iro/iro"
    win = iro._iro_job_executable(frozen=True,
                                  executable="C:\\iro\\iro-ui.exe", win=True)
    assert win.endswith("iro.exe")


def t_iro_job_executable_dev_uses_interpreter():
    # non-frozen: the running interpreter (paired with iro.py)
    assert iro._iro_job_executable(frozen=False, executable="/usr/bin/python3",
                                   win=False) == "/usr/bin/python3"


if __name__ == "__main__":
    import inspect, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("t_") and callable(fn):
                # parameterized tests get exactly one positional arg: the tempdir
                fn(tmp) if inspect.signature(fn).parameters else fn()
                print("ok", name)
    print("ALL PASS")
