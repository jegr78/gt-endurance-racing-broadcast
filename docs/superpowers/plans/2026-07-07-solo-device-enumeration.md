# Solo device enumeration (OBS-WS) → `.env` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (or executing-plans) to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax.

**Goal:** Let an operator pick the local webcam/capture-card device from the real OBS
device list (enumerated via OBS-WebSocket) and persist it to `.env`
(`RACECAST_WEBCAM`/`RACECAST_CAPTURE`), so #303's token injection bakes it in on the
next `setup`. Two surfaces: a CLI `racecast device-scan` and a Control Center →
General Settings dropdown.

**Architecture:** A pure parser + best-effort network helper in `obs_ws.py` (mirroring
`release_feed_inputs`); a `.env` **upsert** helper in `racecast.py` (read-merge-write,
never dropping unlisted keys); the CLI command; a Control Center route + provider +
General-Settings UI; then the deferred #303 minor cleanups. Everything additive; the
endurance path is untouched.

**Tech Stack:** Python 3.11+ stdlib. OBS-WebSocket v5 (existing `obs_ws.py`). Tests are
runnable scripts under `tests/` (no pytest); hyphenated scripts loaded via importlib.

## Global Constraints

- Edit only under `src/`, `tools/`, `tests/`, `docs/`, `src/docs/wiki/images/`.
- English only; no secrets/machine paths/real device ids in committed files (device ids
  are written only to the gitignored `.env`).
