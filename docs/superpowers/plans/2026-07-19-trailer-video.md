# Trailer Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a director-controllable **Trailer** clip that works exactly like Intro/Outro — maintainable via the Sheet Assets tab, its own OBS scene, and controllable from the Director Panel and Companion / Web Buttons.

**Architecture:** The Trailer reuses the entire Intro/Outro pipeline. Most machinery (relay `/obs/scene`, `setup-assets.py` token injection, `placeholders.py`, `tools/tokenize-obs.py`) is already generic and needs no change; the work is threading one more media key (`trailer`) through the handful of spots hard-coded to the intro/outro pair, adding an OBS scene, one Director-Panel PGM macro, and one Companion button.

**Tech Stack:** Python 3 stdlib (no framework, no package manager), stdlib-only runnable test scripts (no pytest), an OBS scene-collection JSON, a Companion `.companionconfig` JSON, and the `src/director/director-panel.html` string.

## Global Constraints

- **Edit only under `src/`** (plus `docs/`, `tests/`, `profiles/`). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all shipped code and docs.
- **No hardcoded secrets or machine paths.**
- **Tooling is Python-only** — no `.sh`/`.bat`.
- **TDD:** failing test first, then the fix. Each test file is a runnable stdlib script (`python3 tests/test_X.py`), auto-discovering `t_*` functions.
- **Naming (locked in the spec):** Sheet label `Trailer Video`; profile key `TRAILER_URL`; env `RACECAST_TRAILER_URL`; file `trailer.mp4`; OBS scene `Trailer` / source `Trailer Video`; Panel/Companion label `TRAILER`.
- **Companion placement (confirmed with user):** `TRAILER` button on PAGE 1 slot `0/7`; the existing `RED FLAG` button moves to the first free slot `4/3`.
- **Playback (confirmed):** loop with own audio, `restart_on_activate` — identical to the Intro scene; the PGM macro mutes Feed A/Feed B/Discord Audio Capture.
- **No default URL in code/profile.env** — the demo default is a `Trailer Video` row the user adds to the demo Sheet; the repo ships only a `SAMPLE0TRAILER` template row.
- After Python changes run `python3 tools/lint.py`; the whole suite is `python3 tools/run-tests.py`.
- **Screenshots same-change rule:** Director Panel and Companion PAGE 1 both change → refresh `director-panel.png` and `companion-page1-*.png` in this branch.

Spec: `docs/superpowers/specs/2026-07-19-trailer-video-design.md`. Work on branch `feat/trailer-video` (already created).

---

### Task 1: Thread the `trailer` key through `get-media.py` (+ graphics skip-list)

**Files:**
- Modify: `src/relay/get-media.py` (`MEDIA_LABELS` line 50; `--which`/`cli`/`--trailer-url` in `main()` lines 355–385)
- Modify: `src/relay/get-graphics.py` (`MEDIA_LABELS` skip-set, line 123)
- Test: `tests/test_media.py`

**Interfaces:**
- Consumes: existing pure helpers `media_urls_from_csv(rows) -> dict`, `resolve_urls(which, cli, env, csv_text) -> dict`, `seed_missing_media(out, which)`.
- Produces: `MEDIA_LABELS` now maps `"trailer video" -> "trailer"`; `--which all` expands to `{"intro","outro","trailer"}`; `--which trailer` and `--trailer-url` exist. No signature changes — the generalisation is data-driven.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_media.py` (before the `if __name__` block):

```python
def t_urls_trailer_label():
    rows = [["Trailer Video", "https://youtu.be/TTT"]]
    assert m.media_urls_from_csv(rows) == {"trailer": "https://youtu.be/TTT"}, \
        m.media_urls_from_csv(rows)


def t_urls_all_three_media_labels():
    rows = [["Intro Video", "https://youtu.be/AAA"],
            ["Outro Video", "https://youtu.be/BBB"],
            ["Trailer Video", "https://youtu.be/TTT"]]
    assert m.media_urls_from_csv(rows) == {
        "intro": "https://youtu.be/AAA", "outro": "https://youtu.be/BBB",
        "trailer": "https://youtu.be/TTT"}


def t_resolve_trailer_priority_cli_then_env():
    cli = {"trailer": "CLI"}
    env = {"RACECAST_TRAILER_URL": "ENV"}
    assert m.resolve_urls({"trailer"}, cli, env, None) == {"trailer": "CLI"}
    assert m.resolve_urls({"trailer"}, {"trailer": None}, env, None) == {"trailer": "ENV"}


