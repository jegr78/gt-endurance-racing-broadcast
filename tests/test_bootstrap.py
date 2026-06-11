#!/usr/bin/env python3
"""Stdlib checks for the shared process bootstrap that BOTH binaries must run.

The `racecast` CLI (racecast.main) and the windowed `racecast-ui` launcher
(racecast_ui.main) used to duplicate their startup sequence and drifted: the
launcher first shipped without _ensure_tool_path (#46 — tools shown missing) and
then without _apply_active_profile_env (#54 — the active profile's SHEET_ID was
never injected, so preflight/asset checks read an empty env). These tests lock in
that both entrypoints route through one _bootstrap, so a step can never be added
to one and forgotten in the other again.

Run: python3 tests/test_bootstrap.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import racecast as iro
import racecast_ui


# Every side-effecting startup helper _bootstrap is expected to call, in order.
# The list IS the contract: drop one and the windowed launcher silently skips it.
_BOOTSTRAP_STEPS = ["_force_utf8_io", "ensure_env_file", "ensure_example_profile",
                    "cleanup_old_binary", "_load_env_frozen", "_ensure_ssl_certs",
                    "_ensure_tool_path", "_apply_active_profile_env"]


def _stub_bootstrap_helpers(monkey, calls):
    """Replace the heavy startup helpers on the racecast module with recorders."""
    monkey["_real_executable"] = iro._real_executable
    iro._real_executable = lambda: "/tmp/racecast"
    monkey["_app_home"] = iro._app_home
    iro._app_home = lambda exe: "/tmp"
    for name in _BOOTSTRAP_STEPS:
        monkey[name] = getattr(iro, name)
        setattr(iro, name, (lambda n: lambda *a, **k: calls.append(n))(name))


def _restore(monkey):
    for name, fn in monkey.items():
        setattr(iro, name, fn)


def t_bootstrap_runs_every_startup_step_in_order():
    monkey, calls = {}, []
    _stub_bootstrap_helpers(monkey, calls)
    try:
        rest = iro._bootstrap(["status"])
    finally:
        _restore(monkey)
    assert calls == _BOOTSTRAP_STEPS, f"missing/disordered startup steps: {calls}"
    assert rest == ["status"]


def t_bootstrap_injects_profile_env_after_path_setup():
    # The regression for #54: _apply_active_profile_env (which needs SHEET_ID etc.)
    # must run, and only AFTER the PATH/env setup it depends on.
    monkey, calls = {}, []
    _stub_bootstrap_helpers(monkey, calls)
    try:
        iro._bootstrap([])
    finally:
        _restore(monkey)
    assert "_apply_active_profile_env" in calls
    assert calls.index("_apply_active_profile_env") == len(calls) - 1   # last


def t_bootstrap_consumes_profile_flag():
    monkey, calls = {}, []
    _stub_bootstrap_helpers(monkey, calls)
    prev = os.environ.pop("RACECAST_PROFILE", None)
    try:
        rest = iro._bootstrap(["--profile", "iro-gtec", "status"])
        assert rest == ["status"]                       # flag stripped
        assert os.environ["RACECAST_PROFILE"] == "iro-gtec"
    finally:
        _restore(monkey)
        if prev is None:
            os.environ.pop("RACECAST_PROFILE", None)
        else:
            os.environ["RACECAST_PROFILE"] = prev


def t_bootstrap_rejects_profile_without_value():
    monkey, calls = {}, []
    _stub_bootstrap_helpers(monkey, calls)
    try:
        iro._bootstrap(["--profile"])
    except ValueError:
        return
    finally:
        _restore(monkey)
    raise AssertionError("expected ValueError for --profile without a name")


def t_cli_main_delegates_to_bootstrap():
    # racecast.main must route startup through _bootstrap (not its own copy).
    real_boot, real_route = iro._bootstrap, iro.route
    seen = {}
    iro._bootstrap = lambda argv: seen.setdefault("argv", argv) or []
    iro.route = lambda argv: {"kind": "help"}            # help -> prints + returns
    try:
        iro.main(["status"])
    finally:
        iro._bootstrap, iro.route = real_boot, real_route
    assert seen.get("argv") == ["status"]


def t_ui_launcher_delegates_to_bootstrap():
    # racecast_ui.main must run the SAME _bootstrap, then serve. This is the lock
    # that keeps the windowed launcher from drifting from the CLI again.
    real_boot, real_run = iro._bootstrap, iro.run_ui
    seen = {}
    iro._bootstrap = lambda argv: seen.setdefault("boot", argv) or ["--no-browser"]
    iro.run_ui = lambda rest, **kw: seen.setdefault("run", rest)
    try:
        racecast_ui.main(["--no-browser"])
    finally:
        iro._bootstrap, iro.run_ui = real_boot, real_run
    assert seen.get("boot") == ["--no-browser"]          # bootstrap ran
    assert seen.get("run") == ["--no-browser"]           # then the server


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
