"""Control Center operation registry: which `racecast` invocations the web UI may
trigger, and how to build the child argv. Pure data + pure helpers (no I/O) —
the UI server routes /api/op/<name> through this table and build_argv() only,
so the HTTP surface can never run arbitrary commands or pass free-form args."""
import re

# name -> base racecast argv. Installs always run with --yes: jobs have no stdin
# (DEVNULL), so an interactive prompt would silently read EOF and decline.
OPS = {
    "relay-start": ["relay", "start"],
    "relay-stop": ["relay", "stop"],
    "relay-restart": ["relay", "restart"],
    "companion-start": ["companion", "start"],
    "companion-stop": ["companion", "stop"],
    "companion-restart": ["companion", "restart"],
    "streams-start": ["streams", "start"],
    "streams-stop": ["streams", "stop"],
    "tailscale-up": ["tailscale", "up"],
    "tailscale-down": ["tailscale", "down"],
    "tailscale-start": ["app", "launch", "tailscale"],
    "tailscale-stop": ["app", "quit", "tailscale"],
    "obs-start": ["app", "launch", "obs"],
    "obs-stop": ["app", "quit", "obs"],
    "discord-start": ["app", "launch", "discord"],
    "discord-stop": ["app", "quit", "discord"],
    "obs-refresh": ["obs", "refresh"],
    "obs-collection-set": ["obs", "collection", "set"],
    "event-start": ["event", "start"],
    "event-stop": ["event", "stop"],
    "cookies": ["cookies"],
    "graphics": ["graphics"],
    "media": ["media"],
    "setup": ["setup"],
    "preflight": ["preflight"],
    "export-companion": ["export", "companion"],
    "install-tools": ["install-tools", "--yes"],
    "install-apps": ["install-apps", "--yes"],
    "update": ["update", "--yes"],   # optional `tag` param installs a preview build
    "chat-clear": ["chat", "clear"],
}

# Browsers get-cookies can export from (yt-dlp --cookies-from-browser names).
BROWSERS = ("firefox", "chrome", "edge", "brave", "safari")


def _browser_arg(value):
    if value not in BROWSERS:
        raise ValueError(f"browser must be one of: {', '.join(BROWSERS)}")
    return [value]


def _stint_arg(value):
    s = str(value)
    if not s.isascii() or not s.isdigit() or int(s) < 1:
        raise ValueError("stint must be a 1-based stint number")
    return ["--stint", s]


def _update_flag(value):
    return ["--update"] if value else []


# The UI's `update` op only ever installs a PREVIEW build by tag (a regular
# update sends no tag and goes to the latest release). Restricting the allowlist
# to preview-* means a crafted /api/op/update {tag: "v1.0.0"} cannot silently
# downgrade to an arbitrary stable release. (`racecast update --tag <vX.Y.Z>` on the
# CLI is still free to pin/downgrade — that boundary is the shell, not the UI.)
_TAG_RE = re.compile(r"^preview-[\w.-]+\Z")


def _tag_arg(value):
    """A preview release tag the UI may install. Allowlist: preview-* only.
    Defends against argv junk and stable-tag downgrades (the UI only ever sends
    a tag it got from /api/previews, which lists prereleases)."""
    s = str(value)
    if not _TAG_RE.match(s):
        raise ValueError(f"invalid preview tag: {value!r}")
    return ["--tag", s]


# op name -> {param name: validator(value) -> argv fragment}. Ops absent here
# accept no parameters at all.
PARAMS = {
    "cookies": {"browser": _browser_arg},
    "event-start": {"stint": _stint_arg},
    "install-tools": {"update": _update_flag},
    "install-apps": {"update": _update_flag},
    "update": {"tag": _tag_arg},
}


def build_argv(name, params=None):
    """Base argv + validated optional params. Raises ValueError on an unknown
    op, an unknown param, or an invalid value. Empty-string/None values are
    treated as 'not provided' (the UI sends blank inputs as empty strings)."""
    if name not in OPS:
        raise ValueError(f"unknown operation: {name}")
    argv = list(OPS[name])
    spec = PARAMS.get(name, {})
    if params is None:
        params = {}
    unknown = set(params) - set(spec)
    if unknown:
        raise ValueError(f"unexpected parameter(s): {', '.join(sorted(unknown))}")
    for key, validate in spec.items():
        if key in params and params[key] not in (None, ""):
            argv += validate(params[key])
    return argv


def job_argv(op_args, frozen, executable, iro_script):
    """argv to run `racecast <op_args...>` as a child process: the frozen binary
    re-invokes itself (same mechanism as the daemon spawns); repo/package mode
    runs racecast.py with this interpreter."""
    if frozen:
        return [executable] + list(op_args)
    return [executable, iro_script] + list(op_args)
