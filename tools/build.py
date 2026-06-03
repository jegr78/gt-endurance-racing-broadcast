#!/usr/bin/env python3
"""Build the distributable from src/ (single source of truth).
Produces dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip.
Usage: python3 tools/build.py
"""
import json, os, re, shutil, sys, zipfile

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
    cp("setup-assets.py", "setup-assets.py")
    cp("assets", "assets")
    cp("scripts", "scripts")
    cp("relay", "relay")  # iro-feeds.py + get-cookies.py

    # .env template (repo root, not src/) so producers can set their own IRO_SHEET_ID
    shutil.copy2(os.path.join(ROOT, ".env.example"), os.path.join(PKG, ".env.example"))

    # companion: copy + strip password (defense in depth)
    os.makedirs(os.path.join(PKG, "companion"))
    cfg = json.load(open(os.path.join(SRC, "companion", "iro-buttons.companionconfig"), encoding="utf-8"))
    blank_pass(cfg)
    json.dump(cfg, open(os.path.join(PKG, "companion", "iro-buttons.companionconfig"), "w", encoding="utf-8"), indent=1)

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

    tpl = open(os.path.join(PKG, "obs", "IRO_Endurance.template.json"), encoding="utf-8").read()
    relay = open(os.path.join(PKG, "relay", "iro-feeds.py"), encoding="utf-8").read()
    # Re-read the SHIPPED companion config from disk (not the in-memory cfg) so the
    # password check actually verifies what was written, not what we already blanked.
    written = json.load(open(os.path.join(PKG, "companion", "iro-buttons.companionconfig"), encoding="utf-8"))
    blob = json.dumps(written)
    checks = {
        "companion pov buttons": "pov/reload" in blob,
        "companion password empty": not has_pw(written),
        "obs tokenized": "__IRO_ASSETS__/" in tpl and "GoogleDrive" not in tpl,
        "obs sheet tokenized": "__IRO_SHEET__" in tpl
                               and not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", tpl),
        "obs timer tokenized": "__IRO_TIMER__" in tpl and "stagetimer.io/output/" not in tpl,
        "relay pov endpoint": "pov/reload" in relay,
        "no .sh/.bat shipped": not any(fn.endswith((".sh", ".bat")) for _, _, fs in os.walk(PKG) for fn in fs),
        "preflight shipped": os.path.isfile(os.path.join(PKG, "scripts", "preflight.py")),
        ".env.example shipped": os.path.isfile(os.path.join(PKG, ".env.example")),
        "no sheet url in relay": not re.search(r"/spreadsheets/d/[A-Za-z0-9_-]{20,}/", relay),
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"Built {PKG}")
    print(f"ZIP   {zip_path}  ({os.path.getsize(zip_path)//1024} KB)")
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
    if bad:
        sys.exit("BUILD VERIFY FAILED: " + ", ".join(bad))


if __name__ == "__main__":
    main()
