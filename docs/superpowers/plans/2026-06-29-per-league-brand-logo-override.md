# Per-League Brand-Logo Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a league owner override (or add) HUD brand logos per league via a new Google-Sheet `Brands` tab, served override-first by the relay and carried with `profile export`.

**Architecture:** A new self-contained downloader (`get-brands.py`) pulls the `Brands` tab's Drive-linked logos into `runtime/<profile>/brands/<asset_key>.png`. The relay derives `brands_dir` next to `graphics_dir` and resolves `/hud/assets/brands/<key>` **override-first** (profile dir, then the committed `src/assets/brands` base) — zero front-end change. `runtime/<profile>/brands/` becomes a third profile-export asset section. A `racecast brands` one-shot and a Control Center download card drive the refresh.

**Tech Stack:** Pure Python 3 stdlib (no framework, no deps). gviz CSV endpoint (no API key). Each `tests/test_*.py` is a runnable script (no pytest). Frozen-binary path resolution via the existing relay-script layout.

## Global Constraints

- **Edit only under `src/` (+ `tests/`, `docs/`).** `dist/`/`runtime/` are generated — never hand-edit. `tools/` are maintainer scripts.
- **All scripts and docs are English only.**
- **Never hardcode secrets or machine paths.**
- **Python only** — no `.sh`/`.bat`.
- **The four self-contained relay scripts** (`racecast-feeds.py`, `setup-assets.py`, `get-media.py`, `get-graphics.py` — and now `get-brands.py`) **must NOT import shared modules** (`config.py` etc.). Duplicated helpers (`load_dotenv`, `asset_key`) are kept in sync and pinned by a test.
- **Cross-platform**: tests run on the Windows CI runner too. Use `os.path.join` only for current-machine paths; compare with `os.path.join(...)` in assertions (never a hardcoded `/`-separated string).
- **PNG only** for brand logos (transparency; the base set is PNG). No SVG/JPG download path.
- **`racecast` is released (v1.1.0)** — backward compatibility matters. Adding the `brands` export section is additive; the forward-incompat (old binary rejecting a new bundle that carries `brands/`) is documented, `SCHEMA` is NOT bumped.
- **Changed a Control Center surface → regenerate its `cc-*.png` wiki screenshot in the SAME change** (CLAUDE.md hard rule), from a local dev build.
- After Python edits run `python3 tools/lint.py`; the full gate is `python3 tools/run-tests.py`; ship-verify with `python3 tools/build.py`.

Reference spec: `docs/superpowers/specs/2026-06-29-per-league-brand-logo-override-design.md`.

---

### Task 1: `get-brands.py` downloader + pure-piece tests

**Files:**
- Create: `src/relay/get-brands.py`
- Create: `tests/test_brands.py`

