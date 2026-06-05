#!/usr/bin/env python3
"""Run the ruff linter over the repo (config: ruff.toml at the repo root).

    python3 tools/lint.py          # check only (what CI runs)
    python3 tools/lint.py --fix    # auto-fix what ruff can (e.g. unused imports)

Ruff is a single external binary, NOT vendored — install once:
  macOS:  brew install ruff      Windows:  winget install astral-sh.ruff
  Linux:  pipx/pip install ruff (or the distro package)
The rule set mirrors the GitHub code-scanning (CodeQL) classes — see ruff.toml.
"""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if not shutil.which("ruff"):
        sys.exit("lint: ruff not found on PATH.\n"
                 "  install: brew install ruff  (macOS) | winget install astral-sh.ruff"
                 "  (Windows) | pipx install ruff  (Linux)")
    cmd = ["ruff", "check", ROOT] + sys.argv[1:]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
