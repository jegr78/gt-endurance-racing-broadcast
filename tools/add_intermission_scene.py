#!/usr/bin/env python3
"""Add the 'Intermission' scene to an OBS scene collection (idempotent).

Creates three sources — a full-screen background graphic
(__RACECAST_GRAPHICS__/Intermission.png), a transparent browser overlay showing
the broadcast-chat page at http://127.0.0.1:8088/intermission (1920x1080), and a
looping audio track (__RACECAST_MEDIA__/intermission.mp3) — then assembles them
into a new 'Intermission' scene and registers it in scene_order.

Deep-copies existing sources as schema-correct templates (same pattern as
tools/add_standby_cover.py). Re-running is a no-op once the 'Intermission' scene
already exists.

Usage: python3 tools/add_intermission_scene.py <collection.json>
"""
import copy, json, sys

SCENE_NAME  = "Intermission"
SCENE_UUID  = "cccccccc-0000-4000-8000-000000000001"
IMAGE_UUID  = "cccccccc-0000-4000-8000-000000000002"
CHAT_UUID   = "cccccccc-0000-4000-8000-000000000003"
MUSIC_UUID  = "cccccccc-0000-4000-8000-000000000004"
IMAGE_FILE  = "__RACECAST_GRAPHICS__/Intermission.png"
CHAT_URL    = "http://127.0.0.1:8088/intermission"
MUSIC_FILE  = "__RACECAST_MEDIA__/intermission.mp3"
CHAT_SOURCE = "Intermission Chat"
MUSIC_SOURCE = "Intermission Music"


def add_intermission_scene(d):
    """Mutate the collection dict in place. Return True if changed, False if already present."""
    srcs = d["sources"]
    if any(s.get("name") == SCENE_NAME and s.get("id") == "scene" for s in srcs):
        return False

    # --- Locate template objects ---
    intro_scene = next(s for s in srcs if s.get("name") == "Intro" and s.get("id") == "scene")
    thumbnail   = next(s for s in srcs if s.get("name") == "Thumbnail")
    hud_browser = next(s for s in srcs if s.get("id") == "browser_source"
                       and "8088/hud" in s.get("settings", {}).get("url", ""))
    intro_video = next(s for s in srcs if s.get("name") == "Intro Video")

    # --- 1. Image source: full-screen background graphic ---
    img_src = copy.deepcopy(thumbnail)
    img_src["name"]     = SCENE_NAME
    img_src["uuid"]     = IMAGE_UUID
    img_src["settings"] = {"file": IMAGE_FILE}
    srcs.append(img_src)

    # --- 2. Browser source: transparent chat overlay (1920x1080) ---
    chat_src = copy.deepcopy(hud_browser)
    chat_src["name"] = CHAT_SOURCE
    chat_src["uuid"] = CHAT_UUID
    chat_src["settings"] = {
        "url":                CHAT_URL,
        "width":              1920,
        "height":             1080,
        "restart_when_active": True,
    }
    srcs.append(chat_src)

    # --- 3. Music source: looping audio track ---
    orig_s = intro_video.get("settings", {})
    music_src = copy.deepcopy(intro_video)
    music_src["name"] = MUSIC_SOURCE
    music_src["uuid"] = MUSIC_UUID
    music_src["settings"] = {
        "file":                orig_s.get("file", MUSIC_FILE),   # path key
        "looping":             orig_s.get("looping", True),
        "restart_on_activate": orig_s.get("restart_on_activate", True),
        "close_when_inactive": orig_s.get("close_when_inactive", True),
    }
    music_src["settings"]["file"] = MUSIC_FILE   # always override to the mp3 path
    srcs.append(music_src)

    # --- 4. Scene: deep-copy Intro skeleton, replace items ---
    scene = copy.deepcopy(intro_scene)
    scene["name"] = SCENE_NAME
    scene["uuid"] = SCENE_UUID

    item_tmpl = copy.deepcopy(intro_scene["settings"]["items"][0])

    def _item(name, uuid, item_id):
        it = copy.deepcopy(item_tmpl)
        it["name"]        = name
        it["source_uuid"] = uuid
        it["visible"]     = True
        it["locked"]      = True
        it["id"]          = item_id
        it["pos"]         = {"x": 0.0, "y": 0.0}
        it["scale"]       = {"x": 1.0, "y": 1.0}
        it["bounds_type"] = 2                        # OBS_BOUNDS_SCALE_INNER = "fit"
        it["bounds"]      = {"x": 1920.0, "y": 1080.0}
        return it

    # Bottom-to-top layer order: image, chat overlay, music (audio-only)
    items = [
        _item(SCENE_NAME,   IMAGE_UUID, 1),
        _item(CHAT_SOURCE,  CHAT_UUID,  2),
        _item(MUSIC_SOURCE, MUSIC_UUID, 3),
    ]
    scene["settings"]["items"]      = items
    scene["settings"]["id_counter"] = 4

    # Hotkeys keyed by scene item id
    scene["hotkeys"] = {"OBSBasic.SelectScene": []}
    for iid in [1, 2, 3]:
        scene["hotkeys"][f"libobs.show_scene_item.{iid}"] = []
        scene["hotkeys"][f"libobs.hide_scene_item.{iid}"] = []

    srcs.append(scene)

    # --- 5. Register in OBS scene list ---
    if "scene_order" in d:
        d["scene_order"].append({"name": SCENE_NAME})

    return True


def main(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if not add_intermission_scene(d):
        print(f"{path}: '{SCENE_NAME}' already present — skip")
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
    print(f"{path}: added '{SCENE_NAME}' scene "
          f"(background graphic + transparent chat overlay + looping music)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: add_intermission_scene.py <collection.json>")
    main(sys.argv[1])
