#!/usr/bin/env python3
"""Stdlib unit checks for whole-profile export/import bundles.
Run: python3 tests/test_profile_io.py"""
import importlib.util, json, os, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "profile_io", os.path.join(ROOT, "src", "scripts", "profile_io.py"))
pio = importlib.util.module_from_spec(spec); spec.loader.exec_module(pio)


def _profile(d, name="iro-gtec", with_logo=True):
    """A fake profile tree + runtime assets. Returns (sources, roots)."""
    pdir = os.path.join(d, "profiles", name)
    overlay = os.path.join(pdir, "overlay")
    os.makedirs(overlay, exist_ok=True)
    with open(os.path.join(pdir, "profile.env"), "w") as f:
        f.write("NAME=IRO GTEC\nSHEET_ID=abc\nSHEET_PUSH_URL=https://x/exec?key=s\n"
                + ("LOGO=logo.png\n" if with_logo else ""))
    with open(os.path.join(overlay, "hud.css"), "w") as f:
        f.write("body{}")
    if with_logo:
        with open(os.path.join(pdir, "logo.png"), "wb") as f:
            f.write(b"PNG")
    gdir = os.path.join(d, "runtime", name, "graphics")
    mdir = os.path.join(d, "runtime", name, "media")
    os.makedirs(gdir, exist_ok=True); os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(gdir, "Overlay.png"), "wb") as f:
        f.write(b"PNG")
    with open(os.path.join(mdir, "Intro.mp4"), "wb") as f:
        f.write(b"MP4")
    sources = {"profile_dir": pdir, "graphics": gdir, "media": mdir}
    roots = {"profiles_root": os.path.join(d, "profiles"),
             "runtime_root": os.path.join(d, "runtime")}
    return sources, roots


def t_export_with_assets():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    path = pio.export_profile("iro-gtec", sources, include_assets=True, dest=d)
    assert path.endswith("iro-gtec-profile.zip")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        man = json.loads(z.read("manifest.json"))
        assert man["kind"] == "profile-export"
        assert man["includes_assets"] is True
        assert man["display"] == "IRO GTEC"
        assert "profile/profile.env" in names
        assert "profile/overlay/hud.css" in names
        assert "profile/logo.png" in names
        assert "graphics/Overlay.png" in names
        assert "media/Intro.mp4" in names


def t_export_without_assets():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    path = pio.export_profile("iro-gtec", sources, include_assets=False, dest=d)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        man = json.loads(z.read("manifest.json"))
        assert man["includes_assets"] is False
        assert "profile/profile.env" in names
        assert not any(n.startswith("graphics/") for n in names)
        assert not any(n.startswith("media/") for n in names)


def t_export_rejects_missing_env():
    d = tempfile.mkdtemp()
    pdir = os.path.join(d, "profiles", "empty"); os.makedirs(pdir)
    try:
        pio.export_profile("empty", {"profile_dir": pdir}, True, d)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_round_trip():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    bundle = pio.export_profile("iro-gtec", sources, include_assets=True, dest=d)
    e = tempfile.mkdtemp()
    roots = {"profiles_root": os.path.join(e, "profiles"),
             "runtime_root": os.path.join(e, "runtime")}
    info = pio.import_profile(bundle, roots)
    assert info["name"] == "iro-gtec"
    assert info["display"] == "IRO GTEC"
    assert info["includes_assets"] is True
    pdir = os.path.join(e, "profiles", "iro-gtec")
    assert os.path.isfile(os.path.join(pdir, "profile.env"))
    assert os.path.isfile(os.path.join(pdir, "overlay", "hud.css"))
    assert os.path.isfile(os.path.join(pdir, "logo.png"))
    assert os.path.isfile(os.path.join(e, "runtime", "iro-gtec", "graphics", "Overlay.png"))
    assert os.path.isfile(os.path.join(e, "runtime", "iro-gtec", "media", "Intro.mp4"))


def _bundle_with(d, members, manifest=None):
    """Write a hand-built zip with the given {arcname: bytes} members."""
    path = os.path.join(d, "bad.zip")
    with zipfile.ZipFile(path, "w") as z:
        if manifest is not None:
            z.writestr("manifest.json", json.dumps(manifest))
        for arc, data in members.items():
            z.writestr(arc, data)
    return path


def t_import_rejects_wrong_kind():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x"},
                       manifest={"kind": "look-backup", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_missing_env():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/overlay/hud.css": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_traversal():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x", "../evil.txt": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_foreign_top():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x", "secrets/x": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_exists_needs_force():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    bundle = pio.export_profile("iro-gtec", sources, True, d)
    e = tempfile.mkdtemp()
    roots = {"profiles_root": os.path.join(e, "profiles"),
             "runtime_root": os.path.join(e, "runtime")}
    pio.import_profile(bundle, roots)
    try:
        pio.import_profile(bundle, roots)
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass
    pio.import_profile(bundle, roots, force=True)   # replaces, no raise


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print(f"ok {n}")
    print("All profile_io tests passed.")
