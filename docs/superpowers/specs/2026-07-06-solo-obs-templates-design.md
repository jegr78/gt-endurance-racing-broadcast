# Solo OBS scene-collection templates + device tokens

Epic: #300 (Solo mode). Issue: **#303**. Builds on the solo relay foundation
(`2026-07-06-solo-relay-mode-design.md`, #302 merged). Feeds the device-enumeration
sub-issue #304 and the kind-conditional UI #307.

## Context

Endurance ships one tokenized OBS scene collection, `src/obs/GT_Endurance.json`
(a real, proven-importable OBS export). `src/setup-assets.py` localizes it for the
machine — replacing `__RACECAST_GRAPHICS__` / `__RACECAST_MEDIA__` tokens with real
paths, swapping the Discord audio source to the platform variant
(`localize_discord_audio`), and naming the collection from the active profile's
`OBS_COLLECTION`. The endurance "main" scene is `Stint`: the relay feeds
`Feed A`/`Feed B`/`Feed POV` (ffmpeg sources on ports 53001/53002/53003), the
relay-served `HUD Overlay` browser source (`http://127.0.0.1:8088/hud`), an `Overlay`
image, all sheet-driven graphics (Standings/Schedule/Results/Weather/Flags), and a
nested `Discord` scene.

Solo mode (`kind = solo`, #301) runs a **local capture card + webcam** as the main
program instead of the A/B stint feeds, and keeps the **optional POV feed** (the
independent third relay feed on port 53003 — #302 decision: POV-from-external-stream
is in solo from the start). Solo therefore needs its own scene collection(s): the
endurance `Stint`/`Splitscreen` A/B layout does not apply.

## The key insight: derive, don't hand-author

An importable OBS collection is a large export artifact (UUIDs, `versioned_id`,
per-item transforms). Hand-writing one from scratch is error-prone. So the two solo
templates are **derived from the proven `GT_Endurance.json`** by a maintainer script,
guaranteeing OBS validity and keeping them regenerable when endurance changes — the
same maintainer-tool model as `tools/tokenize-obs.py`. Both the script and its two
committed output JSONs live in the repo; `setup-assets.py` reads the JSONs.

## Design

### A. Two templates, structurally identical for now

Committed under `src/obs/`:

- `GT_Solo_Commentary.json` — a solo commentator of one race.
- `GT_Solo_POV.json` — a driver's POV stream.

Both are **structurally identical today** (decision: start equal). The intended
divergence is sequenced later: **#324** adds the GT7 telemetry-driven POV HUD to the
POV template; per-broadcast framing differences are an operator's live OBS edit. Two
separate files (not one shared) let them diverge without a migration, and the profile
`--template` (#301) already selects one per profile.

### B. Scene set (derived from endurance)

Starting from `GT_Endurance.json`:

**Kept unchanged** (already useful in solo, no A/B coupling): `Standby`, `Intro`,
`Outro`, `Discord`, `Intermission`, `Interview` (Discord + Post-Race-Interviews — a
solo commentator does interviews too).

**Dropped**: `Stint`, `Splitscreen`, and the `Feed A` / `Feed B` ffmpeg sources
(the A/B ping-pong). **`Feed POV` is NOT dropped** — the relay keeps the POV feed in
solo, so OBS keeps the source.

**New scenes** (the two device captures are their **own scenes**, mirroring the
existing `Discord` scene-wraps-a-source pattern, so they can be nested into `Program`
*and* reused elsewhere — e.g. a webcam corner on `Intermission`):

- `Solo Capture` (scene) → one capture-card device source, id-token
  `__RACECAST_CAPTURE__`.
- `Solo Webcam` (scene) → one webcam device source, id-token `__RACECAST_WEBCAM__`.

**New `Program` scene** (replaces `Stint`; the default program layout — a real POV
broadcast layout, see the reference the user supplied: facecam bottom-left, timing
top-left, telemetry HUD bottom-right):

- `Solo Capture` (nested scene) — fullscreen background.
- `Feed POV` (ffmpeg source, port 53003) — PiP, **position/size from the profile
  overlay CSS `#pov` box**, so the existing `apply_pov_transform` sync keeps working
  in solo unchanged (it targets the item named `Feed POV` anywhere in the tree).
- `Solo Webcam` (nested scene) — PiP, default **bottom-left** corner.
- `HUD Overlay` (browser source → `/hud`), `Overlay` (image).
- All sheet-driven graphics (Standings, Schedule, Race/Quali Results, the three
  Weather overlays, the five Flags) + `Standby Cover` — carried over. They
  **self-hide** to a transparent placeholder when no asset is configured (the
  existing `placeholders.fill_missing` contract), so a solo user who never uploads
  Schedule/Weather sees nothing there. *(Design choice: "rich" — maximum reuse; the
  operator toggles what they don't want via the Director Panel / Companion. Trim to a
  curated/lean set only if the user requests it at spec review.)*
- `Discord` (nested scene) — the interview/co-host audio, as in endurance.

### C. Device-source per-OS localization (mirrors `localize_discord_audio`)

A capture/webcam device source's **type** is platform-specific, exactly like the
Discord audio source. The committed templates carry the **macOS** form (like the
committed Discord audio source); `setup-assets.py` swaps it per platform at localize
time. New pure helper in `setup-assets.py`:

```
DEVICE_SOURCES = (
    # (scene/source name, env var, per-OS settings key holding the device id)
    {"name": "Solo Capture", "env": "RACECAST_CAPTURE", "token": "__RACECAST_CAPTURE__"},
    {"name": "Solo Webcam",  "env": "RACECAST_WEBCAM",  "token": "__RACECAST_WEBCAM__"},
)
DEVICE_VARIANTS = {
    "darwin": ("av_capture_input", "device"),      # device UUID
    "win":    ("dshow_input",      "video_device_id"),  # "Name:\\?\\usb#..."
    "linux":  ("v4l2_input",       "device_id"),   # /dev/videoN
}

def localize_device_sources(collection, platform, env) -> list[str]:
    """For each DEVICE_SOURCES entry, set the matching source's id/versioned_id to
    the platform variant and write env[<env var>] (or the token if unset) into the
    per-OS device-id settings key. Returns the names whose device is UNSET (empty
    env) so the caller can WARN. Never raises (same best-effort contract as
    localize_discord_audio); unknown platform -> keeps the macOS form, warns."""
```

- **Empty device ⇒ warning, not error** (identical contract to a missing graphic):
  the source keeps its token / an empty device id, OBS shows black until a device is
  chosen. **#304** automates discovery (OBS-WS enumeration → `.env`); until then the
  operator sets `RACECAST_WEBCAM` / `RACECAST_CAPTURE` in `.env` by hand.
- The two new machine keys are documented in `.env.example` (`RACECAST_WEBCAM`,
  `RACECAST_CAPTURE`) — machine-local, like `RACECAST_OBS_WS_PASSWORD`.

### D. `setup-assets.py` becomes kind-aware

Template selection currently hardcodes the endurance file. New behavior:

- New args `--kind` (default `os.environ["RACECAST_KIND"]` → `endurance`) and
  `--template` (default `os.environ["RACECAST_TEMPLATE"]`), resolving the base name:
  - `endurance` → `GT_Endurance`
  - `solo` + `commentary` → `GT_Solo_Commentary`
  - `solo` + `pov` → `GT_Solo_POV`
  - solo with unknown/blank template → default to `commentary`.
- The existing `.template.json` → `.json` fallback probe is applied to the resolved
  base (so both the built package and the repo work).
- `localize_device_sources` runs only when the collection actually contains the
  device tokens (guarded like the other token blocks), so endurance is untouched.
- `src/racecast.py` `setup_cmd` passes `--kind`/`--template` from the resolved
  `ResolvedConfig` (`rc.kind`, `rc.template`). Pure selection helper
  `resolve_template_base(kind, template)` is unit-testable.

### E. Kind-dependent collection name

- New constant in `config.py` next to `PRODUCT_COLLECTION_PREFIX`:
  `SOLO_COLLECTION_PREFIX = "GT Racing Solo"`.
- `resolve_config`: when `kind == "solo"` and the profile sets no explicit
  `OBS_COLLECTION`, default to `f"{SOLO_COLLECTION_PREFIX} — {name}"`
  (e.g. `GT Racing Solo — myleague`). The **endurance branch is unchanged**
  (`GT Endurance Racing — <name>`) — byte-identical, and existing installs keep their
  collection name. (#308's rebrand later unifies both under a `GT Racing [MODE]`
  scheme; that is out of scope here.)
- `obs_ws.py` keeps its endurance scene/source constants (`STINT_SCENE`,
  `FEED_SOURCES`, `POV_SOURCE`, `EXPECTED_SCENE_COLLECTION`) **endurance-only**. Solo
  never drives the A/B OBS-control paths (the relay is feed-less for A/B; #307 gates
  the panel controls). The collection *name* used by `event start`'s auto-switch and
  `event status` already comes from the resolved `rc.obs_collection`, so it is
  kind-correct once (E) sets the solo default — no `obs_ws` change needed for the
  switch. `POV_SOURCE` ("Feed POV") stays valid because solo keeps that source.

### F. Build integration

`tools/build.py` renames the tokenized `GT_Endurance.json` →
`GT_Endurance.template.json` in the shipped package and re-strips defensively. Extend
this to the two solo files (`GT_Solo_Commentary.json`, `GT_Solo_POV.json` →
`*.template.json`). The build verify step already asserts no secrets / tokens present;
it must cover the solo templates too.

### G. Derivation script

`tools/derive-solo-templates.py` (maintainer-only, not shipped): reads
`src/obs/GT_Endurance.json`, applies the B transforms deterministically (drop
Stint/Splitscreen + Feed A/B sources; add `Solo Capture`/`Solo Webcam` device
scenes with the macOS device form + tokens; build the `Program` scene), and writes
the two `src/obs/GT_Solo_*.json`. Re-runnable when endurance changes. Committed
alongside its outputs. New UUIDs for the added sources are **fixed constants** in the
script (deterministic — no `uuid4()`, which would churn the committed JSON on every
re-run; fixed ids keep the diff stable and reviewable).

## Testing (purely additive — nothing disabled)

Hard constraint (whole epic): endurance path byte-identical; no existing test
commented out. `python3 tools/run-tests.py` stays green.

- `tests/test_setup.py` (new cases):
  - `resolve_template_base`: `("endurance", "")→GT_Endurance`,
    `("solo","commentary")→GT_Solo_Commentary`, `("solo","pov")→GT_Solo_POV`,
    `("solo","")→GT_Solo_Commentary`.
  - `localize_device_sources`: on a fixture collection with the two device tokens,
    each platform (`darwin`/`win`/`linux`) sets the right source `id` and writes the
    env device id into the right settings key; an **empty** env value is returned in
    the "unset" list (⇒ warning) and does not raise; unknown platform keeps the macOS
    form.
  - The endurance path (`localize_discord_audio`, token replacement) is unchanged
    (existing cases stay green).
- `tests/test_config.py`: `kind == "solo"` with no explicit `OBS_COLLECTION` →
  `GT Racing Solo — <name>`; endurance default unchanged.
- `tests/test_build.py`: both `GT_Solo_*.json` are present, tokenized (contain the
  device/graphics/media tokens, **no** real device ids / secrets), and rename to
  `.template.json` in the package.
- A lightweight structural check on the two committed solo JSONs: they parse, contain
  the `Program`/`Solo Capture`/`Solo Webcam` scenes, retain `Feed POV`, and do **not**
  contain `Feed A`/`Feed B`/`Stint`/`Splitscreen`.

## Non-goals / boundaries

- Device **enumeration** (OBS-WS list of cameras/capture cards) → `.env` population —
  **#304**. #303 only injects whatever is already in `.env` and warns when empty.
- Kind-conditional Director-Panel / Control-Center UI — **#307**.
- Rebrand to "GT Racing Broadcast" / unified `GT Racing [MODE]` collection naming —
  **#308**.
- GT7 UDP telemetry POV HUD — **#324**.

## Success criteria

- `racecast --profile <solo-commentary> setup` writes an importable collection named
  `GT Racing Solo — <name>` whose `Program` scene has `Solo Capture` (full),
  `Feed POV` (PiP, CSS box), `Solo Webcam` (PiP, bottom-left), the HUD, graphics, and
  the Discord/Interview scenes; the device sources carry this platform's source type;
  an unset `RACECAST_WEBCAM`/`RACECAST_CAPTURE` prints a warning (no failure).
- The endurance `setup` output is byte-identical to before.
- The full test suite stays green with no test disabled; `tools/build.py` exits 0 with
  the two solo templates verified.
