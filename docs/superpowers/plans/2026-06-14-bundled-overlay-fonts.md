# Bundled Overlay Fonts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a curated baseline set of overlay fonts inside every OS build and auto-seed it into `runtime/fonts/` on app start, replacing the manual curated-download picker in General Settings.

**Architecture:** A new pure module `src/scripts/fonts_bundle.py` builds a `fonts.zip` (woff2 + manifest with a sha256 stamp) and safely extracts it (stamp-gated, only-if-absent, zip-slip-safe). A maintainer tool `tools/fetch-fonts.py` downloads the curated set (`overlay_build.GOOGLE_FONTS`, the single source of truth) into that zip; `tools/build-binary.py` bundles the zip into both frozen binaries; `racecast._bootstrap()` extracts it on every start (CLI and UI). The General Settings UI loses the curated quick-pick but keeps the free-text Google-font typeahead, the installed-fonts list, and delete.

**Tech Stack:** Python stdlib only (zipfile, hashlib, json, urllib), PyInstaller `--add-data`, vanilla JS in `control-center.html`. Tests are runnable scripts (no pytest); `tools/run-tests.py` auto-discovers `tests/test_*.py`.

---

## File Structure

- **Create** `src/scripts/fonts_bundle.py` — pure zip build/extract/stamp logic (shipped, imported by `racecast.py` and `tools/fetch-fonts.py`).
- **Create** `tools/fetch-fonts.py` — maintainer tool: download the curated set → `fonts.zip`.
- **Create** `tests/test_fonts.py` — unit checks for both of the above.
- **Modify** `src/racecast.py` — `import fonts_bundle as fb`; add `_bundled_fonts_zip()` + `ensure_bundled_fonts()`; call it in `_bootstrap()`; drop the `catalog` field from `machine_fonts_list_data()`.
- **Modify** `tools/build-binary.py` — ensure `fonts.zip` exists before building; `--add-data` it into each binary.
- **Modify** `.gitignore` — ignore the generated `fonts.zip`.
- **Modify** `src/ui/control-center.html` — remove the curated `<select>`/Download row + `downloadLibFont()` + the catalog render path; update the hint text.
- **Modify** `tests/test_bootstrap.py` — add `ensure_bundled_fonts` to the bootstrap-step contract.
- **Modify** `tests/test_racecast.py` — drop the `catalog` assertion.
- **Modify** `tests/test_ui_server.py` — drop `catalog` from the stub + route assertion.
- **Modify** `CLAUDE.md`, `src/docs/wiki/HUD-Overlays.md`, `src/docs/wiki/Control-Center.md` — describe the bundled set.
- **Replace** `src/docs/wiki/images/cc-settings.png` — fresh General Settings screenshot.

---

## Task 1: Pure font-bundle module (`fonts_bundle.py`)

**Files:**
- Create: `src/scripts/fonts_bundle.py`
- Test: `tests/test_fonts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fonts.py` (the `fonts_bundle` portion — the fetch-fonts tests are added in Task 2):

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the bundled overlay-font set: fonts_bundle (zip build +
safe extract + stamp gating) and the tools/fetch-fonts.py assembly logic.
Run: python3 tests/test_fonts.py"""
import importlib.util, json, os, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import fonts_bundle as fb


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
            assert False, "expected ValueError"
        except ValueError:
            pass


def t_missing_zip_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        res = fb.extract_bundled(os.path.join(tmp, "nope.zip"), os.path.join(tmp, "fonts"))
        assert res["skipped"] is True and res["extracted"] == []


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_fonts.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonts_bundle'`.

- [ ] **Step 3: Write the module**

Create `src/scripts/fonts_bundle.py`:

```python
#!/usr/bin/env python3
"""Pure helpers for the bundled overlay-font set: assemble a fonts.zip at build
time and extract it into runtime/fonts/ at app start. No network — fetching the
fonts is the maintainer tool's job (tools/fetch-fonts.py); this module only zips
bytes it is handed and unzips them safely. Stdlib only, unit-tested in
tests/test_fonts.py.

