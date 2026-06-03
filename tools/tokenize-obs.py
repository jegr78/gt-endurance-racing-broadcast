#!/usr/bin/env python3
"""Replace absolute asset paths in an OBS collection with the __IRO_ASSETS__ token.

Recognized assets = the PNG filenames actually present in the assets dir (default
<repo>/src/assets), so adding or renaming a graphic is picked up automatically — no
hardcoded list to keep in sync. Path matching is separator-agnostic (handles a
Windows-authored collection tokenized on macOS and vice-versa). Idempotent.

Usage: tokenize-obs.py IN [OUT] [--assets-dir DIR]
"""
import argparse, json, os, re, sys

TOKEN = "__IRO_ASSETS__"
SHEET_TOKEN = "__IRO_SHEET__"
TIMER_TOKEN = "__IRO_TIMER__"
# Any /spreadsheets/d/<id>/ — the {20,} length guard skips the short token itself.
SHEET_RE = re.compile(r"(/spreadsheets/d/)[A-Za-z0-9_-]{20,}(/)")
# Full stagetimer.io output URL incl. the signed query string (a live secret).
TIMER_RE = re.compile(r"https://stagetimer\.io/output/[^\"\s]+")


def base(path):
    """basename that splits on both / and \\, regardless of host OS."""
    return os.path.basename(path.replace("\\", "/"))


def tokenize_sheets(obj, counter):
    """Recursively replace any Google-Sheet ID in a URL with __IRO_SHEET__."""
    if isinstance(obj, dict):
        return {k: tokenize_sheets(v, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [tokenize_sheets(v, counter) for v in obj]
    if isinstance(obj, str):
        new, c = SHEET_RE.subn(rf"\g<1>{SHEET_TOKEN}\g<2>", obj)
        new, c2 = TIMER_RE.subn(TIMER_TOKEN, new)
        counter[0] += c + c2
        return new
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out", nargs="?", default=None)
    ap.add_argument("--assets-dir", default=None)
    a = ap.parse_args()
    out = a.out or a.src
    assets_dir = a.assets_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "assets")
    known = ({f for f in os.listdir(assets_dir) if f.lower().endswith(".png")}
             if os.path.isdir(assets_dir) else set())
    if not known:
        sys.exit(f"ERROR: no asset PNGs found in {assets_dir} "
                 f"(need them to know which paths to tokenize; run sync-assets first).")

    d = json.load(open(a.src, encoding="utf-8"))
    n = 0
    for s in d.get("sources", []):
        st = s.get("settings") or {}
        f = st.get("file")
        if isinstance(f, str) and base(f) in known:
            st["file"] = f"{TOKEN}/{base(f)}"
            n += 1
    sheet_count = [0]
    d = tokenize_sheets(d, sheet_count)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
    print(f"tokenized {n} asset path(s) + {sheet_count[0]} sheet/timer URL(s) -> {out}")


if __name__ == "__main__":
    main()
