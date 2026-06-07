#!/usr/bin/env python3
"""Stdlib unit checks for preflight.py. Run: python3 tests/test_preflight.py"""
import importlib.util, os, socket, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "preflight", os.path.join(ROOT, "src", "scripts", "preflight.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_classify_ram_boundaries():
    # Nominal 16/32 GB modules report ~0.1-1.5 GB lower (firmware/iGPU
    # reservations) — the boundaries carry RAM_SLACK_GB so real machines
    # land in the intended bucket.
    assert m.classify_ram(14.4).level == "FAIL"
    assert m.classify_ram(14.5).level == "WARN"
    assert m.classify_ram(15.9).level == "WARN"   # physical 16 GB machine
    assert m.classify_ram(30.4).level == "WARN"
    assert m.classify_ram(30.5).level == "PASS"
    assert m.classify_ram(31.9).level == "PASS"   # physical 32 GB machine
    assert "browser sources" not in m.classify_ram(20).detail  # stale HUD hint


def t_classify_cpu_boundaries():
    assert m.classify_cpu(5).level == "FAIL"
    assert m.classify_cpu(6).level == "WARN"
    assert m.classify_cpu(7).level == "WARN"
    assert m.classify_cpu(8).level == "PASS"


def t_classify_disk_boundaries():
    assert m.classify_disk(1).level == "FAIL"
    assert m.classify_disk(4).level == "WARN"
    assert m.classify_disk(5).level == "PASS"


def t_classify_swap_boundaries():
    assert m.classify_swap(0.5).level == "PASS"
    assert m.classify_swap(2).level == "WARN"


def t_readers_return_sane_values():
    assert m.read_ram_bytes() > 0
    assert m.disk_free_bytes(".") > 0
    assert m.read_swap_used_bytes() >= 0


def t_port_free_detects_used_and_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.listen(1)
    try:
        assert m.port_free(port) is False
    finally:
        s.close()
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(("127.0.0.1", 0)); free = s2.getsockname()[1]; s2.close()
    assert m.port_free(free) is True


def t_port_reachable():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.listen(1)
    try:
        assert m.port_reachable("127.0.0.1", port) is True
    finally:
        s.close()
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(("127.0.0.1", 0)); closed = s2.getsockname()[1]; s2.close()
    assert m.port_reachable("127.0.0.1", closed, timeout=0.3) is False


def t_tool_version_missing():
    assert m.tool_version("definitely-not-a-real-tool-xyz") is None


def t_resolve_cookies_overrides():
    assert m.resolve_cookies_path("/x/scripts/preflight.py", None,
                                  "/c/cookies.txt") == "/c/cookies.txt"
    assert m.resolve_cookies_path("/x/scripts/preflight.py", "/run",
                                  None) == os.path.join("/run", "cookies.txt")


def t_cookies_missing():
    with tempfile.TemporaryDirectory() as d:
        r = m.cookies_status(os.path.join(d, "nope.txt"))
        assert r.level == "WARN"


def t_cookies_old():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cookies.txt")
        with open(p, "w") as fh:
            fh.write("SAPISID\tval")
        old = time.time() - 20 * 3600
        os.utime(p, (old, old))
        r = m.cookies_status(p)
        assert r.level == "WARN" and "old" in r.detail.lower()


def t_cookies_fresh_with_marker():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cookies.txt")
        with open(p, "w") as fh:
            fh.write("host\tTRUE\t/\tTRUE\t0\tSAPISID\tval")
        r = m.cookies_status(p)
        assert r.level == "PASS"


def t_main_returns_int():
    rc = m.main([])
    assert rc in (0, 1)


def t_apps_section_levels():
    rs = m.apps_section(lambda app: True)
    assert [r.level for r in rs] == ["PASS"] * 4
    rs = m.apps_section(lambda app: False)
    by = {r.name: r for r in rs}
    assert by["OBS Studio"].level == "FAIL"          # no broadcast without OBS
    assert by["Companion"].level == "WARN"
    assert by["Tailscale"].level == "WARN"
    assert by["Discord"].level == "WARN"
    assert "iro install-apps" in by["Discord"].detail


def t_install_apps_module_loads():
    ia = m._install_apps_module(os.path.join(ROOT, "src", "scripts"))
    assert callable(ia.app_present)


def t_classify_sheet_no_id_warns():
    r = m.classify_sheet(None)
    assert r.level == "WARN"
    assert "IRO_SHEET_ID" in r.detail


def t_classify_sheet_fetch_error_fails_with_sharing_hint():
    r = m.classify_sheet("SHEET_ID", "error", "URLError: timed out")
    assert r.level == "FAIL"
    assert "Anyone with the link" in r.detail


def t_classify_sheet_html_body_is_signin_page():
    r = m.classify_sheet("SHEET_ID", "ok", "<HTML><HEAD><TITLE>Sign in</TITLE>")
    assert r.level == "FAIL"
    assert "sign-in" in r.detail


def t_classify_sheet_csv_passes_with_row_count():
    r = m.classify_sheet("SHEET_ID", "ok", '"url","name"\n"https://x","Max"\n')
    assert r.level == "PASS"
    assert "2 row" in r.detail


def t_classify_sheet_empty_csv_fails():
    r = m.classify_sheet("SHEET_ID", "ok", "\n , \n")
    assert r.level == "FAIL"
    assert "empty" in r.detail


def t_classify_sheet_bom_prefixed_html_still_detected():
    r = m.classify_sheet("SHEET_ID", "ok", "﻿<!DOCTYPE html><title>Sign in</title>")
    assert r.level == "FAIL"
    assert "sign-in" in r.detail


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
