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


def download(url, dst, opener=None):
    """Fetch `url` to file path `dst` (HTTPS, cert-verified)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    resp = opener(req, timeout=120)
    try:
        with open(dst, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def extract_binary(archive, dest_dir):
    """Extract the archive (zip or tar.gz) into dest_dir with the safe_member
    guard and return the path of the contained iro binary, or None."""
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if safe_member(n)]
            zf.extractall(dest_dir, members=names)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            members = [mem for mem in tf.getmembers() if safe_member(mem.name)]
            tf.extractall(dest_dir, members=members)
    for name in ("iro.exe", "iro"):
        path = os.path.join(dest_dir, name)
        if os.path.isfile(path):
            return path
    return None


def perform(plan):
    """Execute a swap_plan. Steps are tiny on purpose — the logic lives in
    swap_plan() where it is unit-tested."""
    for step in plan:
        if step[0] == "rename":
            os.replace(step[1], step[2])
        elif step[0] in ("move", "replace"):
            shutil.move(step[1], step[2]) if step[0] == "move" else os.replace(step[1], step[2])
        elif step[0] == "chmod":
            os.chmod(step[1], os.stat(step[1]).st_mode | 0o755)


def confirmed(answer):
    return answer.strip().lower().startswith("y")


def main():
    ap = argparse.ArgumentParser(prog="update", add_help=True)
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--current", default="dev", help=argparse.SUPPRESS)  # injected by iro
    a = ap.parse_args()

    if parse_version(a.current) is None:
        sys.exit("update: running from source — update with `git pull` instead.")
    try:
        release = fetch_latest()
    except Exception as exc:
        sys.exit(f"update: cannot reach GitHub releases ({exc}). Check your connection.")

    action = classify(release, sys.platform, a.current)
    if action[0] == "error":
        sys.exit(f"update: {action[1]}")
    if action[0] == "up-to-date":
        print(f"up to date ({a.current}; latest release is {action[1]}).")
        return
    if action[0] == "building":
        sys.exit(f"update: {action[1]} is out but the binaries are still building — "
                 "retry in a few minutes.")

    _, tag, url = action
    if a.check:
        print(f"update available: {a.current} -> {tag}  (run `iro update` to install)")
        return
    print(f"update: {a.current} -> {tag}")
    if not a.yes and not confirmed(input("Download and replace this binary? [y/N] ")):
        print("aborted.")
        return

    exe = sys.executable
    with tempfile.TemporaryDirectory() as td:
        archive = os.path.join(td, asset_name(sys.platform))
        print("Downloading:", url)
        download(url, archive)
        new = extract_binary(archive, td)
        if not new:
            sys.exit("update: archive did not contain the iro binary — aborted, nothing changed.")
        perform(swap_plan(sys.platform, exe, new))
    print(f"updated to {tag} — restart iro to use it.")
    if sys.platform.startswith("win"):
        print("(the old binary was kept as iro-old.exe and is removed on the next start)")


if __name__ == "__main__":
    main()
