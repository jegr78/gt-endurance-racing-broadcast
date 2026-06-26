# POV-Box → OBS "Feed POV" Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read a profile's POV-box position/size from its overlay CSS and apply it to the OBS "Feed POV" scene item — baked into the import JSON at `racecast setup` and live-synced via the existing OBS-refresh hook.

**Architecture:** One pure CSS parser (`pov_box_from_css`) feeds two paths. Export: `setup-assets.py` mutates every "Feed POV" scene item's `pos`/`bounds` in the localized collection. Live: `_refresh_obs_pages` merges the override over the `hud.html` base and calls a new best-effort `obs_ws.set_scene_item_transform`. POV-only, behind a one-entry slot→source map.

**Tech Stack:** Pure Python 3 + stdlib. Tests are runnable scripts (no pytest); each `t_*` function is auto-run by the file's `__main__` loop.

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never touch `dist/`/`runtime/`.
- **English only** in all code and docs.
- **Stdlib only.** No new dependencies.
- **`setup-assets.py` stays `config.py`-free** — it may import the pure `overlay_build` from `scripts/` (already on `sys.path`), like it imports `discord_web`.
- **obs-websocket helpers are best-effort:** return `(ok, note)` / `(None, note)`, NEVER raise (OBS closed, wrong password, item missing all map to a failure tuple). A service start/refresh must never fail on this.
- **The 1:1 mapping** (OBS "Feed POV" item is `align:5` top-left, `bounds_type:2` SCALE_INNER): `left→positionX`, `top→positionY`, `width→boundsWidth`, `height→boundsHeight`.
- **Slot→source map:** `OVERLAY_SLOT_OBS_SOURCES = {"pov": "Feed POV"}` (exactly one entry; POV is the only overlay element with a positioned OBS video source).
- **`#pov-name` and every other slot are ignored** — POV box only.
- Run the full suite with `python3 tools/run-tests.py` and lint with `python3 tools/lint.py` before the final commit.

---

### Task 1: Pure CSS parser + slot→source map

**Files:**
- Modify: `src/scripts/overlay_build.py` (add constant + `pov_box_from_css` near the other pure helpers, e.g. after `base_body`)
- Test: `tests/test_overlay.py` (add `t_*` functions; module already imports `overlay_build as ob`)

**Interfaces:**
- Produces: `OVERLAY_SLOT_OBS_SOURCES` (dict `{"pov": "Feed POV"}`); `pov_box_from_css(css_text: str) -> dict` returning any subset of `{"left","top","width","height"}` as `int` (or `float` when non-integer), in px. Empty dict when absent/unparseable/non-str.

- [ ] **Step 1: Write the failing tests**

In `tests/test_overlay.py` (anywhere above the `__main__` block):

