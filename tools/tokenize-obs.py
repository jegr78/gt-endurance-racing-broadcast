#!/usr/bin/env python3
"""Replace absolute asset paths in an OBS collection with the __IRO_GRAPHICS__ token.

Recognized assets = every image_source 'file' path (the broadcast graphics live in
runtime/graphics and are tokenized to __IRO_GRAPHICS__/<basename>). Path matching is
separator-agnostic. Idempotent (already-tokenized paths are left alone).

Usage: tokenize-obs.py IN [OUT]
"""
import argparse, json, os, re

TOKEN = "__IRO_GRAPHICS__"
SHEET_TOKEN = "__IRO_SHEET__"
# Any /spreadsheets/d/<id>/ — the {20,} length guard skips the short token itself.
SHEET_RE = re.compile(r"(/spreadsheets/d/)[A-Za-z0-9_-]{20,}(/)")

# Discord audio source: fold any platform variant (created by setup-assets'
# localize_discord_audio — keep the two ends in sync) back to the committed
# macOS form, so round-trips from Mac and Windows yield the same template.
DISCORD_AUDIO_UUID = "0085d4f3-bf43-4aef-9fe4-28cfd3270c7d"
DISCORD_AUDIO_CANONICAL = ("sck_audio_capture",
                           {"type": 1, "application": "com.hnc.Discord"})


def canonicalize_discord_audio(d):
    """True iff a non-canonical Discord audio source was rewritten."""
    src_id, settings = DISCORD_AUDIO_CANONICAL
    for s in d.get("sources", []):
        if s.get("uuid") == DISCORD_AUDIO_UUID and s.get("id") != src_id:
            s["id"] = src_id
            s["versioned_id"] = src_id
            s["settings"] = dict(settings)
            return True
    return False


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
        counter[0] += c
        return new
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out", nargs="?", default=None)
    a = ap.parse_args()
    out = a.out or a.src

    with open(a.src, encoding="utf-8") as fh:
        d = json.load(fh)
    n = 0
    for s in d.get("sources", []):
        if s.get("id") != "image_source":
            continue
        st = s.get("settings") or {}
        f = st.get("file")
        if isinstance(f, str) and f and not f.startswith("__IRO_"):
            st["file"] = f"{TOKEN}/{base(f)}"
            n += 1
    sheet_count = [0]
    d = tokenize_sheets(d, sheet_count)
    if canonicalize_discord_audio(d):
        print("Discord audio source folded back to the canonical macOS form.")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
    print(f"tokenized {n} asset path(s) + {sheet_count[0]} sheet URL(s) -> {out}")


if __name__ == "__main__":
    main()
