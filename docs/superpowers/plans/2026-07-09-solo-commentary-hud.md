# Solo Commentary HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three builder-managed overlay elements for the solo commentary broadcast — a league-logo image slot (top-right), a Commentary-only tyres/fuel second-capture crop (bottom-left), and a broadcast-chat stream-chat slot (POV+Commentary) — plus fix the solo collections' audio monitoring so the game/race audio is heard and streamed.

**Architecture:** The overlay is the relay-served `src/obs/hud.html` (`HUD Overlay` browser source) layered over the static per-league `Overlay.png` and the full-screen `Solo Capture`. Two of the new slots are pure overlay (logo, chat: rendered in `hud.html`, no OBS source). The third (tyres capture) reuses the #324 box→OBS mechanism: a `#<slot>` CSS box drives a named OBS scene item's transform, export-time (`setup-assets.apply_box_transform`, scene-scoped via `export_scene`) and live (`racecast._sync_pov_transform` loop). Audio monitoring is a property edit on the two committed solo collection JSONs.

**Tech Stack:** Python stdlib only (no deps), plain HTML/CSS/JS overlay, OBS scene-collection JSON, PyInstaller-frozen binary. Tests are stdlib runnable scripts under `tests/`.

## Global Constraints

- **Edit only under `src/` and `tests/`.** `dist/`/`runtime/` are generated. Tooling stays Python-only (no `.sh`/`.bat`).
- **English only** in all code/docs/strings.
- **Released product (v1.x): no breaking changes.** Reuse existing helpers; keep endurance byte-identical (the three new slots self-hide; the tyres map entry is a no-op where its source is absent).
- **All scripts/tests run on any machine + CI** — no real IPs/paths, use fixtures.
- **Slot id `tyres-capture`** is used verbatim as the `OVERLAY_SLOT_OBS_SOURCES` map key, the `hud.html` element id, and the `#tyres-capture` CSS id.
- **Tyres crop is fixed** at `crop_left:258, crop_top:950, crop_right:1336, crop_bottom:18`; the builder box drives only position/size.
- **Audio config (both `src/obs/GT_Racing_Solo_POV.json` + `GT_Racing_Solo_Commentary.json`):** `Solo Capture Device` → `muted:false, monitoring_type:2`; `Discord Audio Capture` → `monitoring_type:2`; `Intro Video`/`Outro Video`/`Intermission Music` → `monitoring_type:2`; the mic unchanged; (Commentary) new `Solo Tyres Capture Device` → `muted:true`.
- **Positions/sizes are provisional** — the CSS default boxes below are sensible starting values; final tuning happens in a later visual dialog. Do not treat pixel-exactness as a spec requirement; do keep the slots in their intended corner (logo top-right, tyres/chat bottom-left).
- After any Python edit run `python3 tools/lint.py`; before finishing run `python3 tools/run-tests.py` (full suite) — both green.
- Do NOT `git add -A` (untracked `tools/cloud/*.sh` + `scratchpad/` must stay untracked); add only the files each task lists.
- The three new slots are all `data-edit-kind="box"`, so they need **no** `SAMPLE` entry (`t_ob_sample_covers_every_text_slot` covers only text slots). Do not add SAMPLE entries for them.

---

## File Structure

- `src/relay/racecast-feeds.py` — add a `/hud/logo` route (loopback) serving the league logo; `logo_path` is already threaded into `make_handler`. (Task 1)
- `src/obs/hud.html` — add the `#league-logo`, `#chat`, `#tyres-capture` slots + their default CSS + the `#chat` poll/render JS. (Tasks 1, 2, 4)
- `src/scripts/overlay_build.py` — add the `tyres-capture` entry to `OVERLAY_SLOT_OBS_SOURCES`. (Task 4)
- `src/setup-assets.py` — add `Solo Tyres Capture Device` to `DEVICE_SOURCES`. (Task 3)
- `src/obs/GT_Racing_Solo_Commentary.json` — add the tyres capture source + Program embed with the baked crop. (Task 3)
- `src/obs/GT_Racing_Solo_POV.json` + `GT_Racing_Solo_Commentary.json` — audio monitoring property edits. (Task 5)
- Tests: `tests/test_overlay.py` (slot list, `OVERLAY_SLOT_OBS_SOURCES`, `box_from_css`), `tests/test_discord_audio.py` (device localize + `apply_box_transform`), `tests/test_racecast.py` (`_sync_pov_transform`), `tests/test_hud.py` or a new relay handler test (`/hud/logo`), and a new `tests/test_solo_audio.py` (monitoring assertions).

