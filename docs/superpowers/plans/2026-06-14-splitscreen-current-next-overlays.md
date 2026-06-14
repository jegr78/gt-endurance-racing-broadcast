# Splitscreen current/next feed labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CURRENT/NEXT overlay boxes to the OBS Splitscreen scene, driven by a dedicated relay-served `/splitscreen` page that labels the always-left Feed A and always-right Feed B by their live role.

**Architecture:** A new relay-served page (`src/obs/splitscreen.html`) is added as its own OBS browser source that lives only in the Splitscreen scene. It polls a thin new relay endpoint `GET /splitscreen/data` that projects `Relay.live_feed()`/`Relay.mode` into `{current, next_active, mode}`. Per-league restyling rides the existing override-CSS machinery (`OVERLAY_PAGES` + `/splitscreen/override.css`). No visual builder tab.

**Tech Stack:** Pure Python 3 + stdlib (relay is `http.server`), plain HTML/CSS/JS page, OBS scene-collection JSON. Tests are stdlib runnable scripts (no pytest).

**Spec:** `docs/superpowers/specs/2026-06-14-splitscreen-current-next-overlays-design.md`

**Branch:** `feat/splitscreen-current-next` (already created; spec already committed).

**Conventions (CLAUDE.md):** edit only under `src/`; English only; no machine paths / real IPs (loopback `127.0.0.1` is fine); TDD. Local gates after the work: `python3 tools/run-tests.py`, `python3 tools/lint.py`, `python3 tools/build.py` (exit 0). Single squash commit → PR title `feat(overlay): …`, `Closes #129`.

---

## File structure

- **Modify** `src/relay/racecast-feeds.py`
  - Add `Relay.splitscreen_state()` (pure projection, after `live_after_next()` ~L1926).
  - Add `"splitscreen"` to `OVERLAY_PAGES` (L284).
  - Add a `splitscreen_path` param to `make_handler()` (L2091) and three routes in `do_GET()`.
  - Resolve `splitscreen_path` in `serve()` (~L2556) and pass it to `make_handler()` (~L2629).
- **Create** `src/obs/splitscreen.html` — the overlay page (mirrors `src/obs/hud.html` base).
- **Modify** `src/racecast.py` — extend `OBS_PAGE_PATHS` (L573) with the two splitscreen paths.
- **Modify** `src/obs/GT_Endurance.json` — add a `Splitscreen Labels` browser source + a scene item in the `Splitscreen` scene only.
- **Tests:** `tests/test_pov.py` (state projection), `tests/test_overlay.py` (OVERLAY_PAGES + override css + page guard + collection guard), `tests/test_racecast.py` (OBS_PAGE_PATHS).

---

### Task 1: `Relay.splitscreen_state()` projection

**Files:**
- Modify: `src/relay/racecast-feeds.py` (after `live_after_next()`, ~L1926)
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` (the `_relay` and `_relay_q` helpers already exist there):

```python
def t_splitscreen_state_maps_live_feed_to_current():
    r = _relay(["s1", "s2", "s3", "s4"])
    assert r.splitscreen_state() == {"current": "A", "next_active": True, "mode": "race"}
    r.next_auto()                                  # B becomes the on-air feed
    assert r.splitscreen_state()["current"] == "B"


