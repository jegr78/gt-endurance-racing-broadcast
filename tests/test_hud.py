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
    r = m.parse_config_roster(CONFIG_CSV)
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche"}, r
    assert r["Feel Good Racing"] == {"number": "303", "brandKey": "porsche"}, r
    assert r["NWR Motorsport"] == {"number": "224", "brandKey": "ferrari"}, r


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
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche"}, r
    assert r["Elite Racing Squad"] == {"number": "73", "brandKey": "bmw"}, r
    assert r["Alien Motorsports"] == {"number": "999", "brandKey": "amg"}, r


def t_parse_config_roster_ignores_image_columns():
    # team header present, only image brand columns -> brandKey blank, number from #1
    assert m.parse_config_roster("Teams,Brand Logo,Brands\nX #1,,\n") == {
        "X": {"number": "1", "brandKey": ""}}


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
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche"}
    assert d["teams"][2] == {"name": "NWR Motorsport", "number": "224", "brandKey": "ferrari"}
    assert d["raceControl"] == ""


def t_build_hud_data_unknown_brand_blank():
    overlay = m.parse_overlay(",Teams P1,,,Mystery Team #0,,,,,\n")
    d = m.build_hud_data(overlay, {})
    assert d["teams"][0] == {"name": "Mystery Team", "number": "0", "brandKey": ""}


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
    assert v == {"stint": [], "streamer": [], "session": [], "racecontrol": []}
    assert m.parse_config_vocab("") == {"stint": [], "streamer": [],
                                        "session": [], "racecontrol": []}


def t_parse_config_vocab_dedupes_keeps_order():
    v = m.parse_config_vocab("Streamers\nB\nA\nB\n\nA\n")
    assert v["streamer"] == ["B", "A"], v


def t_hudsource_vocab_from_refresh():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.vocab() == {"stint": [], "streamer": [], "session": [],
                          "racecontrol": []}   # before any refresh
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

def t_roster_number_column():
    r = m.parse_config_roster(ROSTER_CSV_WITH_NUMBER)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche"},
                 "Feel Good": {"number": "303", "brandKey": "bmw"}}, r

def t_roster_embedded_fallback():
    r = m.parse_config_roster(ROSTER_CSV_EMBEDDED_ONLY)
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche"}
    assert r["Apex Racing"] == {"number": "7", "brandKey": "audi"}

def t_roster_column_wins_over_embedded():
    r = m.parse_config_roster(ROSTER_CSV_BOTH)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche"}}, r

def t_roster_no_teams_header_is_empty():
    assert m.parse_config_roster("Foo,Bar\n1,2\n") == {}

def t_build_hud_data_team_number_and_strip():
    roster = {"OVO eSports": {"number": "111", "brandKey": "porsche"}}
    overlay = {"teams": ["OVO eSports #999", "Unknown #5", ""]}
    d = m.build_hud_data(overlay, roster)
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche"}
    assert d["teams"][1] == {"name": "Unknown", "number": "5", "brandKey": ""}
    assert d["teams"][2] == {"name": "", "number": "", "brandKey": ""}


def t_parse_config_roster_team_name_header():
    r = m.parse_config_roster("Team Name,Number,Brand\nOVO eSports,111,Porsche\n")
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche"}}, r


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
    assert hs.resolve_team("OVO eSports") == {"name": "OVO eSports", "number": "111", "brandKey": "porsche"}
    # unknown -> stripped name, blank number/logo (embedded #9 used as fallback number)
    assert hs.resolve_team("Ghost #9") == {"name": "Ghost", "number": "9", "brandKey": ""}

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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
