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
        {"name": "Solo Capture Device", "uuid": "cap-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_CAPTURE__"}},
        {"name": "Solo Webcam Device", "uuid": "cam-uuid", "id": "av_capture_input",
         "versioned_id": "av_capture_input", "settings": {"device": "__RACECAST_WEBCAM__"}},
        {"name": "Overlay", "uuid": "ov", "id": "image_source", "settings": {}},
    ]}


def _byname(c, n):
    return next(s for s in c["sources"] if s["name"] == n)


def t_device_localize_windows():
    c = _device_coll()
    unset = sa.localize_device_sources(
        c, "win32", {"RACECAST_CAPTURE": "Cam:\\\\?\\usb#abc", "RACECAST_WEBCAM": "Logi:\\\\?\\usb#xyz"})
    cap = _byname(c, "Solo Capture Device")
    assert cap["id"] == cap["versioned_id"] == "dshow_input"
    assert cap["settings"] == {"video_device_id": "Cam:\\\\?\\usb#abc"}
    assert _byname(c, "Solo Webcam Device")["settings"] == {"video_device_id": "Logi:\\\\?\\usb#xyz"}
    assert unset == []


def t_device_localize_linux_and_darwin_keys():
    c = _device_coll()
    sa.localize_device_sources(c, "linux", {"RACECAST_CAPTURE": "/dev/video0",
                                            "RACECAST_WEBCAM": "/dev/video1"})
    assert _byname(c, "Solo Capture Device")["id"] == "v4l2_input"
    assert _byname(c, "Solo Capture Device")["settings"] == {"device_id": "/dev/video0"}
    c = _device_coll()
    sa.localize_device_sources(c, "darwin", {"RACECAST_CAPTURE": "AAAA", "RACECAST_WEBCAM": "BBBB"})
    assert _byname(c, "Solo Capture Device")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture Device")["settings"] == {"device": "AAAA"}


def t_device_localize_empty_env_warns_not_raises():
    c = _device_coll()
    unset = sa.localize_device_sources(c, "darwin", {})   # no device values
    assert sorted(unset) == ["Solo Capture Device", "Solo Webcam Device"]
    # source type still localized; device key present but empty (OBS shows black)
    assert _byname(c, "Solo Capture Device")["id"] == "av_capture_input"
    assert _byname(c, "Solo Capture Device")["settings"] == {"device": ""}


def t_device_localize_absent_sources_is_noop():
    c = {"sources": [{"name": "Overlay", "id": "image_source", "settings": {}}]}
    assert sa.localize_device_sources(c, "win32", {}) == []   # endurance: untouched


def t_device_localize_unknown_platform_all_unset_even_with_values():
    c = _device_coll()
    unset = sa.localize_device_sources(c, "sunos5",
                                       {"RACECAST_CAPTURE": "X", "RACECAST_WEBCAM": "Y"})
    assert sorted(unset) == ["Solo Capture Device", "Solo Webcam Device"]
    # unknown platform: source left untouched (still the macOS template form + token)
    assert _byname(c, "Solo Capture Device")["settings"] == {"device": "__RACECAST_CAPTURE__"}