```python
def t_pov_box_from_css_full_rule():
    css = "#pov { left: 1516px; top: 600px; width: 384px; height: 216px; }"
    assert ob.pov_box_from_css(css) == {"left": 1516, "top": 600,
                                        "width": 384, "height": 216}


def t_pov_box_from_css_partial_keeps_only_present():
    assert ob.pov_box_from_css("#pov { left: 1516px; top: 600px; }") == \
        {"left": 1516, "top": 600}


def t_pov_box_from_css_absent_is_empty():
    assert ob.pov_box_from_css("#stint { left: 5px; }") == {}
    assert ob.pov_box_from_css("") == {}
    assert ob.pov_box_from_css(None) == {}


def t_pov_box_from_css_cascade_later_rule_wins_per_prop():
    # base rule then a customCss override appended later -> left overridden,
    # the other props retained from the earlier rule (per-property cascade).
    css = ("#pov { left: 1496px; top: 644px; width: 384px; height: 216px; }\n"
           "#pov { left: 1600px; }")
    assert ob.pov_box_from_css(css) == {"left": 1600, "top": 644,
                                        "width": 384, "height": 216}


def t_pov_box_from_css_ignores_pov_name_and_non_px():
    assert ob.pov_box_from_css("#pov-name { left: 99px; top: 10px; }") == {}
    # non-px value (e.g. a percentage) is skipped; px sibling still read.
    assert ob.pov_box_from_css("#pov { left: 50%; top: 600px; }") == {"top": 600}
    assert ob.pov_box_from_css("#pov {") == {}        # malformed: no closing brace


def t_pov_box_from_css_float_value():
    assert ob.pov_box_from_css("#pov { left: 1516.5px; }") == {"left": 1516.5}


def t_overlay_slot_obs_sources_constant():
    assert ob.OVERLAY_SLOT_OBS_SOURCES == {"pov": "Feed POV"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `AttributeError: module 'overlay_build' has no attribute 'pov_box_from_css'` (or `OVERLAY_SLOT_OBS_SOURCES`).

- [ ] **Step 3: Implement the parser + constant**

In `src/scripts/overlay_build.py`, add after the `base_body` function (around line 196):

```python
# Overlay slot id -> OBS scene-item name. The single overlay element that maps to
# a positioned OBS video source: the POV picture-in-picture. (Feed A/B are
# full-screen; clock/race-control/flags are pure overlay.) One entry today, named
# so a future overlay-with-OBS-source is a one-line addition.
OVERLAY_SLOT_OBS_SOURCES = {"pov": "Feed POV"}

# `#pov` rule body, NOT `#pov-name`/`#povfoo` (negative lookahead bars a longer
# ident or a hyphen after "pov"). `[^{}]*` lets `#pov`, `#pov.empty`, `#pov:hover`
# through to the brace. The px props we map onto the OBS Feed POV transform.
_POV_RULE_RE = re.compile(r"#pov(?![\w-])[^{}]*\{([^{}]*)\}")
_POV_PX_RE = re.compile(r"\b(left|top|width|height)\s*:\s*(-?\d+(?:\.\d+)?)px")


def pov_box_from_css(css_text):
    """Effective #pov box overrides from override CSS: a dict with any subset of
    {'left','top','width','height'} (px, int or float). Every #pov rule is read in
    document order, later properties overriding earlier ones (CSS cascade — so a
    customCss override appended after a generated rule wins). Empty dict when the
    input is not a string, has no #pov rule, or the rule carries no px box props —
    the caller then applies no transform (today's behavior)."""
    if not isinstance(css_text, str):
        return {}
    out = {}
    for body in _POV_RULE_RE.findall(css_text):       # document order
        for key, val in _POV_PX_RE.findall(body):
            f = float(val)
            out[key] = int(f) if f.is_integer() else f
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ok t_pov_box_from_css_*` lines + `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(overlay): pure pov_box_from_css parser + slot->source map"
```

---

### Task 2: Export bake — `apply_pov_transform` + `--overlay-css` in setup-assets

**Files:**
- Modify: `src/setup-assets.py` (import `overlay_build`; add `POV_SOURCE_NAME`, `apply_pov_transform`; add `--overlay-css` arg + `main()` wiring)
- Test: `tests/test_discord_audio.py` (this is the file that loads `setup-assets.py` as `sa` — NOT `test_setup.py`, which tests the relay's SetupControl)

**Interfaces:**
- Consumes: `overlay_build.pov_box_from_css`, `overlay_build.OVERLAY_SLOT_OBS_SOURCES` (Task 1).
- Produces: `POV_SOURCE_NAME` (str `"Feed POV"`); `apply_pov_transform(collection: dict, overrides: dict) -> dict` — mutates + returns `collection`, setting `pos`/`bounds` of every scene item named "Feed POV" anywhere in the tree from `overrides`; unset keys keep the existing value; no-op on falsy `overrides`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_discord_audio.py` (above the `__main__` block):

