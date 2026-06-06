#!/usr/bin/env python3
"""IRO operator CLI — one entrypoint for every service and setup action.

  python3 src/iro.py relay start        # repo
  python3 iro.py     relay start        # shipped package

  iro relay     start|stop|restart|status|logs|run|open-panel|open-hud|open-status
  iro companion start|stop|restart|status|logs|open-tablet|open-admin
  iro streams   start|stop|restart|status|logs
  iro event     status|start|stop      # event-day readiness: check / bring-up / wind-down
  iro event start --stint N             # takeover: stint N is on air now — the relay starts there
  iro tailscale up|down|status          # connect / disconnect / inspect Tailscale
  iro status                            # aggregate health of all services
  iro preflight | cookies [browser] | graphics | media | setup [--out PATH] | install-tools [--yes] | install-apps [--yes]
  iro export companion [--out PATH]     # write the Companion button config
  iro update [--check] [--yes]          # self-update the binary from GitHub Releases
  iro --version
"""
import glob, json, os, shutil, sys, time, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
# Adapters (added in later tasks) import sibling modules from scripts/ at module
# level (e.g. `import services`), so this injection must stay at import time.
sys.path.insert(0, os.path.join(HERE, "scripts"))
import subprocess
import services as sv

# PyInstaller marks the frozen binary with sys.frozen and unpacks bundled data
# (the whole src/ tree) to sys._MEIPASS. Repo + package mode stay subprocess-based.
IS_FROZEN = bool(getattr(sys, "frozen", False))

def _src_base(frozen, meipass, here):
    """Root of the source tree: bundled data dir when frozen, else this dir."""
    return os.path.join(meipass, "src") if frozen else here

def resource_path(rel):
    """Absolute path of a bundled/checked-out source file, e.g. 'obs/hud.html'."""
    return os.path.join(_src_base(IS_FROZEN, getattr(sys, "_MEIPASS", ""), HERE), rel)

def _runtime_base(frozen, executable, here):
    """Machine-local state dir. Frozen: next to the binary (document: keep the
    binary in its own folder). Repo (src/) -> <repo>/runtime ; package -> <pkg>/runtime."""
    if frozen:
        return os.path.join(os.path.dirname(executable), "runtime")
    if os.path.basename(here) == "src":
        return os.path.join(os.path.dirname(here), "runtime")
    return os.path.join(here, "runtime")

def _runtime_dir():
    return _runtime_base(IS_FROZEN, sys.executable, HERE)

