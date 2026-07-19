#!/usr/bin/env python3
"""Content checks for the Trailer control surfaces. Run: python3 tests/test_trailer.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def t_obs_collection_has_trailer_scene_and_source():
    cfg = json.loads(_read(os.path.join("src", "obs", "GT_Endurance.json")))
    names = {s.get("name") for s in cfg.get("sources", [])}
    assert "Trailer" in names, "no Trailer scene in the collection"
    assert "Trailer Video" in names, "no Trailer Video source"
    order = {e.get("name") for e in cfg.get("scene_order", [])}
    assert "Trailer" in order, "Trailer missing from scene_order"
    src = next(s for s in cfg["sources"] if s.get("name") == "Trailer Video")
    st = src.get("settings", {})
    assert st.get("local_file") == "__RACECAST_MEDIA__/trailer.mp4", st
    assert st.get("looping") is True and st.get("restart_on_activate") is True, st


def t_panel_has_trailer_macro():
    html = _read(os.path.join("src", "director", "director-panel.html"))
    i = html.index('{label:"TRAILER"')
    macro = html[i:html.index('}', i) + 1]
    assert 'scene:"Trailer"' in macro, macro
    # loop-clip-with-own-audio: mutes the feeds + Discord, like INTRO/OUTRO.
    for name in ("Feed A", "Feed B", "Discord Audio Capture"):
        assert name in macro, f"TRAILER macro must mute {name}"


# NOTE: the Companion button assertions (t_companion_has_trailer_button,
# t_companion_red_flag_still_present) are added to THIS file in Task 6, so every
# commit stays green — do not add them here in Task 5.


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
