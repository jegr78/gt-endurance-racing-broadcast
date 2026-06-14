#!/usr/bin/env python3
"""Stdlib unit checks for the per-profile overlay CSS/font helpers.
Run: python3 tests/test_overlay.py"""
import importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "feeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
feeds = importlib.util.module_from_spec(spec); spec.loader.exec_module(feeds)

sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import overlay_build as ob


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


# --- overlay_build: the pure WYSIWYG compiler (issue #114) ---

def t_ob_font_constants_match_relay():
    # Duplicated from the relay and pinned identical (anti-drift, like the
    # load_dotenv copies). If the relay tightens the whitelist, this must follow.
    assert ob.FONT_NAME_RE.pattern == feeds.FONT_NAME_RE.pattern
    assert ob.FONT_CTYPES == feeds.FONT_CTYPES
    assert set(ob.FONT_EXTS) == set(feeds.FONT_CTYPES.keys())


def t_ob_extract_slots_from_real_hud():
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        slots = ob.extract_slots(f.read())
    ids = [s["id"] for s in slots]
    # Each team is three independent slots (logo / number / name; issue #136),
    # plus the POV placeholder box (issue #141) and the merged clock slot.
    assert ids == ["stint", "session", "streamer", "round-top", "round-flag",
                   "round-country",
                   "team1-logo", "team1-num", "team1-name",
                   "team2-logo", "team2-num", "team2-name",
                   "team3-logo", "team3-num", "team3-name",
                   "race-control", "pov", "clock"]
    by_id = {s["id"]: s for s in slots}
    assert by_id["stint"]["label"] == "Stint banner"
    # default props (no data-edit-props) include the text set, not the team-only keys
    assert "fontSize" in by_id["stint"]["props"]
    assert "teamNameMax" not in by_id["stint"]["props"]
    # team name slot: restricted set with the auto-fit bounds, no plain fontSize
    assert by_id["team1-name"]["props"] == ["left", "top", "width", "height",
                                            "teamNameMax", "teamNameMin",
                                            "fontFamily", "color"]
    # team number slot: badge text size/color/background, no auto-fit bounds
    assert by_id["team1-num"]["props"] == ["left", "top", "fontSize",
                                           "fontFamily", "color", "background"]
    # image slots (logo, flag): position/size only
    assert by_id["team1-logo"]["props"] == ["left", "top", "width", "height"]
    assert by_id["round-flag"]["props"] == ["left", "top", "width", "height"]
    # POV box: position/size + border/background props (issue #141)
    assert by_id["pov"]["props"] == ["left", "top", "width", "height",
                                     "background", "borderStyle",
                                     "borderColor", "borderWidth"]
    assert by_id["pov"]["label"] == "POV box"


def t_ob_hud_has_clock_slot():
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        slots = ob.extract_slots(f.read())
    ids = [s["id"] for s in slots]
    assert "clock" in ids
    clock = next(s for s in slots if s["id"] == "clock")
    assert clock["label"] == "Clock"
    assert "left" in clock["props"] and "fontSize" in clock["props"]

def t_ob_hud_clock_base_is_finite_positionable():
    # Regression for #135 carried into the merged page: the clock hugs its digits,
    # it is not a full-canvas centered box (dragging that moves nothing visibly).
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        style = ob.base_style(f.read())
    clock_rule = re.search(r"#clock\s*\{[^}]*\}", style).group(0)
    assert "1920px" not in clock_rule, "clock must not span the full canvas width"

def t_ob_hud_pov_has_border_props_and_obs_position():
    with open(os.path.join(ROOT, "src", "obs", "hud.html"), encoding="utf-8") as f:
        html = f.read()
    pov = next(s for s in ob.extract_slots(html) if s["id"] == "pov")
    for p in ("background", "borderStyle", "borderColor", "borderWidth"):
        assert p in pov["props"], p
    pov_rule = re.search(r"#pov\s*\{[^}]*\}", ob.base_style(html)).group(0)
    # aligned to the OBS Feed POV box (pos 1496,644 bounds 384x216)
    assert "1496px" in pov_rule and "644px" in pov_rule
    assert "384px" in pov_rule and "216px" in pov_rule


def t_ob_base_style_and_body():
    html = ('<head><style>#x{left:1px}</style></head>'
            '<body>\n  <div id="x" data-edit="X"></div>\n<script>1</script></body>')
    assert ob.base_style(html) == "#x{left:1px}"
    body = ob.base_body(html)
    assert '<div id="x"' in body and "<script>" not in body


SLOTS = [{"id": "stint", "label": "Stint banner", "props": list(ob.DEFAULT_PROPS)},
         {"id": "team0", "label": "Team 1",
          "props": ["left", "top", "width", "height", "teamNameMax",
                    "teamNameMin", "fontFamily", "color"]}]


def t_ob_compile_px_and_text_props():
    css = ob.compile_overlay_css(
        {"version": 1, "page": "hud",
         "slots": {"stint": {"left": 800, "top": 30, "fontSize": 44,
                             "color": "#fff"}}}, SLOTS)
    assert "#stint {" in css
    assert "left: 800px" in css and "top: 30px" in css
    assert "font-size: 44px" in css and "color: #fff" in css


def t_ob_compile_align_maps_to_flex():
    css = ob.compile_overlay_css(
        {"slots": {"stint": {"align": "center"}}}, SLOTS)
    assert "justify-content: center" in css
    css = ob.compile_overlay_css({"slots": {"stint": {"align": "right"}}}, SLOTS)
    assert "justify-content: flex-end" in css


def t_ob_compile_team_autofit_vars():
    css = ob.compile_overlay_css(
        {"slots": {"team0": {"teamNameMax": 34, "teamNameMin": 18}}}, SLOTS)
    assert "--team-name-max: 34px" in css and "--team-name-min: 18px" in css


