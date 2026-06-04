# HUD Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~13 Google-Sheets-editor browser sources in the OBS HUD with a single lightweight, relay-served overlay page that pulls sheet data as JSON and auto-refreshes.

**Architecture:** The relay (`src/relay/iro-feeds.py`) gains a `HudSource` that reads the **Overlay** tab (live values) and **Configuration** tab (team→brand text map) as gviz CSV, exposes `GET /hud/data` (JSON) and `GET /hud` (static `src/obs/hud.html`), and serves bundled flag/brand assets at `GET /hud/assets/...`. One transparent OBS browser source points at `http://127.0.0.1:8088/hud` and polls every 2–3 s.

**Tech Stack:** Python stdlib only (no framework, no package manager); vanilla HTML/CSS/JS for the overlay page. Tests are runnable scripts under `tests/` (no pytest), mirroring `tests/test_pov.py`.

**Design reference:** `docs/superpowers/specs/2026-06-04-hud-consolidation-design.md`

---

## File Structure

- `src/relay/iro-feeds.py` (modify) — add `asset_key()`, `parse_overlay()`, `parse_config_brands()`, `build_hud_data()`, `HudSource`; add routes in `make_handler`; wire into `main()`.
- `src/obs/hud.html` (create) — static overlay page (CSS layout + JS polling).
- `src/assets/flags/` (create dir) — `<country>.svg` flag assets (operator-supplied).
- `src/assets/brands/` (create dir) — `<brand>.svg` manufacturer assets (operator-supplied).
- `tests/test_hud.py` (create) — stdlib unit checks for the pure parse/build functions.
- `tools/build.py` (modify) — ship `hud.html` into the package.
- `src/obs/IRO_Endurance.json` (modify, via OBS + tokenize) — 13 HUD sources → 1.
- Google Sheet **Configuration** tab (operator) — add a `Brand Key` text column.

## Conventions to follow

- The relay module is loaded in tests via `importlib` as module `m` (see `tests/test_pov.py`). All pure functions must be module-level so tests can call `m.<fn>`.
- Keep the existing terse code style. Reuse `_send` / `_send_file` helpers in the handler.
- gviz CSV URL shape (already used at `iro-feeds.py:573-575`):
  `https://docs.google.com/spreadsheets/d/<id>/gviz/tq?tqx=out:csv&sheet=<tab>`
- Network is never hit in tests — test the **pure** functions (`parse_*`, `build_hud_data`, `asset_key`), not `HudSource.fetch`.

---

## Task 1: `asset_key()` normalization helper

Normalizes free text (country / brand) to an asset filename stem: lowercase, trimmed, internal whitespace → single `-`, drop anything other than `[a-z0-9-]`.

