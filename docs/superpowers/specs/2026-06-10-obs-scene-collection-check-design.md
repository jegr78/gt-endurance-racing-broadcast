# OBS Scene Collection check & switch — design

**Issue:** #36 — "OBS: Websocket - Select matching Scene Collection"
**Date:** 2026-06-10
**Status:** approved-pending-review

## Problem

OBS can hold several scene collections. A producer who starts the broadcast with
the *wrong* collection active gets none of the IRO scenes/sources. The relay,
HUD and feeds all assume the `IRO Endurance` collection is loaded. Nothing today
detects or corrects a wrong active collection.

obs-websocket v5 exposes exactly the two requests this needs:

- `GetSceneCollectionList` → `currentSceneCollectionName` + `sceneCollections[]`
- `SetCurrentSceneCollection { sceneCollectionName }`

The expected name is knowable from the OBS export: `src/obs/IRO_Endurance.json`
has top-level `"name": "IRO Endurance"` — the name OBS shows after import.

## Decision (chosen approach: "warn + explicit switch action")

A mid-run yes/no prompt inside `event start` is **not** viable in the Control
Center: the UI runs every op as a subprocess with `stdin=DEVNULL`
(`ui_jobs.py:42`) and has no answer-back channel. So the confirmation becomes a
**discrete action** that fits the existing status-provider + op-registry model:

- `event start` / `event status` **only check and warn** — never auto-switch
  (switching tears down all sources, including the relay feeds; the producer
  must opt in).
- A separate **switch** is the explicit "yes": `iro obs collection set` on the
  CLI, and a **Switch** button in the Control Center's Apps-view OBS row.

### Resolved design choices

1. **Expected name:** exact constant `EXPECTED_SCENE_COLLECTION = "IRO Endurance"`
   in `obs_ws.py`, documented to mirror the `name` field of
   `src/obs/IRO_Endurance.json`. (Not parsed at runtime — the file is renamed +
   tokenized in the shipped package and bundled differently when frozen; a magic
   string with a "keep in sync" comment is simpler and testable. A scene
   collection name is not a secret, so the no-hardcoding rule does not apply.)
