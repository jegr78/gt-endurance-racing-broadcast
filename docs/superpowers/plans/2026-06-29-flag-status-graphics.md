# Flag Status Graphics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add league-maintainable flag overlay graphics (Green/Yellow/Red/Safety Car/VSC) as a separate, exactly-one-active OBS control parallel to the existing flag-text chip, toggled from the Director Panel + Companion (and over Funnel), with a transparent-placeholder fallback for unmaintained assets.

**Architecture:** A new pure module `src/scripts/flag_graphic.py` holds the value→source mapping, the mutual-exclusion intent builder, and a small persisted `FlagGraphicStore` (injectable `apply_fn`, mirrors `EventTitleStore`). The relay imports it (like `cue_admin`), constructs the store with `obs_ws.set_scene_item_enabled` as the apply function, re-asserts the saved flag at startup, and serves three GET routes under `/obs/flag/…` (director-gated over Funnel for free, since `console_policy` already maps any `obs` prefix to DIRECTOR). OBS gains 5 image sources + 10 scene items (5 in Stint, 5 in Splitscreen) following the existing `Standings` pattern. The Director Panel gets a dedicated FLAG GRAPHIC bus row; Companion gets a second row on its FLAGS page. The graphics pipeline (`get-graphics.py` / `setup-assets.py` / `tokenize-obs.py`) needs no change — the new tokens ride the existing download + transparent-placeholder path.

**Tech Stack:** Python 3 stdlib only (no framework, no pytest — each `tests/test_*.py` is a runnable script). HTML/vanilla-JS for the panel. Hand-edited JSON for the OBS collection and the Companion config.

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/` or `runtime/`.
- **English only** in all code, comments, and docs (chat is German; artifacts are international).
- **No secrets, no machine paths, no real IPs** anywhere — including tests.
- **Python-only tooling** — no `.sh`/`.bat`.
- **Outbound HTTP** is not involved here; do not add any `urlopen` calls.
- **Tests must run on any machine and in CI** (`python3 tools/run-tests.py`); cross-platform (Windows runner included) — use `os.path.join` only for current-machine paths.
- **Best-effort OBS contract:** every OBS call returns `(ok, note)` and NEVER raises; OBS unreachable → a note, never a crash (mirrors `obs_ws.set_scene_item_enabled` and `_release_obs_feeds`).
- **Backward compatibility matters** (racecast is released): the existing flag *text* path (`flag` Setup field, `#flag-status` chip) must remain completely unchanged.
- **Canonical flag keys** (used in endpoints, panel, Companion): `green`, `yellow`, `red`, `safety-car`, `virtual-safety-car`. Aliases accepted on input: `sc`→`safety-car`, `vsc`→`virtual-safety-car`. Empty/clear = `""`.
- **Sheet Assets labels / OBS source names / PNG basenames** (the three are identical): `Flag Green`, `Flag Yellow`, `Flag Red`, `Flag Safety Car`, `Flag Virtual Safety Car`.
- Run `python3 tools/lint.py` after changing any Python file and `python3 tools/run-tests.py` before finishing.

---

### Task 1: Pure flag-graphic helpers (`src/scripts/flag_graphic.py`)

The value→source map, the alias normalizer, and the mutual-exclusion intent builder. No I/O, no relay deps — fully unit-testable, mirrors the `cue_admin.py` pure-logic pattern.

**Files:**
- Create: `src/scripts/flag_graphic.py`
- Test: `tests/test_flag_graphic.py`

**Interfaces:**
- Produces:
  - `FLAG_GRAPHIC_SCENES = ("Stint", "Splitscreen")`
  - `FLAG_GRAPHIC_SOURCES: dict[str, str]` — canonical key → OBS source name, insertion-ordered green/yellow/red/safety-car/virtual-safety-car.
  - `normalize_flag_value(raw) -> str | None` — returns a canonical key, `""` for empty/clear, or `None` for a non-empty unknown value.
  - `flag_graphic_intents(active) -> list[tuple[str, str, bool]]` — 10 `(scene, source, enabled)` triples (scenes outer, sources inner, dict order); `enabled` true only for the active key's source. `active` `""`/`None`/invalid → all `False`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_flag_graphic.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for flag-status graphics. Run: python3 tests/test_flag_graphic.py"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


fg = _load("flag_graphic", ("src", "scripts", "flag_graphic.py"))


def t_sources_are_the_five_flags():
    assert list(fg.FLAG_GRAPHIC_SOURCES) == [
        "green", "yellow", "red", "safety-car", "virtual-safety-car"]
    assert fg.FLAG_GRAPHIC_SOURCES["green"] == "Flag Green"
    assert fg.FLAG_GRAPHIC_SOURCES["virtual-safety-car"] == "Flag Virtual Safety Car"
    assert fg.FLAG_GRAPHIC_SCENES == ("Stint", "Splitscreen")


def t_normalize_canonical_aliases_and_clear():
    assert fg.normalize_flag_value("green") == "green"
    assert fg.normalize_flag_value("GREEN") == "green"
    assert fg.normalize_flag_value(" Safety Car ") == "safety-car"
    assert fg.normalize_flag_value("sc") == "safety-car"
    assert fg.normalize_flag_value("vsc") == "virtual-safety-car"
    assert fg.normalize_flag_value("") == ""
    assert fg.normalize_flag_value(None) == ""
    assert fg.normalize_flag_value("purple") is None


