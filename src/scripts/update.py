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


def classify(release, platform, current, frozen=False):
    """The whole update decision, pure. Always a (kind, detail, url) 3-tuple:
    ('dev',        None, None)   running from source -> refuse
    ('error',      message, None)  malformed release data
    ('up-to-date', tag, None)
    ('building',   tag, None)    newer release exists, platform asset not uploaded yet
    ('update',     tag, url)
    An unparseable `current` (e.g. 'dev') refuses in repo mode, but a frozen
    binary built without --version gets the latest release offered instead
    (incomparable -> never 'up-to-date')."""
    cur = parse_version(current)
    if cur is None and not frozen:
        return ("dev", None, None)
    tag = release.get("tag_name", "")
    new = parse_version(tag)
    if new is None:
        return ("error", f"unexpected tag on the latest release: {tag!r}", None)
    if cur is not None and new <= cur:
        return ("up-to-date", tag, None)
    want = asset_name(platform)
    for asset in release.get("assets", []):
        if asset.get("name") == want:
            return ("update", tag, asset.get("browser_download_url"))
    return ("building", tag, None)


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


def ui_asset_name(platform):
    """The iro-ui artifact name inside the release archive (mirrors release.yml's
    matrix): a .exe on Windows, a .app bundle on macOS, a bare binary on Linux."""
    if platform.startswith("win"):
        return "iro-ui.exe"
    if platform == "darwin":
        return "iro-ui.app"
    return "iro-ui"


def install_ui(src_dir, target_dir, platform):
    """Place the extracted iro-ui artifact next to the iro binary, replacing any
    existing one. The archive ships iro + iro-ui together, so the GUI launcher
    travels with every update. Returns the install path, or None when the archive
    carried no iro-ui (pre-1.2 releases). Best-effort: the caller treats an OSError
    as non-fatal — the iro swap has already succeeded by then."""
    name = ui_asset_name(platform)
    src = os.path.join(src_dir, name)
    if not os.path.exists(src):
        return None
    dst = os.path.join(target_dir, name)
    if os.path.isdir(dst) and not os.path.islink(dst):
        shutil.rmtree(dst)          # macOS .app is a directory bundle
    elif os.path.lexists(dst):
        os.remove(dst)
    shutil.move(src, dst)
    if not platform.startswith("win") and os.path.isfile(dst):
        os.chmod(dst, os.stat(dst).st_mode | 0o755)
    return dst


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

    # Frozen one-shots run in-process in the binary, so sys.frozen is visible
    # here; repo mode runs under a plain python3. A frozen 'dev' binary (local
    # build without --version) gets the latest release offered instead.
    frozen = bool(getattr(sys, "frozen", False))
    if parse_version(a.current) is None and not frozen:
        sys.exit("update: running from source — update with `git pull` instead.")
    try:
        release = fetch_latest()
    except Exception as exc:
        sys.exit(f"update: cannot reach GitHub releases ({exc}). Check your connection.")

    action = classify(release, sys.platform, a.current, frozen)
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
    # Tempdir NEXT TO the binary: same filesystem, so the final os.replace is an
    # atomic rename (a system tempdir can be another fs -> EXDEV; copy-overwrite
    # of a running ELF would be ETXTBSY).
    with tempfile.TemporaryDirectory(dir=os.path.dirname(exe)) as td:
        archive = os.path.join(td, asset_name(sys.platform))
        print("Downloading:", url)
        download(url, archive)
        new = extract_binary(archive, td)
        if not new:
            sys.exit("update: archive did not contain the iro binary — aborted, nothing changed.")
        try:
            perform(swap_plan(sys.platform, exe, new))
        except OSError as exc:
            hint = (" Restore by renaming iro-old.exe back to iro.exe."
                    if sys.platform.startswith("win") and not os.path.exists(exe) else "")
            sys.exit(f"update: swap failed ({exc}).{hint}")
        # The archive ships the iro-ui launcher alongside iro — install it too, but
        # never let a hiccup here undo the successful iro swap above (best-effort).
        try:
            ui_path = install_ui(td, os.path.dirname(exe), sys.platform)
        except OSError as exc:
            ui_path = None
            print(f"update: note — iro-ui not installed ({exc}); "
                  "use `iro ui` from the CLI, or reinstall the archive.")
    print(f"updated to {tag} — restart iro to use it.")
    if ui_path:
        print(f"installed {os.path.basename(ui_path)} next to iro.")
    if sys.platform.startswith("win"):
        print("(the old binary was kept as iro-old.exe and is removed on the next start)")


if __name__ == "__main__":
    main()