def t_graphics_skip_set_includes_trailer():
    # get-graphics must skip the Trailer row so it is not downloaded as a PNG.
    assert "trailer video" in graphics.MEDIA_LABELS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_media.py`
Expected: FAIL — `t_urls_trailer_label` returns `{}` (label unknown), `t_graphics_skip_set_includes_trailer` AssertionError.

- [ ] **Step 3: Add the Trailer label in `get-media.py`** — line 50:

```python
# Sheet label cell -> output key.
MEDIA_LABELS = {"intro video": "intro", "outro video": "outro",
                "trailer video": "trailer"}
```

- [ ] **Step 4: Wire `--which`, the `cli` dict, and `--trailer-url` in `main()`** — edit the `--which` argument (line 355), add the flag (after line 366), and the set/`cli` logic (lines 377–385):

Change the `--which` choices + help:

```python
    ap.add_argument("--which",
                    choices=["intro", "outro", "trailer", "music", "both", "all"],
                    default="all",
                    help="Which assets to fetch: intro, outro, trailer, music, "
                         "both (=intro+outro), all (=intro+outro+trailer+music, default).")
```

Add the flag next to `--outro-url` (after line 366):

```python
    ap.add_argument("--trailer-url", default=None)
```

Change the set-expansion + `cli` dict (lines 377–385):

```python
    # Determine video clip set and music flag.
    if a.which == "all":
        which = {"intro", "outro", "trailer"}
    elif a.which == "both":
        which = {"intro", "outro"}
    elif a.which == "music":
        which = set()
    else:
        which = {a.which}
    want_music = a.which in ("all", "music")

    cli = {"intro": a.intro_url, "outro": a.outro_url, "trailer": a.trailer_url}
```

(`resolve_urls`, `seed_missing_media`, `reset_unlinked_media`, and the download loop all iterate `which`, so they now handle `trailer` with no further change. The "No URL for {key}" message already reads `f"{key.title()} Video"` → "Trailer Video".)

- [ ] **Step 5: Add `"trailer video"` to the graphics skip-set** — `src/relay/get-graphics.py` line 123:

```python
MEDIA_LABELS = {"intro video", "outro video", "trailer video", "intermission music"}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 tests/test_media.py`
Expected: `ALL PASS`

- [ ] **Step 7: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/get-media.py src/relay/get-graphics.py tests/test_media.py
git commit -m "feat(media): thread trailer key through get-media + graphics skip-list"
```

---

### Task 2: Profile → child-env plumbing for `TRAILER_URL`

