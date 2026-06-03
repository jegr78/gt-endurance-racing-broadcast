#!/usr/bin/env python3
"""Publish src/docs/wiki/ to the GitHub wiki repo.

Maintainer script (NOT shipped). The wiki is generated from the repo: edit the
Markdown under src/docs/wiki/, then run this to mirror it into the GitHub wiki.

It derives the wiki remote from the repo's `origin` (`<origin>.wiki.git`), clones
it into runtime/wiki/ (gitignored) or pulls if already there, mirrors the pages
(add/update/delete), commits and pushes.

Usage:
  python3 tools/sync-wiki.py                 # mirror + commit + push
  python3 tools/sync-wiki.py --dry-run       # show what would change, push nothing
  python3 tools/sync-wiki.py -m "msg"        # custom commit message
  python3 tools/sync-wiki.py --remote URL    # override the wiki remote URL

First-time bootstrap: GitHub only creates the wiki Git repo after the FIRST page is
saved via the web UI. If the clone fails with "repository not found", open the repo's
Wiki tab, create+save any page once, then re-run this script.
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI_SRC = os.path.join(ROOT, "src", "docs", "wiki")
CLONE = os.path.join(ROOT, "runtime", "wiki")


def git(args, cwd=None, check=True, capture=True):
    """Run a git command; return stdout (stripped) when capturing."""
    r = subprocess.run(["git", *args], cwd=cwd, text=True,
                       capture_output=capture)
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {msg}")
    return (r.stdout or "").strip() if capture else ""


def wiki_remote_from_origin():
    """`<origin>.wiki.git` derived from the repo's origin (https or ssh)."""
    try:
        url = git(["remote", "get-url", "origin"], cwd=ROOT)
    except RuntimeError:
        sys.exit("ERROR: no 'origin' remote on this repo. Pass --remote <wiki url>.")
    if url.endswith(".git"):
        url = url[:-4]
    return url + ".wiki.git"


def ensure_clone(remote):
    """Clone the wiki repo into runtime/wiki, or fetch+reset if already present."""
    os.makedirs(os.path.dirname(CLONE), exist_ok=True)
    if os.path.isdir(os.path.join(CLONE, ".git")):
        git(["remote", "set-url", "origin", remote], cwd=CLONE)
        git(["fetch", "origin"], cwd=CLONE)
        head = git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
                   cwd=CLONE, check=False) or "origin/master"
        branch = head.split("/")[-1]
        git(["checkout", branch], cwd=CLONE, check=False)
        git(["reset", "--hard", f"origin/{branch}"], cwd=CLONE)
        git(["clean", "-fd"], cwd=CLONE)  # drop leftovers (e.g. from a prior --dry-run)
        return
    try:
        git(["clone", remote, CLONE], cwd=ROOT)
    except RuntimeError as e:
        if "not found" in str(e).lower() or "Repository not found" in str(e):
            sys.exit(
                "ERROR: the wiki Git repo does not exist yet.\n"
                "GitHub creates it only after the FIRST page is saved via the web UI.\n"
                f"  1. Open the repo's Wiki tab and create + save any page once.\n"
                f"  2. Re-run: python3 tools/sync-wiki.py\n"
                f"(wiki remote: {remote})")
        raise


def mirror_pages():
    """Make the clone's top-level *.md match src/docs/wiki exactly. Returns (added,
    updated, removed) basename lists."""
    src = {f for f in os.listdir(WIKI_SRC) if f.endswith(".md")}
    dst = {f for f in os.listdir(CLONE)
           if f.endswith(".md") and os.path.isfile(os.path.join(CLONE, f))}
    added, updated, removed = [], [], []
    for f in sorted(src):
        s, d = os.path.join(WIKI_SRC, f), os.path.join(CLONE, f)
        new = open(s, encoding="utf-8").read()
        if f not in dst:
            added.append(f)
        elif open(d, encoding="utf-8").read() != new:
            updated.append(f)
        else:
            continue
        with open(d, "w", encoding="utf-8") as fh:
            fh.write(new)
    for f in sorted(dst - src):
        os.remove(os.path.join(CLONE, f))
        removed.append(f)
    return added, updated, removed


def main():
    ap = argparse.ArgumentParser(description="Publish src/docs/wiki/ to the GitHub wiki.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change, commit/push nothing")
    ap.add_argument("-m", "--message", default="Sync wiki from src/docs/wiki",
                    help="commit message")
    ap.add_argument("--remote", default=None, help="override the wiki remote URL")
    a = ap.parse_args()

    if not os.path.isdir(WIKI_SRC):
        sys.exit(f"ERROR: wiki source not found: {WIKI_SRC}")
    if not any(f.endswith(".md") for f in os.listdir(WIKI_SRC)):
        sys.exit(f"ERROR: no Markdown pages under {WIKI_SRC}")

    remote = a.remote or wiki_remote_from_origin()
    print(f"Wiki remote: {remote}")
    ensure_clone(remote)

    added, updated, removed = mirror_pages()
    changes = [("added", added), ("updated", updated), ("removed", removed)]
    if not any(lst for _, lst in changes):
        print("Wiki already up to date — nothing to do.")
        return
    for label, lst in changes:
        for f in lst:
            print(f"  {label:8} {f}")

    if a.dry_run:
        print("\n--dry-run: not committing or pushing.")
        return

    git(["add", "-A"], cwd=CLONE)
    git(["commit", "-m", a.message], cwd=CLONE)
    git(["push", "origin", "HEAD"], cwd=CLONE)
    n = len(added) + len(updated) + len(removed)
    print(f"\nPushed {n} page change(s) to the wiki.")


if __name__ == "__main__":
    main()