def t_intents_show_one_hide_rest_in_both_scenes():
    intents = fg.flag_graphic_intents("yellow")
    assert len(intents) == 10                         # 5 sources x 2 scenes
    on = [(sc, src) for (sc, src, en) in intents if en]
    assert on == [("Stint", "Flag Yellow"), ("Splitscreen", "Flag Yellow")]
    # everything else hidden
    assert all(not en for (sc, src, en) in intents if src != "Flag Yellow")


def t_intents_clear_hides_all():
    for active in ("", None, "bogus"):
        assert all(not en for (_sc, _src, en) in fg.flag_graphic_intents(active))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_flag_graphic.py`
Expected: FAIL — `ModuleNotFoundError` / `spec.loader.exec_module` raises because `src/scripts/flag_graphic.py` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/flag_graphic.py`:

```python
#!/usr/bin/env python3
"""Flag-status graphics (parallel to the flag-text chip): pure value->OBS-source
mapping + mutual-exclusion intents + a small persisted store. No relay imports —
the relay wires obs_ws in as the store's apply_fn (mirrors cue_admin / chat).

Canonical keys are the slugified flag conditions; the OBS source name equals the
Sheet Assets label equals the PNG basename (e.g. key 'safety-car' -> 'Flag Safety
Car' -> 'Flag Safety Car.png'). Flags are mutually exclusive: at most one graphic
is visible, in BOTH the Stint and Splitscreen scenes, or none."""

import json
import os
import threading

# Scenes that carry the flag-graphic scene items (both get all five, kept in
# sync so a scene switch preserves the shown flag). Mirrors the OBS collection.
FLAG_GRAPHIC_SCENES = ("Stint", "Splitscreen")

# Canonical key -> OBS source name (== Sheet Assets label == PNG basename).
FLAG_GRAPHIC_SOURCES = {
    "green": "Flag Green",
    "yellow": "Flag Yellow",
    "red": "Flag Red",
    "safety-car": "Flag Safety Car",
    "virtual-safety-car": "Flag Virtual Safety Car",
}

# Input aliases accepted by normalize_flag_value (parity with the HUD flag chip).
FLAG_GRAPHIC_ALIASES = {"sc": "safety-car", "vsc": "virtual-safety-car"}


def normalize_flag_value(raw):
    """Canonical key for *raw*, or '' for empty/clear, or None for an unknown
    non-empty value. Lowercases, trims, and slugifies spaces to dashes, then
    applies the alias map — so 'Safety Car', 'safety-car', and 'sc' all map to
    'safety-car'."""
    if raw is None:
        return ""
    slug = "-".join(str(raw).strip().lower().split())
    if not slug:
        return ""
    slug = FLAG_GRAPHIC_ALIASES.get(slug, slug)
    return slug if slug in FLAG_GRAPHIC_SOURCES else None


def flag_graphic_intents(active):
    """[(scene, source, enabled), …] for every flag source in every flag scene;
    enabled is True only for *active*'s source. active '' / None / unknown -> all
    hidden. Deterministic order (scenes outer, sources inner)."""
    shown = FLAG_GRAPHIC_SOURCES.get(active)
    out = []
    for scene in FLAG_GRAPHIC_SCENES:
        for source in FLAG_GRAPHIC_SOURCES.values():
            out.append((scene, source, source == shown))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_flag_graphic.py`
Expected: PASS — prints `ok t_…` lines then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/flag_graphic.py tests/test_flag_graphic.py
git commit -m "feat(flag-graphic): pure value->source map + mutual-exclusion intents"
```

---

### Task 2: `FlagGraphicStore` (persisted, OBS-applying) in `src/scripts/flag_graphic.py`

A thread-safe store that owns the active flag, persists it to JSON (restart-safe, mirrors `EventTitleStore`), and applies the intents through an injected `apply_fn` so it is testable without OBS.

**Files:**
- Modify: `src/scripts/flag_graphic.py`
- Test: `tests/test_flag_graphic.py`

**Interfaces:**
- Consumes (Task 1): `FLAG_GRAPHIC_SOURCES`, `normalize_flag_value`, `flag_graphic_intents`.
- Produces:
  - `FlagGraphicStore(path, apply_fn=None)` — `apply_fn(scene, source, enabled) -> (ok, note)`; defaults to a no-op `(False, "obs unavailable")`.
  - `.get() -> str` (active key or `""`), `.data() -> {"active": <key>}`.
  - `.set(raw) -> {"ok": True, "active": <key>}` or `{"error": <msg>}` for an unknown value; persists + applies.
  - `.clear() -> {...}` (== `set("")`).
  - `.reassert() -> None` — re-apply the persisted active to OBS (best-effort; called at relay start).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_flag_graphic.py` (before the `__main__` block):