```python
def _coll_with_pov(pos=(1496.0, 644.0), bounds=(384.0, 216.0)):
    # Scenes are stored as `sources` entries with id "scene"; their items
    # (carrying pos/bounds) live in settings.items — mirrors GT_Endurance.json.
    return {"sources": [
        {"name": "Stint", "id": "scene", "settings": {"items": [
            {"name": "Feed POV",
             "pos": {"x": pos[0], "y": pos[1]},
             "bounds": {"x": bounds[0], "y": bounds[1]}},
        ]}},
    ]}


def _pov_item(coll):
    return coll["sources"][0]["settings"]["items"][0]


def t_pov_source_name_matches_overlay_build():
    assert sa.POV_SOURCE_NAME == "Feed POV"


def t_apply_pov_transform_full():
    coll = _coll_with_pov()
    sa.apply_pov_transform(coll, {"left": 1516, "top": 600,
                                  "width": 384, "height": 216})
    it = _pov_item(coll)
    assert it["pos"] == {"x": 1516, "y": 600}
    assert it["bounds"] == {"x": 384, "y": 216}


def t_apply_pov_transform_partial_keeps_existing():
    coll = _coll_with_pov()
    sa.apply_pov_transform(coll, {"left": 1516, "top": 600})   # no width/height
    it = _pov_item(coll)
    assert it["pos"] == {"x": 1516, "y": 600}
    assert it["bounds"] == {"x": 384.0, "y": 216.0}            # untouched base


def t_apply_pov_transform_empty_is_noop():
    coll = _coll_with_pov()
    sa.apply_pov_transform(coll, {})
    assert _pov_item(coll)["pos"] == {"x": 1496.0, "y": 644.0}


def t_apply_pov_transform_no_pov_item_is_noop():
    coll = {"sources": [{"name": "Feed A", "id": "ffmpeg_source",
                         "settings": {"input": "http://127.0.0.1:53001"}}]}
    sa.apply_pov_transform(coll, {"left": 1516})              # must not raise
    assert coll["sources"][0]["name"] == "Feed A"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_discord_audio.py`
Expected: FAIL — `AttributeError: module 'setup_assets' has no attribute 'POV_SOURCE_NAME'` (or `apply_pov_transform`).

- [ ] **Step 3: Implement the import, constant, and transform**

In `src/setup-assets.py`, extend the existing scripts import block (around line 14-15) so it also loads `overlay_build`:

```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import discord_web  # noqa: E402
import overlay_build  # noqa: E402  (pure stdlib helper — no heavy resolver pulled in)

POV_SOURCE_NAME = overlay_build.OVERLAY_SLOT_OBS_SOURCES["pov"]
```

Add the transform near the other collection transforms (e.g. after `apply_collection_name`, around line 101):

```python
def apply_pov_transform(collection, overrides):
    """Set pos/bounds of EVERY scene item named POV_SOURCE_NAME ('Feed POV'),
    anywhere in the collection tree, from `overrides` (a pov_box_from_css dict:
    any subset of left/top/width/height). Unset keys keep the item's existing
    value, so a partial override leaves the rest at the template base. No-op on
    falsy `overrides`. Mutates and returns `collection` (same contract as
    apply_collection_name / localize_discord_audio)."""
    if not overrides:
        return collection

    def visit(node):
        if isinstance(node, dict):
            if (node.get("name") == POV_SOURCE_NAME
                    and isinstance(node.get("pos"), dict)
                    and isinstance(node.get("bounds"), dict)):
                if "left" in overrides:
                    node["pos"]["x"] = overrides["left"]
                if "top" in overrides:
                    node["pos"]["y"] = overrides["top"]
                if "width" in overrides:
                    node["bounds"]["x"] = overrides["width"]
                if "height" in overrides:
                    node["bounds"]["y"] = overrides["height"]
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(collection)
    return collection
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_discord_audio.py`
Expected: `ok t_apply_pov_transform_*` + `ok t_pov_source_name_matches_overlay_build` + `ALL PASS`.