The zip carries a manifest.json {version, fonts:[names], stamp} where stamp is a
sha256 of the sorted font filenames. Extraction is stamp-gated (a marker file
records the last applied stamp, so an unchanged set is a cheap no-op every start),
per-file only-if-absent (never overwrites an operator's own font), and zip-slip
safe (every entry is whitelist- and containment-checked, never a blind extractall).
"""
import hashlib, json, os, zipfile

import overlay_build as ob

MANIFEST_NAME = "manifest.json"
MARKER_NAME = ".bundled.json"


def font_name_ok(name):
    """True for a safe bundled font filename (whitelisted stem + known extension).
    Mirrors racecast._font_name_ok using the shared overlay_build constants."""
    return (isinstance(name, str) and bool(ob.FONT_NAME_RE.match(name))
            and "." in name and name.rsplit(".", 1)[1].lower() in ob.FONT_EXTS)


def compute_stamp(filenames):
    """A deterministic stamp for a font set = sha256 of the sorted filenames."""
    joined = "\n".join(sorted(filenames)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


def build_zip(zip_path, fonts, version="dev"):
    """Write fonts.zip at zip_path from {filename: bytes}. Adds manifest.json with
    {version, fonts:[sorted names], stamp}. Returns the stamp. Rejects unsafe names
    so a bad manifest can never be produced."""
    names = sorted(fonts)
    for n in names:
        if not font_name_ok(n):
            raise ValueError(f"unsafe font filename: {n!r}")
    stamp = compute_stamp(names)
    manifest = {"version": version, "fonts": names, "stamp": stamp}
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)) or ".", exist_ok=True)
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for n in names:
            zf.writestr(n, fonts[n])
    os.replace(tmp, zip_path)
    return stamp


def read_manifest(zip_path):
    """The {version, fonts, stamp} dict from a fonts.zip (None on any problem)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    except Exception:    # not a zip / no manifest -> caller treats as "nothing to do"
        return None


def read_marker(dest):
    """The last-applied stamp recorded in dest/.bundled.json, or None."""
    try:
        with open(os.path.join(dest, MARKER_NAME), encoding="utf-8") as fh:
            return json.load(fh).get("stamp")
    except Exception:    # absent / unreadable -> force a (re)extract
        return None


def extract_bundled(zip_path, dest):
    """Seed dest (runtime/fonts/) from zip_path's bundled font set.

    Stamp-gated: if the marker already records the zip's stamp, returns
    {"skipped": True, "extracted": []} without touching the filesystem. Otherwise
    extracts each font entry that passes font_name_ok + realpath containment and is
    not already present (never overwrites), then writes the marker. Returns
    {"skipped": False, "extracted": [names]}."""
    manifest = read_manifest(zip_path)
    if not manifest:
        return {"skipped": True, "extracted": []}
    stamp = manifest.get("stamp")
    if stamp and read_marker(dest) == stamp:
        return {"skipped": True, "extracted": []}
    os.makedirs(dest, exist_ok=True)
    base = os.path.realpath(dest)
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in manifest.get("fonts", []):
            if not font_name_ok(name):
                continue                          # zip-slip / junk entry -> skip
            target = os.path.realpath(os.path.join(base, name))
            if not target.startswith(base + os.sep):
                continue                          # escaped dest -> skip
            if os.path.exists(target):
                continue                          # never overwrite operator's own
            try:
                data = zf.read(name)
            except KeyError:
                continue                          # listed but missing in the zip
            with open(target + ".tmp", "wb") as fh:
                fh.write(data)
            os.replace(target + ".tmp", target)
            extracted.append(name)
    with open(os.path.join(dest, MARKER_NAME), "w", encoding="utf-8") as fh:
        json.dump({"stamp": stamp}, fh)
    return {"skipped": False, "extracted": extracted}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_fonts.py`
Expected: `ok t_...` for each, then `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/fonts_bundle.py tests/test_fonts.py
git commit -m "feat(fonts): pure fonts.zip build + safe stamp-gated extract"
```

---

## Task 2: Maintainer fetch tool (`tools/fetch-fonts.py`)

**Files:**
- Create: `tools/fetch-fonts.py`
- Modify: `.gitignore`
- Test: `tests/test_fonts.py` (add fetch-fonts cases)

- [ ] **Step 1: Add the failing tests**

In `tests/test_fonts.py`, add the fetch-fonts loader right after the `import fonts_bundle as fb` line:

```python
# tools/fetch-fonts.py has a hyphen -> load it by path.
_spec = importlib.util.spec_from_file_location(
    "fetch_fonts", os.path.join(ROOT, "tools", "fetch-fonts.py"))
fetch_fonts = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fetch_fonts)
```

And add these test functions before the `__main__` block:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_fonts.py`
Expected: FAIL — `FileNotFoundError`/spec load error for `tools/fetch-fonts.py`.

