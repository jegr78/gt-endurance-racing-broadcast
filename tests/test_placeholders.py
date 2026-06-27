#!/usr/bin/env python3
"""Stdlib unit checks for the neutral asset-placeholder helper + bundled assets.
Run: python3 tests/test_placeholders.py"""
import os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLACEHOLDERS = os.path.join(ROOT, "src", "assets", "placeholders")
PNG = os.path.join(PLACEHOLDERS, "transparent-1080p.png")
MP4 = os.path.join(PLACEHOLDERS, "neutral-5s-1080p.mp4")


def t_bundled_graphic_is_1080p_rgba_png():
    assert os.path.isfile(PNG), "bundled transparent PNG missing"
    with open(PNG, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    # IHDR is the first chunk: 8-byte sig, 4-byte len, 4-byte 'IHDR', then payload.
    w, h, depth, color = struct.unpack(">IIBB", data[16:26])
    assert (w, h) == (1920, 1080), f"wrong size {(w, h)}"
    assert depth == 8 and color == 6, f"expected 8-bit RGBA, got depth={depth} color={color}"


def t_bundled_media_clip_is_a_small_mp4():
    assert os.path.isfile(MP4), "bundled neutral clip missing"
    with open(MP4, "rb") as fh:
        head = fh.read(12)
    assert head[4:8] == b"ftyp", "not an MP4 (no ftyp box)"
    assert os.path.getsize(MP4) < 2 * 1024 * 1024, "clip unexpectedly large (>2 MB)"


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
