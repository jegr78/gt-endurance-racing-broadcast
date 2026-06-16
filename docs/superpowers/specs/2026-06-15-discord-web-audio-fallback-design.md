# Discord-web interview audio — browser/PipeWire fallback (Linux without native Discord)

**Status:** design / approved for spike
**Date:** 2026-06-15
**Scope:** lean / spike-grade — make end-of-race interview audio work on Linux
hosts where Discord cannot be installed natively (notably ARM64).

## Problem

Interview audio is the only thing Discord carries in this toolkit: at the end of a
long race the on-air producer joins the league's Discord "Interviews" voice channel,
and OBS captures the audio they hear via a single platform-aware **"Discord Audio
Capture"** source (UUID `0085d4f3-bf43-4aef-9fe4-28cfd3270c7d` in
`src/obs/GT_Endurance.json`, localized per OS by `localize_discord_audio()` in
`src/setup-assets.py`).

On **Linux ARM64** there is no native Discord — the official package is amd64-only —
so the Linux variant (`pipewire_audio_application_capture` with `TargetName: "Discord"`)
has no process to target. That host (the producer's ARM64 Linux VM) therefore has no
path to interview audio.

Discord's **web app** can join a voice channel in a normal browser, and that browser's
audio is capturable. This design wires that browser audio into the existing OBS source
so the rest of the broadcast (panel/Companion mute & volume) keeps working unchanged.

## Why this approach (and not an OBS Browser Source)

The chosen mechanism is **Discord-web in a regular browser + retarget the existing
PipeWire application-capture source to the browser process**. The deciding constraint:

- The panel's and Companion's **mute/volume controls bind to the existing audio
  source** (the "Discord Audio Capture" input). Keeping the **same audio-source type**
  (`pipewire_audio_application_capture`, same UUID) means those controls stay bound and
  nothing in the panel/Companion layer changes.
- An OBS **Browser Source** pointing at the Discord-web channel URL would be a
  *different widget type* with different audio semantics — it would break the existing
  mute/volume logic, and additionally carries fragile CEF login/mic/WebRTC risk. Out of
  scope: too much effort and risk for an interview fallback.

So the change is deliberately small: one new value-form of an existing source, plus the
logic to pick it.

## Design

### 1. New OBS source variant — "Linux web"

`src/setup-assets.py` gains a second Linux realization of the Discord audio source,
alongside the native one. Same source type as native Linux, only the target changes:

```
linux (native): pipewire_audio_application_capture  {"TargetName": "Discord",  "MatchPriorty": 0}
linux (web):    pipewire_audio_application_capture  {"TargetName": <browser>,  "MatchPriorty": 0}
```

- Same source `id`/`versioned_id` and same UUID `0085d4f3…`; only `settings.TargetName`
  differs. The swap still happens in place via `localize_discord_audio()`.
- `<browser>` is the PipeWire match name of the browser running Discord-web (see §3).
- `MatchPriorty: 0` (the plugin's own — misspelled — key, 0 = binary-name match) is
  kept as the starting point; the spike confirms which match value isolates the
  browser's audio node (see §6).
- `tools/tokenize-obs.py` already canonicalizes this source back to the macOS form by
  UUID on re-export; the spike verifies the new TargetName does not leak into the
  committed template.

### 2. Decision: native vs. web

In `src/setup-assets.py`, when the platform is Linux, decide which Linux variant to
emit. Precedence:

1. **`RACECAST_DISCORD_WEB`** machine-`.env` override: `1` forces web, `0` forces
   native. (Read from the env that `load_dotenv()` already populates.)
2. **Auto** (override unset): use **web** when no native Discord is installed,
   otherwise native. The heuristic is generic — "is native Discord present on this
   machine?" — which covers ARM64 automatically (no install possible) and also any
   amd64 host that simply has not installed it. An amd64 host that wants native before
   installing Discord can set `RACECAST_DISCORD_WEB=0`.

Detection stays dependency-light (`setup-assets.py` is one of the four standalone
scripts that must not import `config.py`): a small inline check — a Discord binary on
`PATH` / known install path, with ARM64 (`platform.machine()` ∈ {aarch64, arm64})
falling through to "absent" naturally. Non-Linux platforms are unchanged.

### 3. Browser target (`TargetName`)

The target is **configurable**, not hardcoded:

1. **`RACECAST_DISCORD_WEB_BROWSER`** machine-`.env` value → used verbatim as
   `TargetName`.
2. Else **auto-detect** a running browser (firefox / chromium-family) and use its
   PipeWire match name.
3. Else default **`"Firefox"`** (the project already recommends Firefox for cookies, so
   it is the most likely present).

### 4. Event-day touchpoints (minimal)

- **`src/scripts/event.py` / `src/scripts/preflight.py`:** on a web-variant host,
  replace the "Discord not running / not installed" WARN with an informational note —
  e.g. *"interview audio via Discord-web in the browser — open it and join the voice
  channel manually."* Discord is already non-critical (WARN), so this is a messaging
  change, not a new failure mode. No auto-launch, no channel-URL config.
- **`src/scripts/install_apps.py`:** on ARM64 Linux, soft-skip / note the native
  Discord install (the amd64-only note already exists) and point at the browser
  fallback.

Explicitly **out of scope** (per lean decision): a `racecast` helper that opens the
browser at a Discord channel URL, any new league/profile config for a channel URL, and
any health check that the browser is running. Opening Discord-web and joining voice
stays the producer's manual step — exactly as joining the voice channel already is
today.

### 5. Config surface

Two new **machine-local** `.env` knobs (machine, not league — consistent with the
`config.py` split), documented in `.env.example`:

- `RACECAST_DISCORD_WEB` — `1`/`0` to force, unset = auto.
- `RACECAST_DISCORD_WEB_BROWSER` — PipeWire `TargetName` override (e.g. `Firefox`,
  `Chromium`).

### 6. Spike verification (the real risk, must be done on the ARM64 VM)

This is a fallback whose core mechanism is untested on real hardware; the spike must
confirm, on the VM, before this is considered done:

1. `pipewire_audio_application_capture` actually matches the browser's audio node when
   Discord-web is in a voice call — and which `TargetName` / `MatchPriorty` pair
   isolates **only** the Discord-web audio (not the browser's other tabs).
2. No echo / doubled audio (no overlap with any desktop-audio capture).
3. `tools/tokenize-obs.py` folds the web variant back to the canonical macOS form on
   re-export (committed template stays clean).

If isolating per-tab audio proves impractical, the documented mitigation is a dedicated
browser instance/profile used only for the interview (acceptable because interviews are
a single end-of-race moment).

## Tests (TDD)

`tests/test_discord_audio.py` extends:

- Web-variant shape: correct source `id`, `TargetName` from the resolved browser,
  `MatchPriorty: 0`, UUID unchanged.
- Decision matrix: `RACECAST_DISCORD_WEB` force `1`/`0`; auto with native present vs.
  absent; ARM64 (`platform.machine`) → web under auto.
- Browser resolution: env override wins; default `Firefox` when nothing detected.
- Fold-back / non-Linux platforms unchanged.

Where practical, a small unit check on the event/preflight messaging for a web-variant
host.

## Docs

- Wiki `src/docs/wiki/OBS-Setup.md` (Linux section) and
  `src/docs/wiki/If-something-goes-wrong.md`: document the browser fallback, the two
  `.env` knobs, and the manual "open Discord-web + join voice" step.
- **No UI screenshots required** — no Control Center / Director Panel / Companion
  surface changes.

## Non-goals

- OBS Browser Source for Discord (breaks panel/Companion mute-volume; CEF login/mic
  risk).
- Auto-launching the browser / Discord channel from `racecast event start`.
- Any league/profile-level Discord configuration.
- Making interview audio broadcast-critical — it stays optional/non-critical.