**Interfaces:**
- Consumes: nothing (self-contained script, stdlib only).
- Produces:
  - `asset_key(s) -> str` — byte-identical to `racecast-feeds.py:asset_key` (pinned by test).
  - `brands_from_csv(rows) -> dict[str, str]` — `{asset_key(brand): drive_url}`, header-located, Drive-links only.
  - `safe_filename(key) -> str | None` — `"<key>.png"` for a valid `[a-z0-9-]+` key, else `None`.
  - `brands_dir(here) -> str`, `fetch_brands_csv(sheet_id, tab, timeout=15) -> str`, `download(url, out_path, timeout=60)`, `is_drive_url`, `drive_id`, `to_download_url`, `load_dotenv`.
  - CLI `main()` with `--out`, `--sheet-id` (default env `RACECAST_SHEET_ID`), `--brands-tab` (default `Brands`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_brands.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for get-brands.py. Run: python3 tests/test_brands.py"""
import importlib.util, inspect, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


m = _load("getbrands", os.path.join("src", "relay", "get-brands.py"))
feeds = _load("irofeeds", os.path.join("src", "relay", "racecast-feeds.py"))


def t_asset_key_matches_brand_text():
    # The downloaded filename stem must equal the HUD's brandKey for that brand.
    assert m.asset_key("BMW") == "bmw"
    assert m.asset_key("Aston Martin") == "aston-martin"
    assert m.asset_key("  Cupra ") == "cupra"
    assert m.asset_key("") == ""


def t_asset_key_pinned_to_relay():
    """Drift guard: the duplicated asset_key must stay byte-identical to the relay's
    (mirrors the STREAMLINK_TWITCH pin in test_streams.py)."""
    norm = lambda fn: inspect.getsource(fn).strip()
    assert norm(m.asset_key) == norm(feeds.asset_key)


def t_safe_filename():
    assert m.safe_filename("bmw") == "bmw.png"
    assert m.safe_filename("aston-martin") == "aston-martin.png"
    assert m.safe_filename("") is None
    assert m.safe_filename("a/b") is None
    assert m.safe_filename("../x") is None
    assert m.safe_filename("BMW") is None   # already normalized; uppercase is not a valid key


def t_brands_from_csv_normalizes_key_and_picks_drive():
    rows = [["Brand", "Logo"],
            ["BMW", "https://drive.google.com/file/d/B1/view?usp=sharing"],
            ["Aston Martin", "https://drive.google.com/file/d/A2/view"],
            ["YouTubeRow", "https://youtu.be/AAA"],
            ["", "https://drive.google.com/file/d/X/view"]]
    assert m.brands_from_csv(rows) == {
        "bmw": "https://drive.google.com/file/d/B1/view?usp=sharing",
        "aston-martin": "https://drive.google.com/file/d/A2/view"}, m.brands_from_csv(rows)


def t_brands_from_csv_header_variants():
    # "Brand Key" header is accepted too; logo header may be "Logo URL".
    rows = [["Brand Key", "Logo URL"],
            ["Cupra", "https://drive.google.com/file/d/C/view"]]
    assert m.brands_from_csv(rows) == {"cupra": "https://drive.google.com/file/d/C/view"}


def t_brands_from_csv_no_header_returns_empty():
    rows = [["Something", "Else"], ["x", "y"]]
    assert m.brands_from_csv(rows) == {}


def t_brands_dir_repo():
    got = m.brands_dir(os.path.join("/x", "src", "relay"))
    assert got == os.path.join("/x", "runtime", "brands"), got


def t_brands_dir_pkg():
    got = m.brands_dir(os.path.join("/x/GT_Racecast_Package", "relay"))
    assert got == os.path.join("/x/GT_Racecast_Package", "brands"), got


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_brands.py`
Expected: FAIL — `FileNotFoundError`/`spec` error because `src/relay/get-brands.py` does not exist yet.

- [ ] **Step 3: Write the downloader**

Create `src/relay/get-brands.py`. It mirrors `get-graphics.py` closely but: header-locates the key/logo columns, normalizes the key with `asset_key` (so the filename stem equals the HUD `brandKey`), and has NO placeholder-seeding (brands have no OBS-template default).

```python
#!/usr/bin/env python3
"""Download per-league brand-logo overrides for the HUD from the Google Sheet
'Brands' tab.

Each Brands row whose logo cell is a Google-Drive share link is downloaded as
'<asset_key(brand)>.png' into the brands dir (repo: <repo>/runtime/brands ;
distributed package: <package>/brands). The relay serves /hud/assets/brands/<key>
OVERRIDE-FIRST: a file here wins over the committed src/assets/brands set, so a
league can replace a built-in logo (e.g. bmw) or add a new manufacturer (e.g.
cupra). The key is normalized with the SAME asset_key() the HUD uses on the
Configuration-tab brand text, so the stem always lines up. Never stored under
src/, never committed.

Usage: python3 get-brands.py [--out DIR] [--sheet-id ID] [--brands-tab NAME]
"""
import argparse, csv, io, os, re, sys
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

# Header names located case-insensitively (first match wins), mirroring the
# relay's tab parsers. The KEY column holds the brand text; the LOGO column holds
# the Drive share link.
BRAND_KEY_HEADERS = ("brand key", "brand", "brand name")
BRAND_LOGO_HEADERS = ("logo", "logo url", "image")


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with a
    .git/.env.example marker). KEEP IN SYNC with the copies in racecast-feeds.py,
    setup-assets.py, get-media.py and get-graphics.py."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, mk)) for mk in (".git", ".env.example")):
            candidates.append(d)
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def asset_key(s):
    """Normalize free text (country/brand) to an asset filename stem."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9-]", "", s)


