# M3c — OBS Scene-Collection Tie-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active profile name its own OBS scene collection so multiple leagues coexist on one machine, each with its own imported collection — instead of the single hardcoded `EXPECTED_SCENE_COLLECTION`.

**Architecture:** A new optional `OBS_COLLECTION` field in `profile.env` flows into `config.ResolvedConfig.obs_collection` (fallback = the profile display `NAME`). The CLI resolves the active value and threads it into the existing best-effort `obs_ws` check/switch (the module constant stays the default for callers without a profile). `setup-assets.py` writes the resolved name into the localized import JSON's top-level `name`, so the imported collection actually carries the per-profile identity; the maintainer fold-back tool (`tokenize-obs.py`) normalizes the name back to the canonical constant so a league name never leaks into the shared source.

**Tech Stack:** Pure Python 3.11+ stdlib. Tests are runnable scripts with `t_`-prefixed functions, bare `assert`, `importlib` module loading, `if __name__=="__main__"` runner. No third-party deps.

**Design decisions (locked with Jens 2026-06-11):**
- Full tie-in now: `setup-assets.py` injects the collection name into the import JSON.
- Fallback when `OBS_COLLECTION` is unset: the profile display `NAME` (not the constant).
- Default behavior unchanged when nobody sets `OBS_COLLECTION` *and* `NAME` already equals the current collection name — additive, no migration for the existing single setup beyond what the operator already controls via `NAME`.

**Non-breaking contract:** `obs_ws.EXPECTED_SCENE_COLLECTION` stays as the parameter default for every `obs_ws` entry point, so a direct `obs_ws` caller (or a test) with no profile behaves exactly as today. `config.py` gains NO `obs_ws` import (layering preserved); the OBS-constant fallback lives only in the CLI helper.

---

### Task 1: `config.ResolvedConfig.obs_collection`

**Files:**
- Modify: `src/scripts/config.py` (dataclass `ResolvedConfig` ~146-156; `resolve_config` return ~185-195)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (after `t_resolve_config_name_defaults_to_profile_when_unset`, ~line 179):

```python
def t_resolve_config_obs_collection_from_field():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro",
                   "NAME=IRO Endurance\nSHEET_ID=abc\nOBS_COLLECTION=IRO Broadcast\n")
        cfg = m.resolve_config(root, environ={})
        assert cfg.obs_collection == "IRO Broadcast"


def t_resolve_config_obs_collection_falls_back_to_name():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "erf", "NAME=ERF Endurance\nSHEET_ID=abc\n")
        cfg = m.resolve_config(root, environ={})
        assert cfg.obs_collection == "ERF Endurance"


def t_resolve_config_obs_collection_falls_back_to_profile_dir_when_no_name():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "erf", "SHEET_ID=abc\n")   # no NAME, no OBS_COLLECTION
        cfg = m.resolve_config(root, environ={})
        assert cfg.obs_collection == "erf"           # == cfg.name fallback
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_config.py`
Expected: FAIL — `AttributeError: 'ResolvedConfig' object has no attribute 'obs_collection'`.

- [ ] **Step 3: Add the field and resolve it**

In `src/scripts/config.py`, add the field to the dataclass after `outro_url` (~line 152):

```python
    intro_url: str = ""
    outro_url: str = ""
    obs_collection: str = ""     # OBS scene-collection name; falls back to NAME
    logo_path: str = ""          # absolute path, or "" if unset/missing
```

In `resolve_config`, hoist the resolved name into a local and reuse it for the fallback. Replace the return block (~185-195) so the `name=` line uses the local and a new `obs_collection=` line is added:

```python
    resolved_name = prof.get("NAME", name)
    return ResolvedConfig(
        profile=name,
        name=resolved_name,
        sheet_id=prof.get("SHEET_ID", ""),
        sheet_push_url=prof.get("SHEET_PUSH_URL", ""),
        intro_url=prof.get("INTRO_URL", ""),
        outro_url=prof.get("OUTRO_URL", ""),
        obs_collection=prof.get("OBS_COLLECTION") or resolved_name,
        logo_path=logo_path,
        profile_dir=pdir,
        runtime_dir=profile_runtime_dir(root, name),
        machine_env=machine,
```

