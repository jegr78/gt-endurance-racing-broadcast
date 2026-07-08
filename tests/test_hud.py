#!/usr/bin/env python3
"""Stdlib unit checks for the HUD additions. Run: python3 tests/test_hud.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
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


def t_parse_config_roster():
    # Keyed by the VERBATIM label (with #NNN) so same-name cars never collide.
    r = m.parse_config_roster(CONFIG_CSV)
    assert r["OVO eSports #111"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["Feel Good Racing #303"] == {"number": "303", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["NWR Motorsport #224"] == {"number": "224", "brandKey": "ferrari", "brandName": "Ferrari"}, r


def t_parse_config_roster_missing_team_header_safe():
    assert m.parse_config_roster("a,b,c\n1,2,3\n") == {}


# Real sheet uses header "Brand Name" (text), alongside image columns
# "Brand Logo" and "Brands" which must NOT be picked up.
CONFIG_CSV_BRANDNAME = (
    "Teams,Brand Name,Brand Logo,Brands,Race Control\n"
    "OVO eSports #111,Porsche,,,Formation Lap\n"
    "Elite Racing Squad #73,BMW,,,Final Lap\n"
    "Alien Motorsports #999,AMG,,,Warmup\n"
)


def t_parse_config_roster_accepts_brand_name_header():
    r = m.parse_config_roster(CONFIG_CSV_BRANDNAME)
    assert r["OVO eSports #111"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}, r
    assert r["Elite Racing Squad #73"] == {"number": "73", "brandKey": "bmw", "brandName": "BMW"}, r
    assert r["Alien Motorsports #999"] == {"number": "999", "brandKey": "amg", "brandName": "AMG"}, r


# New "Brand Name Override" column: when present it wins for the DISPLAY name,
# but never changes the logo mapping (brandKey stays the asset_key of Brand).
CONFIG_CSV_BRAND_OVERRIDE = (
    "Teams,Brand Name,Brand Name Override,Race Control\n"
    "OVO eSports #111,Porsche,Porsche 963,Formation Lap\n"   # override wins for text
    "Elite Racing Squad #73,BMW,,Final Lap\n"                 # blank override -> verbatim
)


def t_parse_config_roster_brand_name_override():
    r = m.parse_config_roster(CONFIG_CSV_BRAND_OVERRIDE)
    # override wins for the display name; brandKey still maps from Brand ("porsche")
    assert r["OVO eSports #111"] == {
        "number": "111", "brandKey": "porsche", "brandName": "Porsche 963"}, r
    # empty override falls back to the verbatim brand text
    assert r["Elite Racing Squad #73"] == {
        "number": "73", "brandKey": "bmw", "brandName": "BMW"}, r


def t_parse_config_roster_ignores_image_columns():
    # team header present, only image brand columns -> brandKey blank, number from #1
    assert m.parse_config_roster("Teams,Brand Logo,Brands\nX #1,,\n") == {
        "X #1": {"number": "1", "brandKey": "", "brandName": ""}}


def t_build_hud_data():
    overlay = m.parse_overlay(OVERLAY_CSV)
    roster = m.parse_config_roster(CONFIG_CSV)
    d = m.build_hud_data(overlay, roster)
    assert d["stint"] == "Intro"
    assert d["streamer"] == "JeGr"
    assert d["session"] == "Warmup"
    assert d["round"]["top"] == "Round 4: Nurburgring 24hrs"
    assert d["round"]["country"] == "GERMANY"
    assert d["round"]["flagKey"] == "germany"
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche",
                             "brandName": "Porsche", "label": "OVO eSports #111"}
    assert d["teams"][2] == {"name": "NWR Motorsport", "number": "224", "brandKey": "ferrari",
                             "brandName": "Ferrari", "label": "NWR Motorsport #224"}
    assert d["raceControl"] == ""


def t_build_hud_data_unknown_brand_blank():
    overlay = m.parse_overlay(",Teams P1,,,Mystery Team #0,,,,,\n")
    d = m.build_hud_data(overlay, {})
    assert d["teams"][0] == {"name": "Mystery Team", "number": "0", "brandKey": "",
                             "brandName": "", "label": "Mystery Team #0"}


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


def t_parse_config_vocab():
    v = m.parse_config_vocab(CONFIG_CSV)
    assert v["stint"] == ["Stint 1", "Stint 2", "Stint 3"], v
    assert v["streamer"] == ["JeGr", "GT45"], v
    assert v["session"] == ["Qualifier", "Race"], v
    assert v["racecontrol"] == ["Formation Lap", "Final Lap"], v


def t_parse_config_vocab_missing_columns_safe():
    v = m.parse_config_vocab("a,b\n1,2\n")
    assert v == {"stint": [], "streamer": [], "session": [], "racecontrol": [], "flag": []}
    assert m.parse_config_vocab("") == {"stint": [], "streamer": [],
                                        "session": [], "racecontrol": [], "flag": []}


def t_parse_config_vocab_dedupes_keeps_order():
    v = m.parse_config_vocab("Streamers\nB\nA\nB\n\nA\n")
    assert v["streamer"] == ["B", "A"], v


FLAG_OVERLAY_CSV = (",Flag,Safety Car,,,,,,,\n")
def t_parse_overlay_flag():
    assert m.parse_overlay(FLAG_OVERLAY_CSV)["flag"] == "Safety Car"

def t_build_hud_data_flag():
    d = m.build_hud_data(m.parse_overlay(FLAG_OVERLAY_CSV), {})
    assert d["flag"] == "Safety Car"

def t_build_hud_data_flag_default_empty():
    d = m.build_hud_data(m.parse_overlay(",Stint,X,,,,,,,\n"), {})
    assert d["flag"] == ""

FLAG_CONFIG_CSV = ("Stints,Flag,Race Control\n"
                   "Stint 1,Yellow Flag,Formation Lap\n"
                   "Stint 2,Safety Car,Final Lap\n")
def t_parse_config_vocab_flag():
    assert m.parse_config_vocab(FLAG_CONFIG_CSV)["flag"] == ["Yellow Flag", "Safety Car"]

def t_hudsource_empty_has_flag():
    assert m.HudSource.EMPTY["flag"] == ""


def t_hudsource_vocab_from_refresh():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.vocab() == {"stint": [], "streamer": [], "session": [],
                          "racecontrol": [], "flag": []}   # before any refresh
    hs.refresh()
    assert hs.vocab()["streamer"] == ["JeGr", "GT45"]


def t_hudsource_vocab_preserved_on_failure():
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
    assert hs.vocab()["streamer"] == ["JeGr", "GT45"]   # last-good preserved


def _hs():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    return hs


def t_override_applies_immediately():
    hs = _hs()
    hs.set_override("raceControl", "Formation Lap", now=1000.0)
    assert hs.data(now=1001.0)["raceControl"] == "Formation Lap"
    assert hs.data(now=1001.0)["streamer"] == "JeGr"   # others untouched
    assert hs.pending(now=1001.0) == {"raceControl"}


def t_override_expires_back_to_sheet_truth():
    hs = _hs()
    hs.set_override("raceControl", "Formation Lap", now=1000.0)
    late = 1000.0 + m.OVERRIDE_TTL + 1
    assert hs.pending(now=late) == set()          # expiry visible without a data() call
    assert hs.data(now=late)["raceControl"] == ""
    assert hs.pending() == set()


def t_override_cleared_when_sheet_confirms():
    hs = _hs()
    hs.set_override("streamer", "GT45", now=1000.0)
    confirmed = OVERLAY_CSV.replace(",Streamer,JeGr,", ",Streamer,GT45,")
    hs._fetch = lambda url, timeout=10: confirmed if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    assert hs.pending() == set()
    assert hs.data(now=1001.0)["streamer"] == "GT45"


def t_override_survives_unconfirmed_refresh():
    hs = _hs()   # sheet still says JeGr
    hs.set_override("streamer", "GT45", now=1000.0)
    hs.refresh()                                       # poll without the new value yet
    assert hs.data(now=1001.0)["streamer"] == "GT45"   # echo still pending
    assert hs.pending(now=1001.0) == {"streamer"}


def t_split_team_label_trailing_number():
    assert m.split_team_label("OVO eSports #111") == ("OVO eSports", "111")
    assert m.split_team_label("Apex Racing #7") == ("Apex Racing", "7")

def t_split_team_label_no_number():
    assert m.split_team_label("OVO eSports") == ("OVO eSports", "")
    assert m.split_team_label("") == ("", "")

def t_split_team_label_mid_string_hash_kept():
    # only a TRAILING "#<digits>" token is split off; a mid-string # stays in the name
    assert m.split_team_label("Team #1 Racing") == ("Team #1 Racing", "")
    assert m.split_team_label("  Spaced #42  ") == ("Spaced", "42")

def t_split_team_label_no_redos_on_long_spaces():
    # CodeQL py/polynomial-redos (#170): the old `^(.*?)\s*#(\d+)\s*$` had `(.*?)`
    # adjacent to `\s*`, both matching a space, so a long run of spaces with no
    # trailing '#<digits>' backtracked quadratically. A huge label must resolve in
    # linear time — this returns effectively instantly with the fixed pattern and
    # would stall for seconds on the old one.
    import time
    label = "Team" + " " * 60000 + "Racing"       # internal spaces, no trailing #num
    t0 = time.monotonic()
    assert m.split_team_label(label) == (label, "")
    assert time.monotonic() - t0 < 1.0
    # trailing number still peeled even behind a long space run
    assert m.split_team_label("Team" + " " * 60000 + "#7") == ("Team", "7")


ROSTER_CSV_WITH_NUMBER = (
    "Teams,Number,Brand Name\n"
    "OVO eSports,111,Porsche\n"
    "Feel Good,303,BMW\n")

ROSTER_CSV_EMBEDDED_ONLY = (
    "Teams,Brand Name\n"
    "OVO eSports #111,Porsche\n"
    "Apex Racing #7,Audi\n")

ROSTER_CSV_BOTH = (
    "Teams,Number,Brand Name\n"
    "OVO eSports #999,111,Porsche\n")   # embedded #999 must be ignored, column wins

# Two cars of the SAME team name but DIFFERENT race numbers: each verbatim
# '#NNN' label is its OWN roster entry. The roster is keyed by the verbatim
# label (not the stripped name), so the dropdown/HUD never collapse two cars
# into one (panel bug: the second car's assignment was lost).
ROSTER_CSV_DUP_NAME = (
    "Teams,Brand Name\n"
    "Scuderia Adriatica Motorsport #14,Ferrari\n"
    "Scuderia Adriatica Motorsport #54,AMG\n")

def t_roster_same_name_different_number_kept_distinct():
    r = m.parse_config_roster(ROSTER_CSV_DUP_NAME)
    assert r["Scuderia Adriatica Motorsport #14"] == {
        "number": "14", "brandKey": "ferrari", "brandName": "Ferrari"}, r
    assert r["Scuderia Adriatica Motorsport #54"] == {
        "number": "54", "brandKey": "amg", "brandName": "AMG"}, r

def t_team_entry_resolves_per_car_by_verbatim_label():
    # The HUD resolves number/brand for the SPECIFIC car in the slot, not
    # whichever same-name row won a stripped-key collision. The displayed name
    # is still stripped; the verbatim 'label' rides along for the panel dropdown.
    roster = m.parse_config_roster(ROSTER_CSV_DUP_NAME)
    assert m.team_entry("Scuderia Adriatica Motorsport #14", roster) == {
        "name": "Scuderia Adriatica Motorsport", "number": "14",
        "brandKey": "ferrari", "brandName": "Ferrari",
        "label": "Scuderia Adriatica Motorsport #14"}
    assert m.team_entry("Scuderia Adriatica Motorsport #54", roster) == {
        "name": "Scuderia Adriatica Motorsport", "number": "54",
        "brandKey": "amg", "brandName": "AMG",
        "label": "Scuderia Adriatica Motorsport #54"}

def t_roster_number_column():
    r = m.parse_config_roster(ROSTER_CSV_WITH_NUMBER)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"},
                 "Feel Good": {"number": "303", "brandKey": "bmw", "brandName": "BMW"}}, r

def t_roster_embedded_fallback():
    r = m.parse_config_roster(ROSTER_CSV_EMBEDDED_ONLY)
    assert r["OVO eSports #111"] == {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}
    assert r["Apex Racing #7"] == {"number": "7", "brandKey": "audi", "brandName": "Audi"}

def t_roster_column_wins_over_embedded():
    # Key is the verbatim label; the Number column still wins for the car number.
    r = m.parse_config_roster(ROSTER_CSV_BOTH)
    assert r == {"OVO eSports #999": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}, r

def t_roster_no_teams_header_is_empty():
    assert m.parse_config_roster("Foo,Bar\n1,2\n") == {}


def t_team_full_labels_keeps_embedded_number():
    # Embedded #NNN (no Number column) -> verbatim label kept under the bare key.
    r = m.parse_team_full_labels(ROSTER_CSV_EMBEDDED_ONLY)
    assert r == {"OVO eSports": "OVO eSports #111", "Apex Racing": "Apex Racing #7"}, r


def t_team_full_labels_bare_when_number_is_separate_column():
    # Bare Teams column + separate Number column -> verbatim label is the bare name.
    r = m.parse_team_full_labels(ROSTER_CSV_WITH_NUMBER)
    assert r == {"OVO eSports": "OVO eSports", "Feel Good": "Feel Good"}, r


def t_team_full_labels_no_teams_header_is_empty():
    assert m.parse_team_full_labels("Foo,Bar\n1,2\n") == {}

def t_build_hud_data_team_number_and_strip():
    # Bare roster key + a numbered slot value -> stripped-name fallback still hits.
    roster = {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}
    overlay = {"teams": ["OVO eSports #999", "Unknown #5", ""]}
    d = m.build_hud_data(overlay, roster)
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche",
                             "brandName": "Porsche", "label": "OVO eSports #999"}
    assert d["teams"][1] == {"name": "Unknown", "number": "5", "brandKey": "",
                             "brandName": "", "label": "Unknown #5"}
    assert d["teams"][2] == {"name": "", "number": "", "brandKey": "", "brandName": "", "label": ""}


def t_parse_config_roster_team_name_header():
    r = m.parse_config_roster("Team Name,Number,Brand\nOVO eSports,111,Porsche\n")
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche", "brandName": "Porsche"}}, r


def t_hudsource_roster_preserved_on_failure():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config", _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.refresh() is True
    assert hs._roster  # populated
    def boom(url, timeout=10): raise OSError("network down")
    hs._fetch = boom
    assert hs.refresh() is False
    assert hs._roster  # last-good roster preserved, not cleared


def _roster_hud():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    overlay = (",Teams P1,OVO eSports,,\n,Teams P2,Feel Good,,\n,Teams P3,,,\n")
    config = "Teams,Number,Brand Name\nOVO eSports,111,Porsche\nFeel Good,303,BMW\n"
    hs._fetch = lambda url, timeout=10: overlay if url == "http://overlay" else config
    hs.refresh()
    return hs

def t_hud_roster_names_and_resolve():
    hs = _roster_hud()
    assert hs.roster_names() == ["OVO eSports", "Feel Good"]
    assert hs.resolve_team("OVO eSports") == {"name": "OVO eSports", "number": "111",
        "brandKey": "porsche", "brandName": "Porsche", "label": "OVO eSports"}
    # unknown -> stripped name, blank number/logo (embedded #9 used as fallback number)
    assert hs.resolve_team("Ghost #9") == {"name": "Ghost", "number": "9",
        "brandKey": "", "brandName": "", "label": "Ghost #9"}

def t_hud_team_override_echo_and_pending():
    hs = _roster_hud()
    entry = hs.resolve_team("Feel Good")
    hs.set_team_override(0, entry, now=1000.0)
    assert hs.data(now=1001.0)["teams"][0] == entry      # optimistic echo into slot 0
    assert hs.team_pending(now=1001.0) == {0}
    assert hs.team_pending(now=1000.0 + m.OVERRIDE_TTL + 1) == set()


def t_hud_team_override_cleared_when_sheet_confirms():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config", _os.path.join(d, "h.json"))
    config = "Teams,Number,Brand Name\nOVO eSports,111,Porsche\nFeel Good,303,BMW\n"
    # sheet starts with P1 = OVO eSports
    state = {"p1": "OVO eSports"}
    def fetch(url, timeout=10):
        if url == "http://overlay":
            return ",Teams P1," + state["p1"] + ",,\n,Teams P2,,,\n,Teams P3,,,\n"
        return config
    hs._fetch = fetch
    assert hs.refresh() is True
    # director optimistically switches P1 to Feel Good
    hs.set_team_override(0, hs.resolve_team("Feel Good"), now=1000.0)
    assert hs.team_pending(now=1001.0) == {0}
    # the sheet has NOT caught up yet -> a refresh keeps the override pending
    assert hs.refresh() is True
    assert hs.team_pending(now=1001.0) == {0}, "override must survive an unconfirmed refresh"
    # now the sheet shows Feel Good in P1 -> the next refresh confirms & clears it
    state["p1"] = "Feel Good"
    assert hs.refresh() is True
    assert hs.team_pending(now=1001.0) == set(), "confirmed override must be pruned"


def t_resolve_brand_override_direct_base():
    import tempfile, os as _os
    bd = tempfile.mkdtemp()
    with open(_os.path.join(bd, "cupra.png"), "w") as fh:
        fh.write("x")
    # brands_dir is the base DIRECTLY (no 'brands' sub-level, unlike resolve_asset)
    path, ctype = m.resolve_brand_override(bd, "cupra")
    assert path.endswith("cupra.png") and ctype == "image/png", (path, ctype)
    assert m.resolve_brand_override(bd, "bmw") is None        # not overridden here
    assert m.resolve_brand_override(bd, "../secret") is None   # traversal rejected
    assert m.resolve_brand_override("", "cupra") is None       # no dir
    assert m.resolve_brand_override(bd, "BadKey") is None       # bad key shape


def t_brand_override_wins_over_base():
    """The exact precedence expression _send_asset uses for sub=='brands'."""
    import tempfile, os as _os
    bd = tempfile.mkdtemp()                       # runtime override dir
    ad = tempfile.mkdtemp()                       # base assets dir (src/assets shape)
    _os.makedirs(_os.path.join(ad, "brands"))
    with open(_os.path.join(bd, "bmw.png"), "w") as fh:
        fh.write("override")
    with open(_os.path.join(ad, "brands", "bmw.png"), "w") as fh:
        fh.write("base")
    hit = m.resolve_brand_override(bd, "bmw") or m.resolve_asset(ad, "brands", "bmw")
    assert hit[0].startswith(_os.path.realpath(bd)), hit          # override path wins
    # a key present only in the base still resolves through the fallback
    with open(_os.path.join(ad, "brands", "audi.png"), "w") as fh:
        fh.write("base")
    hit2 = m.resolve_brand_override(bd, "audi") or m.resolve_asset(ad, "brands", "audi")
    assert hit2[0].endswith("audi.png") and hit2[0].startswith(_os.path.realpath(ad)), hit2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
