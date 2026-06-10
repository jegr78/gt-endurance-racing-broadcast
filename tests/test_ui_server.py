#!/usr/bin/env python3
"""Stdlib checks for the Control Center HTTP server (real server on an
ephemeral port — no fixed ports, CI-safe). Run: python3 tests/test_ui_server.py"""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_jobs
import ui_server as us


# ---------- pure helpers ----------

def t_ui_port_default_and_override():
    assert us.ui_port({}) == 8089
    assert us.ui_port({"IRO_UI_PORT": "9100"}) == 9100
    assert us.ui_port({"IRO_UI_PORT": ""}) == 8089
    assert us.ui_port({"IRO_UI_PORT": "not-a-port"}) == 8089


def t_classify_ping():
    ours = json.dumps({"app": us.APP_ID, "version": "x"}).encode()
    assert us.classify_ping(ours) == "ours"
    assert us.classify_ping(b'{"app": "something-else"}') == "foreign"
    assert us.classify_ping(b"<html>hi</html>") == "foreign"


def t_sse_frames():
    assert us.sse_frame("hello") == b"data: hello\n\n"
    assert us.sse_done(3) == b"event: done\ndata: 3\n\n"


# ---------- live server ----------

def _ctx(jobs=None, init_plan=None, init_step=None):
    page = os.path.join(ROOT, "src", "ui", "control-center.html")
    return {"version": "test",
            "page_path": page,
            "status": lambda: {"relay": {"alive": False}},
            "ops": {"echo": ["echo-args"]},
            "build_argv": lambda name, params=None: ["echo-args"],
            "assets": lambda: {"ok": True,
                               "graphics": {"level": "PASS", "detail": "g"},
                               "media": {"level": "PASS", "detail": "m"}},
            "asset_files": lambda: {"ok": True,
                                    "graphics": ["Overlay.png"],
                                    "media": ["intro.mp4"]},
            "asset_roots": {"graphics": ROOT, "media": ROOT},
            "tools": lambda: {"ok": True, "tools": [
                {"name": "yt-dlp", "installed": True, "version": "1.2.3"},
                {"name": "ffmpeg", "installed": False, "version": None}]},
            "apps": lambda: {"ok": True, "apps": [
                {"name": "obs", "installed": True},
                {"name": "discord", "installed": False}]},
            "preflight": lambda: {"ok": True, "sections": [
                {"title": "Hardware", "results": [
                    {"level": "PASS", "name": "RAM", "detail": "32 GB"}]}]},
            "relay_live": lambda: {"ok": True, "schedule_len": 5, "uptime_s": 60,
                                   "feeds": [{"feed": "A", "stint": 3,
                                              "state": "serving"}],
                                   "timer": {"mode": "running"}},
            "obs_ws": lambda: {"ok": True, "ip": "127.0.0.1", "port": 4455,
                               "password": "pw", "auth_required": True},
            "obs_collection": lambda: {"ok": True, "current": "Other",
                                       "expected": "IRO Endurance", "match": False,
                                       "expected_present": True,
                                       "renamed_variant": None},
            "update_check": lambda force=False: {"ok": True, "current": "v1.0.0",
                                     "latest": "v1.1.0", "update_available": True,
                                     "forced": force,
                                     "releases_url": "https://example/releases"},
            "previews": lambda force=False: {"ok": True, "forced": force, "previews": [
                {"tag": "preview-pr-42", "title": "Preview: PR #42", "commit": "abc1234",
                 "published_at": "2026-06-10T08:00:00Z", "asset_url": "https://x/p42",
                 "notes": "n"}]},
            "streams_read": lambda: {"ok": True, "path": "/x/streams.json",
                                     "entries": [{"label": "Feed A",
                                                  "channel": "UC1", "port": "53001"}]},
            "streams_write": lambda entries: {"ok": True, "path": "/x/streams.json",
                                              "_got": entries},
            "docs": lambda: {"ok": True, "wiki_url": "https://example/wiki",
                             "local": [{"key": "cheat-sheet", "title": "Cheat sheet",
                                        "desc": "d", "kind": "html"}]},
            "docs_content": lambda key: (("text/html; charset=utf-8",
                                          b"<html>cheat</html>")
                                         if key == "cheat-sheet" else None),
            "jobs": jobs or ui_jobs.JobManager(
                lambda a: [sys.executable, "-c", "print('hi from job')"]),
            "log_paths": {},
            "env_read": lambda: {"ok": True, "path": "/x/.env",
                                 "entries": [{"key": "IRO_SHEET_ID", "value": "abc"}]},
            "env_write": lambda entries: {"ok": True, "path": "/x/.env", "_got": entries},
            "init_plan": init_plan or (lambda browser="firefox": {
                "ok": True, "steps": [], "next_steps": []}),
            "init_step": init_step or (lambda key: {"ok": True, "key": key,
                                                    "done": True,
                                                    "skip_reason": None})}


