#!/usr/bin/env python3
"""Maintainer tool (not shipped): derive the two solo OBS scene collections from the
proven src/obs/GT_Endurance.json so they stay OBS-valid and regenerable.

Run: python3 tools/derive-solo-templates.py   (rewrites src/obs/GT_Solo_*.json)

Strategy: deep-copy real nodes from the endurance collection and mutate minimally, so
every OBS-required field shape is inherited from a proven-importable file. We never
hand-author scaffold dicts (a missing key makes OBS refuse the import).

Result per file: the A/B ping-pong is gone (Feed A/B and the Stint/Splitscreen scenes
dropped). A "Program" scene keeps Feed POV + the HUD/graphics overlays and adds two new
device inputs — "Solo Capture Device" (full-frame background) and "Solo Webcam Device"
(bottom-left PiP) — each wrapped in its own scene ("Solo Capture" / "Solo Webcam", the
Discord "scene wraps one source" model — mirroring how the Discord scene wraps the
distinctly-named "Discord Audio Capture" leaf). The device leaf sources carry the
tokens __RACECAST_CAPTURE__ / __RACECAST_WEBCAM__; the committed form is the macOS
av_capture_input source, and setup-assets.py localizes the source type + device
settings per OS at import time.
"""
import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OBS = os.path.join(ROOT, "src", "obs")

# Fixed UUIDs for the added sources/scenes — deterministic, so re-runs don't churn the
# committed JSON (no uuid4()). They follow the endurance file's synthetic-uuid style.
U = {
    "cap_src": "aaaaaaa4-0000-4000-8000-000000000004",
    "cam_src": "aaaaaaa5-0000-4000-8000-000000000005",
    "cap_scene": "bbbbbbb4-0000-4000-8000-000000000004",
    "cam_scene": "bbbbbbb5-0000-4000-8000-000000000005",
    "program": "ccccccc0-0000-4000-8000-000000000000",
}

DROP_SCENES = {"Stint", "Splitscreen"}
DROP_SOURCES = {"Feed A", "Feed B"}

# Committed device tokens (localized per OS by setup-assets.localize_device_sources).
CAPTURE_TOKEN = "__RACECAST_CAPTURE__"
WEBCAM_TOKEN = "__RACECAST_WEBCAM__"

# scene_order after derivation (drops Stint/Splitscreen, adds the device scenes).
SCENE_ORDER = ["Program", "Standby", "Intro", "Outro", "Interview", "Discord",
               "Intermission", "Solo Capture", "Solo Webcam"]

START_SCENE = "Standby"

OUTPUTS = ("GT_Solo_Commentary.json", "GT_Solo_POV.json")


def _by_name(sources):
    return {s.get("name"): s for s in sources}


def _device_leaf(template_leaf, uuid, name, token):
    """Clone a proven video-input leaf source and retarget it as a macOS AV capture
    source carrying the given token. Only name/uuid/id/settings are overridden — every
    other OBS-required field is inherited from the template."""
    leaf = copy.deepcopy(template_leaf)
    leaf["name"] = name
    leaf["uuid"] = uuid
    leaf["id"] = "av_capture_input"
    leaf["versioned_id"] = "av_capture_input"
    leaf["settings"] = {"device": token}
    return leaf


def _device_scene(discord_scene, uuid, name, src_uuid, src_name):
    """Clone the Discord scene (the 'scene wraps one source' model) and point its single
    item at the given device leaf, rendered full-frame (bounds_type 2 = SCALE_INNER)."""
    scene = copy.deepcopy(discord_scene)
    scene["name"] = name
    scene["uuid"] = uuid
    item = copy.deepcopy(scene["settings"]["items"][0])
    item["name"] = src_name
    item["source_uuid"] = src_uuid
    item["visible"] = True
    item["locked"] = True
    item["bounds_type"] = 2
    item["pos"] = {"x": 0.0, "y": 0.0}
    item["bounds"] = {"x": 1920.0, "y": 1080.0}
    scene["settings"]["items"] = [item]
    return scene


