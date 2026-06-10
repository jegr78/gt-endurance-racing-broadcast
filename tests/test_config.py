#!/usr/bin/env python3
"""Stdlib unit checks for the profile-aware config resolver.
Run: python3 tests/test_config.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "racecast_config", os.path.join(ROOT, "src", "scripts", "config.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _mkroot(td):
    """A fake project root: a dir holding a .env.example marker."""
    root = os.path.join(td, "proj")
    os.makedirs(root)
    open(os.path.join(root, ".env.example"), "w").close()
    return root


def t_find_project_root_finds_marker_above_start():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        start = os.path.join(root, "src", "scripts")
        os.makedirs(start)
        assert m.find_project_root(start) == root


def t_find_project_root_returns_none_when_no_marker_within_bound():
    with tempfile.TemporaryDirectory() as td:
        deep = os.path.join(td, "a", "b", "c", "d", "e")
        os.makedirs(deep)
        # no marker anywhere -> None (bounded walk, never an unrelated parent)
        assert m.find_project_root(deep, max_levels=4) is None


def t_parse_env_text_ignores_blanks_comments_and_strips_quotes():
    text = '\n'.join([
        "# a comment",
        "",
        "SHEET_ID=abc123",
        '  NAME = "IRO Endurance" ',
        "URL='https://x/y?key=z'",   # '=' inside the value is kept
        "noequals",
    ])
    got = m.parse_env_text(text)
    assert got == {
        "SHEET_ID": "abc123",
        "NAME": "IRO Endurance",
        "URL": "https://x/y?key=z",
    }


def t_load_machine_env_reads_dotenv_at_root():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        with open(os.path.join(root, ".env"), "w", encoding="utf-8") as fh:
            fh.write("RACECAST_PROFILE=iro\nRACECAST_UI_PORT=8089\n")
        got = m.load_machine_env(root)
        assert got == {"RACECAST_PROFILE": "iro", "RACECAST_UI_PORT": "8089"}


def t_load_machine_env_returns_empty_when_no_dotenv():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)   # marker present, but no .env file
        assert m.load_machine_env(root) == {}


def _mkprofile(root, name, body):
    pdir = os.path.join(root, "profiles", name)
    os.makedirs(pdir)
    with open(os.path.join(pdir, "profile.env"), "w", encoding="utf-8") as fh:
        fh.write(body)
    return pdir


def t_list_profiles_sorted_excludes_example_and_dirs_without_profile_env():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "SHEET_ID=a\n")
        _mkprofile(root, "erf", "SHEET_ID=b\n")
        _mkprofile(root, "example", "SHEET_ID=\n")           # template, excluded
        os.makedirs(os.path.join(root, "profiles", "empty"))  # no profile.env
        assert m.list_profiles(root) == ["erf", "iro"]


def t_list_profiles_empty_when_no_profiles_dir():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        assert m.list_profiles(root) == []


def t_parse_profile_reads_named_profile():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "NAME=IRO Endurance\nSHEET_ID=abc\n")
        assert m.parse_profile(root, "iro") == {
            "NAME": "IRO Endurance", "SHEET_ID": "abc"}


def t_read_active_pointer_reads_and_strips():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "active-profile"), "w", encoding="utf-8") as fh:
            fh.write("erf\n")
        assert m.read_active_pointer(td) == "erf"
        os.remove(os.path.join(td, "active-profile"))
        assert m.read_active_pointer(td) is None


def t_resolve_active_profile_precedence_override_beats_env_and_pointer():
    avail = ["erf", "iro"]
    assert m.resolve_active_profile(
        avail, override="iro", env_value="erf", pointer="erf") == "iro"


def t_resolve_active_profile_env_beats_pointer():
    assert m.resolve_active_profile(
        ["erf", "iro"], env_value="erf", pointer="iro") == "erf"


def t_resolve_active_profile_pointer_used_when_no_override_or_env():
    assert m.resolve_active_profile(["erf", "iro"], pointer="iro") == "iro"


def t_resolve_active_profile_single_profile_is_implicit():
    assert m.resolve_active_profile(["iro"]) == "iro"


def t_resolve_active_profile_unknown_name_raises():
    try:
        m.resolve_active_profile(["iro"], override="ghost")
        raise AssertionError("expected ProfileError")
    except m.ProfileError as e:
        assert "ghost" in str(e) and "iro" in str(e)


def t_resolve_active_profile_ambiguous_raises():
    try:
        m.resolve_active_profile(["erf", "iro"])
        raise AssertionError("expected ProfileError")
    except m.ProfileError as e:
        assert "--profile" in str(e)


def t_resolve_active_profile_none_raises():
    try:
        m.resolve_active_profile([])
        raise AssertionError("expected ProfileError")
    except m.ProfileError as e:
        assert "no profiles" in str(e)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
