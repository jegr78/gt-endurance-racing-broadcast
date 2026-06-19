#!/usr/bin/env python3
"""Stdlib unit checks for the /console authorization policy (#216 phase 2).
Run: python3 tests/test_console.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


cp = _load("console_policy", os.path.join("src", "scripts", "console_policy.py"))


def _cap(segs, method="GET"):
    r = cp.min_capability(segs, method)
    return None if r is None else (r.capability, r.step_up)


def t_any_authenticated_reads():
    for segs in ([], ["status"], ["console"], ["data"], ["program"],
                 ["hud"], ["hud", "data"], ["hud", "override.css"],
                 ["hud", "preview"], ["hud", "assets", "flags", "de.png"],
                 ["preview", "program"], ["preview", "feed", "A"],
                 ["timer", "data"], ["setup", "data"],
                 ["schedule", "data"], ["qualifying", "data"],
                 ["chat", "data"], ["chat", "reload"],
                 ["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
                 ["cockpit", "timer"], ["cockpit", "chat", "data"]):
        assert _cap(segs) == ("any", False), segs


def t_chat_send_is_any_authenticated():
    assert _cap(["chat", "send"], "POST") == ("any", False)


def t_submit_is_commentator():
    assert _cap(["submit"], "POST") == ("commentator", False)
    assert _cap(["cockpit", "submit"], "POST") == ("commentator", False)


def t_director_feed_and_schedule_control():
    for segs in (["next"], ["prev", "A"], ["reload"], ["reload", "A"],
                 ["set", "A", "3"], ["set", "B", "12"]):
        assert _cap(segs) == ("director", False), segs


def t_director_panel_setup_timer_pov_submissions():
    for segs in (["panel"], ["pov", "reload"], ["pov", "set"],
                 ["setup", "set", "stint", "Alice"],
                 ["timer", "start"], ["timer", "stop"], ["timer", "set", "1:00:00"],
                 ["schedule", "set"], ["qualifying", "set"], ["event", "title"],
                 ["submissions"], ["submissions", "approve"], ["submissions", "reject"]):
        assert _cap(segs) == ("director", False), segs


def t_setup_data_and_timer_data_are_reads_not_director():
    # The read endpoints under setup/timer must stay "any", not escalate to director.
    assert _cap(["setup", "data"]) == ("any", False)
    assert _cap(["timer", "data"]) == ("any", False)


def t_producer_stepup_irreversible_ops():
    for segs in (["set", "stint", "4"], ["mode", "race"], ["mode", "qualifying"],
                 ["takeover", "status"], ["takeover", "chat"], ["takeover", "versions"],
                 ["cockpit", "versions"]):
        assert _cap(segs) == ("producer", True), segs


def t_prod_page_is_producer_view_no_stepup():
    assert _cap(["prod"]) == ("producer", False)


def t_set_stint_not_confused_with_set_feed():
    # set/stint/<n> is producer+stepup; set/<feed>/<n> is director. Ordering matters.
    assert _cap(["set", "stint", "4"]) == ("producer", True)
    assert _cap(["set", "A", "4"]) == ("director", False)


def t_unknown_route_is_none():
    for segs in (["bogus"], ["timer"], ["set"], ["set", "A"],
                 ["cockpit", "nope"], ["mode"]):
        assert cp.min_capability(segs) is None, segs


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