---

## Task 1: League-logo relay route + HUD slot

**Files:**
- Modify: `src/relay/racecast-feeds.py` (handler `do_GET`, near the `p == ["hud", "override.css"]` route ~line 6840; `logo_path` param already in `make_handler` ~5948)
- Modify: `src/obs/hud.html` (slot markup + a `#league-logo` CSS rule)
- Test: `tests/test_hud.py`

**Interfaces:**
- Consumes: `servable_logo_path(logo_path)` (returns the path if a web-image by extension, else `""`); `_LOGO_CTYPES` dict (ext→content-type); the handler's `logo_path` closure var; `self._send_file(path, ctype)` and `self._send(obj, status)`.
- Produces: a `GET /hud/logo` route (200 image / 404 JSON) and a `#league-logo` box slot in `hud.html` (so `extract_slots` returns it).

- [ ] **Step 1: Write the failing handler test**

Add to `tests/test_hud.py` (it already spins a relay handler in-process; mirror an existing route test there — reuse its handler-construction helper, passing `logo_path`):

```python
def t_hud_logo_route_serves_image_and_404s():
    import tempfile, os
    # A relay handler built with a real logo file serves it at /hud/logo;
    # built with no logo, /hud/logo is 404.
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "logo.png")
        with open(png, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")            # minimal PNG signature
        got = _get_route(logo_path=png, path="/hud/logo")     # helper in this file
        assert got.status == 200
        assert got.ctype.startswith("image/")
        assert got.body.startswith(b"\x89PNG")
        none = _get_route(logo_path="", path="/hud/logo")
        assert none.status == 404
```

If `tests/test_hud.py` has no reusable single-route helper, add a small one that builds `make_handler(...)` with a fake socket and captures the response (mirror the pattern the file already uses for `/hud` / `/hud/data`). Keep it in the test file.

- [ ] **Step 2: Run the test, verify it fails**

Run: `python3 tests/test_hud.py`
Expected: FAIL (no `/hud/logo` route → 404 for the served case, or helper missing).

- [ ] **Step 3: Add the `/hud/logo` route**

In `src/relay/racecast-feeds.py`, in `do_GET`, next to the other `["hud", …]` routes (after `p == ["hud", "override.css"]`), add:

```python
                if p == ["hud", "logo"]:
                    # League logo for the HUD overlay slot (#league-logo). Loopback —
                    # OBS reads it on 127.0.0.1; served from the active profile's LOGO
                    # (logo_path). 404 when unset/non-image so the slot self-hides.
                    path = servable_logo_path(logo_path)
                    if not path:
                        return self._send({"error": "no logo"}, 404)
                    ext = os.path.splitext(path)[1].lower()
                    return self._send_file(path, _LOGO_CTYPES.get(ext, "image/png"))
```

(`logo_path`, `servable_logo_path`, `_LOGO_CTYPES`, `self._send_file`, `self._send` all already exist — this mirrors the `/console/logo` route at ~6527.)

- [ ] **Step 4: Add the HUD slot + default CSS**

In `src/obs/hud.html`, in the slot markup block (near the `#pov`/`#pov-name` slots), add:

```html
  <div id="league-logo" class="el" data-edit="League logo" data-edit-kind="box"><img alt="" src="/hud/logo" onerror="this.parentElement.style.display='none'"></div>
```

In the `<style>` block add a default box (top-right, provisional) and make the img fit:

```css
  #league-logo{left:1672px;top:20px;width:208px;height:120px}
  #league-logo img{max-width:100%;max-height:100%;object-fit:contain}
```

(No `SAMPLE` entry — it is a box slot; the builder canvas shows it as an empty positioning box, the real logo renders in OBS.)