- [ ] **Step 3: Write the tool**

Create `tools/fetch-fonts.py`:

```python
#!/usr/bin/env python3
"""Download the curated overlay-font set and pack it into fonts.zip for bundling.

The set IS overlay_build.GOOGLE_FONTS (the single source of truth, shared with the
Control Center typeahead fallback). Each family is fetched from Google Fonts the
same way the live "add a font" download does: the fixed googleapis css2 endpoint
yields a gstatic .woff2 URL, which is then downloaded. The result is written to
fonts.zip at the repo root (gitignored); tools/build-binary.py bundles that zip
INTO each frozen binary, and racecast.ensure_bundled_fonts() extracts it into
runtime/fonts/ on first start (so every install has the baseline set).

Network dependency: the build (CI included) reaches fonts.googleapis.com +
fonts.gstatic.com. Missing families are skipped with a warning; the build only
fails if NOTHING downloaded.

Maintainer tool — not shipped in the distributable package.

Usage:
  python3 tools/fetch-fonts.py                  # build ./fonts.zip
  python3 tools/fetch-fonts.py --out PATH       # write elsewhere
  python3 tools/fetch-fonts.py --version vX.Y.Z # stamp the manifest version
"""
import argparse, os, re, sys
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import overlay_build as ob
import fonts_bundle as fb

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _http(url, headers=None, binary=False, timeout=30):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:    # noqa: S310 (fixed Google hosts)
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def fetch_family(name, css_fetch=None, bin_fetch=None):
    """Return the woff2 bytes for a Google font family (bold weight first, then the
    family's default face), or None if it yields no gstatic woff2. Fetchers are
    injectable for tests."""
    css_fetch = css_fetch or (lambda u: _http(u, headers={"User-Agent": _UA}))
    bin_fetch = bin_fetch or (lambda u: _http(u, binary=True))
    for url in (ob.google_font_css_url(name), ob.google_font_css_url(name, weight=None)):
        try:
            css = css_fetch(url)
        except Exception:                          # a 400 for a missing weight, etc.
            continue
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css or "")
        if m:
            data = bin_fetch(m.group(1))
            if data:
                return data
    return None


def build(out_path, version="dev", families=None, css_fetch=None, bin_fetch=None):
    """Fetch every family and write the fonts.zip. Returns (stamp, missing[])."""
    families = ob.GOOGLE_FONTS if families is None else families
    fonts, missing = {}, []
    for fam in families:
        data = fetch_family(fam, css_fetch=css_fetch, bin_fetch=bin_fetch)
        if data:
            fonts[ob.google_font_filename(fam)] = data
        else:
            missing.append(fam)
    if not fonts:
        raise SystemExit("fetch-fonts: no fonts downloaded (network?)")
    stamp = fb.build_zip(out_path, fonts, version=version)
    return stamp, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "fonts.zip"))
    ap.add_argument("--version", default="dev")
    a = ap.parse_args()
    stamp, missing = build(a.out, version=a.version)
    print(f"wrote {a.out} (stamp {stamp[:12]}…, "
          f"{len(ob.GOOGLE_FONTS) - len(missing)} fonts)")
    if missing:
        print("WARNING: no woff2 for: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ignore the generated zip**

In `.gitignore`, after the `incoming/` line, add:

```
fonts.zip
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_fonts.py`
Expected: `ALL PASS`.

- [ ] **Step 6: Smoke the real download (network)**

Run: `python3 tools/fetch-fonts.py`
Expected: `wrote .../fonts.zip (stamp …, 22 fonts)` and no WARNING (or a short missing-list at most). Confirm `git status` does NOT show `fonts.zip` (it is ignored).

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 8: Commit**

```bash
git add tools/fetch-fonts.py tests/test_fonts.py .gitignore
git commit -m "feat(fonts): maintainer tool to download the curated set into fonts.zip"
```

---

## Task 3: Extract on app start (`racecast._bootstrap`)

**Files:**
- Modify: `src/racecast.py` (add `import fonts_bundle as fb`; `_bundled_fonts_zip()`, `ensure_bundled_fonts()`; call in `_bootstrap`)
- Test: `tests/test_bootstrap.py` (extend the step contract)

- [ ] **Step 1: Update the failing bootstrap-contract test**

In `tests/test_bootstrap.py`, replace the `_BOOTSTRAP_STEPS` list:

```python
_BOOTSTRAP_STEPS = ["_force_utf8_io", "ensure_env_file", "ensure_example_profile",
                    "cleanup_old_binary", "_load_env_frozen", "_ensure_ssl_certs",
                    "_ensure_tool_path", "_apply_active_profile_env"]
