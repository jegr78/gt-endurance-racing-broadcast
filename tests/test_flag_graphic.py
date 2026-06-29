#!/usr/bin/env python3
"""Stdlib unit checks for flag-status graphics. Run: python3 tests/test_flag_graphic.py"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


fg = _load("flag_graphic", ("src", "scripts", "flag_graphic.py"))


def t_sources_are_the_five_flags():
    assert list(fg.FLAG_GRAPHIC_SOURCES) == [
        "green", "yellow", "red", "safety-car", "virtual-safety-car"]
    assert fg.FLAG_GRAPHIC_SOURCES["green"] == "Flag Green"
    assert fg.FLAG_GRAPHIC_SOURCES["virtual-safety-car"] == "Flag Virtual Safety Car"
    assert fg.FLAG_GRAPHIC_SCENES == ("Stint", "Splitscreen")


def t_normalize_canonical_aliases_and_clear():
    assert fg.normalize_flag_value("green") == "green"
    assert fg.normalize_flag_value("GREEN") == "green"
    assert fg.normalize_flag_value(" Safety Car ") == "safety-car"
    assert fg.normalize_flag_value("sc") == "safety-car"
    assert fg.normalize_flag_value("vsc") == "virtual-safety-car"
    assert fg.normalize_flag_value("") == ""
    assert fg.normalize_flag_value(None) == ""
    assert fg.normalize_flag_value("purple") is None


def t_intents_show_one_hide_rest_in_both_scenes():
    intents = fg.flag_graphic_intents("yellow")
    assert len(intents) == 10                         # 5 sources x 2 scenes
    on = [(sc, src) for (sc, src, en) in intents if en]
    assert on == [("Stint", "Flag Yellow"), ("Splitscreen", "Flag Yellow")]
    # everything else hidden
    assert all(not en for (sc, src, en) in intents if src != "Flag Yellow")


def t_intents_clear_hides_all():
    for active in ("", None, "bogus"):
        assert all(not en for (_sc, _src, en) in fg.flag_graphic_intents(active))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