- [ ] **Step 5: Extend the slot-list test**

In `tests/test_overlay.py::t_ob_extract_slots_from_real_hud`, add `"league-logo"` to the expected id list at the document-order position you placed it (run the test; it prints the actual order on mismatch). Place the markup so the order is deterministic.

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_hud.py && python3 tests/test_overlay.py && python3 tools/lint.py`
Expected: PASS / All checks passed.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py src/obs/hud.html tests/test_hud.py tests/test_overlay.py
git commit -m "feat(solo): league-logo HUD slot + /hud/logo relay route (epic #300)"
```

---

## Task 2: Stream-chat HUD slot (broadcast chat)

**Files:**
- Modify: `src/obs/hud.html` (slot markup + `#chat` CSS + a poll/render script block)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Consumes: the relay endpoint `GET /broadcast-chat/data` (returns `{"messages":[{"ts":…, "author":…, "text":…, "source":…}], "target":…}` or 404 when disabled — see `src/obs/intermission.html` for the exact field usage and render).
- Produces: a `#chat` box slot in `hud.html` that self-hides on 404/empty.

- [ ] **Step 1: Write the failing slot-list assertion**

In `tests/test_overlay.py::t_ob_extract_slots_from_real_hud`, add `"chat"` to the expected id list at the position you will place the markup. Run to see it fail.

Run: `python3 tests/test_overlay.py`
Expected: FAIL (missing `chat` slot).

- [ ] **Step 2: Add the `#chat` slot markup**

In `src/obs/hud.html`, next to the telemetry block (or the logo slot), add:

```html
  <div id="chat" class="el" data-edit="Stream chat" data-edit-kind="box" style="display:none">
    <div id="chat-log"></div>
  </div>
```

- [ ] **Step 3: Add the `#chat` default CSS**

In the `<style>` block (provisional box — left side, tuned later; the `--chat-*` vars mirror the intermission `--ichat-*` so a league can restyle):

```css
  #chat{left:24px;top:512px;width:360px;height:420px;flex-direction:column;align-items:stretch;
    overflow:hidden;border-radius:12px;background:rgba(12,16,22,.55);color:#eef2f6;
    font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;padding:10px 12px}
  #chat-log{overflow:hidden}
  #chat-log .msg{margin-top:6px;line-height:1.32;font-size:19px;overflow-wrap:anywhere}
  #chat-log .u{font-weight:700;color:#f0a868;margin-right:6px}
  #chat-log .ts{color:#9aa3ad;font-size:12px;margin-right:6px}
```

- [ ] **Step 4: Add the poll/render JS**

In `hud.html`'s script area, add a poller that mirrors `src/obs/intermission.html`'s broadcast-chat render (read that file for the exact fetch + `textContent` render). Self-gate: hide `#chat` on non-200/empty, show + render otherwise:

```javascript
  (function chatPoll(){
    const box = document.getElementById('chat'), log = document.getElementById('chat-log');
    async function tick(){
      try {
        const r = await fetch('/broadcast-chat/data', {cache:'no-store'});
        if (!r.ok) { box.style.display='none'; return; }
        const d = await r.json();
        const msgs = (d && d.messages) || [];
        if (!msgs.length) { box.style.display='none'; return; }
        box.style.display='';                       // .el default is flex
        log.textContent = '';
        for (const m of msgs.slice(-40)) {           // last 40, older clip out
          const row = document.createElement('div'); row.className='msg';
          const u = document.createElement('span'); u.className='u'; u.textContent=(m.author||'')+':';
          const t = document.createElement('span'); t.textContent=' '+(m.text||'');
          row.appendChild(u); row.appendChild(t); log.appendChild(row);
        }
        log.scrollTop = log.scrollHeight;
      } catch(e) { /* transient; keep polling */ }
    }
    tick(); setInterval(tick, 3000);
  })();
```

