#!/usr/bin/env python3
"""Stdlib unit checks for preflight.py. Run: python3 tests/test_preflight.py"""
import importlib.util, os, socket, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# preflight.py imports its sibling `services` (external_tool_env); in production
# scripts/ is always on sys.path for it, so mirror that for the loader.
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
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


def t_no_window_kwargs_per_os():
    # CREATE_NO_WINDOW only on Windows; a no-op (empty kwargs) everywhere else so
    # the same call site stays cross-platform (mirrors services.no_window_kwargs).
    assert m.no_window_kwargs("nt") == {"creationflags": 0x08000000}
    assert m.no_window_kwargs("posix") == {}
    assert m.no_window_kwargs("java") == {}


def t_tool_version_hides_console_window():
    # tool_version() runs in-process inside the console-less racecast-ui.exe
    # (the `tools`/`preflight` status providers), so its `<tool> --version` probe
    # MUST carry CREATE_NO_WINDOW or it flashes a terminal per tool on Windows
    # (issue #23's class, missed for the --version probes). capture_output keeps
    # the version text, so the flag is safe.
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"], captured["kw"] = argv, kw
        return _Result("ffmpeg version 6.0\nbuilt with…", "")

    out = m.tool_version("ffmpeg", run=fake_run, which=lambda n: "/x/ffmpeg")
    assert out == "ffmpeg version 6.0"
    assert captured["argv"] == ["ffmpeg", "--version"]
    for k, v in m.no_window_kwargs().items():   # whatever this OS resolves to
        assert captured["kw"].get(k) == v
    # the probe carries a sanitized env so a frozen binary's bundled libs don't
    # leak into the system-linked tool (the OPENSSL_3.3.0 / libcrypto crash).
    assert "env" in captured["kw"]
    assert captured["kw"]["env"] == m.external_tool_env()


class _Result:
    def __init__(self, stdout, stderr):
        self.stdout, self.stderr = stdout, stderr


def t_resolve_cookies_overrides():
    assert m.resolve_cookies_path("/x/scripts/preflight.py", None,
                                  "/c/cookies.txt") == "/c/cookies.txt"
    assert m.resolve_cookies_path("/x/scripts/preflight.py", "/run",
                                  None) == os.path.join("/run", "yt-cookies.txt")


def t_resolve_cookies_legacy_fallback():
    """runtime-dir with only cookies.txt (not yet migrated) resolves to it."""
    with tempfile.TemporaryDirectory() as d:
        legacy = os.path.join(d, "cookies.txt")
        open(legacy, "w").close()
        result = m.resolve_cookies_path("/x/scripts/preflight.py", d, None)
        assert result == legacy, f"expected legacy fallback, got {result!r}"


def t_resolve_cookies_prefers_yt_over_legacy():
    """runtime-dir with both yt-cookies.txt and cookies.txt resolves to yt-cookies.txt."""
    with tempfile.TemporaryDirectory() as d:
        yt_ck = os.path.join(d, "yt-cookies.txt")
        legacy = os.path.join(d, "cookies.txt")
        open(yt_ck, "w").close()
        open(legacy, "w").close()
        result = m.resolve_cookies_path("/x/scripts/preflight.py", d, None)
        assert result == yt_ck, f"expected yt-cookies.txt preferred, got {result!r}"


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
    assert "racecast install-apps" in by["Discord"].detail


def t_apps_section_web_discord_is_info():
    # Web-variant host: native Discord absent is informational, not a WARN.
    rs = m.apps_section(lambda app: False, web=True)
    disc = [r for r in rs if r.name == "Discord"][0]
    assert disc.level == "INFO" and "Discord-web" in disc.detail
    # The other apps still WARN/FAIL as before when absent.
    obs = [r for r in rs if r.name == "OBS Studio"][0]
    assert obs.level == "FAIL"


def t_install_apps_module_loads():
    ia = m._install_apps_module(os.path.join(ROOT, "src", "scripts"))
    assert callable(ia.app_present)


def t_classify_sheet_no_id_warns():
    r = m.classify_sheet(None)
    assert r.level == "WARN"
    assert "RACECAST_SHEET_ID" in r.detail


def t_classify_sheet_generic_error_fails_with_sharing_and_network_hint():
    r = m.classify_sheet("SHEET_ID", "error", "ValueError: boom")
    assert r.level == "FAIL"
    assert "Anyone with the link" in r.detail and "network" in r.detail


def t_classify_sheet_network_warns_without_sharing_blame():
    # Regression: a timeout is a NETWORK problem, not a sharing one — don't tell
    # the operator to fix sharing that was never broken.
    r = m.classify_sheet("SHEET_ID", "network", "the read operation timed out")
    assert r.level == "WARN"
    assert "Anyone with the link" not in r.detail
    assert "network" in r.detail.lower()


def t_classify_sheet_forbidden_fails_with_sharing_hint():
    r = m.classify_sheet("SHEET_ID", "forbidden", "HTTP 403")
    assert r.level == "FAIL"
    assert "Anyone with the link" in r.detail


def t_classify_sheet_not_found_fails_with_wrong_id_hint():
    r = m.classify_sheet("SHEET_ID", "not_found", "HTTP 404")
    assert r.level == "FAIL"
    assert "Sheet ID" in r.detail


def t_fetch_sheet_csv_timeout_maps_to_network():
    # The exact user-reported failure: urlopen raises TimeoutError. It must become
    # a 'network' outcome (WARN, no sharing blame), not the generic sharing FAIL.
    def boom(*a, **k):
        raise TimeoutError("The read operation timed out")
    orig = m.urlopen
    m.urlopen = boom
    try:
        kind, payload = m.fetch_sheet_csv("SHEET_ID")
    finally:
        m.urlopen = orig
    assert kind == "network"
    assert m.classify_sheet("SHEET_ID", kind, payload).level == "WARN"


def t_fetch_sheet_csv_http_403_maps_to_forbidden():
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    orig = m.urlopen
    m.urlopen = boom
    try:
        kind, _payload = m.fetch_sheet_csv("SHEET_ID")
    finally:
        m.urlopen = orig
    assert kind == "forbidden"


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


def t_speedtest_max_age_env(monkeypatch=None):
    import os
    os.environ.pop("RACECAST_SPEEDTEST_MAX_AGE_DAYS", None)
    assert m._speedtest_max_age() == 7.0                 # default
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "3"
    assert m._speedtest_max_age() == 3.0
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "junk"
    assert m._speedtest_max_age() == 7.0                 # bad value -> default
    os.environ["RACECAST_SPEEDTEST_MAX_AGE_DAYS"] = "-1"
    assert m._speedtest_max_age() == 7.0                 # non-positive -> default
    os.environ.pop("RACECAST_SPEEDTEST_MAX_AGE_DAYS", None)


def t_network_section_has_bandwidth_and_advisory():
    import tempfile
    sections = dict(m.gather(m.__file__, runtime_dir=tempfile.mkdtemp()))
    net = sections["Network"]
    # first entry is the measured/INFO bandwidth result, advisory remains last
    assert net[0].name == "bandwidth"
    assert any("wired connection" in r.detail for r in net)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
