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


# --- program_audio_ffmpeg_cmd: audio-only MP3 to stdout, params from consts ---
def t_program_audio_ffmpeg_cmd_shape():
    cmd = m.program_audio_ffmpeg_cmd()
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd                       # no video
    assert cmd[cmd.index("-map") + 1] == "0:a:0?"   # optional audio stream
    assert cmd[cmd.index("-ar") + 1] == m.PROGRAM_AUDIO_SAMPLE_RATE
    assert cmd[cmd.index("-ac") + 1] == m.PROGRAM_AUDIO_CHANNELS
    assert cmd[cmd.index("-c:a") + 1] == m.PROGRAM_AUDIO_CODEC
    assert cmd[cmd.index("-b:a") + 1] == m.PROGRAM_AUDIO_BITRATE
    assert cmd[cmd.index("-f") + 1] == m.PROGRAM_AUDIO_FORMAT
    assert cmd[-1] == "pipe:1"                 # emit to stdout


def t_program_audio_defaults_are_mp3():
    assert m.PROGRAM_AUDIO_CODEC == "libmp3lame"
    assert m.PROGRAM_AUDIO_FORMAT == "mp3"
    assert m.PROGRAM_AUDIO_CONTENT_TYPE == "audio/mpeg"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