Render via `textContent` only (XSS-safe, matching the crew/broadcast chat convention). Confirm the field names against `intermission.html` (`author`/`text`/`ts`) and adjust if that file uses different keys — that file is the source of truth for the payload shape.

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_overlay.py && python3 tools/lint.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/obs/hud.html tests/test_overlay.py
git commit -m "feat(solo): stream-chat HUD slot rendering broadcast chat (epic #300)"
```

---

## Task 3: Tyres/Fuel capture — OBS source + device localization

**Files:**
- Modify: `src/setup-assets.py` (`DEVICE_SOURCES` ~line 122)
- Modify: `src/obs/GT_Racing_Solo_Commentary.json` (add the capture source + Program embed)
- Test: `tests/test_discord_audio.py`

**Interfaces:**
- Consumes: `localize_device_sources(collection, platform, env)` (rebuilds each `DEVICE_SOURCES` source's id/settings per-OS from `env[<entry.env>]`; video entries use `device_variant`, i.e. Windows `dshow_input`+`video_device_id`).
- Produces: the OBS source named `Solo Tyres/Fuel Capture` (a scene, embedded in `Program` with the baked crop) wrapping the leaf `Solo Tyres Capture Device` (`__RACECAST_TYRES_CAPTURE__`, `muted:true`); a new `RACECAST_TYRES_CAPTURE` device role.

- [ ] **Step 1: Write the failing localize test**

In `tests/test_discord_audio.py`, add:

```python
def t_localize_tyres_capture_windows():
    coll = {"sources": [
        {"name": "Solo Tyres Capture Device", "id": "av_capture_input",
         "settings": {"device": "__RACECAST_TYRES_CAPTURE__"}},
    ]}
    unset = sa.localize_device_sources(coll, "win32", {"RACECAST_TYRES_CAPTURE": "Elgato HD60 X:\\\\?\\usb#x"})
    src = coll["sources"][0]
    assert src["id"] == "dshow_input"
    assert src["settings"] == {"video_device_id": "Elgato HD60 X:\\\\?\\usb#x"}
    assert "Solo Tyres Capture Device" not in unset
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python3 tests/test_discord_audio.py`
Expected: FAIL (`Solo Tyres Capture Device` not in `DEVICE_SOURCES` → source left as-is / listed unset).

- [ ] **Step 3: Add the device role**

In `src/setup-assets.py`, extend `DEVICE_SOURCES`:

```python
DEVICE_SOURCES = (
    {"name": "Solo Capture Device", "env": "RACECAST_CAPTURE", "kind": "video"},
    {"name": "Solo Webcam Device",  "env": "RACECAST_WEBCAM",  "kind": "video"},
    {"name": "Commentary Mic Device", "env": "RACECAST_MIC",   "kind": "audio"},
    {"name": "Solo Tyres Capture Device", "env": "RACECAST_TYRES_CAPTURE", "kind": "video"},
)
```

- [ ] **Step 4: Run the localize test, verify it passes**

Run: `python3 tests/test_discord_audio.py`
Expected: PASS.

- [ ] **Step 5: Add the capture source to the Commentary collection JSON**

In `src/obs/GT_Racing_Solo_Commentary.json`, **mirror the existing `Solo Webcam` / `Solo Webcam Device` pair exactly** (find them: the `Solo Webcam` source with `id:"scene"` wrapping a `Solo Webcam Device` leaf `av_capture_input` with `device:"__RACECAST_WEBCAM__"`). Add two new sources:
  1. A scene `"Solo Tyres/Fuel Capture"` (copy the `Solo Webcam` scene, rename, its single item references `Solo Tyres Capture Device`).
  2. A leaf `"Solo Tyres Capture Device"` (copy `Solo Webcam Device`, rename, set `settings.device` = `"__RACECAST_TYRES_CAPTURE__"`, set `"muted": true`).

Register the new scene the same way `Solo Webcam` is registered (same `scene_order`/source-list treatment — match it verbatim).

Then in the `Program` scene's `settings.items`, add an embed of the new scene (copy the `Solo Webcam` Program item, rename `name` to `"Solo Tyres/Fuel Capture"`), and set on that item the baked crop + a provisional bottom-left transform:

```json
{ "name": "Solo Tyres/Fuel Capture",
  "pos": {"x": 7.0, "y": 926.0},
  "bounds": {"x": 245.0, "y": 84.0}, "bounds_type": 2, "bounds_alignment": 0,
  "crop_left": 258, "crop_top": 950, "crop_right": 1336, "crop_bottom": 18 }