def t_splitscreen_state_hides_next_in_qualifying():
    r = _relay_q(["s1", "s2"], ["q1"], mode="qualifying")
    st = r.splitscreen_state()
    assert st == {"current": "A", "next_active": False, "mode": "qualifying"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: `AttributeError: 'Relay' object has no attribute 'splitscreen_state'`

- [ ] **Step 3: Implement the method**

In `src/relay/racecast-feeds.py`, immediately after the `live_after_next()` method (the block ending ~L1926), add:

```python
    def splitscreen_state(self):
        """State for the /splitscreen overlay. Feed A is always the Splitscreen
        scene's left half, Feed B the right; the overlay labels the on-air feed
        CURRENT and the other NEXT. In qualifying mode only Feed A is used, so
        NEXT is hidden (next_active False)."""
        return {"current": self.live_feed(),
                "next_active": self.mode != "qualifying",
                "mode": self.mode}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_pov.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): splitscreen_state projection for current/next labels"
```

---

### Task 2: Register `splitscreen` as an overlay page

**Files:**
- Modify: `src/relay/racecast-feeds.py:284`
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlay.py` (it already imports the relay module as `feeds` and has a `_overlay_dir`-style tempdir pattern — mirror `t_read_overlay_css_present` at L27):

```python
def t_splitscreen_is_an_overlay_page():
    assert "splitscreen" in feeds.OVERLAY_PAGES


def t_read_overlay_css_splitscreen_present():
    import tempfile, os
    with tempfile.TemporaryDirectory() as od:
        with open(os.path.join(od, "splitscreen.css"), "w") as fh:
            fh.write("#split-left{color:#fff}")
        assert feeds.read_overlay_css(od, "splitscreen") == b"#split-left{color:#fff}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `t_splitscreen_is_an_overlay_page` asserts False; `t_read_overlay_css_splitscreen_present` returns `b""` (page not in `OVERLAY_PAGES`).

- [ ] **Step 3: Implement**

In `src/relay/racecast-feeds.py` change L284 from:

```python
OVERLAY_PAGES = ("hud",)
```

to:

```python
OVERLAY_PAGES = ("hud", "splitscreen")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_overlay.py
git commit -m "feat(relay): register splitscreen as an overlay page (override css)"
```

---

### Task 3: Add splitscreen paths to the OBS refresh-hash set

**Files:**
- Modify: `src/racecast.py:573`
- Test: `tests/test_racecast.py:1280`

- [ ] **Step 1: Update the failing test**

In `tests/test_racecast.py`, change the existing assertion in `t_obs_page_paths_include_overrides` (L1280) from:

```python
def t_obs_page_paths_include_overrides():
    assert m.OBS_PAGE_PATHS == ("/hud", "/hud/override.css")
```

to:

```python
def t_obs_page_paths_include_overrides():
    assert m.OBS_PAGE_PATHS == ("/hud", "/hud/override.css",
                                "/splitscreen", "/splitscreen/override.css")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_obs_page_paths_include_overrides()"`
Expected: `AssertionError`

- [ ] **Step 3: Implement**

In `src/racecast.py` change L573 from:

```python
OBS_PAGE_PATHS = ("/hud", "/hud/override.css")
```

to:

```python
OBS_PAGE_PATHS = ("/hud", "/hud/override.css",
                  "/splitscreen", "/splitscreen/override.css")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_obs_page_paths_include_overrides()"`
Expected: no output (pass)

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(obs): hash /splitscreen pages so edits auto-refresh OBS"
```

---

### Task 4: The `/splitscreen` overlay page

**Files:**
- Create: `src/obs/splitscreen.html`
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing guard test**

Add to `tests/test_overlay.py`:

```python
def t_splitscreen_page_wires_data_and_override():
    import os
    path = os.path.join(ROOT, "src", "obs", "splitscreen.html")
    assert os.path.exists(path), "src/obs/splitscreen.html missing"
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert "/splitscreen/data" in html          # polls the relay state
    assert "/splitscreen/override.css" in html  # per-league override link
    assert 'id="split-left"' in html and 'id="split-right"' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `src/obs/splitscreen.html missing`

- [ ] **Step 3: Create the page**

Create `src/obs/splitscreen.html` with this exact content (transparent 1920×1080; two boxes anchored flush-right to each 960-wide feed half with a slight overhang above the 270px feed top; polls `/splitscreen/data` and assigns CURRENT/NEXT by role; hides NEXT when `next_active` is false):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Splitscreen labels</title>
<style>
  /* Transparent overlay for the OBS Splitscreen scene. Feed A is the left
     half (x 0..960), Feed B the right (x 960..1920); both feeds are a 960x540
     band with their top edge at y=270. Each label sits at the top-right of its
     own feed, flush-right, overhanging slightly above the feed's top edge. */
  html,body{margin:0;width:1920px;height:1080px;background:transparent;overflow:hidden}
  .split-label{position:absolute;top:256px;            /* 270 - 14 overhang */
    background:rgba(38,44,52,.92);border:1px solid #4a5560;border-radius:7px;
    padding:6px 12px;color:#fff;font:600 22px/1.1 'IBM Plex Mono',ui-monospace,monospace;
    letter-spacing:.12em;text-transform:uppercase;box-shadow:0 4px 14px rgba(0,0,0,.5);
    white-space:nowrap}
  #split-left{right:960px}    /* flush to the centre seam */
  #split-right{right:0}       /* flush to the screen edge */
  .split-label[hidden]{display:none}
</style>
<link rel="stylesheet" href="/splitscreen/override.css">
</head>
<body>
  <div id="split-left" class="split-label" hidden></div>
  <div id="split-right" class="split-label" hidden></div>
<script>
  // Feed A renders on the left box, Feed B on the right. The relay reports which
  // feed is on air; that box reads CURRENT, the other NEXT. NEXT hides when the
  // other feed is inactive (qualifying mode). Server-driven only — no reloads.
  var L = document.getElementById('split-left');
  var R = document.getElementById('split-right');
  async function tick(){
    try{
      var s = await (await fetch('/splitscreen/data', {cache:'no-store'})).json();
      var leftIsCurrent = s.current === 'A';
      L.textContent = leftIsCurrent ? 'Current' : 'Next';
      R.textContent = leftIsCurrent ? 'Next' : 'Current';
      // Hide whichever box would read NEXT when next_active is false.
      L.hidden = (!leftIsCurrent && !s.next_active);
      R.hidden = ( leftIsCurrent && !s.next_active);
    }catch(e){ /* keep last-good labels on a transient relay hiccup */ }
  }
  tick(); setInterval(tick, 2500);
</script>
</body>
</html>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/obs/splitscreen.html tests/test_overlay.py
git commit -m "feat(overlay): /splitscreen page with CURRENT/NEXT feed labels"
```

---

### Task 5: Relay routes for `/splitscreen`, `/splitscreen/data`, `/splitscreen/override.css`

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `make_handler()` signature (L2091-2093), `do_GET()` routes (after the `/hud/override.css` route at L2178-2179), `serve()` path resolution (~L2556) and `make_handler(...)` call (~L2629).

This task wires the page + endpoint into the HTTP server. The data projection is already unit-tested (Task 1) and the override-css reader is already unit-tested (Task 2); the route wiring is verified live in the final Verification section (no server-spinning unit harness exists in this repo).

- [ ] **Step 1: Add the `splitscreen_path` parameter to `make_handler`**

Change the signature at `src/relay/racecast-feeds.py:2091-2093` from:

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, setup_ctl=None, overlay_dir=None,
                 chat_store=None, preview_path=None, graphics_dir=None):
```

to (append one keyword param):

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, setup_ctl=None, overlay_dir=None,
                 chat_store=None, preview_path=None, graphics_dir=None,
                 splitscreen_path=None):
