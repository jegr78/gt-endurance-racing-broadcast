#!/usr/bin/env python3
"""`iro update` — self-update the standalone binary from GitHub Releases.
Checks /releases/latest, compares semver tags, downloads the platform archive
and swaps the running binary (Windows: rename trick — a running exe can be
renamed but not overwritten). Frozen-only: a repo checkout updates with
`git pull`. Design: docs/superpowers/specs/2026-06-05-self-update-design.md."""
import argparse, json, os, shutil, sys, tarfile, tempfile, zipfile

REPO = "jegr78/IRO_Broadcast_Setup"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(tag):
    """'vX.Y.Z' -> (X, Y, Z); None for anything else (incl. 'dev')."""
    if not tag or not isinstance(tag, str) or not tag.startswith("v"):
        return None
    parts = tag[1:].split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def asset_name(platform):
    """The release asset for a sys.platform value (mirrors release.yml's matrix)."""
    if platform.startswith("win"):
        return "iro-windows.zip"
    if platform == "darwin":
        return "iro-macos.tar.gz"
    return "iro-linux.tar.gz"


def classify(release, platform, current):
    """The whole update decision, pure. Returns one of:
    ('dev',)                running from source -> refuse
    ('error', message)      malformed release data
    ('up-to-date', tag)
    ('building', tag)       newer release exists, platform asset not uploaded yet
    ('update', tag, url)"""
    cur = parse_version(current)
    if cur is None:
        return ("dev",)
    tag = release.get("tag_name", "")
    new = parse_version(tag)
    if new is None:
        return ("error", f"unexpected tag on the latest release: {tag!r}")
    if new <= cur:
        return ("up-to-date", tag)
    want = asset_name(platform)
    for asset in release.get("assets", []):
        if asset.get("name") == want:
            return ("update", tag, asset.get("browser_download_url"))
    return ("building", tag)


def swap_plan(platform, exe, new):
    """Ordered steps that put `new` in place of the running `exe`.
    ntpath for the Windows branch — keeps the function pure/computable when
    tests run on macOS/Linux (os.path.dirname can't split C:\\ paths there)."""
    if platform.startswith("win"):
        import ntpath
        old = ntpath.join(ntpath.dirname(exe), "iro-old.exe")
        return [("rename", exe, old), ("move", new, exe)]
    return [("replace", new, exe), ("chmod", exe)]


def safe_member(name):
    """True iff an archive member path is safe to extract (no abs, no drive, no ..)."""
    if not name or name.startswith(("/", "\\")):
        return False
    if len(name) > 1 and name[1] == ":":
        return False
    return ".." not in name.replace("\\", "/").split("/")


def fetch_latest(opener=None):
    """GET the latest-release JSON. `opener(request, timeout)` is injectable for tests."""
    import urllib.request
    req = urllib.request.Request(API_LATEST, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    with_resp = opener(req, timeout=15)
    try:
        return json.load(with_resp)
    finally:
        close = getattr(with_resp, "close", None)
        if close:
            close()