```python
class _FakeObs:
    """Records (scene, source, enabled) calls; mimics set_scene_item_enabled."""
    def __init__(self, reachable=True):
        self.calls = []
        self.reachable = reachable
    def apply(self, scene, source, enabled):
        self.calls.append((scene, source, enabled))
        return (True, "") if self.reachable else (False, "obs unavailable")


def t_store_set_persists_and_applies_one_visible():
    with tempfile.TemporaryDirectory() as d:
        obs = _FakeObs()
        st = fg.FlagGraphicStore(os.path.join(d, "flag-graphic.json"), apply_fn=obs.apply)
        res = st.set("vsc")
        assert res == {"ok": True, "active": "virtual-safety-car"}, res
        assert st.get() == "virtual-safety-car"
        on = [(sc, src) for (sc, src, en) in obs.calls if en]
        assert on == [("Stint", "Flag Virtual Safety Car"),
                      ("Splitscreen", "Flag Virtual Safety Car")]
        # persisted
        with open(os.path.join(d, "flag-graphic.json")) as fh:
            assert json.load(fh) == {"active": "virtual-safety-car"}


def t_store_reload_from_file_and_reassert():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "flag-graphic.json")
        with open(path, "w") as fh:
            json.dump({"active": "red"}, fh)
        obs = _FakeObs()
        st = fg.FlagGraphicStore(path, apply_fn=obs.apply)
        assert st.get() == "red"               # loaded
        assert obs.calls == []                  # construction does NOT apply
        st.reassert()
        on = [(sc, src) for (sc, src, en) in obs.calls if en]
        assert on == [("Stint", "Flag Red"), ("Splitscreen", "Flag Red")]


def t_store_clear_hides_all_and_persists_empty():
    with tempfile.TemporaryDirectory() as d:
        obs = _FakeObs()
        st = fg.FlagGraphicStore(os.path.join(d, "flag-graphic.json"), apply_fn=obs.apply)
        st.set("green"); obs.calls.clear()
        assert st.clear() == {"ok": True, "active": ""}
        assert st.get() == ""
        assert all(not en for (_sc, _src, en) in obs.calls)


def t_store_unknown_value_is_error_no_change():
    with tempfile.TemporaryDirectory() as d:
        obs = _FakeObs()
        st = fg.FlagGraphicStore(os.path.join(d, "flag-graphic.json"), apply_fn=obs.apply)
        st.set("green"); obs.calls.clear()
        res = st.set("purple")
        assert "error" in res
        assert st.get() == "green"             # unchanged
        assert obs.calls == []                  # not applied


def t_store_corrupt_file_defaults_to_empty():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "flag-graphic.json")
        with open(path, "w") as fh:
            fh.write("{not json")
        st = fg.FlagGraphicStore(path, apply_fn=_FakeObs().apply)
        assert st.get() == ""


def t_obs_unreachable_is_ok_not_crash():
    with tempfile.TemporaryDirectory() as d:
        obs = _FakeObs(reachable=False)
        st = fg.FlagGraphicStore(os.path.join(d, "flag-graphic.json"), apply_fn=obs.apply)
        res = st.set("yellow")                  # apply_fn returns (False, note)
        assert res == {"ok": True, "active": "yellow"}, res   # state still set + persisted
        assert st.get() == "yellow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_flag_graphic.py`
Expected: FAIL — `AttributeError: module 'flag_graphic' has no attribute 'FlagGraphicStore'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/flag_graphic.py`:

```python
def _noop_apply(scene, source, enabled):
    return False, "obs unavailable"


class FlagGraphicStore:
    """Active flag-graphic state: in-memory + JSON file (restart-safe) + OBS apply
    via an injected apply_fn (the relay passes obs_ws.set_scene_item_enabled).
    Mirrors EventTitleStore's local-file layer; NO sheet sync (this is OBS source
    visibility, not a HUD value). Selecting a flag shows its source and hides the
    other four in both scenes; clear hides all. Best-effort throughout: an OBS
    failure degrades to a note, the state is still stored and persisted."""

    def __init__(self, path, apply_fn=None):
        self.path = path
        self.apply_fn = apply_fn or _noop_apply
        self.lock = threading.Lock()
        self.active = ""                         # canonical key or ""
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            pass  # fresh layout; _save_file degrades per-write if the dir is missing
        self._load_file()

    # -- persistence ------------------------------------------------------
    def _load_file(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return  # no/corrupt file -> keep default ""
        if isinstance(saved, dict) and saved.get("active") in FLAG_GRAPHIC_SOURCES:
            self.active = saved["active"]

    def _save_file(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump({"active": self.active}, fh)
        except OSError:
            pass  # best-effort, same contract as the timer/event caches

    # -- read -------------------------------------------------------------
    def get(self):
        with self.lock:
            return self.active

    def data(self):
        return {"active": self.get()}

    # -- write ------------------------------------------------------------
    def set(self, raw):
        key = normalize_flag_value(raw)
        if key is None:
            return {"error": f"unknown flag graphic: {raw!r} "
                             f"(one of {', '.join(FLAG_GRAPHIC_SOURCES)})"}
        with self.lock:
            self.active = key
            self._save_file()
            self._apply_locked()
            return {"ok": True, "active": self.active}

    def clear(self):
        return self.set("")

    def reassert(self):
        """Re-push the persisted active flag to OBS (best-effort)."""
        with self.lock:
            self._apply_locked()

    def _apply_locked(self):
        for scene, source, enabled in flag_graphic_intents(self.active):
            self.apply_fn(scene, source, enabled)   # (ok, note) ignored — best-effort
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_flag_graphic.py`
Expected: PASS — all `ok t_…` lines then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/flag_graphic.py tests/test_flag_graphic.py
git commit -m "feat(flag-graphic): persisted FlagGraphicStore with injectable OBS apply"
```

---

### Task 3: Relay wiring — construct the store, re-assert at startup, serve `/obs/flag/*`

Import the module, build the store with `obs_ws.set_scene_item_enabled` as the apply function, re-assert on start, and add three GET routes. `console_policy` already maps any `obs` path to `Requirement(DIRECTOR, False)` (`src/scripts/console_policy.py:77`), so the routes are director-gated over Funnel automatically — add a guard test to lock that in.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (import near line 89; store construction in the startup block near line 6578 where `chat_store`/`cue_store` are built; GET route in `do_GET` near the `["setup"]` block ~line 5749)
- Test: `tests/test_flag_graphic.py` (console_policy guard)

**Interfaces:**
- Consumes (Task 2): `flag_graphic.FlagGraphicStore`, `flag_graphic.normalize_flag_value`.
- Produces: relay GET endpoints `/obs/flag/data`, `/obs/flag/set/<value>`, `/obs/flag/clear`; module global `flag_graphic_store` in the relay's `run`/server scope.

- [ ] **Step 1: Add the console_policy guard test (failing first only if the matrix changes — it should already pass)**

Append to `tests/test_flag_graphic.py` (before `__main__`):

```python
cp = _load("console_policy", ("src", "scripts", "console_policy.py"))


def t_console_policy_gates_obs_flag_as_director():
    # The flag-graphic routes live under /obs, which console_policy maps to
    # DIRECTOR — so the Funnel /console/panel director controls reach them and
    # commentators do not. Guards that mapping against a future refactor.
    for seg in (["obs", "flag", "data"], ["obs", "flag", "set", "green"],
                ["obs", "flag", "clear"]):
        assert cp.decide({"director"}, seg, "GET") == cp.ALLOW, seg
        assert cp.decide({"commentator"}, seg, "GET") == cp.FORBIDDEN, seg
```

Run: `python3 tests/test_flag_graphic.py`
Expected: PASS immediately (the policy already covers `obs`). If it FAILS, stop — the `obs`-prefix rule was changed and the design assumption is broken.

- [ ] **Step 2: Import the module in the relay**

In `src/relay/racecast-feeds.py`, next to the other `src/scripts` imports (the block around line 89 with `import cue_admin`), add:

```python
import flag_graphic   # flag-status graphics: value->source + persisted store (#flag-graphic)
```

- [ ] **Step 3: Construct the store + re-assert at startup**

In the relay startup block where `chat_store` / `cue_store` are created (around line 6578, `chat_store = ChatStore(os.path.join(runtime, "chat.json"))`), add:

```python
    def _flag_graphic_apply(scene, source, enabled):
        # Best-effort OBS apply; _obs_ws is None when the obs_ws import failed or
        # OBS is unreachable. Same contract as the POV/feed reflect calls.
        if _obs_ws is None:
            return False, "obs unavailable"
        return _obs_ws.set_scene_item_enabled(scene, source, enabled)
    flag_graphic_store = flag_graphic.FlagGraphicStore(
        os.path.join(runtime, "flag-graphic.json"), apply_fn=_flag_graphic_apply)
    flag_graphic_store.reassert()   # re-push the saved flag to OBS (best-effort)
```

Note: `flag_graphic_store` must be in scope where the request handler closure can see it (the same scope as `chat_store` / `setup_ctl`, which the handler already closes over). Place it alongside them so the nested `Handler` class can reference it.

- [ ] **Step 4: Add the GET routes in `do_GET`**

In `do_GET`, alongside the other segment-list branches (immediately after the `if p[:1] == ["setup"]:` block that ends ~line 5762), add:

```python
                if p[:2] == ["obs", "flag"]:
                    # Flag-status GRAPHIC toggle (parallel to the flag-text chip).
                    # GET so Companion's Generic-HTTP module hits it directly; the
                    # tailnet is the trust boundary. Funnel reaches it via the
                    # /console mount, director-gated by console_policy ('obs').
                    if p == ["obs", "flag", "data"]:
                        return self._send(flag_graphic_store.data())
                    if len(p) == 4 and p[2] == "set":
                        return self._send(flag_graphic_store.set(unquote(p[3])))
                    if p == ["obs", "flag", "clear"]:
                        return self._send(flag_graphic_store.clear())
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

(`unquote` is already imported at the top of the file — it is used by the `["setup"]` block right above.)

- [ ] **Step 5: Smoke-check imports + run the focused + relay-adjacent tests**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'src/scripts'); import flag_graphic; print('import ok')"
python3 tests/test_flag_graphic.py
python3 tests/test_pov.py        # relay still imports/parses (POV/schedule checks load the relay)
python3 tools/lint.py
```
Expected: `import ok`, `ALL PASS`, `test_pov.py` passes, lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_flag_graphic.py
git commit -m "feat(flag-graphic): relay store wiring + /obs/flag GET routes (director-gated over Funnel)"
```

---

### Task 4: OBS collection — 5 image sources + 10 scene items

Add the five flag image sources and their scene items to the **Stint** and **Splitscreen** scenes, by duplicating the existing `Standings` blocks verbatim and changing only the fields below. No tool change is needed — `tools/tokenize-obs.py` already tokenizes any `image_source.settings.file`, and `get-graphics.py` / `setup-assets.py` already seed transparent placeholders for any `__RACECAST_GRAPHICS__/…` token with no downloaded PNG.

**Files:**
- Modify: `src/obs/GT_Endurance.json`

**Reference blocks (in the current file):**
- `Standings` image source: lines 1654–1681.
- `Standings` scene item inside the Stint scene: lines 2020–~2060 (the object starting `"name": "Standings"`, `source_uuid: dddddd01-…`, ending after its `hide_transition`).

**Field values for the five new entries (uuids `dddddd06`–`dddddd0a` are unused; verified free):**

| Key | source `name` | `uuid` / `source_uuid` | `settings.file` |
|---|---|---|---|
| green | `Flag Green` | `dddddd06-0000-4000-8000-000000000006` | `__RACECAST_GRAPHICS__/Flag Green.png` |
| yellow | `Flag Yellow` | `dddddd07-0000-4000-8000-000000000007` | `__RACECAST_GRAPHICS__/Flag Yellow.png` |
| red | `Flag Red` | `dddddd08-0000-4000-8000-000000000008` | `__RACECAST_GRAPHICS__/Flag Red.png` |
| safety-car | `Flag Safety Car` | `dddddd09-0000-4000-8000-000000000009` | `__RACECAST_GRAPHICS__/Flag Safety Car.png` |
| virtual-safety-car | `Flag Virtual Safety Car` | `dddddd0a-0000-4000-8000-00000000000a` | `__RACECAST_GRAPHICS__/Flag Virtual Safety Car.png` |

- [ ] **Step 1: Confirm the uuids and pick free scene-item ids**

Run:
```bash
grep -c "dddddd0[6-9a]-0000-4000-8000" src/obs/GT_Endurance.json   # expect 0 (all free)
# Scene-item id ranges (ids are unique PER scene; reuse across scenes is fine):
python3 - <<'PY'
import json
c = json.load(open("src/obs/GT_Endurance.json"))
for s in c["sources"]:
    if s.get("id") == "scene" and s["name"] in ("Stint", "Splitscreen"):
        ids = sorted(it["id"] for it in s["settings"]["items"])
        print(s["name"], "max id", max(ids), "->", "use", list(range(max(ids)+1, max(ids)+6)))
PY
```
Expected: first command prints `0`. Use the printed id ranges (Stint max id is 30 → use 31–35; Splitscreen → use its own next-5). Record the two id lists.

- [ ] **Step 2: Add the five image sources**

In the top-level `sources` array, immediately after the `Standings` image-source object (after its closing `},` at line ~1681), insert five objects. Each is a verbatim copy of the `Standings` source (lines 1654–1681) with `name`, `uuid`, and `settings.file` replaced per the table. Example for the first:

```json
        {
            "prev_ver": 536936450,
            "name": "Flag Green",
            "uuid": "dddddd06-0000-4000-8000-000000000006",
            "id": "image_source",
            "versioned_id": "image_source",
            "settings": {
                "file": "__RACECAST_GRAPHICS__/Flag Green.png",
                "unload": false,
                "linear_alpha": true
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
            "hotkeys": {},
            "deinterlace_mode": 0,
            "deinterlace_field_order": 0,
            "monitoring_type": 0,
            "private_settings": {}
        },
```

Repeat for Yellow / Red / Safety Car / Virtual Safety Car with their `name`, `uuid`, `file`.

- [ ] **Step 3: Add five scene items to the Stint scene**

In the `Stint` scene's `settings.items` array, after the `Standings` scene item, insert five objects. Each is a verbatim copy of the `Standings` scene item (the object at lines ~2020–2060) with `name`, `source_uuid`, and `id` replaced (`id` = the Stint id list from Step 1, e.g. 31–35; `source_uuid` per the table). Rename the two transition `name` fields to match (e.g. `"Flag Green Show Transition"` / `"Flag Green Hide Transition"`) — purely cosmetic, but keep them consistent. `visible` MUST stay `false`. Example:

```json
                    {
                        "name": "Flag Green",
                        "source_uuid": "dddddd06-0000-4000-8000-000000000006",
                        "visible": false,
                        "locked": true,
                        "rot": 0.0,
                        "align": 5,
                        "bounds_type": 2,
                        "bounds_align": 0,
                        "bounds_crop": false,
                        "crop_left": 0,
                        "crop_top": 0,
                        "crop_right": 0,
                        "crop_bottom": 0,
                        "id": 31,
                        "group_item_backup": false,
                        "pos": { "x": 0.0, "y": 0.0 },
                        "scale": { "x": 1.0, "y": 1.0 },
                        "bounds": { "x": 1920.0, "y": 1080.0 },
                        "scale_filter": "disable",
                        "blend_method": "default",
                        "blend_type": "normal",
                        "show_transition": { "id": "fade_transition", "name": "Flag Green Show Transition", "duration": 300 },
                        "hide_transition": { "id": "fade_transition", "name": "Flag Green Hide Transition", "duration": 300 }
                    },
```

(Match the EXACT key layout of the existing `Standings` item — if the existing file expands `pos`/`scale`/`bounds`/transitions onto multiple lines, follow that; JSON is whitespace-insensitive but keep the diff clean.)

- [ ] **Step 4: Add five scene items to the Splitscreen scene**

Same five objects in the `Splitscreen` scene's `settings.items` array (append at the end of the items list), using the Splitscreen id list from Step 1. `source_uuid` values are the SAME five uuids (one source, referenced from both scenes). `visible: false`.

- [ ] **Step 5: Validate JSON + build verify**

Run:
```bash
python3 -c "import json; json.load(open('src/obs/GT_Endurance.json')); print('json ok')"
# uniqueness: each scene's item ids must be unique; each source uuid present once as a source def
python3 - <<'PY'
import json
c = json.load(open("src/obs/GT_Endurance.json"))
for s in c["sources"]:
    if s.get("id") == "scene" and s["name"] in ("Stint", "Splitscreen"):
        ids = [it["id"] for it in s["settings"]["items"]]
        assert len(ids) == len(set(ids)), (s["name"], "duplicate scene-item id")
        names = [it["name"] for it in s["settings"]["items"]]
        for flag in ("Flag Green","Flag Yellow","Flag Red","Flag Safety Car","Flag Virtual Safety Car"):
            assert flag in names, (s["name"], "missing", flag)
print("scene items ok")
PY
python3 tools/build.py
```
Expected: `json ok`, `scene items ok`, and `tools/build.py` completes with its verify step passing (tokenization intact, no secrets, no shell scripts).

- [ ] **Step 6: Commit**

```bash
git add src/obs/GT_Endurance.json
git commit -m "feat(obs): flag-status graphic sources + Stint/Splitscreen scene items"
```

---

### Task 5: Director Panel — FLAG GRAPHIC bus row

Add a dedicated, clearly-labelled row of five mutually-exclusive flag pills + CLEAR that drive `/obs/flag/…` and highlight the active flag from `/obs/flag/data`. Separate from the existing flag-text `#condRow`.

**Files:**
- Modify: `src/director/director-panel.html`

**Interfaces:**
- Consumes (Task 3): GET `/obs/flag/data` → `{active}`, `/obs/flag/set/<key>`, `/obs/flag/clear`. (The global `fetch` patch at lines 16–19 already prefixes `RC_API_BASE`, so plain `fetch("/obs/flag/…")` works at the tailnet root and under `/console`.)

- [ ] **Step 1: Add the bus container in the HTML**

After the `Gfx` bus section (line 465: `<section class="bus"><div class="cap">Gfx</div><div class="keys" id="gfxBus"></div></section>`), add:

```html
  <section class="bus"><div class="cap">Flag Gfx</div><div class="keys" id="flagGfxBus"></div></section>
```

- [ ] **Step 2: Add the config + render + poll JS**

After the `CONFIG.graphics.forEach(...)` block (ends line 784), add a render block. Reuse `mkKey(label, tag, onClick)` (defined at line 715). The five keys + CLEAR call the new endpoints; a module-level `flagGfxKeys` map lets the poll highlight the active one:

```javascript
/* ---------- Flag-status GRAPHIC bus (#flag-graphic) ----------
   Exactly-one-active OBS overlay toggle, PARALLEL to the flag-TEXT chip on
   #condRow. Drives /obs/flag/* (relay-mediated OBS visibility); the active flag
   is highlighted from /obs/flag/data. Distinct from the Gfx bus (independent
   toggles) — these five are mutually exclusive. */