```

(Keep every other field the `Solo Webcam` embed carries — `align`, `scale`, `visible`, ids, etc. — identical; only `name`/`pos`/`bounds`/`crop_*` differ.)

- [ ] **Step 6: Write a JSON structure guard test**

In `tests/test_discord_audio.py` add a test that loads the real commentary collection and asserts the structure (so a hand-edit typo is caught):

```python
def t_commentary_has_tyres_capture_structure():
    import json, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(os.path.join(root, "src/obs/GT_Racing_Solo_Commentary.json")))
    by_name = {s.get("name"): s for s in d["sources"]}
    assert by_name["Solo Tyres Capture Device"]["settings"]["device"] == "__RACECAST_TYRES_CAPTURE__"
    assert by_name["Solo Tyres Capture Device"].get("muted") is True
    prog = by_name["Program"]["settings"]["items"]
    tyres = [it for it in prog if it.get("name") == "Solo Tyres/Fuel Capture"]
    assert len(tyres) == 1
    it = tyres[0]
    assert (it["crop_left"], it["crop_top"], it["crop_right"], it["crop_bottom"]) == (258, 950, 1336, 18)
    assert it["bounds_type"] == 2
    # POV collection must NOT gain the tyres source (Commentary-only)
    pov = json.load(open(os.path.join(root, "src/obs/GT_Racing_Solo_POV.json")))
    assert "Solo Tyres Capture Device" not in {s.get("name") for s in pov["sources"]}
```

- [ ] **Step 7: Run tests + lint**

Run: `python3 tests/test_discord_audio.py && python3 tools/lint.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/setup-assets.py src/obs/GT_Racing_Solo_Commentary.json tests/test_discord_audio.py
git commit -m "feat(solo): commentary tyres/fuel second-capture source + device role (epic #300)"
```

---

## Task 4: Tyres/Fuel capture — builder box → OBS coupling

**Files:**
- Modify: `src/scripts/overlay_build.py` (`OVERLAY_SLOT_OBS_SOURCES` ~line 311)
- Modify: `src/obs/hud.html` (`#tyres-capture` slot + CSS)
- Test: `tests/test_overlay.py`, `tests/test_discord_audio.py`, `tests/test_racecast.py`

**Interfaces:**
- Consumes: `overlay_build.box_from_css(css, "tyres-capture")` → `#tyres-capture` box dict; `setup-assets.apply_box_transform(coll, source, overrides, scene=…)`; `racecast._sync_pov_transform` already loops `OVERLAY_SLOT_OBS_SOURCES`.
- Produces: the `tyres-capture` slot→OBS mapping (scene `Program`, source `Solo Tyres/Fuel Capture`, `export_scene: "Program"`); a `#tyres-capture` builder box slot.

- [ ] **Step 1: Write the failing map + parse tests**

In `tests/test_overlay.py`:

```python
def t_overlay_slot_obs_sources_has_tyres_capture():
    assert ob.OVERLAY_SLOT_OBS_SOURCES["tyres-capture"] == {
        "scene": "Program", "source": "Solo Tyres/Fuel Capture", "export_scene": "Program"}

def t_box_from_css_tyres_capture_slot():
    css = "#tyres-capture{left:7px;top:926px;width:245px;height:84px}"
    assert ob.box_from_css(css, "tyres-capture") == {"left":7,"top":926,"width":245,"height":84}
```

Also add `"tyres-capture"` to the expected list in `t_ob_extract_slots_from_real_hud`, and update `t_overlay_slot_obs_sources_constant` to include the new entry.

- [ ] **Step 2: Run, verify failure**

Run: `python3 tests/test_overlay.py`
Expected: FAIL (`KeyError`/assertion on the missing `tyres-capture` entry + slot).

- [ ] **Step 3: Add the map entry**

In `src/scripts/overlay_build.py`, `OVERLAY_SLOT_OBS_SOURCES`:

```python
OVERLAY_SLOT_OBS_SOURCES = {
    "pov":    {"scene": "Stint",   "source": "Feed POV"},
    "webcam": {"scene": "Program", "source": "Solo Webcam", "export_scene": "Program"},
    "tyres-capture": {"scene": "Program", "source": "Solo Tyres/Fuel Capture", "export_scene": "Program"},
}
```

- [ ] **Step 4: Add the `#tyres-capture` slot + CSS**

In `src/obs/hud.html` add an invisible positioning box (like `#pov` — the cropped capture shows from the OBS source beneath `HUD Overlay`):

```html
  <div id="tyres-capture" class="el" data-edit="Tyres/Fuel capture" data-edit-kind="box"></div>
```
```css
  #tyres-capture{left:7px;top:926px;width:245px;height:84px}
```

- [ ] **Step 5: Add the scene-scoped export + live-sync tests**

In `tests/test_discord_audio.py` (mirror the webcam scoped test) assert `apply_box_transform` with `scene="Program"` sets the `Solo Tyres/Fuel Capture` Program item and leaves a same-named decoy in another scene untouched.

In `tests/test_racecast.py::t_sync_pov_transform_calls_setter_with_merged_box`, extend the captured-calls assertion so `("Program","Solo Tyres/Fuel Capture")` is also targeted (its box comes from the `#tyres-capture` base rule in `hud.html`, no override) — `by_source` now has three entries.

- [ ] **Step 6: Run tests + lint**

Run: `python3 tests/test_overlay.py && python3 tests/test_discord_audio.py && python3 tests/test_racecast.py && python3 tools/lint.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/overlay_build.py src/obs/hud.html tests/test_overlay.py tests/test_discord_audio.py tests/test_racecast.py
git commit -m "feat(solo): tyres/fuel capture builder box drives OBS transform, Program-scoped (epic #300)"
```

---

## Task 5: Audio-monitoring config (via the generator, both solo collections)

**IMPORTANT — the solo OBS collections are GENERATED.** `tools/derive-solo-templates.py`
derives both `src/obs/GT_Racing_Solo_*.json` from `GT_Racing_Endurance.json`, and
`tests/test_solo_obs.py::t_committed_solo_json_matches_derive_output` asserts the committed
files equal a fresh `derive()`. So the monitoring config MUST be set inside `derive()` and
the files regenerated — a hand-edit to the JSON would fail the drift guard. (Task 3 already
routes the tyres source through `derive(with_tyres=True)`.)

**Files:**
- Modify: `tools/derive-solo-templates.py` (set monitoring/muted in `derive()`)
- Regenerate: `src/obs/GT_Racing_Solo_POV.json`, `src/obs/GT_Racing_Solo_Commentary.json`
  (via `python3 tools/derive-solo-templates.py`)
- Test: `tests/test_solo_audio.py` (new)

**Interfaces:**
- Consumes: `derive()`'s existing locals — `cap_src` (the `Solo Capture Device` leaf), and
  the endurance-copied sources in `col["sources"]` (`Discord Audio Capture`, `Intro Video`,
  `Outro Video`, `Intermission Music`).
- Produces: the monitoring config asserted by the new test + still equal to `derive()`.

- [ ] **Step 1: Write the failing monitoring test**

Create `tests/test_solo_audio.py`:

```python
#!/usr/bin/env python3
"""Solo collections' audio-monitoring config (game/Discord/media audible + streamed)."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLS = ("src/obs/GT_Racing_Solo_POV.json", "src/obs/GT_Racing_Solo_Commentary.json")
MON_AND_OUT = 2


def _by_name(path):
    d = json.load(open(os.path.join(ROOT, path)))
    return {s.get("name"): s for s in d["sources"]}


def t_game_and_discord_and_media_monitor_and_output():
    for path in COLLS:
        n = _by_name(path)
        cap = n["Solo Capture Device"]
        assert cap.get("muted") is False, path
        assert cap.get("monitoring_type") == MON_AND_OUT, path
        assert n["Discord Audio Capture"].get("monitoring_type") == MON_AND_OUT, path
        for media in ("Intro Video", "Outro Video", "Intermission Music"):
            assert n[media].get("monitoring_type") == MON_AND_OUT, (path, media)


def t_mic_unchanged_and_tyres_muted():
    for path in COLLS:
        n = _by_name(path)
        mic = n["Commentary Mic Device"]
        assert mic.get("monitoring_type") in (0, None), path      # no self-monitor
        assert mic.get("muted") is False, path                    # but output on
    tyres = _by_name("src/obs/GT_Racing_Solo_Commentary.json").get("Solo Tyres Capture Device")
    assert tyres is not None and tyres.get("muted") is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python3 tests/test_solo_audio.py`