(Keep every other existing keyword argument and the closing `)` exactly as they were.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_config.py`
Expected: `ALL PASS` (the three new tests plus the existing suite — `t_resolve_config_end_to_end_single_profile` etc. still green).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): add obs_collection to ResolvedConfig (falls back to NAME)"
```

---

### Task 2: Document `OBS_COLLECTION` in the example profile

**Files:**
- Modify: `profiles/example/profile.env`

- [ ] **Step 1: Add the documented optional field**

Append to `profiles/example/profile.env` (after the `LOGO=` block, keep the existing English-only, comment-then-key style):

```
# OPTIONAL: the OBS scene-collection name this league uses. Lets several leagues
# keep separate collections in OBS on one machine (switch with
# `racecast obs collection set`). `racecast setup` writes this name into the
# import JSON. Blank = use the display NAME above.
OBS_COLLECTION=
```

- [ ] **Step 2: Verify the template still parses**

Run: `python3 -c "import sys; sys.path.insert(0,'src/scripts'); import config; print(config.parse_env_text(open('profiles/example/profile.env').read()).get('OBS_COLLECTION'))"`
Expected: prints an empty line (key present, value empty) — no traceback.

- [ ] **Step 3: Commit**

```bash
git add profiles/example/profile.env
git commit -m "docs(profile): document optional OBS_COLLECTION in the example profile"
```

---

### Task 3: `obs_ws.get_scene_collection` takes an `expected` argument

**Files:**
- Modify: `src/scripts/obs_ws.py` (`get_scene_collection` ~471-487)
- Test: `tests/test_obsws.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_obsws.py` (after `t_get_scene_collection_reads_current_and_list`, ~line 471):

```python
def t_get_scene_collection_honors_custom_expected():
    state = {"released": [], "current_collection": "ERF Endurance",
             "collections": ["ERF Endurance", "IRO Endurance"]}
    port, srv = _start_fake_obs(state)
    status, note = m.get_scene_collection(port=port, password="supersecret",
                                          timeout=5, expected="ERF Endurance")
    assert note == "", note
    assert status["expected"] == "ERF Endurance"
    assert status["match"] is True          # would be False against the default
    srv.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `TypeError: get_scene_collection() got an unexpected keyword argument 'expected'`.

- [ ] **Step 3: Thread `expected` through**

In `src/scripts/obs_ws.py`, change the signature and the `scene_collection_status` call (~471-482):

```python
def get_scene_collection(host="127.0.0.1", port=None, password=None, timeout=2.0,
                         expected=EXPECTED_SCENE_COLLECTION):
    """Ask OBS which scene collection is active and classify it against
    `expected` (default EXPECTED_SCENE_COLLECTION). Returns (status_dict, note);
    (None, reason) on any failure — OBS closed, wrong password, protocol surprise
    — NEVER an exception (same best-effort contract as release_feed_inputs/
    refresh_browser_inputs)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        resp = session.request("GetSceneCollectionList", {})
        status = scene_collection_status(resp.get("currentSceneCollectionName"),
                                         resp.get("sceneCollections", []),
                                         expected=expected)
        return status, ""
```

(Leave the `except`/`finally` tail untouched.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS` (new test plus the existing scene-collection tests, which omit `expected` and still classify against `IRO Endurance`).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): get_scene_collection accepts an expected-collection arg"
```

---

### Task 4: Wire the active collection name through the CLI

**Files:**
- Modify: `src/iro.py` — add `_active_obs_collection()`; extend `_profile_env_vars` (~172-180); pass the name in `obs_collection_cmd` (~815-842), `_check_scene_collection` (~1358-1360), `_event_sections` (~1216-1220), `obs_collection_data` (~1687-1701)
- Test: `tests/test_iro.py`

**Context:** `_profile_env_vars(rc)` returns the league values the CLI pushes into the child env (`RACECAST_SHEET_ID` etc.); `setup-assets.py` (Task 5) will read `RACECAST_OBS_COLLECTION` from there. `_active_sheet_id` (~2092) is the existing tolerant `resolve_config` wrapper to mirror. The `obs_collection_data` test seam (`tests/test_ui_ops.py:748`) passes a zero-arg `get` — keep that contract by binding `expected` inside the default branch only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_iro.py` near the other `_profile_env_vars` test (`t_profile_env_vars_filters_empty`, ~630):

```python
def t_profile_env_vars_includes_obs_collection():
    rc = m.pcfg.ResolvedConfig(profile="iro", name="IRO Endurance", sheet_id="abc",
                               obs_collection="IRO Broadcast")
    out = m._profile_env_vars(rc)
    assert out["RACECAST_OBS_COLLECTION"] == "IRO Broadcast"


def t_active_obs_collection_falls_back_to_constant_without_profile(monkeypatch=None):
    # No active profile resolvable -> the obs_ws default constant.
    import obs_ws
    saved = dict(os.environ)
    try:
        os.environ.pop("RACECAST_PROFILE", None)
        # Point the resolver at an empty temp root so no profile resolves.
        with tempfile.TemporaryDirectory() as td:
            orig = m._env_base
            m._env_base = lambda *a, **k: td
            try:
                assert m._active_obs_collection() == obs_ws.EXPECTED_SCENE_COLLECTION
            finally:
                m._env_base = orig
    finally:
        os.environ.clear(); os.environ.update(saved)
```

Add `import os, tempfile` at the top of `tests/test_iro.py` if not already present (check the existing imports first; most `test_iro.py` helpers already import `os`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `KeyError: 'RACECAST_OBS_COLLECTION'` and `AttributeError: module 'iro' has no attribute '_active_obs_collection'`.

- [ ] **Step 3: Add the env var to `_profile_env_vars`**

In `src/iro.py`, extend the `pairs` tuple (~176-179):

```python
    pairs = (("RACECAST_SHEET_ID", rc.sheet_id),
             ("RACECAST_SHEET_PUSH_URL", rc.sheet_push_url),
             ("RACECAST_INTRO_URL", rc.intro_url),
             ("RACECAST_OUTRO_URL", rc.outro_url),
             ("RACECAST_OBS_COLLECTION", rc.obs_collection))
```

- [ ] **Step 4: Add the tolerant resolver helper**

In `src/iro.py`, add next to `_active_sheet_id` (~2092). It must import `obs_ws` lazily for the fallback constant (same pattern the other obs call sites use):

```python
def _active_obs_collection():
    """The active profile's OBS scene-collection name, or the obs_ws default
    constant when no profile resolves. Tolerant: any resolution failure -> the
    constant, so the check/switch still work on a profile-less machine."""
    import obs_ws
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    active = _active_profile_name()
    if active:
        try:
            return pcfg.resolve_config(root, override=active,
                                       runtime_root=_runtime_base_dir()).obs_collection
        except pcfg.ProfileError:
            pass
    return obs_ws.EXPECTED_SCENE_COLLECTION
```

- [ ] **Step 5: Pass the name into the four call sites**

`obs_collection_cmd` (~820-825) — resolve once, pass to both get and set:

```python
    import obs_ws
    expected = _active_obs_collection()
    if rest[:1] == ["set"] and len(rest) == 1:
        ok, note = obs_ws.set_scene_collection(name=expected)
        if not ok:
            sys.exit(f"obs: scene collection switch failed — {note}")
        print(f"obs: {note or 'scene collection switched to ' + expected}.")
        return
    if rest:
        sys.exit("usage: iro obs collection [set]")
    status, note = obs_ws.get_scene_collection(expected=expected)
```

(The branch bodies below — `match`/`expected_present`/`renamed_variant` — already read `status['expected']`, so they need no change.)

`_check_scene_collection` (~1358-1360):

```python
    try:
        import obs_ws
        status, note = obs_ws.get_scene_collection(expected=_active_obs_collection())
```

`_event_sections` (~1216-1220):

```python
    if obs_running:
        try:
            import obs_ws
            status, note = obs_ws.get_scene_collection(expected=_active_obs_collection())
            apps.append(ev.classify_scene_collection(status, note))
```

`obs_collection_data` (~1692-1697) — bind `expected` inside the default branch so the injected zero-arg test seam keeps working:

```python
    if get is None:
        try:
            import obs_ws
            expected = _active_obs_collection()
            def get():
                return obs_ws.get_scene_collection(expected=expected)
        except Exception as exc:                     # noqa: BLE001 — best effort
            return {"ok": False, "note": str(exc)}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_iro.py && python3 tests/test_ui_ops.py && python3 tests/test_ui_server.py`
Expected: `ALL PASS` for each (the existing `obs_collection_data` seam tests still pass because injected `get` stays zero-arg).

- [ ] **Step 7: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): thread the active profile's OBS collection into the check/switch"
```

---

### Task 5: `setup-assets.py` writes the collection name into the import JSON

**Files:**
- Modify: `src/setup-assets.py` (add pure helper near the other transforms ~63; new `--collection` arg + wiring in `main` ~124-208)
- Test: `tests/test_discord_audio.py` (already loads `setup-assets.py` as `sa`)

**Context:** `main()` already resolves `--sheet-id` from `os.environ.get("RACECAST_SHEET_ID")` (injected by the CLI). `--collection` mirrors that with `RACECAST_OBS_COLLECTION` (Task 4). The helper is pure so it is unit-testable without running `argparse`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discord_audio.py` (after the existing setup-assets tests):

```python
def t_apply_collection_name_sets_top_level_name():
    c = {"name": "IRO Endurance", "sources": []}
    out = sa.apply_collection_name(c, "ERF Endurance")
    assert out["name"] == "ERF Endurance"


def t_apply_collection_name_noop_on_blank():
    c = {"name": "IRO Endurance", "sources": []}
    out = sa.apply_collection_name(c, "")
    assert out["name"] == "IRO Endurance"
    out2 = sa.apply_collection_name(c, None)
    assert out2["name"] == "IRO Endurance"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_discord_audio.py`
Expected: FAIL — `AttributeError: module 'setup_assets' has no attribute 'apply_collection_name'`.

- [ ] **Step 3: Add the pure helper**

In `src/setup-assets.py`, add near `localize_discord_audio` (~63):

```python
def apply_collection_name(collection, name):
    """Set the OBS collection's top-level display name to `name` (the active
    profile's OBS_COLLECTION). Blank/None -> leave the template name untouched.
    Mutates and returns `collection` (consistent with the other transforms)."""
    if name:
        collection["name"] = name
    return collection
```

- [ ] **Step 4: Run the helper test to verify it passes**

Run: `python3 tests/test_discord_audio.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Wire it into `main`**

In `src/setup-assets.py main()`, add the argument after `--sheet-id` (~139):

```python
    ap.add_argument("--collection", default=os.environ.get("RACECAST_OBS_COLLECTION"),
                    help="OBS scene-collection display name written into the import "
                         "JSON. Default: env RACECAST_OBS_COLLECTION (active profile).")
```

Apply it after `localize_discord_audio`, before the file is written (~188):

```python
    swapped = localize_discord_audio(localized, sys.platform)
    apply_collection_name(swapped, a.collection)
```

Add a confirmation line in the output block (after the `Graphics dir` print, ~200):

```python
    if a.collection:
        print(f"  OBS collection name: {a.collection}")
```

- [ ] **Step 6: Run the full suite to verify nothing regressed**

Run: `python3 tests/test_discord_audio.py`
Expected: `ALL PASS`.

- [ ] **Step 7: Commit**

```bash
git add src/setup-assets.py tests/test_discord_audio.py
git commit -m "feat(setup): write the active profile's OBS collection name into the import"
```

---

### Task 6: `tokenize-obs.py` normalizes the collection name on fold-back

**Files:**
- Modify: `tools/tokenize-obs.py` (add pure helper ~37; call it in `main` before `json.dump` ~77-79)
- Test: `tests/test_discord_audio.py` (already loads `tokenize-obs.py` as `tk`)

**Context:** `tokenize-obs.py` folds a maintainer's OBS export back into the shared `src/obs/IRO_Endurance.json`. After Task 5, an export can carry a per-league name (e.g. "ERF Endurance"). Normalizing it back to the canonical constant keeps a league identity out of the committed source. The constant must match `obs_ws.EXPECTED_SCENE_COLLECTION` / the source JSON `name` ("IRO Endurance") today; M5 renames all three together.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discord_audio.py`:

```python
def t_canonicalize_name_resets_to_constant():
    d = {"name": "ERF Endurance", "sources": []}
    out = tk.canonicalize_name(d)
    assert out["name"] == tk.CANONICAL_COLLECTION_NAME
    assert tk.CANONICAL_COLLECTION_NAME == "IRO Endurance"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_discord_audio.py`
Expected: FAIL — `AttributeError: module 'tokenize_obs' has no attribute 'canonicalize_name'`.

- [ ] **Step 3: Add the constant and helper**

In `tools/tokenize-obs.py`, add near the top-level transforms (~37, by `base`/`canonicalize_discord_audio`):

```python
# The canonical scene-collection name in the committed source. Mirrors
# obs_ws.EXPECTED_SCENE_COLLECTION and src/obs/IRO_Endurance.json's "name";
# M5 renames all three together. Folding an export back resets the name so a
# per-league name (written by setup-assets) never lands in git.
CANONICAL_COLLECTION_NAME = "IRO Endurance"


def canonicalize_name(d):
    """Reset the collection's display name to the canonical source name."""
    d["name"] = CANONICAL_COLLECTION_NAME
    return d
```

- [ ] **Step 4: Call it in `main` before writing**

In `tools/tokenize-obs.py main()`, just before the `json.dump` (~77-79), apply it to the tokenized object (the variable written out is `d`):

```python
    canonicalize_name(d)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
```

(If the in-scope variable at that point is not named `d`, apply `canonicalize_name(<that var>)` to whatever object is passed to `json.dump`.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_discord_audio.py`
Expected: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add tools/tokenize-obs.py tests/test_discord_audio.py
git commit -m "fix(tools): tokenize-obs resets the collection name to the canonical source name"
```

---

### Task 7: Full-suite + lint + build gate

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS`.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: clean (no findings). If E731 (lambda assignment) or F-class issues appear in `obs_collection_data`, the nested `def get()` form from Task 4 Step 5 avoids them — confirm that form was used.

- [ ] **Step 3: Build verify**

Run: `python3 tools/build.py`
Expected: verify step passes (tokenization OK, blanked Companion password, no secrets, preflight present, no shell scripts). Graphics "missing file" warnings are expected and not failures.

- [ ] **Step 4: Sanity-check the end-to-end name flow (manual, no OBS needed)**

Run:
```bash
python3 -c "
import os, sys; sys.path.insert(0,'src/scripts')
os.environ['RACECAST_OBS_COLLECTION']='ERF Endurance'
os.environ['RACECAST_SHEET_ID']='dummy'
import subprocess, tempfile, json
out=tempfile.mktemp(suffix='.json')
subprocess.run([sys.executable,'src/setup-assets.py','--out',out], check=True)
print('name =', json.load(open(out))['name'])
"
```
Expected: prints `name = ERF Endurance` (proves `RACECAST_OBS_COLLECTION` reaches the import JSON). The run also prints the usual localization lines/warnings.

- [ ] **Step 5: Commit any incidental fixes from the gate**

```bash
git add -A
git commit -m "test(m3c): full-suite/lint/build gate green"   # only if the gate required a fix
```

---

## Self-Review

**Spec coverage** (against memory note + the two locked decisions):
- "Active profile names its own OBS collection via a new `profile.env` field (`OBS_COLLECTION`)" → Task 1 + Task 2.
- "Plumb through `obs_ws` `EXPECTED_SCENE_COLLECTION` default + `get/set_scene_collection`" → Task 3 (`get` gains `expected`; `set` already had `name`); the constant stays the default.
- "`iro obs collection` + event start/status checks + `config.ResolvedConfig`" → Task 1 (config) + Task 4 (CLI command, `_check_scene_collection`, `_event_sections`, Control Center `obs_collection_data`).
- "Full tie-in: setup-assets injects the name" → Task 5; fold-back safety → Task 6.

**Placeholder scan:** No TBD/TODO; every code step shows the exact code. The only hedge is Task 6 Step 4's "if the variable isn't named `d`" — `tokenize-obs.py main` writes `json.dump(d, ...)` per the grep, so `d` is correct; the note is a safety net, not a placeholder.

**Type/name consistency:** `obs_collection` (field), `_active_obs_collection()` (helper), `RACECAST_OBS_COLLECTION` (env var), `OBS_COLLECTION` (profile.env key), `apply_collection_name` / `canonicalize_name` / `CANONICAL_COLLECTION_NAME` — used identically across tasks. `get_scene_collection(..., expected=...)` and `set_scene_collection(name=...)` match the call sites in Task 4. `_profile_env_vars` already filters empty values, and `obs_collection` is always non-empty (falls back to `name`), so it is always injected — intended.

**Layering:** `config.py` gains no `obs_ws` import; the constant fallback lives only in `iro._active_obs_collection`. The relay (`iro-feeds.py`) is untouched (it never reads the collection name). Maintainer tool change (Task 6) ships to no one.
