# Intro / Outro Videos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a director-controllable stream **Intro** and **Outro** video — each a looping, audio-on YouTube clip played from a local file via a dedicated OBS scene and a single Companion button.

**Architecture:** A new prep script `src/relay/get-media.py` reads the clip URLs from the Google Sheet `Configuration` tab (label cell → URL in the next cell) and downloads them with `yt-dlp` into `runtime/media/` (repo) or `<package>/media` (dist). Two new OBS scenes play the clips from a local file (looping, audio routed like Feed A), their path tokenised as a new `__IRO_MEDIA__` token resolved by `setup-assets.py`. Two new Companion buttons switch to those scenes via the existing OBS `set_scene` action. `build.py` downloads a clip snapshot into the package at build time (best-effort). Clips are never stored under `src/` and never committed.

**Tech Stack:** Python 3 stdlib only (+ `yt-dlp` subprocess, already a runtime dep). OBS scene-collection JSON (indent 4). Companion `.companionconfig` JSON (indent 1). No new dependencies, no framework.

---

## Context the engineer needs (read first)

- **Hard rules (`CLAUDE.md`):** edit only under `src/` (and `tests/`, `tools/`, `docs/`); `dist/`+`runtime/` are generated/gitignored; **English only** in all code/docs; never hardcode secrets/paths; no `.sh`/`.bat` files (the build fails if any ship).
- **This repo is not currently a git checkout** (`Is a git repository: false`). Where a step says "Commit", run it if a `.git` exists; otherwise skip the commit and move on (the file changes are what matter). Check once with `git rev-parse --is-inside-work-tree 2>/dev/null`.
- **Tokenisation:** `src/setup-assets.py` replaces tokens in the OBS collection with machine-local values. Existing tokens: `__IRO_ASSETS__` (image dir), `__IRO_SHEET__`, `__IRO_TIMER__`. This plan adds `__IRO_MEDIA__` (clip dir). The replacement is conditional — a token is only required/replaced if it actually appears in the collection.
- **Repo-vs-package path detection:** `default_runtime_dir(here)` in `src/relay/iro-feeds.py` and `src/relay/get-cookies.py` distinguishes the repo layout (`src/relay/…`) from the distributed package (`relay/…`). We add two small analogues: `media_dir(here)` in `get-media.py` (script lives in `…/relay/`) and `media_dir(base)` in `setup-assets.py` (script lives one level up).
- **Tests are stdlib-only runnable scripts** (no pytest). Each `tests/test_*.py` loads the hyphenated module with `importlib.util.spec_from_file_location` and runs every top-level `t_*` function from `__main__`. Mirror `tests/test_pov.py` exactly.
- **`load_dotenv`** is a small bounded `.env` reader duplicated verbatim in `src/relay/iro-feeds.py` and `src/setup-assets.py`. This plan adds a third copy to `get-media.py`; the docs task updates the `CLAUDE.md` note to say "three copies".

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/relay/get-media.py` | **Create** | Resolve intro/outro URLs (CLI > env > sheet) + download clips via `yt-dlp` into the media dir. Pure helpers `media_dir`, `media_urls_from_csv`, `resolve_urls`, `fetch_config_csv`, `download`. |
| `tests/test_media.py` | **Create** | Stdlib unit checks for the pure helpers in `get-media.py`. |
| `src/obs/IRO_Endurance.json` | **Modify** | Add 2 `ffmpeg_source` sources (local-file, looping, audio) + 2 `scene` entries (`Intro`, `Outro`) + 2 `scene_order` entries. Introduces `__IRO_MEDIA__`. |
| `src/setup-assets.py` | **Modify** | Add `media_dir(base)`, `--media` arg, conditional `__IRO_MEDIA__` replacement, warn on missing clips. Update its `load_dotenv` is untouched (keep in sync rule). |
| `src/companion/iro-buttons.companionconfig` | **Modify** | Add `INTRO` (page 1, row 0, col 5) and `OUTRO` (col 6) buttons: OBS `set_scene` + mute live feeds, `sceneProgram` feedback. |
| `tools/build.py` | **Modify** | Download clip snapshot into `<pkg>/media` (best-effort) + verify `__IRO_MEDIA__` tokenised + soft clip-present note. |
| `.env.example` | **Modify** | Document optional `IRO_INTRO_URL` / `IRO_OUTRO_URL` overrides. |
| `README.md`, `src/docs/README_SETUP.md`, `src/docs/IRO_cheat_sheets.html`, `CLAUDE.md`, `src/docs/wiki/*` | **Modify** | Operator + maintainer docs. |

---

## Task 1: `media_urls_from_csv` — locate URLs in the sheet (TDD)

**Files:**
- Create: `src/relay/get-media.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_media.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for get-media.py. Run: python3 tests/test_media.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "getmedia", os.path.join(ROOT, "src", "relay", "get-media.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_urls_basic():
    rows = [["Intro Video", "https://youtu.be/AAA"],
            ["Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {
        "intro": "https://youtu.be/AAA", "outro": "https://youtu.be/BBB"}, \
        m.media_urls_from_csv(rows)


def t_urls_label_case_and_gap():
    # label match is case/space-insensitive; URL is the next NON-empty cell
    rows = [["  intro video ", "", "https://youtu.be/AAA"]]
    assert m.media_urls_from_csv(rows) == {"intro": "https://youtu.be/AAA"}


def t_urls_label_without_value_omitted():
    rows = [["Intro Video", ""], ["Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {"outro": "https://youtu.be/BBB"}


def t_urls_moved_columns():
    rows = [["foo", "bar", "Outro Video", "https://youtu.be/BBB"]]
    assert m.media_urls_from_csv(rows) == {"outro": "https://youtu.be/BBB"}


def t_urls_empty():
    assert m.media_urls_from_csv([]) == {}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL PASS")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_media.py`
Expected: FAIL — `FileNotFoundError`/`spec` error because `src/relay/get-media.py` does not exist yet.

- [ ] **Step 3: Create `get-media.py` with the module skeleton + `media_urls_from_csv`**

Create `src/relay/get-media.py`:

```python
#!/usr/bin/env python3
"""Download the stream Intro/Outro clips for OBS from YouTube.

URL resolution priority per clip:  --intro-url/--outro-url  >  env
IRO_INTRO_URL/IRO_OUTRO_URL  >  Google Sheet 'Configuration' tab (a cell whose
text is 'Intro Video'/'Outro Video', URL in the next non-empty cell to its right).

Clips are written as intro.mp4 / outro.mp4 into the media dir (repo:
<repo>/runtime/media ; distributed package: <package>/media). Never stored
under src/, never committed.

Usage: python3 get-media.py [--which intro|outro|both] [--out DIR]
       [--sheet-id ID] [--config-tab NAME] [--intro-url U] [--outro-url U]
"""
import argparse, csv, io, os, subprocess, sys
from urllib.parse import quote
from urllib.request import Request, urlopen

# Single muxed MP4 with audio, capped at 1080p (falls back to best available).
YTDLP_FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

# Sheet label cell -> output key.
MEDIA_LABELS = {"intro video": "intro", "outro video": "outro"}


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with
    a .git/.env.example marker). KEEP IN SYNC with the copies in iro-feeds.py and
    setup-assets.py."""
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


def media_urls_from_csv(rows):
    """Configuration-tab rows -> {'intro': url, 'outro': url} (only found keys).
    Located by label cell so column positions can move: a cell equal (trimmed,
    case-insensitive) to a MEDIA_LABELS key marks the row; the value is the next
    non-empty cell to its right."""
    out = {}
    for row in rows:
        for i, cell in enumerate(row):
            key = MEDIA_LABELS.get((cell or "").strip().lower())
            if not key:
                continue
            for nxt in row[i + 1:]:
                v = (nxt or "").strip()
                if v:
                    out[key] = v
                    break
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_media.py`
Expected: PASS — `ok  t_urls_*` lines then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/get-media.py tests/test_media.py
git commit -m "feat(media): add get-media.py URL lookup from Configuration tab"
```

---

## Task 2: `media_dir` + `resolve_urls` (TDD)

**Files:**
- Modify: `src/relay/get-media.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_media.py` (before the `if __name__` block):

```python
def t_media_dir_repo():
    assert m.media_dir("/x/src/relay") == "/x/runtime/media", m.media_dir("/x/src/relay")


def t_media_dir_pkg():
    assert m.media_dir("/x/IRO_Broadcast_Package/relay") == \
        "/x/IRO_Broadcast_Package/media"


def t_resolve_priority_cli_then_env():
    cli = {"intro": "CLI", "outro": None}
    env = {"IRO_OUTRO_URL": "ENV"}
    csv_text = "Intro Video,SHEET_I\nOutro Video,SHEET_O\n"
    out = m.resolve_urls({"intro", "outro"}, cli, env, csv_text)
    assert out == {"intro": "CLI", "outro": "ENV"}, out


def t_resolve_sheet_fallback():
    out = m.resolve_urls({"intro"}, {"intro": None}, {}, "Intro Video,SHEET_I\n")
    assert out == {"intro": "SHEET_I"}, out


def t_resolve_missing_is_none():
    out = m.resolve_urls({"intro"}, {"intro": None}, {}, None)
    assert out == {"intro": None}, out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_media.py`
Expected: FAIL — `AttributeError: module 'getmedia' has no attribute 'media_dir'`.

- [ ] **Step 3: Implement `media_dir` and `resolve_urls`**

Append to `src/relay/get-media.py` (after `media_urls_from_csv`):

```python
def media_dir(here):
    """Where clips live when --out is not given. Mirrors default_runtime_dir():
    repo layout (src/relay/) -> <repo>/runtime/media ; package (relay/) -> <pkg>/media."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "media")
    return os.path.join(os.path.dirname(here), "media")


def resolve_urls(which, cli, env, csv_text):
    """Resolve a URL per key in `which` (a set of 'intro'/'outro').
    Priority: cli[key]  >  env['IRO_<KEY>_URL']  >  sheet label lookup.
    `csv_text` may be None (sheet not fetched)."""
    sheet = media_urls_from_csv(list(csv.reader(io.StringIO(csv_text)))) if csv_text else {}
    out = {}
    for key in which:
        out[key] = (cli.get(key) or env.get(f"IRO_{key.upper()}_URL") or sheet.get(key))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_media.py`
Expected: PASS — all `t_*` lines then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/get-media.py tests/test_media.py
git commit -m "feat(media): add media_dir + resolve_urls with CLI>env>sheet priority"
```

---

## Task 3: `get-media.py` download + CLI (`main`)

The download path runs `yt-dlp` (network), so it is verified by a manual run, not a unit test. The pure helpers are already covered by Tasks 1–2.

**Files:**
- Modify: `src/relay/get-media.py`

- [ ] **Step 1: Add `fetch_config_csv`, `download`, and `main`**

Append to `src/relay/get-media.py`:

```python
def fetch_config_csv(sheet_id, tab, timeout=15):
    """Fetch the Configuration tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "iro-media/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(url, out_path, cookies=None):
    """Download `url` to `out_path` as a single muxed MP4 (audio included).
    Uses cookies.txt if it exists (YouTube bot-check parity with the relay)."""
    cmd = ["yt-dlp", "-f", YTDLP_FORMAT, "--merge-output-format", "mp4",
           "--no-warnings", "-o", out_path, url]
    if cookies and os.path.exists(cookies):
        cmd[1:1] = ["--cookies", cookies]
    subprocess.run(cmd, check=True, timeout=600)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["intro", "outro", "both"], default="both")
    ap.add_argument("--out", default=media_dir(here),
                    help="Target dir for intro.mp4 / outro.mp4 (default: media_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Configuration tab. Default: env IRO_SHEET_ID.")
    ap.add_argument("--config-tab", default="Configuration")
    ap.add_argument("--intro-url", default=None)
    ap.add_argument("--outro-url", default=None)
    a = ap.parse_args()

    which = {"intro", "outro"} if a.which == "both" else {a.which}
    cli = {"intro": a.intro_url, "outro": a.outro_url}

    # Only hit the sheet if a CLI/env URL is missing for something we need.
    csv_text = None
    need_sheet = any(not (cli.get(k) or os.environ.get(f"IRO_{k.upper()}_URL")) for k in which)
    if need_sheet and a.sheet_id:
        try:
            csv_text = fetch_config_csv(a.sheet_id, a.config_tab)
        except Exception as e:
            print(f"WARNING: could not read sheet Configuration tab: {e}")

    urls = resolve_urls(which, cli, os.environ, csv_text)
    os.makedirs(a.out, exist_ok=True)
    cookies = os.path.join(os.path.dirname(os.path.abspath(a.out)), "cookies.txt")

    failed = []
    for key in sorted(which):
        url = urls.get(key)
        if not url:
            print(f"WARNING: no URL for {key} "
                  f"(sheet label '{key.title()} Video' / --{key}-url / IRO_{key.upper()}_URL)")
            failed.append(key)
            continue
        out_path = os.path.join(a.out, f"{key}.mp4")
        print(f"Downloading {key}: {url}")
        try:
            download(url, out_path, cookies)
            print(f"OK -> {out_path}")
        except FileNotFoundError:
            sys.exit("ERROR: yt-dlp not found (brew install yt-dlp / pip install -U yt-dlp).")
        except Exception as e:
            print(f"WARNING: download failed for {key}: {e}")
            failed.append(key)

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the module still imports and unit tests still pass**

Run: `python3 tests/test_media.py`
Expected: PASS — `ALL PASS` (adding `main`/`download` must not break the pure helpers).

- [ ] **Step 3: Verify the CLI parses and reports missing URLs cleanly (no network)**

Run: `python3 src/relay/get-media.py --which intro --out /tmp/iro-media-test --sheet-id ""`
Expected: prints `WARNING: no URL for intro …` and exits non-zero with `Incomplete: intro not downloaded.` (No traceback. Confirms argparse + resolution wiring.)

- [ ] **Step 4: (Optional, requires network + yt-dlp) Real download smoke test**

Run: `python3 src/relay/get-media.py --which intro --out /tmp/iro-media-test --intro-url "https://www.youtube.com/watch?v=HqlROA7of2M"`
Expected: `OK -> /tmp/iro-media-test/intro.mp4`; file exists and plays with audio. Then `rm -rf /tmp/iro-media-test`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/get-media.py
git commit -m "feat(media): get-media.py download pipeline + CLI"
```

---

## Task 4: OBS scenes `Intro` / `Outro`

Add two `ffmpeg_source` sources (local file, looping, audio like Feed A), two `scene` entries each showing one source full-screen, and two `scene_order` entries. Done with a one-shot Python edit so the structure is exact and re-runnable.

**Files:**
- Modify: `src/obs/IRO_Endurance.json`

- [ ] **Step 1: Apply the edit**

Run this script from the repo root (`python3 - <<'PY' … PY`):

```python
import json, os
P = "src/obs/IRO_Endurance.json"
d = json.load(open(P, encoding="utf-8"))

def ffmpeg_clip(name, uuid, fname):
    return {
        "prev_ver": 536936450, "name": name, "uuid": uuid,
        "id": "ffmpeg_source", "versioned_id": "ffmpeg_source",
        "settings": {
            "close_when_inactive": True, "hw_decode": True,
            "local_file": f"__IRO_MEDIA__/{fname}", "is_local_file": True,
            "looping": True, "clear_on_media_end": False,
            "restart_on_activate": True, "buffering_mb": 8, "speed_percent": 100,
        },
        "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
        "enabled": True, "muted": False, "push-to-mute": False,
        "push-to-mute-delay": 0, "push-to-talk": False, "push-to-talk-delay": 0,
        "hotkeys": {"libobs.mute": [], "libobs.unmute": [],
                    "libobs.push-to-mute": [], "libobs.push-to-talk": [],
                    "MediaSource.Restart": [], "MediaSource.Play": [],
                    "MediaSource.Pause": [], "MediaSource.Stop": []},
        "deinterlace_mode": 0, "deinterlace_field_order": 0,
        "monitoring_type": 0, "private_settings": {},
    }

def scene(name, uuid, src_name, src_uuid):
    return {
        "prev_ver": 536936450, "name": name, "uuid": uuid,
        "id": "scene", "versioned_id": "scene",
        "settings": {"custom_size": False, "id_counter": 2, "items": [{
            "name": src_name, "source_uuid": src_uuid, "visible": True,
            "locked": True, "rot": 0.0, "align": 5, "bounds_type": 0,
            "bounds_align": 0, "bounds_crop": False, "crop_left": 0,
            "crop_top": 0, "crop_right": 0, "crop_bottom": 0, "id": 1,
            "group_item_backup": False, "pos": {"x": 0.0, "y": 0.0},
            "scale": {"x": 1.0, "y": 1.0}, "bounds": {"x": 0.0, "y": 0.0},
            "scale_filter": "disable", "blend_method": "default",
            "blend_type": "normal", "show_transition": {"duration": 300},
            "hide_transition": {"duration": 300}, "private_settings": {}}]},
        "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
        "enabled": True, "muted": False, "push-to-mute": False,
        "push-to-mute-delay": 0, "push-to-talk": False, "push-to-talk-delay": 0,
        "hotkeys": {"OBSBasic.SelectScene": [],
                    "libobs.show_scene_item.1": [], "libobs.hide_scene_item.1": []},
        "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0,
        "canvas_uuid": "6c69626f-6273-4c00-9d88-c5136d61696e", "private_settings": {},
    }

INTRO_SRC = "7a7a7a7a-0000-4000-8000-000000000071"
OUTRO_SRC = "9a9a9a9a-0000-4000-8000-000000000091"
INTRO_SCN = "77777777-7777-4777-8777-777777777777"
OUTRO_SCN = "99999999-9999-4999-8999-999999999999"

names = {s["name"] for s in d["sources"]}
assert "Intro" not in names and "Outro" not in names, "already added"

d["sources"].append(ffmpeg_clip("Intro Video", INTRO_SRC, "intro.mp4"))
d["sources"].append(ffmpeg_clip("Outro Video", OUTRO_SRC, "outro.mp4"))
d["sources"].append(scene("Intro", INTRO_SCN, "Intro Video", INTRO_SRC))
d["sources"].append(scene("Outro", OUTRO_SCN, "Outro Video", OUTRO_SRC))

order = [o["name"] for o in d["scene_order"]]
d["scene_order"].insert(order.index("Standby") + 1, {"name": "Intro"})
d["scene_order"].insert(order.index("Standby") + 2, {"name": "Outro"})

json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
print("OBS collection updated")
PY
```

- [ ] **Step 2: Verify the collection is valid and contains the new scenes + token**

Run:
```bash
python3 - <<'PY'
import json
d = json.load(open("src/obs/IRO_Endurance.json", encoding="utf-8"))
names = [s["name"] for s in d["sources"]]
assert "Intro" in names and "Outro" in names, names
assert {"name": "Intro"} in d["scene_order"] and {"name": "Outro"} in d["scene_order"]
blob = json.dumps(d)
assert "__IRO_MEDIA__/intro.mp4" in blob and "__IRO_MEDIA__/outro.mp4" in blob
src = next(s for s in d["sources"] if s["name"] == "Intro Video")
assert src["settings"]["looping"] and src["settings"]["is_local_file"]
assert src["mixers"] == 255  # audio reaches the broadcast tracks
print("OBS verify OK")
PY
```
Expected: `OBS verify OK`.

- [ ] **Step 3: (Manual, when OBS is available) confirm the local-file key name**

In a throwaway OBS, add a *Media Source* pointing at any local `.mp4`, export the scene collection, and confirm the file-path key is `local_file` (with `is_local_file: true`). If your OBS build serialises it differently, update the `ffmpeg_clip()` settings keys accordingly and re-run Step 1. (Documented as the one open detail in the spec.)

- [ ] **Step 4: Commit**

```bash
git add src/obs/IRO_Endurance.json
git commit -m "feat(obs): add Intro/Outro media scenes (looping, audio, __IRO_MEDIA__)"
```

---

## Task 5: `setup-assets.py` — resolve `__IRO_MEDIA__`

**Files:**
- Modify: `src/setup-assets.py`

- [ ] **Step 1: Add the `MEDIA_TOKEN` constant and `media_dir` helper**

In `src/setup-assets.py`, after the existing token constants (`TIMER_TOKEN = "__IRO_TIMER__"`), add:

```python
MEDIA_TOKEN = "__IRO_MEDIA__"


def media_dir(base):
    """Default clip dir. setup-assets.py sits at src/ (repo) or <pkg>/ (package):
    repo (base basename 'src') -> <repo>/runtime/media ; package -> <base>/media."""
    if os.path.basename(base) == "src":
        return os.path.join(os.path.dirname(base), "runtime", "media")
    return os.path.join(base, "media")
```

- [ ] **Step 2: Add the `--media` argument**

In `main()`, after the `--out` argument is added, add:

```python
    ap.add_argument("--media", default=media_dir(base),
                    help="Folder with intro.mp4/outro.mp4 for the Intro/Outro "
                         "scenes (replaces __IRO_MEDIA__). Default: media_dir().")
```

- [ ] **Step 3: Add conditional `__IRO_MEDIA__` replacement + missing-clip warning**

In `main()`, after the `TIMER_TOKEN` handling block (the `if TIMER_TOKEN in raw:` block), add:

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

- [ ] **Step 4: Add a confirmation print**

In `main()`, after the existing `if TIMER_TOKEN in mapping:` print block (near the end), add:

```python
    if MEDIA_TOKEN in mapping:
        print(f"  Intro/Outro clip dir: {a.media}")
```

- [ ] **Step 5: Verify localisation injects the media path**

Run:
```bash
python3 src/setup-assets.py --out /tmp/iro.import.json --media /tmp/iro-clips
grep -c "/tmp/iro-clips/intro.mp4" /tmp/iro.import.json
```
Expected: command prints `OK -> /tmp/iro.import.json`, a `WARNING: Intro/Outro clip(s) missing …` line (the dir is empty), and `grep` prints `1`. Then `rm -f /tmp/iro.import.json`.

> Note: this run also needs `IRO_SHEET_ID`/`IRO_TIMER_URL` available (from `.env`) only if the collection still contains those tokens. The collection currently has `__IRO_TIMER__`, so ensure `.env` has `IRO_TIMER_URL` set, or pass `--timer-url x` for the smoke test.

- [ ] **Step 6: Commit**

```bash
git add src/setup-assets.py
git commit -m "feat(setup-assets): resolve __IRO_MEDIA__ to the clip dir"
```

---

## Task 6: Companion `INTRO` / `OUTRO` buttons

Add two buttons on Page 1, Row 0, columns 5 and 6 (next to the scene-switch buttons). Each does the same as `STANDBY`: switch scene + mute the live feeds (so only the clip audio is heard) + a `sceneProgram` feedback that lights the button when its scene is live.

**Files:**
- Modify: `src/companion/iro-buttons.companionconfig`

- [ ] **Step 1: Apply the edit**

Run from the repo root:

```python
import json
P = "src/companion/iro-buttons.companionconfig"
cfg = json.load(open(P, encoding="utf-8"))
OBS = "dv_e1zuVb_6XgPv0eRibl"          # OBS connection id (existing)
row0 = cfg["pages"]["1"]["controls"]["0"]
assert "5" not in row0 and "6" not in row0, "slots already used"

def button(text, scene, ids):
    mutes = [{"id": ids[i + 1], "definitionId": "set_source_mute", "connectionId": OBS,
              "options": {"source": {"value": src, "isExpression": False},
                          "mute": {"value": "true", "isExpression": False}},
              "type": "action"}
             for i, src in enumerate(["Discord Audio Capture", "Feed A", "Feed B"])]
    return {
        "type": "button",
        "style": {"text": text, "textExpression": False, "size": "18",
                  "png64": None, "alignment": "center:center",
                  "pngalignment": "center:center", "color": 16777215,
                  "bgcolor": 0, "show_topbar": "default"},
        "options": {"stepProgression": "auto", "stepExpression": "", "rotaryActions": False},
        "feedbacks": [{"id": ids[0], "definitionId": "sceneProgram", "connectionId": OBS,
                       "options": {"scene": {"value": scene, "isExpression": False}},
                       "type": "feedback",
                       "style": {"color": 16777215, "bgcolor": 13107200},
                       "isInverted": {"value": False, "isExpression": False}}],
        "steps": {"0": {"action_sets": {"down": [
            {"id": ids[4], "definitionId": "set_scene", "connectionId": OBS,
             "options": {"scene": {"value": scene, "isExpression": False},
                         "customSceneName": {"value": "", "isExpression": False}},
             "type": "action"}] + mutes, "up": []},
            "options": {"runWhileHeld": []}}},
        "localVariables": [],
    }

row0["5"] = button("INTRO", "Intro",
                   ["iro-intro-fb", "iro-intro-a0", "iro-intro-a1", "iro-intro-a2", "iro-intro-set"])
row0["6"] = button("OUTRO", "Outro",
                   ["iro-outro-fb", "iro-outro-a0", "iro-outro-a1", "iro-outro-a2", "iro-outro-set"])

json.dump(cfg, open(P, "w", encoding="utf-8"), indent=1)
print("Companion config updated")
PY
```

- [ ] **Step 2: Verify the config is valid and the buttons exist**

Run:
```bash
python3 - <<'PY'
import json
cfg = json.load(open("src/companion/iro-buttons.companionconfig", encoding="utf-8"))
row0 = cfg["pages"]["1"]["controls"]["0"]
for col, text, scene in (("5", "INTRO", "Intro"), ("6", "OUTRO", "Outro")):
    b = row0[col]
    assert b["style"]["text"] == text
    act = b["steps"]["0"]["action_sets"]["down"][0]
    assert act["definitionId"] == "set_scene" and act["options"]["scene"]["value"] == scene
print("Companion verify OK")
PY
```
Expected: `Companion verify OK`.

- [ ] **Step 3: Commit**

```bash
git add src/companion/iro-buttons.companionconfig
git commit -m "feat(companion): add INTRO/OUTRO scene buttons (page 1, row 0)"
```

---

## Task 7: `build.py` — bundle clips + verify

**Files:**
- Modify: `tools/build.py`

- [ ] **Step 1: Add the `subprocess` import**

Change the import line at the top of `tools/build.py`:

```python
import json, os, re, shutil, subprocess, sys, zipfile
```

- [ ] **Step 2: Download a clip snapshot into the package (best-effort)**

In `main()`, after the line `cp("relay", "relay")  # iro-feeds.py + get-cookies.py`, add:

```python
    # intro/outro clips: download into the package so the artifact is self-contained.
    # Best-effort — offline / code-only builds must still succeed (the shipped
    # get-media.py lets a producer re-fetch on site if the sheet URLs change).
    media_dst = os.path.join(PKG, "media")
    os.makedirs(media_dst, exist_ok=True)
    try:
        subprocess.run([sys.executable, os.path.join(SRC, "relay", "get-media.py"),
                        "--out", media_dst], check=True, timeout=600)
    except Exception as e:
        print(f"  [WARN] intro/outro clip fetch skipped: {e}")
```

- [ ] **Step 3: Add verify checks**

In `main()`, inside the `checks = { … }` dict, add this entry (e.g. after `"obs timer tokenized"`):

```python
        "obs media tokenized": "__IRO_MEDIA__/" in tpl,
```

Then, immediately after the `for k, v in checks.items(): print(...)` loop and before `if bad:`, add a soft (non-failing) clip-present note:

```python
    for clip in ("intro.mp4", "outro.mp4"):
        ok = os.path.isfile(os.path.join(PKG, "media", clip))
        print(f"  [{'OK' if ok else 'warn'}] media {clip} "
              f"{'present' if ok else 'MISSING (run get-media.py before release)'}")
```

- [ ] **Step 4: Run the build and confirm verify passes**

Run: `python3 tools/build.py`
Expected: `Built …`, all `[OK]` checks **including** `[OK] obs media tokenized`, and two `media intro.mp4 / outro.mp4` lines (`OK` if network was available and clips downloaded, otherwise `warn … MISSING`). The build must **not** exit non-zero on a missing clip.

- [ ] **Step 5: Commit**

```bash
git add tools/build.py
git commit -m "build: bundle intro/outro clips + verify __IRO_MEDIA__ tokenisation"
```

---

## Task 8: Docs + `.env.example`

**Files:**
- Modify: `.env.example`, `README.md`, `src/docs/README_SETUP.md`, `src/docs/IRO_cheat_sheets.html`, `CLAUDE.md`

- [ ] **Step 1: `.env.example` — document the optional overrides**

Append to `.env.example`:

```bash

# OPTIONAL: override the Intro/Outro clip URLs. Normally these come from the
# Google Sheet "Configuration" tab (label cells "Intro Video" / "Outro Video").
# Set these only to override the sheet for this machine (used by get-media.py).
IRO_INTRO_URL=
IRO_OUTRO_URL=
```

- [ ] **Step 2: `README.md` — add the prep command**

Under the relevant commands section in `README.md` (near the `get-cookies.py` line), add:

```markdown
# Download the stream Intro/Outro clips (URLs from the Sheet's Configuration tab)
python3 src/relay/get-media.py            # -> runtime/media/intro.mp4, outro.mp4
```

- [ ] **Step 3: `src/docs/README_SETUP.md` — operator note**

Add a short subsection (English) explaining: the Intro/Outro scenes play local clips; refresh them with `python3 relay/get-media.py` when the sheet URLs change or before an event; the clip URLs live in the Sheet `Configuration` tab as label cells `Intro Video` / `Outro Video`; the director triggers them with the `INTRO` / `OUTRO` Companion buttons (Page 1, top row) and switches away to end (the clip loops). Keep wording consistent with the existing file's style.

- [ ] **Step 4: `src/docs/IRO_cheat_sheets.html` — mention the buttons**

Add `INTRO` and `OUTRO` to the printable button reference next to the other scene buttons (`STINT A/B`, `SPLIT`, `INTERVIEW`, `STANDBY`), with a one-line note: "plays the looping intro/outro clip with audio; press another scene button to leave."

- [ ] **Step 5: `CLAUDE.md` — update the `load_dotenv` note**

In the "Secrets via `.env`" section, change the sentence that says `load_dotenv()` is "duplicated in `src/relay/iro-feeds.py` and `src/setup-assets.py`" to also list `src/relay/get-media.py` (three copies now; keep them in sync). Also add one line under the relay/architecture docs noting the new `__IRO_MEDIA__` token + `get-media.py` (Intro/Outro clips, sheet-driven, downloaded to `runtime/media`).

- [ ] **Step 6: Commit**

```bash
git add .env.example README.md src/docs/README_SETUP.md src/docs/IRO_cheat_sheets.html CLAUDE.md
git commit -m "docs: document Intro/Outro clips, get-media.py, __IRO_MEDIA__ token"
```

---

## Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run:
```bash
python3 tests/test_media.py && python3 tests/test_pov.py && \
python3 tests/test_hud.py && python3 tests/test_preflight.py
```
Expected: each prints its pass summary; no failures/tracebacks.

- [ ] **Step 2: Run the build verify**

Run: `python3 tools/build.py`
Expected: all `[OK]` checks (incl. `obs media tokenized`); clip lines `OK` or soft `warn MISSING`; build exits 0.

- [ ] **Step 3: (Manual, OBS available) end-to-end smoke**

1. `python3 src/relay/get-media.py` (or with `--intro-url`/`--outro-url`) → clips in `runtime/media/`.
2. `python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json` → no media warning.
3. Import the collection in OBS; switch to the `Intro` scene → clip plays from start, loops, audio audible. Switch away → stops.
4. In Companion, press `INTRO` / `OUTRO` → OBS switches and the button lights while live.

- [ ] **Step 4: Regenerate the Companion wiki screenshots (out of band)**

Use the `companion-screenshots` skill to refresh `src/docs/wiki/images/companion-page1-*.png` so the new buttons appear. (Requires a running Companion instance; not a code change — do this when convenient.)

---

## Self-review notes (for the executor)

- **`local_file` key (Task 4, Step 3):** the one assumption verified against OBS at runtime. If your OBS serialises the media path under a different key, fix `ffmpeg_clip()` and re-run.
- **Audio routing:** the clip sources use `mixers: 255` (same as Feed A) so audio reaches the broadcast; the `INTRO`/`OUTRO` buttons mute Feed A/B/Discord so only the clip is heard — mirroring the existing `STANDBY` button.
- **No secrets/paths committed:** clips only ever land in `runtime/media` (repo) or `<pkg>/media` (build output); both are gitignored / generated. `__IRO_MEDIA__` keeps the committed OBS JSON path-free.