def parse_env_text(text):
    """Minimal .env parser (KEY=VALUE, '#' comments, optional quotes) — matches the
    semantics of the bounded load_dotenv() copies in the src/ scripts."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key:
            out[key] = val.strip().strip("'\"")
    return out

def ensure_env_file(exe_dir, frozen=None):
    """First run of the frozen binary: the release archives ship .env.example
    next to the binary but never a real .env (an upgrade extract must not
    clobber filled-in secrets). Copy the template once so the operator only
    fills in values. Returns True iff .env was created."""
    frozen = IS_FROZEN if frozen is None else frozen
    if not frozen:
        return False
    env_path = os.path.join(exe_dir, ".env")
    example = os.path.join(exe_dir, ".env.example")
    if os.path.exists(env_path) or not os.path.exists(example):
        return False
    try:
        shutil.copyfile(example, env_path)
    except OSError as exc:
        print(f"warning: could not create .env next to the binary ({exc}) — "
              "copy .env.example to .env manually.", file=sys.stderr)
        return False
    print("created .env next to the binary — fill in IRO_SHEET_ID and "
          "IRO_TIMER_URL (see the comments inside).", file=sys.stderr)
    return True


def cleanup_old_binary(exe_dir, frozen=None, platform=None):
    """Best-effort removal of the iro-old.exe that `iro update` leaves behind on
    Windows (a running exe can only be renamed, not deleted, during the swap).
    Returns True iff the leftover existed and was removed."""
    frozen = IS_FROZEN if frozen is None else frozen
    platform = sys.platform if platform is None else platform
    if not frozen or not platform.startswith("win"):
        return False
    old = os.path.join(exe_dir, "iro-old.exe")
    try:
        if os.path.exists(old):
            os.remove(old)
            return True
    except OSError:
        pass  # still locked by a lingering process — retried on the next run
    return False


def _load_env_frozen():
    """Frozen binary: load <exe-dir>/.env into os.environ (existing env wins).
    The scripts' own load_dotenv() can't find it — their marker walk starts in
    the throwaway _MEIPASS dir — but they all let real env vars take precedence."""
    if not IS_FROZEN:
        return
    path = os.path.join(os.path.dirname(sys.executable), ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            pairs = parse_env_text(fh.read())
    except OSError:
        return
    for key, val in pairs.items():
        os.environ.setdefault(key, val)

# Known system CA bundle locations (macOS ships /etc/ssl/cert.pem; the Linux
# paths cover Debian/Ubuntu and RHEL/Fedora).
CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/etc/pki/tls/certs/ca-bundle.crt")


def pick_ca_bundle(cafile, capath, candidates, exists=os.path.exists):
    """The CA bundle SSL_CERT_FILE should point at, or None when the build's
    own OpenSSL default paths work (or no candidate exists). Pure for tests."""
    if (cafile and exists(cafile)) or (capath and exists(capath)):
        return None
    for path in candidates:
        if exists(path):
            return path
    return None


def _ensure_ssl_certs():
    """Frozen on macOS/Linux: the bundled OpenSSL looks for CA certs at the
    BUILD machine's compile-time paths, which usually don't exist on the
    producer's machine -> every in-process HTTPS call dies with
    CERTIFICATE_VERIFY_FAILED. Point SSL_CERT_FILE at the system bundle
    instead (Windows uses the OS cert store natively). Must run before any
    ssl context is created; children inherit the variable."""
    if not IS_FROZEN or sys.platform.startswith("win") or os.environ.get("SSL_CERT_FILE"):
        return
    import ssl
    paths = ssl.get_default_verify_paths()
    bundle = pick_ca_bundle(paths.openssl_cafile, paths.openssl_capath, CA_BUNDLES)
    if bundle:
        os.environ["SSL_CERT_FILE"] = bundle

def _script_invocation(rel, args, frozen, base=None):
    """How to run a src/ script: subprocess in repo/package mode; in-process when
    frozen (the .py files ship as bundled data, there is no python3 to exec)."""
    if frozen:
        base = base if base is not None else _src_base(True, getattr(sys, "_MEIPASS", ""), HERE)
        return ("inprocess", os.path.join(base, *rel.split("/")), list(args))
    return ("subprocess", [sys.executable, os.path.join(HERE, *rel.split("/"))] + list(args), None)

def _run_module(path, args):
    """Load a bundled script by file path and run its main() with patched argv.
    Returns an exit code (SystemExit from argparse/sys.exit is translated; an int
    return value from main() is honored — e.g. preflight returns 1 on failure)."""
    import importlib.util
    name = os.path.splitext(os.path.basename(path))[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = [os.path.basename(path)] + list(args)
    try:
        spec.loader.exec_module(mod)
        fn = getattr(mod, "main", None)
        if fn is None:
            print(f"iro: {os.path.basename(path)} has no main()", file=sys.stderr)
            return 1
        result = fn()
        return result if isinstance(result, int) else 0
    except SystemExit as e:
        if e.code is None:
            return 0
        if isinstance(e.code, int):
            return e.code
        print(e.code, file=sys.stderr)  # mirror Python: sys.exit(str) -> stderr + 1
        return 1
    finally:
        sys.argv = old_argv

def _run_script(rel, args):
    kind, target, extra = _script_invocation(rel, args, IS_FROZEN)
    if kind == "subprocess":
        return subprocess.call(target)
    return _run_module(target, extra)

def _relay_daemon_argv(rest, frozen):
    """Detached relay child: frozen -> the binary re-invokes itself in foreground
    mode; otherwise python3 runs the script directly (as before)."""
    if frozen:
        return [sys.executable, "relay", "run"] + list(rest)
    return [sys.executable, _relay_script(), "--runtime-dir", _runtime_dir()] + list(rest)

def _oneshot_extra(command, rest, frozen, runtime_dir):
    """Extra argv for a one-shot. --runtime-dir where the script supports it (see
    RUNTIME_DIR_ONESHOTS); when frozen, also redirect default locations away from
    the throwaway _MEIPASS unpack dir (unless the user passed the flag himself):
    --out for the writers, and setup's --media/--graphics — those are INJECTED
    into the OBS collection as absolute paths and must outlive the process."""
    extra = []
    if command in RUNTIME_DIR_ONESHOTS:
        extra += ["--runtime-dir", runtime_dir]
    if frozen and "--out" not in rest:
        out = {"graphics": os.path.join(runtime_dir, "graphics"),
               "media": os.path.join(runtime_dir, "media"),
               "setup": os.path.join(runtime_dir, "IRO_Endurance.import.json")}.get(command)
        if out:
            extra += ["--out", out]
    if frozen and command == "setup":
        for flag, sub in (("--media", "media"), ("--graphics", "graphics")):
            if flag not in rest:
                extra += [flag, os.path.join(runtime_dir, sub)]
    return extra

def _relay_script():
    return os.path.join(HERE, "relay", "iro-feeds.py")

def _relay_pid_path():
    return os.path.join(_runtime_dir(), "relay.pid")

def _relay_log_path():
    return os.path.join(_runtime_dir(), "logs", "relay.console.log")

RELAY_PORT = 8088

SERVICES = ("relay", "companion", "streams")
SERVICE_VERBS = ("start", "stop", "restart", "status", "logs")
# Per-service verbs beyond the common set (relay foreground + browser-open shortcuts).
EXTRA_VERBS = {
    "relay": ("run", "open-panel", "open-hud", "open-status"),
    "companion": ("open-tablet", "open-admin"),
}
# Internal verbs: routed but never advertised (frozen feed children use run-feed).
HIDDEN_VERBS = {"streams": ("run-feed",)}
ONESHOTS = ("preflight", "cookies", "graphics", "media", "setup", "install-tools", "install-apps", "update")
EVENT_VERBS = ("status", "start", "stop")
TAILSCALE_VERBS = ("up", "down", "status")

USAGE = __doc__


def route(argv):
    """Resolve argv into an action dict WITHOUT executing. Raises ValueError on bad
    usage. This is the unit-test seam; main() executes the result."""
    if not argv or argv[0] in ("-h", "--help", "help"):
        return {"kind": "help"}
    if argv[0] in ("--version", "-V"):
        return {"kind": "version"}
    cmd, rest = argv[0], argv[1:]
    if cmd == "status" and not rest:
        return {"kind": "aggregate"}
    if cmd in SERVICES:
        verb = rest[0] if rest else None
        valid = SERVICE_VERBS + EXTRA_VERBS.get(cmd, ())
        if verb not in valid + HIDDEN_VERBS.get(cmd, ()):
            raise ValueError(f"usage: iro {cmd} {{{'|'.join(valid)}}}")
        return {"kind": "service", "command": cmd, "verb": verb, "rest": rest[1:]}
    if cmd == "event":
        verb = rest[0] if rest else None
        if verb not in EVENT_VERBS:
            raise ValueError(f"usage: iro event {{{'|'.join(EVENT_VERBS)}}}")
        return {"kind": "service", "command": "event", "verb": verb, "rest": rest[1:]}
    if cmd == "tailscale":
        verb = rest[0] if rest else None
        if verb not in TAILSCALE_VERBS:
            raise ValueError(f"usage: iro tailscale {{{'|'.join(TAILSCALE_VERBS)}}}")
        return {"kind": "service", "command": "tailscale", "verb": verb, "rest": rest[1:]}
    if cmd in ONESHOTS:
        return {"kind": "oneshot", "command": cmd, "rest": rest}
    if cmd == "export":
        if rest[:1] != ["companion"]:
            raise ValueError("usage: iro export companion [--out PATH]")
        return {"kind": "export", "target": "companion", "rest": rest[1:]}
    raise ValueError(f"unknown command: {cmd}")


def _tailscale_ip():
    try:
        import tailscale
        return tailscale.detect_tailscale_ip()
    except Exception:
        return None

def _relay_http_ok():
    """True iff the relay control server answers on localhost."""
    try:
        import urllib.request
        # .read() drains the socket; we only care whether the request succeeds
        urllib.request.urlopen(f"http://127.0.0.1:{RELAY_PORT}/status", timeout=3).read()
        return True
    except Exception:
        return False


def _relay_extra():
    parts = []
    if _relay_http_ok():
        parts.append(f"control http://127.0.0.1:{RELAY_PORT}/status OK")
    else:
        parts.append(f"(port {RELAY_PORT} not responding)")
    ts = _tailscale_ip()
    if ts:
        parts.append(f"tablet/panel http://{ts}:{RELAY_PORT}/panel")
    return "  ".join(parts)

def _frozen_child_env():
    """Env for daemon children spawned from the frozen --onefile binary.
    PyInstaller >= 6.10 treats a child running the SAME executable as a worker
    that shares the parent's _MEIPASS extraction dir — which the parent deletes
    on exit, killing the daemon ('Failed to import encodings module'). Setting
    PYINSTALLER_RESET_ENVIRONMENT=1 is the documented way to spawn an
    independent instance: the child extracts its own bundle and outlives us."""
    if not IS_FROZEN:
        return None
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env

def relay_start(rest):
    stint = _stint_args(rest)   # validate early: fail fast BEFORE spawning the daemon
    pid = sv.read_pid(_relay_pid_path())
    if sv.pid_alive(pid):
        print(f"relay already running (pid {pid}).")
        if stint:
            print(f"  --stint ignored (relay keeps its position) — to reposition the "
                  f"running relay open http://127.0.0.1:{RELAY_PORT}/set/stint/{stint[1]}")
        relay_status([])
        return None
    argv = _relay_daemon_argv(rest, IS_FROZEN)
    newpid = sv.start_detached(argv, _relay_log_path(), _relay_pid_path(),
                               env=_frozen_child_env())
    print(f"relay started (pid {newpid}). Watch it: iro relay logs -f")
    return None

def _release_obs_feeds():
    """Make OBS (via obs-websocket) drop its connections to the just-killed
    feeds. Otherwise OBS keeps the half-dead connections and the kernel pins
    the feed ports in FIN_WAIT_1 until OBS restarts — the next preflight then
    warns "port in use". Must run AFTER the kill: the rebuild would reconnect
    to a still-live relay. Best effort: OBS closed, auth missing, anything —
    print one notice and keep going."""
    try:
        import obs_ws
        names, note = obs_ws.release_feed_inputs()
    except Exception as exc:                # a stop must never fail on this
        print(f"obs: feed release skipped ({exc}).")
        return
    if names:
        print(f"obs: released media inputs {', '.join(names)} "
              f"(frees the feed ports; they restart on scene activation).")
    elif note:
        print(f"obs: feed release skipped — {note}")

def relay_stop(rest):
    pid = sv.read_pid(_relay_pid_path())
    if not sv.pid_alive(pid):
        if os.path.exists(_relay_pid_path()):
            os.remove(_relay_pid_path())
        print("relay is not running.")
        return
    if sv.stop_pid(pid, _relay_pid_path()):
        print("relay stopped.")
        _release_obs_feeds()                # AFTER the kill — see docstring
    else:
        print("relay may still be running.")

def relay_restart(rest):
    relay_stop([])
    relay_start(rest)

def relay_status(rest):
    pid = sv.read_pid(_relay_pid_path())
    alive = sv.pid_alive(pid)
    print(sv.status_line("relay", pid, alive, _relay_extra() if alive else ""))

def relay_logs(rest):
    sv.tail(_relay_log_path(), follow=("-f" in rest or "--follow" in rest))

def relay_run(rest):
    raise SystemExit(_run_script("relay/iro-feeds.py",
                                 ["--runtime-dir", _runtime_dir()] + rest))


def _companion():
    import companion_common as cc
    return cc

def _companion_cmds(cc):
    exe = cc.find_companion_exe() if sys.platform.startswith("win") else None
    return cc.companion_control_commands(sys.platform, exe)

def _companion_unsupported_msg():
    if sys.platform.startswith("win"):
        return ("companion: Companion.exe not found. Set IRO_COMPANION_EXE in .env "
                "to its full path and retry.")
    return ("companion: automated control supports Windows and macOS. On Linux "
            "(WSL/Docker), run and bind Companion on the host instead.")

def _companion_running(cc):
    cmds = _companion_cmds(cc)
    if not cmds:
        return False
    # errors="replace": tasklist writes OEM-codepage console output (e.g. German
    # "ausgeführt" = 0x81), which is NOT decodable as the ANSI codepage Python
    # uses for text=True. The matched token (Companion.exe) is pure ASCII.
    probe = subprocess.run(cmds["running"], capture_output=True, text=True,
                           errors="replace")
    return cc.parse_running(sys.platform, probe.returncode, probe.stdout or "")

def companion_start(rest):
    cc = _companion()
    cmds = _companion_cmds(cc)
    if cmds is None:
        sys.exit(_companion_unsupported_msg())
    bind_arg = rest[0] if rest else "auto"
    cfg_path = cc.companion_config_path(sys.platform)
    if not os.path.exists(cfg_path):
        # First launch: Companion creates its config on startup — start it
        # plainly now, bind on the next run (the bind edit needs the file).
        print(f"companion: first launch (no config at {cfg_path} yet) — starting Companion as-is.")
        print("  When it is up, run `iro companion restart` to bind it to the Tailscale IP.")
        subprocess.Popen(cmds["start"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
        return
    with open(cfg_path, encoding="utf-8") as fh:
        text = fh.read()
    cfg = json.loads(text)
    current, port = cfg.get("bind_ip", "127.0.0.1"), cfg.get("http_port", 8000)
    ts = _tailscale_ip()
    desired = cc.desired_bind_ip(bind_arg, ts)
    if bind_arg == "auto" and not ts:
        print("  (warn) no Tailscale IP found — binding 127.0.0.1 (local only).")
    plan = cc.plan_companion_action(current, desired, _companion_running(cc))
    if plan["stop_first"]:
        print("Stopping Companion to change its bind address…")
        subprocess.run(cmds["quit"], capture_output=True)
        for _ in range(30):
            if not _companion_running(cc):
                break
            time.sleep(0.5)
        else:
            sys.exit("companion: did not stop in time; aborting (config untouched).")
    if plan["edit"]:
        shutil.copy2(cfg_path, cfg_path + ".iro-bak")
        tmp = cfg_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(cc.config_with_bind_ip(text, desired))
        os.replace(tmp, cfg_path)
        print(f"Set Companion bind_ip {current} -> {desired} (backup: {cfg_path}.iro-bak)")
    if plan["start"]:
        print("Starting Companion…")
        subprocess.Popen(cmds["start"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
    else:
        print(f"Companion already bound to {desired} and running.")
    host = desired if desired != "0.0.0.0" else (ts or "<this-machine-ip>")
    print(f"Companion buttons (tablet): http://{host}:{port}/tablet")
    print("  Admin GUI shares this port — restrict who reaches it with a Tailscale ACL.")

def companion_stop(rest):
    cc = _companion()
    cmds = _companion_cmds(cc)
    if cmds is None:
        sys.exit(_companion_unsupported_msg())
    if not _companion_running(cc):
        print("companion is not running.")
        return
    print("Stopping Companion…")
    subprocess.run(cmds["quit"], capture_output=True)
    for _ in range(30):
        if not _companion_running(cc):
            print("companion stopped.")
            return
        time.sleep(0.5)
    hint = ("taskkill /F /IM Companion.exe" if sys.platform.startswith("win")
            else "pkill -f Companion")
    print(f"companion may still be running. Force-quit: {hint}")

def companion_restart(rest):
    companion_stop([])
    companion_start(rest)

def companion_status(rest):
    cc = _companion()
    cmds = _companion_cmds(cc)
    if cmds is None:
        why = ("(Companion.exe not found — set IRO_COMPANION_EXE in .env)"
               if sys.platform.startswith("win") else f"(manual on {sys.platform})")
        print(sv.status_line("companion", None, False, why))
        return
    running = _companion_running(cc)
    extra = ""
    if running:
        cfg_path = cc.companion_config_path(sys.platform)
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            extra = f"http://{cfg.get('bind_ip')}:{cfg.get('http_port', 8000)}/tablet"
        except Exception:
            extra = ""
    print(sv.status_line("companion", "?" if running else None, running, extra))

def companion_logs(rest):
    cc = _companion()
    logdir = os.path.join(os.path.dirname(cc.companion_config_path(sys.platform)), "logs")
    logs = sorted(glob.glob(os.path.join(logdir, "*")), key=os.path.getmtime)
    if not logs:
        print(f"(no Companion logs at {logdir})")
        return
    sv.tail(logs[-1], follow=("-f" in rest or "--follow" in rest))


def _streams_static_dir():
    return os.path.join(_runtime_dir(), "static")

def streams_start(rest):
    raise SystemExit(_run_script("scripts/start-streams.py",
                                 ["--state-dir", _streams_static_dir()] + rest))

def streams_stop(rest):
    # Static feeds serve the same OBS media sources as the relay (same ports),
    # so OBS must drop them here too — but only if feeds actually ran.
    had_feeds = bool(glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")))
    # No SystemExit: streams_restart() must continue into streams_start().
    _run_script("scripts/stop-streams.py",
                ["--state-dir", _streams_static_dir()] + rest)
    if had_feeds:
        _release_obs_feeds()                # AFTER the kill — see the helper

def streams_run_feed(rest):
    raise SystemExit(_run_script("scripts/loopstream.py", rest))

def streams_restart(rest):
    streams_stop([])
    streams_start(rest)

def streams_status(rest):
    pidfiles = sorted(glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")))
    if not pidfiles:
        print(sv.status_line("streams", None, False, "(no feeds started)"))
        return
    for pf in pidfiles:
        pid = sv.read_pid(pf)
        label = "streams:" + os.path.basename(pf)[len("feed_"):-len(".pid")]
        print(sv.status_line(label, pid, sv.pid_alive(pid)))

def streams_logs(rest):
    logs = sorted(glob.glob(os.path.join(_streams_static_dir(), "logs", "feed_*.log")),
                  key=os.path.getmtime)
    if not logs:
        print(f"(no stream logs under {os.path.join(_streams_static_dir(), 'logs')})")
        return
    sv.tail(logs[-1], follow=("-f" in rest or "--follow" in rest))


def _http_url(host, port, path):
    return f"http://{host}:{port}{path}"

def _open_url(url):
    print(f"Opening {url}")
    webbrowser.open(url)

def relay_open_panel(rest):
    _open_url(_http_url("127.0.0.1", RELAY_PORT, "/panel"))

def relay_open_hud(rest):
    _open_url(_http_url("127.0.0.1", RELAY_PORT, "/hud"))

def relay_open_status(rest):
    _open_url(_http_url("127.0.0.1", RELAY_PORT, "/status"))

def _companion_open(path):
    # Companion listens on its bind_ip (the Tailscale IP), not 127.0.0.1 — open that.
    cc = _companion()
    cfg_path = cc.companion_config_path(sys.platform)
    if not os.path.exists(cfg_path):
        sys.exit(f"companion: config not found at {cfg_path}. Launch Companion once, then retry.")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    _open_url(_http_url(cfg.get("bind_ip", "127.0.0.1"), cfg.get("http_port", 8000), path))

def companion_open_tablet(rest):
    _companion_open("/tablet")

def companion_open_admin(rest):
    _companion_open("/")


def _stint_args(rest):
    """Extract + validate a --stint flag ("--stint 4" or "--stint=4") from an
    argv. Returns the fragment to forward to the relay launch; exits on an
    invalid value (fail fast BEFORE a detached daemon is spawned — its own
    error would only land in the log file)."""
    for i, tok in enumerate(rest):
        val = None
        if tok == "--stint" and i + 1 < len(rest):
            val = rest[i + 1]
        elif tok.startswith("--stint="):
            val = tok.split("=", 1)[1]
        if val is not None:
            if not val.isdigit() or int(val) < 1:
                sys.exit(f"--stint must be a 1-based stint number (got {val!r}).")
            return ["--stint", val]
    return []


def _event_modules():
    """event/preflight are plain sibling modules of services (scripts/ is on
    sys.path; frozen: hidden-imports in tools/build-binary.py)."""
    import event as ev
    import preflight as pf
    return ev, pf


def _load_relay_module(rel):
    """Load a relay script (hyphenated filename) as a module, repo + package +
    frozen alike — module-level code only defines functions, no side effects."""
    import importlib.util
    path = resource_path(rel)
    name = os.path.splitext(os.path.basename(path))[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _asset_dirs(gg, gm):
    """Where `iro graphics`/`iro media` put files in THIS run mode. Frozen:
    the oneshot injection redirects to runtime/ (see _oneshot_extra); repo and
    package follow the scripts' own defaults (runtime/ vs. package root)."""
    if IS_FROZEN:
        return (os.path.join(_runtime_dir(), "graphics"),
                os.path.join(_runtime_dir(), "media"))
    return (gg.graphics_dir(os.path.dirname(os.path.abspath(gg.__file__))),
            gm.media_dir(os.path.dirname(os.path.abspath(gm.__file__))))


