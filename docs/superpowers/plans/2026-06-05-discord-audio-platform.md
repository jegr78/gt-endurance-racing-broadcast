# Platform-dependent Discord Audio Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `iro setup` produces the platform-correct Discord audio capture source (macOS/Windows/Linux), and `tokenize-obs.py` folds any platform variant back to the canonical committed form.

**Architecture:** Approach B from the spec (`docs/superpowers/specs/2026-06-05-discord-audio-platform-design.md`): one logical source in git (the macOS `sck_audio_capture` form, uuid `0085d4f3-bf43-4aef-9fe4-28cfd3270c7d`); `src/setup-assets.py` swaps `id`/`versioned_id`/`settings` in place at localize time (platform known there); `tools/tokenize-obs.py` normalizes the reverse direction. Scene items untouched.

**Tech Stack:** Python stdlib only, repo test convention (runnable `tests/test_*.py`, no pytest).

---

### Task 1: Pure transform helpers + tests

**Files:**
- Modify: `src/setup-assets.py` (after `graphics_dir()`, before `load_dotenv`)
- Modify: `tools/tokenize-obs.py` (constants near `TIMER_RE`, function before `main`)
- Create: `tests/test_discord_audio.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discord_audio.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the platform-dependent Discord audio source transforms.
Run: python3 tests/test_discord_audio.py"""
import copy, importlib.util, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sa = _load("setup_assets", "src", "setup-assets.py")
tk = _load("tokenize_obs", "tools", "tokenize-obs.py")

CANONICAL_SETTINGS = {"type": 1, "application": "com.hnc.Discord"}


def coll(src_id="sck_audio_capture", settings=None):
    return {"sources": [
        {"name": "Discord Audio Capture", "uuid": sa.DISCORD_AUDIO_UUID,
         "id": src_id, "versioned_id": src_id,
         "settings": dict(CANONICAL_SETTINGS if settings is None else settings)},
        {"name": "Feed A", "uuid": "feed-a", "id": "ffmpeg_source",
         "settings": {"input": "http://127.0.0.1:53001"}},
    ]}


def t_variant_per_platform():
    assert sa.discord_variant("darwin")[0] == "sck_audio_capture"
    assert sa.discord_variant("win32")[0] == "wasapi_process_output_capture"
    assert sa.discord_variant("linux")[0] == "pipewire_audio_application_capture"
    assert sa.discord_variant("sunos5") is None


def t_localize_windows_swaps_id_and_settings():
    c = coll()
    assert sa.localize_discord_audio(c, "win32") == "wasapi_process_output_capture"
    s = c["sources"][0]
    assert s["id"] == s["versioned_id"] == "wasapi_process_output_capture"
    assert s["settings"] == {"window": "Discord:Chrome_WidgetWin_1:Discord.exe",
                             "priority": 2}   # 2 = WINDOW_PRIORITY_EXE
    assert c["sources"][1]["settings"]["input"] == "http://127.0.0.1:53001"


def t_localize_linux_uses_pipewire_plugin():
    c = coll()
    assert sa.localize_discord_audio(c, "linux") == "pipewire_audio_application_capture"
    # "MatchPriorty" (sic) is the plugin's actual settings key; 0 = binary name.
    assert c["sources"][0]["settings"] == {"TargetName": "Discord", "MatchPriorty": 0}


def t_localize_idempotent_and_darwin_noop():
    c = coll()
    sa.localize_discord_audio(c, "win32")
    once = copy.deepcopy(c)
    sa.localize_discord_audio(c, "win32")
    assert c == once
    d = coll()
    sa.localize_discord_audio(d, "darwin")
    assert d["sources"][0]["id"] == "sck_audio_capture"
    assert d["sources"][0]["settings"] == CANONICAL_SETTINGS


def t_localize_missing_source_or_unknown_platform():
    c = {"sources": [{"name": "x", "uuid": "other", "id": "scene", "settings": {}}]}
    before = copy.deepcopy(c)
    assert sa.localize_discord_audio(c, "win32") is None
    assert c == before
    d = coll()
    before = copy.deepcopy(d)
    assert sa.localize_discord_audio(d, "sunos5") is None
    assert d == before


def t_tokenize_folds_any_variant_back():
    c = coll()
    sa.localize_discord_audio(c, "win32")
    assert tk.canonicalize_discord_audio(c) is True
    s = c["sources"][0]
    assert s["id"] == s["versioned_id"] == "sck_audio_capture"
    assert s["settings"] == CANONICAL_SETTINGS
    assert tk.canonicalize_discord_audio(c) is False   # canonical input: no-op


def t_committed_template_carries_the_source():
    # Guards against the uuid drifting when scenes are re-exported.
    path = os.path.join(ROOT, "src", "obs", "IRO_Endurance.json")
    d = json.load(open(path, encoding="utf-8"))
    hits = [s for s in d.get("sources", []) if s.get("uuid") == sa.DISCORD_AUDIO_UUID]
    assert len(hits) == 1 and hits[0]["id"] == "sck_audio_capture"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_discord_audio.py`