const FLAG_GFX = [
  ["GREEN","green"], ["YELLOW","yellow"], ["RED","red"],
  ["SAFETY CAR","safety-car"], ["VSC","virtual-safety-car"],
];
const flagGfxKeys = {};          // key -> button
async function flagGfxSet(key){  // key "" clears
  const path = key ? "obs/flag/set/" + key : "obs/flag/clear";
  try{
    const r = await fetch("/" + path, {cache:"no-store"});
    const d = await r.json();
    if (d.error){ log("Flag gfx: " + d.error, "err"); toast("Flag gfx: " + d.error); }
    else log("Flag gfx → " + (key || "(cleared)"));
    flagGfxRender(d.active || "");
  }catch(e){ log("Flag gfx failed (relay reachable?): " + e, "err"); toast("Flag gfx failed — relay unreachable"); }
}
function flagGfxRender(active){
  for (const [key, btn] of Object.entries(flagGfxKeys)) btn.classList.toggle("on", key === active);
}
FLAG_GFX.forEach(([label, key])=>{
  const b = mkKey(label, "flaggfx", ()=>flagGfxSet(key));
  flagGfxKeys[key] = b; $("#flagGfxBus").appendChild(b);
});
$("#flagGfxBus").appendChild(mkKey("CLEAR", "stop", ()=>flagGfxSet("")));
async function flagGfxPoll(){
  try{
    const r = await fetch("/obs/flag/data", {cache:"no-store"});
    const d = await r.json();
    if (!d.error) flagGfxRender(d.active || "");
  }catch(e){ /* relay unreachable: leave the last highlight in place */ }
}
```

- [ ] **Step 3: Drive the poll from the existing loop**

Find the periodic poll driver (search for `setupPoll()` calls inside the page's interval/refresh function — e.g. a `setInterval` or a `refresh()` that already calls `setupPoll()` / `obsStatePoll()`). Add a `flagGfxPoll();` call next to the existing `obsStatePoll();` there, and call `flagGfxPoll();` once during initial load next to the initial `setupPoll();`. (Use the same cadence as `obsStatePoll` — the OBS state poll — since both reflect OBS-side state.)

Run to locate:
```bash
grep -n "obsStatePoll()\|setupPoll()" src/director/director-panel.html
```
Add `flagGfxPoll();` adjacent to each `obsStatePoll();` invocation (the recurring driver) and to the initial-load call site.

- [ ] **Step 4: Manual visual check (no unit test — HTML)**

Stand up a local dev build (see the `racecast-local-uat` skill) or rely on the e2e/manual UAT in Task 8. Confirm the new "Flag Gfx" row renders five pills + CLEAR, clicking one highlights it (and un-highlights the others), and CLEAR clears the highlight. With OBS connected, the matching graphic shows in both Stint and Splitscreen.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): FLAG GRAPHIC bus row (exactly-one-active, highlights from /obs/flag/data)"
```