def _event_sections(ev, pf):
    """Gather all event-day facts and classify them into report sections."""
    # Apps
    apps = [ev.classify_app("obs", ev.app_running("obs")),
            ev.classify_app("discord", ev.app_running("discord")),
            ev.classify_tailscale(_tailscale_ip())]
    # Services
    pid = sv.read_pid(_relay_pid_path())
    alive = sv.pid_alive(pid)
    services = [ev.classify_relay(alive, _relay_http_ok() if alive else False, RELAY_PORT)]
    try:
        cc = _companion()
        supported = _companion_cmds(cc) is not None
        services.append(ev.classify_companion(
            _companion_running(cc) if supported else False, supported,
            "" if supported else _companion_unsupported_msg()))
    except Exception as exc:
        services.append(ev.Result(ev.WARN, "Companion", f"check failed: {exc}"))
    # Assets — get-graphics' load_dotenv also fills IRO_* for the repo/package
    # modes (frozen already loaded .env next to the binary at startup). A
    # broken probe must never traceback the report (spec: error behaviour).
    assets = [pf.cookies_status(os.path.join(_runtime_dir(), "cookies.txt"))]
    try:
        gg = _load_relay_module("relay/get-graphics.py")
        gm = _load_relay_module("relay/get-media.py")
        gg.load_dotenv(os.path.dirname(os.path.abspath(gg.__file__)))
        g_dir, m_dir = _asset_dirs(gg, gm)
        rows = ev.fetch_assets_rows(gg, os.environ.get("IRO_SHEET_ID"))
        missing_g = ev.check_assets(ev.required_graphics(gg, rows), g_dir) if rows else None
        missing_m = ev.check_assets(ev.required_media(gm, rows), m_dir) if rows else None
        assets += [ev.classify_assets("Graphics", missing_g, ev.local_count(g_dir),
                                      ev.FAIL, "run `iro graphics`"),
                   ev.classify_assets("Media", missing_m, ev.local_count(m_dir),
                                      ev.WARN, "run `iro media`")]
    except Exception as exc:
        assets.append(ev.Result(ev.WARN, "Graphics/Media", f"check failed: {exc}"))
    config = [ev.classify_env(os.environ.get("IRO_SHEET_ID"),
                              os.environ.get("IRO_TIMER_URL"))]
    return [("Apps", apps), ("Services", services), ("Assets", assets),
            ("Config", config), ("Go-live reminders", [ev.GO_LIVE_REMINDER])]


