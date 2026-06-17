"""Tailscale detection and connect/disconnect control for the racecast CLI.

One home for everything Tailscale: CLI-binary discovery, BackendState-aware
detection, and the argument-less `up`/`down` control behind `racecast tailscale ...`
and `racecast event start`. A stopped/disconnected node keeps its assigned tailnet
IP, so `tailscale ip -4` alone reports false positives — only BackendState
"Running" counts as connected.

detect_tailscale_ip() is duplicated in src/relay/racecast-feeds.py (the relay is a
standalone single file by design) — the project's bounded-duplication
convention (cf. load_dotenv). Keep the two in sync.

Spec: docs/superpowers/specs/2026-06-06-tailscale-connect-design.md.
Tests: tests/test_tailscale.py."""
import ipaddress, json, subprocess
import services   # sibling module (scripts/ on sys.path) — no_window_kwargs (#23)

_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's IPv4 range
# Candidate Tailscale CLI locations (PATH first, then the platform installers).
_TAILSCALE_BINS = [
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",  # macOS GUI app
    "/usr/bin/tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
]


def _in_cgnat(ip):
    """True iff ip is a valid IPv4 address inside Tailscale's 100.64.0.0/10 range."""
    try:
        return ipaddress.ip_address(ip) in _CGNAT_NET
    except ValueError:
        return False


def parse_tailscale_backend(output):
    """(BackendState, ip) parsed from `tailscale status --json` output.

    The IP is Self's first CGNAT IPv4 and is only reported while Running.
    (None, None) on unparseable output or a missing BackendState."""
    try:
        data = json.loads(output)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    state = data.get("BackendState")
    if not isinstance(state, str) or not state:
        return None, None
    if state != "Running":
        return state, None
    for ip in (data.get("Self") or {}).get("TailscaleIPs") or []:
        if _in_cgnat(str(ip)):
            return state, str(ip)
    return state, None


def parse_tailscale_status(output):
    """Self's first CGNAT IPv4 from `tailscale status --json`, or None unless
    the backend is actually Running."""
    return parse_tailscale_backend(output)[1]