def t_device_localize_env_none_is_safe():
    c = _device_coll()
    assert sorted(sa.localize_device_sources(c, "darwin", None)) == ["Solo Capture Device", "Solo Webcam Device"]


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
    """setup-assets.localize_device_sources must localize the device LEAF sources
    (id/settings -> per-OS device) while leaving the distinctly-named wrapping SCENES
    intact (still id=='scene' with their items). Scene and leaf are named distinctly
    ("Solo Capture" scene vs "Solo Capture Device" leaf, mirroring the Discord
    precedent), so the by-name lookup in localize_device_sources can never collide
    them — no ordering contract required. Covers the video (capture/webcam) AND
    audio (commentary mic, #307) device leaves."""
    d = _load_solo("GT_Solo_Commentary.json")
    unset = sa.localize_device_sources(
        d, "darwin", {"RACECAST_CAPTURE": "CAPDEV", "RACECAST_WEBCAM": "CAMDEV",
                     "RACECAST_MIC": "MICDEV"})
    assert unset == []
    # The wrapping scenes survive as scenes with their single wrapped item.
    for scene_name in ("Solo Capture", "Solo Webcam", "Commentary Mic"):
        sc = next(s for s in d["sources"]
                  if s.get("name") == scene_name and s.get("id") == "scene")
        assert len(sc["settings"]["items"]) == 1, scene_name
    # The video device leaves are localized to the real device values (tokens gone).
    devs = {s["uuid"]: s for s in d["sources"]
            if s.get("id") == "av_capture_input"}
    assert {s["settings"]["device"] for s in devs.values()} == {"CAPDEV", "CAMDEV"}
    for s in devs.values():
        assert "__RACECAST_" not in s["settings"]["device"]
    # The mic (audio) device leaf is localized to its per-OS coreaudio form.
    mic = _byname(d, "Commentary Mic Device")
    assert mic["id"] == mic["versioned_id"] == "coreaudio_input_capture"
    assert mic["settings"] == {"device_id": "MICDEV"}


def t_solo_templates_device_leaves_are_distinctly_named():
    """The device LEAF sources are named distinctly from their wrapping scenes
    ("Solo Capture Device" / "Solo Webcam Device"), carry id=='av_capture_input'
    (the committed macOS form) and their respective tokens."""
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        cap = _byname(d, "Solo Capture Device")
        cam = _byname(d, "Solo Webcam Device")
        assert cap["id"] == "av_capture_input", fn
        assert cam["id"] == "av_capture_input", fn
        assert cap["settings"]["device"] == "__RACECAST_CAPTURE__", fn
        assert cam["settings"]["device"] == "__RACECAST_WEBCAM__", fn


def t_solo_templates_have_own_name_and_no_splitscreen_leftovers():
    """#304: the derived collections carry their own display name (not the inherited
    endurance one -- setup-assets overrides it at localize time, but the committed
    artifact should already be self-consistent) and no orphaned Splitscreen-only
    leftovers (the Splitscreen scene itself was already dropped in #303, but the
    derive script only pruned `sources`, leaving the `Split HUD` group and the
    `Splitscreen Labels` leaf source behind)."""
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        assert d["name"] == "GT Racing Solo", fn
        src_names = {s.get("name") for s in d["sources"]}
        assert "Splitscreen Labels" not in src_names, fn
        group_names = {g.get("name") for g in d.get("groups", [])}
        assert "Split HUD" not in group_names, fn


def t_solo_templates_no_scene_source_name_collision():
    """Collision guard: no source `name` is shared between a scene and a non-scene
    source. "Solo Capture"/"Solo Webcam" must each resolve to exactly one scene, and
    the device leaves ("Solo Capture Device"/"Solo Webcam Device") must not collide
    with any scene name — the bug this fix removes."""
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        scene_names = [s.get("name") for s in d["sources"] if s.get("id") == "scene"]
        non_scene_names = [s.get("name") for s in d["sources"] if s.get("id") != "scene"]
        assert scene_names.count("Solo Capture") == 1, fn
        assert scene_names.count("Solo Webcam") == 1, fn
        assert set(scene_names) & set(non_scene_names) == set(), (fn, scene_names, non_scene_names)


