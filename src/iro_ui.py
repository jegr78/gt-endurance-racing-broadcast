#!/usr/bin/env python3
"""Second entrypoint: the windowed Control Center launcher (the `iro-ui`
binary). Producers double-click it — there is no terminal. It runs the same
server as `iro ui` via iro.run_ui(), but a fatal startup error (port taken /
bind failure) is shown in a NATIVE dialog instead of being written to a console
that does not exist. Jobs still spawn the sibling `iro` binary (see
iro._iro_job_executable). Spec: docs/superpowers/specs/2026-06-07-control-center-design.md."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)            # import the sibling iro module

import iro                              # noqa: E402 — after the path insert
import native_dialog                    # noqa: E402 — from scripts/ (iro added it to sys.path)


def _fatal(message):
    """Show the message natively, then exit non-zero (no console to print to)."""
    native_dialog.notify(message)
    raise SystemExit(1)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Same bootstrap as iro.main(): make sure .env exists next to the binary,
    # retire any stale update binary, load the frozen env + SSL certs.
    iro.ensure_env_file(os.path.dirname(sys.executable))
    iro.cleanup_old_binary(os.path.dirname(sys.executable))
    iro._load_env_frozen()
    iro._ensure_ssl_certs()
    try:
        iro.run_ui(argv, fail=_fatal,
                   open_browser="--no-browser" not in argv)
    except SystemExit as exc:
        # belt-and-suspenders: a string exit code means a fatal message slipped
        # through as text — surface it natively too.
        if isinstance(exc.code, str):
            _fatal(exc.code)
        raise


if __name__ == "__main__":
    main()
