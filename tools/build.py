#!/usr/bin/env python3
"""Build the distributable from src/ (single source of truth).
Produces dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip.
Usage: python3 tools/build.py
"""
import json, os, re, shutil, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
PKG = os.path.join(DIST, "IRO_Broadcast_Package")


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
    for f in ("IRO_Broadcast_Setup_Guide.md", "IRO_cheat_sheets.html", "README_SETUP.md"):
        cp(f"docs/{f}", f)
    cp("director/director-panel.html", "director-panel.html")
    cp("obs/hud.html", "hud.html")
    cp("obs/timer.html", "timer.html")
    cp("setup-assets.py", "setup-assets.py")
    cp("iro.py", "iro.py")
    cp("iro_ui.py", "iro_ui.py")   # windowed Control Center launcher (iro-ui)
    cp("assets", "assets")
    cp("scripts", "scripts")
    cp("relay", "relay")  # iro-feeds.py + get-cookies.py
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

    # .env template (repo root, not src/) so producers can set their own IRO_SHEET_ID
    shutil.copy2(os.path.join(ROOT, ".env.example"), os.path.join(PKG, ".env.example"))

    # companion: copy + strip password (defense in depth)
    os.makedirs(os.path.join(PKG, "companion"))
    with open(os.path.join(SRC, "companion", "iro-buttons.companionconfig"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    blank_pass(cfg)
    with open(os.path.join(PKG, "companion", "iro-buttons.companionconfig"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)

    # obs: ship the tokenized collection as .template.json (setup-assets localizes it)
    os.makedirs(os.path.join(PKG, "obs"))
    shutil.copy2(os.path.join(SRC, "obs", "IRO_Endurance.json"),
                 os.path.join(PKG, "obs", "IRO_Endurance.template.json"))

    # drop any stray __pycache__ from copied trees
    for root, dirs, _ in os.walk(PKG):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d)); dirs.remove(d)

    # zip
    zip_path = os.path.join(DIST, "IRO_Broadcast_Package.zip")
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

    with open(os.path.join(PKG, "obs", "IRO_Endurance.template.json"), encoding="utf-8") as fh:
        tpl = fh.read()
    with open(os.path.join(PKG, "relay", "iro-feeds.py"), encoding="utf-8") as fh:
        relay = fh.read()
    # Re-read the SHIPPED companion config from disk (not the in-memory cfg) so the
    # password check actually verifies what was written, not what we already blanked.
    with open(os.path.join(PKG, "companion", "iro-buttons.companionconfig"), encoding="utf-8") as fh:
        written = json.load(fh)
    blob = json.dumps(written)
    checks = {
        "companion pov buttons": "pov/reload" in blob,
        "companion password empty": not has_pw(written),
        "obs graphics tokenized": "__IRO_GRAPHICS__/" in tpl
            and "GoogleDrive" not in tpl and "drive.google.com" not in tpl,
        # The HUD no longer embeds the sheet (the relay serves /hud), so the
        # collection legitimately has no __IRO_SHEET__ token — just assert no raw
        # sheet URL ever leaks in.
        "obs no raw sheet url": not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", tpl),
        "obs timer is relay-served": "http://127.0.0.1:8088/timer" in tpl
            and "__IRO_TIMER__" not in tpl and "stagetimer" not in tpl,
        "relay timer endpoint": "/timer/data" in relay,
        "obs media tokenized": "__IRO_MEDIA__/" in tpl,
        "relay pov endpoint": "pov/reload" in relay,
        "no .sh/.bat shipped": not any(fn.endswith((".sh", ".bat")) for _, _, fs in os.walk(PKG) for fn in fs),
        "preflight shipped": os.path.isfile(os.path.join(PKG, "scripts", "preflight.py")),
        "timer html shipped": os.path.isfile(os.path.join(PKG, "timer.html")),
        ".env.example shipped": os.path.isfile(os.path.join(PKG, ".env.example")),
        "no sheet url in relay": not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", relay),
        "iro cli shipped": os.path.isfile(os.path.join(PKG, "iro.py")),
        "iro-ui launcher shipped": os.path.isfile(os.path.join(PKG, "iro_ui.py")),
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
    for fn in sorted(set(re.findall(r"__IRO_GRAPHICS__/([^\"\\]+\.png)", tpl))):
        ok = os.path.isfile(os.path.join(PKG, "graphics", fn))
        print(f"  [{'OK' if ok else 'warn'}] graphic {fn} "
              f"{'present' if ok else 'MISSING (run get-graphics.py before release)'}")
    if bad:
        sys.exit("BUILD VERIFY FAILED: " + ", ".join(bad))


if __name__ == "__main__":
    main()