- [ ] **Step 5: Add the `--overlay-css` flag and wire it into `main()`**

In `src/setup-assets.py`'s `main()`, add the argument next to the others (after `--collection`, around line 166):

```python
    ap.add_argument("--overlay-css", default=None,
                    help="Profile overlay hud.css whose #pov box position/size is "
                         "synced onto the OBS 'Feed POV' scene item. Default: none.")
```

Then, right after `apply_collection_name(localized, a.collection)` (around line 222):

```python
    pov = {}
    if a.overlay_css and os.path.isfile(a.overlay_css):
        try:
            with open(a.overlay_css, encoding="utf-8") as fh:
                pov = overlay_build.pov_box_from_css(fh.read())
        except OSError as e:
            print(f"  NOTE: could not read overlay CSS {a.overlay_css}: {e}")
        apply_pov_transform(localized, pov)
```

And add a status line in the success-print block (after the `if a.collection:` line, around line 236):

```python
    if pov:
        print(f"  POV box synced to OBS '{POV_SOURCE_NAME}': {pov}")
```

- [ ] **Step 6: Verify the wiring with a manual run (no test regression)**

Run: `python3 tests/test_discord_audio.py`
Expected: still `ALL PASS` (the new arg doesn't change existing behavior).

- [ ] **Step 7: Commit**

```bash
git add src/setup-assets.py tests/test_discord_audio.py
git commit -m "feat(setup): bake the overlay POV box onto the OBS Feed POV source"
```

---

### Task 3: obs_ws — `pov_scene_item_transform` + `set_scene_item_transform`

**Files:**
- Modify: `src/scripts/obs_ws.py` (add the pure mapper next to `feed_state_intents`; add the network helper next to `set_scene_item_enabled`)
- Test: `tests/test_obsws.py` (uses the existing `_FakeSession` + `m._connect` monkeypatch pattern)

**Interfaces:**
- Produces: `pov_scene_item_transform(box: dict) -> dict` — pure map of a full `{left,top,width,height}` box to the obs-websocket `sceneItemTransform` (`positionX/Y`, `boundsType:2`, `boundsAlignment:0`, `alignment:5`, `boundsWidth/Height`); `set_scene_item_transform(scene, source, transform, host=…, port=None, password=None, timeout=2.0) -> (ok, note)` best-effort.

- [ ] **Step 1: Write the failing tests**

In `tests/test_obsws.py` (above the `__main__` block; `_FakeSession` is defined around line 931):

```python
def t_pov_scene_item_transform_maps_box():
    assert m.pov_scene_item_transform(
        {"left": 1516, "top": 600, "width": 384, "height": 216}) == {
            "positionX": 1516, "positionY": 600,
            "boundsType": 2, "boundsAlignment": 0, "alignment": 5,
            "boundsWidth": 384, "boundsHeight": 216}


def t_set_scene_item_transform_sends_request():
    sess = _FakeSession({"GetSceneItemId": {"sceneItemId": 7}})
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        tf = m.pov_scene_item_transform(
            {"left": 1516, "top": 600, "width": 384, "height": 216})
        ok, note = m.set_scene_item_transform("Stint", "Feed POV", tf)
    finally:
        m._connect = orig
    assert ok is True and note == ""
    assert ("SetSceneItemTransform",
            {"sceneName": "Stint", "sceneItemId": 7,
             "sceneItemTransform": tf}) in sess.sent


def t_set_scene_item_transform_missing_item():
    sess = _FakeSession({"GetSceneItemId": {}})        # no sceneItemId
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_scene_item_transform("Stint", "Feed POV", {})
    finally:
        m._connect = orig
    assert ok is False and "not found" in note


def t_set_scene_item_transform_unreachable():
    orig, m._connect = m._connect, lambda *a, **k: (None, "OBS not running")
    try:
        assert m.set_scene_item_transform("Stint", "Feed POV", {}) == \
            (False, "OBS not running")
    finally:
        m._connect = orig
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'pov_scene_item_transform'` (or `set_scene_item_transform`).

- [ ] **Step 3: Implement the pure mapper and the network helper**

In `src/scripts/obs_ws.py`, add the pure mapper near `feed_state_intents` (around line 69):

```python
def pov_scene_item_transform(box):
    """Map a full POV box {left,top,width,height} to an obs-websocket
    sceneItemTransform. The Feed POV item is top-left anchored (alignment 5) with
    SCALE_INNER bounds (boundsType 2); all fields are sent explicitly so the
    result is idempotent regardless of the item's current bounds settings."""
    return {"positionX": box["left"], "positionY": box["top"],
            "boundsType": 2, "boundsAlignment": 0, "alignment": 5,
            "boundsWidth": box["width"], "boundsHeight": box["height"]}
```

And the network helper right after `set_scene_item_enabled` (around line 790):

```python
def set_scene_item_transform(scene, source, transform, host="127.0.0.1", port=None,
                             password=None, timeout=2.0):
    """Set a scene item's transform (best effort). `transform` is the
    obs-websocket sceneItemTransform dict (see pov_scene_item_transform).
    Mirrors set_scene_item_enabled: GetSceneItemId -> SetSceneItemTransform.
    Returns (ok, note); (False, reason) on any failure — OBS closed, wrong
    password, item missing — NEVER an exception."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        sid = session.request("GetSceneItemId",
                              {"sceneName": scene, "sourceName": source}).get("sceneItemId")
        if sid is None:
            return False, f"scene item '{source}' not found in scene '{scene}'"
        session.request("SetSceneItemTransform",
                        {"sceneName": scene, "sceneItemId": sid,
                         "sceneItemTransform": dict(transform)})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ok t_pov_scene_item_transform_maps_box`, `ok t_set_scene_item_transform_*`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): best-effort set_scene_item_transform + pure POV mapper"
