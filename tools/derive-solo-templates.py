#!/usr/bin/env python3
"""Maintainer tool (not shipped): derive the two solo OBS scene collections from the
proven src/obs/GT_Racing_Endurance.json so they stay OBS-valid and regenerable.

Run: python3 tools/derive-solo-templates.py   (rewrites src/obs/GT_Racing_Solo_*.json)

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
    "mic_src": "aaaaaaa6-0000-4000-8000-000000000006",
    "mic_scene": "bbbbbbb6-0000-4000-8000-000000000006",
}

DROP_SCENES = {"Stint", "Splitscreen"}
DROP_SOURCES = {"Feed A", "Feed B"}

# Committed device tokens (localized per OS by setup-assets.localize_device_sources).
CAPTURE_TOKEN = "__RACECAST_CAPTURE__"
WEBCAM_TOKEN = "__RACECAST_WEBCAM__"
MIC_TOKEN = "__RACECAST_MIC__"

# Scenes the "Commentary Mic" nested scene is wired into as an item — audible
# everywhere except the rendered Intro/Outro clips (which carry their own audio).
MIC_TARGET_SCENES = ("Program", "Interview", "Standby", "Intermission", "Discord")

# scene_order after derivation (drops Stint/Splitscreen, adds the device scenes).
SCENE_ORDER = ["Program", "Standby", "Intro", "Outro", "Interview", "Discord",
               "Intermission", "Solo Capture", "Solo Webcam", "Commentary Mic"]

START_SCENE = "Standby"

OUTPUTS = ("GT_Racing_Solo_Commentary.json", "GT_Racing_Solo_POV.json")


def _by_name(sources):
    return {s.get("name"): s for s in sources}


def _device_leaf(template_leaf, uuid, name, token, source_id="av_capture_input",
                  settings_key="device"):
    """Clone a proven leaf source and retarget it as a device source carrying the
    given token. Only name/uuid/id/versioned_id/settings are overridden — every
    other OBS-required field is inherited from the template. Defaults match the
    committed macOS video-capture form (av_capture_input/device); the audio mic
    leaf overrides source_id/settings_key to the macOS coreaudio form."""
    leaf = copy.deepcopy(template_leaf)
    leaf["name"] = name
    leaf["uuid"] = uuid
    leaf["id"] = source_id
    leaf["versioned_id"] = source_id
    leaf["settings"] = {settings_key: token}
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


def _nested_scene_item(template_item, name, src_uuid, item_id):
    """Clone a proven audio-style scene item (bounds_type 0 — no visual footprint,
    the shape already used to reference the "Discord" scene from other scenes) and
    retarget it to point at a different nested scene. Used to wire the "Commentary
    Mic" scene into the five target scenes."""
    it = copy.deepcopy(template_item)
    it["name"] = name
    it["source_uuid"] = src_uuid
    it["id"] = item_id
    # Audio-only reference (no visual footprint) — carry no show/hide transition
    # rather than inheriting the template item's 300 ms (cosmetic; the timing is
    # meaningless for an item that never renders).
    it["show_transition"] = {"duration": 0}
    it["hide_transition"] = {"duration": 0}
    return it


def _add_mic_reference(scene, mic_ref_template, mic_scene_uuid):
    """Deep-copy `scene` and append a "Commentary Mic" nested-scene item — the
    same pattern other scenes already use to reference "Discord"."""
    scene = copy.deepcopy(scene)
    next_id = int(scene["settings"].get("id_counter", 0)) + 1
    item = _nested_scene_item(mic_ref_template, "Commentary Mic", mic_scene_uuid, next_id)
    scene["settings"]["items"].append(item)
    scene["settings"]["id_counter"] = next_id
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
    with open(os.path.join(OBS, "GT_Racing_Endurance.json"), encoding="utf-8") as fh:
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
    # The existing "Discord" nested-scene reference is the template for wiring in
    # the new "Commentary Mic" nested-scene reference (same bounds_type-0 shape).
    discord_ref_item = next(it for it in items if it.get("name") == "Discord")

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
    # Commentary Mic: audible in Program (nested-scene reference, no visual footprint).
    mic_item_program = _nested_scene_item(discord_ref_item, "Commentary Mic",
                                          U["mic_scene"], item_id=32)
    new_items.append(mic_item_program)
    program["settings"]["items"] = new_items
    program["settings"]["id_counter"] = max(
        int(program["settings"].get("id_counter", 0)), 32)

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
    # Commentary Mic device leaf (macOS coreaudio_input_capture form) + its wrapping
    # scene (cloned from Discord, the audio-scene precedent).
    mic_src = _device_leaf(pov_leaf, U["mic_src"], "Commentary Mic Device", MIC_TOKEN,
                           source_id="coreaudio_input_capture", settings_key="device_id")
    # The commentary mic is the PRIMARY audio of a solo commentary broadcast, so it
    # ships HOT (unmuted) — unlike the muted-by-default capture/webcam leaves. The
    # operator can still mute it from the panel Audio bus.
    mic_src["muted"] = False
    mic_scene = _device_scene(discord_scene, U["mic_scene"], "Commentary Mic",
                              U["mic_src"], "Commentary Mic Device")

    # Wire the "Commentary Mic" scene into the remaining four target scenes (Program
    # already got its reference above, built inline with the rest of its items).
    other_targets = [n for n in MIC_TARGET_SCENES if n != "Program"]
    mic_targets = {name: _add_mic_reference(by[name], discord_ref_item, U["mic_scene"])
                   for name in other_targets}

    # Remove the endurance-only scenes/sources, substitute the mic-wired scenes, then
    # append the solo additions.
    kept = []
    for s in col["sources"]:
        name = s.get("name")
        if name in (DROP_SCENES | DROP_SOURCES):
            continue
        kept.append(mic_targets[name] if name in mic_targets else s)
    kept.extend([cap_scene, cam_scene, mic_scene, cap_src, cam_src, mic_src, program])
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
