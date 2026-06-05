#!/usr/bin/env python3
"""Stdlib checks for the `iro update` decision helpers. Run: python3 tests/test_update.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "update", os.path.join(ROOT, "src", "scripts", "update.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- parse_version ------------------------------------------------------------
def t_parse_version_good():
    assert m.parse_version("v0.1.0") == (0, 1, 0)
    assert m.parse_version("v12.34.56") == (12, 34, 56)


def t_parse_version_bad():
    for bad in ("dev", "", None, "0.1.0", "v1.2", "v1.2.3.4", "va.b.c", "v1.2.x"):
        assert m.parse_version(bad) is None, bad


# --- asset_name ----------------------------------------------------------------
def t_asset_name_per_platform():
    assert m.asset_name("win32") == "iro-windows.zip"
    assert m.asset_name("darwin") == "iro-macos.tar.gz"
    assert m.asset_name("linux") == "iro-linux.tar.gz"


# --- classify: the whole decision in one pure function --------------------------
REL = {"tag_name": "v0.2.0",
       "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/m"},
                  {"name": "iro-windows.zip", "browser_download_url": "https://x/w"}]}


def t_classify_dev_refused():
    # repo mode (not frozen): the verb stays git-pull-only
    assert m.classify(REL, "darwin", "dev") == ("dev", None, None)
    assert m.classify(REL, "darwin", "dev", frozen=False) == ("dev", None, None)


def t_classify_frozen_dev_offers_latest():
    # a locally built frozen binary (version 'dev') jumps to the latest release
    assert m.classify(REL, "darwin", "dev", frozen=True) == ("update", "v0.2.0", "https://x/m")
    assert m.classify(REL, "win32", "dev", frozen=True) == ("update", "v0.2.0", "https://x/w")


def t_classify_frozen_dev_building_window():
    assert m.classify(REL, "linux", "dev", frozen=True) == ("building", "v0.2.0", None)


def t_classify_frozen_dev_bad_tag_is_error():
    assert m.classify({"tag_name": "nightly", "assets": []}, "darwin", "dev", frozen=True)[0] == "error"


def t_classify_up_to_date_equal_and_newer_current():
    assert m.classify(REL, "darwin", "v0.2.0") == ("up-to-date", "v0.2.0", None)
    assert m.classify(REL, "darwin", "v0.3.0") == ("up-to-date", "v0.2.0", None)


def t_classify_update_with_url():
    assert m.classify(REL, "darwin", "v0.1.0") == ("update", "v0.2.0", "https://x/m")
    assert m.classify(REL, "win32", "v0.1.0") == ("update", "v0.2.0", "https://x/w")


def t_classify_building_window():
    # newer release exists but the platform asset is not uploaded yet
    assert m.classify(REL, "linux", "v0.1.0") == ("building", "v0.2.0", None)


def t_classify_bad_tag_is_error():
    assert m.classify({"tag_name": "nightly", "assets": []}, "darwin", "v0.1.0")[0] == "error"


# --- swap_plan -------------------------------------------------------------------
def t_swap_plan_posix_inplace():
    assert m.swap_plan("darwin", "/app/iro", "/tmp/new/iro") == \
        [("replace", "/tmp/new/iro", "/app/iro"), ("chmod", "/app/iro")]


def t_swap_plan_windows_rename_trick():
    # impl must use ntpath so this is computable when the test runs on macOS/Linux
    plan = m.swap_plan("win32", r"C:\IRO\iro.exe", r"C:\tmp\iro.exe")
    assert plan == [("rename", r"C:\IRO\iro.exe", r"C:\IRO\iro-old.exe"),
                    ("move", r"C:\tmp\iro.exe", r"C:\IRO\iro.exe")]


# --- safe_member: archive extraction guard ----------------------------------------
def t_safe_member():
    assert m.safe_member("iro") and m.safe_member(".env.example")
    assert m.safe_member("sub/iro")
    assert not m.safe_member("/etc/passwd")
    assert not m.safe_member("..\\iro.exe")
    assert not m.safe_member("a/../../b")
    assert not m.safe_member("C:\\evil")
    assert not m.safe_member("")


# --- fetch_latest: parsing with an injected opener ---------------------------------
def t_fetch_latest_parses_json():
    import io, json
    body = json.dumps(REL).encode()
    rel = m.fetch_latest(opener=lambda req, timeout: io.BytesIO(body))
    assert rel["tag_name"] == "v0.2.0"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