def t_solo_templates_have_commentary_mic_scene():
    """#307: both solo templates carry a "Commentary Mic" scene wrapping the
    distinctly-named "Commentary Mic Device" leaf (macOS coreaudio_input_capture
    form, tokenized __RACECAST_MIC__), included as a nested-scene item in exactly
    Program/Interview/Standby/Intermission/Discord — never Intro/Outro."""
    for fn in SOLO_FILES:
        d = _load_solo(fn)
        by = _byname_map(d)
        mic_scene = by.get("Commentary Mic")
        assert mic_scene is not None and mic_scene.get("id") == "scene", fn
        mic_items = mic_scene["settings"]["items"]
        assert len(mic_items) == 1 and mic_items[0]["name"] == "Commentary Mic Device", fn
        mic_dev = by.get("Commentary Mic Device")
        assert mic_dev is not None, fn
        assert mic_dev["id"] == mic_dev["versioned_id"] == "coreaudio_input_capture", fn
        assert mic_dev["settings"] == {"device_id": "__RACECAST_MIC__"}, fn

        referencing = set()
        for s in d["sources"]:
            if s.get("id") != "scene":
                continue
            for it in s["settings"]["items"]:
                if it.get("name") == "Commentary Mic":
                    referencing.add(s["name"])
        assert referencing == {"Program", "Interview", "Standby", "Intermission", "Discord"}, \
            (fn, referencing)
        assert "Commentary Mic" in [e["name"] for e in d["scene_order"]], fn


def t_solo_templates_regeneration_is_deterministic():
    """Running the derive script twice must yield byte-identical output — the
    #303/#307 no-uuid4()/no-timestamp determinism contract."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "derive_solo_templates", os.path.join(ROOT, "tools", "derive-solo-templates.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    first = json.dumps(mod.derive(), sort_keys=True)
    second = json.dumps(mod.derive(), sort_keys=True)
    assert first == second


def _byname_map(d):
    return {s.get("name"): s for s in d["sources"]}


# --- #307: audio (mic) device localization ---

def _mic_coll():
    return {"sources": [
        {"name": "Commentary Mic Device", "uuid": "mic-uuid", "id": "coreaudio_input_capture",
         "versioned_id": "coreaudio_input_capture", "settings": {"device_id": "__RACECAST_MIC__"}},
        {"name": "Overlay", "uuid": "ov", "id": "image_source", "settings": {}},
    ]}


def t_mic_localize_windows():
    c = _mic_coll()
    unset = sa.localize_device_sources(c, "win32", {"RACECAST_MIC": "MIC-ID"})
    mic = _byname(c, "Commentary Mic Device")
    assert mic["id"] == mic["versioned_id"] == "wasapi_input_capture"
    assert mic["settings"] == {"device_id": "MIC-ID"}
    assert unset == []


def t_mic_localize_darwin_and_linux():
    c = _mic_coll()
    sa.localize_device_sources(c, "darwin", {"RACECAST_MIC": "MICDEV"})
    mic = _byname(c, "Commentary Mic Device")
    assert mic["id"] == mic["versioned_id"] == "coreaudio_input_capture"
    assert mic["settings"] == {"device_id": "MICDEV"}

    c = _mic_coll()
    sa.localize_device_sources(c, "linux", {"RACECAST_MIC": "/dev/whatever"})
    mic = _byname(c, "Commentary Mic Device")
    assert mic["id"] == mic["versioned_id"] == "pulse_input_capture"
    assert mic["settings"] == {"device_id": "/dev/whatever"}


def t_mic_localize_empty_env_warns_not_raises():
    c = _mic_coll()
    unset = sa.localize_device_sources(c, "darwin", {})
    assert unset == ["Commentary Mic Device"]
    assert _byname(c, "Commentary Mic Device")["settings"] == {"device_id": ""}


def t_audio_variants_cross_check_obs_ws_audio_property():
    """AUDIO_VARIANTS' settings-key must agree with obs_ws's audio device property
    name on every platform — enumeration writes into the same field localization
    later reads (mirrors the existing video DEVICE_VARIANTS cross-check)."""
    obs_ws = _load("obs_ws", "src", "scripts", "obs_ws.py")
    for platform, (_src_id, key) in sa.AUDIO_VARIANTS.items():
        assert key == obs_ws.device_property_name(platform, kind="audio") == "device_id", platform


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
