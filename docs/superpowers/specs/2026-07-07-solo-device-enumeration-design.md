# Solo device enumeration (OBS-WS) → `.env`

Epic: #300 (Solo mode). Issue: **#304**. Builds on #303 (the
`__RACECAST_WEBCAM__`/`__RACECAST_CAPTURE__` tokens + `localize_device_sources`,
which reads `RACECAST_WEBCAM`/`RACECAST_CAPTURE` from `.env`). Makes choosing the
local webcam/capture-card device convenient: enumerate the real devices via
OBS-WebSocket, persist the choice in `.env`, and let #303's token approach bake it in
on the next `setup-assets` export.

## Context

#303 tokenized the solo `Solo Capture Device` / `Solo Webcam Device` sources.
`setup-assets.localize_device_sources` swaps each to the platform source type
(`av_capture_input` / `dshow_input` / `v4l2_input`) and injects the device id from
`RACECAST_CAPTURE` / `RACECAST_WEBCAM` (empty ⇒ a WARNING, OBS shows black). Today the
operator must find and type the raw device id by hand (or pick it directly in OBS).
#304 automates discovery.

OBS-WebSocket v5 exposes the exact device list OBS itself writes into a collection via
`GetInputPropertiesListPropertyItems(inputName, propertyName)`, which returns the
dropdown options for a property: `propertyItems: [{itemName, itemEnabled,
itemValue}]`. `itemValue` is exactly the id that belongs in the source settings, so
enumeration + injection cannot drift. `src/scripts/obs_ws.py` already speaks v5
(`Session.request`, `_connect`, best-effort helpers like `release_feed_inputs`).

**One video-device list per platform.** On macOS every video capture is
`av_capture_input`; on Windows every one is `dshow_input`. So a single query against
either solo input returns the full list of video devices; the operator just assigns
which entry is the webcam and which is the capture card. (ffmpeg device listing is
deliberately NOT used — its ids differ from what OBS writes.)

## Key decisions

1. **`.env` keys are `RACECAST_WEBCAM` / `RACECAST_CAPTURE`** — the exact keys #303's
   `localize_device_sources` reads. The issue's `_DEVICE`-suffixed names are NOT used
   (that would break the just-shipped injection). Machine-local, so `.env` is the
   right layer (like `RACECAST_OBS_WS_PASSWORD`), never the profile (which travels via
   `profile export`). Already documented in `.env.example` from #303.
