#!/usr/bin/env python3
"""Localize the tokenized OBS collection for THIS machine: replace the
__RACECAST_ASSETS__/__RACECAST_SHEET__/__RACECAST_MEDIA__/__RACECAST_GRAPHICS__ tokens with this
machine's real paths/values and write an importable collection.
Works from the repo (src/) or the distributed package — same ./obs ./assets layout.

Usage: python3 setup-assets.py [--out PATH] [--assets DIR] [--template FILE]
"""
import argparse, json, os, re, sys

ASSETS_TOKEN = "__RACECAST_ASSETS__"
SHEET_TOKEN = "__RACECAST_SHEET__"
MEDIA_TOKEN = "__RACECAST_MEDIA__"
GRAPHICS_TOKEN = "__RACECAST_GRAPHICS__"


def media_dir(base):
    """Default clip dir. setup-assets.py sits at src/ (repo) or <pkg>/ (package):
    repo (base basename 'src') -> <repo>/runtime/media ; package -> <base>/media."""
    if os.path.basename(base) == "src":
        return os.path.join(os.path.dirname(base), "runtime", "media")
    return os.path.join(base, "media")


def graphics_dir(base):
    """Default graphics dir. setup-assets.py sits at src/ (repo) or <pkg>/ (package):
    repo (base basename 'src') -> <repo>/runtime/graphics ; package -> <base>/graphics."""
    if os.path.basename(base) == "src":
        return os.path.join(os.path.dirname(base), "runtime", "graphics")
    return os.path.join(base, "graphics")


# ---- Discord interview audio: one logical source, per-platform realization.
# The committed collection carries the macOS form (a real Mac export). At
# localize time the platform is known, so the source is swapped in place;
# tools/tokenize-obs.py folds any variant back (keep the two ends in sync).
# Windows "priority" 2 = WINDOW_PRIORITY_EXE (obs window-helpers.h) — match
# any Discord.exe window, never the volatile channel-name window title.
# Linux needs the obs-pipewire-audio-capture plugin (untested, see docs);
# "MatchPriorty" (sic) is the plugin's actual settings key, 0 = binary name.
DISCORD_AUDIO_UUID = "0085d4f3-bf43-4aef-9fe4-28cfd3270c7d"
DISCORD_AUDIO_VARIANTS = {
    "darwin": ("sck_audio_capture",
               {"type": 1, "application": "com.hnc.Discord"}),
    "win": ("wasapi_process_output_capture",
            {"window": "Discord:Chrome_WidgetWin_1:Discord.exe", "priority": 2}),
    "linux": ("pipewire_audio_application_capture",
              {"TargetName": "Discord", "MatchPriorty": 0}),
}


def discord_variant(platform):
    """(source id, settings) for this platform, or None when unknown."""
    if platform.startswith("win"):
        return DISCORD_AUDIO_VARIANTS["win"]
    if platform == "darwin":
        return DISCORD_AUDIO_VARIANTS["darwin"]
    if platform.startswith("linux"):
        return DISCORD_AUDIO_VARIANTS["linux"]
    return None


def localize_discord_audio(collection, platform):
    """Swap the Discord audio source to this platform's variant, in place.
    Returns the new source id, or None (source absent / unknown platform —
    never fails, same contract as the missing-graphics warnings)."""
    variant = discord_variant(platform)
    if variant is None:
        return None
    src_id, settings = variant
    for s in collection.get("sources", []):
        if s.get("uuid") == DISCORD_AUDIO_UUID:
            s["id"] = src_id
            s["versioned_id"] = src_id
            s["settings"] = dict(settings)
            return src_id
    return None


