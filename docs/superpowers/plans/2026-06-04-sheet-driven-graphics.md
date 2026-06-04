# Sheet-Driven Graphics + Weather Overlays — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive every broadcast still-graphic from the Google Sheet **Assets** tab — downloaded into `runtime/graphics/` as `<Label>.png`, never committed — exactly like the Intro/Outro clips, and add three weather graphics as OBS sources each switchable by its own Companion button.

**Architecture:** New runtime token `__IRO_GRAPHICS__` → `runtime/graphics/` (package: `<pkg>/graphics/`), parallel to `__IRO_MEDIA__`. A new `src/relay/get-graphics.py` reads the Assets tab and downloads each Drive-link row as `<Label>.png` (the Sheet label *is* the filename — no mapping table). The committed top-level PNGs in `src/assets/` are removed (pure runtime); `flags/`+`brands/` stay. Three weather `image_source`s become hidden full-screen Stint overlays toggled by Companion.

**Tech Stack:** Python 3 stdlib only (Drive download via `urllib`, no `yt-dlp`). OBS scene-collection JSON (4-space indent). Companion `.companionconfig` JSON (1-space indent).

**Spec:** `docs/superpowers/specs/2026-06-04-sheet-driven-graphics-design.md`

**Canonical graphic labels (= filenames `<Label>.png`):** `Overlay`, `Standings`, `Schedule`, `Race Results`, `Quali Results`, `Race Weather 1`, `Race Weather 2`, `Quali Weather`, `Post Race Interviews`, `Standby`.

**Branch:** `feat/sheet-driven-graphics` (already created; spec committed).

---

## Task 1: `get-graphics.py` + unit tests

**Files:**
- Create: `src/relay/get-graphics.py`
- Test: `tests/test_graphics.py`

- [ ] **Step 1: Write the failing test** — `tests/test_graphics.py`

```python
#!/usr/bin/env python3
"""Stdlib unit checks for get-graphics.py. Run: python3 tests/test_graphics.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "getgraphics", os.path.join(ROOT, "src", "relay", "get-graphics.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_drive_id_file_form():
    assert m.drive_id("https://drive.google.com/file/d/ABC_123-x/view?usp=sharing") == "ABC_123-x"


def t_drive_id_id_form():
    assert m.drive_id("https://drive.google.com/uc?export=download&id=ZZ9_y") == "ZZ9_y"


def t_drive_id_none():
    assert m.drive_id("https://youtu.be/AAA") is None
    assert m.drive_id("") is None


def t_to_download_url():
    assert m.to_download_url("XYZ") == "https://drive.google.com/uc?export=download&id=XYZ"


def t_safe_filename_basic():
    assert m.safe_filename("Race Results") == "Race Results.png"
    assert m.safe_filename("  Standings ") == "Standings.png"


def t_safe_filename_rejects():
    assert m.safe_filename("") is None
    assert m.safe_filename("a/b") is None
    assert m.safe_filename("a\\b") is None
    assert m.safe_filename("bad\x01") is None


def t_graphics_from_csv_picks_drive_skips_youtube():
    rows = [["Intro Video", "https://youtu.be/AAA"],
            ["Standings", "https://drive.google.com/file/d/SID/view?usp=sharing"],
            ["Schedule", "https://drive.google.com/file/d/SCH/view"]]
    assert m.graphics_from_csv(rows) == {
        "Standings": "https://drive.google.com/file/d/SID/view?usp=sharing",
        "Schedule": "https://drive.google.com/file/d/SCH/view"}, m.graphics_from_csv(rows)


def t_graphics_from_csv_label_verbatim_and_empty():
    rows = [["Race Weather 1", "https://drive.google.com/file/d/W1/view"],
            ["", "https://drive.google.com/file/d/X/view"],
            ["NoUrl", ""]]
    assert m.graphics_from_csv(rows) == {
        "Race Weather 1": "https://drive.google.com/file/d/W1/view"}


def t_graphics_dir_repo():
    assert m.graphics_dir("/x/src/relay") == "/x/runtime/graphics", m.graphics_dir("/x/src/relay")


def t_graphics_dir_pkg():
    assert m.graphics_dir("/x/IRO_Broadcast_Package/relay") == \
        "/x/IRO_Broadcast_Package/graphics"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_graphics.py`
Expected: FAIL — `ModuleNotFoundError` / `FileNotFoundError` for `get-graphics.py` (file not yet created).

- [ ] **Step 3: Create `src/relay/get-graphics.py`**

