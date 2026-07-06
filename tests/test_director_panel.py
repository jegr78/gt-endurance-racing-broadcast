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
    # Scn.Vis -> Gfx -> Flag Gfx -> Timer -> Audio -> Transition -> Schedule
    # (merged: urlsBox) -> Pending -> Substitution, all after the SETUP panel.
    h = _html()
    _order(h, 'id="tabSetup"',
           'id="scnBus"', 'id="gfxBus"', 'id="flagGfxBus"', 'id="timerBus"',
           'id="audio"', 'id="txBar"', 'id="urlsBox"',
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


def t_setup_badge_hidden_rule():
    # The badge carries `hidden` until Task 4 wires it; an unconditional
    # display: on .tabbadge would override the UA [hidden] rule, so a
    # [hidden] override must exist to keep it invisible.
    h = _html()
    assert ".tabbadge[hidden]" in h, "badge must honor the hidden attribute"


def t_keyboard_shortcuts_present():
    h = _html()
    # global 1/2 switch tabs
    assert 'e.key === "1"' in h and 'e.key === "2"' in h
    # arrow-key nav on the tablist
    assert '"ArrowLeft"' in h and '"ArrowRight"' in h


def t_shortcut_guards_typing():
    # 1/2 must NOT fire while typing in a field.
    h = _html()
    assert "/^(INPUT|TEXTAREA|SELECT)$/.test" in h
    assert "isContentEditable" in h


def t_tx_chip_present_and_wired():
    h = _html()
    # chip lives in the PGM section
    assert 'id="txArmed"' in h
    pgm = h.find('class="bus pgm"')
    assert pgm != -1 and h.find('id="txArmed"') > pgm
    assert h.find('id="txArmed"') < h.find('id="cuesBus"'), "chip must be inside PGM section"
    # renderTxBar updates the chip text
    assert 'chip.textContent = "TX: " + activeTransition.toUpperCase()' in h
    # clicking the chip switches to the SETUP tab
    assert 'chip.addEventListener("click", () => setTab("setup"))' in h


def t_setup_badge_wired():
    h = _html()
    assert "function updateSetupBadge(" in h
    assert 'id="setupBadge"' in h
    # called from BOTH the submissions poll and the substitution poll
    assert h.count("updateSetupBadge()") >= 3  # 1 def-site call chain + >=2 call sites
    # reads the existing pending count and the substitution-visible state
    assert 'getElementById("subsCount")' in h
    assert 'getElementById("subSec")' in h


def t_final_part_confirmation_present():
    h = _html()
    # last-part detection in the modal + the final-confirm copy
    assert "d.index === d.count" in h or "d.index == d.count" in h
    assert "ends the broadcast" in h.lower()
    # the panel reacts to the relay's {final:true} response
    assert "res.final" in h


def t_mode_drives_section_visibility():
    # relayPoll delegates to applyMode(); applyMode toggles the two mode regions
    # and flips the single switch label. The two mode regions are mutually exclusive.
    h = _html()
    assert "applyMode(" in h, "relayPoll must delegate mode handling to applyMode"
    assert '$("#raceSched").hidden = qualifying' in h
    assert '$("#qualSched").hidden = !qualifying' in h
    assert "switch → QUALIFYING" in h   # race-mode target
    assert "switch → RACE" in h          # qualifying-mode target


def t_single_merged_schedule_section():
    # The old standalone Qualifying <details> is gone — one merged block.
    h = _html()
    assert 'id="qualBox"' not in h, "qualBox must be merged into the single #urlsBox block"
    assert h.count('id="urlsBox"') == 1


def t_mode_regions_and_switch_present():
    h = _html()
    assert 'id="raceSched"' in h    # race-only region
    assert 'id="qualSched"' in h    # qualifying-only region
    assert 'id="modeSwitch"' in h   # the single mode switch
    assert 'id="modeChip"' in h     # always-visible mode indicator


def t_pov_editor_shared_across_modes():
    # POV must work in BOTH modes → its editor sits AFTER both mode regions
    # (shared), never nested inside the race-only or qualifying-only region.
    h = _html()
    assert h.index('id="povUrl"') > h.index('id="schedBody"')   # after race region content
    assert h.index('id="povUrl"') > h.index('id="qualRow"')     # after qualifying region content


def t_old_mode_buttons_removed():
    h = _html()
    assert 'id="qualOn"' not in h
    assert 'id="qualOff"' not in h
    assert 'id="qualModeBadge"' not in h


def t_urls_section_honors_hidden_rule():
    # `details.urls{display:block}` is an author rule that overrides the UA
    # `[hidden]{display:none}`, so setting `#urlsBox`.hidden in qualifying mode
    # would NOT hide the race schedule editor without an explicit override —
    # leaving the qualifying feed shown twice. A [hidden] guard must exist.
    h = _html()
    assert "details.urls[hidden]" in h, \
        "details.urls must honor the hidden attribute (else urlsBox stays shown in qualifying mode)"


def t_qualifying_submission_tag_present():
    h = _html()
    # subRow renders a QUALI tag when the pending entry is a qualifying submission
    assert 'QUALI' in h
    assert 'e.mode === "qualifying"' in h


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
