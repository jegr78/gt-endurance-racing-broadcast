"""Control Center HTTP server: serves the static page, the JSON status API,
job control, and SSE streams (job output + service log tails) on localhost.
Same construction as the relay's control server (ThreadingHTTPServer +
make_handler closure). v1 binds 127.0.0.1 only; the bind/auth seams for the
v2 Tailscale+password feature are this module's serve() and _allowed().
Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

APP_ID = "iro-control-center"
DEFAULT_PORT = 8089
TAIL_LINES = 40          # how much history a log stream starts with


def ui_port(env):
    """Port from IRO_UI_PORT (.env/environment), falling back to 8089."""
    try:
        return int(env.get("IRO_UI_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def classify_ping(body):
    """'ours' when an IRO Control Center answered the ping, else 'foreign'."""
    try:
        return "ours" if json.loads(body.decode()).get("app") == APP_ID else "foreign"
    except Exception:
        return "foreign"


def probe_instance(host, port, fetch=None):
    """Is something on host:port? 'free' (nothing), 'ours' (a running Control
    Center), 'foreign' (another app)."""
    fetch = fetch or _fetch_ping
    try:
        body = fetch(host, port)
    except Exception:
        return "free"
    return classify_ping(body)


def _fetch_ping(host, port):
    import urllib.request
    with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=2) as r:
        return r.read()


def sse_frame(line):
    return f"data: {line}\n\n".encode("utf-8")


def sse_done(exit_code):
    return f"event: done\ndata: {exit_code}\n\n".encode("utf-8")


def _allowed(_handler):
    """Auth seam: always allowed in v1 (localhost-only bind is the boundary).
    v2 (Tailscale + IRO_UI_PASSWORD session cookie) changes only this."""
    return True


def make_handler(ctx):
    """ctx: version, page_path, status() -> dict, ops {name: argv},
    jobs (ui_jobs.JobManager), log_paths {name: () -> path|None},
    shutdown() (installed by serve())."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass                                  # quiet — one consumer, localhost

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _not_found(self, what="not found"):
            self._json({"ok": False, "error": what}, code=404)

        def _sse_headers(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

        def do_GET(self):
            if not _allowed(self):
                return self._json({"ok": False, "error": "unauthorized"}, code=401)
            path = urlparse(self.path).path
            if path == "/":
                return self._page()
            if path == "/api/ping":
                return self._json({"app": APP_ID, "version": ctx["version"]})
            if path == "/api/status":
                return self._json({"ok": True, **ctx["status"]()})
            if path.startswith("/api/jobs/") and path.endswith("/stream"):
                return self._stream_job(path.split("/")[3])
            if path.startswith("/api/jobs/"):
                snap = ctx["jobs"].snapshot(path.split("/")[3])
                return self._json({"ok": True, **snap}) if snap else self._not_found("unknown job")
            if path.startswith("/api/logs/") and path.endswith("/stream"):
                return self._stream_log(path.split("/")[3])
            return self._not_found()

        def do_POST(self):
            if not _allowed(self):
                return self._json({"ok": False, "error": "unauthorized"}, code=401)
            path = urlparse(self.path).path
            if path.startswith("/api/op/"):
                name = path[len("/api/op/"):]
                if name not in ctx["ops"]:
                    return self._not_found(f"unknown operation: {name}")
                job_id, err = ctx["jobs"].start(name, ctx["ops"][name])
                if err:
                    return self._json({"ok": False, "error": err}, code=409)
                return self._json({"ok": True, "job_id": job_id})
            if path == "/api/quit":
                self._json({"ok": True})
                # shutdown() blocks until serve_forever() returns — never call
                # it from a request thread directly.
                threading.Thread(target=ctx["shutdown"], daemon=True).start()
                return None
            return self._not_found()

        def _page(self):
            try:
                with open(ctx["page_path"], "rb") as fh:
                    body = fh.read()
            except OSError:
                return self._not_found("page not bundled")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None

        def _stream_job(self, job_id):
            if ctx["jobs"].snapshot(job_id) is None:
                return self._not_found("unknown job")
            self._sse_headers()
            since = 0
            try:
                while True:
                    chunk, since, code = ctx["jobs"].lines_since(job_id, since)
                    for line in chunk:
                        self.wfile.write(sse_frame(line))
                    if chunk:
                        self.wfile.flush()
                    if code is not None and not chunk:
                        self.wfile.write(sse_done(code))
                        self.wfile.flush()
                        return
                    if not chunk:
                        time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError):
                return                            # browser tab closed mid-stream

        def _stream_log(self, name):
            path_fn = ctx["log_paths"].get(name)
            if path_fn is None:
                return self._not_found(f"unknown log: {name}")
            self._sse_headers()
            try:
                path, notified = path_fn(), False
                while not path or not os.path.exists(path):
                    # one visible notice, then SSE comment pings (detect a
                    # closed tab without spamming the client)
                    self.wfile.write(sse_frame("(no log yet — waiting)")
                                     if not notified else b": ping\n\n")
                    self.wfile.flush()
                    notified = True
                    time.sleep(2.0)
                    path = path_fn()
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh.readlines()[-TAIL_LINES:]:
                        self.wfile.write(sse_frame(line.rstrip("\r\n")))
                    self.wfile.flush()
                    while True:
                        line = fh.readline()
                        if line:
                            self.wfile.write(sse_frame(line.rstrip("\r\n")))
                            self.wfile.flush()
                        else:
                            time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def serve(ctx, host, port):
    """Build the server (caller runs serve_forever) and install ctx['shutdown'].
    Raises OSError when the port is taken — callers turn that into the
    IRO_UI_PORT hint."""
    httpd = ThreadingHTTPServer((host, port), make_handler(ctx))
    httpd.daemon_threads = True                  # SSE threads die with the process
    ctx["shutdown"] = httpd.shutdown
    return httpd