def apply_collection_name(collection, name):
    """Set the OBS collection's top-level display name to `name` (the active
    profile's OBS_COLLECTION). Blank/None -> leave the template name untouched.
    Mutates and returns `collection` (consistent with the other transforms)."""
    if name:
        collection["name"] = name
    return collection


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root
    into os.environ. Real environment variables win (setdefault). No dependency.

    SECURITY: bounded to the project (nearest ancestor with a .git/.env.example
    marker) so a stray .env in an unrelated parent dir is never loaded."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, m)) for m in (".git", ".env.example")):
            candidates.append(d)
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def replace_tokens(obj, mapping):
    """Recursively replace each token->value in every string value.
    Done on the parsed JSON (not raw text) so backslashes/quotes in a path —
    e.g. Windows 'C:\\Users\\...' — are escaped correctly on re-serialization."""
    if isinstance(obj, dict):
        return {k: replace_tokens(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_tokens(v, mapping) for v in obj]
    if isinstance(obj, str):
        for tok, val in mapping.items():
            obj = obj.replace(tok, val)
        return obj
    return obj


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(base)  # picks up machine vars from a gitignored .env at repo/package root
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(base, "assets"))
    ap.add_argument("--template", default=None)
    ap.add_argument("--out", default=os.path.join(base, "obs", "IRO_Endurance.import.json"))
    ap.add_argument("--media", default=media_dir(base),
                    help="Folder with intro.mp4/outro.mp4 for the Intro/Outro "
                         "scenes (replaces __RACECAST_MEDIA__). Default: media_dir().")
    ap.add_argument("--graphics", default=graphics_dir(base),
                    help="Folder with the broadcast graphics (<Label>.png) for the "
                         "image sources (replaces __RACECAST_GRAPHICS__). Default: graphics_dir().")
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID injected into the HUD browser source. "
                         "Default: env RACECAST_SHEET_ID (from the active profile).")
    ap.add_argument("--collection", default=os.environ.get("RACECAST_OBS_COLLECTION"),
                    help="OBS scene-collection display name written into the import "
                         "JSON. Default: env RACECAST_OBS_COLLECTION (active profile).")
    a = ap.parse_args()

    tpl = a.template
    if tpl is None:
        for cand in ("IRO_Endurance.template.json", "IRO_Endurance.json"):
            p = os.path.join(base, "obs", cand)
            if os.path.exists(p):
                tpl = p
                break
    if not tpl or not os.path.exists(tpl):
        sys.exit(f"ERROR: OBS template not found under {os.path.join(base, 'obs')}")
    if not os.path.isdir(a.assets):
        sys.exit(f"ERROR: assets folder missing: {a.assets}")

    try:
        with open(tpl, encoding="utf-8") as fh:
            collection = json.load(fh)
    except (OSError, ValueError) as e:
        sys.exit(f"ERROR: could not read OBS template {tpl}: {e}")

    raw = json.dumps(collection)
    mapping = {}
    if ASSETS_TOKEN in raw:
        mapping[ASSETS_TOKEN] = a.assets
    if SHEET_TOKEN in raw:
        if not a.sheet_id:
            sys.exit(f"ERROR: the collection references the HUD sheet ({SHEET_TOKEN}) but no "
                     "Sheet ID is set. Set SHEET_ID in the active profile "
                     "(profiles/<name>/profile.env) or pass --sheet-id.")
        mapping[SHEET_TOKEN] = a.sheet_id
    if MEDIA_TOKEN in raw:
        mapping[MEDIA_TOKEN] = a.media
        missing = [f for f in ("intro.mp4", "outro.mp4")
                   if not os.path.isfile(os.path.join(a.media, f))]
        if missing:
            print(f"  WARNING: Intro/Outro clip(s) missing in {a.media}: "
                  f"{', '.join(missing)} — run get-media.py (OBS will show black "
                  "until then).")
    if GRAPHICS_TOKEN in raw:
        mapping[GRAPHICS_TOKEN] = a.graphics
        refs = sorted(set(re.findall(r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)", raw)))
        missing = [f for f in refs if not os.path.isfile(os.path.join(a.graphics, f))]
        if missing:
            print(f"  WARNING: graphic(s) missing in {a.graphics}: "
                  f"{', '.join(missing)} — run get-graphics.py (OBS shows black "
                  "until then).")

    localized = replace_tokens(collection, mapping)
    swapped = localize_discord_audio(localized, sys.platform)
    apply_collection_name(localized, a.collection)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(localized, fh, ensure_ascii=False, indent=4)
    print(f"OK -> {a.out}")
    if ASSETS_TOKEN in mapping:
        print(f"  Asset paths now point to: {a.assets}")
    if SHEET_TOKEN in mapping:
        print(f"  HUD sheet ID injected: {a.sheet_id}")
    if MEDIA_TOKEN in mapping:
        print(f"  Intro/Outro clip dir: {a.media}")
    if GRAPHICS_TOKEN in mapping:
        print(f"  Graphics dir: {a.graphics}")
    if a.collection:
        print(f"  OBS collection name: {a.collection}")
    if swapped:
        print(f"  Discord audio source: {swapped}")
    elif discord_variant(sys.platform) is None:
        print(f"  NOTE: no Discord audio variant for {sys.platform} — macOS form kept.")
    else:
        print("  WARNING: Discord audio source not found in the collection.")
    print(f"OBS: Scene Collection -> Import -> {a.out}")
    print("IMPORTANT: do NOT move this folder afterwards (OBS stores absolute paths).")


if __name__ == "__main__":
    main()
