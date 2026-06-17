#!/usr/bin/env python3
"""End-to-end / regression harness: stand up the relay + Control Center from
src/ and assert the live HTTP surface. Synthetic mode (default, CI-runnable,
no real Sheet/cookies/OBS/Tailscale) or --real-league NAME (local-only).

Not shipped (maintainer tool). Stdlib only."""
import argparse, contextlib, os, shutil, signal, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import e2e_checks as E
import cockpit_auth


def _csv_server(csv_text):
    body = csv_text.encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv"); self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", E.free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/schedule.csv"


def _spawn(argv, env, log):
    """Spawn a child from src/, its own process group so teardown kills the tree.
    stdout/stderr captured to *log* (a file path) for diagnosis."""
    fh = open(log, "wb")  # noqa: SIM115 — handle outlives this fn; closed in _kill
    kw = {}
    if os.name == "posix":
        kw["start_new_session"] = True
    p = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, **kw)
    p._logfh = fh  # keep handle for close on teardown
    return p


def _kill(p):
    if not p or p.poll() is not None:
        with contextlib.suppress(Exception):
            if getattr(p, "_logfh", None): p._logfh.close()
        return
    with contextlib.suppress(Exception):
        if os.name == "posix":
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        else:
            p.terminate()
    with contextlib.suppress(Exception):
        p.wait(timeout=10)
    with contextlib.suppress(Exception):
        if getattr(p, "_logfh", None): p._logfh.close()


