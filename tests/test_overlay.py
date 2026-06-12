#!/usr/bin/env python3
"""Stdlib unit checks for the per-profile overlay CSS/font helpers.
Run: python3 tests/test_overlay.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "feeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
feeds = importlib.util.module_from_spec(spec); spec.loader.exec_module(feeds)


def _mkoverlay(tmp, hud_css=None, timer_css=None, fonts=None):
    od = os.path.join(tmp, "overlay")
    os.makedirs(os.path.join(od, "fonts"), exist_ok=True)
    if hud_css is not None:
        with open(os.path.join(od, "hud.css"), "w", encoding="utf-8") as f: f.write(hud_css)
    if timer_css is not None:
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as f: f.write(timer_css)
    for name, data in (fonts or {}).items():
        with open(os.path.join(od, "fonts", name), "wb") as f: f.write(data)
    return od

def t_read_overlay_css_present():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, hud_css="#stint{left:10px}")
        assert feeds.read_overlay_css(od, "hud") == b"#stint{left:10px}"

def t_read_overlay_css_timer_present():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, timer_css="#clock{font-size:300px}")
        assert feeds.read_overlay_css(od, "timer") == b"#clock{font-size:300px}"

def t_read_overlay_css_absent_is_empty():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)  # no hud.css
        assert feeds.read_overlay_css(od, "hud") == b""

def t_read_overlay_css_no_dir_is_empty():
    assert feeds.read_overlay_css(None, "hud") == b""
    assert feeds.read_overlay_css("", "timer") == b""

def t_read_overlay_css_rejects_unknown_page():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, hud_css="x")
        assert feeds.read_overlay_css(od, "../hud") == b""
        assert feeds.read_overlay_css(od, "panel") == b""

def t_resolve_overlay_font_ok():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, fonts={"Title.woff2": b"OTTO"})
        hit = feeds.resolve_overlay_font(od, "Title.woff2")
        assert hit and hit[1] == "font/woff2"
        assert os.path.basename(hit[0]) == "Title.woff2"

def t_font_ctypes_out_is_identity_whitelist():
    # The handler re-derives the Content-Type header from this constant map
    # (defense vs. header injection, mirroring ASSET_CTYPES), so every ctype
    # resolve_overlay_font can return must map back to itself — otherwise a valid
    # font would 404 — and any unknown value must drop to None.
    for ctype in feeds.FONT_CTYPES.values():
        assert feeds.FONT_CTYPES_OUT.get(ctype) == ctype
    assert feeds.FONT_CTYPES_OUT.get("text/html; charset=utf-8") is None


def t_resolve_overlay_font_rejects_traversal_and_bad_ext():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, fonts={"ok.ttf": b"x"})
        assert feeds.resolve_overlay_font(od, "../../etc/passwd") is None
        assert feeds.resolve_overlay_font(od, "ok.exe") is None
        assert feeds.resolve_overlay_font(od, "nope.woff2") is None
        assert feeds.resolve_overlay_font(None, "ok.ttf") is None
        assert feeds.resolve_overlay_font(od, ".woff2") is None


# --- resolve_preview_bg: per-profile HUD-preview backdrop (overlay/preview-bg.*) ---
def t_resolve_preview_bg_present_jpg():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)
        with open(os.path.join(od, "preview-bg.jpg"), "wb") as f: f.write(b"\xff\xd8\xff")
        hit = feeds.resolve_preview_bg(od)
        assert hit is not None and hit[0].endswith("preview-bg.jpg") and hit[1] == "image/jpeg"


def t_resolve_preview_bg_ext_precedence_jpg_over_png():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)
        with open(os.path.join(od, "preview-bg.png"), "wb") as f: f.write(b"\x89PNG")
        with open(os.path.join(od, "preview-bg.jpg"), "wb") as f: f.write(b"\xff\xd8\xff")
        assert feeds.resolve_preview_bg(od)[1] == "image/jpeg"   # jpg first in PREVIEW_BG_EXTS


def t_resolve_preview_bg_png_when_only_png():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)
        with open(os.path.join(od, "preview-bg.png"), "wb") as f: f.write(b"\x89PNG")
        assert feeds.resolve_preview_bg(od)[1] == "image/png"


def t_resolve_preview_bg_absent_or_no_dir_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert feeds.resolve_preview_bg(_mkoverlay(tmp)) is None   # no per-profile, no assets
    assert feeds.resolve_preview_bg(None) is None


def t_resolve_preview_bg_falls_back_to_shared_default():
    # No per-profile override -> the shipped shared default in assets/ is used.
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)                      # no preview-bg here
        assets = os.path.join(tmp, "assets"); os.makedirs(assets)
        with open(os.path.join(assets, "preview-bg.jpg"), "wb") as f: f.write(b"\xff\xd8\xff")
        hit = feeds.resolve_preview_bg(od, assets)
        assert hit is not None and hit[0].endswith(os.path.join("assets", "preview-bg.jpg"))


def t_resolve_preview_bg_profile_overrides_shared_default():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)
        with open(os.path.join(od, "preview-bg.png"), "wb") as f: f.write(b"\x89PNG")
        assets = os.path.join(tmp, "assets"); os.makedirs(assets)
        with open(os.path.join(assets, "preview-bg.jpg"), "wb") as f: f.write(b"\xff\xd8\xff")
        # per-profile (overlay_dir) wins over the shared default
        assert feeds.resolve_preview_bg(od, assets)[0].endswith(os.path.join("overlay", "preview-bg.png"))


def t_resolve_preview_bg_shared_default_only_when_no_overlay_dir():
    with tempfile.TemporaryDirectory() as tmp:
        assets = os.path.join(tmp, "assets"); os.makedirs(assets)
        with open(os.path.join(assets, "preview-bg.jpg"), "wb") as f: f.write(b"\xff\xd8\xff")
        assert feeds.resolve_preview_bg(None, assets)[1] == "image/jpeg"


def t_resolve_preview_bg_ctypes_are_asset_whitelisted():
    # The handler re-derives the header via ASSET_CTYPES[hit[1]] — every ctype the
    # resolver can return must be a key there (else a KeyError at request time).
    for _ext, ctype in feeds.PREVIEW_BG_EXTS:
        assert ctype in feeds.ASSET_CTYPES


# --- resolve_preview_frame: the Overlay.png broadcast frame from runtime graphics ---
def t_resolve_preview_frame_present():
    with tempfile.TemporaryDirectory() as tmp:
        g = os.path.join(tmp, "graphics"); os.makedirs(g)
        with open(os.path.join(g, "Overlay.png"), "wb") as f: f.write(b"\x89PNG")
        hit = feeds.resolve_preview_frame(g)
        assert hit is not None and hit[1] == "image/png" and "image/png" in feeds.ASSET_CTYPES


def t_resolve_preview_frame_absent_or_no_dir_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert feeds.resolve_preview_frame(os.path.join(tmp, "graphics")) is None
    assert feeds.resolve_preview_frame(None) is None


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
