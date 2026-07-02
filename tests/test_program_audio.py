#!/usr/bin/env python3
"""Stdlib unit checks for the on-air program-audio monitor (relay tap).
Run: python3 tests/test_program_audio.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- program_audio_enabled: default ON, explicit falsey token disables --------
def t_program_audio_default_on():
    assert m.program_audio_enabled({}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": ""}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": "1"}) is True
    assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": "on"}) is True


def t_program_audio_killswitch():
    for tok in ("0", "false", "no", "off", "OFF", " Off "):
        assert m.program_audio_enabled({"RACECAST_PROGRAM_AUDIO": tok}) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
