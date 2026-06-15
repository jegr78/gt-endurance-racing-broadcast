#!/usr/bin/env python3
"""Build the distributable from src/ (single source of truth).
Produces dist/GT_Racecast_Package/ + dist/GT_Racecast_Package.zip.
Usage: python3 tools/build.py
"""
import json, os, re, shutil, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
PKG = os.path.join(DIST, "GT_Racecast_Package")


# The SHEET_PUSH_URL (an Apps Script webhook) is the one league secret most
# likely to leak into a committed artifact (e.g. the OBS json). The verify
# allowlist below is per-pattern, so it would miss this *class*; catch the two
# shapes — a /macros/.../exec endpoint and a ?key= query — explicitly (#103).
# Scanned only against secret-free artifacts (OBS template / relay / companion),
# never the docs, which legitimately document the webhook URL format.
_APPSCRIPT_SECRET_RE = re.compile(r"/macros/|/exec\b|[?&]key=", re.IGNORECASE)


def has_appscript_secret(text):
    """True iff `text` contains an Apps Script webhook URL pattern (/macros/ or
    /exec endpoint, or a ?key= query)."""
    return bool(_APPSCRIPT_SECRET_RE.search(text or ""))


def blank_pass(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("pass", "password") and isinstance(v, str):
                o[k] = ""
            else:
                blank_pass(v)
    elif isinstance(o, list):
        for x in o:
            blank_pass(x)


def cp(srcrel, dstrel):
    s = os.path.join(SRC, srcrel)
    d = os.path.join(PKG, dstrel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)


def main():
    if not os.path.isdir(SRC):
        sys.exit("ERROR: src/ not found")
    if os.path.exists(PKG):
        shutil.rmtree(PKG)
    os.makedirs(PKG)

    # top-level docs + director panel + setup-assets
    for f in ("Broadcast_Setup_Guide.md", "cheat_sheets.html", "README_SETUP.md"):
        cp(f"docs/{f}", f)
    cp("director/director-panel.html", "director-panel.html")
    cp("obs/hud.html", "hud.html")
    cp("obs/hud-preview.html", "hud-preview.html")
    cp("obs/splitscreen.html", "splitscreen.html")
    cp("setup-assets.py", "setup-assets.py")
    cp("racecast.py", "racecast.py")
    cp("racecast_ui.py", "racecast_ui.py")   # windowed Control Center launcher (racecast-ui)
    cp("assets", "assets")
    cp("scripts", "scripts")
    cp("relay", "relay")  # racecast-feeds.py + get-cookies.py
    cp("ui", "ui")        # Control Center server + page

    # intro/outro clips: download into the package so the artifact is self-contained.
    # Best-effort — offline / code-only builds must still succeed (the shipped
    # get-media.py lets a producer re-fetch on site if the sheet URLs change).
    media_dst = os.path.join(PKG, "media")
    os.makedirs(media_dst, exist_ok=True)
    try:
        subprocess.run([sys.executable, os.path.join(SRC, "relay", "get-media.py"),
                        "--out", media_dst], check=True, timeout=600)
    except Exception as e:
        print(f"  [WARN] intro/outro clip fetch skipped: {e}")

    # broadcast graphics: download into the package so the artifact is self-contained.
    # Best-effort (same policy as the clips) — get-graphics.py lets a producer re-fetch
    # on site when the sheet graphics change.
    graphics_dst = os.path.join(PKG, "graphics")
    os.makedirs(graphics_dst, exist_ok=True)
    try:
        subprocess.run([sys.executable, os.path.join(SRC, "relay", "get-graphics.py"),
                        "--out", graphics_dst], check=True, timeout=600)
    except Exception as e:
        print(f"  [WARN] graphics fetch skipped: {e}")

    # .env template (repo root, not src/) so producers can set their own RACECAST_SHEET_ID
    shutil.copy2(os.path.join(ROOT, ".env.example"), os.path.join(PKG, ".env.example"))

    # profiles/example/ (repo root, not src/): the league template `racecast profile
    # new` copies from. Without it the shipped package can't create a profile (#45).
    shutil.copytree(os.path.join(ROOT, "profiles", "example"),
                    os.path.join(PKG, "profiles", "example"))

    # companion: copy + strip password (defense in depth)
    os.makedirs(os.path.join(PKG, "companion"))
    with open(os.path.join(SRC, "companion", "racecast-buttons.companionconfig"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    blank_pass(cfg)
    with open(os.path.join(PKG, "companion", "racecast-buttons.companionconfig"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)

    # obs: ship the tokenized collection as .template.json (setup-assets localizes it)
    os.makedirs(os.path.join(PKG, "obs"))
    shutil.copy2(os.path.join(SRC, "obs", "GT_Endurance.json"),
                 os.path.join(PKG, "obs", "GT_Endurance.template.json"))
    # obs-browser source-build wrapper CMakeLists (used by `racecast obs-browser`
    # on Linux to compile the Browser Source plugin against the distro libobs).
    cp("obs/obs-browser-build", "obs/obs-browser-build")

    # drop any stray __pycache__ from copied trees
    for root, dirs, _ in os.walk(PKG):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d)); dirs.remove(d)

    # zip
    zip_path = os.path.join(DIST, "GT_Racecast_Package.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(PKG):
            for fn in files:
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, DIST))

    # verify
    def has_pw(o):
        if isinstance(o, dict):
            return any((k in ("pass", "password") and v) or has_pw(v) for k, v in o.items())
        if isinstance(o, list):
            return any(has_pw(x) for x in o)
        return False

    with open(os.path.join(PKG, "obs", "GT_Endurance.template.json"), encoding="utf-8") as fh:
        tpl = fh.read()
    with open(os.path.join(PKG, "relay", "racecast-feeds.py"), encoding="utf-8") as fh:
        relay = fh.read()
    # Re-read the SHIPPED companion config from disk (not the in-memory cfg) so the
    # password check actually verifies what was written, not what we already blanked.
    with open(os.path.join(PKG, "companion", "racecast-buttons.companionconfig"), encoding="utf-8") as fh:
        written = json.load(fh)
    blob = json.dumps(written)
    with open(os.path.join(PKG, "hud.html"), encoding="utf-8") as fh:
        hud = fh.read()
    checks = {
        "companion pov buttons": "pov/reload" in blob,
        "companion password empty": not has_pw(written),
        "obs graphics tokenized": "__RACECAST_GRAPHICS__/" in tpl
            and "GoogleDrive" not in tpl and "drive.google.com" not in tpl,
        # The HUD no longer embeds the sheet (the relay serves /hud), so the
        # collection legitimately has no __RACECAST_SHEET__ token — just assert no raw
        # sheet URL ever leaks in.
        "obs no raw sheet url": not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", tpl),
        # No Apps Script SHEET_PUSH_URL leaked into the secret-free artifacts (#103).
        "obs no apps-script webhook": not has_appscript_secret(tpl),
        "relay no apps-script webhook": not has_appscript_secret(relay),
        "companion no apps-script webhook": not has_appscript_secret(blob),
        "relay timer endpoint": "/timer/data" in relay,
        "obs media tokenized": "__RACECAST_MEDIA__/" in tpl,
        "relay pov endpoint": "pov/reload" in relay,
        "no .sh/.bat shipped": not any(fn.endswith((".sh", ".bat")) for _, _, fs in os.walk(PKG) for fn in fs),
        "preflight shipped": os.path.isfile(os.path.join(PKG, "scripts", "preflight.py")),
        "hud serves the clock": '<div id="clock"' in hud,
        "hud preview shipped": os.path.isfile(os.path.join(PKG, "hud-preview.html")),
        "splitscreen page shipped": os.path.isfile(os.path.join(PKG, "splitscreen.html")),
        "preview backdrop shipped": os.path.isfile(os.path.join(PKG, "assets", "preview-bg.jpg")),
        ".env.example shipped": os.path.isfile(os.path.join(PKG, ".env.example")),
        "example profile shipped": os.path.isfile(
            os.path.join(PKG, "profiles", "example", "profile.env")),
        "no sheet url in relay": not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", relay),
        "racecast cli shipped": os.path.isfile(os.path.join(PKG, "racecast.py")),
        "racecast-ui launcher shipped": os.path.isfile(os.path.join(PKG, "racecast_ui.py")),
        "services helper shipped": os.path.isfile(os.path.join(PKG, "scripts", "services.py")),
        "install-tools shipped": os.path.isfile(os.path.join(PKG, "scripts", "install_tools.py")),
        "install-apps shipped": os.path.isfile(os.path.join(PKG, "scripts", "install_apps.py")),
        "installer-common shipped": os.path.isfile(os.path.join(PKG, "scripts", "installer_common.py")),
        "old entrypoint removed: scripts/start-companion.py": not os.path.isfile(os.path.join(PKG, "scripts", "start-companion.py")),
        "old entrypoint removed: scripts/stop-companion.py": not os.path.isfile(os.path.join(PKG, "scripts", "stop-companion.py")),
        "ui server shipped": os.path.isfile(os.path.join(PKG, "ui", "ui_server.py")),
        "ui page shipped": os.path.isfile(os.path.join(PKG, "ui", "control-center.html")),
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"Built {PKG}")
    print(f"ZIP   {zip_path}  ({os.path.getsize(zip_path)//1024} KB)")
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
    for clip in ("intro.mp4", "outro.mp4"):
        ok = os.path.isfile(os.path.join(PKG, "media", clip))
        print(f"  [{'OK' if ok else 'warn'}] media {clip} "
              f"{'present' if ok else 'MISSING (run get-media.py before release)'}")
    for fn in sorted(set(re.findall(r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)", tpl))):
        ok = os.path.isfile(os.path.join(PKG, "graphics", fn))
        print(f"  [{'OK' if ok else 'warn'}] graphic {fn} "
              f"{'present' if ok else 'MISSING (run get-graphics.py before release)'}")
    if bad:
        sys.exit("BUILD VERIFY FAILED: " + ", ".join(bad))


if __name__ == "__main__":
    main()