2. **Enumerate the real inputs (import first).** Query the property items of the
   existing `Solo Capture Device` input. Requires the solo collection to be imported in
   OBS (its inputs must exist). If the input is absent, surface a clear instruction
   ("import the solo collection first: `racecast setup` → OBS Scene Collection →
   Import") rather than probing. Natural loop: import (empty devices) → scan → write
   `.env` → re-run `setup` to bake in.
3. **Two surfaces.** A CLI `racecast device-scan` (honors the #303 WARNING that already
   points at it) AND a Control Center → General Settings dropdown (the documented,
   primary path per the Control-Center-first convention).

## Design

### Correctness: the `.env` write is an UPSERT, not a bare `merge_env_text`

`merge_env_text` / `env_write_data` treat their `entries` as the **complete** desired
key set — any existing real `RACECAST_*` key NOT in the passed list is **dropped** (this
is correct for the full-text `.env` editor, which always sends every key). So a device
write must **not** call the writer with only the two device keys — that would delete
`RACECAST_OBS_WS_PASSWORD` and every other machine knob. Both surfaces use a shared
**upsert** helper `env_upsert_data(updates: dict, path=None)`: read the current machine
`.env` into entries, overlay only the `updates` keys, then call `env_write_data` with
the **full merged** entry set (preserving comments + all other keys). This helper is the
single write path for both the CLI and the route, and is unit-tested against a fixture
`.env` proving unrelated keys survive.

### A. OBS-WS enumeration (`src/scripts/obs_ws.py`)

- **Pure parser** `parse_property_items(payload) -> list[dict]`: from a
  `GetInputPropertiesListPropertyItems` response, return
  `[{"name": itemName, "value": itemValue, "enabled": bool}]`, skipping items with a
  null/empty `itemValue`. Unit-tested (like `parse_obs_stats`).
- **Per-OS property name** `device_property_name(platform) -> str | None`: macOS
  `"device"`, Windows `"video_device_id"`, Linux `"device_id"` — the SAME mapping as
  `setup-assets.DEVICE_VARIANTS`. To prevent drift, a test cross-checks the two agree
  (the `STREAMLINK_TWITCH` duplication precedent: pinned by a test, not shared import,
  so `obs_ws` stays importable without pulling `setup-assets`).
- **Network helper** `enumerate_device_options(input_name, property_name, host, port,
  password, timeout) -> (items, note)`: connect (`_connect`), request
  `GetInputPropertiesListPropertyItems`, parse, return `(items, "")` or `([], note)` on
  any failure (OBS unreachable, input/property absent) — best-effort, never raises,
  mirroring `release_feed_inputs`. The note distinguishes "OBS unreachable" from "input
  not found (import the solo collection first)".

### B. CLI `racecast device-scan` (`src/racecast.py`)

- Resolves the OBS-WS target (host/port/password auto-discovered, as the existing
  `/obs/*` path does) and calls `enumerate_device_options("Solo Capture Device",
  device_property_name(sys.platform), …)`.
- **List** the devices numbered. Then either:
  - **interactive**: prompt for the webcam index and the capture index (blank = skip /
    leave unchanged), or
  - **non-interactive flags** `--webcam <id|index>` / `--capture <id|index>` (id
    substring or list index) for scripted/headless use.
- Resolve the selection to the device `value` and write `RACECAST_WEBCAM` /
  `RACECAST_CAPTURE` to `.env` via `env_upsert_data` (the shared upsert helper — see
  Correctness above). Only the keys the user set are written; the
  other is left untouched.
- If the input is absent → print the "import the solo collection first" guide and exit
  non-zero (nothing written). If OBS is unreachable → the same best-effort note.
- On success, print a reminder: re-run `racecast setup` to bake the choice into the
  collection.
- Pure decision helpers (index/id resolution, which keys to write) are unit-testable
  without a live OBS.

### C. Control Center → General Settings (`src/ui/ui_server.py` + `control-center.html`)

- **Route** `GET /api/devices` → `{"ok": bool, "devices": [{"name","value"}], "note":
  str}` — enumerate via `enumerate_device_options`. Reuses the OBS-WS resolution the UI
  already has for other OBS calls.
- **UI** in the General Settings view (where the `.env` editor + font library live): a
  small "Solo devices" section with two dropdowns (Webcam, Capture) populated from
  `/api/devices`, plus a Save that writes `RACECAST_WEBCAM` / `RACECAST_CAPTURE` via a
  dedicated `POST /api/devices/select` calling `env_upsert_data` (the shared upsert
  helper — see Correctness above; the full-text `/api/env` editor is left untouched). The currently saved values are
  pre-selected from the loaded `.env`.
- **Degraded states** (never an error): OBS unreachable or the solo input absent →
  the dropdowns are disabled with a one-line hint ("Start OBS with the solo collection
  imported to list devices, or set RACECAST_CAPTURE/WEBCAM in the .env editor above").
  The section self-explains; it does not block the rest of General Settings.
- **UI surface change → visual verification + wiki screenshot.** Per CLAUDE.md, the
  General Settings view screenshot `src/docs/wiki/images/cc-settings.png` becomes stale
  and MUST be regenerated (via the `wiki-screenshots` skill, local dev build) and
  committed in this change, after a render-and-eyeball visual verification
  (`ui-visual-verification`).

### D. Deferred #303 minor cleanups (folded in)

The #303 final review deferred three harmless minors to this issue:

- `tools/derive-solo-templates.py`: set the committed collection `name` to
  `"GT Racing Solo"` (currently inherits `"GT Endurance Racing"`; harmless since
  `setup-assets` overrides at localize, but the committed artifact should be
  self-consistent), and **prune the now-orphaned `Split HUD` group + its
  `Splitscreen Labels` leaf** (the `Splitscreen` scene was dropped but the top-level
  `groups` array was not pruned). Regenerate both `src/obs/GT_Solo_*.json`
  deterministically.
- `src/racecast.py`: the solo `setup` default `--out` becomes kind-aware
  (`GT_Solo.import.json` for a solo profile instead of the hardcoded
  `GT_Endurance.import.json`). Cosmetic (OBS uses the internal `name`), but tidy.

These stay small and are clearly separate commits within the PR.

## Testing (additive — nothing disabled)

- `tests/test_obsws.py`: `parse_property_items` (normal, empty/null-value filtering,
  malformed payload → `[]`); `device_property_name` per platform; the cross-check that
  it agrees with `setup-assets.DEVICE_VARIANTS`.
- `tests/test_racecast.py`: `device-scan` selection resolution (index vs id-substring,
  skip/leave-unchanged, which `.env` keys get written) — pure, no live OBS; kind-aware
  `setup` `--out` default.
- `tests/test_ui_server.py`: `GET /api/devices` shape (mocked/injected enumerator) +
  the device-select write path.
- Enumeration returns only device NAMES/ids → written only to the gitignored `.env`;
  no secret/machine-path enters git. Tests use fixtures, no real device ids, no live
  OBS.

## Non-goals / boundaries

- No ffmpeg device listing (format mismatch — rejected in the issue).
- No temp-input probe (decision: enumerate the real inputs; import first).
- Kind-conditional Director-Panel/Control-Center affordances beyond this dropdown —
  **#307**. Rebrand — **#308**. GT7 telemetry POV HUD — **#324**.

## Success criteria

- With the solo collection imported in OBS: `racecast device-scan` lists the machine's
  video devices and, on selection (interactive or `--webcam/--capture`), writes
  `RACECAST_WEBCAM`/`RACECAST_CAPTURE` to `.env`; re-running `racecast setup` bakes them
  into the collection (no more device WARNING).
- Control Center → General Settings shows the two device dropdowns from `/api/devices`,
  and saving persists to `.env`; OBS-unreachable/absent-input degrade to a hint, never
  an error.
- `cc-settings.png` regenerated; endurance path unaffected; full suite green, no test
  disabled.