```python
#!/usr/bin/env python3
"""Download the broadcast still-graphics for OBS from the Google Sheet 'Assets' tab.

Each Assets row whose value cell is a Google-Drive share link is downloaded as
'<Label>.png' into the graphics dir (repo: <repo>/runtime/graphics ; distributed
package: <package>/graphics). The Sheet label IS the filename — there is no mapping
table, so keep Sheet labels filesystem-clean. YouTube rows (Intro/Outro) are skipped;
those are handled by get-media.py. Never stored under src/, never committed.

Usage: python3 get-graphics.py [--out DIR] [--sheet-id ID] [--assets-tab NAME]
       [--only "Label[,Label...]"]
"""
import argparse, csv, io, os, re, sys
from urllib.parse import quote
from urllib.request import Request, urlopen


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with a
    .git/.env.example marker). KEEP IN SYNC with the copies in iro-feeds.py,
    setup-assets.py and get-media.py."""
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
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


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


def safe_filename(label):
    """'<trimmed label>.png', or None if the label is empty or contains a path
    separator / control char. Spaces are allowed (OBS already uses them)."""
    name = (label or "").strip().strip(".")
    if not name or "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        return None
    return f"{name}.png"


def graphics_from_csv(rows):
    """Assets-tab rows -> {label: drive_url} for every row whose first non-empty value
    cell is a Google-Drive link. YouTube / non-Drive rows are skipped. Label verbatim."""
    out = {}
    for row in rows:
        if not row:
            continue
        label = (row[0] or "").strip()
        if not label:
            continue
        for cell in row[1:]:
            v = (cell or "").strip()
            if not v:
                continue
            if "drive.google.com" in v and drive_id(v):
                out[label] = v
            break  # only the first non-empty value cell matters
    return out


def graphics_dir(here):
    """Where graphics live when --out is not given. Mirrors get-media.media_dir():
    repo (src/relay) -> <repo>/runtime/graphics ; package (relay) -> <pkg>/graphics."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "graphics")
    return os.path.join(os.path.dirname(here), "graphics")


def fetch_assets_csv(sheet_id, tab, timeout=15):
    """Fetch the Assets tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "iro-graphics/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(url, out_path, timeout=60):
    """GET a Drive file to out_path as a PNG. Handles the large-file confirm
    interstitial. Writes atomically; verifies the PNG signature before committing."""
    req = Request(url, headers={"User-Agent": "iro-graphics/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    if ctype.startswith("text/html"):
        m = re.search(rb"confirm=([0-9A-Za-z_-]+)", data)
        if not m:
            raise RuntimeError("Drive returned an HTML interstitial with no confirm token")
        req2 = Request(url + "&confirm=" + m.group(1).decode(),
                       headers={"User-Agent": "iro-graphics/1.0"})
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
    ap.add_argument("--out", default=graphics_dir(here),
                    help="Target dir for <Label>.png files (default: graphics_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env IRO_SHEET_ID.")
    ap.add_argument("--assets-tab", default="Assets")
    ap.add_argument("--only", default=None,
                    help="Comma-separated labels to fetch (default: all graphic rows).")
    a = ap.parse_args()

    if not a.sheet_id:
        sys.exit("ERROR: no Sheet ID (set IRO_SHEET_ID in .env or pass --sheet-id).")
    try:
        csv_text = fetch_assets_csv(a.sheet_id, a.assets_tab)
    except Exception as e:
        sys.exit(f"ERROR: could not read sheet Assets tab: {e}")

    graphics = graphics_from_csv(list(csv.reader(io.StringIO(csv_text))))
    if a.only:
        wanted = {x.strip() for x in a.only.split(",") if x.strip()}
        graphics = {k: v for k, v in graphics.items() if k in wanted}
    if not graphics:
        sys.exit("ERROR: no graphic (Drive-link) rows found in the Assets tab.")

    os.makedirs(a.out, exist_ok=True)
    failed = []
    for label in sorted(graphics):
        fname = safe_filename(label)
        if not fname:
            print(f"WARNING: skipping unsafe label {label!r}")
            failed.append(label)
            continue
        out_path = os.path.join(a.out, fname)
        print(f"Downloading {label}: {fname}")
        try:
            download(to_download_url(drive_id(graphics[label])), out_path)
            print(f"OK -> {out_path}")
        except Exception as e:
            print(f"WARNING: download failed for {label}: {e}")
            failed.append(label)

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_graphics.py`
Expected: `ok  t_*` for all 9 functions, then `ALL PASS`.

- [ ] **Step 5: Smoke-test a real fetch** (network)