def is_drive_url(url):
    """True iff the URL's HOST is drive.google.com (or a subdomain). A plain
    substring check would also match e.g. https://evil.example/?drive.google.com."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "drive.google.com" or host.endswith(".drive.google.com")


def drive_id(url):
    """Extract a Google-Drive file ID from a share or download URL, else None."""
    if not url:
        return None
    m = (re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
         or re.search(r"[?&]id=([A-Za-z0-9_-]+)", url))
    return m.group(1) if m else None


def to_download_url(file_id):
    """Direct-download endpoint for a Drive file ID (no API key)."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def safe_filename(key):
    """'<key>.png' for a valid normalized brand key ([a-z0-9-]+), else None.
    The input is expected to already be asset_key()-normalized."""
    if not key or not re.fullmatch(r"[a-z0-9-]+", key):
        return None
    return f"{key}.png"


def brands_from_csv(rows):
    """Brands-tab rows -> {asset_key(brand): drive_url}. Columns are header-located
    (BRAND_KEY_HEADERS / BRAND_LOGO_HEADERS, first match wins, case-insensitive).
    A row is kept only when its logo cell is a Google-Drive link. No header row ->
    {} (we never positionally guess, to avoid mis-downloading)."""
    if not rows:
        return {}
    header = [(h or "").strip().lower() for h in rows[0]]
    ki = next((header.index(h) for h in BRAND_KEY_HEADERS if h in header), None)
    li = next((header.index(h) for h in BRAND_LOGO_HEADERS if h in header), None)
    if ki is None or li is None:
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) <= ki or len(row) <= li:
            continue
        key = asset_key(row[ki])
        url = (row[li] or "").strip()
        if key and is_drive_url(url) and drive_id(url):
            out[key] = url
    return out


def brands_dir(here):
    """Where brand overrides live when --out is not given. Mirrors
    get-graphics.graphics_dir(): repo (src/relay) -> <repo>/runtime/brands ;
    package (relay) -> <pkg>/brands."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "brands")
    return os.path.join(os.path.dirname(here), "brands")


def fetch_brands_csv(sheet_id, tab, timeout=15):
    """Fetch the Brands tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "racecast-brands/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(url, out_path, timeout=60):
    """GET a Drive file to out_path as a PNG. Handles the large-file confirm
    interstitial. Writes atomically; verifies the PNG signature before committing."""
    req = Request(url, headers={"User-Agent": "racecast-brands/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    if ctype.startswith("text/html"):
        m = re.search(rb"confirm=([0-9A-Za-z_-]+)", data)
        if not m:
            raise RuntimeError("Drive returned an HTML interstitial with no confirm token")
        req2 = Request(url + "&confirm=" + m.group(1).decode(),
                       headers={"User-Agent": "racecast-brands/1.0"})
        with urlopen(req2, timeout=timeout) as resp2:
            data = resp2.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("downloaded data is not a PNG")
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=brands_dir(here),
                    help="Target dir for <key>.png files (default: brands_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID holding the Brands tab. Default: env RACECAST_SHEET_ID.")
    ap.add_argument("--brands-tab", default="Brands")
    a = ap.parse_args()

    if not a.sheet_id:
        sys.exit("ERROR: no Sheet ID (set SHEET_ID in the active profile or pass --sheet-id).")
    try:
        csv_text = fetch_brands_csv(a.sheet_id, a.brands_tab)
    except Exception as e:
        sys.exit(f"ERROR: could not read sheet Brands tab: {e}")

    brands = brands_from_csv(list(csv.reader(io.StringIO(csv_text))))
    if not brands:
        # No Brands tab / no override rows is NOT an error: the committed base set
        # is still served. Exit 0 so `racecast brands` is safe to run on any league.
        print("No brand-override rows in the Brands tab — base logos unchanged.")
        return

    os.makedirs(a.out, exist_ok=True)
    failed = []
    for key in sorted(brands):
        fname = safe_filename(key)
        if not fname:
            print(f"WARNING: skipping unsafe brand key {key!r}")
            failed.append(key)
            continue
        out_path = os.path.join(a.out, fname)
        print(f"Downloading {key}: {fname}")
        try:
            download(to_download_url(drive_id(brands[key])), out_path)
            print(f"OK -> {out_path}")
        except Exception as e:
            print(f"WARNING: download failed for {key}: {e}")
            failed.append(key)

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_brands.py`
Expected: `ALL PASS` (every `ok  t_*` line, incl. `t_asset_key_pinned_to_relay`).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/get-brands.py tests/test_brands.py
git commit -m "feat(brands): get-brands.py downloader for per-league Brands-tab logos"
```

---

### Task 2: Relay override-first serving

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `resolve_brand_override`; thread `brands_dir` through `make_handler`; override-first in `_send_asset`; derive `brands_dir` in `main()`)
- Test: `tests/test_hud.py`

