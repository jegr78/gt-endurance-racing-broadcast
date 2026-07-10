# Solo device enumeration — standalone (no imported collection)

Epic: #300 (Solo mode). Supersedes the enumeration mechanism of
[#304](2026-07-07-solo-device-enumeration-design.md). Everything else in #304 stands
(the `.env` keys, the `env_upsert_data` write path, the two surfaces, the deferred
cleanups). This design **replaces only how the device list is obtained**: from
"query an already-imported input" to "probe OBS with a throwaway scene + input", so the
list appears **without any solo collection imported** — exactly how OBS itself shows
devices when you manually add a capture source.

## Why this supersedes #304's enumeration

#304 chose *"enumerate the real inputs (import first)"* and listed
*"No temp-input probe"* as a non-goal (§Non-goals, line 158). Live UAT on 2026-07-09
showed this fails the operator's expectation: with the demo (non-solo) collection
active, `GET /api/devices` returns
`note: "input 'Solo Capture Device' not found — import the solo collection first"` and
the dropdowns stay empty. The operator's verbatim expectation:

> "dass die Geräteliste auch ohne passende Szene ermittelt werden kann, so wie das OBS
> selbst macht, wenn man manuell eine solche Quelle hinzufügt"

The temp-probe delivers exactly that. **Decision: reverse the non-goal.** No
import-first path is kept — the probe is strictly better (it needs nothing pre-imported)
and a dead fallback would only be maintenance ballast (confirmed with the user
2026-07-09: "kein Fallback").

## Proven feasibility

`scratchpad/devscan_probe.py` ran against a live OBS on this macOS machine and returned
the exact expected devices with **no solo collection imported**, then cleaned up:

- `GetInputKindList` → video kind `av_capture_input_v2`, audio kind
  `coreaudio_input_capture` (note: **`_v2`** — #304's assumed `av_capture_input` is a
  substring of it, so substring matching is required; an exact-string match would miss
  it).
- `CreateScene` (throwaway) → `CreateInput(sceneItemEnabled=False)` of that kind →
  `GetInputPropertiesListPropertyItems` on property `device` (video) /
  `device_id` (audio) → the real device dropdown (FaceTime HD Camera, MacBook Air
  Microphone, …) → `RemoveInput` + `RemoveScene`.

The current program scene is never switched; the temp input is created disabled.

## Design

### A. OBS-WS enumeration (`src/scripts/obs_ws.py`)

**Retained (unchanged):** `parse_property_items` and
`device_property_name(platform, kind="video")` — which **already** returns the video
property per OS (macOS `"device"`, Windows `"video_device_id"`, Linux `"device_id"`,
cross-checked against `setup-assets.DEVICE_VARIANTS`) **and** the audio property for
`kind="audio"` (cross-checked against `setup-assets.AUDIO_VARIANTS`; the `kind` arg
landed in #307). The probe reuses it verbatim — no change to this function.

**New pure helper** `pick_input_kind(kind_list, matchers) -> str | None`
- `matchers` is an ordered list of substrings; return the first kind in `kind_list`
  whose lowercased value contains a matcher, honoring **matcher order first, then
  `kind_list` order** (so a preferred matcher wins even if a less-preferred kind appears
  earlier in the OBS list). `None` if nothing matches.
- Unit-tested: finds `av_capture_input_v2` from matcher `av_capture_input`; picks by
  matcher priority; empty/no-match → `None`.

Two module-level matcher constants (documented as the platform capture kinds):
- `VIDEO_INPUT_KIND_MATCHERS = ("av_capture_input", "dshow_input", "v4l2_input")`
- `AUDIO_INPUT_KIND_MATCHERS = ("coreaudio_input_capture", "wasapi_input_capture", "pulse_input_capture")`

**New network helper** `probe_device_options(host="127.0.0.1", port=None,
password=None, timeout=2.0) -> {"devices": [...], "note": str, "mic": [...],
"mic_note": str}`
- One `_connect`. On failure → both lists `[]`, both notes = the connect note.
- `GetInputKindList` → `kinds`. Compute `vid_kind = pick_input_kind(kinds,
  VIDEO_INPUT_KIND_MATCHERS)`, `aud_kind = pick_input_kind(kinds,
  AUDIO_INPUT_KIND_MATCHERS)`.
- `CreateScene(PROBE_SCENE_NAME)` **once**. `PROBE_SCENE_NAME =
  "__racecast_device_probe__"`. Guard against a stale scene from a crashed prior run:
  `RemoveScene` first (ignore any error), then `CreateScene`.
- For video (if `vid_kind`): `CreateInput(sceneName=PROBE_SCENE_NAME,
  inputName=PROBE_VIDEO_INPUT, inputKind=vid_kind, sceneItemEnabled=False)`, then
  `GetInputPropertiesListPropertyItems(PROBE_VIDEO_INPUT,
  device_property_name(sys.platform))` → `parse_property_items` → `devices`. No
  `vid_kind` → `devices=[]`, `note="no video capture input kind in this OBS"`.
- For audio (if `aud_kind`): same with `PROBE_MIC_INPUT`, property
  `device_property_name(sys.platform, kind="audio")` → `mic`.
- **Cleanup in `finally`**: `RemoveInput` each created input, then
  `RemoveScene(PROBE_SCENE_NAME)`, each guarded (ignore errors), then `session.close()`.
  Cleanup runs on **every** exit path — including when a property read raises. This
  guarantee is the central test.
- Best-effort contract identical to `release_feed_inputs`: **never raises**; a note is
  populated on any degraded path.

`PROBE_VIDEO_INPUT = "__racecast_probe_video__"`, `PROBE_MIC_INPUT =
"__racecast_probe_mic__"`.

No per-platform property **fallback** list is added — `device_property_name` is known and
deterministic; if a future OBS renames a property the note surfaces an empty list, not a
crash (best-effort).

`enumerate_device_options` (the #304 named-input reader) is **removed** — it has exactly
two callers (the CC route and the CLI), both migrated below, and keeping a dead
import-first path is the ballast the user rejected.

### B. Integration — Control Center + CLI

Both surfaces from #304 stay; only their call target changes.

- **`devices_enumerate_data()` (`src/racecast.py`)** now calls `probe_device_options(...)`
  and maps its result to the existing response shape the route already returns
  (`{ok, devices, note, mic, mic_note}` — the mic fields already exist per #307's
  commentary-mic work). `DEVICE_SCAN_INPUT_NAME` / `DEVICE_SCAN_MIC_INPUT_NAME` become
  unused and are removed.
- **CLI `racecast device-scan`** resolves the OBS-WS target as today and calls
  `probe_device_options(...)`; the rest (numbered list, interactive prompt /
  `--webcam`/`--capture`/`--mic` selection, `env_upsert_data` write, "re-run `racecast
  setup`" reminder) is unchanged. The pure selection helpers are untouched.

### C. UX copy

The "import the solo collection first" hint is obsolete. New degraded states:
- OBS unreachable → "Start OBS (with obs-websocket enabled) to list devices, or set
  RACECAST_WEBCAM/RACECAST_CAPTURE in the .env editor above."
- No capture kind found (rare) → the note from `probe_device_options`.

On the happy path the dropdowns populate directly, no collection needed. The
`#dev-hint` element in `control-center.html` shows `d.note` when present, else the OBS
hint; the empty-because-not-imported message is deleted.

## Testing (additive — nothing disabled)

- `tests/test_obsws.py`
  - `pick_input_kind`: finds `av_capture_input_v2` via the `av_capture_input` matcher;
    matcher-priority ordering; empty list and no-match → `None`.
  - `device_property_name` video + audio cross-checks (`DEVICE_VARIANTS` /
    `AUDIO_VARIANTS`) are pre-existing (#307) and stay green — no new assertion needed.
  - `probe_device_options` against a **fake session** (records every `request` call,
    returns canned `GetInputKindList` + property payloads): asserts it (1) creates the
    scene and a disabled input of the picked kind, (2) reads the right property per
    stream, (3) returns the parsed devices, and (4) **always** issues `RemoveInput` +
    `RemoveScene` — including a variant where the property read raises, proving cleanup.
    A `_connect` returning `(None, note)` → empty lists + note, no scene created.
- `tests/test_racecast.py`: `devices_enumerate_data()` maps a probe result to the route
  shape (injected/patched `probe_device_options`). Existing `device-scan` selection tests
  unchanged.
- `tests/test_ui_server.py`: `GET /api/devices` shape via the injected enumerator —
  unchanged contract, new source.
- No live OBS in CI; the macOS live path is validated manually (the probe already ran).

## Non-goals / boundaries

- Windows (`dshow_input` / `wasapi_input_capture`) and Linux (`v4l2_input` /
  `pulse_input_capture`) go through the **same** `GetInputKindList` + `pick_input_kind` +
  `device_property_name` mechanism, but are **not** live-tested here (only macOS is). This
  is the same cross-platform assumption #304 already carried; documented as a known risk.
- No ffmpeg device listing (format mismatch — rejected in #304).
- No import-first fallback (the user rejected keeping one).
- The `.env` write path, keys (`RACECAST_WEBCAM`/`RACECAST_CAPTURE`/mic), and the
  `env_upsert_data` upsert semantics are exactly as #304 — unchanged here.

## Success criteria

- With **no** solo collection imported (e.g. the demo collection active), Control Center
  → General Settings lists the machine's video **and** audio devices from `/api/devices`,
  and `racecast device-scan` lists them too; a selection persists to `.env` via
  `env_upsert_data`.
- The throwaway scene/input never appears in the program output and is always removed,
  even on a mid-probe error.
- OBS-unreachable / no-kind degrade to a one-line hint, never an error.
- Full suite green; no test disabled; `cc-settings.png` refreshed if the General
  Settings view changed visibly (copy-only change → re-verify per
  `ui-visual-verification`).
