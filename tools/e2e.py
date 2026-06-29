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
import console_auth


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


def _spawn(argv, env, log, cwd=ROOT):
    """Spawn a child in its own process group so teardown kills the tree.
    stdout/stderr captured to *log* (a file path) for diagnosis. *cwd* is ROOT for
    the src/ dev path; binary mode runs from the copied binary's isolated app dir."""
    fh = open(log, "wb")  # noqa: SIM115 — handle outlives this fn; closed in _kill
    kw = {}
    if os.name == "posix":
        kw["start_new_session"] = True
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, **kw)
    p._logfh = fh  # keep handle for close on teardown
    return p


def _resolve_binary(args, tmp):
    """Locate (optionally build) the frozen racecast binary and copy it into an
    ISOLATED temp app-home, so its frozen side-effect files (.env, the seeded
    profiles/example, runtime/) land in the throwaway dir — never in dist/bin.
    Returns the copied executable's path. The binary uses dirname(exe) as its app
    home (racecast._app_home), which is why the copy — not the dist/bin original —
    is what we drive."""
    src = args.binary or E.default_binary_path(ROOT)
    if args.build:
        print("building the binary (tools/build-binary.py)...", flush=True)
        rc = subprocess.call([sys.executable,
                              os.path.join(ROOT, "tools", "build-binary.py"),
                              "--version", "e2e"])
        if rc != 0:
            raise RuntimeError("tools/build-binary.py failed")
        src = args.binary or E.default_binary_path(ROOT)
    if not os.path.exists(src):
        raise RuntimeError(
            f"binary not found: {src}\n"
            "  Build it first: python3 tools/build-binary.py  (or pass --build).")
    app = os.path.join(tmp, "app")
    os.makedirs(app, exist_ok=True)
    dst = os.path.join(app, E.binary_name())
    shutil.copy2(src, dst)
    os.chmod(dst, 0o700)   # owner-only rwx (the harness spawns it as this user) — not world-readable
    return dst


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


# --- Optional Playwright rendered checks (gated, never run in CI) ----------------
#
# These load the cockpit page in a real browser and assert that its state pills
# actually render — the one thing the stdlib HTTP checks can't see (they only
# fetch the JSON the page polls). They are STRICTLY optional: the repo is
# stdlib-only with no package manager for what CI runs, so Playwright is NEVER a
# hard dependency. The browser path below is exercised ONLY when a developer has
# `playwright` (and a browser) installed locally; CI runs tools/e2e.py WITHOUT
# --playwright, so these always skip there. When Playwright is unavailable the
# whole block degrades to clean SKIP results via E.classify_capability — never a
# failure — and the exit code stays governed by the API checks alone.

def _playwright_available():
    """True iff Playwright's sync API imports AND a Chromium browser launches.
    Guarded so importing/running this module without Playwright never errors:
    a missing package, a missing browser binary, or any launch failure all read
    as 'unavailable' (-> the rendered checks SKIP)."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 — optional, lazy
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


def _render_pill(ctx, name, selector, what, headed=False, slowmo=0):
    """Load the auth'd cockpit page in Chromium and assert *selector* renders
    (is attached + visible). Returns a CheckResult. Only ever called when
    _playwright_available() is True — all Playwright usage is behind that gate,
    so this body is dead code in a browserless environment (incl. CI). With
    *headed* the browser is a VISIBLE window (local debugging / a visual run);
    *slowmo* (ms) slows each action so the run is watchable. When headed, hold
    the rendered page briefly so it's actually seen before the browser closes."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 — optional, lazy
    url = ctx.relay_url + "/cockpit?t=" + ctx.token
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not headed, slow_mo=slowmo)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                # The page polls /cockpit/data, then fills the pill in. Wait for
                # the element to be attached + visible (a short, bounded wait).
                page.wait_for_selector(selector, state="visible", timeout=10000)
                if headed:
                    page.wait_for_timeout(2500)   # let a human see the rendered pill
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — a render failure is a check failure
        return E.CheckResult(name, "fail", f"{what}: {type(exc).__name__}: {exc}")
    return E.CheckResult(name, "pass", "")