**Interfaces:**
- Consumes: `ASSET_KEY_RE`, `ASSET_EXTS` (existing module constants).
- Produces: `resolve_brand_override(brands_dir, key) -> (path, content_type) | None`. `make_handler(..., brands_dir=None)`. `_send_asset` resolves brands override-first.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hud.py` (the module is already loaded as `m`):

```python
def t_resolve_brand_override_direct_base():
    import tempfile, os as _os
    bd = tempfile.mkdtemp()
    with open(_os.path.join(bd, "cupra.png"), "w") as fh:
        fh.write("x")
    # brands_dir is the base DIRECTLY (no 'brands' sub-level, unlike resolve_asset)
    path, ctype = m.resolve_brand_override(bd, "cupra")
    assert path.endswith("cupra.png") and ctype == "image/png", (path, ctype)
    assert m.resolve_brand_override(bd, "bmw") is None        # not overridden here
    assert m.resolve_brand_override(bd, "../secret") is None   # traversal rejected
    assert m.resolve_brand_override("", "cupra") is None       # no dir
    assert m.resolve_brand_override(bd, "BadKey") is None       # bad key shape


def t_brand_override_wins_over_base():
    """The exact precedence expression _send_asset uses for sub=='brands'."""
    import tempfile, os as _os
    bd = tempfile.mkdtemp()                       # runtime override dir
    ad = tempfile.mkdtemp()                       # base assets dir (src/assets shape)
    _os.makedirs(_os.path.join(ad, "brands"))
    with open(_os.path.join(bd, "bmw.png"), "w") as fh:
        fh.write("override")
    with open(_os.path.join(ad, "brands", "bmw.png"), "w") as fh:
        fh.write("base")
    hit = m.resolve_brand_override(bd, "bmw") or m.resolve_asset(ad, "brands", "bmw")
    assert hit[0].startswith(_os.path.realpath(bd)), hit          # override path wins
    # a key present only in the base still resolves through the fallback
    with open(_os.path.join(ad, "brands", "audi.png"), "w") as fh:
        fh.write("base")
    hit2 = m.resolve_brand_override(bd, "audi") or m.resolve_asset(ad, "brands", "audi")
    assert hit2[0].endswith("audi.png") and hit2[0].startswith(_os.path.realpath(ad)), hit2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'resolve_brand_override'`.

- [ ] **Step 3: Add `resolve_brand_override` next to `resolve_asset`**

In `src/relay/racecast-feeds.py`, immediately after `resolve_asset` (after line 538), add:

```python
def resolve_brand_override(brands_dir, key):
    """Resolve a per-league brand-logo override by key (no extension) to
    (path, content_type), or None. Unlike resolve_asset, `brands_dir`
    (runtime/<profile>/brands) is treated DIRECTLY as the base — there is no
    'brands' sub-level. Same safety contract: strict key regex + the ASSET_EXTS
    extension whitelist + realpath containment (no path traversal)."""
    if not brands_dir or not ASSET_KEY_RE.match(key):
        return None
    base = os.path.realpath(brands_dir)
    for ext, ctype in ASSET_EXTS:
        path = os.path.realpath(os.path.join(base, f"{key}.{ext}"))
        if not path.startswith(base + os.sep):
            return None
        if os.path.exists(path):
            return path, ctype
    return None
```

- [ ] **Step 4: Thread `brands_dir` into `make_handler` and use it override-first**

In the `make_handler` signature (line 4799), add `brands_dir=None` to the final kwargs line:

```python
                 broadcast_chat_store=None, broadcast_chat_supervisor=None,
                 preview_manager=None, brands_dir=None):
```

In `_send_asset` (lines 4913-4923), change the resolution to be override-first for brands:

```python
        def _send_asset(self, assets_dir, sub, key):
            hit = resolve_brand_override(brands_dir, key) if sub == "brands" else None
            if not hit:
                hit = resolve_asset(assets_dir, sub, key)
            if not hit:
                return self._send({"error": "asset not found", "key": key}, 404)
            path, ctype = hit
            # Header value comes from the ASSET_CTYPES constant, never from the
            # request-derived tuple (defense vs. header injection).
            ctype = ASSET_CTYPES.get(ctype)
            if not ctype:
                return self._send({"error": "asset not found", "key": key}, 404)
            return self._send_file(path, ctype)
