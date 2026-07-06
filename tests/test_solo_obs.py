#!/usr/bin/env python3
"""Stdlib checks for solo OBS templates + device localization (#303).
Run: python3 tests/test_solo_obs.py"""
import importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sa = _load("setup_assets", "src", "setup-assets.py")


def t_resolve_template_base():
    assert sa.resolve_template_base("endurance", "") == "GT_Endurance"
    assert sa.resolve_template_base("solo", "commentary") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("solo", "pov") == "GT_Solo_POV"
    assert sa.resolve_template_base("solo", "") == "GT_Solo_Commentary"      # default
    assert sa.resolve_template_base("solo", "nonsense") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("", "") == "GT_Endurance"                 # default kind


def _device_coll():
    return {"sources": [
        {"name": "Solo Capture", "uuid": "cap-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_CAPTURE__"}},
        {"name": "Solo Webcam", "uuid": "cam-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_WEBCAM__"}},
        {"name": "Overlay", "uuid": "ov", "id": "image_source", "settings": {}},
    ]}


def _byname(c, n):
    return next(s for s in c["sources"] if s["name"] == n)


def t_device_localize_windows():
    c = _device_coll()
    unset = sa.localize_device_sources(
        c, "win32", {"RACECAST_CAPTURE": "Cam:\\\\?\\usb#abc", "RACECAST_WEBCAM": "Logi:\\\\?\\usb#xyz"})
    cap = _byname(c, "Solo Capture")
    assert cap["id"] == cap["versioned_id"] == "dshow_input"
    assert cap["settings"] == {"video_device_id": "Cam:\\\\?\\usb#abc"}
    assert _byname(c, "Solo Webcam")["settings"] == {"video_device_id": "Logi:\\\\?\\usb#xyz"}
    assert unset == []


def t_device_localize_linux_and_darwin_keys():
    c = _device_coll()
    sa.localize_device_sources(c, "linux", {"RACECAST_CAPTURE": "/dev/video0",
                                            "RACECAST_WEBCAM": "/dev/video1"})
    assert _byname(c, "Solo Capture")["id"] == "v4l2_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device_id": "/dev/video0"}
    c = _device_coll()
    sa.localize_device_sources(c, "darwin", {"RACECAST_CAPTURE": "AAAA", "RACECAST_WEBCAM": "BBBB"})
    assert _byname(c, "Solo Capture")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device": "AAAA"}


def t_device_localize_empty_env_warns_not_raises():
    c = _device_coll()
    unset = sa.localize_device_sources(c, "darwin", {})   # no device values
    assert sorted(unset) == ["Solo Capture", "Solo Webcam"]
    # source type still localized; device key present but empty (OBS shows black)
    assert _byname(c, "Solo Capture")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture")["settings"] == {"device": ""}


def t_device_localize_absent_sources_is_noop():
    c = {"sources": [{"name": "Overlay", "id": "image_source", "settings": {}}]}
    assert sa.localize_device_sources(c, "win32", {}) == []   # endurance: untouched


def t_device_localize_unknown_platform_all_unset_even_with_values():
    c = _device_coll()
    unset = sa.localize_device_sources(c, "sunos5",
                                       {"RACECAST_CAPTURE": "X", "RACECAST_WEBCAM": "Y"})
    assert sorted(unset) == ["Solo Capture", "Solo Webcam"]
    # unknown platform: source left untouched (still the macOS template form + token)
    assert _byname(c, "Solo Capture")["settings"] == {"device": "__RACECAST_CAPTURE__"}


def t_device_localize_env_none_is_safe():
    c = _device_coll()
    assert sorted(sa.localize_device_sources(c, "darwin", None)) == ["Solo Capture", "Solo Webcam"]


# --- Structural checks on the two committed solo templates (#303) ---

SOLO_FILES = ("GT_Solo_Commentary.json", "GT_Solo_POV.json")


def _load_solo(fn):
    with open(os.path.join(ROOT, "src", "obs", fn), encoding="utf-8") as fh:
        return json.load(fh)


def t_solo_templates_exist_and_have_expected_scenes():
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        names = {s.get("name") for s in d["sources"] if s.get("id") == "scene"}
        assert {"Program", "Solo Capture", "Solo Webcam"} <= names, (fn, names)
        assert {"Standby", "Intro", "Outro", "Discord", "Intermission", "Interview"} <= names, fn
        assert "Stint" not in names and "Splitscreen" not in names, fn


def t_solo_templates_keep_pov_drop_ab_feeds():
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        src_names = {s.get("name") for s in d["sources"]}
        assert "Feed POV" in src_names, fn
        assert "Feed A" not in src_names and "Feed B" not in src_names, fn


def t_solo_templates_are_tokenized_no_real_devices():
    for fn in SOLO_FILES:
        with open(os.path.join(ROOT, "src", "obs", fn), encoding="utf-8") as fh:
            raw = fh.read()
        assert "__RACECAST_CAPTURE__" in raw and "__RACECAST_WEBCAM__" in raw, fn
        assert "__RACECAST_GRAPHICS__" in raw and "__RACECAST_MEDIA__" in raw, fn
        assert "/dev/video" not in raw and "usb#" not in raw.lower(), fn


def t_program_scene_references_device_scenes_and_pov():
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        prog = next(s for s in d["sources"]
                    if s.get("id") == "scene" and s.get("name") == "Program")
        item_names = {it.get("name") for it in prog["settings"]["items"]}
        assert {"Solo Capture", "Solo Webcam", "Feed POV", "HUD Overlay"} <= item_names, (fn, item_names)


def t_solo_templates_scene_and_source_references_resolve():
    """Every scene item's source_uuid resolves to a real source, and scene_order /
    current_scene name real scenes — the importability integrity the committed file
    must guarantee (OBS resolves references by uuid)."""
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        uuids = {s.get("uuid") for s in d["sources"]}
        uuids |= {g.get("uuid") for g in d.get("groups", [])}
        scene_names = {s.get("name") for s in d["sources"] if s.get("id") == "scene"}
        for s in d["sources"]:
            if s.get("id") != "scene":
                continue
            for it in s["settings"]["items"]:
                assert it["source_uuid"] in uuids, (fn, s["name"], it.get("name"))
        for entry in d["scene_order"]:
            assert entry["name"] in scene_names, (fn, entry)
        assert d["current_scene"] in scene_names, fn
        assert d["current_program_scene"] in scene_names, fn


def t_localize_preserves_solo_scenes():
    """setup-assets.localize_device_sources must localize the two device LEAF sources
    (id/settings -> per-OS device) while leaving the same-named wrapping SCENES intact
    (still id=='scene' with their items). Locks the ordering contract in
    tools/derive-solo-templates.py (leaf after scene so the by_name lookup wins)."""
    d = _load_solo("GT_Solo_Commentary.json")
    unset = sa.localize_device_sources(
        d, "darwin", {"RACECAST_CAPTURE": "CAPDEV", "RACECAST_WEBCAM": "CAMDEV"})
    assert unset == []
    # The wrapping scenes survive as scenes with their single wrapped item.
    for scene_name in ("Solo Capture", "Solo Webcam"):
        sc = next(s for s in d["sources"]
                  if s.get("name") == scene_name and s.get("id") == "scene")
        assert len(sc["settings"]["items"]) == 1, scene_name
    # The device leaves are localized to the real device values (tokens gone).
    devs = {s["uuid"]: s for s in d["sources"]
            if s.get("id") == "av_capture_input"}
    assert {s["settings"]["device"] for s in devs.values()} == {"CAPDEV", "CAMDEV"}
    for s in devs.values():
        assert "__RACECAST_" not in s["settings"]["device"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
