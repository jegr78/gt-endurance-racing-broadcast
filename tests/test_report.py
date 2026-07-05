#!/usr/bin/env python3
"""Integration checks for the `racecast report` CLI (generate + send)."""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load("racecast", ("src", "racecast.py"))
hs = _load("health_store", ("src", "scripts", "health_store.py"))


def _seed_db(path):
    conn = hs.open_db(path)
    hs.migrate(conn)
    now = 1_700_000_000.0
    for i in range(4):
        hs.record(conn, {"ts": now + i * 30, "health_level": "green",
                         "feed_a_down": 0, "feed_b_down": 0, "live_stint": 1,
                         "health_reasons": []}, "periodic")
    conn.close()


def t_generate_writes_file(monkeypatch=None):
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "health-history.db")
        _seed_db(db)
        reports = os.path.join(d, "reports")
        orig_db, orig_dir = rc._health_db_path, rc._runtime_dir
        orig_map, orig_title = rc._report_name_map, rc._report_event_title
        rc._health_db_path = lambda: db
        rc._runtime_dir = lambda: d
        rc._report_name_map = lambda: {1: "Alice"}
        rc._report_event_title = lambda: "Unit Event"
        try:
            rc.report_cmd(["generate"])
        finally:
            rc._health_db_path, rc._runtime_dir = orig_db, orig_dir
            rc._report_name_map, rc._report_event_title = orig_map, orig_title
        files = os.listdir(reports)
        assert files and files[0].endswith(".html"), files
        with open(os.path.join(reports, files[0]), encoding="utf-8") as fh:
            html = fh.read()
        assert "Unit Event" in html and "Alice" in html


def t_generate_no_data_exits():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "health-history.db")
        conn = hs.open_db(db); hs.migrate(conn); conn.close()   # empty DB
        orig_db, orig_dir = rc._health_db_path, rc._runtime_dir
        rc._health_db_path = lambda: db
        rc._runtime_dir = lambda: d
        try:
            raised = False
            try:
                rc.report_cmd(["generate"])
            except SystemExit:
                raised = True
            assert raised, "expected SystemExit on empty DB"
        finally:
            rc._health_db_path, rc._runtime_dir = orig_db, orig_dir


def t_send_no_webhook_exits():
    with tempfile.TemporaryDirectory() as d:
        reports = os.path.join(d, "reports")
        os.makedirs(reports)
        p = os.path.join(reports, "2026-07-01-x.html")
        with open(p, "w") as fh:
            fh.write("<!doctype html><html></html>")
        orig_dir, orig_hook = rc._runtime_dir, rc._active_discord_webhook
        rc._runtime_dir = lambda: d
        rc._active_discord_webhook = lambda: ("", "")
        try:
            raised = False
            try:
                rc.report_cmd(["send"])
            except SystemExit:
                raised = True
            assert raised, "expected SystemExit when no webhook configured"
        finally:
            rc._runtime_dir, rc._active_discord_webhook = orig_dir, orig_hook


def t_send_posts_multipart():
    with tempfile.TemporaryDirectory() as d:
        reports = os.path.join(d, "reports")
        os.makedirs(reports)
        p = os.path.join(reports, "2026-07-01-x.html")
        with open(p, "w") as fh:
            fh.write("<!doctype html><html>hi</html>")
        sent = {}

        def _fake_post(url, fields=None, files=None, **kw):
            sent["url"] = url
            sent["fields"] = fields
            sent["files"] = files
            return b"ok"

        orig_dir = rc._runtime_dir
        orig_hook = rc._active_discord_webhook
        orig_post = rc.http_util.post_multipart
        rc._runtime_dir = lambda: d
        rc._active_discord_webhook = lambda: ("https://discord.invalid/webhook", "My League")
        rc.http_util.post_multipart = _fake_post
        try:
            rc.report_cmd(["send"])
        finally:
            rc._runtime_dir = orig_dir
            rc._active_discord_webhook = orig_hook
            rc.http_util.post_multipart = orig_post
        assert sent["url"] == "https://discord.invalid/webhook"
        assert "payload_json" in sent["fields"]
        assert sent["files"][0][1] == "2026-07-01-x.zip"
        assert sent["files"][0][3] == "application/zip"


def t_send_report_embed_zip():
    import io
    import json
    import zipfile

    with tempfile.TemporaryDirectory() as d:
        reports = os.path.join(d, "reports")
        os.makedirs(reports)
        p = os.path.join(reports, "2026-07-01-x.html")
        with open(p, "w") as fh:
            fh.write("<!doctype html><html>hi</html>")
        captured = {}

        def _fake_post(url, fields=None, files=None, **kw):
            captured["fields"] = fields
            captured["files"] = files
            return b"ok"

        orig_hook = rc._active_discord_webhook
        orig_post = rc.http_util.post_multipart
        rc._active_discord_webhook = lambda: ("https://discord.invalid/webhook", "My League")
        rc.http_util.post_multipart = _fake_post
        try:
            rc._send_report_core(p, report={"header": {"uptime_pct": 99.0, "on_air_s": 60,
                "duration_s": 60, "start": 0, "end": 60}, "incidents": []})
        finally:
            rc._active_discord_webhook = orig_hook
            rc.http_util.post_multipart = orig_post

        payload = json.loads(captured["fields"]["payload_json"])
        assert payload["username"] == "GT Racecast"
        assert payload["embeds"][0]["fields"][0]["name"] == "Uptime"
        fname, content, ctype = (captured["files"][0][1], captured["files"][0][2],
                                  captured["files"][0][3])
        assert fname.endswith(".zip") and ctype == "application/zip"
        names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        assert any(n.endswith(".html") for n in names)


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
