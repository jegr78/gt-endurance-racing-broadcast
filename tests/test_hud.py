#!/usr/bin/env python3
"""Stdlib unit checks for the HUD additions. Run: python3 tests/test_hud.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_asset_key_basic():
    assert m.asset_key("GERMANY") == "germany"
    assert m.asset_key("  United Arab Emirates ") == "united-arab-emirates"
    assert m.asset_key("Porsche") == "porsche"
    assert m.asset_key("") == ""
    assert m.asset_key(None) == ""


OVERLAY_CSV = (
    ",Stint,Intro,,,,,,,\n"
    ",,,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Streamer,JeGr,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Session,Warmup,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Top,Round 4: Nurburgring 24hrs,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Bottom,GERMANY,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Flag,,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P1,,,OVO eSports #111,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P2,,,Feel Good Racing #303,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P3,,,NWR Motorsport #224,,,,,\n"
    ",,,,,,,,,\n"
    ",Race Control,,,,,,,,\n"
)


def t_parse_overlay_values():
    o = m.parse_overlay(OVERLAY_CSV)
    assert o["stint"] == "Intro", o
    assert o["streamer"] == "JeGr", o
    assert o["session"] == "Warmup", o
    assert o["round_top"] == "Round 4: Nurburgring 24hrs", o
    assert o["country"] == "GERMANY", o
    assert o["teams"] == ["OVO eSports #111", "Feel Good Racing #303",
                          "NWR Motorsport #224"], o
    assert o["race_control"] == "", o


def t_parse_overlay_missing_rows_safe():
    o = m.parse_overlay(",Streamer,JeGr,,,,,,,\n")
    assert o["streamer"] == "JeGr"
    assert o["teams"] == ["", "", ""]
    assert o["country"] == ""


CONFIG_CSV = (
    "Stints,Streamers,Session,Round,Country,Flag,Teams,,Brands,Race Control,Brand Key\n"
    "Stint 1,JeGr,Qualifier,Round 1,UNITED STATES,,OVO eSports #111,,,Formation Lap,Porsche\n"
    "Stint 2,GT45,Race,Round 2,AUSTRALIA,,Feel Good Racing #303,,,Final Lap,Porsche\n"
    "Stint 3,,,,,,NWR Motorsport #224,,,,Ferrari\n"
)


def t_parse_config_brands():
    b = m.parse_config_brands(CONFIG_CSV)
    assert b["OVO eSports #111"] == "porsche", b
    assert b["Feel Good Racing #303"] == "porsche", b
    assert b["NWR Motorsport #224"] == "ferrari", b


def t_parse_config_brands_missing_columns_safe():
    assert m.parse_config_brands("a,b,c\n1,2,3\n") == {}


# Real sheet uses header "Brand Name" (text), alongside image columns
# "Brand Logo" and "Brands" which must NOT be picked up.
CONFIG_CSV_BRANDNAME = (
    "Teams,Brand Name,Brand Logo,Brands,Race Control\n"
    "OVO eSports #111,Porsche,,,Formation Lap\n"
    "Elite Racing Squad #73,BMW,,,Final Lap\n"
    "Alien Motorsports #999,AMG,,,Warmup\n"
)


def t_parse_config_brands_accepts_brand_name_header():
    b = m.parse_config_brands(CONFIG_CSV_BRANDNAME)
    assert b["OVO eSports #111"] == "porsche", b
    assert b["Elite Racing Squad #73"] == "bmw", b
    assert b["Alien Motorsports #999"] == "amg", b


def t_parse_config_brands_ignores_image_columns():
    # only image columns present -> nothing matched
    assert m.parse_config_brands("Teams,Brand Logo,Brands\nX #1,,\n") == {}


def t_build_hud_data():
    overlay = m.parse_overlay(OVERLAY_CSV)
    brands = m.parse_config_brands(CONFIG_CSV)
    d = m.build_hud_data(overlay, brands)
    assert d["stint"] == "Intro"
    assert d["streamer"] == "JeGr"
    assert d["session"] == "Warmup"
    assert d["round"]["top"] == "Round 4: Nurburgring 24hrs"
    assert d["round"]["country"] == "GERMANY"
    assert d["round"]["flagKey"] == "germany"
    assert d["teams"][0] == {"name": "OVO eSports #111", "brandKey": "porsche"}
    assert d["teams"][2] == {"name": "NWR Motorsport #224", "brandKey": "ferrari"}
    assert d["raceControl"] == ""


def t_build_hud_data_unknown_brand_blank():
    overlay = m.parse_overlay(",Teams P1,,,Mystery Team #0,,,,,\n")
    d = m.build_hud_data(overlay, {})
    assert d["teams"][0] == {"name": "Mystery Team #0", "brandKey": ""}


def t_hudsource_data_uses_builders():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.refresh() is True
    data = hs.data()
    assert data["streamer"] == "JeGr"
    assert data["teams"][0]["brandKey"] == "porsche"


def t_resolve_asset_extension_agnostic():
    import tempfile, os as _os
    ad = tempfile.mkdtemp()
    _os.makedirs(_os.path.join(ad, "brands"))
    _os.makedirs(_os.path.join(ad, "flags"))
    with open(_os.path.join(ad, "brands", "porsche.png"), "w") as fh:
        fh.write("x")
    with open(_os.path.join(ad, "flags", "germany.svg"), "w") as fh:
        fh.write("x")
    # png resolves with image/png ctype
    path, ctype = m.resolve_asset(ad, "brands", "porsche")
    assert path.endswith("porsche.png") and ctype == "image/png", (path, ctype)
    # svg resolves with image/svg+xml ctype
    path, ctype = m.resolve_asset(ad, "flags", "germany")
    assert path.endswith("germany.svg") and ctype == "image/svg+xml", (path, ctype)
    # unknown key -> None
    assert m.resolve_asset(ad, "brands", "ferrari") is None
    # bad subdir / bad key -> None
    assert m.resolve_asset(ad, "evil", "porsche") is None
    assert m.resolve_asset(ad, "brands", "../secret") is None


def t_hudsource_keeps_last_good_on_failure():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    def boom(url, timeout=10):
        raise RuntimeError("sheet down")
    hs._fetch = boom
    assert hs.refresh() is False
    assert hs.data()["streamer"] == "JeGr"   # last-good preserved


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
