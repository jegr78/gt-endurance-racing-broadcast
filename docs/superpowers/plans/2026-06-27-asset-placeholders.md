# Neutral Asset Placeholders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop bundled neutral placeholders (transparent PNG / black 5 s clip) under the expected filenames whenever an OBS-referenced graphic or Intro/Outro clip is missing, so OBS never shows a broken source for assets a league did not provide.

**Architecture:** A pure stdlib helper `src/scripts/placeholders.py` resolves the bundled placeholder paths, extracts the OBS collection's expected graphic basenames, and copies a placeholder into any missing slot. It is wired into the localize step (`setup-assets.py`, the authoritative collection-driven net) and both download steps (`get-graphics.py`, `get-media.py`). The bundled placeholder files live under `src/assets/placeholders/` and ship via the existing `assets` entry in `build-binary.py`'s `DATA` list.

**Tech Stack:** Python 3 stdlib only (`zlib`, `struct`, `shutil`, `re`); `ffmpeg` (maintainer-only, for regenerating the clip); PyInstaller (bundling).

## Global Constraints

- **Edit only under `src/`** (plus `tools/`, `tests/`, `docs/` for this work). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** for all scripts and docs.
- **No new heavy dependency:** the helper is pure stdlib and must **not** import `config.py`. Importing a small pure helper from `src/scripts` (like `overlay_build`, `discord_web`, `services`) is allowed.
- **Best-effort, never raise:** every placeholder fill degrades gracefully (missing bundle / missing template / copy error → today's behavior), exactly like the existing missing-asset warnings.
- **Status unchanged:** do **not** touch `event.py` / `event status` / preflight. A placeholder counts as a present file (silent).
- **Run `python3 tools/lint.py` after changing any Python file** (mirrors the CI lint job); remove imports that become unused.
- Tests are stdlib scripts: each `tests/test_*.py` defines `t_*()` functions and a `__main__` runner `for n, fn in sorted(globals().items()): if n.startswith("t_") and callable(fn): fn()`. No pytest.
- Spec: `docs/superpowers/specs/2026-06-27-asset-placeholders-design.md`.

---

### Task 1: Bundled placeholder assets + regenerator tool

**Files:**
- Create: `tools/make-placeholders.py`
- Create (generated, committed): `src/assets/placeholders/transparent-1080p.png`, `src/assets/placeholders/neutral-5s-1080p.mp4`
- Test: `tests/test_placeholders.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the two committed placeholder files at `src/assets/placeholders/` (consumed by Tasks 2–5) and `tools/make-placeholders.py` (maintainer regenerator).

- [ ] **Step 1: Write the failing test** — create `tests/test_placeholders.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the neutral asset-placeholder helper + bundled assets.
Run: python3 tests/test_placeholders.py"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLACEHOLDERS = os.path.join(ROOT, "src", "assets", "placeholders")
PNG = os.path.join(PLACEHOLDERS, "transparent-1080p.png")
MP4 = os.path.join(PLACEHOLDERS, "neutral-5s-1080p.mp4")


def t_bundled_graphic_is_1080p_rgba_png():
    assert os.path.isfile(PNG), "bundled transparent PNG missing"
    with open(PNG, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    # IHDR is the first chunk: 8-byte sig, 4-byte len, 4-byte 'IHDR', then payload.
    w, h, depth, color = struct.unpack(">IIBB", data[16:26])
    assert (w, h) == (1920, 1080), f"wrong size {(w, h)}"
    assert depth == 8 and color == 6, f"expected 8-bit RGBA, got depth={depth} color={color}"


def t_bundled_media_clip_is_a_small_mp4():
    assert os.path.isfile(MP4), "bundled neutral clip missing"
    with open(MP4, "rb") as fh:
        head = fh.read(12)
    assert head[4:8] == b"ftyp", "not an MP4 (no ftyp box)"
    assert os.path.getsize(MP4) < 2 * 1024 * 1024, "clip unexpectedly large (>2 MB)"


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_placeholders.py`
Expected: FAIL — `AssertionError: bundled transparent PNG missing`.

- [ ] **Step 3: Write the generator tool** — create `tools/make-placeholders.py`:

```python
#!/usr/bin/env python3
"""Generate the bundled neutral placeholder assets for missing broadcast graphics
and Intro/Outro clips. Maintainer tool (not shipped): run it, commit the output.

Outputs (committed product assets, like src/assets/flags/):
  src/assets/placeholders/transparent-1080p.png   fully transparent 1920x1080 RGBA
  src/assets/placeholders/neutral-5s-1080p.mp4     black, silent, 5 s, 1080p H.264

The PNG is built with the stdlib (zlib); the MP4 needs ffmpeg on PATH.

Usage: python3 tools/make-placeholders.py [--width 1920] [--height 1080] [--seconds 5]
"""
import argparse, os, struct, subprocess, sys, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "src", "assets", "placeholders")


def transparent_png_bytes(width, height):
    """A fully transparent (alpha 0) RGBA PNG, encoded with the stdlib."""
    row = b"\x00" * (width * 4)
    raw = bytearray()
    for _ in range(height):
        raw.append(0)            # filter type 0 (None) for the scanline
        raw += row
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


def write_png(path, width, height):
    with open(path, "wb") as fh:
        fh.write(transparent_png_bytes(width, height))
    print(f"OK -> {path} ({os.path.getsize(path)} bytes)")


def write_mp4(path, width, height, seconds):
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", f"color=c=black:s={width}x{height}:d={seconds}:r=30",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryslow",
           "-crf", "30", "-an", path]
    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("ERROR: ffmpeg not found (brew install ffmpeg).")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: ffmpeg failed: {e}")
    print(f"OK -> {path} ({os.path.getsize(path)} bytes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--seconds", type=int, default=5)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    write_png(os.path.join(OUT_DIR, "transparent-1080p.png"), a.width, a.height)
    write_mp4(os.path.join(OUT_DIR, "neutral-5s-1080p.mp4"), a.width, a.height, a.seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the assets**

Run: `python3 tools/make-placeholders.py`
Expected: two `OK -> …` lines; both files now exist under `src/assets/placeholders/`. (Requires `ffmpeg` on PATH for the clip.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 tests/test_placeholders.py`
Expected: PASS — `ok t_bundled_graphic_is_1080p_rgba_png`, `ok t_bundled_media_clip_is_a_small_mp4`, `ALL PASS`.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add tools/make-placeholders.py src/assets/placeholders/ tests/test_placeholders.py
git commit -m "feat(assets): bundle neutral placeholder PNG/clip + regenerator tool"
```

---

### Task 2: Shared helper `src/scripts/placeholders.py`

**Files:**
- Create: `src/scripts/placeholders.py`
- Test: `tests/test_placeholders.py` (append)

**Interfaces:**
- Consumes: the bundled files from Task 1.
- Produces (used by Tasks 3–5):
  - `GRAPHIC_PLACEHOLDER: str = "transparent-1080p.png"`, `MEDIA_PLACEHOLDER: str = "neutral-5s-1080p.mp4"`
  - `graphic_placeholder_path() -> str | None`
  - `media_placeholder_path() -> str | None`
  - `expected_graphics_from_template(text: str) -> list[str]`  (sorted unique `<name>.png`)
  - `find_obs_template(obs_dir: str) -> str | None`
  - `fill_missing(expected_names: Iterable[str], directory: str, src_path: str | None) -> list[str]`  (sorted names actually written)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_placeholders.py` (above the `__main__` block):

```python
import shutil, tempfile

sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import placeholders as ph  # noqa: E402


def t_expected_graphics_extracts_sorted_unique():
    text = ('{"a":"__RACECAST_GRAPHICS__/Weather Sunny.png",'
            '"b":"__RACECAST_GRAPHICS__/Overlay.png",'
            '"c":"__RACECAST_GRAPHICS__/Overlay.png",'
            '"d":"__RACECAST_MEDIA__/intro.mp4"}')
    assert ph.expected_graphics_from_template(text) == ["Overlay.png", "Weather Sunny.png"]


def t_expected_graphics_empty_when_no_refs():
    assert ph.expected_graphics_from_template('{"x":"y"}') == []


def t_find_obs_template_prefers_template_then_json():
    with tempfile.TemporaryDirectory() as tmp:
        assert ph.find_obs_template(tmp) is None
        open(os.path.join(tmp, "GT_Endurance.json"), "w").close()
        assert ph.find_obs_template(tmp).endswith("GT_Endurance.json")
        open(os.path.join(tmp, "GT_Endurance.template.json"), "w").close()
        assert ph.find_obs_template(tmp).endswith("GT_Endurance.template.json")


def t_placeholder_paths_resolve_to_bundled_files():
    assert ph.graphic_placeholder_path() == PNG
    assert ph.media_placeholder_path() == MP4


def t_fill_missing_writes_only_absent_byte_identical():
    with tempfile.TemporaryDirectory() as tmp:
        with open(PNG, "rb") as fh:
            src_bytes = fh.read()
        # one already present -> must not be touched / re-listed
        with open(os.path.join(tmp, "Overlay.png"), "wb") as fh:
            fh.write(b"REAL")
        written = ph.fill_missing(["Overlay.png", "Weather Sunny.png"], tmp, PNG)
        assert written == ["Weather Sunny.png"]
        with open(os.path.join(tmp, "Overlay.png"), "rb") as fh:
            assert fh.read() == b"REAL"          # untouched
        with open(os.path.join(tmp, "Weather Sunny.png"), "rb") as fh:
            assert fh.read() == src_bytes        # byte-identical to the bundle
        assert not any(n.endswith(".part") for n in os.listdir(tmp))  # atomic, no temp left


def t_fill_missing_is_idempotent_and_creates_dir():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "gfx")        # does not exist yet
        first = ph.fill_missing(["A.png"], target, PNG)
        assert first == ["A.png"] and os.path.isfile(os.path.join(target, "A.png"))
        assert ph.fill_missing(["A.png"], target, PNG) == []   # second run: nothing


def t_fill_missing_tolerates_absent_source():
    with tempfile.TemporaryDirectory() as tmp:
        assert ph.fill_missing(["A.png"], tmp, None) == []
        assert ph.fill_missing(["A.png"], tmp, os.path.join(tmp, "nope.png")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_placeholders.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'placeholders'`.

- [ ] **Step 3: Write the helper** — create `src/scripts/placeholders.py`:

```python
#!/usr/bin/env python3
"""Neutral placeholders for missing broadcast assets.

When the OBS scene collection references a graphic or Intro/Outro clip that a
league never provided (e.g. weather overlays a league does not use), drop a
byte-identical copy of a bundled neutral placeholder under the expected filename
so OBS shows a neutral source instead of a broken/black one.

Pure stdlib; never imports config.py (the heavy resolver) — the same
dependency-light contract as the relay scripts that call it. The bundled assets
live at src/assets/placeholders/ and ship inside the binary because src/assets is
in build-binary.py's DATA list (--add-data of a directory recurses)."""
import os, re, shutil

GRAPHIC_PLACEHOLDER = "transparent-1080p.png"
MEDIA_PLACEHOLDER = "neutral-5s-1080p.mp4"

_GRAPHICS_REF_RE = re.compile(r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)")
_OBS_TEMPLATE_NAMES = ("GT_Endurance.template.json", "GT_Endurance.json")


def _placeholders_dir():
    """src/assets/placeholders resolved relative to THIS module, so it works in the
    repo and under _MEIPASS (src/scripts and src/assets ship side by side)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "assets", "placeholders")


def graphic_placeholder_path():
    """Absolute path of the bundled transparent PNG, or None when absent."""
    p = os.path.join(_placeholders_dir(), GRAPHIC_PLACEHOLDER)
    return p if os.path.isfile(p) else None


def media_placeholder_path():
    """Absolute path of the bundled neutral clip, or None when absent."""
    p = os.path.join(_placeholders_dir(), MEDIA_PLACEHOLDER)
    return p if os.path.isfile(p) else None


def expected_graphics_from_template(text):
    """Sorted unique '<name>.png' from every __RACECAST_GRAPHICS__/<name>.png
    reference in the (raw JSON) collection text."""
    return sorted(set(_GRAPHICS_REF_RE.findall(text)))


def find_obs_template(obs_dir):
    """First existing OBS template in obs_dir (package '.template.json' preferred,
    then the repo '.json'), or None."""
    for name in _OBS_TEMPLATE_NAMES:
        p = os.path.join(obs_dir, name)
        if os.path.isfile(p):
            return p
    return None


def fill_missing(expected_names, directory, src_path):
    """Copy `src_path` to `directory/<name>` for every name in `expected_names` not
    already present. Returns the sorted list of names actually written.

    Best-effort: a falsy/absent `src_path`, an uncreatable/unreadable `directory`,
    or a per-file copy error is skipped, never raised. Writes atomically
    (`.part` -> os.replace). Idempotent. Creates `directory`."""
    if not src_path or not os.path.isfile(src_path):
        return []
    try:
        os.makedirs(directory, exist_ok=True)
        have = set(os.listdir(directory))
    except OSError:
        return []
    written = []
    for name in expected_names:
        if name in have:
            continue
        dst = os.path.join(directory, name)
        tmp = dst + ".part"
        try:
            shutil.copyfile(src_path, tmp)
            os.replace(tmp, dst)
            written.append(name)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    return sorted(written)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_placeholders.py`
Expected: PASS — all `t_*` print `ok …`, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/placeholders.py tests/test_placeholders.py
git commit -m "feat(assets): pure helper to fill missing graphics/clips with placeholders"
```

---

### Task 3: Wire `setup-assets.py` (authoritative, collection-driven)

**Files:**
- Modify: `src/setup-assets.py` (imports near line 14–16; the `MEDIA_TOKEN`/`GRAPHICS_TOKEN` branches, lines 236–251)
- Test: `tests/test_placeholders.py` (append)

**Interfaces:**
- Consumes: `placeholders.expected_graphics_from_template`, `fill_missing`, `graphic_placeholder_path`, `media_placeholder_path`.
- Produces: localized collection plus placeholder files written into `--graphics`/`--media`; a `NOTE: …placeholder…` line on stdout.

- [ ] **Step 1: Write the failing test** — append to `tests/test_placeholders.py`:

```python
def t_setup_assets_fills_placeholders_for_missing():
    import json, subprocess
    with tempfile.TemporaryDirectory() as tmp:
        tpl = os.path.join(tmp, "tpl.json")
        with open(tpl, "w", encoding="utf-8") as fh:
            json.dump({"name": "T", "sources": [
                {"settings": {"file": "__RACECAST_GRAPHICS__/Weather Sunny.png"}},
                {"settings": {"local_file": "__RACECAST_MEDIA__/intro.mp4"}},
            ]}, fh)
        gfx, med = os.path.join(tmp, "gfx"), os.path.join(tmp, "med")
        out = os.path.join(tmp, "import.json")
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "src", "setup-assets.py"),
             "--template", tpl, "--assets", os.path.join(ROOT, "src", "assets"),
             "--graphics", gfx, "--media", med, "--out", out, "--sheet-id", "x"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert os.path.isfile(os.path.join(gfx, "Weather Sunny.png")), r.stdout
        assert os.path.isfile(os.path.join(med, "intro.mp4")), r.stdout
        assert os.path.isfile(os.path.join(med, "outro.mp4")), r.stdout
        assert "placeholder" in r.stdout.lower(), r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_setup_assets_fills_placeholders_for_missing()"`
Expected: FAIL — `AssertionError` (the Weather/intro/outro placeholder files are not written; `setup-assets` only warns today).

- [ ] **Step 3a: Add the helper import** — in `src/setup-assets.py`, after the existing `import overlay_build  # noqa: E402` line (≈ line 16), add:

```python
import placeholders  # noqa: E402  (pure stdlib helper — fills missing assets)
```

- [ ] **Step 3b: Replace the MEDIA_TOKEN branch** — change the block at lines 236–243 from:

```python
    if MEDIA_TOKEN in raw:
        mapping[MEDIA_TOKEN] = a.media
        missing = [f for f in ("intro.mp4", "outro.mp4")
                   if not os.path.isfile(os.path.join(a.media, f))]
        if missing:
            print(f"  WARNING: Intro/Outro clip(s) missing in {a.media}: "
                  f"{', '.join(missing)} — run get-media.py (OBS will show black "
                  "until then).")
```

to:

```python
    if MEDIA_TOKEN in raw:
        mapping[MEDIA_TOKEN] = a.media
        filled = placeholders.fill_missing(
            ["intro.mp4", "outro.mp4"], a.media, placeholders.media_placeholder_path())
        if filled:
            print(f"  NOTE: wrote neutral placeholder clip for missing "
                  f"{', '.join(filled)} in {a.media} (no real Intro/Outro configured "
                  "— run get-media.py to replace).")
```

- [ ] **Step 3c: Replace the GRAPHICS_TOKEN branch** — change the block at lines 244–251 from:

```python
    if GRAPHICS_TOKEN in raw:
        mapping[GRAPHICS_TOKEN] = a.graphics
        refs = sorted(set(re.findall(r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)", raw)))
        missing = [f for f in refs if not os.path.isfile(os.path.join(a.graphics, f))]
        if missing:
            print(f"  WARNING: graphic(s) missing in {a.graphics}: "
                  f"{', '.join(missing)} — run get-graphics.py (OBS shows black "
                  "until then).")
```

to:

```python
    if GRAPHICS_TOKEN in raw:
        mapping[GRAPHICS_TOKEN] = a.graphics
        refs = placeholders.expected_graphics_from_template(raw)
        filled = placeholders.fill_missing(
            refs, a.graphics, placeholders.graphic_placeholder_path())
        if filled:
            print(f"  NOTE: wrote transparent placeholder for missing graphic(s) in "
                  f"{a.graphics}: {', '.join(filled)} (no real asset configured — "
                  "run get-graphics.py to replace).")
```

- [ ] **Step 3d: Drop the now-unused `re` import** — confirm `re` is no longer referenced, then edit the import line:

```bash
grep -n "re\\." src/setup-assets.py    # expect: no matches
```

Change line 9 from `import argparse, json, os, re, sys` to `import argparse, json, os, sys`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_setup_assets_fills_placeholders_for_missing()"`
Expected: PASS (no output / no assertion).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
python3 tests/test_placeholders.py
git add src/setup-assets.py tests/test_placeholders.py
git commit -m "feat(assets): setup-assets fills missing OBS graphics/clips with placeholders"
```

---

### Task 4: Wire `get-graphics.py` (download step)

**Files:**
- Modify: `src/relay/get-graphics.py` (module-level import block; new `obs_template_dir` + `seed_missing_graphics`; call site in `main()` before the final `if failed:`)
- Test: `tests/test_placeholders.py` (append)

**Interfaces:**
- Consumes: `placeholders.find_obs_template`, `expected_graphics_from_template`, `fill_missing`, `graphic_placeholder_path`.
- Produces: `obs_template_dir(here: str) -> str`, `seed_missing_graphics(out_dir: str, here: str) -> list[str]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_placeholders.py` (the `_load_script` helper is introduced here and reused in Task 5):

```python
import importlib.util


def _load_script(rel):
    """Import a hyphen-named src script (e.g. relay/get-graphics.py) by path."""
    name = os.path.basename(rel).replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "src", rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def t_get_graphics_seeds_from_real_template():
    gg = _load_script("relay/get-graphics.py")
    here = os.path.join(ROOT, "src", "relay")
    with tempfile.TemporaryDirectory() as tmp:
        seeded = gg.seed_missing_graphics(tmp, here)
        assert seeded, "expected placeholders for collection-referenced graphics"
        with open(PNG, "rb") as a, open(os.path.join(tmp, seeded[0]), "rb") as b:
            assert a.read() == b.read()          # byte-identical to the bundle


def t_get_graphics_obs_template_dir_is_sibling():
    gg = _load_script("relay/get-graphics.py")
    assert gg.obs_template_dir(os.path.join(ROOT, "src", "relay")) == \
        os.path.join(ROOT, "src", "obs")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_get_graphics_seeds_from_real_template()"`
Expected: FAIL — `AttributeError: module 'get_graphics' has no attribute 'seed_missing_graphics'`.

- [ ] **Step 3a: Add the helper import block** — in `src/relay/get-graphics.py`, immediately after the imports (after line 15, `from urllib.request import Request, urlopen`), add:

```python
# Pure stdlib placeholder helper from src/scripts (resolved both from source and
# the frozen bundle, mirroring get-media.py). It is NOT config.py, so the relay's
# dependency-light contract holds.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_HERE, "..", "scripts"),
              os.path.join(getattr(sys, "_MEIPASS", _HERE), "src", "scripts")):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)
import placeholders  # noqa: E402
```

- [ ] **Step 3b: Add the seeding functions** — in `src/relay/get-graphics.py`, after `graphics_dir(here)` (line 104), add:

```python
def obs_template_dir(here):
    """Dir holding the bundled OBS collection template, a sibling of this script's
    parent in every layout: repo src/relay -> src/obs ; package relay/ -> ../obs ;
    frozen _MEIPASS/src/relay -> _MEIPASS/src/obs."""
    return os.path.join(os.path.dirname(here), "obs")


def seed_missing_graphics(out_dir, here):
    """Drop the transparent placeholder for any OBS-collection-referenced graphic
    still missing in out_dir — covers graphics a league never put in the Sheet
    (e.g. weather overlays). Best-effort; returns the sorted names written."""
    tpl = placeholders.find_obs_template(obs_template_dir(here))
    if not tpl:
        return []
    try:
        with open(tpl, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    refs = placeholders.expected_graphics_from_template(text)
    return placeholders.fill_missing(refs, out_dir, placeholders.graphic_placeholder_path())
```

- [ ] **Step 3c: Call it from `main()`** — in `src/relay/get-graphics.py`, replace the final block (lines 183–184):

```python
    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")
```

with:

```python
    seeded = seed_missing_graphics(a.out, here)
    if seeded:
        print(f"Wrote transparent placeholder for {len(seeded)} graphic(s) still "
              f"missing (no Sheet asset): {', '.join(seeded)}")

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_get_graphics_seeds_from_real_template(); t.t_get_graphics_obs_template_dir_is_sibling()"`
Expected: PASS (no output).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
python3 tests/test_placeholders.py
git add src/relay/get-graphics.py tests/test_placeholders.py
git commit -m "feat(assets): get-graphics seeds placeholders for never-in-Sheet graphics"
```

---

### Task 5: Wire `get-media.py` (download step)

**Files:**
- Modify: `src/relay/get-media.py` (import next to `services`; new `seed_missing_media`; call site in `main()` before the final `if failed:`)
- Test: `tests/test_placeholders.py` (append)

**Interfaces:**
- Consumes: `placeholders.fill_missing`, `media_placeholder_path`.
- Produces: `seed_missing_media(out_dir: str, which: Iterable[str]) -> list[str]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_placeholders.py`:

```python
def t_get_media_seeds_placeholder_clip():
    gm = _load_script("relay/get-media.py")
    with tempfile.TemporaryDirectory() as tmp:
        seeded = gm.seed_missing_media(tmp, {"intro", "outro"})
        assert sorted(seeded) == ["intro.mp4", "outro.mp4"]
        with open(MP4, "rb") as a, open(os.path.join(tmp, "intro.mp4"), "rb") as b:
            assert a.read() == b.read()
        # already-present clip is not overwritten / re-listed
        assert gm.seed_missing_media(tmp, {"intro"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_get_media_seeds_placeholder_clip()"`
Expected: FAIL — `AttributeError: module 'get_media' has no attribute 'seed_missing_media'`.

- [ ] **Step 3a: Add the helper import** — in `src/relay/get-media.py`, after the existing `from services import external_tool_env` line (line 27), add:

```python
import placeholders  # noqa: E402  (pure stdlib helper — fills a missing clip)
```

- [ ] **Step 3b: Add the seeding function** — in `src/relay/get-media.py`, after `media_dir(here)` (line 97), add:

```python
def seed_missing_media(out_dir, which):
    """Drop the neutral placeholder clip for any of intro.mp4/outro.mp4 named in
    `which` (a set of 'intro'/'outro') still missing in out_dir. Best-effort;
    returns the sorted names written."""
    names = [f"{k}.mp4" for k in sorted(which)]
    return placeholders.fill_missing(names, out_dir, placeholders.media_placeholder_path())
```

- [ ] **Step 3c: Call it from `main()`** — in `src/relay/get-media.py`, replace the final block (lines 224–225):

```python
    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")
```

with:

```python
    seeded = seed_missing_media(a.out, which)
    if seeded:
        print(f"Wrote neutral placeholder clip for {len(seeded)} missing: "
              f"{', '.join(seeded)}")

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_get_media_seeds_placeholder_clip()"`
Expected: PASS (no output).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
python3 tests/test_placeholders.py
git add src/relay/get-media.py tests/test_placeholders.py
git commit -m "feat(assets): get-media seeds a neutral placeholder for a missing clip"
```

---

### Task 6: Freeze the helper in the binary build

**Files:**
- Modify: `tools/build-binary.py` (the `--hidden-import` list in `build_target`, near `overlay_build` ≈ line 97)
- Test: `tests/test_placeholders.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `placeholders` as a frozen hidden import so the importlib-loaded scripts resolve it in the binary.

- [ ] **Step 1: Write the failing test** — append to `tests/test_placeholders.py`:

```python
def t_build_binary_freezes_placeholders():
    with open(os.path.join(ROOT, "tools", "build-binary.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert '"placeholders"' in src, \
        "build-binary.py must --hidden-import placeholders (importlib-loaded scripts " \
        "import it; PyInstaller's static scan cannot see that)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_build_binary_freezes_placeholders()"`
Expected: FAIL — `AssertionError: build-binary.py must --hidden-import placeholders`.

- [ ] **Step 3: Add the hidden import** — in `tools/build-binary.py`, change the line (≈ 97):

```python
           "--hidden-import", "overlay_build",
```

to:

```python
           "--hidden-import", "overlay_build",
           "--hidden-import", "placeholders",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_placeholders as t; t.t_build_binary_freezes_placeholders()"`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tools/build-binary.py tests/test_placeholders.py
git commit -m "build(assets): freeze the placeholders helper into the binaries"
```

---

### Task 7: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass, including `tests/test_placeholders.py`.

- [ ] **Step 2: Run the lint job**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build-verify the distributable**

Run: `python3 tools/build.py`
Expected: build + verify succeed (tokenization, blanked password, no secrets, no shell scripts). Confirm `src/assets/placeholders/` is copied into `dist/GT_Racecast_Package/src/assets/placeholders/` (or the package's assets path) and the verify step does not flag the binary files.

- [ ] **Step 4: Manual sanity (optional, local)**

Run a localize against the demo profile into a temp dir and confirm the NOTE + placeholder files appear:
```bash
python3 src/setup-assets.py --sheet-id demo \
  --out /tmp/import.json --graphics /tmp/gfx --media /tmp/med 2>&1 | grep -i placeholder
ls /tmp/gfx /tmp/med
```
Expected: a `NOTE: wrote … placeholder …` line; transparent PNGs in `/tmp/gfx`, `intro.mp4`/`outro.mp4` in `/tmp/med`.

---

## Self-Review notes

- **Spec coverage:** bundled assets + tool (Task 1) ✓; helper with all five functions (Task 2) ✓; setup-assets wiring + NOTE (Task 3) ✓; get-graphics never-in-Sheet seeding (Task 4) ✓; get-media clip seeding (Task 5) ✓; `--hidden-import placeholders` build change (Task 6) ✓; status untouched (no `event.py` task — intentional) ✓; tests (Tasks 1–6 + suite in 7) ✓.
- **Placeholder scan:** no TBD/TODO; every code step shows full code.
- **Type consistency:** `fill_missing`, `expected_graphics_from_template`, `find_obs_template`, `graphic_placeholder_path`, `media_placeholder_path`, `obs_template_dir`, `seed_missing_graphics`, `seed_missing_media` are spelled identically across the tasks that define and consume them.