def tailscale_backend(timeout=3):
    """(binary, BackendState, ip) via the first CLI whose backend answers
    `status --json`; (None, None, None) when none does (CLI missing, or the
    backend is not running — on macOS it only lives while the app runs)."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=timeout,
                                 env=services.external_tool_env(),
                                 **services.no_window_kwargs())
        except (OSError, subprocess.SubprocessError):
            continue
        state, ip = parse_tailscale_backend(out.stdout)
        if state is not None:
            return binary, state, ip
    return None, None, None


def detect_tailscale_ip():
    """This machine's connected Tailscale IPv4 via the CLI, or None if the
    Tailscale backend is unavailable, stopped, or logged out."""
    return tailscale_backend()[2]


def parse_magicdns_name(output):
    """Self's MagicDNS name (e.g. 'host.tailnet.ts.net') from `tailscale status
    --json`, trailing dot stripped, or '' when absent. Pure → unit-tested. Used to
    build the public Funnel cockpit URL (#191) instead of a placeholder host."""
    try:
        data = json.loads(output)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    name = (data.get("Self") or {}).get("DNSName") or ""
    return name.rstrip(".") if isinstance(name, str) else ""


_FUNNEL_CAP = "https://tailscale.com/cap/funnel"


def parse_funnel_capable(output):
    """True iff `tailscale status --json` shows this node carries the Funnel
    capability — i.e. the tailnet policy granted it the 'funnel' nodeAttr (the
    one-time admin step). Pure → unit-tested. Lets `cockpit funnel on` fail fast
    with guidance instead of hanging on the CLI's interactive enable prompt."""
    try:
        data = json.loads(output)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    capmap = (data.get("Self") or {}).get("CapMap") or {}
    return isinstance(capmap, dict) and _FUNNEL_CAP in capmap


def funnel_capable(timeout=3):
    """Best-effort: is this node authorized for Funnel? (same discovery as
    tailscale_backend). False when the CLI is missing / backend down / nodeAttr
    absent."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=timeout,
                                 env=services.external_tool_env(),
                                 **services.no_window_kwargs())
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            return parse_funnel_capable(out.stdout)
    return False


def detect_magicdns_name(timeout=3):
    """This machine's MagicDNS name via the CLI, or '' if unavailable. Best-effort
    (same discovery as tailscale_backend)."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=timeout,
                                 env=services.external_tool_env(),
                                 **services.no_window_kwargs())
        except (OSError, subprocess.SubprocessError):
            continue
        name = parse_magicdns_name(out.stdout)
        if name:
            return name
    return ""


def parse_tailscale_peers(output):
    """Tailnet peers from `tailscale status --json`: a list of
    {hostname, ip, online, os}, one per peer that has a CGNAT IPv4 (peers without
    one are skipped — nothing to connect to). `[]` on unparseable/empty output.
    Pure → unit-tested. Used to offer a device dropdown for the takeover IP."""
    try:
        data = json.loads(output)
    except ValueError:
        return []
    peers_map = data.get("Peer") if isinstance(data, dict) else None
    if not isinstance(peers_map, dict):
        return []
    peers = []
    for peer in peers_map.values():
        if not isinstance(peer, dict):
            continue
        ip = next((str(x) for x in (peer.get("TailscaleIPs") or [])
                   if _in_cgnat(str(x))), None)
        if not ip:
            continue
        peers.append({"hostname": peer.get("HostName") or "", "ip": ip,
                      "online": bool(peer.get("Online")), "os": peer.get("OS") or ""})
    return peers


def tailscale_peers(timeout=3):
    """Live tailnet peer list via the CLI (same discovery as tailscale_backend),
    or [] on any failure (CLI missing / tailnet down)."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=timeout,
                                 env=services.external_tool_env(),
                                 **services.no_window_kwargs())
        except (OSError, subprocess.SubprocessError):
            continue
        peers = parse_tailscale_peers(out.stdout)
        if peers or out.returncode == 0:
            return peers
    return []


def plan_tailscale_up(state):
    """Decision for an `up` request given a BackendState:
    connected   : Running — nothing to do.
    needs-login : `up` would trigger the interactive browser login; hint only.
    launch-app  : no backend answered — start the Tailscale app first.
    run-up      : any other state (Stopped, Starting, ...) — run `up`."""
    if state == "Running":
        return "connected"
    if state in ("NeedsLogin", "NeedsMachineAuth"):
        return "needs-login"
    if state is None:
        return "launch-app"
    return "run-up"


def _run_verb(binary, verb, timeout):
    """Run an argument-less `tailscale up|down`; returns (ok, detail). The
    timeout is a backstop in case `up` unexpectedly enters the interactive
    login flow — callers never invoke it in the NeedsLogin state."""
    try:
        out = subprocess.run([binary, verb], capture_output=True, text=True,
                             errors="replace", timeout=timeout,
                             env=services.external_tool_env(),
                             **services.no_window_kwargs())
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if out.returncode:
        detail = (out.stderr or out.stdout or "").strip()
        return False, detail or f"exit code {out.returncode}"
    return True, ""


def tailscale_up(binary, timeout=15):
    """Argument-less `tailscale up`: brings the network online WITHOUT changing
    any settings (per the CLI's own help — the opposite of `tailscale down`)."""
    return _run_verb(binary, "up", timeout)


def tailscale_down(binary, timeout=15):
    """Argument-less `tailscale down`: disconnect, keep login + settings."""
    return _run_verb(binary, "down", timeout)


def funnel_args(path, target_port, enable):
    """Pure: the `tailscale funnel` argv to expose ONLY *path* (e.g. /cockpit) on
    public 443, reverse-proxied to the local relay, or to tear it down. Unit-
    tested without shelling out. The target keeps the same path so /cockpit/* maps
    1:1 onto the relay's /cockpit/* (#191)."""
    flag = f"--set-path={path}"
    if enable:
        return ["funnel", "--bg", flag, f"http://127.0.0.1:{target_port}{path}"]
    return ["funnel", flag, "off"]


def funnel(binary, path, target_port, enable, timeout=20):
    """Run the funnel on/off command. Returns (ok, detail). Best-effort, mirrors
    _run_verb. NOTE: enabling requires MagicDNS + HTTPS + the 'funnel' nodeAttr in
    the tailnet policy (a one-time admin step) — surface failures verbatim."""
    args = funnel_args(path, target_port, enable)
    try:
        out = subprocess.run([binary, *args], capture_output=True, text=True,
                             errors="replace", timeout=timeout,
                             env=services.external_tool_env(),
                             **services.no_window_kwargs())
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if out.returncode:
        detail = (out.stderr or out.stdout or "").strip()
        return False, detail or f"exit code {out.returncode}"
    return True, (out.stdout or "").strip()