def _wait_ready(url, timeout, proc=None, log=None):
    """Poll *url* until HTTP 200 or timeout. On timeout, dump *log* and raise."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            break
        try:
            st, _, _ = E.http_request(url, timeout=2)
            if st == 200:
                return
        except Exception:
            pass  # not up yet (connection refused / mid-startup) — keep polling
        time.sleep(0.3)
    detail = ""
    if log and os.path.exists(log):
        with open(log, "rb") as fh:
            detail = fh.read()[-2000:].decode("utf-8", "replace")
    raise RuntimeError(f"service not ready at {url} within {timeout}s\n--- child log ---\n{detail}")


SCHEDULE_ROWS = [
    ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Alice", "Stint 1"),
    ("https://www.twitch.tv/bobcaster", "Bob", "Stint 2"),
]


def run_synthetic(args):
    tmp = tempfile.mkdtemp(prefix="racecast-e2e-")
    procs, servers = [], []
    try:
        # 1. synthetic profile (scaffold from profiles/example) + cockpit secret
        prof_root = os.path.join(tmp, "profiles")
        shutil.copytree(os.path.join(ROOT, "profiles", "example"),
                        os.path.join(prof_root, "e2e"))
        secret = "e2e-secret-0123456789abcdef"
        key = cockpit_auth.streamer_key("Alice")
        token = cockpit_auth.mint_token(secret, key, version=1)

        # The CLI always injects --cookies <runtime>/yt-cookies.txt and the relay
        # hard-exits if that path is missing. Synthetic runs have no real YouTube
        # session, so hand it an empty jar in the temp dir (appended last -> wins
        # over the CLI-injected path; feed pulls fail in best-effort threads, which
        # is fine — we only assert the HTTP control surface).
        dummy_cookies = os.path.join(tmp, "yt-cookies.txt")
        with open(dummy_cookies, "w", encoding="utf-8") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
        # Isolate ALL relay state (chat.json, cockpit-versions/pending.json) in the
        # temp dir. The CLI injects --runtime-dir <repo>/runtime/...; we override it
        # (last-wins) so a synthetic run never writes into the real runtime tree.
        relay_runtime = os.path.join(tmp, "runtime")
        os.makedirs(relay_runtime, exist_ok=True)

        # 2. schedule CSV server
        csv_srv, csv_url = _csv_server(E.build_schedule_csv(SCHEDULE_ROWS))
        servers.append(csv_srv)

        # 3. enabled relay
        relay_port = E.free_port()
        env = dict(os.environ)
        env.update(RACECAST_COCKPIT_SECRET=secret, RACECAST_COCKPIT_ENABLED="1",
                   RACECAST_PROFILE="e2e")
        relay_log = os.path.join(tmp, "relay.log")
        relay = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                        "relay", "run", "--bind", "127.0.0.1",
                        "--http-port", str(relay_port), "--sheet-csv-url", csv_url,
                        "--cookies", dummy_cookies, "--runtime-dir", relay_runtime],
                       env, relay_log)
        procs.append(relay)
        relay_url = f"http://127.0.0.1:{relay_port}"
        _wait_ready(relay_url + "/status", args.timeout, relay, relay_log)

        # 4. disabled relay (no RACECAST_COCKPIT_ENABLED) -> /cockpit/* 404
        dis_port = E.free_port()
        env2 = dict(os.environ); env2.update(RACECAST_PROFILE="e2e")
        dis_log = os.path.join(tmp, "relay-disabled.log")
        dis = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                      "relay", "run", "--bind", "127.0.0.1",
                      "--http-port", str(dis_port), "--sheet-csv-url", csv_url,
                      "--cookies", dummy_cookies,
                      "--runtime-dir", os.path.join(tmp, "runtime-disabled")],
                     env2, dis_log)
        procs.append(dis)
        dis_url = f"http://127.0.0.1:{dis_port}"
        _wait_ready(dis_url + "/status", args.timeout, dis, dis_log)

        # 5. Control Center
        ui_port = E.free_port()
        env3 = dict(env); env3["RACECAST_UI_PORT"] = str(ui_port)
        ui_log = os.path.join(tmp, "ui.log")
        ui = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                     "ui", "--no-browser"], env3, ui_log)
        procs.append(ui)
        ui_url = f"http://127.0.0.1:{ui_port}"
        _wait_ready(ui_url + "/api/ping", args.timeout, ui, ui_log)

        # 6. run checks
        ctx = E.Ctx(relay_url=relay_url, disabled_relay_url=dis_url, ui_url=ui_url,
                    token=token, streamer_key=key, own_stint="Stint 1",
                    expect={"schedule_len": 2, "live_stint": 1})
        results, code = E.run_checks(E.SYNTHETIC_CHECKS, ctx)
        print(E.summarize(results))
        return code
    finally:
        if not args.keep:
            for p in procs: _kill(p)
            for s in servers:
                with contextlib.suppress(Exception): s.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"--keep: left tmp at {tmp}")


def _resolve_real_profile(name):
    """Resolve the league profile *name* via src/scripts/config.py against the
    repo's profiles/ tree. Returns a ResolvedConfig or None when the profile is
    absent (graceful skip — the operator must copy it in per the
    racecast-local-uat skill; repo profiles/* except example are gitignored)."""
    sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
    import config as cfg
    if name not in cfg.list_profiles(ROOT):
        return None
    try:
        return cfg.resolve_config(ROOT, override=name)
    except cfg.ProfileError:
        return None


def run_real_league(args):
    """Drive the relay + Control Center against a REAL copied league profile and
    run the non-mutating REAL_LEAGUE_CHECKS subset. Local-only: refuses under CI,
    and degrades to a clear skip (return 0) when the profile is not present in the
    repo. NEVER writes to the deployed instance. Same _spawn/_wait_ready/_kill
    teardown discipline as run_synthetic."""
    if os.environ.get("CI"):
        print("real-league mode is local-only; refusing under CI.")
        return 0

    name = args.real_league
    rc = _resolve_real_profile(name)
    if rc is None:
        print(f"real-league: profile {name!r} not found under {ROOT}/profiles/.")
        print("  Copy it in first (see the racecast-local-uat skill); this is a "
              "graceful skip, not a failure.")
        return 0
    if not rc.cockpit_secret:
        print(f"real-league: profile {name!r} has no COCKPIT_SECRET in profile.env.")
        print("  Run 'racecast cockpit enable' for that league first; skipping.")
        return 0

    tmp = tempfile.mkdtemp(prefix="racecast-e2e-real-")
    procs = []
    try:
        # Spawn the relay via the NORMAL CLI path against the real profile: the
        # CLI injects the league's real runtime-dir, cookie jar and overlay. We
        # only override --bind (loopback) and --http-port (a free port, so we
        # never collide with or disturb a relay the operator already runs).
        relay_port = E.free_port()
        env = dict(os.environ)
        env["RACECAST_PROFILE"] = name
        env["RACECAST_COCKPIT_ENABLED"] = "1"   # machine flag; secret is the league's real one
        relay_log = os.path.join(tmp, "relay.log")
        relay = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                        "relay", "run", "--bind", "127.0.0.1",
                        "--http-port", str(relay_port)],
                       env, relay_log)
        procs.append(relay)
        relay_url = f"http://127.0.0.1:{relay_port}"
        _wait_ready(relay_url + "/status", args.timeout, relay, relay_log)

        # Mint a token for a REAL streamer from the live schedule. /schedule/data
        # is unauthenticated and reflects the league's actual roster (the relay
        # fetched the real Sheet on startup), so we don't have to hardcode a name.
        # http_request returns a 3-tuple (status, body_bytes, headers); the pure
        # decode + first-streamer pick lives in E.first_roster_streamer (unit-
        # tested), so this byte-decoding path can't regress unnoticed again.
        st, sched_body, _ = E.http_request(relay_url + "/schedule/data", timeout=10)
        streamer = E.first_roster_streamer(st, sched_body)
        if not streamer:
            print("real-league: the live schedule is empty (no Sheet/network?).")
            print("  Cockpit-token checks need a real streamer; skipping the run.")
            return 0
        key = cockpit_auth.streamer_key(streamer)
        token = cockpit_auth.mint_token(rc.cockpit_secret, key, version=1)

        # Control Center against the same real profile.
        ui_port = E.free_port()
        env_ui = dict(env)
        env_ui["RACECAST_UI_PORT"] = str(ui_port)
        ui_log = os.path.join(tmp, "ui.log")
        ui = _spawn([sys.executable, os.path.join(ROOT, "src", "racecast.py"),
                     "ui", "--no-browser"], env_ui, ui_log)
        procs.append(ui)
        ui_url = f"http://127.0.0.1:{ui_port}"
        _wait_ready(ui_url + "/api/ping", args.timeout, ui, ui_log)

        print(f"real-league {name!r}: minting cockpit token for {streamer!r} "
              "(first roster streamer from the live schedule).")
        ctx = E.Ctx(relay_url=relay_url, disabled_relay_url=relay_url, ui_url=ui_url,
                    token=token, streamer_key=key, own_stint=None, expect={})
        results, code = E.run_checks(E.REAL_LEAGUE_CHECKS, ctx)
        print(E.summarize(results))
        return code
    finally:
        if not args.keep:
            for p in procs:
                _kill(p)
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"--keep: left tmp at {tmp}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="racecast e2e/regression harness")
    ap.add_argument("--real-league", metavar="NAME", default=None,
                    help="drive the copied real-league dev build (local only, never CI)")
    ap.add_argument("--playwright", action="store_true",
                    help="also run gated rendered checks (skip if unavailable)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="per-service readiness timeout (s)")
    ap.add_argument("--keep", action="store_true", help="skip teardown (debug)")
    args = ap.parse_args(argv)
    if args.real_league:
        return run_real_league(args)
    return run_synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