def event_status(rest):
    ev, pf = _event_modules()
    color = pf.enable_color("--no-color" in rest)
    raise SystemExit(pf.report(_event_sections(ev, pf), color))


def _event_launch(ev, app):
    """Best-effort GUI-app launch: report and continue on every failure path.
    Returns True iff a launch was actually attempted."""
    import install_apps
    if not install_apps.app_present(app, sys.platform):
        print(f"{app}: not installed — run `iro install-apps`.")
        return False
    cmd = ev.launch_command(app, sys.platform)
    if cmd is None:
        hint = ("run `sudo tailscale up`" if app == "tailscale"
                else "launch it manually")
        print(f"{app}: cannot launch automatically — {hint}.")
        return False
    argv, cwd = cmd
    print(f"{app}: launching…")
    try:
        subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
    except OSError as exc:
        print(f"{app}: launch failed ({exc}).")
        return False
    return True


def _tailscale_connect(ev=None):
    """Best-effort connect: argument-less `tailscale up` keeps all settings
    ("the opposite of tailscale down"). Launches the app first when no backend
    answers (macOS: the backend only lives while the app runs); never runs `up`
    in NeedsLogin — that would trigger the interactive browser login. Shared by
    `iro tailscale up` and `iro event start`; returns the tailnet IP or None."""
    import tailscale as ts
    binary, state, ip = ts.tailscale_backend()
    if ts.plan_tailscale_up(state) == "launch-app":
        ev = ev or _event_modules()[0]
        if not _event_launch(ev, "tailscale"):
            return None  # _event_launch already printed the actionable hint
        for _ in range(20):  # ~10 s for the backend to come up
            time.sleep(0.5)
            binary, state, ip = ts.tailscale_backend()
            if state:
                break
    action = ts.plan_tailscale_up(state)
    if action == "connected":
        print(f"tailscale: already connected ({ip or 'no IPv4 yet'}).")
        return ip
    if action == "needs-login":
        print("tailscale: logged out — open the Tailscale app and sign in.")
        return None
    if action == "launch-app":  # the backend never came up
        print("tailscale: not running — start the Tailscale app manually.")
        return None
    ok, detail = ts.tailscale_up(binary)
    if not ok:
        hint = " (try `sudo tailscale up`)" if sys.platform.startswith("linux") else ""
        print(f"tailscale: `up` failed: {detail}{hint}")
        return None
    for _ in range(20):  # ~10 s for the tailnet to come up
        ip = ts.detect_tailscale_ip()
        if ip:
            break
        time.sleep(0.5)
    print(f"tailscale: connected ({ip})." if ip
          else "tailscale: `up` succeeded but no tailnet IP yet.")
    return ip