Expected: FAIL (`Solo Capture Device` is `muted:true`, `monitoring_type:0`).

- [ ] **Step 3: Set the monitoring config in `derive()` + regenerate**

In `tools/derive-solo-templates.py`, inside `derive()`, apply the monitoring config before
`return col`. The `Solo Capture Device` leaf is the local `cap_src`; the others are
endurance-copied sources reachable via a name map over `col["sources"]`. Add:

```python
    # Audio: the game/race + Discord + media must be audible AND streamed (monitorAndOutput);
    # the game capture ships hot (unmuted) — commentator/driver hears the race in-headset and
    # it lands in the stream mix. The mic stays output-only (no self-monitor → no echo); the
    # webcam and the tyres second-capture stay muted (video-only). Both solo outputs get this.
    cap_src["muted"] = False
    cap_src["monitoring_type"] = 2
    _by_name(col["sources"])  # (re-map after all source mutations)
    for nm in ("Discord Audio Capture", "Intro Video", "Outro Video", "Intermission Music"):
        s = _by_name(col["sources"]).get(nm)
        if s is not None:
            s["monitoring_type"] = 2
```

(Place it after `col["sources"] = kept` so every source — including the endurance-copied
media/Discord — is present in `col["sources"]`. `cap_src` is the same object referenced in
`col["sources"]`, so mutating it in place is enough. Do NOT set monitoring on the mic or
webcam.) Then regenerate:

```bash
python3 tools/derive-solo-templates.py
```

- [ ] **Step 4: Run the test + the drift guard, verify they pass**

Run: `python3 tests/test_solo_audio.py && python3 tests/test_solo_obs.py`
Expected: `ALL PASS` for both (the drift guard confirms the committed JSONs still equal
`derive()` — proving the config came from the generator, not a hand-edit).

- [ ] **Step 5: Full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: `ALL TEST FILES PASS` / All checks passed.

- [ ] **Step 6: Commit**

```bash
git add tools/derive-solo-templates.py src/obs/GT_Racing_Solo_POV.json src/obs/GT_Racing_Solo_Commentary.json tests/test_solo_audio.py
git commit -m "fix(solo): game/Discord/media audio monitorAndOutput via the generator (epic #300)"
```

---

## Post-plan: visual dialog

After all five tasks land, the exact default boxes for `#league-logo`, `#chat`, and
`#tyres-capture` are tuned in a visual dialog with Jens — rendered over his real
commentary streams, iterated to approval (the same process used for the POV/telemetry
layout), then baked into the `hud.html` defaults / per-league overlay CSS and
visually re-verified. Also confirm the tyres crop region against a fresh commentary
capture. The Control Center overlay-builder wiki screenshot is refreshed if that view's
slot set changed (CLAUDE.md rule).

## Self-Review notes

- **Spec coverage:** logo (T1), tyres capture source+device (T3) + box→OBS (T4), chat (T2),
  audio monitoring (T5), device/identifier validation (done in the spec, no code task).
  All spec sections have a task.
- **Endurance byte-identical:** logo `onerror`-hides, chat 404-gates, tyres map entry is a
  no-op where the source is absent; audio edits touch solo collections only. Covered.
- **No SAMPLE for the three box slots** (corrects the spec's earlier note) — box slots are
  not covered by `t_ob_sample_covers_every_text_slot`.
- **Slot id consistency:** `tyres-capture` used identically in the map, CSS, element, and
  `box_from_css` calls.