```

---

### Task 4: racecast wiring — export arg + live sync

**Files:**
- Modify: `src/racecast.py` (`_oneshot_extra` gains an `overlay_css` param + the call site at line 3109 passes it; new `_sync_pov_transform`; call it from `_refresh_obs_pages` after a confirmed refresh)
- Test: `tests/test_racecast.py` (loads `racecast` as `m`; extend `t_oneshot_extra`, add a `_sync_pov_transform` seam test)

**Interfaces:**
- Consumes: `overlay_build.pov_box_from_css`, `overlay_build.OVERLAY_SLOT_OBS_SOURCES`, `obs_ws.pov_scene_item_transform`, `obs_ws.set_scene_item_transform`, `obs_ws.STINT_SCENE` (= `"Stint"`), `overlay_build.base_style`, `m._active_overlay_dir`.
- Produces: `_oneshot_extra(command, rest, runtime_dir, base_dir, overlay_css=None)` (adds `--overlay-css <path>` for `setup` only when `overlay_css` is a real file and not already in `rest`); `_sync_pov_transform(set_transform=None)` (best-effort glue, `set_transform` is a test seam).

- [ ] **Step 1: Write the failing tests**

In `tests/test_racecast.py`, extend `t_oneshot_extra` (after its last assertion, around line 454):

```python
    # --overlay-css is injected for `setup` only when the passed path exists.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        css = os.path.join(d, "hud.css")
        assert m._oneshot_extra("setup", [], R, B, overlay_css=css) == \
            ["--out", os.path.join(R, "GT_Endurance.import.json"),
             "--media", os.path.join(R, "media"),
             "--graphics", os.path.join(R, "graphics")]            # file absent -> skipped
        with open(css, "w") as fh:
            fh.write("#pov { left: 1516px; }")
        assert m._oneshot_extra("setup", [], R, B, overlay_css=css) == \
            ["--out", os.path.join(R, "GT_Endurance.import.json"),
             "--media", os.path.join(R, "media"),
             "--graphics", os.path.join(R, "graphics"),
             "--overlay-css", css]                                 # file present -> added
        # explicit --overlay-css in rest wins: the auto one is not appended.
        assert m._oneshot_extra("setup", ["--overlay-css", "x"], R, B,
                                overlay_css=css).count("--overlay-css") == 0
