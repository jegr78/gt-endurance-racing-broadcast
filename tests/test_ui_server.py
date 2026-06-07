#!/usr/bin/env python3
"""Stdlib checks for the Control Center HTTP server (real server on an
ephemeral port — no fixed ports, CI-safe). Run: python3 tests/test_ui_server.py"""
import json, os, sys, threading, time, urllib.error, urllib.request

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

def _ctx(jobs=None):
    page = os.path.join(ROOT, "src", "ui", "control-center.html")
    return {"version": "test",
            "page_path": page,
            "status": lambda: {"relay": {"alive": False}},
            "ops": {"echo": ["echo-args"]},
            "jobs": jobs or ui_jobs.JobManager(
                lambda a: [sys.executable, "-c", "print('hi from job')"]),
            "log_paths": {}}


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
