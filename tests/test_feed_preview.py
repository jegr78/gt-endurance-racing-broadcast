#!/usr/bin/env python3
"""Stdlib unit checks for the Director Panel live preview. Run: python3 tests/test_feed_preview.py"""
import importlib.util, os, time

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


def t_split_mjpeg_frames_extracts_complete_jpegs():
    soi, eoi = b"\xff\xd8", b"\xff\xd9"
    a = soi + b"AAAA" + eoi
    b = soi + b"BBBB" + eoi
    frames, rem = m.split_mjpeg_frames(b"\x00\x00" + a + b + soi + b"CC")
    assert frames == [a, b]
    assert rem == soi + b"CC"          # incomplete trailing frame is kept


def t_split_mjpeg_frames_no_complete_frame():
    frames, rem = m.split_mjpeg_frames(b"\xff\xd8partial")
    assert frames == []
    assert rem == b"\xff\xd8partial"


def t_parse_ebur128_momentary():
    line = "[Parsed_ebur128_1 @ 0x55] t: 3   TARGET:-23 LUFS    M: -20.1 S: -22.0 ..."
    assert abs(m.parse_ebur128_momentary(line) - (-20.1)) < 1e-6
    assert m.parse_ebur128_momentary("frame= 10 fps=1.0") is None
    assert m.parse_ebur128_momentary("[Parsed_ebur128_1] M: -inf S: -inf") is None


def t_lufs_to_meter_maps_range():
    assert m.lufs_to_meter(None) == 0.0
    assert m.lufs_to_meter(-60.0) == 0.0          # at/below floor
    assert m.lufs_to_meter(-10.0) == 1.0          # at/above ceiling
    mid = m.lufs_to_meter(-35.0)                   # halfway (-60..-10)
    assert 0.49 < mid < 0.51




class _FakeProc:
    def __init__(self): self._alive = True
    def poll(self): return None if self._alive else 0
    def kill(self): self._alive = False
    def wait(self, timeout=None): self._alive = False


def _quiet_log():
    import logging
    lg = logging.getLogger("test.preview"); lg.addHandler(logging.NullHandler()); return lg


def _wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred(): return
        time.sleep(0.02)


def t_preview_pull_worker_collects_frame_and_level():
    soi, eoi = b"\xff\xd8", b"\xff\xd9"
    frame = soi + b"IMG" + eoi
    proc = _FakeProc()

    def fake_spawn(worker):
        # video: one complete JPEG then EOF; stderr: one ebur128 line then EOF
        video = [frame, b""]
        def vread(n=65536):
            return video.pop(0) if video else b""
        class _V:  # minimal read() interface
            read = staticmethod(vread)
        stderr = iter(["[Parsed_ebur128_1] M: -20.0 S: -22.0\n"])
        return proc, _V(), stderr

    w = m._PreviewPullWorker("B", "https://twitch.tv/x", None,
                             _quiet_log(), spawn=fake_spawn)
    w.start()
    _wait(lambda: w.latest_frame() == frame, 2.0)
    assert w.latest_frame() == frame
    _wait(lambda: w.latest_level() > 0.0, 2.0)
    assert 0.0 < w.latest_level() <= 1.0
    w.stop()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