Run: `python3 src/relay/get-graphics.py --out runtime/graphics`
Expected: `Downloading …` / `OK -> runtime/graphics/<Label>.png` for all 10 labels, exit 0. Confirm: `ls runtime/graphics` shows 10 `.png` files (incl. `Schedule.png`, `Standby.png`, `Race Weather 1.png`, `Race Weather 2.png`, `Quali Weather.png`).

- [ ] **Step 6: Commit**

```bash
git add src/relay/get-graphics.py tests/test_graphics.py
git commit -m "feat(graphics): get-graphics.py fetches Assets-tab graphics into runtime"
```

---

## Task 2: `setup-assets.py` resolves `__IRO_GRAPHICS__`

**Files:**
- Modify: `src/setup-assets.py`

- [ ] **Step 1: Add the token, helper, and import**

In `src/setup-assets.py`, change the imports line `import argparse, json, os, sys` to:

```python
import argparse, json, os, re, sys
```

After `MEDIA_TOKEN = "__IRO_MEDIA__"` add:

```python
GRAPHICS_TOKEN = "__IRO_GRAPHICS__"
```

After the `media_dir(base)` function add:

```python
def graphics_dir(base):
    """Default graphics dir. setup-assets.py sits at src/ (repo) or <pkg>/ (package):
    repo (base basename 'src') -> <repo>/runtime/graphics ; package -> <base>/graphics."""
    if os.path.basename(base) == "src":
        return os.path.join(os.path.dirname(base), "runtime", "graphics")
    return os.path.join(base, "graphics")
```

- [ ] **Step 2: Add the `--graphics` arg**

Immediately after the `--media` argument block add:

```python
    ap.add_argument("--graphics", default=graphics_dir(base),
                    help="Folder with the broadcast graphics (<Label>.png) for the "
                         "image sources (replaces __IRO_GRAPHICS__). Default: graphics_dir().")
```

- [ ] **Step 3: Make ASSETS mapping conditional and add the GRAPHICS block**

Replace this line:

```python
    mapping = {ASSETS_TOKEN: a.assets}
```

with:

```python
    mapping = {}
    if ASSETS_TOKEN in raw:
        mapping[ASSETS_TOKEN] = a.assets
```

Then, immediately after the `if MEDIA_TOKEN in raw:` block (the one that warns about missing intro/outro clips) add:

```python
    if GRAPHICS_TOKEN in raw:
        mapping[GRAPHICS_TOKEN] = a.graphics
        refs = sorted(set(re.findall(r"__IRO_GRAPHICS__/([^\"\\]+\.png)", raw)))
        missing = [f for f in refs if not os.path.isfile(os.path.join(a.graphics, f))]
        if missing:
            print(f"  WARNING: graphic(s) missing in {a.graphics}: "
                  f"{', '.join(missing)} — run get-graphics.py (OBS shows black "
                  "until then).")
```

- [ ] **Step 4: Fix the confirmation prints**

Replace this line:

```python
    print(f"  Image paths now point to: {a.assets}")
```

with:

```python
    if ASSETS_TOKEN in mapping:
        print(f"  Asset paths now point to: {a.assets}")
```

And immediately after the `if MEDIA_TOKEN in mapping:` print block add:

```python
    if GRAPHICS_TOKEN in mapping:
        print(f"  Graphics dir: {a.graphics}")
```

- [ ] **Step 5: Verify it parses and runs**

Run: `python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json`
Expected (collection still uses `__IRO_ASSETS__` at this point — that changes in Task 3): `OK -> runtime/IRO_Endurance.import.json` and the existing sheet/timer/media lines print without error.

- [ ] **Step 6: Commit**

```bash
git add src/setup-assets.py
git commit -m "feat(graphics): setup-assets resolves __IRO_GRAPHICS__ with missing-file warning"
```

---

## Task 3: OBS collection — retokenise, rename, add weather, drop committed PNGs

**Files:**
- Modify: `src/obs/IRO_Endurance.json`
- Create: `tools/add_weather_sources.py`
- Delete: `src/assets/Overlay.png`, `src/assets/Post Race Interviews.png`, `src/assets/Quali Results.png`, `src/assets/Race Results.png`, `src/assets/Season Schedule.png`, `src/assets/Standings.png`, `src/assets/YT-IRO-Race.png`

- [ ] **Step 1: One-time retokenise + rename migration**

Run this once (heredoc; not a shipped script):