---

### Task 6: Companion — second row on the FLAGS page

Add a "graphics" row beneath the existing text-flag row, colored per flag, calling `/obs/flag/…`. The `.companionconfig` is hand-edited JSON.

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig`

**Reference:** the FLAGS page is `"name": "FLAGS"` at line 4418; its buttons live under `"controls"` → row key `"0"` → column keys `"0"`–`"5"`. A single text button (Green) is lines 4420–4479 (note its unique `"id"` and the `url.value`). The new graphic buttons go under row key `"1"`, column keys `"0"`–`"5"`.

**Button spec (row "1"):**

| col | `text` | `url.value` | `bgcolor` (dec / hex) | `color` (text) |
|---|---|---|---|---|
| 0 | `GFX\nGREEN` | `http://127.0.0.1:8088/obs/flag/set/green` | `2066491` (0x1F8A3B) | `16777215` (white) |
| 1 | `GFX\nYELLOW` | `http://127.0.0.1:8088/obs/flag/set/yellow` | `15908884` (0xF2C014) | `0` (black) |
| 2 | `GFX\nSC` | `http://127.0.0.1:8088/obs/flag/set/safety-car` | `15908884` (0xF2C014) | `0` (black) |
| 3 | `GFX\nVSC` | `http://127.0.0.1:8088/obs/flag/set/virtual-safety-car` | `15908884` (0xF2C014) | `0` (black) |
| 4 | `GFX\nRED` | `http://127.0.0.1:8088/obs/flag/set/red` | `12984609` (0xC62121) | `16777215` (white) |
| 5 | `GFX\nCLEAR` | `http://127.0.0.1:8088/obs/flag/clear` | `0` (black) | `16777215` (white) |