```

- [ ] **Step 5: Derive `brands_dir` in `main()` and pass it to `make_handler`**

After line 6472 (`graphics_dir = os.path.join(runtime, "graphics") ...`), add:

```python
    brands_dir = os.path.join(runtime, "brands")   # per-league brand-logo overrides
```

In the `make_handler(...)` call (around line 6664, end of the kwargs), add `brands_dir=brands_dir`:

```python
                           uplot_dir=uplot_dir,
                           brands_dir=brands_dir,
```
(Place it among the existing trailing kwargs; exact neighbor lines may have shifted — append it to the call's keyword arguments.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS` including `t_resolve_brand_override_direct_base` and `t_brand_override_wins_over_base`.

Run: `python3 tests/test_pov.py`
Expected: PASS (relay smoke unchanged).

- [ ] **Step 7: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(brands): relay serves /hud/assets/brands override-first from runtime/<profile>/brands"
```

---

### Task 3: `racecast brands` one-shot CLI

**Files:**
- Modify: `src/racecast.py` (`ONESHOTS`, `ONESHOT_MAP`, `_oneshot_extra` `--out` map, top usage/help text)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `get-brands.py` (Task 1) via `ONESHOT_MAP`; `_oneshot_extra` injects `--out runtime/<active>/brands`.
- Produces: `racecast brands` runs the downloader with the profile-scoped output dir.

- [ ] **Step 1: Write the failing test**

First inspect how `tests/test_racecast.py` already asserts one-shot wiring, then mirror it. Add a test that the `brands` command maps to the downloader and gets a profile-scoped `--out`:

```python
def t_brands_oneshot_mapping_and_out():
    import importlib.util, os as _os
    # rc is the loaded racecast module used elsewhere in this file; reuse that loader.
    assert rc.ONESHOT_MAP["brands"] == "relay/get-brands.py"
    assert "brands" in rc.ONESHOTS
    extra = rc._oneshot_extra("brands", [], _os.path.join("/rt", "demo"), "/rt")
    assert extra == ["--out", _os.path.join("/rt", "demo", "brands")], extra
    # an explicit --out from the user wins (no injected default)
    assert rc._oneshot_extra("brands", ["--out", "/x"], _os.path.join("/rt", "demo"), "/rt") == []
```

(Use the same module-load helper the file already defines for `rc`. If the file loads the module under a different name, match it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `KeyError: 'brands'` / `assert "brands" in rc.ONESHOTS`.

- [ ] **Step 3: Wire the one-shot**

In `src/racecast.py`:

Add `"brands"` to `ONESHOTS` (line 877):
```python
ONESHOTS = ("preflight", "speedtest", "cookies", "graphics", "media", "brands", "setup", "install-tools", "install-apps", "obs-browser", "update")
```

Add the script mapping to `ONESHOT_MAP` (after the `"media"` entry, line 3133):
```python
    "media":         "relay/get-media.py",
    "brands":        "relay/get-brands.py",
```

Add the profile-scoped `--out` in `_oneshot_extra` (the dict at lines 549-551):
```python
        out = {"graphics": os.path.join(runtime_dir, "graphics"),
               "media": os.path.join(runtime_dir, "media"),
               "brands": os.path.join(runtime_dir, "brands"),
               "setup": os.path.join(runtime_dir, "GT_Endurance.import.json")}.get(command)
```

Update the top-of-file usage/help line that lists one-shots (line ~29) to include `brands`:
```python
  racecast preflight | speedtest [--json] | cookies [twitch] [browser] | graphics | media | brands | setup [--out PATH] | install-tools [--yes] [--update] | install-apps [--yes] [--update]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS (incl. `t_brands_oneshot_mapping_and_out`).

- [ ] **Step 5: Smoke the CLI surface**

