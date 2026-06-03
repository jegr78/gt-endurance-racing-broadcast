#!/usr/bin/env python3
"""Repo launcher: run the relay with the repo's runtime/ directory.
Forwards extra args to iro-feeds.py.  Usage: python3 tools/run-relay.py [relay args...]
"""
import os, subprocess, sys


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runtime = os.path.join(root, "runtime")
    feeds = os.path.join(root, "src", "relay", "iro-feeds.py")
    cmd = [sys.executable, feeds, "--runtime-dir", runtime] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