def tailscale_up_cmd(_rest):
    raise SystemExit(0 if _tailscale_connect() else 1)


def tailscale_down_cmd(_rest):
    import tailscale as ts
    binary, state, _ip = ts.tailscale_backend()
    if state != "Running":
        print("tailscale: not connected.")
        return
    ok, detail = ts.tailscale_down(binary)
    if not ok:
        hint = " (try `sudo tailscale down`)" if sys.platform.startswith("linux") else ""
        sys.exit(f"tailscale: `down` failed: {detail}{hint}")
    print("tailscale: disconnected.")


def tailscale_status_cmd(_rest):
    import tailscale as ts
    _binary, state, ip = ts.tailscale_backend()
    if state is None:
        print("Tailscale: backend not running — `iro tailscale up` starts and connects it.")
    elif state == "Running":
        print(f"Tailscale: connected ({ip or 'no IPv4 yet'}).")
    elif state in ("NeedsLogin", "NeedsMachineAuth"):
        print(f"Tailscale: {state} — open the Tailscale app and sign in.")
    else:
        print(f"Tailscale: {state} — run `iro tailscale up` to connect.")


def event_start(rest):
    """Bring the event stack up. Order matters: Tailscale first (the Companion
    bind needs its IP), relay before OBS (the HUD browser source then connects
    against a live relay on OBS's first load). Every step is best effort."""
    ev, pf = _event_modules()
    # 1. Tailscale — connect a stopped backend; launch the app when needed.
    if _tailscale_connect(ev) is None:
        print("tailscale: continuing local-only (OBS keeps working).")
    # 2. Discord
    if ev.app_running("discord"):
        print("discord: already running.")
    else:
        _event_launch(ev, "discord")
    # 3. Relay (before OBS — see docstring). A takeover bring-up forwards
    # --stint so the feeds start at the stint that is on air right now.
    relay_start(_stint_args(rest))
    # 4. OBS
    if ev.app_running("obs"):
        print("obs: already running.")
    else:
        _event_launch(ev, "obs")
    # 5. Companion (companion_start sys.exits on unsupported setups — keep going)
    try:
        companion_start(["auto"])
    except SystemExit as exc:
        print(exc.code if isinstance(exc.code, str)
              else f"companion: start failed (exit {exc.code}).")
    # Give the launches time to settle: OBS and the relay take a few seconds,
    # and a too-early report shows FAILs that are already resolving. Only the
    # dynamic probes are waited on — static problems never self-heal.
    import install_apps
    probes = {"relay": _relay_http_ok}
    if install_apps.app_present("obs", sys.platform):
        probes["obs"] = lambda: ev.app_running("obs")
    print("\nWaiting for the launched services to come up (max 60 s)…")
    for name, up in sorted(ev.wait_until_up(probes).items()):
        print(f"  {name}: {'up' if up else 'still not up — see the report below'}")
    print("\nEvent readiness:")
    event_status(rest)  # exit code: 0 = ready, 1 = FAILs remain