- [ ] **Step 1: Add row "1" to the FLAGS page controls**

Under the FLAGS page `"controls"` object, add a `"1"` key (sibling of `"0"`) whose value is an object with column keys `"0"`–`"5"`. Each button is a verbatim copy of the existing text-flag button structure (lines 4420–4479) with these changes: `style.text`, `style.bgcolor`, `style.color` per the table; the single action's `options.url.value` per the table; and a **fresh unique `"id"`** for the action (21-char alphanumeric, unlike any existing id in the file). Example for col 0:

```json
     "0": {
      "type": "button",
      "style": {
       "text": "GFX\nGREEN",
       "textExpression": false,
       "size": "14",
       "png64": null,
       "alignment": "center:center",
       "pngalignment": "center:center",
       "color": 16777215,
       "bgcolor": 2066491,
       "show_topbar": "default"
      },
      "options": { "stepProgression": "auto", "stepExpression": "", "rotaryActions": false },
      "feedbacks": [],
      "steps": {
       "0": {
        "action_sets": {
         "down": [
          {
           "id": "Fg1GreenGfxBtn0aAbCdEf",
           "definitionId": "get",
           "connectionId": "BB0jmLMxj_0YwbhwslOiw",
           "options": {
            "url": { "value": "http://127.0.0.1:8088/obs/flag/set/green", "isExpression": false },
            "header": { "isExpression": false, "value": "" },
            "jsonResultDataVariable": { "isExpression": false },
            "result_stringify": { "isExpression": false, "value": true },
            "statusCodeVariable": { "isExpression": false }
           },
           "upgradeIndex": 1,
           "type": "action"
          }
         ],
         "up": []
        },
        "options": { "runWhileHeld": [] }
       }
      }
     },
```

Repeat for cols 1–5 with their text / bgcolor / color / url and a unique action `id` each (e.g. `Fg2YellowGfxBtn...`, `Fg3ScGfxBtn...`, `Fg4VscGfxBtn...`, `Fg5RedGfxBtn...`, `Fg6ClearGfxBtn...` — any 21-char unique string).

- [ ] **Step 2: Validate JSON + unique ids + portability**