```

- [ ] **Step 2: Add the three routes in `do_GET`**

In `src/relay/racecast-feeds.py`, immediately after the `/hud/override.css` route (L2178-2179):

```python
                if p == ["hud", "override.css"]:
                    return self._send_css(read_overlay_css(overlay_dir, "hud"))
```

insert:

```python
                if p == ["splitscreen"]:
                    if not splitscreen_path:
                        return self._send({"error": "splitscreen page not found"}, 404)
                    return self._send_file(splitscreen_path, "text/html; charset=utf-8")
                if p == ["splitscreen", "data"]:
                    return self._send(relay.splitscreen_state())
                if p == ["splitscreen", "override.css"]:
                    return self._send_css(read_overlay_css(overlay_dir, "splitscreen"))
```

- [ ] **Step 3: Resolve `splitscreen_path` in `serve()`**

In `src/relay/racecast-feeds.py`, right after the `assets_dir = ...` line (L2556) and before the `if not args.no_hud ...` block, add (served unconditionally — the page needs only relay state, not the sheet):

```python
    splitscreen_path = None
    for cand in (os.path.join(here, "splitscreen.html"),
                 os.path.join(here, "..", "splitscreen.html"),
                 os.path.join(here, "..", "obs", "splitscreen.html")):
        if os.path.exists(cand):
            splitscreen_path = os.path.abspath(cand); break
    if not splitscreen_path:
        print("WARN: splitscreen.html not found — /splitscreen will 404.")