```

Add a new seam test (above the `__main__` block):

```python
def t_sync_pov_transform_calls_setter_with_merged_box():
    import tempfile
    captured = {}

    def fake_set(scene, source, transform):
        captured["scene"] = scene
        captured["source"] = source
        captured["transform"] = transform
        return True, ""

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "hud.css"), "w") as fh:
            # override only left/top; width/height fall back to the hud.html base.
            fh.write("#pov { left: 1516px; top: 600px; }")
        orig = m._active_overlay_dir
        m._active_overlay_dir = lambda: d
        try:
            m._sync_pov_transform(set_transform=fake_set)
        finally:
            m._active_overlay_dir = orig

    assert captured["scene"] == "Stint"
    assert captured["source"] == "Feed POV"
    tf = captured["transform"]
    assert tf["positionX"] == 1516 and tf["positionY"] == 600   # from the override
    assert tf["boundsWidth"] == 384 and tf["boundsHeight"] == 216  # from the base
    assert tf["boundsType"] == 2 and tf["alignment"] == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `_oneshot_extra() got an unexpected keyword argument 'overlay_css'` and `AttributeError: ... '_sync_pov_transform'`.

- [ ] **Step 3: Add the `overlay_css` param to `_oneshot_extra`**

In `src/racecast.py`, change the signature (line 536) and add the branch at the end of the function (before `return extra`, around line 555):

```python
def _oneshot_extra(command, rest, runtime_dir, base_dir, overlay_css=None):
```

```python
    if (command == "setup" and overlay_css and "--overlay-css" not in rest
            and os.path.isfile(overlay_css)):
        extra += ["--overlay-css", overlay_css]
    return extra
```

Update the call site (line 3109) to pass the active profile's overlay hud.css:

```python
    _od = _active_overlay_dir()
    extra = _oneshot_extra(command, rest, _runtime_dir(), _runtime_base_dir(),
                           overlay_css=os.path.join(_od, "hud.css") if _od else None)
```

- [ ] **Step 4: Add `_sync_pov_transform` and call it from `_refresh_obs_pages`**

In `src/racecast.py`, add the helper just above `_refresh_obs_pages` (around line 1813):

```python
def _sync_pov_transform(set_transform=None):
    """Best-effort live sibling of the setup-time POV bake: push the active
    profile's POV-box position/size onto the OBS 'Feed POV' scene item. Reads the
    profile override CSS, merges over the hud.html base (so an override of only
    some props keeps the rest at the base), and calls SetSceneItemTransform.
    Silent on any miss — OBS unreachable, no overlay, item absent. `set_transform`
    is a test seam (defaults to obs_ws.set_scene_item_transform)."""
    import overlay_build
    try:
        with open(os.path.join(HERE, "obs", "hud.html"), encoding="utf-8") as fh:
            base = overlay_build.pov_box_from_css(overlay_build.base_style(fh.read()))
    except OSError:
        return
    if not base:                       # base page lost its #pov rule -> nothing to anchor
        return
    overrides = {}
    od = _active_overlay_dir()
    css = os.path.join(od, "hud.css") if od else None
    if css and os.path.isfile(css):
        try:
            with open(css, encoding="utf-8") as fh:
                overrides = overlay_build.pov_box_from_css(fh.read())
        except OSError:
            overrides = {}
    box = {**base, **overrides}
    source = overlay_build.OVERLAY_SLOT_OBS_SOURCES["pov"]
    if set_transform is None:
        import obs_ws
        set_transform = obs_ws.set_scene_item_transform
    import obs_ws
    transform = obs_ws.pov_scene_item_transform(box)
    ok, note = set_transform(obs_ws.STINT_SCENE, source, transform)
    if ok:
        print(f"obs: POV box synced to '{source}' "
              f"({box['left']},{box['top']} {box['width']}x{box['height']}).")
```