2. **Matching:** `current` is *correct* iff it equals the expected name. A
   `startswith("IRO Endurance")` match that is **not** exact (e.g. an
   import-renamed `IRO Endurance 2`) produces a distinct warning ("looks
   renamed — switch manually"), never an automatic guess.
3. **`set` target:** switches only to the exact `IRO Endurance` when that name is
   present in the list. If it is absent, `set` refuses with a clear message
   (no guessing between renamed variants).
4. **UI surfacing:** on-demand `GET /api/obs-collection` (live OBS connect only
   when the Apps view opens — like `/api/update`, never in the cheap
   `/api/status` dashboard poll). The OBS row shows ✓ correct / ⚠ wrong + a
   **Switch** button when wrong.
5. **Readiness report:** `iro event status` gains a non-fatal (WARN) collection
   line in the Apps section; `event start` also warns after OBS comes up.

All OBS-websocket I/O stays **best-effort** (the module's existing contract):
any failure — OBS closed, wrong password, output active, protocol surprise —
returns `(..., note)` and never raises.

## Components

### 1. `src/scripts/obs_ws.py` — protocol + pure logic

**New constant**
```python
EXPECTED_SCENE_COLLECTION = "IRO Endurance"   # mirrors name in src/obs/IRO_Endurance.json
```

**New pure function (unit-tested):**
```python
def scene_collection_status(current, available, expected=EXPECTED_SCENE_COLLECTION):
    """Classify the active scene collection. Pure.
    Returns {
      "current": current,            # active collection name (or None/"" if unknown)
      "expected": expected,
      "available": list(available),  # all collection names OBS reported
      "match": current == expected,  # the only "correct" state
      "expected_present": expected in available,   # can we switch to it?
      "renamed_variant": <name or None>,  # a non-exact "IRO Endurance*" present
    }"""
```
`renamed_variant` = the first `available` name that `startswith(expected)` but
`!= expected` (drives the "looks renamed" warning). This is the only place the
prefix heuristic lives.

**New I/O functions (best-effort, mirror `refresh_browser_inputs`):**
```python
def get_scene_collection(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """(status_dict, note). Connects, GetSceneCollectionList, runs
    scene_collection_status(). (None, reason) on any failure — never raises."""

def set_scene_collection(name=EXPECTED_SCENE_COLLECTION, host="127.0.0.1",
                         port=None, password=None, timeout=2.0):
    """(ok_bool, note). Refuses (False, reason) if `name` is not in the live
    list (avoids creating/guessing). Otherwise SetCurrentSceneCollection.
    OBS rejects the switch while an output (stream/record/virtual-cam) is
    active — that surfaces as (False, <obs error>), printed/shown, never raised."""
```
`set_scene_collection` first calls `GetSceneCollectionList` to (a) early-return
when already correct and (b) verify the target exists before switching.

### 2. `src/iro.py` — CLI surface + event integration

- `OBS_VERBS = ("refresh", "collection")`. New `obs_collection_cmd(rest)`:
  - `iro obs collection` (no arg) → check & print status (current, expected,
    match/renamed/absent), exit 0.
  - `iro obs collection set` → switch; print the `(ok, note)` outcome. Upfront
    relay-independent: only needs OBS reachable. Non-zero exit on failure so the
    UI job shows red.
- `event_start`: after the "wait until up" loop confirms OBS is up (near the
  existing `_refresh_obs_pages()` retry at the both-sides-up point), call a new
  `_check_scene_collection()` helper that prints one warning line on
  mismatch/renamed/unreachable and the remedy (`iro obs collection set` / Switch
  button). Best-effort, never blocks bring-up.
- `event_status`: `_event_sections()` adds an OBS-collection Result to the Apps
  section via a new `ev.classify_scene_collection(...)`.

### 3. `src/scripts/event.py` — readiness classification

```python
def classify_scene_collection(status, note):
    """WARN-level. status = obs_ws.scene_collection_status dict or None.
    - status is None        -> WARN "check skipped — {note}" (OBS unreachable etc.)
    - status["match"]       -> PASS "IRO Endurance active"
    - renamed_variant       -> WARN "'{variant}' active — looks renamed; switch manually"
    - expected_present      -> WARN "'{current}' active — switch to IRO Endurance (iro obs collection set)"
    - else                  -> WARN "IRO Endurance collection not found — import it (iro setup)"
    """
```
WARN, not FAIL: the report stays informational + actionable; a flaky live probe
must not turn a green readiness report red on its own.

### 4. Control Center — `src/ui/`

- **`ui_ops.py`:** add `"obs-collection-set": ["obs", "collection", "set"]` to
  `OPS` (no params).
- **`ui_server.py`:** add `GET /api/obs-collection` → `ctx["obs_collection"]()`
  (same try/except envelope as `/api/obs-ws`).
- **`iro.py` UI ctx:** add an `obs_collection` provider calling
  `obs_ws.get_scene_collection()` and returning
  `{"ok": True, **status}` / `{"ok": False, "note": ...}`.
- **`control-center.html`:** in the Apps-view OBS row, fetch `/api/obs-collection`
  on view open; render ✓ correct / ⚠ wrong-or-renamed; show a **Switch** button
  (triggers `obs-collection-set`) only when `expected_present && !match`. Refetch
  after the switch job finishes. No confirm dialog needed beyond the standard op
  flow (the action is explicit).

## Data flow

```
iro obs collection        -> obs_ws.get_scene_collection() -> print status
iro obs collection set     -> obs_ws.set_scene_collection() -> SetCurrentSceneCollection
event start (after OBS up) -> _check_scene_collection() -> warn line (best-effort)
event status               -> ev.classify_scene_collection() -> Apps WARN/PASS line
UI Apps view (on open)     -> GET /api/obs-collection -> ✓/⚠ + [Switch]
UI [Switch] click          -> POST /api/op/obs-collection-set -> job -> refetch
```

## Error handling

Every OBS path is best-effort and returns a note instead of raising:
- OBS not running / WS unreachable → `(None/False, "OBS WebSocket not reachable…")`.
- Output active (stream/record/virtual-cam) → OBS rejects `SetCurrentSceneCollection`;
  surfaces as `(False, <obs status>)`; the producer sees "stop the output first".
- `set` target absent → refused, no creation/guess.
- `event start` / `event status` degrade to a WARN/skip line; bring-up never blocks.

## Testing (TDD, `tests/test_obsws.py` + `tests/test_event.py` + `tests/test_ui_ops.py`)

Pure-logic first, then thin I/O via the existing fake-session seam used by the
other `obs_ws` tests.

- `scene_collection_status`: match; wrong-but-present; renamed variant
  (`IRO Endurance 2`); expected absent; empty/None current; unrelated
  collections only.
- `set_scene_collection`: already-correct early return; target present → issues
  `SetCurrentSceneCollection`; target absent → refuses without a switch request;
  OBS error/output-active → `(False, note)`, no raise; OBS unreachable →
  `(False, note)`.
- `get_scene_collection`: maps a fake `GetSceneCollectionList` response to the
  status dict; unreachable → `(None, note)`.
- `classify_scene_collection`: each branch (None/match/renamed/present/absent)
  → correct level + name + detail.
- `ui_ops`: `obs-collection-set` builds `["obs","collection","set"]`; rejects
  unexpected params.

CI: `python3 tools/run-tests.py` + `python3 tools/lint.py`; `python3 tools/build.py`
verify (no shell scripts, secrets, tokenization intact).

## Out of scope (YAGNI)

- Creating/importing a missing collection (that is `iro setup` + manual import).
- Auto-switching during `event start` (deliberately rejected — see Decision).
- A mid-run yes/no prompt and the UI stdin plumbing it would require.
- Per-scene validation inside the collection (the issue is collection selection).

## Docs touched

- `CLAUDE.md`: relay/obs_ws section — note the collection check/switch.
- `README.md` + command list: `iro obs collection [set]`.
- Apps-view note in `control-center.html` already mentions the collection;
  extend to mention the indicator + Switch.