```

- [ ] **Step 4: Pass it to `make_handler`**

Change the `make_handler(...)` call (~L2629-2632) from:

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, setup_ctl,
                           overlay_dir=args.overlay_dir, chat_store=chat_store,
                           preview_path=preview_path, graphics_dir=graphics_dir)
```

to (append the new keyword):

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, setup_ctl,
                           overlay_dir=args.overlay_dir, chat_store=chat_store,
                           preview_path=preview_path, graphics_dir=graphics_dir,
                           splitscreen_path=splitscreen_path)
```

- [ ] **Step 5: Verify nothing regressed**

Run: `python3 tests/test_pov.py && python3 tests/test_overlay.py`
Expected: both `ALL PASS`

Run: `python3 tools/lint.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): serve /splitscreen page, /splitscreen/data and override.css"
```

---

### Task 6: Add the `Splitscreen Labels` browser source to the OBS collection

**Files:**
- Modify: `src/obs/GT_Endurance.json` — add one source object (sources array) + one scene item in the `Splitscreen` scene only.
- Test: `tests/test_overlay.py`

- [ ] **Step 1: Write the failing collection guard test**

Add to `tests/test_overlay.py` (mirrors the style of `t_committed_template_carries_the_source` in `tests/test_discord_audio.py`):

```python
def t_splitscreen_labels_source_in_collection_splitscreen_scene_only():
    import os, json
    with open(os.path.join(ROOT, "src", "obs", "GT_Endurance.json"),
              encoding="utf-8") as fh:
        d = json.load(fh)
    srcs = [s for s in d.get("sources", []) if s.get("name") == "Splitscreen Labels"]
    assert len(srcs) == 1, "exactly one Splitscreen Labels source expected"
    src = srcs[0]
    assert src.get("id") == "browser_source"
    assert src["settings"]["url"] == "http://127.0.0.1:8088/splitscreen"
    uuid = src["uuid"]
    # present in the Splitscreen scene, absent from every other scene
    def has_item(scene_name):
        for s in d["sources"]:
            if s.get("name") == scene_name and s.get("id") == "scene":
                return any(it.get("source_uuid") == uuid
                           for it in s["settings"]["items"])
        return False
    assert has_item("Splitscreen")
    assert not has_item("Stint")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `exactly one Splitscreen Labels source expected` (0 found).

- [ ] **Step 3: Add the source object**

In `src/obs/GT_Endurance.json`, add this object to the top-level `"sources"` array (place it next to the existing `HUD Overlay` source object for readability). It copies the `HUD Overlay` browser-source shape with a new name, uuid, and url:

```json
{
 "prev_ver": 536936450,
 "name": "Splitscreen Labels",
 "uuid": "0ad0fee0-0000-4000-8000-000000000002",
 "id": "browser_source",
 "versioned_id": "browser_source",
 "settings": {
  "url": "http://127.0.0.1:8088/splitscreen",
  "width": 1920,
  "height": 1080,
  "restart_when_active": true
 },
 "mixers": 255,
 "sync": 0,
 "flags": 0,
 "volume": 1.0,
 "balance": 0.5,
 "enabled": true,
 "muted": false,
 "push-to-mute": false,
 "push-to-mute-delay": 0,
 "push-to-talk": false,
 "push-to-talk-delay": 0,
 "hotkeys": {
  "libobs.mute": [],
  "libobs.unmute": [],
  "libobs.push-to-mute": [],
  "libobs.push-to-talk": [],
  "ObsBrowser.Refresh": []
 },
 "deinterlace_mode": 0,
 "deinterlace_field_order": 0,
 "monitoring_type": 0,
 "private_settings": {},
 "filters": []
}
```

- [ ] **Step 4: Add the scene item to the Splitscreen scene only**