```bash
python3 - <<'PY'
import json
P = "src/obs/IRO_Endurance.json"
d = json.load(open(P, encoding="utf-8"))
FILE = {
    "__IRO_ASSETS__/Overlay.png": "__IRO_GRAPHICS__/Overlay.png",
    "__IRO_ASSETS__/Post Race Interviews.png": "__IRO_GRAPHICS__/Post Race Interviews.png",
    "__IRO_ASSETS__/Quali Results.png": "__IRO_GRAPHICS__/Quali Results.png",
    "__IRO_ASSETS__/Race Results.png": "__IRO_GRAPHICS__/Race Results.png",
    "__IRO_ASSETS__/Season Schedule.png": "__IRO_GRAPHICS__/Schedule.png",
    "__IRO_ASSETS__/Standings.png": "__IRO_GRAPHICS__/Standings.png",
    "__IRO_ASSETS__/YT-IRO-Race.png": "__IRO_GRAPHICS__/Standby.png",
}
for s in d["sources"]:
    st = s.get("settings") or {}
    f = st.get("file")
    if isinstance(f, str) and f in FILE:
        st["file"] = FILE[f]
    if s.get("name") == "Season Schedule":
        s["name"] = "Schedule"
for s in d["sources"]:
    if s.get("id") == "scene":
        for it in s["settings"].get("items", []):
            if it.get("name") == "Season Schedule":
                it["name"] = "Schedule"
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
print("retokenised + renamed Season Schedule -> Schedule")
PY
```

Expected: `retokenised + renamed Season Schedule -> Schedule`. Verify:
`grep -c "__IRO_ASSETS__" src/obs/IRO_Endurance.json` → `0`;
`grep -c "__IRO_GRAPHICS__" src/obs/IRO_Endurance.json` → `8`.

- [ ] **Step 2: Create the kept tool `tools/add_weather_sources.py`**

```python
#!/usr/bin/env python3
"""Add the three weather graphic sources + hidden Stint items to an OBS collection.

Idempotent (mirrors tools/add_standby_cover.py): deep-copies the 'Standings' image
source and its full-screen Stint scene item as templates, so the result always matches
OBS's schema. Re-running is a no-op once the sources exist. Files are tokenised as
__IRO_GRAPHICS__/<name>.png (resolved by setup-assets.py).

Usage: python3 tools/add_weather_sources.py <collection.json>
"""
import copy, json, sys

WEATHER = [
    ("Race Weather 1", "c1c1c1c1-0000-4000-8000-000000000001"),
    ("Race Weather 2", "c2c2c2c2-0000-4000-8000-000000000002"),
    ("Quali Weather",  "c3c3c3c3-0000-4000-8000-000000000003"),
]


def add_weather_sources(d):
    """Mutate the collection in place. Return the list of names added."""
    srcs = d["sources"]
    stint = next(s for s in srcs if s.get("id") == "scene" and s.get("name") == "Stint")
    items = stint["settings"]["items"]
    tmpl_src = next(s for s in srcs if s.get("name") == "Standings")
    tmpl_item = next(it for it in items if it.get("name") == "Standings")
    added = []
    for name, uuid in WEATHER:
        if any(s.get("name") == name for s in srcs):
            continue
        src = copy.deepcopy(tmpl_src)
        src["name"] = name
        src["uuid"] = uuid
        src["settings"] = dict(src.get("settings", {}))
        src["settings"]["file"] = f"__IRO_GRAPHICS__/{name}.png"
        srcs.append(src)

        item = copy.deepcopy(tmpl_item)
        item["name"] = name
        item["source_uuid"] = uuid
        item["visible"] = False
        item["locked"] = False
        item["id"] = max(it.get("id", 0) for it in items) + 1
        item["pos"] = {"x": 0.0, "y": 0.0}
        item["scale"] = {"x": 1.0, "y": 1.0}
        item["bounds_type"] = 2                  # OBS_BOUNDS_SCALE_INNER = "fit"
        item["bounds"] = {"x": 1920.0, "y": 1080.0}
        items.append(item)
        added.append(name)
    return added


def main(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    added = add_weather_sources(d)
    if not added:
        print(f"{path}: weather sources already present — skip"); return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
    print(f"{path}: added {', '.join(added)} (hidden full-screen Stint items)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: add_weather_sources.py <collection.json>")
    main(sys.argv[1])
```

- [ ] **Step 3: Run it against the source collection**

Run: `python3 tools/add_weather_sources.py src/obs/IRO_Endurance.json`
Expected: `src/obs/IRO_Endurance.json: added Race Weather 1, Race Weather 2, Quali Weather (hidden full-screen Stint items)`.
Re-run once → `weather sources already present — skip` (idempotency check).

- [ ] **Step 4: Verify the collection state**