Run: `python3 src/racecast.py brands --help`
Expected: argparse help for `get-brands.py` (shows `--out`, `--sheet-id`, `--brands-tab`); exit 0.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(brands): racecast brands one-shot -> get-brands.py (profile-scoped --out)"
```

---

### Task 4: Profile export/import carries `brands/`

**Files:**
- Modify: `src/scripts/profile_io.py:23` (`ASSET_SECTIONS`)
- Modify: `src/racecast.py:4685-4687` (`profile_export_data` sources)
- Test: `tests/test_profile_io.py`

**Interfaces:**
- Consumes: `export_profile`/`import_profile` (existing — already iterate `ASSET_SECTIONS`).
- Produces: bundles include a `brands/` section when present; import restores `runtime/<slug>/brands/`.

- [ ] **Step 1: Write the failing test**

In `tests/test_profile_io.py`, extend the `_profile` fixture to also create a brands dir, and add a round-trip assertion. Change `_profile` to add brands files and return them in `sources`:

```python
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
    bdir = os.path.join(d, "runtime", name, "brands")
    os.makedirs(gdir, exist_ok=True); os.makedirs(mdir, exist_ok=True)
    os.makedirs(bdir, exist_ok=True)
    with open(os.path.join(gdir, "Overlay.png"), "wb") as f:
        f.write(b"PNG")
    with open(os.path.join(mdir, "Intro.mp4"), "wb") as f:
        f.write(b"MP4")
    with open(os.path.join(bdir, "cupra.png"), "wb") as f:
        f.write(b"PNG")
    sources = {"profile_dir": pdir, "graphics": gdir, "media": mdir, "brands": bdir}
    roots = {"profiles_root": os.path.join(d, "profiles"),
             "runtime_root": os.path.join(d, "runtime")}
    return sources, roots
```

Add assertions to `t_export_with_assets` (after the `media/Intro.mp4` assert):
```python
        assert "brands/cupra.png" in names
        assert man["counts"].get("brands") == 1
```

Add to `t_round_trip` (after the media assert):
```python
    assert os.path.isfile(os.path.join(e, "runtime", "iro-gtec", "brands", "cupra.png"))
```

Add a new test that a profile WITHOUT a brands dir still exports/imports cleanly (backward shape):
```python
def t_export_without_brands_dir_is_fine():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    import shutil
    shutil.rmtree(sources["brands"])   # league never ran `racecast brands`
    path = pio.export_profile("iro-gtec", sources, include_assets=True, dest=d)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert not any(n.startswith("brands/") for n in names)
        assert json.loads(z.read("manifest.json"))["counts"].get("brands", 0) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_profile_io.py`
Expected: FAIL — `assert "brands/cupra.png" in names` (brands not yet in `ASSET_SECTIONS`).

- [ ] **Step 3: Add `brands` to `ASSET_SECTIONS`**

In `src/scripts/profile_io.py:23`:
```python
ASSET_SECTIONS = ("graphics", "media", "brands")   # top-level subtrees beside profile/
```

- [ ] **Step 4: Add `brands` to the export sources**

In `src/racecast.py`, `profile_export_data` (lines 4685-4687):
```python
        sources = {"profile_dir": profile_dir,
                   "graphics": os.path.join(rt, "graphics"),
                   "media": os.path.join(rt, "media"),
                   "brands": os.path.join(rt, "brands")}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 tests/test_profile_io.py`
Expected: `All profile_io tests passed.` (incl. the new brands assertions and `t_export_without_brands_dir_is_fine`).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/profile_io.py src/racecast.py tests/test_profile_io.py
git commit -m "feat(brands): carry runtime/<profile>/brands in profile export/import"
```

---

### Task 5: Control Center download card

**Files:**
- Modify: `src/ui/ui_ops.py` (`OPS`)
- Modify: `src/racecast.py` (`assets_files_data` listing + default `roots`; `asset_roots_data`)
- Modify: `src/ui/control-center.html` (Brands section + gallery + op-completion refresh + `fetchAssetFiles` render)
- Regenerate: `src/docs/wiki/images/cc-*.png` (the Profile/Assets view) via the `wiki-screenshots` skill
- Test: `tests/test_ui_ops.py`

**Interfaces:**
- Consumes: the `brands` one-shot (Task 3) via `OPS["brands"]`; `asset_roots_data`/`assets_files_data` serve+list the runtime brands dir.
- Produces: a Brands download card + gallery in the Profile view; `op('brands')` triggers the download and refreshes the gallery.

- [ ] **Step 1: Write the failing test**

In `tests/test_ui_ops.py`, assert the new op builds the right argv (mirror the existing graphics/media op test):

```python
def t_brands_op_argv():
    import importlib.util, os
    # uo is the loaded ui_ops module used elsewhere in this file; reuse that loader.
    assert uo.OPS["brands"] == ["brands"]
    assert uo.build_argv("brands", {}) == ["brands"]
```