def _serve(ctx):
    httpd = us.serve(ctx, "127.0.0.1", 0)        # port 0 -> ephemeral
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def t_ping_identifies_app():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/ping")
        assert code == 200
        data = json.loads(body)
        assert data["app"] == us.APP_ID and data["version"] == "test"
    finally:
        httpd.shutdown()


def t_status_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/status")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True and data["relay"] == {"alive": False}
    finally:
        httpd.shutdown()


def t_relay_live_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/relay-live")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["feeds"][0]["stint"] == 3 and data["timer"]["mode"] == "running"
    finally:
        httpd.shutdown()


def t_obs_ws_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/obs-ws")
        data = json.loads(body)
        assert code == 200 and data["ok"] and data["port"] == 4455
        assert data["ip"] == "127.0.0.1" and data["password"] == "pw"
    finally:
        httpd.shutdown()


def t_obs_collection_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/obs-collection")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["expected"] == "IRO Endurance" and data["match"] is False
    finally:
        httpd.shutdown()


def t_update_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/update")
        data = json.loads(body)
        assert code == 200 and data["update_available"] is True
        assert data["latest"] == "v1.1.0" and data["forced"] is False
        _c, body2 = _get(port, "/api/update?force=1")          # force re-check
        assert json.loads(body2)["forced"] is True
    finally:
        httpd.shutdown()


def t_previews_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/previews")
        assert code == 200
        d = json.loads(body)
        assert d["ok"] and d["previews"][0]["tag"] == "preview-pr-42"
        _c, body2 = _get(port, "/api/previews?force=1")        # force re-check
        d2 = json.loads(body2)
        assert d2["ok"] and d2["forced"] is True               # force forwarded to provider
    finally:
        httpd.shutdown()


def t_streams_get_and_post_routes():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/streams")
        data = json.loads(body)
        assert code == 200 and data["ok"] and data["entries"][0]["port"] == "53001"
        code, body = _post_json(port, "/api/streams",
                                {"entries": [{"channel": "UC2", "port": "53002"}]})
        got = json.loads(body)
        assert code == 200 and got["ok"] and got["_got"] == [{"channel": "UC2",
                                                              "port": "53002"}]
    finally:
        httpd.shutdown()


def t_docs_route_and_file():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/docs")
        data = json.loads(body)
        assert code == 200 and data["ok"] and data["local"][0]["key"] == "cheat-sheet"
        code, body = _get(port, "/api/docs/file/cheat-sheet")     # allowlisted -> served
        assert code == 200 and b"<html" in body.lower()
        code, _b = _get(port, "/api/docs/file/unknown")           # not allowlisted -> 404
        assert code == 404
    finally:
        httpd.shutdown()


def t_unknown_routes_are_json_404():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/nope")
        assert code == 404 and json.loads(body)["ok"] is False
        code, body = _post(port, "/api/op/not-an-op")
        assert code == 404 and "unknown operation" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_op_starts_job_and_snapshot_completes():
    httpd, port = _serve(_ctx())
    try:
        code, body = _post(port, "/api/op/echo")
        assert code == 200
        job_id = json.loads(body)["job_id"]
        deadline = time.time() + 10
        while time.time() < deadline:
            _c, body = _get(port, f"/api/jobs/{job_id}")
            snap = json.loads(body)
            if snap["exit_code"] is not None:
                break
            time.sleep(0.1)
        assert snap["exit_code"] == 0 and snap["op"] == "echo"
        code, _b = _get(port, "/api/jobs/unknown-id")
        assert code == 404
    finally:
        httpd.shutdown()


def t_quit_shuts_the_server_down():
    httpd, port = _serve(_ctx())
    code, body = _post(port, "/api/quit")
    assert code == 200 and json.loads(body)["ok"] is True
    deadline = time.time() + 5
    while time.time() < deadline:           # serve_forever() must return
        try:
            _get(port, "/api/ping")
            time.sleep(0.1)
        except (urllib.error.URLError, ConnectionError, OSError):
            break
    httpd.server_close()


