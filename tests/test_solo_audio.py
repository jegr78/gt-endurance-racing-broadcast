#!/usr/bin/env python3
"""Solo collections' audio-monitoring config (game/Discord/media audible + streamed).
Run: python3 tests/test_solo_audio.py"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLS = ("src/obs/GT_Racing_Solo_POV.json", "src/obs/GT_Racing_Solo_Commentary.json")
MON_AND_OUT = 2


def _by_name(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        d = json.load(fh)
    return {s.get("name"): s for s in d["sources"]}


def t_game_and_discord_and_media_monitor_and_output():
    for path in COLLS:
        n = _by_name(path)
        cap = n["Solo Capture Device"]
        assert cap.get("muted") is False, path
        assert cap.get("monitoring_type") == MON_AND_OUT, path
        assert n["Discord Audio Capture"].get("monitoring_type") == MON_AND_OUT, path
        for media in ("Intro Video", "Outro Video", "Intermission Music"):
            assert n[media].get("monitoring_type") == MON_AND_OUT, (path, media)


def t_mic_unchanged_and_tyres_muted():
    for path in COLLS:
        n = _by_name(path)
        mic = n["Commentary Mic Device"]
        assert mic.get("monitoring_type") in (0, None), path      # no self-monitor
        assert mic.get("muted") is False, path                    # but output on
    tyres = _by_name("src/obs/GT_Racing_Solo_Commentary.json").get("Solo Tyres Capture Device")
    assert tyres is not None and tyres.get("muted") is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