Expected: FAIL with `AttributeError: module 'setup_assets' has no attribute 'DISCORD_AUDIO_UUID'` (after the module loads fine).

- [ ] **Step 3: Implement the setup-assets side**

In `src/setup-assets.py`, after `graphics_dir()`:

```python
# ---- Discord interview audio: one logical source, per-platform realization.
# The committed collection carries the macOS form (a real Mac export). At
# localize time the platform is known, so the source is swapped in place;
# tools/tokenize-obs.py folds any variant back (keep the two ends in sync).
# Windows "priority" 2 = WINDOW_PRIORITY_EXE (obs window-helpers.h) — match
# any Discord.exe window, never the volatile channel-name window title.
# Linux needs the obs-pipewire-audio-capture plugin (untested, see docs);
# "MatchPriorty" (sic) is the plugin's actual settings key, 0 = binary name.
DISCORD_AUDIO_UUID = "0085d4f3-bf43-4aef-9fe4-28cfd3270c7d"
DISCORD_AUDIO_VARIANTS = {
    "darwin": ("sck_audio_capture",
               {"type": 1, "application": "com.hnc.Discord"}),
    "win": ("wasapi_process_output_capture",
            {"window": "Discord:Chrome_WidgetWin_1:Discord.exe", "priority": 2}),
    "linux": ("pipewire_audio_application_capture",
              {"TargetName": "Discord", "MatchPriorty": 0}),
}


def discord_variant(platform):
    """(source id, settings) for this platform, or None when unknown."""
    if platform.startswith("win"):
        return DISCORD_AUDIO_VARIANTS["win"]
    if platform == "darwin":
        return DISCORD_AUDIO_VARIANTS["darwin"]
    if platform.startswith("linux"):
        return DISCORD_AUDIO_VARIANTS["linux"]
    return None


def localize_discord_audio(collection, platform):
    """Swap the Discord audio source to this platform's variant, in place.
    Returns the new source id, or None (source absent / unknown platform —
    never fails, same contract as the missing-graphics warnings)."""
    variant = discord_variant(platform)
    if variant is None:
        return None
    src_id, settings = variant
    for s in collection.get("sources", []):
        if s.get("uuid") == DISCORD_AUDIO_UUID:
            s["id"] = src_id
            s["versioned_id"] = src_id
            s["settings"] = dict(settings)
            return src_id
    return None
```

- [ ] **Step 4: Implement the tokenize side**

In `tools/tokenize-obs.py`, after `TIMER_RE`:

```python
# Discord audio source: fold any platform variant (created by setup-assets'
# localize_discord_audio — keep the two ends in sync) back to the committed
# macOS form, so round-trips from Mac and Windows yield the same template.
DISCORD_AUDIO_UUID = "0085d4f3-bf43-4aef-9fe4-28cfd3270c7d"
DISCORD_AUDIO_CANONICAL = ("sck_audio_capture",
                           {"type": 1, "application": "com.hnc.Discord"})


def canonicalize_discord_audio(d):
    """True iff a non-canonical Discord audio source was rewritten."""
    src_id, settings = DISCORD_AUDIO_CANONICAL
    for s in d.get("sources", []):
        if s.get("uuid") == DISCORD_AUDIO_UUID and s.get("id") != src_id:
            s["id"] = src_id
            s["versioned_id"] = src_id
            s["settings"] = dict(settings)
            return True
    return False
```

- [ ] **Step 5: Run the tests**