def t_empty_path_segments_are_404():
    httpd, port = _serve(_ctx())
    try:
        code, _b = _get(port, "/api/jobs//stream")
        assert code == 404
        code, _b = _get(port, "/api/logs//stream")
        assert code == 404
    finally:
        httpd.shutdown()


def t_job_stream_delivers_lines_then_done():
    httpd, port = _serve(_ctx())
    try:
        _c, body = _post(port, "/api/op/echo")
        job_id = json.loads(body)["job_id"]
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/jobs/{job_id}/stream", timeout=10)
        assert req.headers["Content-Type"] == "text/event-stream"
        raw = b""
        deadline = time.time() + 10
        while b"event: done\ndata: 0\n\n" not in raw and time.time() < deadline:
            raw += req.read(1)                  # tiny reads — no buffering surprises
        req.close()
        assert b"data: hi from job\n\n" in raw
        assert b"event: done\ndata: 0\n\n" in raw
    finally:
        httpd.shutdown()


def t_job_stream_unknown_id_is_404():
    httpd, port = _serve(_ctx())
    try:
        code, _b = _get(port, "/api/jobs/nope/stream")
        assert code == 404
    finally:
        httpd.shutdown()


def t_root_serves_the_page():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/")
        assert code == 200
        assert b"IRO Control Center" in body
        assert b"/api/status" in body          # the page talks to our API
    finally:
        httpd.shutdown()


def t_probe_instance_classifies():
    ours = json.dumps({"app": us.APP_ID}).encode()
    assert us.probe_instance("h", 1, fetch=lambda h, p: ours) == "ours"
    assert us.probe_instance("h", 1, fetch=lambda h, p: b"nope") == "foreign"
    def boom(h, p):
        raise OSError("connection refused")
    assert us.probe_instance("h", 1, fetch=boom) == "free"