```bash
python3 - <<'PY'
import json
d = json.load(open("src/obs/IRO_Endurance.json", encoding="utf-8"))
names = [s["name"] for s in d["sources"] if s.get("id") == "image_source"]
assert "Schedule" in names and "Season Schedule" not in names, names
for w in ("Race Weather 1", "Race Weather 2", "Quali Weather"):
    assert w in names, w
stint = next(s for s in d["sources"] if s.get("name") == "Stint")
items = [it["name"] for it in stint["settings"]["items"]]
for w in ("Race Weather 1", "Race Weather 2", "Quali Weather"):
    assert w in items, items
assert "__IRO_ASSETS__" not in json.dumps(d)
print("OBS collection OK:", names)
PY
```

Expected: `OBS collection OK: [...]` listing all image sources incl. `Schedule` and the 3 weather, no assertion error.

- [ ] **Step 5: Delete the committed top-level PNGs (pure runtime)**

```bash
git rm "src/assets/Overlay.png" "src/assets/Post Race Interviews.png" \
  "src/assets/Quali Results.png" "src/assets/Race Results.png" \
  "src/assets/Season Schedule.png" "src/assets/Standings.png" \
  "src/assets/YT-IRO-Race.png"
```

Confirm `flags/` + `brands/` remain: `git ls-files src/assets/ | grep -c brands/` → non-zero; `ls src/assets/*.png 2>/dev/null` → no matches. Confirm `runtime/` is gitignored: `git check-ignore runtime/graphics` → prints `runtime/graphics`.

- [ ] **Step 6: Commit**

```bash
git add src/obs/IRO_Endurance.json tools/add_weather_sources.py
git commit -m "feat(graphics): OBS uses __IRO_GRAPHICS__; add weather sources; drop committed PNGs"
```

---

## Task 4: Companion — weather buttons + Schedule retarget

**Files:**
- Modify: `src/companion/iro-buttons.companionconfig`

- [ ] **Step 1: Add the 3 weather buttons and retarget Schedule Toggle**

Run (heredoc; mutates the source config, preserving 1-space indent):

```bash
python3 - <<'PY'
import json, copy
P = "src/companion/iro-buttons.companionconfig"
c = json.load(open(P, encoding="utf-8"))
ctrls = c["pages"]["1"]["controls"]
tmpl = ctrls["3"]["0"]   # 'Standings Toggle' — toggle_scene_item on Stint + scene_item_active feedback

def make(text, source, sfx):
    b = copy.deepcopy(tmpl)
    b["style"]["text"] = text
    fb = b["feedbacks"][0]
    fb["id"] = "wx-fb-" + sfx
    fb["options"]["source"] = {"value": source, "isExpression": False}
    act = b["steps"]["0"]["action_sets"]["down"][0]
    act["id"] = "wx-act-" + sfx
    act["options"]["source"] = {"value": source, "isExpression": False}
    return b

ctrls.setdefault("1", {})["7"] = make("Race Wx 1", "Race Weather 1", "rw1")
ctrls.setdefault("2", {})["7"] = make("Race Wx 2", "Race Weather 2", "rw2")
ctrls.setdefault("3", {})["7"] = make("Quali Wx",  "Quali Weather",  "qw")

# Retarget the renamed source on 'Schedule Toggle' (Season Schedule -> Schedule)
sch = ctrls["3"]["1"]
sch["feedbacks"][0]["options"]["source"] = {"value": "Schedule", "isExpression": False}
sch["steps"]["0"]["action_sets"]["down"][0]["options"]["source"] = {"value": "Schedule", "isExpression": False}

json.dump(c, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("added Race Wx 1 / Race Wx 2 / Quali Wx; retargeted Schedule Toggle -> Schedule")
PY
```

Expected: the success line above.

- [ ] **Step 2: Verify the buttons and upgradeIndex**

```bash
python3 - <<'PY'
import json
c = json.load(open("src/companion/iro-buttons.companionconfig", encoding="utf-8"))
ctrls = c["pages"]["1"]["controls"]
for row, txt, src in (("1", "Race Wx 1", "Race Weather 1"),
                      ("2", "Race Wx 2", "Race Weather 2"),
                      ("3", "Quali Wx", "Quali Weather")):
    b = ctrls[row]["7"]
    assert b["style"]["text"] == txt
    act = b["steps"]["0"]["action_sets"]["down"][0]
    assert act["definitionId"] == "toggle_scene_item"
    assert act["options"]["source"]["value"] == src
    assert act["options"]["scene"]["value"] == "Stint"
    assert act.get("upgradeIndex") == 8 and b["feedbacks"][0].get("upgradeIndex") == 8
    assert b["feedbacks"][0]["options"]["source"]["value"] == src
sch = ctrls["3"]["1"]
assert sch["feedbacks"][0]["options"]["source"]["value"] == "Schedule"
print("companion buttons OK")
PY
```