def render_tally_pill(ctx, headed=False, slowmo=0):
    """The ON-AIR / UP-NEXT tally pill (#tally) renders on the cockpit page."""
    return _render_pill(ctx, "render_tally_pill", "#tally", "tally pill", headed, slowmo)


def render_funnel_pill(ctx, headed=False, slowmo=0):
    """The funnel-delivered identity pill (#who) renders on the cockpit page —
    it confirms the Funnel/token auth resolved a streamer (the page only shows
    this once /cockpit/data authenticates the session that Funnel delivered)."""
    return _render_pill(ctx, "render_funnel_pill", "#who", "funnel-state pill", headed, slowmo)


RENDERED_CHECKS = [render_tally_pill, render_funnel_pill]


def run_rendered_checks(ctx, headed=False, slowmo=0):
    """Run the gated Playwright rendered checks for *ctx*. Returns a list of
    CheckResults to APPEND after the API results. When Playwright/browser is
    unavailable, every rendered check is reported as SKIP (via
    classify_capability) — so a browserless run (incl. CI) never fails here and
    the exit code is decided by the API checks alone. *headed*/*slowmo* drive a
    visible, watchable browser (local only)."""
    available = _playwright_available()
    results = []
    for fn in RENDERED_CHECKS:
        skipped = E.classify_capability(available, fn.__name__)
        if skipped is not None:
            results.append(skipped)
            continue
        # Browser is available: run the real rendered check (local-only path).
        try:
            results.append(fn(ctx, headed=headed, slowmo=slowmo))
        except Exception as exc:  # noqa: BLE001 — a crashing check is a failure
            results.append(E.CheckResult(fn.__name__, "fail",
                                         f"{type(exc).__name__}: {exc}"))
    return results


