"""Control Center operation registry: which `iro` invocations the web UI may
trigger, and how to build the child argv. Pure data + pure helpers (no I/O) —
the UI server routes /api/op/<name> through this table only, so the HTTP
surface can never run arbitrary commands."""

# name -> iro argv. Phase 1: service control + the OBS page refresh.
# Phase 2 adds the one-shots (installs, graphics, media, cookies, preflight, …).
OPS = {
    "relay-start": ["relay", "start"],
    "relay-stop": ["relay", "stop"],
    "relay-restart": ["relay", "restart"],
    "companion-start": ["companion", "start"],
    "companion-stop": ["companion", "stop"],
    "companion-restart": ["companion", "restart"],
    "streams-start": ["streams", "start"],
    "streams-stop": ["streams", "stop"],
    "obs-refresh": ["obs", "refresh"],
}


def job_argv(op_args, frozen, executable, iro_script):
    """argv to run `iro <op_args...>` as a child process: the frozen binary
    re-invokes itself (same mechanism as the daemon spawns); repo/package mode
    runs iro.py with this interpreter."""
    if frozen:
        return [executable] + list(op_args)
    return [executable, iro_script] + list(op_args)
