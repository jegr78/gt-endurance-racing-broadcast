#!/usr/bin/env python3
"""Stdlib checks for shared installer helpers. Run: python3 tests/test_installer_common.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "installer_common", os.path.join(ROOT, "src", "scripts", "installer_common.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_confirmed_parsing():
    assert m.confirmed("y") and m.confirmed("Y") and m.confirmed("yes")
    assert not m.confirmed("") and not m.confirmed("n") and not m.confirmed("nein")


def t_find_brew_prefers_path():
    assert m.find_brew(which=lambda n: "/usr/local/bin/brew",
                       exists=lambda p: True) == "/usr/local/bin/brew"


def t_find_brew_standard_locations():
    arm = "/opt/homebrew/bin/brew"
    assert m.find_brew(which=lambda n: None, exists=lambda p: p == arm) == arm
    intel = "/usr/local/bin/brew"
    assert m.find_brew(which=lambda n: None, exists=lambda p: p == intel) == intel
    assert m.find_brew(which=lambda n: None, exists=lambda p: False) is None


def t_bootstrap_declined_runs_nothing():
    calls = []
    out = m.bootstrap_brew(False, input_fn=lambda prompt: "n",
                           run=lambda url, runner: calls.append(url) or 0,
                           find=lambda: "/opt/homebrew/bin/brew")
    assert out is None and calls == []


def t_bootstrap_yes_runs_and_relocates():
    calls = []
    out = m.bootstrap_brew(True, input_fn=lambda prompt: "n",
                           run=lambda url, runner: calls.append((url, runner)) or 0,
                           find=lambda: "/opt/homebrew/bin/brew")
    assert out == "/opt/homebrew/bin/brew"
    assert calls == [(m.BREW_INSTALLER, ["/bin/bash"])]


def t_bootstrap_failed_install_returns_none():
    out = m.bootstrap_brew(True, input_fn=lambda prompt: "y",
                           run=lambda url, runner: 1,
                           find=lambda: "/opt/homebrew/bin/brew")
    assert out is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
