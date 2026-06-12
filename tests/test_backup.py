#!/usr/bin/env python3
"""Stdlib unit checks for profile look backups (overlay+graphics+media zips).
Run: python3 tests/test_backup.py"""
import importlib.util, os, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "backup_admin", os.path.join(ROOT, "src", "scripts", "backup_admin.py"))
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)


def _sources(d):
    """Make a fake profile look: overlay/ + graphics/ + media/ with one file each."""
    overlay = os.path.join(d, "profiles", "x", "overlay")
    graphics = os.path.join(d, "runtime", "x", "graphics")
    media = os.path.join(d, "runtime", "x", "media")
    for sub in (overlay, graphics, media):
        os.makedirs(sub, exist_ok=True)
    with open(os.path.join(overlay, "hud.css"), "w") as f:
        f.write("body{}")
    with open(os.path.join(graphics, "Overlay.png"), "wb") as f:
        f.write(b"PNG")
    with open(os.path.join(media, "Intro.mp4"), "wb") as f:
        f.write(b"MP4")
    return {"overlay": overlay, "graphics": graphics, "media": media,
            "backups": os.path.join(d, "runtime", "x", "backups")}


def t_label_sanitize():
    assert ba.sanitize_label("Winter Theme!") == "winter-theme"
    assert ba.sanitize_label("  v2 2026 ") == "v2-2026"
    try:
        ba.sanitize_label("***"); raise AssertionError()
    except ValueError:
        pass


def t_create_writes_zip_with_manifest():
    d = tempfile.mkdtemp(); src = _sources(d)
    path = ba.create_backup("Winter Theme", src, profile="x")
    assert path.endswith(os.path.join("backups", "winter-theme.zip"))
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert "manifest.json" in names
        assert "overlay/hud.css" in names
        assert "graphics/Overlay.png" in names
        assert "media/Intro.mp4" in names
        import json
        man = json.loads(z.read("manifest.json"))
        assert man["label"] == "Winter Theme" and man["profile"] == "x"


def t_create_duplicate_needs_force():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("dup", src, profile="x")
    try:
        ba.create_backup("dup", src, profile="x"); raise AssertionError()
    except FileExistsError:
        pass
    ba.create_backup("dup", src, profile="x", force=True)   # ok


def t_list_reads_manifests():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("Alpha", src, profile="x")
    ba.create_backup("Beta", src, profile="x")
    items = ba.list_backups(src["backups"])
    labels = sorted(i["label"] for i in items)
    assert labels == ["Alpha", "Beta"], labels
    assert all("created" in i and "bytes" in i and i["slug"] for i in items)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