Then call it from `_refresh_obs_pages` right after the confirmed-refresh print (the last line of the function, around line 1844). Add:

```python
    _sync_pov_transform()              # live POV-box position sibling (best effort)
```

(Place it as the final statement of `_refresh_obs_pages`, after the `print(... refreshed browser sources ...)` line, so it only runs once the relay+OBS round-trip has succeeded.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: `ok t_oneshot_extra`, `ok t_sync_pov_transform_calls_setter_with_merged_box`, `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(racecast): wire POV-box sync into setup export + obs refresh"
```

---

### Task 5: Documentation

**Files:**
- Modify: `CLAUDE.md` (the OBS token round-trip section — note the overlay-POV → OBS-source sync)

**Interfaces:** none.

- [ ] **Step 1: Add the note to CLAUDE.md**

In `CLAUDE.md`, in the **Two token round-trips** → **OBS** bullet (the paragraph describing `setup-assets.py`), append a sentence:

```markdown
  The localized export also **syncs the per-league POV-box position**: `setup-assets.py`
  reads the active profile's `overlay/hud.css` (`--overlay-css`, passed by the CLI) and
  applies its `#pov` box (`left/top/width/height`) onto the OBS **"Feed POV"** scene item
  (`pos`/`bounds` — the 1:1 overlay-frame↔PiP mapping). The same box is pushed **live** to
  a running OBS by the `racecast obs refresh` / `relay start` / `event start` hook
  (`_sync_pov_transform` → `obs_ws.set_scene_item_transform`), so a builder edit aligns the
  PiP immediately without a re-import. POV-only (`overlay_build.OVERLAY_SLOT_OBS_SOURCES`);
  best-effort — a missing overlay/OBS leaves today's behavior. Pure parser:
  `overlay_build.pov_box_from_css`. Spec: `docs/superpowers/specs/2026-06-26-pov-box-obs-sync-design.md`.
```

- [ ] **Step 2: Run the full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: all tests pass; lint clean.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note the overlay POV-box -> OBS Feed POV sync"
```

---

## Self-Review

**Spec coverage:**
- Source of truth = Option B (parse override CSS) → Task 1 `pov_box_from_css`. ✓
- POV-only slot→source map → Task 1 `OVERLAY_SLOT_OBS_SOURCES`. ✓
- 1:1 CSS→OBS mapping → Task 3 `pov_scene_item_transform`. ✓
- Export bake (`setup-assets`, `--overlay-css`, every "Feed POV" item, unset-keeps-existing) → Task 2. ✓
- Live sync via `_refresh_obs_pages` (merge over base, `set_scene_item_transform`, STINT_SCENE) → Task 4. ✓
- Best-effort contract everywhere (OBS unreachable / item absent / no override) → Tasks 2-4 tests. ✓
- `#pov-name` ignored → Task 1 `t_pov_box_from_css_ignores_pov_name_and_non_px`. ✓
- Edge cases (absent/partial/malformed/cascade/float) → Task 1 tests. ✓
- Docs note (no UI screenshot needed — no visible surface change) → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every run step states the command + expected output. ✓

**Type consistency:** `pov_box_from_css` returns `{left,top,width,height}` keys (CSS names); `pov_scene_item_transform` consumes those exact keys and emits OBS `positionX/positionY/boundsWidth/boundsHeight`; `apply_pov_transform` consumes the same CSS-named keys and writes `pos.x/pos.y/bounds.x/bounds.y`. `POV_SOURCE_NAME` / `OVERLAY_SLOT_OBS_SOURCES["pov"]` = `"Feed POV"` consistently; `obs_ws.STINT_SCENE` = `"Stint"`. ✓