Run: `python tests/test_discord_audio.py`
Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add src/setup-assets.py tools/tokenize-obs.py tests/test_discord_audio.py
git commit -m "feat(obs): platform-dependent Discord audio source transforms"
```

### Task 2: Wire into main() of both scripts

**Files:**
- Modify: `src/setup-assets.py` (in `main()`, after `localized = replace_tokens(...)`)
- Modify: `tools/tokenize-obs.py` (in `main()`, after the `tokenize_sheets` call)

- [ ] **Step 1: setup-assets main() calls the localize step**

In `src/setup-assets.py` `main()`, directly after
`localized = replace_tokens(collection, mapping)`:

```python
    swapped = localize_discord_audio(localized, sys.platform)
```

And in the summary prints (after the GRAPHICS_TOKEN print block):

```python
    if swapped:
        print(f"  Discord audio source: {swapped}")
    elif discord_variant(sys.platform) is None:
        print(f"  NOTE: no Discord audio variant for {sys.platform} — macOS form kept.")
    else:
        print("  WARNING: Discord audio source not found in the collection.")
```

- [ ] **Step 2: tokenize-obs main() folds back**

In `tools/tokenize-obs.py` `main()`, after `d = tokenize_sheets(d, sheet_count)`:

```python
    if canonicalize_discord_audio(d):
        print("Discord audio source folded back to the canonical macOS form.")
```

- [ ] **Step 3: End-to-end check on this repo**

Run: `python src/iro.py setup --out runtime/discord-check.json --sheet-id smoke --timer-url https://example.com/t`
Expected (on Windows): output contains `Discord audio source: wasapi_process_output_capture`; then
`python -c "import json; d=json.load(open('runtime/discord-check.json', encoding='utf-8')); s=[x for x in d['sources'] if x.get('uuid')=='0085d4f3-bf43-4aef-9fe4-28cfd3270c7d'][0]; print(s['id'], s['settings'])"`
prints the Windows id + `{'window': 'Discord:Chrome_WidgetWin_1:Discord.exe', 'priority': 2}`.

Round-trip: `python tools/tokenize-obs.py runtime/discord-check.json runtime/discord-roundtrip.json`
Expected: prints the folded-back line; the uuid's source in `runtime/discord-roundtrip.json` is `sck_audio_capture` again.
Cleanup: delete both runtime check files.

- [ ] **Step 4: Full suite + package build**

Run: `python tools/run-tests.py` → `ALL TEST FILES PASS`
Run: `python tools/build.py` → all `[OK]` verify lines.

- [ ] **Step 5: Commit**

```bash
git add src/setup-assets.py tools/tokenize-obs.py
git commit -m "feat(obs): iro setup localizes the Discord audio source per platform"
```

### Task 3: Docs

**Files:**
- Modify: `src/docs/README_SETUP.md` (section "3c. Discord audio")
- Modify: `src/docs/wiki/OBS-Setup.md` (Discord audio note)
- Modify: `src/docs/wiki/If-something-goes-wrong.md` (Discord audio row)

- [ ] **Step 1: Update the three Discord-audio passages**

Message in all three (adapted to surrounding style): the collection ships ONE
Discord audio source and `iro setup` realizes it for the importing OS — macOS
*App Audio Capture* (ScreenCaptureKit), Windows *Application Audio Capture*
(matches any `Discord.exe` window, channel titles don't matter), Linux the
PipeWire app-audio-capture **plugin** (install separately:
https://obsproject.com/forum/resources/pipewire-audio-capture.1458/ — untested).
Re-run `iro setup` + re-import after switching machines/OS.

- [ ] **Step 2: Build + commit + publish wiki**

Run: `python tools/build.py` → verify `[OK]`s.

```bash
git add src/docs/README_SETUP.md src/docs/wiki/OBS-Setup.md src/docs/wiki/If-something-goes-wrong.md
git commit -m "docs(obs): Discord audio source is localized per platform by iro setup"
python tools/sync-wiki.py
```

### Task 4: Refresh the producer deployment

- [ ] **Step 1: Rebuild the binary and copy to the deploy folder**

Run: `python tools/build-binary.py` → `Smoke test OK`.
Copy `dist/bin/iro.exe` to `C:\Users\User\Documents\IRO\iro.exe`.

- [ ] **Step 2: Tell the operator the final manual step**

`.\iro.exe setup --out runtime/IRO_Endurance.import.json` + re-import in OBS
(collections are localized at import time; the running OBS needs the fresh
import to pick up the Windows Discord source).