Find the source object with `"name": "Splitscreen"` and `"id": "scene"`. In its `settings.items` array, add this item (it references the new source uuid, full-frame, top layer, unique `id` 27 — one above the scene's current max of 26):

```json
{
 "name": "Splitscreen Labels",
 "source_uuid": "0ad0fee0-0000-4000-8000-000000000002",
 "visible": true,
 "locked": false,
 "rot": 0.0,
 "align": 5,
 "bounds_type": 2,
 "bounds_align": 0,
 "bounds_crop": false,
 "crop_left": 0,
 "crop_top": 0,
 "crop_right": 0,
 "crop_bottom": 0,
 "id": 27,
 "group_item_backup": true,
 "pos": { "x": 0.0, "y": 0.0 },
 "scale": { "x": 1.0, "y": 1.0 },
 "bounds": { "x": 1920.0, "y": 1080.0 },
 "scale_filter": "disable",
 "blend_method": "default",
 "blend_type": "normal",
 "show_transition": { "duration": 0 },
 "hide_transition": { "duration": 0 },
 "private_settings": {}
}
```

Add it as the FIRST entry of the `items` array (OBS renders the first item top-most, so the labels sit above the feeds and the Overlay frame).

- [ ] **Step 5: Verify the JSON is valid and the test passes**

Run: `python3 -c "import json; json.load(open('src/obs/GT_Endurance.json')); print('json ok')"`
Expected: `json ok`

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add src/obs/GT_Endurance.json tests/test_overlay.py
git commit -m "feat(obs): add Splitscreen Labels browser source to the Splitscreen scene"
```

---

## Verification (before opening the PR)

- [ ] **Full local gates (mirror CI):**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # All checks passed!
python3 tools/build.py         # exit 0 (asset/media warnings are fine)
```

- [ ] **Live route check** (uses the installed test profile with sheet data, like the #152 verification):

```bash
cp -R ~/Documents/racecast/profiles/iro-gtec profiles/ 2>/dev/null
echo iro-gtec > runtime/active-profile
python3 src/racecast.py relay start
sleep 3
curl -s http://127.0.0.1:8088/splitscreen/data        # -> {"current":"A","next_active":true,"mode":"race"}
curl -s http://127.0.0.1:8088/splitscreen | head -c 80 # -> <!doctype html> ... (the page)
curl -s http://127.0.0.1:8088/splitscreen/override.css # -> empty (no league override) — 200
python3 src/racecast.py relay stop
rm -rf profiles/iro-gtec runtime/active-profile        # clean up the borrowed profile
```

Expected: `/splitscreen/data` returns the JSON; `/splitscreen` serves the HTML; `/splitscreen/override.css` returns 200 with empty body.

- [ ] **Optional visual check (Playwright):** load `http://127.0.0.1:8088/splitscreen` over a dark backdrop and confirm the two grey CURRENT/NEXT boxes render at the top-right of each feed half. (No wiki screenshot exists for the Splitscreen scene, so nothing to refresh — the wiki-screenshot rule covers Control Center / Director Panel / Companion only.)

## Squash + PR

- [ ] Squash the task commits into one conventional commit and open the PR:

```bash
gh pr create --base main \
  --title "feat(overlay): label splitscreen feeds CURRENT/NEXT (#129)" \
  --body "...Closes #129..."
```

(The branch already carries the `docs(spec)` commit; the PR is the spec + implementation for #129. Squash-merge yields the single conventional subject release-please parses.)

---

## Self-review notes (spec coverage)

- Dedicated relay page + own browser source, Splitscreen scene only → Tasks 4, 5, 6.
- Box text role-only CURRENT/NEXT, flush-right top corner, slight overhang, grey/white look → Task 4 (`splitscreen.html` CSS/JS).
- `current` from `live_feed()`, A=left/B=right, `next_active` false in qualifying → Task 1 (+ tests).
- Per-league override CSS via `OVERLAY_PAGES` + `/splitscreen/override.css`, no builder tab → Task 2 + Task 5 route.
- `OBS_PAGE_PATHS` includes the two splitscreen paths (auto-refresh) → Task 3.
- Tests for current/next mapping, qualifying, routes-as-projection, override css, OBS collection source → Tasks 1, 2, 4, 6.
