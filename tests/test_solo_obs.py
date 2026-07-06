#!/usr/bin/env python3
"""Stdlib checks for solo OBS templates + device localization (#303).
Run: python3 tests/test_solo_obs.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sa = _load("setup_assets", "src", "setup-assets.py")


def t_resolve_template_base():
    assert sa.resolve_template_base("endurance", "") == "GT_Endurance"
    assert sa.resolve_template_base("solo", "commentary") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("solo", "pov") == "GT_Solo_POV"
    assert sa.resolve_template_base("solo", "") == "GT_Solo_Commentary"      # default
    assert sa.resolve_template_base("solo", "nonsense") == "GT_Solo_Commentary"
    assert sa.resolve_template_base("", "") == "GT_Endurance"                 # default kind


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