```

with:

```python
_BOOTSTRAP_STEPS = ["_force_utf8_io", "ensure_env_file", "ensure_example_profile",
                    "ensure_bundled_fonts", "cleanup_old_binary", "_load_env_frozen",
                    "_ensure_ssl_certs", "_ensure_tool_path", "_apply_active_profile_env"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_bootstrap.py`
Expected: FAIL — `t_bootstrap_runs_every_startup_step_in_order` reports `ensure_bundled_fonts` missing from `calls` (it isn't called yet; the stub setter also raises `AttributeError` if the attr is absent — both confirm the step doesn't exist).

- [ ] **Step 3: Add the import**

In `src/racecast.py`, find line 41 (`import overlay_build as ob`) and add directly below it:

```python
import fonts_bundle as fb
```

- [ ] **Step 4: Add the helper functions**

In `src/racecast.py`, after `ensure_example_profile()` ends (the `return True` near line 286, before `def cleanup_old_binary`), insert:

```python
def _bundled_fonts_zip():
    """Path of the fonts.zip carrying the curated overlay-font set: bundled inside
    the frozen binary (_MEIPASS/fonts.zip) or at the repo root in dev. None when
    absent (e.g. a dev who never ran tools/fetch-fonts.py)."""
    if IS_FROZEN:
        p = os.path.join(getattr(sys, "_MEIPASS", ""), "fonts.zip")
    else:
        p = os.path.join(os.path.dirname(HERE), "fonts.zip")
    return p if os.path.isfile(p) else None


def ensure_bundled_fonts():
    """Seed the machine-wide overlay font library (runtime/fonts/) from the bundled
    fonts.zip on start, so every install has the curated baseline set without a
    manual download. Stamp-gated + only-if-absent + zip-slip-safe (see
    fonts_bundle.extract_bundled); fully best-effort. Returns True iff anything was
    extracted."""
    zip_path = _bundled_fonts_zip()
    if not zip_path:
        return False
    try:
        res = fb.extract_bundled(zip_path, _machine_fonts_dir())
    except Exception as exc:
        print(f"warning: could not seed bundled fonts ({exc}).", file=sys.stderr)
        return False
    if res.get("extracted"):
        print(f"seeded {len(res['extracted'])} overlay font(s) into runtime/fonts/.",
              file=sys.stderr)
        return True
    return False
```

(`_machine_fonts_dir` is defined later in the file; that is fine — it resolves at call time.)

- [ ] **Step 5: Call it in `_bootstrap`**

In `src/racecast.py`, in `_bootstrap()`, find:

```python
    ensure_example_profile(home)   # seed profiles/example so `profile new` works (#45)
```

and add directly below it:

```python
    ensure_bundled_fonts()         # seed runtime/fonts/ from the bundled curated set (#bundled-fonts)
```

- [ ] **Step 6: Run the bootstrap test to verify it passes**

Run: `python3 tests/test_bootstrap.py`
Expected: `ALL PASS`.

- [ ] **Step 7: Verify extraction end-to-end (dev)**

Run (after Task 2 created a real `fonts.zip` at the repo root):

```bash
rm -rf runtime/fonts && python3 src/racecast.py status >/dev/null; ls runtime/fonts | head
```

Expected: stderr shows `seeded N overlay font(s)…` on the first run; `runtime/fonts/` contains the curated `.woff2` files + `.bundled.json`. Run the same command again — no "seeded" line the second time (stamp-gated).

- [ ] **Step 8: Lint**

Run: `python3 tools/lint.py`
Expected: no new findings.

- [ ] **Step 9: Commit**

```bash
git add src/racecast.py tests/test_bootstrap.py
git commit -m "feat(fonts): extract bundled font set into runtime/fonts on start"
```

---

## Task 4: Drop the curated `catalog` from the data layer

**Files:**
- Modify: `src/racecast.py` (`machine_fonts_list_data`)
- Test: `tests/test_racecast.py`, `tests/test_ui_server.py`

- [ ] **Step 1: Update the failing tests**

In `tests/test_racecast.py`, find (around line 1154):

```python
        assert "Oswald.woff2" in lib["fonts"] and "Oswald" in lib["catalog"]
```

replace with:

```python
        assert "Oswald.woff2" in lib["fonts"] and "catalog" not in lib
```

In `tests/test_ui_server.py`, find (around line 151-152) in the `_ctx()` stub:

```python
            "machine_fonts": lambda: {"ok": True, "fonts": ["Oswald.woff2"],
                                      "catalog": ["Oswald", "Roboto"]},
```

replace with:

```python
            "machine_fonts": lambda: {"ok": True, "fonts": ["Oswald.woff2"]},
```

In `tests/test_ui_server.py`, find (around line 1105) in `t_font_library_list_route`:

```python
        assert code == 200 and "Oswald" in data["catalog"]
        assert "Oswald.woff2" in data["fonts"]
```

replace with:

```python
        assert code == 200 and "catalog" not in data
        assert "Oswald.woff2" in data["fonts"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 tests/test_racecast.py` then `python3 tests/test_ui_server.py`
Expected: `test_racecast` FAILS at `t_machine_font_download_into_library` (`catalog` still present → `"catalog" not in lib` is False).

- [ ] **Step 3: Drop the field**

In `src/racecast.py`, in `machine_fonts_list_data()` (around line 2626-2631), replace:

```python
def machine_fonts_list_data():
    """The machine-wide font library + the curated catalog available to add.
    Machine-scoped (no active profile needed). {ok, fonts, catalog}."""
    try:
        return {"ok": True, "fonts": _list_fonts(_machine_fonts_dir()),
                "catalog": list(ob.GOOGLE_FONTS)}
    except Exception as exc:
        return {"ok": False, "error": f"could not list fonts: {exc}"}
```

with:

```python
def machine_fonts_list_data():
    """The machine-wide font library (runtime/fonts/), pre-seeded from the bundled
    curated set and extendable via the Settings typeahead. Machine-scoped (no active
    profile needed). {ok, fonts}."""
    try:
        return {"ok": True, "fonts": _list_fonts(_machine_fonts_dir())}
    except Exception as exc:
        return {"ok": False, "error": f"could not list fonts: {exc}"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_racecast.py` then `python3 tests/test_ui_server.py`
Expected: `ALL PASS` for both. (`/api/fonts/catalog` typeahead tests are untouched and still pass.)

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py tests/test_ui_server.py
git commit -m "refactor(fonts): drop curated catalog from /api/fonts (bundled now)"
```

---

## Task 5: Bundle `fonts.zip` into the binaries (`build-binary.py`)

**Files:**
- Modify: `tools/build-binary.py`

This task has no unit test (it drives PyInstaller); it is verified by the binary build + smoke test in Task 8.

- [ ] **Step 1: Ensure `fonts.zip` exists before building**

In `tools/build-binary.py`, in `main()`, find:

```python
    sep = ";" if os.name == "nt" else ":"
    rc_bin = build_target(launcher, workdir, version_file, sep,
                           "racecast.py", "racecast", windowed=False)
```

and insert the fonts-fetch block directly above the `rc_bin = ...` line:

```python
    sep = ";" if os.name == "nt" else ":"
    fonts_zip = os.path.join(ROOT, "fonts.zip")
    if not os.path.isfile(fonts_zip):
        print("fonts.zip missing — fetching the curated overlay-font set…", flush=True)
        if subprocess.call([sys.executable, os.path.join(ROOT, "tools", "fetch-fonts.py"),
                            "--version", a.version]) != 0:
            sys.exit("fetch-fonts failed (network?) — cannot bundle overlay fonts.")
    rc_bin = build_target(launcher, workdir, version_file, sep,
                           "racecast.py", "racecast", windowed=False)
```

- [ ] **Step 2: Add `--add-data` for the zip**

In `tools/build-binary.py`, in `build_target()`, find the `profiles/example` add-data block (around line 107-113):

```python
    cmd += ["--add-data",
            f"{os.path.join(ROOT, 'profiles', 'example')}{sep}profiles/example"]
    cmd.append(os.path.join(SRC, entry))
```

and insert the fonts.zip block between them:

```python
    cmd += ["--add-data",
            f"{os.path.join(ROOT, 'profiles', 'example')}{sep}profiles/example"]
    # fonts.zip carries the curated overlay-font set; racecast.ensure_bundled_fonts()
    # extracts it into runtime/fonts/ on first start. Bundled to the _MEIPASS root,
    # so it travels INSIDE the binary and survives `racecast update` (binary-only swap).
    fonts_zip = os.path.join(ROOT, "fonts.zip")
    if os.path.isfile(fonts_zip):
        cmd += ["--add-data", f"{fonts_zip}{sep}."]
    cmd.append(os.path.join(SRC, entry))
```

- [ ] **Step 3: Commit**

```bash
git add tools/build-binary.py
git commit -m "build(fonts): fetch + bundle fonts.zip into the frozen binaries"
```

---

## Task 6: Remove the curated picker from General Settings (`control-center.html`)

**Files:**
- Modify: `src/ui/control-center.html`

This is UI markup/JS; verified by Task 8's full suite (`test_ui_server` covers the routes) and the manual screenshot in Task 7.

- [ ] **Step 1: Remove the curated `<select>` + Download row**

In `src/ui/control-center.html`, find:

```html
          <div class="row">
            <span class="name">Add font</span>
            <select id="font-catalog" aria-label="Google font to add" style="flex:1"></select>
            <button id="font-add" onclick="downloadLibFont()">
              <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download</button></div>
          <div class="row">
            <span class="name">Other font</span>
            <input id="font-custom" style="flex:1" aria-label="Any Google font family name"
```

replace with (drops the curated row, renames the typeahead row's label to "Add font"):

```html
          <div class="row">
            <span class="name">Add font</span>
            <input id="font-custom" style="flex:1" aria-label="Any Google font family name"
```

- [ ] **Step 2: Remove the catalog render path in `loadFontLibrary()`**

In `src/ui/control-center.html`, find:

```javascript
  if (!d.ok) { showFontErr(d.error || 'could not list font library'); return; }
  const have = (d.fonts || []).map(n => n.replace(/[^A-Za-z0-9]/g, '').toLowerCase());
  const sel = $('font-catalog'); sel.textContent = '';
  const pending = (d.catalog || []).filter(
    n => have.indexOf(n.replace(/[^A-Za-z0-9]/g, '').toLowerCase()) < 0);
  if (!pending.length) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = 'All catalog fonts downloaded'; sel.appendChild(o);
  }
  pending.forEach(n => {
    const o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o);
  });
  $('font-add').disabled = !pending.length;
  ovInjectDocFonts(d.fonts || []);             // so each row can preview in its own font
```

replace with:

```javascript
  if (!d.ok) { showFontErr(d.error || 'could not list font library'); return; }
  ovInjectDocFonts(d.fonts || []);             // so each row can preview in its own font
```

- [ ] **Step 3: Delete the `downloadLibFont()` function**

In `src/ui/control-center.html`, find and DELETE this entire function (leave `downloadCustomFont` and `deleteLibFont` intact):

```javascript
async function downloadLibFont() {
  const name = $('font-catalog').value;
  if (!name) return;
  $('font-err').hidden = true;
  const b = $('font-add'); b.disabled = true;
  const orig = b.innerHTML; b.textContent = 'Downloading…';
  let d;
  try {
    d = await (await fetch('/api/fonts/download', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})})).json();
  } catch (e) { showFontErr('Control Center not reachable.'); }
  b.innerHTML = orig; b.disabled = false;
  if (d && !d.ok) { showFontErr(d.error || 'download failed'); return; }
  loadFontLibrary();
}
```

- [ ] **Step 4: Update the hint text**

In `src/ui/control-center.html`, find:

```html
          <p class="envhint">Free Google Fonts, downloaded once into <b>runtime/fonts/</b> and offered in the
            Overlay Builder's font pickers. When a league's design uses one, it is copied into that
            league's <b>overlay/fonts/</b> on save, so the overlay works offline and
            <b>profile export</b> stays self-contained. Fetched from Google Fonts.</p>
```

replace with:

```html
          <p class="envhint">A curated set of free Google Fonts ships with every install and is offered in the
            Overlay Builder's font pickers. Add any other family by name above — it is downloaded once into
            <b>runtime/fonts/</b>. When a league's design uses a font, it is copied into that league's
            <b>overlay/fonts/</b> on save, so the overlay works offline and <b>profile export</b> stays self-contained.</p>
```

- [ ] **Step 5: Verify no dangling references**

Run: `grep -n "font-catalog\b\|font-add\b\|downloadLibFont" src/ui/control-center.html`
Expected: only `font-catalog-all` (the typeahead datalist, kept) appears — NO bare `font-catalog`, `font-add`, or `downloadLibFont`.

- [ ] **Step 6: Manual sanity check in the UI**

Run: `python3 src/racecast.py ui` (then open the printed URL → Settings → Overlay fonts). Confirm: the curated dropdown is gone, the "Add font" typeahead works, the installed-fonts list shows the bundled fonts with working Remove + previews, and "Browse Google Fonts ↗" still opens. Stop with Ctrl-C.

- [ ] **Step 7: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): drop curated font picker, keep typeahead + bundled list"
```

---

## Task 7: Docs + wiki screenshot

**Files:**
- Modify: `CLAUDE.md`, `src/docs/wiki/HUD-Overlays.md`, `src/docs/wiki/Control-Center.md`
- Replace: `src/docs/wiki/images/cc-settings.png`

- [ ] **Step 1: Update `CLAUDE.md`**

In `CLAUDE.md`, in the Control Center section, find the General Settings sentence describing the font library:

```
- **General Settings** — machine-wide knobs: the `.env` editor (`RACECAST_*` vars),
  cookie refresh, and the **overlay font library** (curated free Google Fonts downloaded
  once into `runtime/fonts/`, shared across leagues; routes `/api/fonts`,
  `/api/fonts/{download,delete}`). A font a league's design uses is copied into that
  profile's `overlay/fonts/` on save (`_materialize_overlay_fonts`), so `profile export`
  stays self-contained; the relay/canvas serve it locally (no broadcast-time CDN).
```

replace with:

```
- **General Settings** — machine-wide knobs: the `.env` editor (`RACECAST_*` vars),
  cookie refresh, and the **overlay font library** (`runtime/fonts/`, shared across
  leagues). A curated baseline set (`overlay_build.GOOGLE_FONTS`) is downloaded at build
  time into `fonts.zip`, bundled INTO each binary, and extracted into `runtime/fonts/` on
  first start by `ensure_bundled_fonts()` (stamp-gated, only-if-absent, zip-slip-safe — so
  every install has fonts without a manual download, and `racecast update` refreshes the
  set). Operators add further families by name via the Settings typeahead (routes
  `/api/fonts`, `/api/fonts/{catalog,download,delete}`); `tools/fetch-fonts.py` is the
  maintainer tool that builds the zip. A font a league's design uses is copied into that
  profile's `overlay/fonts/` on save (`_materialize_overlay_fonts`), so `profile export`
  stays self-contained; the relay/canvas serve it locally (no broadcast-time CDN).
```

- [ ] **Step 2: Update the wiki HUD-Overlays page**

In `src/docs/wiki/HUD-Overlays.md`, find the paragraph around lines 83-87 describing the curated catalog + the machine-wide library, and replace its substance with:

```markdown
A curated set of broadcast-friendly Google Fonts **ships with every install** and is
offered in the Overlay Builder's font pickers — no download step. To use a family that
is not in the set, type its name in **General Settings → Overlay fonts** (or open the
**Browse Google Fonts** link to find the exact name); it is self-hosted once into the
machine-wide library (`runtime/fonts/`) shared across all leagues — no per-league
re-download. When a league's design uses a font, it is copied into that league's
`overlay/fonts/` on save, so the overlay works offline and **profile export** stays
self-contained.
```

(Keep the surrounding section structure; only the curated-catalog wording changes.)

- [ ] **Step 3: Update the Control-Center wiki page if it lists fonts**

Run: `grep -n "font" src/docs/wiki/Control-Center.md`
If the General Settings section enumerates a "download curated fonts" step, reword it to: a curated set ships pre-installed; add others by name via the typeahead. If fonts are not mentioned there, no change is needed.

- [ ] **Step 4: Regenerate the General Settings screenshot**

There is no automated tool for Control Center screenshots (unlike `companion-screenshots`). Produce it manually via the Playwright MCP against the running Control Center, then crop. Concretely:

1. Ensure fonts are seeded so the section looks populated: `python3 tools/fetch-fonts.py` then `rm -rf runtime/fonts && python3 src/racecast.py status >/dev/null`.
2. Start the UI on a fixed port: `RACECAST_UI_PORT=8899 python3 src/racecast.py ui --no-browser &`
3. With the Playwright MCP: `browser_navigate` to `http://127.0.0.1:8899/`, open the **Settings** view, scroll the **Overlay fonts** section into view, and `browser_take_screenshot` (capture the General Settings view including the new font section).
4. Crop/resize to match the other `cc-*.png` (open `src/docs/wiki/images/cc-overlay-builder.png` to gauge the target width) and save as `src/docs/wiki/images/cc-settings.png`, overwriting the old file.
5. Stop the UI (`kill %1`).

- [ ] **Step 5: Verify the screenshot is in place**

Run: `git status --short src/docs/wiki/images/cc-settings.png`
Expected: the file shows as modified. Open it (Read tool) and confirm it shows the General Settings view with the new "Overlay fonts" section (no curated dropdown, the typeahead "Add font" row, the installed-fonts list).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md src/docs/wiki/HUD-Overlays.md src/docs/wiki/Control-Center.md src/docs/wiki/images/cc-settings.png
git commit -m "docs(fonts): document bundled font set + refresh General Settings screenshot"
```

> **Publishing the wiki** (after merge, maintainer): `python3 tools/sync-wiki.py` mirrors `src/docs/wiki/` to the GitHub wiki. Optionally verify with the `wiki-visual-test` skill. This is NOT part of the PR.

---

## Task 8: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: every `tests/test_*.py` passes, including the new `tests/test_fonts.py`.

- [ ] **Step 2: Lint the whole repo**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build + self-verify the distributable**

Run: `python3 tools/build.py`
Expected: the verify step passes (tokenization, blanked password, no secrets, no shell scripts). Note: `tools/build.py` assembles the producer ZIP from `src/`; it does not bundle `fonts.zip` (that is a binary-only artifact) — confirm it still passes.

- [ ] **Step 4: Build + smoke the binary (bundles fonts.zip)**

Run: `python3 tools/build-binary.py --version dev`
Expected: it fetches `fonts.zip` (if absent), builds `racecast` + `racecast-ui`, and both smoke tests pass. The `status` smoke run also exercises `ensure_bundled_fonts()` extracting into the binary's sibling `runtime/fonts/`.

- [ ] **Step 5: Confirm `fonts.zip` is not tracked**

Run: `git status --short`
Expected: no `fonts.zip` entry (it is gitignored). Only the intended source/doc changes from earlier tasks are present (and already committed).

- [ ] **Step 6: Final commit (if anything was left staged)**

Only if Step 1-5 surfaced a fix:

```bash
git add -A
git commit -m "chore(fonts): finalize bundled overlay fonts"
```

---

## Notes for the implementer

- **TDD order matters.** Tasks 1-4 are test-first. Tasks 5-7 (PyInstaller, UI markup, docs/screenshot) are verified by build/smoke/grep/visual checks, not unit tests — that is intentional, not a gap.
- **Anti-drift:** `overlay_build.GOOGLE_FONTS` stays the ONE list of curated families (build manifest + typeahead fallback). Do not introduce a second list in `fonts_bundle.py` or `fetch-fonts.py`.
- **Security:** never `extractall` the zip; `extract_bundled` only reads manifest-listed names that pass `font_name_ok` + realpath containment. The `t_extract_rejects_zip_slip` test guards this.
- **`racecast update` semantics:** the zip lives inside the binary, so an update brings a new set; existing files are never overwritten, but a new stamp re-seeds any deleted baseline fonts. This is the intended "always-available baseline" behavior.
```
