#!/usr/bin/env python3
"""Stdlib unit checks for the profile management commands
(src/scripts/profile_admin.py). Run: python3 tests/test_profile.py"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "src", "scripts")
sys.path.insert(0, SCRIPTS)   # so profile_admin's `import config` resolves
spec = importlib.util.spec_from_file_location(
    "profile_admin", os.path.join(SCRIPTS, "profile_admin.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    raise AssertionError("expected exception")


def t_parse_list_takes_no_args():
    assert m.parse_profile_args(["list"]) == {
        "verb": "list", "name": None, "source": "example"}
    _raises(lambda: m.parse_profile_args(["list", "extra"]))


def t_parse_show_optional_name():
    assert m.parse_profile_args(["show"])["name"] is None
    assert m.parse_profile_args(["show", "iro"])["name"] == "iro"
    _raises(lambda: m.parse_profile_args(["show", "a", "b"]))


def t_parse_use_requires_one_name():
    assert m.parse_profile_args(["use", "erf"]) == {
        "verb": "use", "name": "erf", "source": "example"}
    _raises(lambda: m.parse_profile_args(["use"]))
    _raises(lambda: m.parse_profile_args(["use", "a", "b"]))


def t_parse_new_with_from():
    assert m.parse_profile_args(["new", "erf"]) == {
        "verb": "new", "name": "erf", "source": "example"}
    assert m.parse_profile_args(["new", "erf", "--from", "iro"])["source"] == "iro"
    assert m.parse_profile_args(["new", "erf", "--from=iro"])["source"] == "iro"
    _raises(lambda: m.parse_profile_args(["new"]))
    _raises(lambda: m.parse_profile_args(["new", "erf", "--bogus"]))
    _raises(lambda: m.parse_profile_args(["new", "erf", "--from"]))    # missing value
    _raises(lambda: m.parse_profile_args(["new", "erf", "--from="]))   # empty value


def t_parse_unknown_verb_raises():
    _raises(lambda: m.parse_profile_args([]))
    _raises(lambda: m.parse_profile_args(["frobnicate"]))


def t_split_profile_flag_extracts_anywhere():
    assert m.split_profile_flag(["relay", "start"]) == (["relay", "start"], None)
    assert m.split_profile_flag(["--profile", "erf", "relay", "start"]) == (
        ["relay", "start"], "erf")
    assert m.split_profile_flag(["relay", "--profile=erf", "start"]) == (
        ["relay", "start"], "erf")


def t_split_profile_flag_missing_value_raises():
    _raises(lambda: m.split_profile_flag(["--profile"]))
    _raises(lambda: m.split_profile_flag(["--profile=", "relay"]))   # empty value


def t_valid_profile_name():
    assert m.valid_profile_name("erf")
    assert m.valid_profile_name("gt-2026_a")
    assert not m.valid_profile_name("ERF")
    assert not m.valid_profile_name("-bad")
    assert not m.valid_profile_name("has space")
    assert not m.valid_profile_name("")


def t_slugify_makes_directory_safe_slug():
    assert m.slugify("IRO GTEC") == "iro-gtec"
    assert m.slugify("erf") == "erf"
    assert m.slugify("gt-2026_a") == "gt-2026_a"        # already-valid slugs unchanged
    assert m.slugify("  Hello   World!  ") == "hello-world"
    assert m.slugify("../../etc") == "etc"               # path traversal collapses to a slug
    assert m.slugify("!!!") == ""                        # nothing usable
    assert m.slugify("") == ""


def _mkroot_with_example(td):
    """A fake project root with profiles/example/profile.env."""
    root = os.path.join(td, "proj")
    ex = os.path.join(root, "profiles", "example")
    os.makedirs(ex)
    with open(os.path.join(ex, "profile.env"), "w", encoding="utf-8") as fh:
        fh.write("NAME=Example League\nSHEET_ID=\n")
    open(os.path.join(root, ".env.example"), "w").close()   # project marker
    return root


def t_create_profile_copies_example():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        target = m.create_profile(root, "erf")
        assert target == os.path.join(root, "profiles", "erf")
        assert os.path.isfile(os.path.join(target, "profile.env"))
        # config now lists it (example stays excluded)
        assert m.cfg.list_profiles(root) == ["erf"]


def t_create_profile_from_other_profile():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        m.create_profile(root, "iro")
        with open(os.path.join(root, "profiles", "iro", "profile.env"),
                  "w", encoding="utf-8") as fh:
            fh.write("NAME=IRO\nSHEET_ID=abc\n")
        m.create_profile(root, "erf", source="iro")
        assert m.cfg.parse_profile(root, "erf")["SHEET_ID"] == "abc"


def t_create_profile_accepts_spaces_via_slug_and_sets_display_name():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        target = m.create_profile(root, "IRO GTEC")
        assert target == os.path.join(root, "profiles", "iro-gtec")   # slugged dir
        assert m.cfg.list_profiles(root) == ["iro-gtec"]
        # the typed name is preserved as the league display NAME, not the slug
        assert m.cfg.parse_profile(root, "iro-gtec")["NAME"] == "IRO GTEC"


def t_create_profile_rejects_unsluggable_existing_and_missing_source():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        _raises(lambda: m.create_profile(root, "!!!"))       # nothing usable -> empty slug
        _raises(lambda: m.create_profile(root, "example"))   # reserved
        m.create_profile(root, "erf")
        _raises(lambda: m.create_profile(root, "erf"))        # already exists
        _raises(lambda: m.create_profile(root, "Erf"))        # same slug already exists
        _raises(lambda: m.create_profile(root, "x", source="ghost"))  # no source


def t_set_active_profile_writes_pointer():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        m.create_profile(root, "erf")
        runtime = os.path.join(td, "runtime")
        assert m.set_active_profile(root, runtime, "erf") == "erf"
        assert m.cfg.read_active_pointer(runtime) == "erf"


def t_set_active_profile_unknown_raises():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        runtime = os.path.join(td, "runtime")
        _raises(lambda: m.set_active_profile(root, runtime, "ghost"))


def t_format_profile_list_marks_active():
    out = m.format_profile_list(["erf", "iro"], "iro")
    assert "  erf" in out
    assert "* iro" in out


def t_format_profile_list_empty():
    assert "no profiles" in m.format_profile_list([], None)


def t_mask_hides_secret_body():
    assert m.mask_secret("") == "(unset)"
    assert m.mask_secret("https://script.google.com/exec?key=SECRETVALUE") \
        .startswith("http")
    # the secret body is not shown in full
    assert "SECRETVALUE" not in m.mask_secret(
        "https://x/exec?key=SECRETVALUE")
    assert m.mask_secret("short") == "****"


def t_format_profile_show_masks_push_url():
    cfg_obj = m.cfg.ResolvedConfig(
        profile="iro", name="IRO GTEC", sheet_id="SHEETID123",
        sheet_push_url="https://x/exec?key=TOPSECRET",
        profile_dir="/p/profiles/iro", runtime_dir="/p/runtime/iro")
    out = m.format_profile_show(cfg_obj, active="iro")
    assert "IRO GTEC" in out
    assert "SHEETID123" in out          # sheet id shown (link-shared, not a secret)
    assert "TOPSECRET" not in out       # push-url secret masked
    assert "(active)" in out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
