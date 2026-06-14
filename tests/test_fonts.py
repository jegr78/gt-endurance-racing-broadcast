#!/usr/bin/env python3
"""Stdlib unit checks for the bundled overlay-font set: fonts_bundle (zip build +
safe extract + stamp gating) and the tools/fetch-fonts.py assembly logic.
Run: python3 tests/test_fonts.py"""
import importlib.util, json, os, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import fonts_bundle as fb

# tools/fetch-fonts.py has a hyphen -> load it by path.
_spec = importlib.util.spec_from_file_location(
    "fetch_fonts", os.path.join(ROOT, "tools", "fetch-fonts.py"))
fetch_fonts = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fetch_fonts)


def t_compute_stamp_is_order_independent():
    assert fb.compute_stamp(["B.woff2", "A.woff2"]) == fb.compute_stamp(["A.woff2", "B.woff2"])
    assert fb.compute_stamp(["A.woff2"]) != fb.compute_stamp(["B.woff2"])


def t_build_and_extract_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "fonts.zip")
        stamp = fb.build_zip(zp, {"Oswald.woff2": b"AAA", "Teko.woff2": b"BBB"}, version="v1")
        dest = os.path.join(tmp, "fonts")
        res = fb.extract_bundled(zp, dest)
        assert res["skipped"] is False
        assert sorted(res["extracted"]) == ["Oswald.woff2", "Teko.woff2"]
        with open(os.path.join(dest, "Oswald.woff2"), "rb") as fh:
            assert fh.read() == b"AAA"
        assert fb.read_marker(dest) == stamp


def t_extract_is_stamp_gated():
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "fonts.zip")
        fb.build_zip(zp, {"Oswald.woff2": b"AAA"})
        dest = os.path.join(tmp, "fonts")
        assert fb.extract_bundled(zp, dest)["skipped"] is False
        res2 = fb.extract_bundled(zp, dest)
        assert res2["skipped"] is True and res2["extracted"] == []


def t_extract_never_overwrites_existing():
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "fonts.zip")
        fb.build_zip(zp, {"Oswald.woff2": b"NEW"})
        dest = os.path.join(tmp, "fonts"); os.makedirs(dest)
        with open(os.path.join(dest, "Oswald.woff2"), "wb") as fh:
            fh.write(b"MINE")
        res = fb.extract_bundled(zp, dest)
        assert "Oswald.woff2" not in res["extracted"]
        with open(os.path.join(dest, "Oswald.woff2"), "rb") as fh:
            assert fh.read() == b"MINE"


def t_extract_rejects_zip_slip():
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "fonts.zip")
        bad = "../evil.woff2"
        manifest = {"version": "x", "fonts": [bad], "stamp": fb.compute_stamp([bad])}
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr(fb.MANIFEST_NAME, json.dumps(manifest))
            zf.writestr(bad, b"PWNED")
        dest = os.path.join(tmp, "fonts")
        res = fb.extract_bundled(zp, dest)
        assert res["extracted"] == []
        assert not os.path.exists(os.path.join(tmp, "evil.woff2"))


def t_build_zip_rejects_unsafe_name():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            fb.build_zip(os.path.join(tmp, "f.zip"), {"../evil.woff2": b"x"})
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def t_missing_zip_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        res = fb.extract_bundled(os.path.join(tmp, "nope.zip"), os.path.join(tmp, "fonts"))
        assert res["skipped"] is True and res["extracted"] == []


def t_fetch_build_assembles_zip_from_injected_fetchers():
    css = ('@font-face{font-family:X;'
           'src:url(https://fonts.gstatic.com/s/x/v1/a.woff2) format("woff2")}')
    with tempfile.TemporaryDirectory() as tmp:
        zp = os.path.join(tmp, "fonts.zip")
        stamp, missing = fetch_fonts.build(
            zp, version="v9", families=["Oswald", "Saira Condensed"],
            css_fetch=lambda u: css, bin_fetch=lambda u: b"WOFF2")
        assert missing == []
        man = fb.read_manifest(zp)
        assert man["version"] == "v9" and man["stamp"] == stamp
        assert "Oswald.woff2" in man["fonts"] and "SairaCondensed.woff2" in man["fonts"]


def t_fetch_family_returns_none_without_woff2():
    assert fetch_fonts.fetch_family(
        "Nope", css_fetch=lambda u: "no urls here", bin_fetch=lambda u: b"x") is None


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