**Files:**
- Modify: `src/relay/iro-feeds.py` (add near the other module-level helpers, after `is_channel`, ~line 127)
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_hud.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the HUD additions. Run: python3 tests/test_hud.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_asset_key_basic():
    assert m.asset_key("GERMANY") == "germany"
    assert m.asset_key("  United Arab Emirates ") == "united-arab-emirates"
    assert m.asset_key("Porsche") == "porsche"
    assert m.asset_key("") == ""
    assert m.asset_key(None) == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL with `AttributeError: module 'irofeeds' has no attribute 'asset_key'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add after the `is_channel` helper (around line 127):

```python
def asset_key(s):
    """Normalize free text (country/brand) to an asset filename stem."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9-]", "", s)
```

(`re` is already imported at line 52.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ok t_asset_key_basic` / `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(hud): add asset_key() text→filename normalizer"
```

---

## Task 2: `parse_overlay()` — Overlay tab CSV → label/value map

Reads the Overlay tab rows. For each row whose **column B** (index 1) holds a known label, takes the value as the **first non-empty cell from column C (index 2) onward**. This naturally returns team *names* (the brand-image cell is empty in CSV).

**Files:**
- Modify: `src/relay/iro-feeds.py`
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hud.py`:

```python
OVERLAY_CSV = (
    ",,,,,,,,,\n"
    ",,,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Streamer,JeGr,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Session,Warmup,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Top,Round 4: Nurburgring 24hrs,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Bottom,GERMANY,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Round Flag,,,,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P1,,,OVO eSports #111,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P2,,,Feel Good Racing #303,,,,,\n"
    ",,,,,,,,,\n"
    ",Teams P3,,,NWR Motorsport #224,,,,,\n"
    ",,,,,,,,,\n"
    ",Race Control,,,,,,,,\n"
)


def t_parse_overlay_values():
    o = m.parse_overlay(OVERLAY_CSV)
    assert o["streamer"] == "JeGr", o
    assert o["session"] == "Warmup", o
    assert o["round_top"] == "Round 4: Nurburgring 24hrs", o
    assert o["country"] == "GERMANY", o
    assert o["teams"] == ["OVO eSports #111", "Feel Good Racing #303",
                          "NWR Motorsport #224"], o
    assert o["race_control"] == "", o


def t_parse_overlay_missing_rows_safe():
    o = m.parse_overlay(",Streamer,JeGr,,,,,,,\n")
    assert o["streamer"] == "JeGr"
    assert o["teams"] == ["", "", ""]
    assert o["country"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL with `AttributeError: ... 'parse_overlay'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add below `asset_key`:

```python
OVERLAY_LABELS = {
    "streamer": "streamer", "session": "session",
    "round top": "round_top", "round bottom": "country",
    "race control": "race_control",
}


def _first_value(row, start=2):
    for c in range(start, len(row)):
        v = (row[c] or "").strip()
        if v:
            return v
    return ""


def parse_overlay(text):
    """Overlay tab CSV -> {streamer, session, round_top, country,
    race_control, teams:[p1,p2,p3]}. Label is column B; value is the first
    non-empty cell from column C on."""
    out = {v: "" for v in OVERLAY_LABELS.values()}
    teams = {"teams p1": 0, "teams p2": 1, "teams p3": 2}
    out["teams"] = ["", "", ""]
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        label = (row[1] or "").strip().lower()
        if label in OVERLAY_LABELS:
            out[OVERLAY_LABELS[label]] = _first_value(row)
        elif label in teams:
            out["teams"][teams[label]] = _first_value(row)
    return out
```

(`csv` and `io` are already imported at line 52.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(hud): parse Overlay tab CSV into label/value map"
```

---

## Task 3: `parse_config_brands()` — Configuration tab CSV → {team: brand_key}

Reads the Configuration tab. Locates the `Teams` and `Brand Key` columns **by header name** in row 1 (robust to column position), then builds a `{team_name: asset_key(brand)}` map.

**Files:**
- Modify: `src/relay/iro-feeds.py`
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hud.py`:

```python
CONFIG_CSV = (
    "Stints,Streamers,Session,Round,Country,Flag,Teams,,Brands,Race Control,Brand Key\n"
    "Stint 1,JeGr,Qualifier,Round 1,UNITED STATES,,OVO eSports #111,,,Formation Lap,Porsche\n"
    "Stint 2,GT45,Race,Round 2,AUSTRALIA,,Feel Good Racing #303,,,Final Lap,Porsche\n"
    "Stint 3,,,,,,NWR Motorsport #224,,,,Ferrari\n"
)


def t_parse_config_brands():
    b = m.parse_config_brands(CONFIG_CSV)
    assert b["OVO eSports #111"] == "porsche", b
    assert b["Feel Good Racing #303"] == "porsche", b
    assert b["NWR Motorsport #224"] == "ferrari", b


def t_parse_config_brands_missing_columns_safe():
    assert m.parse_config_brands("a,b,c\n1,2,3\n") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL with `AttributeError: ... 'parse_config_brands'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add below `parse_overlay`:

```python
def parse_config_brands(text):
    """Configuration tab CSV -> {team_name: brand_key}. Columns are located
    by header name ('Teams', 'Brand Key') so positions can change."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}
    header = [(h or "").strip().lower() for h in rows[0]]
    try:
        ti = header.index("teams")
        bi = header.index("brand key")
    except ValueError:
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) <= max(ti, bi):
            continue
        name = (row[ti] or "").strip()
        brand = asset_key(row[bi])
        if name and brand:
            out[name] = brand
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(hud): parse Configuration tab into team→brand map"
```

---

## Task 4: `build_hud_data()` — assemble the `/hud/data` JSON contract

Pure function combining an Overlay map and a brand map into the final contract. No network.

**Files:**
- Modify: `src/relay/iro-feeds.py`
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hud.py`:

```python
def t_build_hud_data():
    overlay = m.parse_overlay(OVERLAY_CSV)
    brands = m.parse_config_brands(CONFIG_CSV)
    d = m.build_hud_data(overlay, brands)
    assert d["streamer"] == "JeGr"
    assert d["session"] == "Warmup"
    assert d["round"]["top"] == "Round 4: Nurburgring 24hrs"
    assert d["round"]["country"] == "GERMANY"
    assert d["round"]["flagKey"] == "germany"
    assert d["teams"][0] == {"name": "OVO eSports #111", "brandKey": "porsche"}
    assert d["teams"][2] == {"name": "NWR Motorsport #224", "brandKey": "ferrari"}
    assert d["raceControl"] == ""


def t_build_hud_data_unknown_brand_blank():
    overlay = m.parse_overlay(",Teams P1,,,Mystery Team #0,,,,,\n")
    d = m.build_hud_data(overlay, {})
    assert d["teams"][0] == {"name": "Mystery Team #0", "brandKey": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL with `AttributeError: ... 'build_hud_data'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add below `parse_config_brands`:

```python
def build_hud_data(overlay, brands):
    """Combine an Overlay map + {team: brand_key} into the /hud/data contract."""
    return {
        "streamer": overlay.get("streamer", ""),
        "session": overlay.get("session", ""),
        "round": {
            "top": overlay.get("round_top", ""),
            "country": overlay.get("country", ""),
            "flagKey": asset_key(overlay.get("country", "")),
        },
        "teams": [{"name": n, "brandKey": brands.get(n, "")}
                  for n in overlay.get("teams", ["", "", ""])],
        "raceControl": overlay.get("race_control", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(hud): build /hud/data JSON contract from parsed sheets"
```

---

## Task 5: `HudSource` — fetch both tabs, cache last-good, expose `data()`

Wraps fetching the Overlay + Configuration CSVs and building the contract, with an in-memory last-good value plus a JSON cache file (same robustness idea as `ScheduleSource`). The pure builders are already tested; this class is thin glue.

**Files:**
- Modify: `src/relay/iro-feeds.py`
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hud.py` (tests glue without network by overriding `_fetch`):

```python
def t_hudsource_data_uses_builders(tmp_path=None):
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.refresh() is True
    data = hs.data()
    assert data["streamer"] == "JeGr"
    assert data["teams"][0]["brandKey"] == "porsche"


def t_hudsource_keeps_last_good_on_failure():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    def boom(url, timeout=10):
        raise RuntimeError("sheet down")
    hs._fetch = boom
    assert hs.refresh() is False
    assert hs.data()["streamer"] == "JeGr"   # last-good preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL with `AttributeError: ... 'HudSource'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add after the `ScheduleSource` class (after line ~262):

```python
class HudSource:
    """Reads the Overlay + Configuration tabs and serves the /hud/data dict
    with last-good caching (mirrors ScheduleSource robustness)."""
    EMPTY = {"streamer": "", "session": "",
             "round": {"top": "", "country": "", "flagKey": ""},
             "teams": [{"name": "", "brandKey": ""}] * 3, "raceControl": ""}

    def __init__(self, overlay_url, config_url, cache_path):
        self.overlay_url = overlay_url
        self.config_url = config_url
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self._data = None
        self.last_ok = None
        self.last_error = None
        self._load_cache()

    @staticmethod
    def _fetch(url, timeout=10):
        req = Request(url, headers={"User-Agent": "iro-feeds/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (OSError, ValueError):
            self._data = None

    def refresh(self, timeout=10):
        try:
            overlay = parse_overlay(self._fetch(self.overlay_url, timeout))
            brands = parse_config_brands(self._fetch(self.config_url, timeout))
            data = build_hud_data(overlay, brands)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            self._data = data
            self.last_ok = time.time()
            self.last_error = None
        try:
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass
        return True

    def data(self):
        with self.lock:
            return self._data if self._data is not None else dict(self.EMPTY)

    def health(self):
        with self.lock:
            return {"last_ok_age_s": (round(time.time() - self.last_ok, 1)
                                      if self.last_ok else None),
                    "last_error": self.last_error}
```

