#!/usr/bin/env python3
"""Localize the tokenized OBS collection for THIS machine: replace the
__RACECAST_ASSETS__/__RACECAST_SHEET__/__RACECAST_MEDIA__/__RACECAST_GRAPHICS__ tokens with this
machine's real paths/values and write an importable collection.
Works from the repo (src/) or the distributed package — same ./obs ./assets layout.

Usage: python3 setup-assets.py [--out PATH] [--assets DIR] [--template FILE]
"""
import argparse, json, os, sys

# Load the sibling decision helper (scripts/ sits next to this script in both
# the repo and the package). setup-assets stays config.py-free, but discord_web
# is a tiny pure stdlib helper — importing it does not pull in the heavy resolver.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import discord_web  # noqa: E402
import overlay_build  # noqa: E402  (pure stdlib helper — no heavy resolver pulled in)
import placeholders  # noqa: E402  (pure stdlib helper — fills missing assets)

POV_SOURCE_NAME = overlay_build.OVERLAY_SLOT_OBS_SOURCES["pov"]

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
# Linux needs the obs-pipewire-audio-capture plugin (not in OBS core — install it
# on every Linux box, see docs). "MatchPriorty" (sic) is the plugin's actual settings
# key; it only orders the UI list — the plugin matches TargetName case-INsensitively
# against the node's binary/app-name/node-name (astrcmpi), so "Discord"/"Firefox" hit
# regardless of case. Verified: Firefox capture confirmed on ARM64 Linux (PR #179).
DISCORD_AUDIO_UUID = "0085d4f3-bf43-4aef-9fe4-28cfd3270c7d"
DISCORD_AUDIO_VARIANTS = {
    "darwin": ("sck_audio_capture",
               {"type": 1, "application": "com.hnc.Discord"}),
    "win": ("wasapi_process_output_capture",
            {"window": "Discord:Chrome_WidgetWin_1:Discord.exe", "priority": 2}),
    "linux": ("pipewire_audio_application_capture",
              {"TargetName": "Discord", "MatchPriorty": 0}),
}


def discord_variant(platform, web=False, browser="Firefox"):
    """(source id, settings) for this platform, or None when unknown.
    On Linux with web=True, target the browser running Discord-web instead of a
    native Discord process — same pipewire source type, only TargetName differs,
    so the panel/Companion mute & volume bindings stay intact."""
    if platform.startswith("win"):
        return DISCORD_AUDIO_VARIANTS["win"]
    if platform == "darwin":
        return DISCORD_AUDIO_VARIANTS["darwin"]
    if platform.startswith("linux"):
        if web:
            return ("pipewire_audio_application_capture",
                    {"TargetName": browser, "MatchPriorty": 0})
        return DISCORD_AUDIO_VARIANTS["linux"]
    return None


def localize_discord_audio(collection, platform, web=False, browser="Firefox"):
    """Swap the Discord audio source to this platform's variant, in place.
    Returns the new source id, or None (source absent / unknown platform —
    never fails, same contract as the missing-graphics warnings)."""
    variant = discord_variant(platform, web=web, browser=browser)
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


def apply_pov_transform(collection, overrides):
    """Set pos/bounds of EVERY scene item named POV_SOURCE_NAME ('Feed POV'),
    anywhere in the collection tree, from `overrides` (a pov_box_from_css dict:
    any subset of left/top/width/height). Unset keys keep the item's existing
    value, so a partial override leaves the rest at the template base. No-op on
    falsy `overrides`. Mutates and returns `collection` (same contract as
    apply_collection_name / localize_discord_audio)."""
    if not overrides:
        return collection

    def visit(node):
        if isinstance(node, dict):
            if (node.get("name") == POV_SOURCE_NAME
                    and isinstance(node.get("pos"), dict)
                    and isinstance(node.get("bounds"), dict)):
                if "left" in overrides:
                    node["pos"]["x"] = overrides["left"]
                if "top" in overrides:
                    node["pos"]["y"] = overrides["top"]
                if "width" in overrides:
                    node["bounds"]["x"] = overrides["width"]
                if "height" in overrides:
                    node["bounds"]["y"] = overrides["height"]
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(collection)
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
    ap.add_argument("--out", default=os.path.join(base, "obs", "GT_Endurance.import.json"))
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
    ap.add_argument("--overlay-css", default=None,
                    help="Profile overlay hud.css whose #pov box position/size is "
                         "synced onto the OBS 'Feed POV' scene item. Default: none.")
    a = ap.parse_args()

    tpl = a.template
    if tpl is None:
        for cand in ("GT_Endurance.template.json", "GT_Endurance.json"):
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
        filled = placeholders.fill_missing(
            ["intro.mp4", "outro.mp4"], a.media, placeholders.media_placeholder_path())
        if filled:
            print(f"  NOTE: wrote neutral placeholder clip for missing "
                  f"{', '.join(filled)} in {a.media} (no real Intro/Outro configured "
                  "— run get-media.py to replace).")
    if GRAPHICS_TOKEN in raw:
        mapping[GRAPHICS_TOKEN] = a.graphics
        refs = placeholders.expected_graphics_from_template(raw)
        filled = placeholders.fill_missing(
            refs, a.graphics, placeholders.graphic_placeholder_path())
        if filled:
            print(f"  NOTE: wrote transparent placeholder for missing graphic(s) in "
                  f"{a.graphics}: {', '.join(filled)} (no real asset configured — "
                  "run get-graphics.py to replace).")

    localized = replace_tokens(collection, mapping)
    web = discord_web.use_web(sys.platform, os.environ)
    # Only probe for a running browser when the web variant is actually in play —
    # detect_running_browser() spawns pgrep subprocesses we'd otherwise discard on
    # every macOS/Windows/native-Linux setup.
    browser = discord_web.resolve_browser(
        os.environ, discord_web.detect_running_browser() if web else None)
    swapped = localize_discord_audio(localized, sys.platform, web=web, browser=browser)
    apply_collection_name(localized, a.collection)
    pov = {}
    if a.overlay_css and os.path.isfile(a.overlay_css):
        try:
            with open(a.overlay_css, encoding="utf-8") as fh:
                pov = overlay_build.pov_box_from_css(fh.read())
        except OSError as e:
            print(f"  NOTE: could not read overlay CSS {a.overlay_css}: {e}")
        apply_pov_transform(localized, pov)
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
    if pov:
        print(f"  POV box synced to OBS '{POV_SOURCE_NAME}': {pov}")
    if swapped:
        print(f"  Discord audio source: {swapped}")
        if web:
            print(f"  Discord interview audio: capturing browser '{browser}' "
                  "(Discord-web) — open it and join the voice channel manually")
    elif discord_variant(sys.platform) is None:
        print(f"  NOTE: no Discord audio variant for {sys.platform} — macOS form kept.")
    else:
        print("  WARNING: Discord audio source not found in the collection.")
    print(f"OBS: Scene Collection -> Import -> {a.out}")
    print("IMPORTANT: do NOT move this folder afterwards (OBS stores absolute paths).")


if __name__ == "__main__":
    main()