def event_stop(rest):
    """Stop iro-managed services only — never the GUI apps (a mistyped command
    must not be able to kill a live broadcast)."""
    relay_stop([])
    try:
        companion_stop([])
    except SystemExit as exc:
        print(exc.code if isinstance(exc.code, str)
              else f"companion: stop failed (exit {exc.code}).")
    if glob.glob(os.path.join(_streams_static_dir(), "feed_*.pid")):
        streams_stop([])
    print("OBS/Discord/Tailscale keep running — quit them manually if needed.")


DISPATCH = {
    ("relay", "start"): relay_start, ("relay", "stop"): relay_stop,
    ("relay", "restart"): relay_restart, ("relay", "status"): relay_status,
    ("relay", "logs"): relay_logs, ("relay", "run"): relay_run,
    ("relay", "open-panel"): relay_open_panel, ("relay", "open-hud"): relay_open_hud,
    ("relay", "open-status"): relay_open_status,
    ("companion", "start"): companion_start, ("companion", "stop"): companion_stop,
    ("companion", "restart"): companion_restart, ("companion", "status"): companion_status,
    ("companion", "logs"): companion_logs,
    ("companion", "open-tablet"): companion_open_tablet,
    ("companion", "open-admin"): companion_open_admin,
    ("streams", "start"): streams_start, ("streams", "stop"): streams_stop,
    ("streams", "restart"): streams_restart, ("streams", "status"): streams_status,
    ("streams", "logs"): streams_logs, ("streams", "run-feed"): streams_run_feed,
    ("event", "status"): event_status, ("event", "start"): event_start,
    ("event", "stop"): event_stop,
    ("tailscale", "up"): tailscale_up_cmd, ("tailscale", "down"): tailscale_down_cmd,
    ("tailscale", "status"): tailscale_status_cmd,
}