Run:
```bash
python3 -c "import json; json.load(open('src/companion/racecast-buttons.companionconfig')); print('json ok')"
# action ids must be globally unique in the file
python3 - <<'PY'
import json, re
raw = open("src/companion/racecast-buttons.companionconfig").read()
ids = re.findall(r'"id":\s*"([^"]+)"', raw)
dupes = {i for i in ids if ids.count(i) > 1}
assert not dupes, ("duplicate ids", dupes)
print("ids unique:", len(ids))
PY
python3 tests/test_companion.py
```
Expected: `json ok`, `ids unique: …`, `test_companion.py` passes. If `tools/check_portable.py` exists in the build, also run `python3 tools/build.py` to confirm the bundled copy still strips the password and verifies.

- [ ] **Step 3: Commit**

```bash
git add src/companion/racecast-buttons.companionconfig
git commit -m "feat(companion): FLAGS page graphic-flag row -> /obs/flag (distinct from text row)"
```

---

### Task 7: Full suite + lint gate

Run the whole regression suite and lint exactly as CI does, before docs/screenshots.

**Files:** none (verification only).

- [ ] **Step 1: Run everything**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: the full suite passes (including the new `tests/test_flag_graphic.py`, auto-discovered) and lint is clean.

- [ ] **Step 2: (Optional but recommended) synthetic e2e**

Run:
```bash
python3 tools/e2e.py
```
Expected: the synthetic harness stands up the relay + Control Center and its checks pass — confirms the relay still boots with the new import + routes.

- [ ] **Step 3: Commit any fixes** (only if Steps 1–2 surfaced issues)

```bash
git add -A && git commit -m "test: fixes from full-suite run for flag-status graphics"
```

---

### Task 8: Docs + wiki screenshots (same change)

Per the CLAUDE.md rule, any visible Control-surface change ships its refreshed wiki screenshot in the SAME change. The Director Panel and the Companion FLAGS page both changed.

**Files:**
- Modify: the wiki Assets/Sheet docs under `src/docs/wiki/` (the page documenting the Assets tab labels + the Sheet-Webhook page if it lists flag controls).
- Modify (regenerate): `src/docs/wiki/images/director-panel.png` and the Companion FLAGS screenshot `src/docs/wiki/images/companion-page*-*.png` for the FLAGS page.

- [ ] **Step 1: Document the five new Assets labels + the text-vs-graphic distinction**

In the wiki page that lists the Sheet **Assets** rows (search `src/docs/wiki/` for the existing graphics-label list, e.g. "Standings", "Schedule"), add the five flag-graphic labels (`Flag Green`, `Flag Yellow`, `Flag Red`, `Flag Safety Car`, `Flag Virtual Safety Car`) with a one-line note: they are full-screen transparent 1080p PNGs, optional (missing → transparent placeholder), and are the GRAPHIC alternative to the flag-TEXT chip — toggled from the panel's "Flag Gfx" row and the Companion FLAGS page's graphic row. Run:
```bash
grep -rln "Standings\|Assets tab\|get-graphics" src/docs/wiki/
```
to find the right page(s).

- [ ] **Step 2: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: PASS (no broken links/anchors introduced).

- [ ] **Step 3: Regenerate the Director Panel screenshot**

Use the **`wiki-screenshots`** skill (drives a local dev build with the demo profile + `tools/obs-sim.py`). Recapture `director-panel.png` so the new "Flag Gfx" row is visible. Always capture from a local dev build (no `VERSION` stamped) per the CLAUDE.md uniformity rule.

- [ ] **Step 4: Regenerate the Companion FLAGS screenshot**

Use the **`companion-screenshots`** skill to recapture the FLAGS page board (now two rows).

- [ ] **Step 5: Commit docs + images**

```bash
git add src/docs/wiki/
git commit -m "docs(wiki): flag-status graphics — Assets labels + refreshed panel/Companion screenshots"
```

---

## Self-Review (completed by plan author)

**Spec coverage** — every spec section maps to a task:
- Parallel independent control → Tasks 1–3 (new module/store/endpoints, text path untouched). ✓
- Exactly-one-active + both scenes → `flag_graphic_intents` (Task 1), applied by the store (Task 2), scene items in both scenes (Task 4). ✓
- Sheet Assets naming + transparent fallback → Task 4 (tokens) + no-pipeline-change note; labels documented Task 8. ✓
- Relay endpoints + Funnel-first director-gating → Task 3 (`/obs/flag/*` under the already-DIRECTOR `obs` policy prefix) + the console_policy guard test. ✓
- Director Panel row → Task 5. ✓
- Companion second row, distinct from text → Task 6 (different row, color, `/obs/flag` endpoints). ✓
- Docs + screenshots → Task 8. ✓
- Tests + build verify → Tasks 1–4 inline + Task 7 full suite. ✓

**Placeholder scan** — no TBD/TODO; all code shown in full for Python; JSON/markup steps give exact field tables + verbatim-copy instructions with concrete example blocks.

**Type consistency** — `apply_fn(scene, source, enabled) -> (ok, note)` matches `obs_ws.set_scene_item_enabled`'s positional signature; `FlagGraphicStore.set/clear/data/get/reassert` names are used consistently across Tasks 2–3 and the panel consumes `{active}` from `/obs/flag/data` exactly as the store's `data()` produces it; canonical keys (`green`/`yellow`/`red`/`safety-car`/`virtual-safety-car`) are identical across module, endpoints, panel, and Companion.