def _stub_tools_bin(tmp):
    """A bin dir of no-op stubs for the external tools the relay checks at
    startup. The relay hard-exits if `yt-dlp`/`streamlink` are not on PATH
    (racecast-feeds.py), and `ffmpeg`/`deno` are invoked by a feed pull. The
    synthetic schedule's URLs are fake, so no real stream is ever pulled; these
    stubs just let the startup tool-check pass and make feed threads fail
    instantly (no network) on a clean machine / CI runner where the real tools
    aren't installed. Prepended to PATH so the run is deterministic even on a dev
    box that HAS the real tools. POSIX-only — the heavy synthetic run targets the
    Linux CI job (real-league mode uses the operator's real PATH, no stubs)."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    for name in ("yt-dlp", "streamlink", "ffmpeg", "deno"):
        p = os.path.join(bindir, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o700)   # owner-only: the harness spawns the relay as this user
    return bindir


def _capture_shots(ctx, outdir, headed=False, slowmo=0):
    """Write a screenshot of each visual surface to *outdir* using the same
    Playwright library the rendered checks use — a reproducible, MCP-free visual
    tour of a run. Best-effort: a shot failure warns but never fails the run.
    Returns the list of written paths.

    NOTE: the Control Center Home shows this machine's Tailscale IP — treat the
    output as a local artifact and do NOT commit it (CLAUDE.md: no real IPs)."""
    if not _playwright_available():
        print(f"--shots: Playwright/browser unavailable — nothing written to {outdir}.")
        return []
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 — optional, lazy
    os.makedirs(outdir, exist_ok=True)
    surfaces = [
        ("control-center", ctx.ui_url + "/"),
        ("cockpit", ctx.relay_url + "/cockpit?t=" + ctx.token),
        ("director-panel", ctx.relay_url + "/panel"),
        ("hud", ctx.relay_url + "/hud"),
    ]
    written = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, slow_mo=slowmo)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            for name, url in surfaces:
                path = os.path.join(outdir, f"{name}.png")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)   # let the SPA poll its data in
                    page.screenshot(path=path, full_page=True)
                    written.append(path)
                    print(f"--shots: wrote {path}")
                except Exception as exc:  # noqa: BLE001 — best-effort artifact
                    print(f"--shots: WARN could not capture {name}: "
                          f"{type(exc).__name__}: {exc}")
        finally:
            browser.close()
    return written


def _print_live_urls(relay_url, ui_url, token):
    """With --keep the spawned relay + Control Center are left running (they were
    started in their own session, so they outlive this process). Print the live
    surfaces so they can be opened in a browser for a visual walk-through."""
    print("\n--- live services (left up by --keep — open these in a browser) ---")
    print(f"  relay status (JSON): {relay_url}/status")
    print(f"  director panel:      {relay_url}/panel")
    print(f"  lower-third HUD:     {relay_url}/hud")
    print(f"  commentator cockpit: {relay_url}/cockpit?t={token}")
    print(f"  Control Center:      {ui_url}/")
    print("  (stop them with:  pkill -f 'racecast.py relay run' ; "
          "pkill -f 'racecast.py ui')")


def run_synthetic(args):
    tmp = tempfile.mkdtemp(prefix="racecast-e2e-")
    procs, servers = [], []
    try:
        # 1. synthetic profile (scaffold from profiles/example) + cockpit secret
        prof_root = os.path.join(tmp, "profiles")
        shutil.copytree(os.path.join(ROOT, "profiles", "example"),
                        os.path.join(prof_root, "e2e"))
        secret = "e2e-secret-0123456789abcdef"
        key = console_auth.streamer_key("Alice")
        token = console_auth.mint_token(secret, key, version=1)

        # The CLI always injects --cookies <runtime>/yt-cookies.txt and the relay
        # hard-exits if that path is missing. Synthetic runs have no real YouTube
        # session, so hand it an empty jar in the temp dir (appended last -> wins
        # over the CLI-injected path; feed pulls fail in best-effort threads, which
        # is fine — we only assert the HTTP control surface).
        dummy_cookies = os.path.join(tmp, "yt-cookies.txt")
        with open(dummy_cookies, "w", encoding="utf-8") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
        # Isolate ALL relay state (chat.json, console-versions/pending.json) in the
        # temp dir. The CLI injects --runtime-dir <repo>/runtime/...; we override it
        # (last-wins) so a synthetic run never writes into the real runtime tree.
        relay_runtime = os.path.join(tmp, "runtime")
        os.makedirs(relay_runtime, exist_ok=True)

        # Stub the external stream tools so the relay's startup tool-check passes
        # on a clean machine / CI runner (the fake schedule URLs are never pulled).
        stub_bin = _stub_tools_bin(tmp)

        # Launcher: the FROZEN binary (binary mode) or `python src/racecast.py`
        # (src/dev mode). Binary mode is the regression guard for binary-ONLY bugs
        # (a file/import missing from the PyInstaller bundle, frozen path
        # resolution) — the class the src/ dev build hides. The subcommand surface
        # is identical, so the same 10 checks run against whichever is driven.
        if args.binary is not None:
            binary = _resolve_binary(args, tmp)
            launcher, run_cwd = E.service_launcher(binary), os.path.dirname(binary)
            print(f"binary mode: driving the frozen binary at {binary}", flush=True)
        else:
            launcher = E.service_launcher(
                None, sys.executable, os.path.join(ROOT, "src", "racecast.py"))
            run_cwd = ROOT

        # 2. schedule CSV server
        csv_srv, csv_url = _csv_server(E.build_schedule_csv(SCHEDULE_ROWS))
        servers.append(csv_srv)

        # 3. cockpit relay (a secret in the env -> /cockpit/* is served, token-gated)
        relay_port = E.free_port()
        env = dict(os.environ)
        # Fan-out is the product default (on), but the two cockpit relays below share
        # the host default feed ports — two fan-out relays would collide binding them.
        # Pin them to direct-serve (=0) so they keep exercising the fallback path and
        # never bind feed ports; the dedicated fan-out relay (#6) overrides this to 1
        # on its own explicit free ports. Also neutralizes any RACECAST_FEED_FANOUT
        # leaked from the operator's shell, keeping synthetic e2e deterministic.
        env.update(RACECAST_CONSOLE_SECRET=secret, RACECAST_PROFILE="e2e",
                   RACECAST_FEED_FANOUT="0")
        env["PATH"] = stub_bin + os.pathsep + env.get("PATH", "")
        relay_log = os.path.join(tmp, "relay.log")
        relay = _spawn(launcher + ["relay", "run", "--bind", "127.0.0.1",
                        "--http-port", str(relay_port), "--sheet-csv-url", csv_url,
                        "--cookies", dummy_cookies, "--runtime-dir", relay_runtime],
                       env, relay_log, cwd=run_cwd)
        procs.append(relay)
        relay_url = f"http://127.0.0.1:{relay_port}"
        _wait_ready(relay_url + "/status", args.timeout, relay, relay_log)

        # 4. secret-less relay -> /cockpit/* 404. The cockpit is zero-config (the CLI
        # auto-provisions a secret), so "no cockpit" now means "no secret": we point
        # this relay at the shipped 'example' profile, the one profile the auto-
        # provision deliberately never touches -> no secret -> every /cockpit/* 404s.
        dis_port = E.free_port()
        env2 = dict(os.environ); env2.update(RACECAST_PROFILE="example")
        env2.pop("RACECAST_CONSOLE_SECRET", None)
        env2["PATH"] = stub_bin + os.pathsep + env2.get("PATH", "")
        dis_log = os.path.join(tmp, "relay-disabled.log")
        dis = _spawn(launcher + ["relay", "run", "--bind", "127.0.0.1",
                      "--http-port", str(dis_port), "--sheet-csv-url", csv_url,
                      "--cookies", dummy_cookies,
                      "--runtime-dir", os.path.join(tmp, "runtime-disabled")],
                     env2, dis_log, cwd=run_cwd)
        procs.append(dis)
        dis_url = f"http://127.0.0.1:{dis_port}"
        _wait_ready(dis_url + "/status", args.timeout, dis, dis_log)

        # 5. Control Center
        ui_port = E.free_port()
        env3 = dict(env); env3["RACECAST_UI_PORT"] = str(ui_port)
        ui_log = os.path.join(tmp, "ui.log")
        ui = _spawn(launcher + ["ui", "--no-browser"], env3, ui_log, cwd=run_cwd)
        procs.append(ui)
        ui_url = f"http://127.0.0.1:{ui_port}"
        _wait_ready(ui_url + "/api/ping", args.timeout, ui, ui_log)

        # 6. fan-out relay — a third relay with RACECAST_FEED_FANOUT=1 on explicit
        #    free feed ports.  In fan-out mode the relay itself binds the feed
        #    ports (FeedRing + FeedFanoutServer in Relay.start), so once /status
        #    is up the feed-A port is already bound and serving HTTP.  The two
        #    existing relays run in direct-serve mode and never bind feed ports
        #    (the no-op stub streamlink exits immediately), so allocating fresh
        #    free ports guarantees no collision.
        fanout_feed_a = E.free_port()
        fanout_feed_b = E.free_port()
        fanout_pov = E.free_port()
        fanout_http = E.free_port()
        fanout_runtime = os.path.join(tmp, "runtime-fanout")
        os.makedirs(fanout_runtime, exist_ok=True)
        env4 = dict(env); env4["RACECAST_FEED_FANOUT"] = "1"
        fanout_log = os.path.join(tmp, "relay-fanout.log")
        fanout_relay = _spawn(
            launcher + ["relay", "run", "--bind", "127.0.0.1",
                        "--http-port", str(fanout_http),
                        "--sheet-csv-url", csv_url,
                        "--cookies", dummy_cookies,
                        "--runtime-dir", fanout_runtime,
                        "--ports", f"{fanout_feed_a},{fanout_feed_b}",
                        "--pov-port", str(fanout_pov)],
            env4, fanout_log, cwd=run_cwd)
        procs.append(fanout_relay)
        _wait_ready(f"http://127.0.0.1:{fanout_http}/status",
                    args.timeout, fanout_relay, fanout_log)

        # 7. run checks
        ctx = E.Ctx(relay_url=relay_url, disabled_relay_url=dis_url, ui_url=ui_url,
                    token=token, streamer_key=key, own_stint="Stint 1",
                    expect={"schedule_len": 2, "live_stint": 1},
                    fanout_feed_port=fanout_feed_a)
        results, code = E.run_checks(E.SYNTHETIC_CHECKS, ctx)
        if args.playwright:
            # Optional, gated: append the rendered-check results AFTER the API
            # results. A browserless run (incl. CI, which omits --playwright)
            # yields SKIPs that don't touch the exit code; only an actual
            # rendered FAIL (browser present) can bump it.
            rendered = run_rendered_checks(ctx, headed=args.headed, slowmo=args.slowmo)
            results = results + rendered
            if any(r.status == "fail" for r in rendered):
                code = 1
        print(E.summarize(results))
        if args.shots:
            _capture_shots(ctx, args.shots, headed=args.headed, slowmo=args.slowmo)
        if args.keep:
            _print_live_urls(relay_url, ui_url, token)
            print("  NOTE: synthetic schedule was served in-process — it stops "
                  "when this command exits, so the relay keeps only its cached schedule.")
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
    if not rc.console_secret:
        print(f"real-league: profile {name!r} has no CONSOLE_SECRET in profile.env.")
        print("  Start the relay once for that league (it auto-provisions the secret), "
              "then re-run; skipping.")
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
        env["RACECAST_PROFILE"] = name   # the relay serves /cockpit whenever the league has a secret
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
        key = console_auth.streamer_key(streamer)
        token = console_auth.mint_token(rc.console_secret, key, version=1)

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
        if args.playwright:
            # gated; SKIP without a browser. --headed -> visible window.
            rendered = run_rendered_checks(ctx, headed=args.headed, slowmo=args.slowmo)
            results = results + rendered
            if any(r.status == "fail" for r in rendered):
                code = 1
        print(E.summarize(results))
        if args.shots:
            _capture_shots(ctx, args.shots, headed=args.headed, slowmo=args.slowmo)
        if args.keep:
            _print_live_urls(relay_url, ui_url, token)
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
    ap.add_argument("--binary", nargs="?", const="", default=None, metavar="PATH",
                    help="drive the FROZEN binary instead of src/ — the regression "
                         "guard for binary-only bugs (missing bundled file/import, "
                         "frozen path resolution). PATH defaults to "
                         "dist/bin/racecast; pair with --build to build it first")
    ap.add_argument("--build", action="store_true",
                    help="build the binary (tools/build-binary.py) before a --binary run")
    ap.add_argument("--playwright", action="store_true",
                    help="also run gated rendered checks (skip if unavailable)")
    ap.add_argument("--headed", action="store_true",
                    help="run the --playwright rendered checks in a VISIBLE browser "
                         "window (local only; a visual walk-through of the cockpit page)")
    ap.add_argument("--slowmo", type=int, default=0, metavar="MS",
                    help="slow each Playwright action by MS ms so a --headed run is watchable")
    ap.add_argument("--shots", metavar="DIR", default=None,
                    help="write a screenshot of each surface (cockpit/panel/hud/Control "
                         "Center) to DIR via Playwright — a reproducible, MCP-free visual "
                         "tour (local only; the Control Center shot shows your Tailscale IP)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="per-service readiness timeout (s)")
    ap.add_argument("--keep", action="store_true",
                    help="skip teardown: leave relay + Control Center running and print "
                         "their URLs (open them in a browser)")
    args = ap.parse_args(argv)
    # --build implies binary mode even without an explicit --binary.
    if args.build and args.binary is None:
        args.binary = ""
    if args.real_league:
        if args.binary is not None:
            ap.error("--binary is synthetic-only; not supported with --real-league")
        return run_real_league(args)
    return run_synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