(Match the module variable name the file already uses for `ui_ops`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL — `KeyError: 'brands'`.

- [ ] **Step 3: Register the op**

In `src/ui/ui_ops.py`, add to `OPS` after the `"media"` entry (line 36):
```python
    "graphics": ["graphics"],
    "media": ["media"],
    "brands": ["brands"],
```

- [ ] **Step 4: Serve + list the runtime brands dir**

In `src/racecast.py`, `asset_roots_data` (lines 3635-3637):
```python
    rt = _runtime_dir()
    return {"graphics": os.path.join(rt, "graphics"),
            "media": os.path.join(rt, "media"),
            "brands": os.path.join(rt, "brands")}
```

In `assets_files_data` — extend the default `roots` (lines 3606-3607) and the returned listing (lines 3619-3622). Brand files are images, so reuse the `IMG` extension tuple:
```python
        if roots is None:
            rt = _runtime_dir()
            roots = {"graphics": os.path.join(rt, "graphics"),
                     "media": os.path.join(rt, "media"),
                     "brands": os.path.join(rt, "brands")}
```
```python
        return {"ok": True,
                "profile": profile,
                "graphics": listing(roots["graphics"], IMG),
                "media": listing(roots["media"], VID),
                "brands": listing(roots.get("brands", ""), IMG)}
```
(Use `roots.get("brands", "")` so a caller passing the old two-key `roots` dict — e.g. an existing test seam — still works; `listing("")` returns `[]`.)

- [ ] **Step 5: Add the Brands card + gallery to the Profile view**

In `src/ui/control-center.html`, after the Media `<section>` (closes at line 819), add a Brands section mirroring it:
```html
        <section>
          <div class="row"><span class="name">Brands</span>
            <span class="dim grow" id="d-brands">per-league logo overrides (Sheet "Brands" tab)</span>
            <button onclick="op('brands')">
              <svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>Download</button></div>
          <div class="gallery" id="brands-gallery"></div>
        </section>
```
Update the Assets view subtitle (line 800) to mention brands:
```html
          <span class="sub">graphics + media + brand overrides for the active profile</span>
```
Update the op-completion refresh (line 1900) to include brands:
```javascript
    if (name === 'graphics' || name === 'media' || name === 'brands') fetchAssetFiles();
```
In `fetchAssetFiles()` (the function that renders `gfx-gallery`/`media-gallery` from `/api/assets/files`), render the brands gallery the same way. Locate the block that populates `gfx-gallery` and `media-gallery` from the response and add an equivalent for `a.brands` into `brands-gallery`. The brands images are served by the same `/api/assets/files`-backed image route the graphics gallery uses (kind = `brands`, now present in `asset_roots`), so the thumbnail `src` follows the existing graphics pattern with the `brands` kind.

- [ ] **Step 6: Run test + verify the UI surface manually**

Run: `python3 tests/test_ui_ops.py`
Expected: PASS (incl. `t_brands_op_argv`).

Run: `python3 tools/run-tests.py`
Expected: full suite PASS (catches any `assets_files_data` shape regression in `tests/test_ui_*`).

Manual: start a dev-build Control Center (`python3 src/racecast.py ui`), open the Profile view, confirm the **Brands** card shows a Download button and (after a download) a gallery of `runtime/<profile>/brands/*.png`.

- [ ] **Step 7: Regenerate the wiki screenshot (CLAUDE.md hard rule)**

Use the `wiki-screenshots` skill to recapture the Control Center Profile/Assets view from a **local dev build** (no `VERSION` stamp). Commit the refreshed `src/docs/wiki/images/cc-*.png` alongside the code.

- [ ] **Step 8: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_ops.py src/racecast.py src/ui/control-center.html src/docs/wiki/images/
git commit -m "feat(brands): Control Center download card + gallery for brand overrides"
```

---

### Task 6: Docs, wiki, command list

**Files:**
- Modify: `CLAUDE.md` (Commands list + Architecture brand-assets paragraph)
- Modify: `README.md` (command list)
- Modify: `src/docs/wiki/` — the Sheet-tab reference page (add the `Brands` tab), `League-Owner-Setup.md`, `Profiles.md`
- Test: `tests/test_wiki.py`

**Interfaces:** documentation only — no runtime code.

- [ ] **Step 1: Document the `Brands` tab in the wiki Sheet reference**

Find the wiki page that lists the Sheet tabs (Configuration/Assets/Crew/Channel/…):
```bash
grep -rln "Assets" src/docs/wiki/
```
Add a `Brands` tab entry: header `Brand | Logo`; one row per overridden/new manufacturer; the Logo cell is a Google-Drive **share link**; the Brand cell is normalized the same way as the Configuration-tab brand text (so `BMW` overrides `bmw`, a new `Cupra` adds `cupra`). Note it is **optional** — without it the committed base logos are served — and refreshed with `racecast brands` (or the Control Center "Brands → Download" card) before an event.

- [ ] **Step 2: Note brand overrides in League-Owner-Setup and Profiles**

In `src/docs/wiki/League-Owner-Setup.md`: add that a league can ship custom brand logos via the `Brands` tab, downloaded with `racecast brands`.
In `src/docs/wiki/Profiles.md`: in the export/import section, note that `profile export` now also carries the per-league brand logos (`runtime/<profile>/brands/`), like graphics/media. Add the compatibility caveat verbatim from the spec: a bundle carrying `brands/` requires a matching-or-newer build to import.

- [ ] **Step 3: Update CLAUDE.md and README command lists**

In `CLAUDE.md` Commands section, add next to `racecast graphics`/`media`:
```
python3 src/racecast.py brands            # download per-league brand-logo overrides (Sheet "Brands" tab) -> runtime/<profile>/brands/
```
In the Architecture "Broadcast graphics are pure-runtime" / `src/assets/` paragraph, add a sentence: brand logos are served **override-first** — `runtime/<profile>/brands/<asset_key>.png` (downloaded from the Sheet `Brands` tab by `get-brands.py`) wins over the committed `src/assets/brands/` base; the override travels in `profile export` as a third asset section.
In `README.md`, add `racecast brands` to the operator command list near `graphics`/`media`.

- [ ] **Step 4: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: PASS (no broken links/anchors after the edits).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md src/docs/wiki/
git commit -m "docs(brands): document the Brands sheet tab, racecast brands, and export coverage"
```

---

### Final verification

- [ ] **Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: ALL tests pass (incl. `test_brands.py`, `test_hud.py`, `test_racecast.py`, `test_profile_io.py`, `test_ui_ops.py`, `test_wiki.py`).

- [ ] **Run lint**

Run: `python3 tools/lint.py`
Expected: clean (no findings).

- [ ] **Ship-verify the build**

Run: `python3 tools/build.py`
Expected: build + self-verify pass (tokenization, blanked password, no secrets, no shell scripts, preflight present).

- [ ] **(Optional) e2e smoke** — `python3 tools/e2e.py` (synthetic mode) still green; brand serving is additive and should not regress the existing checks.

---

## Self-Review

**Spec coverage:**
- Sheet `Brands` tab + key-normalization invariant → Task 1 (`brands_from_csv` + `asset_key` pin), Task 6 (docs).
- `get-brands.py` downloader + `racecast brands` → Task 1 + Task 3.
- Override-first relay serving, no front-end change, live after OBS refresh → Task 2.
- Runtime storage `runtime/<profile>/brands/` → Task 1 (`brands_dir`), Task 2 (relay derivation).
- Profile export/import new section + compatibility caveat → Task 4 + Task 6.
- Control Center download card + wiki screenshot → Task 5.
- Tests (`brands_from_csv`, `resolve_brand_override`, precedence, profile_io round-trip + no-brands shape, getsource pin, ui op) → Tasks 1–5.
- Docs/CLAUDE.md/README/wiki + `test_wiki` → Task 6.
- Out-of-scope (per-team, live polling, SVG/JPG, profile-tree mirroring) → honored (PNG-only download, per-brand keying, runtime-only storage).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the one "locate the gallery render block" instruction (Task 5 Step 5) points at the exact existing function (`fetchAssetFiles`) and the exact element ids — acceptable, as the surrounding render code is the pattern to copy verbatim.

**Type consistency:** `resolve_brand_override(brands_dir, key)` returns `(path, ctype)|None` and is consumed via `... or resolve_asset(...)` in `_send_asset` and in the precedence test — consistent. `brands_from_csv` returns `{asset_key: drive_url}`; `safe_filename` consumes an already-normalized key — consistent (the loop iterates `brands` keys which are `asset_key` outputs). `ASSET_SECTIONS` adding `"brands"` lines up with the `sources["brands"]` key and the `assets_files_data` `"brands"` listing key.