def t_ob_compile_respects_allowed_props():
    # fontSize is not in team0's allowed set -> never emitted even if present
    css = ob.compile_overlay_css({"slots": {"team0": {"fontSize": 50}}}, SLOTS)
    assert "font-size" not in css


def t_ob_compile_unknown_slot_ignored():
    css = ob.compile_overlay_css({"slots": {"bogus": {"left": 1}}}, SLOTS)
    assert "bogus" not in css and css.strip() == ""


def t_ob_compile_empty_layout_is_empty():
    assert ob.compile_overlay_css(ob.empty_layout("hud"), SLOTS).strip() == ""


def t_ob_compile_fonts_emit_font_face():
    css = ob.compile_overlay_css(
        {"slots": {}, "fonts": ["League.woff2"]}, SLOTS)
    assert '@font-face' in css and 'font-family: "League"' in css
    assert 'url(/overlay/fonts/League.woff2)' in css


def t_ob_compile_rejects_bad_font_name():
    css = ob.compile_overlay_css(
        {"slots": {}, "fonts": ["../evil.woff2", "ok.exe", "Good.ttf"]}, SLOTS)
    assert "evil" not in css and "ok.exe" not in css
    assert 'font-family: "Good"' in css


def t_ob_compile_customcss_last_and_verbatim():
    css = ob.compile_overlay_css(
        {"slots": {"stint": {"left": 10}}, "customCss": "/* mine */\n#stint{top:5px}"},
        SLOTS)
    assert css.rstrip().endswith("/* mine */\n#stint{top:5px}")
    assert "left: 10px" in css and css.index("left: 10px") < css.index("/* mine */")


def t_ob_compile_sanitizes_value_breakout():
    # A structured prop value must not be able to close the rule / inject CSS;
    # the customCss escape hatch is the only verbatim path.
    css = ob.compile_overlay_css(
        {"slots": {"stint": {"color": "red; } body{display:none"}}}, SLOTS)
    assert "display:none" not in css and "body{" not in css


def t_ob_migrate_imports_existing_css_into_customcss():
    layout = ob.migrate_layout("hud", "#stint{left:999px}/* hand-written */")
    assert layout["page"] == "hud" and layout["slots"] == {}
    assert layout["customCss"] == "#stint{left:999px}/* hand-written */"
    # and it compiles back out verbatim
    css = ob.compile_overlay_css(layout, SLOTS)
    assert "#stint{left:999px}" in css


def t_ob_font_family_is_file_stem():
    assert ob.font_family("League.woff2") == "League"
    assert ob.font_family("My-Font.ttf") == "My-Font"


def t_ob_google_fonts_curated_list():
    assert isinstance(ob.GOOGLE_FONTS, tuple) and len(ob.GOOGLE_FONTS) >= 10
    assert all(isinstance(n, str) and n for n in ob.GOOGLE_FONTS)
    assert "Oswald" in ob.GOOGLE_FONTS


def t_ob_google_font_filename_and_family():
    # spaces stripped, valid against the font-name whitelist, family = stem
    fn = ob.google_font_filename("Saira Condensed")
    assert fn == "SairaCondensed.woff2"
    assert ob.FONT_NAME_RE.match(fn) and fn.rsplit(".", 1)[1] in ob.FONT_EXTS
    assert ob.font_family(fn) == "SairaCondensed"
    assert ob.google_font_filename("Oswald") == "Oswald.woff2"


def t_ob_google_font_css_url():
    u = ob.google_font_css_url("Saira Condensed")
    assert u.startswith("https://fonts.googleapis.com/css2?family=Saira+Condensed")
    assert "wght@700" in u


def t_ob_is_google_font_name():
    # valid families (incl. ones outside the curated catalog) pass
    for ok in ("Oswald", "Exo 2", "Roboto Condensed", "Big Shoulders Display", "A1"):
        assert ob.is_google_font_name(ok), ok
    # host/path/injection tricks and junk are rejected -> never fetched
    for bad in ("", " Oswald", "Oswald ", "../etc/passwd", "Evil/Font", "a@b",
                "x" * 60, "name\ninjection", None, 5):
        assert not ob.is_google_font_name(bad), bad


POVSLOTS = [{"id": "pov", "label": "POV box",
             "props": ["left", "top", "width", "height",
                       "background", "borderStyle", "borderColor", "borderWidth"]}]


def t_ob_compile_pov_border_and_background():
    css = ob.compile_overlay_css(
        {"slots": {"pov": {"background": "#0b0f1a", "borderStyle": "solid",
                           "borderColor": "#ff2a2a", "borderWidth": 4}}}, POVSLOTS)
    assert "#pov {" in css
    assert "background: #0b0f1a" in css
    assert "border-style: solid" in css
    assert "border-color: #ff2a2a" in css
    assert "border-width: 4px" in css


def t_ob_compile_border_width_is_px_gated():
    # borderWidth is numeric-only (px), like the other geometry props
    css = ob.compile_overlay_css({"slots": {"pov": {"borderWidth": "4; }#x{a:b"}}}, POVSLOTS)
    assert "border-width" not in css


def t_ob_compile_border_props_respect_allowed():
    # a text slot that does NOT allow border props must not emit them
    slots = [{"id": "stint", "label": "S", "props": list(ob.DEFAULT_PROPS)}]
    css = ob.compile_overlay_css({"slots": {"stint": {"borderStyle": "solid"}}}, slots)
    assert "border-style" not in css


def t_ob_sample_has_clock_in_hud_only():
    assert ob.SAMPLE["hud"].get("clock") == "1:23:45"
    assert "timer" not in ob.SAMPLE      # timer page is merged into hud


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
