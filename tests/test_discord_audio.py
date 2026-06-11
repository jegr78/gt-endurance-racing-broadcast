#!/usr/bin/env python3
"""Stdlib checks for the platform-dependent Discord audio source transforms.
Run: python3 tests/test_discord_audio.py"""
import copy, importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sa = _load("setup_assets", "src", "setup-assets.py")
tk = _load("tokenize_obs", "tools", "tokenize-obs.py")

CANONICAL_SETTINGS = {"type": 1, "application": "com.hnc.Discord"}


def coll(src_id="sck_audio_capture", settings=None):
    return {"sources": [
        {"name": "Discord Audio Capture", "uuid": sa.DISCORD_AUDIO_UUID,
         "id": src_id, "versioned_id": src_id,
         "settings": dict(CANONICAL_SETTINGS if settings is None else settings)},
        {"name": "Feed A", "uuid": "feed-a", "id": "ffmpeg_source",
         "settings": {"input": "http://127.0.0.1:53001"}},
    ]}


def t_variant_per_platform():
    assert sa.discord_variant("darwin")[0] == "sck_audio_capture"
    assert sa.discord_variant("win32")[0] == "wasapi_process_output_capture"
    assert sa.discord_variant("linux")[0] == "pipewire_audio_application_capture"
    assert sa.discord_variant("sunos5") is None


def t_localize_windows_swaps_id_and_settings():
    c = coll()
    assert sa.localize_discord_audio(c, "win32") == "wasapi_process_output_capture"
    s = c["sources"][0]
    assert s["id"] == s["versioned_id"] == "wasapi_process_output_capture"
    assert s["settings"] == {"window": "Discord:Chrome_WidgetWin_1:Discord.exe",
                             "priority": 2}   # 2 = WINDOW_PRIORITY_EXE
    assert c["sources"][1]["settings"]["input"] == "http://127.0.0.1:53001"


def t_localize_linux_uses_pipewire_plugin():
    c = coll()
    assert sa.localize_discord_audio(c, "linux") == "pipewire_audio_application_capture"
    # "MatchPriorty" (sic) is the plugin's actual settings key; 0 = binary name.
    assert c["sources"][0]["settings"] == {"TargetName": "Discord", "MatchPriorty": 0}


def t_localize_idempotent_and_darwin_noop():
    c = coll()
    sa.localize_discord_audio(c, "win32")
    once = copy.deepcopy(c)
    sa.localize_discord_audio(c, "win32")
    assert c == once
    d = coll()
    sa.localize_discord_audio(d, "darwin")
    assert d["sources"][0]["id"] == "sck_audio_capture"
    assert d["sources"][0]["settings"] == CANONICAL_SETTINGS


def t_localize_missing_source_or_unknown_platform():
    c = {"sources": [{"name": "x", "uuid": "other", "id": "scene", "settings": {}}]}
    before = copy.deepcopy(c)
    assert sa.localize_discord_audio(c, "win32") is None
    assert c == before
    d = coll()
    before = copy.deepcopy(d)
    assert sa.localize_discord_audio(d, "sunos5") is None
    assert d == before


def t_tokenize_folds_any_variant_back():
    c = coll()
    sa.localize_discord_audio(c, "win32")
    assert tk.canonicalize_discord_audio(c) is True
    s = c["sources"][0]
    assert s["id"] == s["versioned_id"] == "sck_audio_capture"
    assert s["settings"] == CANONICAL_SETTINGS
    assert tk.canonicalize_discord_audio(c) is False   # canonical input: no-op


def t_committed_template_carries_the_source():
    # Guards against the uuid drifting when scenes are re-exported.
    path = os.path.join(ROOT, "src", "obs", "IRO_Endurance.json")
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    hits = [s for s in d.get("sources", []) if s.get("uuid") == sa.DISCORD_AUDIO_UUID]
    assert len(hits) == 1 and hits[0]["id"] == "sck_audio_capture"


def t_apply_collection_name_sets_top_level_name():
    c = {"name": "IRO Endurance", "sources": []}
    out = sa.apply_collection_name(c, "ERF Endurance")
    assert out["name"] == "ERF Endurance"


def t_apply_collection_name_noop_on_blank():
    c = {"name": "IRO Endurance", "sources": []}
    out = sa.apply_collection_name(c, "")
    assert out["name"] == "IRO Endurance"
    out2 = sa.apply_collection_name(c, None)
    assert out2["name"] == "IRO Endurance"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