ONESHOT_MAP = {
    "preflight":     "scripts/preflight.py",
    "cookies":       "relay/get-cookies.py",
    "graphics":      "relay/get-graphics.py",
    "media":         "relay/get-media.py",
    "setup":         "setup-assets.py",
    "install-tools": "scripts/install_tools.py",
    "install-apps":  "scripts/install_apps.py",
    "update":        "scripts/update.py",
}

# Forward --runtime-dir only to one-shot scripts whose argparse defines it.
# Verified against each script: preflight.py + get-cookies.py accept it; get-graphics.py
# and get-media.py (they use --out) and setup-assets.py do not.
RUNTIME_DIR_ONESHOTS = ("preflight", "cookies")


def oneshot(command, rest):
    extra = _oneshot_extra(command, rest, IS_FROZEN, _runtime_dir())
    if command == "update" and "--current" not in rest:
        extra += ["--current", version()]
    raise SystemExit(_run_script(ONESHOT_MAP[command], list(rest) + extra))


def version():
    """Build version: a VERSION file is stamped into the bundle by
    tools/build-binary.py; a repo checkout has none -> 'dev'."""
    try:
        with open(resource_path("VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"


def export_companion(rest):
    """Write the bundled (password-stripped) Companion config for import.
    Default: runtime/ — the same home as the localized OBS collection."""
    out = None
    if rest[:1] == ["--out"] and len(rest) == 2:
        out = rest[1]
    elif rest:
        sys.exit("usage: iro export companion [--out PATH]")
    dst = out or os.path.join(_runtime_dir(), "iro-buttons.companionconfig")
    if os.path.isdir(dst):
        dst = os.path.join(dst, "iro-buttons.companionconfig")
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    shutil.copyfile(resource_path("companion/iro-buttons.companionconfig"), dst)
    print(f"Wrote {dst} — import it in Companion (Import / Export -> Import).")


def aggregate_status(_rest=None):
    relay_status([])
    companion_status([])
    streams_status([])


def main(argv=None):
    ensure_env_file(os.path.dirname(sys.executable))
    cleanup_old_binary(os.path.dirname(sys.executable))
    _load_env_frozen()
    _ensure_ssl_certs()
    argv = sys.argv[1:] if argv is None else argv
    try:
        action = route(argv)
    except ValueError as e:
        sys.exit(f"iro: {e}")
    if action["kind"] == "help":
        print(USAGE)
        return None
    if action["kind"] == "version":
        print(f"iro {version()}")
        return None
    if action["kind"] == "export":
        export_companion(action["rest"])
        return None
    if action["kind"] == "service":
        fn = DISPATCH.get((action["command"], action["verb"]))
        if not fn:
            sys.exit(f"iro: {action['command']} {action['verb']} not implemented yet")
        return fn(action["rest"])
    if action["kind"] == "oneshot":
        return oneshot(action["command"], action["rest"])
    if action["kind"] == "aggregate":
        aggregate_status()
        return None
    sys.exit(f"iro: {action['kind']} not implemented")


if __name__ == "__main__":
    main()
