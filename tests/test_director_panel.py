#!/usr/bin/env python3
"""Stdlib structural checks for the Director Panel tab layout.
Run: python3 tests/test_director_panel.py

No JS runtime here — these assert markup + presence-of-code anchors over the
served HTML string (same pattern as tests/test_cockpit.py). Runtime behavior is
verified via the ui-visual-verification render pass, not here."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PANEL = os.path.join(ROOT, "src", "director", "director-panel.html")


def _html():
    with open(PANEL, encoding="utf-8") as fh:
        return fh.read()


def _order(html, *needles):
    """Assert each needle appears, in strictly increasing position."""
    last = -1
    for n in needles:
        i = html.find(n)
        assert i != -1, f"missing: {n}"
        assert i > last, f"out of order: {n} (at {i}) not after previous (at {last})"
        last = i


def t_tabbar_present():
    h = _html()
    assert 'role="tablist"' in h
    assert 'id="tabBtnProgram"' in h and 'data-tab="program"' in h
    assert 'id="tabBtnSetup"' in h and 'data-tab="setup"' in h
    assert '>PROGRAM<' in h and '>SETUP' in h


def t_two_tabpanels_present():
    h = _html()
    assert 'id="tabProgram"' in h and 'id="tabSetup"' in h
    assert 'role="tabpanel"' in h
    # SETUP panel ships hidden by default (PROGRAM is the default tab).
    seg = h[h.find('id="tabSetup"'):h.find('id="tabSetup"') + 120]
    assert "hidden" in seg, "SETUP panel must be hidden by default"


def t_program_tab_order():
    # Preview -> PGM -> Cues -> Feeds -> HUD, all inside the PROGRAM panel.
    h = _html()
    _order(h, 'id="tabProgram"',
           'id="previewSec"', 'id="pgmBus"', 'id="cuesBus"',
           'id="feedsBus"', 'id="setupRow"',
           'id="tabSetup"')  # everything above precedes the SETUP panel opening


def t_setup_tab_order():
    # Scn.Vis -> Gfx -> Flag Gfx -> Timer -> Audio -> Transition -> URLs
    # -> Qualifying -> Pending -> Substitution, all after the SETUP panel opening.
    h = _html()
    _order(h, 'id="tabSetup"',
           'id="scnBus"', 'id="gfxBus"', 'id="flagGfxBus"', 'id="timerBus"',
           'id="audio"', 'id="txBar"', 'id="urlsBox"', 'id="qualBox"',
           'id="subsBox"', 'id="subSec"')


def t_log_outside_panels():
    # The status log stays below both panels (visible on both tabs).
    h = _html()
    _order(h, 'id="subSec"', 'id="log"')


def t_settab_and_default():
    h = _html()
    assert "function setTab(" in h
    assert '"rc_panel_tab"' in h
    # boot initializes from the stored tab, defaulting to program
    assert 'localStorage.getItem(TAB_KEY) || "program"' in h


def t_preview_default_shown():
    # New/unset installs show the preview by default (respects an explicit "0").
    h = _html()
    assert 'localStorage.getItem(PV_KEY) || "1"' in h


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