def _program_item(template_item, name, src_uuid, pos, bounds, item_id):
    """Clone a proven Stint scene item (inherits every transform key) and retarget it."""
    it = copy.deepcopy(template_item)
    it["name"] = name
    it["source_uuid"] = src_uuid
    it["visible"] = True
    it["locked"] = True
    it["bounds_type"] = 2
    it["pos"] = {"x": float(pos[0]), "y": float(pos[1])}
    it["bounds"] = {"x": float(bounds[0]), "y": float(bounds[1])}
    it["id"] = item_id
    return it


def derive():
    with open(os.path.join(OBS, "GT_Endurance.json"), encoding="utf-8") as fh:
        col = json.load(fh)

    by = _by_name(col["sources"])
    stint = by["Stint"]
    discord_scene = by["Discord"]
    pov_leaf = by["Feed POV"]

    # Program scene: deep-copy Stint, rename, re-uuid.
    program = copy.deepcopy(stint)
    program["name"] = "Program"
    program["uuid"] = U["program"]

    items = program["settings"]["items"]
    # Drop the A/B feed items; keep Feed POV + HUD/overlays/graphics/flags/Discord/Standby.
    items = [it for it in items if it.get("name") not in DROP_SOURCES]

    # The Feed POV item is the cleanest transform template for the two new PiP items.
    pov_item = next(it for it in items if it.get("name") == "Feed POV")

    # Solo Capture: full-frame background at the BOTTOM of the z-order (rendered first).
    cap_item = _program_item(pov_item, "Solo Capture", U["cap_scene"],
                             (0, 0), (1920, 1080), item_id=29)
    # Solo Webcam: bottom-left PiP, inserted right after Feed POV.
    cam_item = _program_item(pov_item, "Solo Webcam", U["cam_scene"],
                             (24, 776), (384, 280), item_id=30)

    new_items = [cap_item]
    for it in items:
        new_items.append(it)
        if it.get("name") == "Feed POV":
            new_items.append(cam_item)
    program["settings"]["items"] = new_items
    program["settings"]["id_counter"] = max(
        int(program["settings"].get("id_counter", 0)), 31)

    # Device leaf sources + wrapping scenes. The leaf is named distinctly from its
    # wrapping scene ("Solo Capture Device" vs the "Solo Capture" scene) — mirroring
    # the Discord precedent (scene "Discord" wraps leaf "Discord Audio Capture") — so
    # setup-assets' by-name lookup in localize_device_sources can never collide a
    # device leaf with its wrapping scene.
    cap_src = _device_leaf(pov_leaf, U["cap_src"], "Solo Capture Device", CAPTURE_TOKEN)
    cam_src = _device_leaf(pov_leaf, U["cam_src"], "Solo Webcam Device", WEBCAM_TOKEN)
    cap_scene = _device_scene(discord_scene, U["cap_scene"], "Solo Capture",
                              U["cap_src"], "Solo Capture Device")
    cam_scene = _device_scene(discord_scene, U["cam_scene"], "Solo Webcam",
                              U["cam_src"], "Solo Webcam Device")

    # Remove the endurance-only scenes/sources, then append the solo additions.
    kept = [s for s in col["sources"]
            if s.get("name") not in (DROP_SCENES | DROP_SOURCES)]
    kept.extend([cap_scene, cam_scene, cap_src, cam_src, program])
    col["sources"] = kept

    col["scene_order"] = [{"name": n} for n in SCENE_ORDER]
    # current_scene / current_program_scene are plain strings in this collection.
    col["current_scene"] = START_SCENE
    col["current_program_scene"] = START_SCENE
    # Own display name (setup-assets still overrides it with the per-league name at
    # localize time, but the committed artifact should be self-consistent rather than
    # carrying the inherited endurance name).
    col["name"] = "GT Racing Solo"

    # Prune Splitscreen-only leftovers (#304): the Splitscreen scene itself was already
    # dropped above, but its "Split HUD" group (top-level col["groups"]) and its
    # "Splitscreen Labels" leaf source (col["sources"]) were left orphaned -- neither is
    # referenced by any scene item in the solo collections.
    col["sources"] = [s for s in col["sources"] if s.get("name") != "Splitscreen Labels"]
    if col.get("groups"):
        col["groups"] = [g for g in col["groups"] if g.get("name") != "Split HUD"]
    return col


def main():
    col = derive()
    for fn in OUTPUTS:
        path = os.path.join(OBS, fn)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(col, fh, ensure_ascii=False, indent=4)
            fh.write("\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
