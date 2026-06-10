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


# --- ui_asset_name: the iro-ui artifact name in the archive, per platform -----------
def t_ui_asset_name_per_platform():
    assert m.ui_asset_name("win32") == "iro-ui.exe"
    assert m.ui_asset_name("darwin") == "iro-ui.app"
    assert m.ui_asset_name("linux") == "iro-ui"


# --- install_ui: place the sibling iro-ui next to the iro binary --------------------
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def t_install_ui_moves_file():
    import tempfile
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
        _write(os.path.join(src, "iro-ui"), "new")
        dst = m.install_ui(src, tgt, "linux")
        assert dst == os.path.join(tgt, "iro-ui")
        assert os.path.isfile(dst)
        assert not os.path.exists(os.path.join(src, "iro-ui"))


def t_install_ui_overwrites_existing_file():
    import tempfile
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
        _write(os.path.join(src, "iro-ui"), "new")
        _write(os.path.join(tgt, "iro-ui"), "old")
        m.install_ui(src, tgt, "linux")
        with open(os.path.join(tgt, "iro-ui"), encoding="utf-8") as fh:
            assert fh.read() == "new"


def t_install_ui_app_bundle_overwrites_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
        _write(os.path.join(src, "iro-ui.app", "Contents", "MacOS", "iro-ui"), "new")
        _write(os.path.join(tgt, "iro-ui.app", "Contents", "MacOS", "iro-ui"), "old")
        dst = m.install_ui(src, tgt, "darwin")
        assert dst == os.path.join(tgt, "iro-ui.app")
        assert os.path.isdir(dst)
        inner = os.path.join(dst, "Contents", "MacOS", "iro-ui")
        with open(inner, encoding="utf-8") as fh:
            assert fh.read() == "new"
        assert not os.path.exists(os.path.join(src, "iro-ui.app"))


def t_install_ui_missing_returns_none():
    import tempfile
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
        assert m.install_ui(src, tgt, "linux") is None
        assert os.listdir(tgt) == []


# --- classify_tag: install exactly one named release (no semver compare) -------
TAGREL = {"tag_name": "preview-pr-42",
          "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/m"},
                     {"name": "iro-windows.zip", "browser_download_url": "https://x/w"}]}


def t_classify_tag_install_when_asset_present():
    assert m.classify_tag(TAGREL, "darwin") == ("install", "preview-pr-42", "https://x/m")
    assert m.classify_tag(TAGREL, "win32") == ("install", "preview-pr-42", "https://x/w")


def t_classify_tag_building_when_platform_asset_missing():
    assert m.classify_tag(TAGREL, "linux") == ("building", "preview-pr-42", None)


def t_classify_tag_error_on_missing_tag():
    assert m.classify_tag({"assets": []}, "darwin")[0] == "error"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