- `.env` keys are **`RACECAST_WEBCAM` / `RACECAST_CAPTURE`** (the #303 keys) — NOT the
  issue's `_DEVICE` variant.
- The device `.env` write is an **UPSERT**: read current machine `.env`, overlay only
  the device keys, write the full merged set. Never call `env_write_data`/`merge_env_text`
  with only the two keys (it drops every unlisted `RACECAST_*` key).
- Endurance path unaffected; no existing test disabled; `run-tests.py` + `lint.py` green;
  tests run on Windows CI (no OS-absolute paths; use fixtures).
- `obs_ws.py` must stay importable WITHOUT importing `setup-assets` — the per-OS device
  property mapping is duplicated and pinned by a cross-check test (the `STREAMLINK_TWITCH`
  precedent), not shared by import.
- The Control Center General-Settings UI change requires regenerating
  `src/docs/wiki/images/cc-settings.png` (dev build) + a visual verification, in this PR.
- Work on branch `feat/304-device-enumeration` (off `epic/300-solo-mode`); PR
  `--base epic/300-solo-mode`.

## File Structure

- `src/scripts/obs_ws.py` — `parse_property_items`, `device_property_name`,
  `enumerate_device_options`.
- `src/racecast.py` — `env_upsert_data`; `device-scan` command (`device_scan_cmd` +
  pure `resolve_device_selection`); kind-aware `setup` `--out` default (cleanup D).
- `src/ui/ui_server.py` — `GET /api/devices`, `POST /api/devices/select` routes.
- `src/racecast_ui.py` (or wherever the ctx providers live) — `devices_enumerate` +
  `devices_write` providers wired into the ui_server ctx.
- `src/ui/control-center.html` — the "Solo devices" section in General Settings.
- `tools/derive-solo-templates.py` + `src/obs/GT_Solo_*.json` — cleanup D.
- Tests: `tests/test_obsws.py`, `tests/test_racecast.py`, `tests/test_ui_server.py`,
  `tests/test_solo_obs.py`.

---

### Task 1: OBS-WS device enumeration (`obs_ws.py`)

**Files:** Modify `src/scripts/obs_ws.py`; Test `tests/test_obsws.py`.

**Interfaces — Produces:**
- `parse_property_items(payload) -> list[dict]` — `[{"name","value","enabled"}]`.
- `device_property_name(platform) -> str | None`.
- `enumerate_device_options(input_name, property_name, host="127.0.0.1", port=None,
  password=None, timeout=2.0) -> (list, str)`.

- [ ] **Step 1: Failing tests** — append to `tests/test_obsws.py` (match its existing
  import of `obs_ws`; read the top of the file first):

```python
def t_parse_property_items_basic():
    payload = {"propertyItems": [
        {"itemName": "FaceTime HD", "itemEnabled": True, "itemValue": "0x14000000"},
        {"itemName": "Elgato", "itemEnabled": True, "itemValue": "0x14200000"},
        {"itemName": "Disabled Dummy", "itemEnabled": False, "itemValue": ""},
    ]}
    items = obs_ws.parse_property_items(payload)
    assert items == [
        {"name": "FaceTime HD", "value": "0x14000000", "enabled": True},
        {"name": "Elgato", "value": "0x14200000", "enabled": True},
    ]  # empty-value item dropped


def t_parse_property_items_malformed():
    assert obs_ws.parse_property_items({}) == []
    assert obs_ws.parse_property_items({"propertyItems": None}) == []
    assert obs_ws.parse_property_items("garbage") == []


def t_device_property_name_per_platform():
    assert obs_ws.device_property_name("darwin") == "device"
    assert obs_ws.device_property_name("win32") == "video_device_id"
    assert obs_ws.device_property_name("linux") == "device_id"
    assert obs_ws.device_property_name("sunos5") is None


def t_device_property_name_matches_setup_assets_variants():
    # cross-check: obs_ws (enumeration) and setup-assets (localization) must agree on
    # the per-OS device-id settings key, or a scanned value lands in the wrong field.
    import importlib.util, os
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    spec = importlib.util.spec_from_file_location(
        "setup_assets_x", os.path.join(root, "src", "setup-assets.py"))
    sa = importlib.util.module_from_spec(spec); spec.loader.exec_module(sa)
    for os_key, plat in (("darwin", "darwin"), ("win", "win32"), ("linux", "linux")):
        _src_id, prop_key = sa.DEVICE_VARIANTS[os_key]
        assert obs_ws.device_property_name(plat) == prop_key, os_key
```

- [ ] **Step 2: Run — verify fail.** `python3 tests/test_obsws.py` → FAIL (functions missing).

- [ ] **Step 3: Implement** in `src/scripts/obs_ws.py` (near the other pure parsers /
  `release_feed_inputs`):

```python
DEVICE_PROPERTY_NAMES = {"darwin": "device", "win": "video_device_id", "linux": "device_id"}


def device_property_name(platform):
    """OBS input-settings property key holding the video device id for `platform`,
    or None if unknown. MUST match setup-assets.DEVICE_VARIANTS (cross-checked by a
    test) — enumeration writes into the same field localization later reads."""
    if platform.startswith("win"):
        return DEVICE_PROPERTY_NAMES["win"]
    if platform == "darwin":
        return DEVICE_PROPERTY_NAMES["darwin"]
    if platform.startswith("linux"):
        return DEVICE_PROPERTY_NAMES["linux"]
    return None


def parse_property_items(payload):
    """[{name,value,enabled}] from a GetInputPropertiesListPropertyItems response,
    dropping items with an empty/None itemValue. Tolerant: bad shape -> []."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("propertyItems")
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        val = it.get("itemValue")
        if val is None or val == "":
            continue
        out.append({"name": it.get("itemName", ""), "value": val,
                    "enabled": bool(it.get("itemEnabled", True))})
    return out


def enumerate_device_options(input_name, property_name, host="127.0.0.1", port=None,
                             password=None, timeout=2.0):
    """(items, note) — the device dropdown OBS offers for `input_name`'s
    `property_name`. Best-effort like release_feed_inputs: OBS unreachable / input
    absent / protocol surprise -> ([], reason), never raises. Callers surface `note`."""
    if not property_name:
        return [], f"no device property for this platform"
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    try:
        payload = session.request("GetInputPropertiesListPropertyItems",
                                  {"inputName": input_name, "propertyName": property_name})
        return parse_property_items(payload), ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return [], (f"input {input_name!r} not found — import the solo collection first"
                    if "not found" in str(exc).lower() or "InvalidResource" in str(exc)
                    else (str(exc) or exc.__class__.__name__))
    finally:
        session.close()
```

- [ ] **Step 4: Run — verify pass.** `python3 tests/test_obsws.py` → PASS.
- [ ] **Step 5: lint** `python3 tools/lint.py` → clean.
- [ ] **Step 6: Commit** `src/scripts/obs_ws.py tests/test_obsws.py`:
  `git commit -m "feat(solo): OBS-WS device enumeration helper (#304)"`
  (end body with the Co-Authored-By trailer).

---

### Task 2: `.env` upsert helper (`racecast.py`)

**Files:** Modify `src/racecast.py`; Test `tests/test_racecast.py`.

**Interfaces — Produces:** `env_upsert_data(updates: dict, path=None) -> dict`
(`{ok,path}` / `{ok:false,error}`), preserving all existing keys.

- [ ] **Step 1: Failing test** — append to `tests/test_racecast.py` (match its module
  alias — read the top; it likely imports racecast as `rc`/`m`):

```python
def t_env_upsert_preserves_other_keys():
    import tempfile, os as _os
    d = tempfile.mkdtemp(prefix="racecast-envupsert-")
    p = _os.path.join(d, ".env")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("# machine knobs\nRACECAST_OBS_WS_PASSWORD=secret\nRACECAST_UI_PORT=8089\n")
    res = rc.env_upsert_data({"RACECAST_WEBCAM": "cam0", "RACECAST_CAPTURE": "cap1"}, path=p)
    assert res["ok"], res
    text = open(p, encoding="utf-8").read()
    assert "RACECAST_OBS_WS_PASSWORD=secret" in text   # unrelated key preserved
    assert "RACECAST_UI_PORT=8089" in text
    assert "RACECAST_WEBCAM=cam0" in text
    assert "RACECAST_CAPTURE=cap1" in text
    assert "# machine knobs" in text                   # comment preserved


def t_env_upsert_updates_existing_key_in_place():
    import tempfile, os as _os
    d = tempfile.mkdtemp(prefix="racecast-envupsert2-")
    p = _os.path.join(d, ".env")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("RACECAST_WEBCAM=old\nRACECAST_UI_PORT=8089\n")
    rc.env_upsert_data({"RACECAST_WEBCAM": "new"}, path=p)
    text = open(p, encoding="utf-8").read()
    assert "RACECAST_WEBCAM=new" in text and "RACECAST_WEBCAM=old" not in text
    assert "RACECAST_UI_PORT=8089" in text
```

- [ ] **Step 2: Run — verify fail.** Run the two new tests → FAIL (`env_upsert_data` missing).

- [ ] **Step 3: Implement** in `src/racecast.py` near `env_write_data` — read the current
  `.env`, overlay `updates`, write the FULL set through the existing validated writer.
  Read the existing `.env`-reading helper first (the GET `/api/env` data provider parses
  the file into entries — reuse it; likely `env_read_data`/`parse_env_text`):

```python
def env_upsert_data(updates, path=None):
    """Set each key in `updates` (dict) in the machine .env WITHOUT dropping any other
    key. env_write_data treats its entries as the COMPLETE set (unlisted real keys are
    removed), so we read the current entries, overlay `updates`, and write the union.
    {ok,path} or {ok:false,error}. Never raises."""
    target = path or _env_file()
    try:
        original = ""
        if os.path.isfile(target):
            with open(target, encoding="utf-8") as fh:
                original = fh.read()
    except OSError as exc:
        return {"ok": False, "error": f"could not read .env: {exc}"}
    pairs = parse_env_text(original)          # [(key, value)] — reuse the existing parser
    merged = {k: v for k, v in pairs}
    merged.update({k: str(v) for k, v in updates.items()})
    entries = [[k, v] for k, v in merged.items()]
    return env_write_data(entries, path=target)
```

(If the existing parser is named differently than `parse_env_text`, use the real name —
grep `def parse_env_text` / how GET `/api/env` builds its entries. Preserve ordering as
much as the parser allows; `merge_env_text` keeps existing lines in place regardless.)

- [ ] **Step 4: Run — verify pass** (the two tests) → PASS.
- [ ] **Step 5:** `python3 tools/run-tests.py` + `python3 tools/lint.py` → green.
- [ ] **Step 6: Commit** `src/racecast.py tests/test_racecast.py`:
  `git commit -m "feat(solo): .env upsert helper that preserves unlisted keys (#304)"`

---

### Task 3: CLI `racecast device-scan` (`racecast.py`)

**Files:** Modify `src/racecast.py`; Test `tests/test_racecast.py`.

**Interfaces — Consumes:** `obs_ws.enumerate_device_options`,
`obs_ws.device_property_name`, `env_upsert_data`.
**Produces:** `resolve_device_selection(devices, token) -> (value|None, error|None)`
(pure); `device_scan_cmd(rest)` wired into the CLI dispatch + help.

- [ ] **Step 1: Failing test (pure resolver)** — append to `tests/test_racecast.py`:

```python
def t_resolve_device_selection_by_index_and_id():
    devs = [{"name": "FaceTime", "value": "0x14000000"},
            {"name": "Elgato HD60", "value": "0x14200000"}]
    assert rc.resolve_device_selection(devs, "1") == ("0x14000000", None)   # 1-based index
    assert rc.resolve_device_selection(devs, "2") == ("0x14200000", None)
    assert rc.resolve_device_selection(devs, "Elgato") == ("0x14200000", None)  # name substring
    assert rc.resolve_device_selection(devs, "0x14000000") == ("0x14000000", None)  # exact value
    val, err = rc.resolve_device_selection(devs, "9")
    assert val is None and "out of range" in err
    val, err = rc.resolve_device_selection(devs, "nosuch")
    assert val is None and err
    assert rc.resolve_device_selection(devs, "") == (None, None)   # blank = skip/leave
```

- [ ] **Step 2: Run — verify fail.** → FAIL (`resolve_device_selection` missing).

- [ ] **Step 3: Implement the resolver + command.** Pure resolver:

```python
def resolve_device_selection(devices, token):
    """Map a user token to a device value. token: "" -> (None,None) (skip/leave);
    a 1-based index; a case-insensitive name substring; or an exact value. Returns
    (value, None) or (None, error)."""
    token = (token or "").strip()
    if not token:
        return None, None
    if token.isdigit():
        i = int(token)
        if 1 <= i <= len(devices):
            return devices[i - 1]["value"], None
        return None, f"index {i} out of range (1..{len(devices)})"
    for d in devices:                                   # exact value first
        if d["value"] == token:
            return d["value"], None
    matches = [d for d in devices if token.lower() in d.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]["value"], None
    if not matches:
        return None, f"no device matches {token!r}"
    return None, f"{token!r} is ambiguous ({len(matches)} matches)"
```

Command `device_scan_cmd(rest)` (follow the argument-parsing style of a nearby
one-shot command; add it to the command dispatch table + the help text):
- parse `--webcam VAL` / `--capture VAL` (optional).
- `devices, note = obs_ws.enumerate_device_options("Solo Capture Device",
  obs_ws.device_property_name(sys.platform))`.
- if not `devices`: print `note` (or the "import the solo collection first" guide) and
  return non-zero.
- print the numbered device list.
- if neither flag given → interactive: prompt "Webcam [index/name, blank=skip]:" and
  "Capture [...]:" via `input()`.
- resolve each provided token with `resolve_device_selection`; on error print it and
  return non-zero without writing.
- build `updates = {}`; add `RACECAST_WEBCAM`/`RACECAST_CAPTURE` for each resolved value;
  if empty (both skipped) print "nothing to write" and return 0.
- `env_upsert_data(updates)`; print the written keys and "Re-run `racecast setup` to bake
  these into the OBS collection."

Guard `input()` for non-interactive/headless: if neither flag is given AND stdin is not a
TTY (`not sys.stdin.isatty()`), print the list + a hint to pass `--webcam/--capture` and
return 0 (do not block on input).

- [ ] **Step 4: Run — verify pass** (resolver test) → PASS.
- [ ] **Step 5: Add a routing test** — assert `device-scan` is a known command in the
  dispatch table / help (match how `tests/test_racecast.py` asserts other commands
  route). Run it → PASS.
- [ ] **Step 6:** `python3 tools/run-tests.py` + `python3 tools/lint.py` → green.
- [ ] **Step 7: Commit** `src/racecast.py tests/test_racecast.py`:
  `git commit -m "feat(solo): racecast device-scan CLI (#304)"`

---

### Task 4: Control Center route + provider + General-Settings UI

**Files:** Modify `src/ui/ui_server.py`, the ctx-provider wiring (grep
`"env_write": env_write_data` — same dict, ~`src/racecast.py:6132`),
`src/ui/control-center.html`; Test `tests/test_ui_server.py`.

**Interfaces — Produces:** `GET /api/devices` → `{ok, devices:[{name,value}], note}`;
`POST /api/devices/select` (body `{webcam, capture}`) → `{ok, path}`/`{ok:false,error}`.

- [ ] **Step 1: Failing route tests** — append to `tests/test_ui_server.py`, following
  how it builds a `ctx` with injected providers and drives routes (read the file's
  existing route tests first). Inject a fake `devices_enumerate` returning a known list
  and a fake `devices_write` recording its call:

```python
def t_get_devices_returns_enumerated_list():
    ctx = _ctx(devices_enumerate=lambda: {"ok": True,
              "devices": [{"name": "Cam", "value": "v0"}], "note": ""})
    status, body = _get(ctx, "/api/devices")
    assert status == 200
    assert body["devices"] == [{"name": "Cam", "value": "v0"}]


def t_post_devices_select_writes_env():
    seen = {}
    ctx = _ctx(devices_write=lambda w, c: seen.update(webcam=w, capture=c) or {"ok": True})
    status, body = _post(ctx, "/api/devices/select", {"webcam": "v0", "capture": "v1"})
    assert status == 200 and body["ok"]
    assert seen == {"webcam": "v0", "capture": "v1"}
```

(Use the file's real ctx-builder + `_get`/`_post` helpers — names may differ; mirror the
existing `/api/env` route tests exactly.)

- [ ] **Step 2: Run — verify fail.** → FAIL (routes/providers missing).

- [ ] **Step 3: Implement.**
  - `src/ui/ui_server.py`: add `GET /api/devices` (call `ctx["devices_enumerate"]()`,
    return its dict) and `POST /api/devices/select` (parse `{webcam,capture}`, call
    `ctx["devices_write"](webcam, capture)`) — mirror the `/api/env` GET+POST error
    handling (malformed-body 400, exception → 500).
  - Providers (in the module that builds the ui_server ctx dict): `devices_enumerate()` →
    `{ok, devices, note}` from `obs_ws.enumerate_device_options("Solo Capture Device",
    obs_ws.device_property_name(sys.platform))`; `devices_write(webcam, capture)` →
    `env_upsert_data` of the non-empty ones (a blank value leaves that key unchanged).
    Wire both into the ctx dict next to `"env_write"`.
  - `src/ui/control-center.html`: in the General Settings view (next to the `.env`
    editor / font library), add a "Solo devices" section: two `<select>` (Webcam,
    Capture) + a Save button. On view open, `GET /api/devices`; populate both selects
    (pre-select current values if the page knows them — otherwise leave at "—"); on Save,
    `POST /api/devices/select`. On `ok:false`/empty devices, disable the selects and show
    `note` (or the import-first hint). Match the existing section markup/JS style.

- [ ] **Step 4: Run — verify pass** (route tests) → PASS.
- [ ] **Step 5:** `python3 tools/run-tests.py` + `python3 tools/lint.py` → green.
- [ ] **Step 6: Commit** the four files:
  `git commit -m "feat(solo): device dropdown in Control Center General Settings (#304)"`
  (Note: the wiki screenshot is Task 6 — do NOT mark the UI done for docs yet.)

---

### Task 5: Deferred #303 cleanups (derive script + kind-aware import name)

**Files:** Modify `tools/derive-solo-templates.py`, regenerate
`src/obs/GT_Solo_Commentary.json` + `src/obs/GT_Solo_POV.json`; Modify `src/racecast.py`;
Test `tests/test_solo_obs.py`, `tests/test_racecast.py`.

- [ ] **Step 1: Failing tests** —
  - `tests/test_solo_obs.py`: assert each committed solo JSON has `name ==
    "GT Racing Solo"` and contains NO source named `Splitscreen Labels` and NO group
    named `Split HUD` (load JSON; check `sources` names + the top-level `groups` array).
  - `tests/test_racecast.py`: assert the solo `setup` default out filename is
    `GT_Solo.import.json` for a solo kind (test the pure default-`--out` selection —
    grep how `_oneshot_extra` builds the `setup` out; make it kind-aware and testable).

- [ ] **Step 2: Run — verify fail.**

- [ ] **Step 3: Implement.**
  - `tools/derive-solo-templates.py`: after building the collection, set
    `col["name"] = "GT Racing Solo"`. Prune the `Splitscreen`-only leftovers: remove any
    source named `Splitscreen Labels` from `col["sources"]`, and remove the `Split HUD`
    entry from the top-level `col["groups"]` array (and any now-orphaned group members).
    Re-run `python3 tools/derive-solo-templates.py` to regenerate both JSONs
    deterministically.
  - `src/racecast.py`: in `_oneshot_extra` (the `setup` default `--out` at
    `os.path.join(runtime_dir, "GT_Endurance.import.json")`), pick the filename by kind —
    `GT_Solo.import.json` when the active kind is solo, else `GT_Endurance.import.json`.
    The kind is available via the resolved config / `RACECAST_KIND` env in that scope
    (grep how `_oneshot_extra`'s caller knows the profile; if kind isn't in scope, read
    `os.environ.get("RACECAST_KIND")`, consistent with setup-assets). Keep the endurance
    filename byte-identical for endurance.

- [ ] **Step 4: Run — verify pass** + confirm `git diff --stat src/obs/GT_Endurance.json`
  is EMPTY (endurance untouched).
- [ ] **Step 5:** `python3 tools/run-tests.py` + `python3 tools/lint.py` → green.
- [ ] **Step 6: Commit** the changed files:
  `git commit -m "fix(solo): tidy derived collections + kind-aware import filename (#304)"`

---

### Task 6: Visual verification + `cc-settings.png` (CONTROLLER — interactive)

Not a subagent task — needs a running dev build + the repo screenshot skills.

- [ ] Start a local dev Control Center (`racecast ui` from `src/`, on a FREE port —
  `RACECAST_UI_PORT`, scan 8090+; never touch the user's 8089) with the OBS stand-in
  (`tools/obs-sim.py`) so `/api/devices` returns a believable list, per the
  `wiki-screenshots` skill's fake-content recipe.
- [ ] **Visual verification** (`ui-visual-verification`): open General Settings, confirm
  the "Solo devices" section renders on-theme in light + dark, the dropdowns populate,
  and the degraded/hint state looks right; record the marker.
- [ ] Regenerate `src/docs/wiki/images/cc-settings.png` (element/settings-view shot,
  dev-build version badge, framing matching the existing image) via the
  `wiki-screenshots` skill. Tear down the dev build + obs-sim; confirm no lingering
  procs and `git status` clean except the PNG.
- [ ] Commit `src/docs/wiki/images/cc-settings.png`:
  `git commit -m "docs(wiki): refresh Control Center settings screenshot for solo devices (#304)"`

---

### Task 7: Full gates + real run + PR (CONTROLLER)

- [ ] `python3 tools/run-tests.py` (ALL PASS) + `python3 tools/lint.py` (clean) +
  `python3 tools/build.py` (exit 0).
- [ ] Real `racecast device-scan` smoke: if the user's OBS is reachable with the solo
  collection imported, run it and confirm it lists devices + writes `.env`. If OBS is not
  available, confirm the "import the solo collection first" / "OBS not reachable" guide
  prints and nothing is written (do NOT mutate the user's real `.env` — run against a
  scratch `.env` via the `path=`/`--env` seam, or verify the no-op guidance path only).
- [ ] Confirm endurance byte-identical (`git status --porcelain src/obs/GT_Endurance.json`
  empty).
- [ ] Push + PR `--base epic/300-solo-mode` (after user OK); wait for green CI (full
  matrix incl. Windows); squash-merge into the epic (after user OK); update the memory
  progress line.

---

## Self-Review

- **Spec coverage:** enumeration parser + helper (T1) ✓; `.env` upsert safety (T2) ✓;
  CLI device-scan (T3) ✓; Control Center route + provider + dropdown (T4) ✓; deferred
  #303 minors (T5) ✓; visual verify + `cc-settings.png` (T6) ✓; keys reconciled to
  `RACECAST_WEBCAM`/`RACECAST_CAPTURE` ✓; obs_ws↔setup-assets cross-check ✓.
- **Placeholder scan:** the two spots that say "match the file's real helper name / ctx
  builder" (`parse_env_text`, ui_server `_ctx`/`_get`/`_post`, `_oneshot_extra` kind
  scope) are explicit "grep the real name" instructions, not TODOs — the shapes differ
  per file and must be read, not guessed.
- **Type consistency:** `enumerate_device_options(...) -> (list, str)` used identically
  in T1/T3/T4; `env_upsert_data(updates: dict, path=None)` in T2/T3/T4;
  `resolve_device_selection(devices, token) -> (value|None, error|None)` in T3;
  `device_property_name`/`parse_property_items` consistent across T1's tests + impl.