Expected: `companion buttons OK`.

- [ ] **Step 3: Commit**

```bash
git add src/companion/iro-buttons.companionconfig
git commit -m "feat(graphics): Companion weather toggle buttons + Schedule source retarget"
```

---

## Task 5: Maintainer tools — `tokenize-obs.py` + `add_standby_cover.py`

**Files:**
- Modify: `tools/tokenize-obs.py`
- Modify: `tools/add_standby_cover.py`

- [ ] **Step 1: Rework `tokenize-obs.py` to target `__IRO_GRAPHICS__`**

The old logic listed `src/assets` PNGs to decide what to tokenise — those files are gone. New logic tokenises every `image_source` file path to `__IRO_GRAPHICS__/<basename>`, idempotently.

Replace the module docstring's first paragraph and `TOKEN = "__IRO_ASSETS__"` with:

```python
TOKEN = "__IRO_GRAPHICS__"
```

Update the docstring line about recognised assets to:

```
Recognized assets = every image_source 'file' path (the broadcast graphics live in
runtime/graphics and are tokenized to __IRO_GRAPHICS__/<basename>). Path matching is
separator-agnostic. Idempotent (already-tokenized paths are left alone).
```

In `main()`, delete the `--assets-dir` handling and the `known`/`sys.exit` block:

```python
    assets_dir = a.assets_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "assets")
    known = ({f for f in os.listdir(assets_dir) if f.lower().endswith(".png")}
             if os.path.isdir(assets_dir) else set())
    if not known:
        sys.exit(f"ERROR: no asset PNGs found in {assets_dir} "
                 f"(need them to know which paths to tokenize; run sync-assets first).")
```

Replace the tokenise loop:

```python
    for s in d.get("sources", []):
        st = s.get("settings") or {}
        f = st.get("file")
        if isinstance(f, str) and base(f) in known:
            st["file"] = f"{TOKEN}/{base(f)}"
            n += 1
```

with:

```python
    for s in d.get("sources", []):
        if s.get("id") != "image_source":
            continue
        st = s.get("settings") or {}
        f = st.get("file")
        if isinstance(f, str) and f and not f.startswith("__IRO_"):
            st["file"] = f"{TOKEN}/{base(f)}"
            n += 1
```

Also remove the now-unused `--assets-dir` argument line:

```python
    ap.add_argument("--assets-dir", default=None)
```

(`base()`, `tokenize_sheets()`, the sheet/timer regexes and their handling stay unchanged. `sys` is still used by `argparse`; leave the import.)

- [ ] **Step 2: Verify `tokenize-obs.py` is idempotent on the source collection**

Run: `python3 tools/tokenize-obs.py src/obs/IRO_Endurance.json /tmp/tok_check.json`
Expected: `tokenized 0 asset path(s) + 0 sheet/timer URL(s) -> /tmp/tok_check.json` (already tokenised — 0 changes). Confirm no diff: `diff <(python3 -m json.tool src/obs/IRO_Endurance.json) <(python3 -m json.tool /tmp/tok_check.json) && echo IDENTICAL`. Then `rm -f /tmp/tok_check.json`.

- [ ] **Step 3: Update `add_standby_cover.py` token**

In `tools/add_standby_cover.py`, change:

```python
COVER_FILE = "__IRO_ASSETS__/YT-IRO-Race.png"          # reuse the standby graphic (tokenized)
```

to:

```python
COVER_FILE = "__IRO_GRAPHICS__/Standby.png"            # reuse the standby graphic (tokenized)
```

- [ ] **Step 4: Verify `add_standby_cover.py` is still a no-op (cover already present)**

Run: `python3 tools/add_standby_cover.py src/obs/IRO_Endurance.json`
Expected: `… 'Standby Cover' already present — skip` (no change to the file).

- [ ] **Step 5: Commit**

```bash
git add tools/tokenize-obs.py tools/add_standby_cover.py
git commit -m "chore(graphics): retarget tokenize-obs + add_standby_cover to __IRO_GRAPHICS__"
```

---

## Task 6: Build — fetch graphics + verify token swap

**Files:**
- Modify: `tools/build.py`

- [ ] **Step 1: Add the graphics download (after the intro/outro media block)**

In `tools/build.py`, immediately after the media download `try/except` (the block ending with `print(f"  [WARN] intro/outro clip fetch skipped: {e}")`) add:

```python
    # broadcast graphics: download into the package so the artifact is self-contained.
    # Best-effort (same policy as the clips) — get-graphics.py lets a producer re-fetch
    # on site when the sheet graphics change.
    graphics_dst = os.path.join(PKG, "graphics")
    os.makedirs(graphics_dst, exist_ok=True)
    try:
        subprocess.run([sys.executable, os.path.join(SRC, "relay", "get-graphics.py"),
                        "--out", graphics_dst], check=True, timeout=600)
    except Exception as e:
        print(f"  [WARN] graphics fetch skipped: {e}")
```

- [ ] **Step 2: Swap the verify check**

Replace this check line:

```python
        "obs tokenized": "__IRO_ASSETS__/" in tpl and "GoogleDrive" not in tpl,
```

with:

```python
        "obs graphics tokenized": "__IRO_GRAPHICS__/" in tpl
            and "GoogleDrive" not in tpl and "drive.google.com" not in tpl,
```

- [ ] **Step 3: Add per-graphic presence notes (after the media clip notes)**

Immediately after the `for clip in ("intro.mp4", "outro.mp4"):` loop add:

```python
    for fn in sorted(set(re.findall(r"__IRO_GRAPHICS__/([^\"\\]+\.png)", tpl))):
        ok = os.path.isfile(os.path.join(PKG, "graphics", fn))
        print(f"  [{'OK' if ok else 'warn'}] graphic {fn} "
              f"{'present' if ok else 'MISSING (run get-graphics.py before release)'}")
```

(`re` is already imported at the top of `build.py`.)

- [ ] **Step 4: Run the build and confirm verify passes**

Run: `python3 tools/build.py`
Expected: all `[OK]` checks (including `obs graphics tokenized`), `[OK] graphic <Label>.png present` for the 10 graphics (network permitting; `warn` is acceptable offline but the token check must be `OK`), `BUILD VERIFY FAILED` must NOT appear. Confirm: `python3 -c "import os;print(sorted(os.listdir('dist/IRO_Broadcast_Package/graphics')))"` lists the downloaded PNGs.

- [ ] **Step 5: Commit**

```bash
git add tools/build.py
git commit -m "build(graphics): fetch graphics into package + verify __IRO_GRAPHICS__ tokenization"
```

---

## Task 7: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `src/docs/README_SETUP.md`, `src/docs/IRO_cheat_sheets.html`
- Modify: `src/docs/wiki/OBS-Setup.md`, `src/docs/wiki/Run-an-event.md`, `src/docs/wiki/Director.md`, `src/docs/wiki/Configuration.md`

- [ ] **Step 1: `CLAUDE.md`** — Update the secrets/`load_dotenv` paragraph to say the bounded `load_dotenv()` is now **four** copies (add `src/relay/get-graphics.py`). In the "Two token round-trips" section, add `__IRO_GRAPHICS__` to the OBS token list and document that the broadcast graphics are **pure-runtime**: downloaded from the Sheet **Assets** tab by `python3 src/relay/get-graphics.py` into `runtime/graphics/` (never committed), tokenised `__IRO_GRAPHICS__`, resolved by `setup-assets.py`; `src/assets/` now holds only `flags/`+`brands/` (the relay HUD assets, still committed). Add a Commands-section line: `python3 src/relay/get-graphics.py   # fetch broadcast graphics (Assets tab -> runtime/graphics)`.

- [ ] **Step 2: `README.md`** — Add a command line next to the `get-media.py` one:

```bash
# Download the broadcast graphics (Standings/Schedule/Results/Weather/… from the Assets tab)
python3 src/relay/get-graphics.py            # -> runtime/graphics/<Label>.png
```

- [ ] **Step 3: `src/docs/README_SETUP.md`** — In the prep section that mentions `get-media.py`, add the parallel graphics step (run `get-graphics.py` before `setup-assets.py`); add a package-contents note that graphics ship under `graphics/` and can be refreshed on site.

- [ ] **Step 4: `src/docs/wiki/OBS-Setup.md`** — In §2 "The scenes", extend the Intro/Outro bullet (or add one) noting the broadcast graphics + the three **weather** graphics (`Race Weather 1`, `Race Weather 2`, `Quali Weather`) are local files in `runtime/graphics/`, tokenised `__IRO_GRAPHICS__`, downloaded from the Sheet **Assets** tab with `python3 src/relay/get-graphics.py`; black if missing. Note they are hidden Stint overlays toggled from Companion.