def _post_json(port, path, obj):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def t_op_param_validation_is_400():
    ctx = _ctx()
    def boom(name, params=None):
        raise ValueError("browser must be one of: firefox")
    ctx["build_argv"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/op/echo", {"params": {"browser": "x"}})
        assert code == 400 and "browser" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_op_malformed_body_is_400():
    httpd, port = _serve(_ctx())
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/op/echo", method="POST",
            data=b"{not json", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 400
    finally:
        httpd.shutdown()


def t_op_with_params_passes_them_to_build_argv():
    seen = []
    ctx = _ctx()
    ctx["build_argv"] = lambda name, params=None: seen.append((name, params)) or ["echo-args"]
    httpd, port = _serve(ctx)
    try:
        code, _b = _post_json(port, "/api/op/echo", {"params": {"browser": "firefox"}})
        assert code == 200
        assert seen == [("echo", {"browser": "firefox"})]
    finally:
        httpd.shutdown()


def t_assets_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/assets")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["graphics"]["level"] == "PASS"
    finally:
        httpd.shutdown()


def t_assets_route_provider_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("sheet down")
    ctx["assets"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/assets")
        assert code == 500 and "sheet down" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_cancel_route():
    httpd, port = _serve(_ctx())
    try:
        _c, body = _post(port, "/api/op/echo")
        job_id = json.loads(body)["job_id"]
        code, body = _post(port, f"/api/jobs/{job_id}/cancel")
        assert code == 200 and json.loads(body)["ok"] is True
        code, _b = _post(port, "/api/jobs/nope/cancel")
        assert code == 404
    finally:
        httpd.shutdown()


def t_setup_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/setup")
        data = json.loads(body)
        assert code == 200
        assert data["tools"]["ok"] is True and data["apps"]["ok"] is True
        assert data["tools"]["tools"][0]["name"] == "yt-dlp"
    finally:
        httpd.shutdown()


def t_setup_route_provider_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("which down")
    ctx["tools"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/setup")
        assert code == 500 and "which down" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_preflight_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/preflight")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["sections"][0]["title"] == "Hardware"
    finally:
        httpd.shutdown()


def t_preflight_route_provider_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("gather down")
    ctx["preflight"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/preflight")
        assert code == 500 and "gather down" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_asset_files_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/assets/files")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["graphics"] == ["Overlay.png"]
    finally:
        httpd.shutdown()


def t_asset_file_serves_bytes_with_ctype():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "Overlay.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nFAKE")
    ctx = _ctx()
    ctx["asset_roots"] = {"graphics": d, "media": d}
    httpd, port = _serve(ctx)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/assets/file/graphics/Overlay.png")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
            assert r.headers.get("Content-Type") == "image/png"
            assert r.read().startswith(b"\x89PNG")
    finally:
        httpd.shutdown()


def t_asset_file_rejects_traversal():
    ctx = _ctx()
    ctx["asset_roots"] = {"graphics": ROOT, "media": ROOT}
    httpd, port = _serve(ctx)
    try:
        for bad in ("/api/assets/file/graphics/..%2F..%2Fsecret",
                    "/api/assets/file/graphics/%2Fetc%2Fpasswd",
                    "/api/assets/file/nope/Overlay.png"):
            code, _b = _get(port, bad)
            assert code == 404, bad
    finally:
        httpd.shutdown()


def t_asset_file_missing_is_404():
    ctx = _ctx()
    ctx["asset_roots"] = {"graphics": tempfile.mkdtemp(),
                          "media": tempfile.mkdtemp()}
    httpd, port = _serve(ctx)
    try:
        code, _b = _get(port, "/api/assets/file/graphics/nothere.png")
        assert code == 404
    finally:
        httpd.shutdown()


def t_env_get_route():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/env")
        data = json.loads(body)
        assert code == 200 and data["ok"] is True
        assert data["entries"][0]["key"] == "IRO_SHEET_ID"
    finally:
        httpd.shutdown()


def t_env_get_route_error_is_500():
    ctx = _ctx()
    def boom():
        raise RuntimeError("disk gone")
    ctx["env_read"] = boom
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/env")
        assert code == 500 and "disk gone" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_env_post_saves_entries():
    seen = []
    ctx = _ctx()
    ctx["env_write"] = lambda entries: seen.append(entries) or {"ok": True, "path": "/x/.env"}
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/env",
                                {"entries": [{"key": "A", "value": "1"}]})
        assert code == 200 and json.loads(body)["ok"] is True
        assert seen == [[{"key": "A", "value": "1"}]]
    finally:
        httpd.shutdown()


def t_env_post_validation_error_is_400():
    ctx = _ctx()
    ctx["env_write"] = lambda entries: {"ok": False, "error": "invalid key: 'bad key'"}
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/env", {"entries": [{"key": "bad key", "value": "x"}]})
        assert code == 400 and "invalid key" in json.loads(body)["error"]
    finally:
        httpd.shutdown()


def t_env_post_malformed_body_is_400():
    httpd, port = _serve(_ctx())
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/env", method="POST",
            data=b"{not json", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 400
    finally:
        httpd.shutdown()


def t_init_plan_route_returns_plan():
    ctx = _ctx(init_plan=lambda browser="firefox": {
        "ok": True, "steps": [{"key": "env", "label": ".env", "kind": "gate",
                               "op": None, "done": False, "skip_reason": None,
                               "instruction": "set it"}],
        "next_steps": []})
    httpd, port = _serve(ctx)
    try:
        code, body = _get(port, "/api/init/plan")
        data = json.loads(body)
        assert code == 200
        assert data["ok"] is True
        assert data["steps"][0]["key"] == "env"
    finally:
        httpd.shutdown()


def t_init_plan_route_passes_browser_query():
    seen = {}
    def plan(browser="firefox"):
        seen["browser"] = browser
        return {"ok": True, "steps": [], "next_steps": []}
    httpd, port = _serve(_ctx(init_plan=plan))
    try:
        code, body = _get(port, "/api/init/plan?browser=edge")
        json.loads(body)
        assert code == 200
        assert seen["browser"] == "edge"
    finally:
        httpd.shutdown()


def t_init_step_route_runs_action():
    ctx = _ctx(init_step=lambda key: {"ok": True, "key": key, "done": True,
                                      "skip_reason": "config already exported"})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/init/step/export-companion", {})
        data = json.loads(body)
        assert code == 200
        assert data["ok"] is True
        assert data["done"] is True
    finally:
        httpd.shutdown()


def t_init_step_route_reports_error_as_400():
    ctx = _ctx(init_step=lambda key: {"ok": False, "error": "nope"})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/init/step/cookies", {})
        data = json.loads(body)
        assert code == 400
        assert data["ok"] is False
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