(`json`, `threading`, `time` already imported at line 52; `Request`/`urlopen` at line 55.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(hud): HudSource with last-good cache"
```

---

## Task 6: HTTP routes — `/hud`, `/hud/data`, `/hud/assets/...`

Extend `make_handler` to accept the HUD source, the `hud.html` path, and the assets dir, and add three routes. Asset serving is locked to two subdirs with a strict filename allowlist (no path traversal).

**Files:**
- Modify: `src/relay/iro-feeds.py:443-481` (`make_handler`)

- [ ] **Step 1: Add a content-type helper + route logic**

Change the signature at line 443:

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None):
```

Add an asset filename guard as a module-level constant near the other regexes (top of file, after `CHANNEL_RE`):

```python
ASSET_NAME_RE = re.compile(r"^[a-z0-9-]+\.(svg|png)$")
ASSET_CTYPE = {"svg": "image/svg+xml", "png": "image/png"}
```

Inside `do_GET` (after the existing `panel` branch, before the `next` branch), add. Assets live in `flags/`/`brands/` subdirs, so the asset path is `/hud/assets/<sub>/<file>` (4 parts):

```python
                if p == ["hud"]:
                    if not (hud_source and hud_path):
                        return self._send({"error": "hud disabled"}, 404)
                    return self._send_file(hud_path, "text/html; charset=utf-8")
                if p == ["hud", "data"]:
                    if not hud_source:
                        return self._send({"error": "hud disabled"}, 404)
                    return self._send(hud_source.data())
                if len(p) == 4 and p[:2] == ["hud", "assets"]:
                    return self._send_asset(assets_dir, p[2], p[3])
```

Add the `_send_asset` method to the handler class (next to `_send_file`):

```python
        def _send_asset(self, assets_dir, sub, name):
            if not assets_dir or sub not in ("flags", "brands") \
                    or not ASSET_NAME_RE.match(name):
                return self._send({"error": "bad asset"}, 404)
            path = os.path.join(assets_dir, sub, name)
            ext = name.rsplit(".", 1)[1]
            self._send_file(path, ASSET_CTYPE[ext])
```

(`_send_file` already returns a 404 JSON if the file is missing.)

- [ ] **Step 2: Manual smoke test (no automated test — handler needs a socket)**

This task is verified end-to-end in Task 9. For now just confirm the module still imports:

Run: `python3 -c "import importlib.util,os; s=importlib.util.spec_from_file_location('m','src/relay/iro-feeds.py'); mm=importlib.util.module_from_spec(s); s.loader.exec_module(mm); print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: Run the existing tests to ensure nothing broke**

Run: `python3 tests/test_hud.py && python3 tests/test_pov.py`
Expected: both print `ALL PASS`

- [ ] **Step 4: Commit**

```bash
git add src/relay/iro-feeds.py
git commit -m "feat(hud): serve /hud, /hud/data and /hud/assets routes"
```

---

## Task 7: Wire `HudSource` into `main()`

Add CLI args, build the two gviz URLs, discover `hud.html` + assets dir, start a HUD poller, and pass everything to `make_handler`. HUD derivation is disabled when `--sheet-csv-url` is used (no tab to point at) or `--no-hud` is set — same rule as POV.

**Files:**
- Modify: `src/relay/iro-feeds.py` (`main()`, lines ~509–650)

- [ ] **Step 1: Add CLI args**

After the `--no-panel` arg (line 537), add:

```python
    ap.add_argument("--overlay-tab", default="Overlay",
                    help="Google-Sheet tab with the live HUD values (default 'Overlay').")
    ap.add_argument("--config-tab", default="Configuration",
                    help="Google-Sheet tab with the team→brand map (default 'Configuration').")
    ap.add_argument("--hud-poll", type=int, default=5,
                    help="HUD sheet refresh interval in seconds (default 5).")
    ap.add_argument("--no-hud", action="store_true",
                    help="Do not serve the HUD overlay at /hud.")
```

- [ ] **Step 2: Build the HudSource + discover hud.html and assets dir**

After the `panel_path` discovery block (line ~611), add:

```python
    # HUD overlay: derived from sheet-id/tab (disabled with a custom CSV URL).
    hud_source = None
    hud_path = None
    assets_dir = os.path.abspath(os.path.join(here, "..", "assets"))
    if not args.no_hud and not args.sheet_csv_url:
        base = f"https://docs.google.com/spreadsheets/d/{args.sheet_id}/gviz/tq?tqx=out:csv&sheet="
        overlay_url = base + quote(args.overlay_tab)
        config_url = base + quote(args.config_tab)
        hud_cache = os.path.join(runtime, "hud.cache.json")
        hud_source = HudSource(overlay_url, config_url, hud_cache)
        hud_source.refresh()   # non-fatal: keeps last-good / empty if unreachable
        for cand in (os.path.join(here, "hud.html"),
                     os.path.join(here, "..", "hud.html"),
                     os.path.join(here, "..", "obs", "hud.html")):
            if os.path.exists(cand):
                hud_path = os.path.abspath(cand); break
        if not hud_path:
            print("WARN: hud.html not found — /hud will 404 (assets dir: "
                  f"{assets_dir}).")
```

- [ ] **Step 3: Start a HUD poller and pass to make_handler**

Replace the `make_handler(relay, panel_path)` call (line 626):

```python
    if hud_source:
        threading.Thread(target=poller, args=(hud_source, args.hud_poll, stop_evt),
                         daemon=True).start()
    httpd = ThreadingHTTPServer((args.bind, args.http_port),
                                make_handler(relay, panel_path, hud_source, hud_path, assets_dir))
```

(The `poller` helper already calls `source.refresh()` on each tick — `HudSource.refresh` matches that interface.)

- [ ] **Step 4: Add a startup log line**

After the `Director panel` print block (line ~648), add:

```python
    if hud_source and hud_path:
        host = "127.0.0.1" if args.bind in ("127.0.0.1", "localhost") else "<this-machine-ip>"
        print(f"  HUD overlay: http://{host}:{args.http_port}/hud  "
              f"(tabs '{args.overlay_tab}'/'{args.config_tab}', refresh {args.hud_poll}s)")
```

- [ ] **Step 5: Verify import + existing tests still pass**

Run: `python3 tests/test_hud.py && python3 tests/test_pov.py`
Expected: both `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add src/relay/iro-feeds.py
git commit -m "feat(hud): wire HudSource + poller into the relay main()"
```

---

## Task 8: `src/obs/hud.html` — the overlay page

A single transparent page that polls `/hud/data` every 2.5 s and fills the elements. Positions are placeholders to be aligned to the current overlay design during Task 10; the data binding is what matters here. Race Control is a plain static line.

**Files:**
- Create: `src/obs/hud.html`

- [ ] **Step 1: Create the file**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IRO HUD</title>
<style>
  :root { --green: #5dd039; }
  html, body { margin: 0; width: 1920px; height: 1080px;
    background: transparent; overflow: hidden;
    font-family: "Arial Narrow", Arial, sans-serif; color: #fff; }
  .hud-el { position: absolute; display: flex; align-items: center; }
  .hud-el.empty { display: none; }
  #streamer   { left: 270px; top: 60px;  font-size: 48px; font-weight: 700; color:#111; }
  #session    { left: 270px; top: 180px; font-size: 56px; font-style: italic; font-weight:700; color:#111; }
  #round-top  { left: 270px; top: 300px; font-size: 32px; font-style: italic; font-weight:700; }
  #round-country { left: 270px; top: 380px; font-size: 32px; font-weight: 700; }
  #round-flag { left: 270px; top: 470px; height: 60px; }
  #round-flag img { height: 60px; }
  .team { font-size: 30px; font-weight: 700; }
  .team img { height: 56px; width: 56px; object-fit: contain; margin-right: 16px; }
  #team0 { left: 270px; top: 560px; }
  #team1 { left: 270px; top: 670px; }
  #team2 { left: 270px; top: 780px; }
  #race-control { left: 270px; top: 900px; font-size: 30px; font-weight: 700; }
</style>
</head>
<body>
  <div id="streamer" class="hud-el"></div>
  <div id="session" class="hud-el"></div>
  <div id="round-top" class="hud-el"></div>
  <div id="round-country" class="hud-el"></div>
  <div id="round-flag" class="hud-el"><img alt=""></div>
  <div id="team0" class="hud-el team"><img alt=""><span></span></div>
  <div id="team1" class="hud-el team"><img alt=""><span></span></div>
  <div id="team2" class="hud-el team"><img alt=""><span></span></div>
  <div id="race-control" class="hud-el"></div>

<script>
  const POLL_MS = 2500;

  function setText(id, value) {
    const el = document.getElementById(id);
    el.textContent = value || "";
    el.classList.toggle("empty", !value);
  }
  function setImg(containerId, key, sub) {
    const el = document.getElementById(containerId);
    const img = el.querySelector("img");
    if (key) { img.src = `/hud/assets/${sub}/${key}.svg`; el.classList.remove("empty"); }
    else { img.removeAttribute("src"); el.classList.add("empty"); }
  }
  function setTeam(i, team) {
    const el = document.getElementById("team" + i);
    const name = (team && team.name) || "";
    el.querySelector("span").textContent = name;
    const img = el.querySelector("img");
    if (team && team.brandKey) img.src = `/hud/assets/brands/${team.brandKey}.svg`;
    else img.removeAttribute("src");
    el.classList.toggle("empty", !name);
  }

  async function tick() {
    try {
      const r = await fetch("/hud/data", { cache: "no-store" });
      const d = await r.json();
      setText("streamer", d.streamer);
      setText("session", d.session);
      setText("round-top", d.round && d.round.top);
      setText("round-country", d.round && d.round.country);
      setImg("round-flag", d.round && d.round.flagKey, "flags");
      (d.teams || []).forEach((t, i) => { if (i < 3) setTeam(i, t); });
      setText("race-control", d.raceControl);
    } catch (e) { /* keep last good frame on transient errors */ }
  }
  tick();
  setInterval(tick, POLL_MS);
</script>
</body>
</html>
```

- [ ] **Step 2: Sanity-check it serves (manual, optional now — full check in Task 9)**

Run: `python3 -c "open('src/obs/hud.html').read(); print('readable')"`
Expected: `readable`

- [ ] **Step 3: Commit**

```bash
git add src/obs/hud.html
git commit -m "feat(hud): add relay-served overlay page (polls /hud/data)"
```

---

## Task 9: Ship `hud.html` in the build + integration smoke test

**Files:**
- Modify: `tools/build.py:43` (next to the `director-panel.html` copy)

- [ ] **Step 1: Add the copy line**

In `tools/build.py`, right after `cp("director/director-panel.html", "director-panel.html")` (line 43), add:

```python
    cp("obs/hud.html", "hud.html")
```

(The `assets` tree is already copied at line 45, so flags/brands ship automatically.)

- [ ] **Step 2: Live integration smoke test**

Start the relay against the real sheet (requires `.env` with `IRO_SHEET_ID`, plus `yt-dlp`/`streamlink` installed):

Run:
```bash
python3 tools/run-relay.py --no-pov &
sleep 8
curl -s http://127.0.0.1:8088/hud/data
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8088/hud
kill %1
```
Expected: `/hud/data` prints JSON with `streamer`/`teams`/`round`; `/hud` returns `200`.

- [ ] **Step 3: Run the full build + verify**

Run: `python3 tools/build.py`
Expected: build completes; verify step passes (no `BUILD VERIFY FAILED`); `dist/IRO_Broadcast_Package/hud.html` exists.

- [ ] **Step 4: Commit**

```bash
git add tools/build.py
git commit -m "build(hud): ship hud.html in the distributable package"
```

---

## Task 10: Operator integration — sheet column, assets, OBS swap

These steps happen in the Google Sheet and the OBS app (not in code), and require the operator's logos. Done once per machine; the OBS collection change is then folded back into git via the existing tokenize flow.

**Files:**
- Create: `src/assets/flags/*.svg`, `src/assets/brands/*.svg`
- Modify (via OBS export + tokenize): `src/obs/IRO_Endurance.json`
- Google Sheet **Configuration** tab

- [ ] **Step 1: Add the `Brand Key` column in the Configuration tab**

Append a column with header exactly `Brand Key`. For each team row, enter the
brand as text matching its logo filename stem (e.g. `Porsche` → asset
`brands/porsche.svg`; case/spacing is normalized by `asset_key`). Leave blank to
hide the brand logo for that team.

- [ ] **Step 2: Export logos into `src/assets/`**

Place the manufacturer crests in `src/assets/brands/<key>.svg` (one per distinct
`Brand Key`, e.g. `porsche.svg`, `ferrari.svg`) and the country flags in
`src/assets/flags/<country>.svg` (one per Country value, e.g. `germany.svg`,
`united-states.svg`). Filenames must be the `asset_key`-normalized stem
(lowercase, spaces→`-`). PNG is also accepted (`.png`) — adjust the `<img>` src
extension in `hud.html` if not using SVG.

- [ ] **Step 3: Verify assets resolve against a running relay**

Run (relay running from Task 9):
```bash
curl -s -o /dev/null -w "flag %{http_code}\n" http://127.0.0.1:8088/hud/assets/flags/germany.svg
curl -s -o /dev/null -w "brand %{http_code}\n" http://127.0.0.1:8088/hud/assets/brands/porsche.svg
```
Expected: both `200`.

- [ ] **Step 4: Swap the OBS sources**

In OBS, in the HUD/Overlay scene: add one **Browser** source named `HUD Overlay`,
URL `http://127.0.0.1:8088/hud`, 1920×1080, transparent background; uncheck
"Shutdown source when not visible" so it stays warm. Position/scale it full-frame.
Then **delete** the 13 old sheet browser sources (Stint, Streamer, Session, Round
Track/Flag/Country, Race Control, Team 1–3 Brand/Name) and their chroma/colour-key
filters. Verify the overlay renders against a running relay; nudge the CSS
positions in `src/obs/hud.html` until elements line up with the previous look.

- [ ] **Step 5: Fold the OBS change back into git**

Export the collection from OBS, then re-tokenize:

Run: `python3 tools/tokenize-obs.py <exported.json> src/obs/IRO_Endurance.json`
Expected: tokenized collection written; `git diff` shows the 13 sources replaced
by one `HUD Overlay` source and no real secrets/paths.

- [ ] **Step 6: Final build + commit**

```bash
python3 tools/build.py
git add src/assets src/obs/IRO_Endurance.json src/obs/hud.html
git commit -m "feat(hud): consolidate 13 sheet sources into one HUD overlay"
```

---

## Task 11: Update operator docs

**Files:**
- Modify: `src/docs/wiki/OBS-Setup.md`, `src/docs/README_SETUP.md`
- Modify: `CLAUDE.md` (the relay endpoints list + architecture note)

- [ ] **Step 1: Document the new endpoint + workflow**

In `src/docs/wiki/OBS-Setup.md` and `README_SETUP.md`, describe: the single
`HUD Overlay` browser source pointing at `http://127.0.0.1:8088/hud`; that HUD
content is edited in the **Overlay** tab and brands in the **Configuration** tab's
`Brand Key` column; and that flags/brands come from `src/assets/`. Note the
`--no-hud`, `--overlay-tab`, `--config-tab`, `--hud-poll` flags.

- [ ] **Step 2: Update `CLAUDE.md`**

Add `/hud`, `/hud/data`, `/hud/assets/...` to the relay endpoints description and a
one-line note in the architecture section that the HUD is a single relay-served
page (replacing the old per-cell browser sources).

- [ ] **Step 3: Commit**

```bash
git add src/docs CLAUDE.md
git commit -m "docs(hud): document single relay-served HUD overlay"
```

---

## Self-Review notes

- **Spec coverage:** host=relay (Tasks 5–7), data contract (Tasks 2–4), images via
  bundled assets + text keys (Tasks 1,3,6,10), polling/no-reload (Tasks 7–8),
  last-good robustness (Task 5), one OBS source (Task 10), tests (Tasks 1–5),
  build/ship (Task 9), docs (Task 11), Stagetimer untouched (not in scope).
- **Type consistency:** `parse_overlay` keys (`round_top`, `country`,
  `race_control`, `teams`) are consumed exactly in `build_hud_data`; contract keys
  (`round.flagKey`, `teams[].brandKey`, `raceControl`) match `hud.html`’s
  `d.round.flagKey`, `t.brandKey`, `d.raceControl`. `HudSource.refresh()` matches
  the `poller()` `source.refresh()` interface.
- **Network isolation:** all unit tests target pure functions or override
  `HudSource._fetch`; no test hits Google.
