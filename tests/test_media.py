#!/usr/bin/env python3
"""Stdlib unit checks for get-media.py. Run: python3 tests/test_media.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "getmedia", os.path.join(ROOT, "src", "relay", "get-media.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_urls_basic():
    rows = [["Intro Video", "https://youtu.be/AAA"],
            ["Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {
        "intro": "https://youtu.be/AAA", "outro": "https://youtu.be/BBB"}, \
        m.media_urls_from_csv(rows)


def t_urls_label_case_and_gap():
    # label match is case/space-insensitive; URL is the next NON-empty cell
    rows = [["  intro video ", "", "https://youtu.be/AAA"]]
    assert m.media_urls_from_csv(rows) == {"intro": "https://youtu.be/AAA"}


def t_urls_label_without_value_omitted():
    rows = [["Intro Video", ""], ["Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {"outro": "https://youtu.be/BBB"}


def t_urls_moved_columns():
    rows = [["foo", "bar", "Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {"outro": "https://youtu.be/BBB"}


def t_urls_empty():
    assert m.media_urls_from_csv([]) == {}


def t_media_dir_repo():
    # expected via os.path.join: separators differ when this test runs on Windows
    got = m.media_dir(os.path.join("/x", "src", "relay"))
    assert got == os.path.join("/x", "runtime", "media"), got


def t_media_dir_pkg():
    got = m.media_dir(os.path.join("/x/GT_Racecast_Package", "relay"))
    assert got == os.path.join("/x/GT_Racecast_Package", "media"), got


def t_resolve_priority_cli_then_env():
    cli = {"intro": "CLI", "outro": None}
    env = {"RACECAST_OUTRO_URL": "ENV"}
    csv_text = "Intro Video,SHEET_I\nOutro Video,SHEET_O\n"
    out = m.resolve_urls({"intro", "outro"}, cli, env, csv_text)
    assert out == {"intro": "CLI", "outro": "ENV"}, out


def t_resolve_sheet_fallback():
    out = m.resolve_urls({"intro"}, {"intro": None}, {}, "Intro Video,SHEET_I\n")
    assert out == {"intro": "SHEET_I"}, out


def t_resolve_missing_is_none():
    out = m.resolve_urls({"intro"}, {"intro": None}, {}, None)
    assert out == {"intro": None}, out


# ---------- download argv separator + scheme guard (sheet arg-injection #3) ----

def t_download_cmd_separates_url():
    cmd = m.build_download_cmd("https://youtu.be/AAA", "/tmp/intro.mp4")
    assert cmd[-2:] == ["--", "https://youtu.be/AAA"], cmd
    assert "-o" in cmd and cmd[cmd.index("-o") + 1] == "/tmp/intro.mp4"
    assert "--cookies" not in cmd


def t_download_cmd_cookies_before_separator():
    import tempfile, os as _os
    fd, ck = tempfile.mkstemp(); _os.close(fd)
    try:
        cmd = m.build_download_cmd("https://youtu.be/AAA", "/tmp/o.mp4", ck)
        assert cmd[-2:] == ["--", "https://youtu.be/AAA"], cmd
        assert cmd.index("--cookies") < cmd.index("--")    # cookies stay an option
    finally:
        _os.unlink(ck)


def t_download_rejects_non_http_url():
    for bad in ("--exec=evil", "file:///etc/passwd", "ftp://x/y", "-o/tmp/x"):
        raised = False
        try:
            m.download(bad, "/tmp/out.mp4")
        except ValueError:
            raised = True
        assert raised, bad


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL PASS")
