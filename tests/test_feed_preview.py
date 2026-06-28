#!/usr/bin/env python3
"""Stdlib unit checks for the Director Panel live preview. Run: python3 tests/test_feed_preview.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_preview_pull_streamlink_cmd_twitch():
    cmd = m.preview_pull_streamlink_cmd("https://twitch.tv/foo", "twitch",
                                        m.PREVIEW_QUALITY_TW)
    assert cmd == ["streamlink", "--stdout", "--",
                   "https://twitch.tv/foo", m.PREVIEW_QUALITY_TW]


def t_preview_pull_streamlink_cmd_youtube_has_ua_and_cookies():
    cmd = m.preview_pull_streamlink_cmd("https://hls.example/360.m3u8", "youtube",
                                        m.PREVIEW_QUALITY_YT,
                                        cookies="/tmp/yt.txt", user_agent="UA/1")
    assert "--http-header" in cmd and "User-Agent=UA/1" in cmd
    assert "--http-cookies-file" in cmd and "/tmp/yt.txt" in cmd
    assert cmd[-2:] == ["https://hls.example/360.m3u8", m.PREVIEW_QUALITY_YT]
    assert cmd[0] == "streamlink" and "--stdout" in cmd


def t_preview_ffmpeg_cmd_pinned():
    assert m.preview_ffmpeg_cmd(480) == [
        "ffmpeg", "-nostdin", "-loglevel", "info", "-i", "pipe:0",
        "-map", "0:v:0", "-vf", "fps=1,scale=480:-2", "-f", "mjpeg", "pipe:1",
        "-map", "0:a:0?", "-af", "ebur128", "-f", "null", "-"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