**Files:**
- Modify: `src/scripts/config.py` (`ResolvedConfig` line 156; `resolve_config` return line 213)
- Modify: `src/racecast.py` (`_profile_env_vars` lines 214–215)
- Modify: `profiles/example/profile.env`, `profiles/demo/profile.env` (Intro/Outro block)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `ResolvedConfig` dataclass, `_profile_env_vars(rc) -> dict`.
- Produces: `ResolvedConfig.trailer_url: str = ""`; `_profile_env_vars` emits `RACECAST_TRAILER_URL` when non-empty. `get-media.py` (Task 1) reads `RACECAST_TRAILER_URL` via `resolve_urls`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_racecast.py` (near `t_profile_env_vars_includes_event_title`, before `if __name__`). The file has no `_rc` helper — build the config with `m.pcfg.ResolvedConfig(...)` exactly like the sibling tests:

```python
def t_profile_env_vars_includes_trailer_url():
    rc = m.pcfg.ResolvedConfig(profile="demo", name="Demo", sheet_id="abc",
                               trailer_url="https://youtu.be/TTT")
    assert m._profile_env_vars(rc)["RACECAST_TRAILER_URL"] == "https://youtu.be/TTT"
    # empty -> filtered out
    rc2 = m.pcfg.ResolvedConfig(profile="demo", name="Demo", sheet_id="abc")
    assert "RACECAST_TRAILER_URL" not in m._profile_env_vars(rc2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `ResolvedConfig` has no `trailer_url` (TypeError) or `RACECAST_TRAILER_URL` missing (KeyError).

- [ ] **Step 3: Add the field to `ResolvedConfig`** — `src/scripts/config.py` line 156, right after `outro_url`:

```python
    intro_url: str = ""
    outro_url: str = ""
    trailer_url: str = ""
```

- [ ] **Step 4: Populate it in `resolve_config`** — `src/scripts/config.py` line 213, after `outro_url=...`:

```python
        intro_url=prof.get("INTRO_URL", ""),
        outro_url=prof.get("OUTRO_URL", ""),
        trailer_url=prof.get("TRAILER_URL", ""),
```

- [ ] **Step 5: Emit the child env var** — `src/racecast.py` `_profile_env_vars` line 215, after the OUTRO pair:

```python
             ("RACECAST_INTRO_URL", rc.intro_url),
             ("RACECAST_OUTRO_URL", rc.outro_url),
             ("RACECAST_TRAILER_URL", rc.trailer_url),
```

- [ ] **Step 6: Add `TRAILER_URL=` to both profile templates** — in `profiles/example/profile.env` and `profiles/demo/profile.env`, extend the Intro/Outro comment + keys. Replace the existing block:

```
# OPTIONAL: override the Intro/Outro clip URLs (normally taken from the Sheet's
# Assets tab cells "Intro Video" / "Outro Video").
INTRO_URL=
OUTRO_URL=
```

with:

```
# OPTIONAL: override the Intro/Outro/Trailer clip URLs (normally taken from the
# Sheet's Assets tab cells "Intro Video" / "Outro Video" / "Trailer Video").
INTRO_URL=
OUTRO_URL=
TRAILER_URL=
```

(Match each file's exact wording — `demo` says "Sheet's Assets tab", `example` says "sheet's Assets tab"; keep the file's own casing, just add the Trailer clause + `TRAILER_URL=` line.)

- [ ] **Step 7: Run test + config test to verify pass**

Run: `python3 tests/test_racecast.py && python3 tests/test_config.py`
Expected: both `ALL PASS`

- [ ] **Step 8: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/config.py src/racecast.py profiles/example/profile.env profiles/demo/profile.env tests/test_racecast.py
git commit -m "feat(config): TRAILER_URL profile key -> RACECAST_TRAILER_URL"
```

---

### Task 3: Include `trailer.mp4` in `event.py` asset-readiness fallback

**Files:**
- Modify: `src/scripts/event.py` (`required_media` lines 219–226)
- Test: `tests/test_event.py` (`t_required_media_from_assets_rows` lines 117–123)

**Interfaces:**
- Consumes: `gm.media_urls_from_csv(rows)` (now returns `trailer` when the Sheet has the row — Task 1).
- Produces: `required_media(gm, None)` and the empty-media fallback now include `"trailer.mp4"` (the OBS collection references all three clips).

- [ ] **Step 1: Update the test to expect trailer in the fallback** — `tests/test_event.py` lines 117–123, replace with:

```python
def t_required_media_from_assets_rows():
    gm = _load_relay("get-media.py")
    rows = [["Intro Video", "https://youtu.be/xyz"]]
    assert m.required_media(gm, rows) == ["intro.mp4"]
    # No media rows in the sheet -> require all three (the OBS scenes reference them).
    assert m.required_media(gm, [["Overlay", "u"]]) == \
        ["intro.mp4", "outro.mp4", "trailer.mp4"]
    assert m.required_media(gm, None) == ["intro.mp4", "outro.mp4", "trailer.mp4"]
    # A Sheet Trailer row flows through media_urls_from_csv -> included.
    rows3 = [["Trailer Video", "https://youtu.be/ttt"]]
    assert m.required_media(gm, rows3) == ["trailer.mp4"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_event.py`
Expected: FAIL — `required_media(gm, None)` still returns `["intro.mp4", "outro.mp4"]`.

- [ ] **Step 3: Update `required_media`** — `src/scripts/event.py` lines 219–226:

```python
def required_media(gm, rows):
    """intro.mp4/outro.mp4/trailer.mp4 for each media row found in the Assets tab;
    all three when the sheet defines none or is unreadable (the OBS Intro/Outro/
    Trailer scenes reference them)."""
    if rows is None:
        return ["intro.mp4", "outro.mp4", "trailer.mp4"]
    keys = sorted(gm.media_urls_from_csv(rows)) or ["intro", "outro", "trailer"]
    return [f"{k}.mp4" for k in keys]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_event.py`
Expected: `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): trailer.mp4 in required-media fallback"
```

---

### Task 4: Add the `Trailer` OBS scene + `Trailer Video` source

**Files:**
- Modify: `src/obs/GT_Endurance.json` (`scene_order` line 301; the top-level `sources` array — insert after the `Outro Video` source object)
- Modify: `tests/test_placeholders.py` (`t_setup_assets_fills_placeholders_for_missing` ~line 117; `t_get_media_seeds_placeholder_clip` ~line 174)
- Test: `tests/test_trailer.py` (created in Task 5 — the OBS assertion is added there; keep Task 4's OBS edit tested by the placeholder round-trip here)

**Interfaces:**
- Consumes: `setup-assets.py` token injection + `placeholders.py` template scan (generic — a new `__RACECAST_MEDIA__/trailer.mp4` reference is auto-placeholdered).
- Produces: OBS scene `Trailer` (uuid `cccccccc-cccc-4ccc-8ccc-cccccccccccc`) with item `Trailer Video` → `ffmpeg_source` `Trailer Video` (uuid `ca7a7a7a-0000-4000-8000-0000000000c1`), `local_file: __RACECAST_MEDIA__/trailer.mp4`, `looping/restart_on_activate/close_when_inactive: true`, `mixers: 255`.

- [ ] **Step 1: Write the failing placeholder round-trip test** — extend `tests/test_placeholders.py` `t_setup_assets_fills_placeholders_for_missing` to include a trailer ref. Add this line inside the `sources` list (after the `outro.mp4` entry, ~line 128):

```python
                {"settings": {"local_file": "__RACECAST_MEDIA__/trailer.mp4"}},
```

and add this assertion after the `outro.mp4` assertion (~line 141):

```python
        assert os.path.isfile(os.path.join(med, "trailer.mp4")), r.stdout
```

Also extend `t_get_media_seeds_placeholder_clip` (~line 174) to cover trailer — replace its body's first two lines:

```python
def t_get_media_seeds_placeholder_clip():
    gm = _load_script("relay/get-media.py")
    with tempfile.TemporaryDirectory() as tmp:
        seeded = gm.seed_missing_media(tmp, {"intro", "outro", "trailer"})
        assert sorted(seeded) == ["intro.mp4", "outro.mp4", "trailer.mp4"]
        with open(MP4, "rb") as a, open(os.path.join(tmp, "intro.mp4"), "rb") as b:
            assert a.read() == b.read()
        # already-present clip is not overwritten / re-listed
        assert gm.seed_missing_media(tmp, {"intro"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_placeholders.py`
Expected: `t_get_media_seeds_placeholder_clip` FAILS immediately (`seed_missing_media` returns 3 names as soon as we pass `{"intro","outro","trailer"}` — that part passes — but `t_setup_assets_fills_placeholders_for_missing` FAILS: no `trailer.mp4` written because the OBS edit is not done yet). Confirm at least the setup-assets assertion fails.

- [ ] **Step 3: Add `Trailer` to `scene_order`** — `src/obs/GT_Endurance.json`, after the `Outro` entry (line 301–302), before `Discord`:

```json
        {
            "name": "Outro"
        },
        {
            "name": "Trailer"
        },
        {
            "name": "Discord"
        },
```

- [ ] **Step 4: Add the `Trailer` scene + `Trailer Video` source objects** — in the top-level `sources` array, immediately after the `Outro Video` `ffmpeg_source` object (find the object with `"name": "Outro Video"` and insert right after its closing `},`). Paste both objects (indentation: 8 spaces, matching the surrounding array items):

```json
        {
            "prev_ver": 536936450,
            "name": "Trailer",
            "uuid": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "id": "scene",
            "versioned_id": "scene",
            "settings": {
                "custom_size": false,
                "id_counter": 2,
                "items": [
                    {
                        "name": "Trailer Video",
                        "source_uuid": "ca7a7a7a-0000-4000-8000-0000000000c1",
                        "visible": true,
                        "locked": true,
                        "rot": 0.0,
                        "align": 5,
                        "bounds_type": 0,
                        "bounds_align": 0,
                        "bounds_crop": false,
                        "crop_left": 0,
                        "crop_top": 0,
                        "crop_right": 0,
                        "crop_bottom": 0,
                        "id": 1,
                        "group_item_backup": false,
                        "pos": {
                            "x": 0.0,
                            "y": 0.0
                        },
                        "scale": {
                            "x": 1.0,
                            "y": 1.0
                        },
                        "bounds": {
                            "x": 0.0,
                            "y": 0.0
                        },
                        "scale_filter": "disable",
                        "blend_method": "default",
                        "blend_type": "normal",
                        "show_transition": {
                            "duration": 300
                        },
                        "hide_transition": {
                            "duration": 300
                        },
                        "private_settings": {}
                    }
                ]
            },
            "mixers": 0,
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
                "OBSBasic.SelectScene": [],
                "libobs.show_scene_item.1": [],
                "libobs.hide_scene_item.1": []
            },
            "deinterlace_mode": 0,
            "deinterlace_field_order": 0,
            "monitoring_type": 0,
            "canvas_uuid": "6c69626f-6273-4c00-9d88-c5136d61696e",
            "private_settings": {}
        },
        {
            "prev_ver": 536936450,
            "name": "Trailer Video",
            "uuid": "ca7a7a7a-0000-4000-8000-0000000000c1",
            "id": "ffmpeg_source",
            "versioned_id": "ffmpeg_source",
            "settings": {
                "close_when_inactive": true,
                "hw_decode": true,
                "local_file": "__RACECAST_MEDIA__/trailer.mp4",
                "is_local_file": true,
                "looping": true,
                "clear_on_media_end": false,
                "restart_on_activate": true,
                "buffering_mb": 8,
                "speed_percent": 100
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
                "MediaSource.Restart": [],
                "MediaSource.Play": [],
                "MediaSource.Pause": [],
                "MediaSource.Stop": []
            },
            "deinterlace_mode": 0,
            "deinterlace_field_order": 0,
            "monitoring_type": 0,
            "private_settings": {}
        },
```

- [ ] **Step 5: Verify the JSON still parses**

Run: `python3 -c "import json; json.load(open('src/obs/GT_Endurance.json')); print('OK valid JSON')"`
Expected: `OK valid JSON`

- [ ] **Step 6: Run the placeholder test to verify it passes**

Run: `python3 tests/test_placeholders.py`
Expected: `ALL PASS` (setup-assets now round-trips a `trailer.mp4` placeholder into the media dir).

- [ ] **Step 7: Lint + commit**

```bash
python3 tools/lint.py
git add src/obs/GT_Endurance.json tests/test_placeholders.py
git commit -m "feat(obs): Trailer scene + Trailer Video source (looping, own audio)"
```

---

### Task 5: Director-Panel `TRAILER` PGM macro + a focused `tests/test_trailer.py`

**Files:**
- Modify: `src/director/director-panel.html` (`CONFIG.macros`, after the OUTRO macro line 883–884)
- Create: `tests/test_trailer.py`

**Interfaces:**
- Consumes: the panel's existing `runMacro`/`obsScene` → `POST /obs/scene` path (generic, unchanged).
- Produces: a `{label:"TRAILER", scene:"Trailer", …}` macro rendered onto `#pgmBus` next to INTRO/OUTRO. `tests/test_trailer.py` asserts the panel macro, the OBS scene, and (after Task 6) the Companion button.

- [ ] **Step 1: Create the failing test** — `tests/test_trailer.py`:

```python
#!/usr/bin/env python3
"""Content checks for the Trailer control surfaces. Run: python3 tests/test_trailer.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def t_obs_collection_has_trailer_scene_and_source():
    cfg = json.loads(_read(os.path.join("src", "obs", "GT_Endurance.json")))
    names = {s.get("name") for s in cfg.get("sources", [])}
    assert "Trailer" in names, "no Trailer scene in the collection"
    assert "Trailer Video" in names, "no Trailer Video source"
    order = {e.get("name") for e in cfg.get("scene_order", [])}
    assert "Trailer" in order, "Trailer missing from scene_order"
    src = next(s for s in cfg["sources"] if s.get("name") == "Trailer Video")
    st = src.get("settings", {})
    assert st.get("local_file") == "__RACECAST_MEDIA__/trailer.mp4", st
    assert st.get("looping") is True and st.get("restart_on_activate") is True, st


def t_panel_has_trailer_macro():
    html = _read(os.path.join("src", "director", "director-panel.html"))
    i = html.index('{label:"TRAILER"')
    macro = html[i:html.index('}', i) + 1]
    assert 'scene:"Trailer"' in macro, macro
    # loop-clip-with-own-audio: mutes the feeds + Discord, like INTRO/OUTRO.
    for name in ("Feed A", "Feed B", "Discord Audio Capture"):
        assert name in macro, f"TRAILER macro must mute {name}"


# NOTE: the Companion button assertions (t_companion_has_trailer_button,
# t_companion_red_flag_still_present) are added to THIS file in Task 6, so every
# commit stays green — do not add them here in Task 5.


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify the panel check fails**

Run: `python3 tests/test_trailer.py`
Expected: `t_obs_collection_has_trailer_scene_and_source` PASSES (Task 4 done), `t_panel_has_trailer_macro` FAILS (`substring not found`).

- [ ] **Step 3: Add the TRAILER macro** — `src/director/director-panel.html`, after the OUTRO macro (line 884):

```javascript
    {label:"OUTRO", scene:"Outro", show:[], hide:[],
     unmute:[], mute:["Feed A","Feed B","Discord Audio Capture"]},
    {label:"TRAILER", scene:"Trailer", show:[], hide:[],
     unmute:[], mute:["Feed A","Feed B","Discord Audio Capture"]},
```

- [ ] **Step 4: Run the whole test file to verify it passes**

Run: `python3 tests/test_trailer.py`
Expected: `ALL PASS` (OBS scene check + panel macro check — the Companion checks are added in Task 6).

- [ ] **Step 5: Commit the panel macro + test**

```bash
git add src/director/director-panel.html tests/test_trailer.py
git commit -m "feat(panel): TRAILER PGM macro next to INTRO/OUTRO"
```

---

### Task 6: Companion `TRAILER` button (slot 0/7), move `RED FLAG` to 4/3

> **This task uses the `companion-buttons` skill** (see CLAUDE.md: it authors the button JSON, exports, imports into a running Companion via Playwright with "Import Preserving Unselected", and click-tests — keeping a minimal 1-space-indent diff). Invoke that skill to perform the import/validation; the exact JSON below is the button to author. The file is 1-space indented — preserve that.

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig` (PAGE 1 `controls`: move `"0"/"7"` → `"4"/"3"`; add new `"0"/"7"`)
- Test: `tests/test_trailer.py` (already written in Task 5 — `t_companion_has_trailer_button`, `t_companion_red_flag_still_present`)

**Interfaces:**
- Consumes: the native OBS-WebSocket Companion connection (`connectionId: "dv_e1zuVb_6XgPv0eRibl"`, `definitionId: "set_scene"` / `set_source_mute` / `sceneProgram`) used by INTRO/OUTRO.
- Produces: a PAGE 1 button at `0/7` labelled `TRAILER` that switches to scene `Trailer` and mutes Discord/Feed A/Feed B (mirror of INTRO); `RED FLAG` relocated to `4/3`, unchanged otherwise.

- [ ] **Step 0: Add the failing Companion test functions** — append to `tests/test_trailer.py` (before the `if __name__` block; they replace the Task-5 NOTE comment):

```python
def t_companion_has_trailer_button():
    cfg = json.loads(_read(os.path.join("src", "companion", "racecast-buttons.companionconfig")))

    def downs(btn):
        try:
            return btn["steps"]["0"]["action_sets"]["down"]
        except (KeyError, TypeError):
            return []

    def scene_val(a):
        return ((a.get("options") or {}).get("scene") or {}).get("value")

    target = None
    for page in cfg.get("pages", {}).values():
        for row in (page.get("controls", {}) or {}).values():
            for btn in (row or {}).values():
                if isinstance(btn, dict) and any(scene_val(a) == "Trailer" for a in downs(btn)
                                                 if isinstance(a, dict)):
                    target = btn
    assert target is not None, "no Companion button switches to the Trailer scene"
    assert (target.get("style") or {}).get("text") == "TRAILER", target.get("style")


def t_companion_red_flag_still_present():
    # RED FLAG moved slots but must still exist (it also lives on PAGE 3).
    raw = _read(os.path.join("src", "companion", "racecast-buttons.companionconfig"))
    assert "RED\\nFLAG" in raw, "RED FLAG button disappeared"
```

Run: `python3 tests/test_trailer.py`
Expected: FAIL — `t_companion_has_trailer_button` (no such button yet).

- [ ] **Step 1: Move the existing `RED FLAG` button** — in `src/companion/racecast-buttons.companionconfig`, PAGE 1 `controls`: take the whole button object currently at `controls["0"]["7"]` (the `RED\nFLAG` button) and move it to `controls["4"]["3"]` (an empty slot). Do not change its internals — only its grid position (the dictionary key).

- [ ] **Step 2: Add the `TRAILER` button at the now-free `0/7`** — insert this object at `controls["0"]["7"]` (mirrors the INTRO button at `0/5`, scene `Trailer`, fresh action/feedback ids):

```json
     "7": {
      "type": "button",
      "style": {
       "text": "TRAILER",
       "textExpression": false,
       "size": "18",
       "png64": null,
       "alignment": "center:center",
       "pngalignment": "center:center",
       "color": 16777215,
       "bgcolor": 0,
       "show_topbar": "default"
      },
      "options": {
       "stepProgression": "auto",
       "stepExpression": "",
       "rotaryActions": false
      },
      "feedbacks": [
       {
        "id": "trailerFbSceneProg01",
        "definitionId": "sceneProgram",
        "connectionId": "dv_e1zuVb_6XgPv0eRibl",
        "options": {
         "scene": {
          "value": "Trailer",
          "isExpression": false
         }
        },
        "type": "feedback",
        "style": {
         "color": 16777215,
         "bgcolor": 13107200
        },
        "isInverted": {
         "value": false,
         "isExpression": false
        },
        "upgradeIndex": 8
       }
      ],
      "steps": {
       "0": {
        "action_sets": {
         "down": [
          {
           "id": "trailerActSetScene01",
           "definitionId": "set_scene",
           "connectionId": "dv_e1zuVb_6XgPv0eRibl",
           "options": {
            "scene": {
             "value": "Trailer",
             "isExpression": false
            },
            "customSceneName": {
             "value": "",
             "isExpression": false
            }
           },
           "type": "action",
           "upgradeIndex": 8
          },
          {
           "id": "trailerActMuteDisc01",
           "definitionId": "set_source_mute",
           "connectionId": "dv_e1zuVb_6XgPv0eRibl",
           "options": {
            "source": {
             "value": "Discord Audio Capture",
             "isExpression": false
            },
            "mute": {
             "value": "true",
             "isExpression": false
            }
           },
           "type": "action",
           "upgradeIndex": 8
          },
          {
           "id": "trailerActMuteFeedA1",
           "definitionId": "set_source_mute",
           "connectionId": "dv_e1zuVb_6XgPv0eRibl",
           "options": {
            "source": {
             "value": "Feed A",
             "isExpression": false
            },
            "mute": {
             "value": "true",
             "isExpression": false
            }
           },
           "type": "action",
           "upgradeIndex": 8
          },
          {
           "id": "trailerActMuteFeedB1",
           "definitionId": "set_source_mute",
           "connectionId": "dv_e1zuVb_6XgPv0eRibl",
           "options": {
            "source": {
             "value": "Feed B",
             "isExpression": false
            },
            "mute": {
             "value": "true",
             "isExpression": false
            }
           },
           "type": "action",
           "upgradeIndex": 8
          }
         ],
         "up": []
        },
        "options": {
         "runWhileHeld": []
        }
       }
      },
      "localVariables": []
     },
```

- [ ] **Step 3: Verify the config is still valid JSON**

Run: `python3 -c "import json; json.load(open('src/companion/racecast-buttons.companionconfig')); print('OK valid JSON')"`
Expected: `OK valid JSON`

- [ ] **Step 4: Import + click-test via the companion-buttons skill**

Use the `companion-buttons` skill to import the edited config into a running Companion ("Import Preserving Unselected"), bind to the Tailscale IP, then click the `TRAILER` button and confirm OBS switches to the `Trailer` scene and the feeds/Discord mute. Confirm `RED FLAG` at `4/3` still fires. (This validates against a live Companion+OBS; the skill documents the exact Playwright steps.)

- [ ] **Step 5: Run the Trailer test to verify all checks pass**

Run: `python3 tests/test_trailer.py`
Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add src/companion/racecast-buttons.companionconfig
git commit -m "feat(companion): TRAILER button on PAGE 1 (0/7); move RED FLAG to 4/3"
```

---

### Task 7: Sample template row + docs

**Files:**
- Modify: `src/docs/sheet-template/Assets.csv` (after the `Outro Video` row, line 27)
- Modify: `src/docs/wiki/Sheet-Template.md` (Assets sample, ~line 327), `src/docs/wiki/OBS-Setup.md` (~lines 38–40), `src/docs/wiki/Director.md`, `src/docs/wiki/Configuration.md` (~lines 39–40, 65), `src/docs/wiki/Profiles.md` (~lines 27–28, 42)
- Modify: `CLAUDE.md` (Intro/Outro mentions)
- Test: `tests/test_wiki.py` (link/anchor validation — run after wiki edits)

**Interfaces:** none (docs + a sample CSV row). The `SAMPLE0TRAILER` value is a placeholder, never fetched.

- [ ] **Step 1: Add the sample Assets row** — `src/docs/sheet-template/Assets.csv`, after line 27:

```
Intro Video,https://www.youtube.com/watch?v=SAMPLE0INTRO
Outro Video,https://www.youtube.com/watch?v=SAMPLE0OUTRO
Trailer Video,https://www.youtube.com/watch?v=SAMPLE0TRAILER
```

- [ ] **Step 2: Mirror it in the wiki Sheet template** — `src/docs/wiki/Sheet-Template.md`, after the `Outro Video` sample line (~327):

```
Intro Video          | https://www.youtube.com/watch?v=SAMPLE0INTRO
Outro Video          | https://www.youtube.com/watch?v=SAMPLE0OUTRO
Trailer Video        | https://www.youtube.com/watch?v=SAMPLE0TRAILER
```

- [ ] **Step 3: Document the Trailer scene + button** — `src/docs/wiki/OBS-Setup.md`: where it lists the Intro/Outro scenes and the Companion INTRO/OUTRO buttons (~lines 38–40), add the `Trailer` scene and the `TRAILER` PAGE 1 button in the same sentence/table style (read the surrounding lines first and match the format — one added scene + one added button).

- [ ] **Step 4: Document the panel macro / run-of-show** — `src/docs/wiki/Director.md`: wherever INTRO/OUTRO PGM macros are described, add `TRAILER` as a third looping-clip macro that mutes the feeds. Match the existing wording; do not invent broadcast procedure (state only what the button does).

- [ ] **Step 5: Document the profile key** — add `TRAILER_URL` next to `INTRO_URL`/`OUTRO_URL` in both `src/docs/wiki/Configuration.md` (~lines 39–40 code block + ~line 65 description) and `src/docs/wiki/Profiles.md` (~lines 27–28 code block + ~line 42 table row). Extend the existing "override the Intro/Outro clip URLs" phrasing to "Intro/Outro/Trailer".

- [ ] **Step 6: Update CLAUDE.md** — extend the Intro/Outro mentions to include the Trailer: the `racecast media` line (~185), the `INTRO_URL`/`OUTRO_URL` profile-keys line (~247), the `RACECAST_INTRO_URL`/`RACECAST_OUTRO_URL` line (~260–261), and the `__RACECAST_MEDIA__` / get-media → OBS scenes description (~304, ~329–331). Add "Trailer" alongside Intro/Outro in each — mechanism only, no procedure.

- [ ] **Step 7: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (per CLAUDE.md memory: always run after wiki edits).

- [ ] **Step 8: Commit**

```bash
git add src/docs/ CLAUDE.md
git commit -m "docs: Trailer video (Assets sample row, wiki, CLAUDE.md)"
```

---

### Task 8: Refresh the Director-Panel + Companion wiki screenshots

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` (+ its `src/docs/slides/assets/img/` copy if one exists)
- Modify: `src/docs/wiki/images/companion-page1-*.png`

**Interfaces:** none (image artifacts). Same-change project rule.

- [ ] **Step 1: Recapture the Director Panel** — use the `wiki-screenshots` skill to drive a local dev build (demo profile + `tools/obs-sim.py` OBS stand-in) and take the Director-Panel element screenshot, so `director-panel.png` shows the new TRAILER macro. Follow the skill's reproducible fake-content recipe.

- [ ] **Step 2: Recapture the Companion PAGE 1 board** — use the `companion-screenshots` skill to regenerate `companion-page1-*.png` showing the TRAILER button at 0/7 and RED FLAG at 4/3.

- [ ] **Step 3: Commit the images**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/wiki/images/companion-page1-*.png
git commit -m "docs(wiki): refresh Director-Panel + Companion PAGE 1 screenshots for Trailer"
```

---

### Task 9: Full-suite gate + build verify

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: all green (this is exactly what CI runs).

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build the distributable (closest thing to CI verify)**

Run: `python3 tools/build.py`
Expected: `dist/GT_Racecast_Package/` assembled + self-verify passes (tokenization intact, blanked password, no secrets, no shell scripts). Confirms the tokenized `__RACECAST_MEDIA__/trailer.mp4` survives the build and the collection stays path/secret-free.

- [ ] **Step 4: Final commit if the build produced tracked changes** (normally none — `dist/` is gitignored; commit only if a `src/`-tracked verify artifact changed)

```bash
git status --short
# if nothing tracked changed, no commit needed — the branch is ready for a PR.
```

---

## Notes for the implementer

- **One PR** for the whole feature (per repo convention). After Task 9, open a PR from `feat/trailer-video` into `main` with a summary of the Trailer feature; let full CI run (it exercises all three OSes + the binary smoke + e2e synthetic).
- **Do NOT** touch `dist/` or `runtime/` by hand.
- **Companion (Task 6)** genuinely needs a running Companion + OBS to click-validate — that is why it delegates to the `companion-buttons` skill rather than asserting only file content.
- **User-provided, outside this plan:** the user uploads a real Trailer clip to their YouTube channel and adds a `Trailer Video` row to the **demo Sheet's Assets tab**, so the `demo` profile downloads it via `racecast media`. The repo ships only the `SAMPLE0TRAILER` template row.
