#!/usr/bin/env python3
"""Refresh src/assets/ from the production graphics source (a Google-Drive, Dropbox,
or network folder) — run this whenever the graphics change.

The source folder is per-user (machine-specific) and is NOT hardcoded. Provide it,
in priority order:
  1. --source DIR
  2. env var  IRO_ASSETS_SOURCE
  3. file     runtime/assets-source.txt   (one line: the path; runtime/ is gitignored)

Usage: python3 tools/sync-assets.py [--source DIR]
"""
import argparse, os, shutil, sys

ASSETS = ["Overlay.png", "Post Race Interviews.png", "Quali Results.png",
          "Race Results.png", "Season Schedule.png", "Standings.png", "YT-IRO-Race.png"]


def resolve_source(arg, root):
    if arg:
        return os.path.expanduser(arg)
    env = os.environ.get("IRO_ASSETS_SOURCE")
    if env:
        return os.path.expanduser(env)
    cfg = os.path.join(root, "runtime", "assets-source.txt")
    if os.path.exists(cfg):
        line = open(cfg, encoding="utf-8").read().strip()
        if line:
            return os.path.expanduser(line)
    return None


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = os.path.join(root, "src", "assets")
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None,
                    help="Folder holding the production PNGs (Google-Drive/Dropbox/share).")
    a = ap.parse_args()

    src = resolve_source(a.source, root)
    if not src:
        sys.exit("ERROR: no assets source set. Provide one of:\n"
                 "  python3 tools/sync-assets.py --source /path/to/graphics/folder\n"
                 "  export IRO_ASSETS_SOURCE=/path/to/graphics/folder\n"
                 "  echo /path/to/graphics/folder > runtime/assets-source.txt")
    if not os.path.isdir(src):
        sys.exit(f"ERROR: source folder not found: {src}")

    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in ASSETS:
        s = os.path.join(src, name)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dst, name)); n += 1; print(f"  {name}")
        else:
            print(f"  MISSING in source: {name}")
    print(f"synced {n}/{len(ASSETS)} assets from {src} -> {dst}")


if __name__ == "__main__":
    main()