- [ ] **Step 5: `src/docs/wiki/Run-an-event.md`** — In "Before you go live", add a prep step after the intro/outro clip step: **Refresh the graphics:** `python3 src/relay/get-graphics.py` — pulls every graphic from the Sheet **Assets** tab into `runtime/graphics/`. Mention weather graphics are available as toggles during the race.

- [ ] **Step 6: `src/docs/wiki/Director.md`** — In the Page-1 board "Graphics" row description, add the three weather toggles (`Race Wx 1`, `Race Wx 2`, `Quali Wx`) in the right-edge Weather column; add a short beat that weather graphics are full-screen toggles like Standings/Results.

- [ ] **Step 7: `src/docs/wiki/Configuration.md`** — Where `__IRO_ASSETS__` and the other tokens are documented, add `__IRO_GRAPHICS__` → `runtime/graphics/` (Sheet-driven graphics) and note `__IRO_ASSETS__` now covers only the bundled HUD `flags/`+`brands/`.

- [ ] **Step 8: `src/docs/IRO_cheat_sheets.html`** — In the Director card's graphics/combos area, add the three weather buttons (`Race Wx 1`, `Race Wx 2`, `Quali Wx`).

- [ ] **Step 9: Verify English-only + no secrets, then commit**

Run: `grep -rIl "drive.google.com\|/spreadsheets/d/[A-Za-z0-9_-]\{20,\}/" CLAUDE.md README.md src/docs 2>/dev/null` → expect **no output** (no raw sheet/Drive URLs committed in docs).

```bash
git add CLAUDE.md README.md src/docs
git commit -m "docs(graphics): document __IRO_GRAPHICS__, get-graphics.py, weather buttons"
```

---

## Task 8: End-to-end validation + screenshots (user-in-the-loop)

**Files:** none (verification only) — except the regenerated screenshot.

- [ ] **Step 1: Full test suite**

Run, expecting `ALL PASS` / no failures from each:
```bash
python3 tests/test_graphics.py
python3 tests/test_media.py
python3 tests/test_pov.py
python3 tests/test_preflight.py
python3 tests/test_hud.py
```

- [ ] **Step 2: Real localize for this machine**

```bash
python3 src/relay/get-graphics.py --out runtime/graphics
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json
```
Expected: 10 graphics downloaded; `setup-assets` prints `Graphics dir: …/runtime/graphics` and **no** "graphic(s) missing" warning. Confirm the import collection resolves the token:
`grep -c "runtime/graphics" runtime/IRO_Endurance.import.json` → non-zero; `grep -c "__IRO_GRAPHICS__" runtime/IRO_Endurance.import.json` → `0`.

- [ ] **Step 3: User imports into OBS** — Ask the user to **Scene Collection → Import** `runtime/IRO_Endurance.import.json`, switch to it, and confirm: the existing graphics still show when toggled, and the 3 weather sources exist in the **Stint** scene (hidden). Wait for the user to confirm before screenshots.

- [ ] **Step 4: User imports the Companion config** — Ask the user to import `src/companion/iro-buttons.companionconfig` into a running Companion (localhost:8000) and confirm the 3 weather buttons appear on Page 1, col 7, rows 1–3.

- [ ] **Step 5: Regenerate the Page-1 screenshot** — Use the **companion-screenshots** skill to recapture `src/docs/wiki/images/companion-page1-show-control.png` (page 1 changed: new weather column). Verify it renders the new buttons.

- [ ] **Step 6: Commit the screenshot**

```bash
git add src/docs/wiki/images/companion-page1-show-control.png
git commit -m "docs(companion): refresh page-1 screenshot with weather buttons"
```

- [ ] **Step 7: Final review + finish** — Dispatch a final code-review subagent over the whole branch, then use **superpowers:finishing-a-development-branch** (the user previously chose: Wiki dry-run → squash commit to main → push → Wiki sync → delete branch → visual wiki test).

---

## Notes for the executor

- **Edit only under `src/`** for shipped code/docs; `tools/` are maintainer scripts (allowed). Never hand-edit `dist/`/`runtime/`. Graphics live only in `runtime/graphics/` (gitignored) and the built `dist/.../graphics/` — never under `src/`, never committed.
- **English only** in all code/docs.
- **Keep the four `load_dotenv` copies in sync** (`iro-feeds.py`, `setup-assets.py`, `get-media.py`, `get-graphics.py`).
- The user is separately reconsidering the **overall Companion layout**. The weather buttons are deliberately isolated (Page 1, col 7, rows 1–3); if the user changes the layout before/after this work, only Task 4's placement coordinates change — sources, feedbacks and the OBS side are unaffected.
- Do not touch `flags/`, `brands/`, the HUD, or the relay feed logic.
