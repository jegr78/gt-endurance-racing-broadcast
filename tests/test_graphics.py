#!/usr/bin/env python3
"""Stdlib unit checks for get-graphics.py. Run: python3 tests/test_graphics.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "getgraphics", os.path.join(ROOT, "src", "relay", "get-graphics.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_drive_id_file_form():
    assert m.drive_id("https://drive.google.com/file/d/ABC_123-x/view?usp=sharing") == "ABC_123-x"


def t_drive_id_id_form():
    assert m.drive_id("https://drive.google.com/uc?export=download&id=ZZ9_y") == "ZZ9_y"


def t_drive_id_none():
    assert m.drive_id("https://youtu.be/AAA") is None
    assert m.drive_id("") is None


def t_to_download_url():
    assert m.to_download_url("XYZ") == "https://drive.google.com/uc?export=download&id=XYZ"


def t_safe_filename_basic():
    assert m.safe_filename("Race Results") == "Race Results.png"
    assert m.safe_filename("  Standings ") == "Standings.png"


def t_safe_filename_rejects():
    assert m.safe_filename("") is None
    assert m.safe_filename("a/b") is None
    assert m.safe_filename("a\\b") is None
    assert m.safe_filename("bad\x01") is None


def t_graphics_from_csv_picks_drive_skips_youtube():
    rows = [["Intro Video", "https://youtu.be/AAA"],
            ["Standings", "https://drive.google.com/file/d/SID/view?usp=sharing"],
            ["Schedule", "https://drive.google.com/file/d/SCH/view"]]
    assert m.graphics_from_csv(rows) == {
        "Standings": "https://drive.google.com/file/d/SID/view?usp=sharing",
        "Schedule": "https://drive.google.com/file/d/SCH/view"}, m.graphics_from_csv(rows)


def t_graphics_from_csv_excludes_media_labels():
    # Media rows (handled by get-media.py) must NOT be grabbed as PNG graphics —
    # a Drive-hosted Intermission Music MP3 would otherwise be downloaded as
    # 'Intermission Music.png' and fail the PNG signature check (#368 follow-up).
    # Intro/Outro escape only when YouTube-hosted; a Drive-hosted clip would break too.
    rows = [["Intermission Music", "https://drive.google.com/file/d/MUS/view"],
            ["Intro Video", "https://drive.google.com/file/d/INTRO/view"],
            ["Outro Video", "https://drive.google.com/file/d/OUTRO/view"],
            ["Intermission", "https://drive.google.com/file/d/BG/view"]]
    assert m.graphics_from_csv(rows) == {
        "Intermission": "https://drive.google.com/file/d/BG/view"}, m.graphics_from_csv(rows)


def t_graphics_from_csv_label_verbatim_and_empty():
    rows = [["Race Weather 1", "https://drive.google.com/file/d/W1/view"],
            ["", "https://drive.google.com/file/d/X/view"],
            ["NoUrl", ""]]
    assert m.graphics_from_csv(rows) == {
        "Race Weather 1": "https://drive.google.com/file/d/W1/view"}


def t_graphics_dir_repo():
    # expected via os.path.join: separators differ when this test runs on Windows
    got = m.graphics_dir(os.path.join("/x", "src", "relay"))
    assert got == os.path.join("/x", "runtime", "graphics"), got


def t_graphics_dir_pkg():
    got = m.graphics_dir(os.path.join("/x/GT_Racecast_Package", "relay"))
    assert got == os.path.join("/x/GT_Racecast_Package", "graphics"), got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL PASS")
