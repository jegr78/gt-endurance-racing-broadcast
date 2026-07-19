# Trailer Video — Design Spec

Date: 2026-07-19
Status: Approved (design); implementation plan pending

## Goal

Add a third director-controllable broadcast clip — a **Trailer** — that behaves
exactly like the existing **Intro** / **Outro** videos (see
`2026-06-04-intro-outro-videos-design.md`). The Trailer is a promotional/waiting
clip that:

- plays full-screen **with its own audio** on the broadcast,
- **loops** until the director switches away,
- is maintainable per league via the Google **Sheet Assets tab** (like Intro/Outro),
- shows up as a dedicated **OBS scene** (`Trailer`),
- is selectable from both the **Director Panel** (a PGM macro next to INTRO/OUTRO)
  and a **Companion / Web Buttons** button (Page 1, next to INTRO/OUTRO).

This is a deliberately additive, pattern-matching feature: the Trailer threads
through the same machinery as Intro/Outro, changing only the handful of spots that
are hard-coded to the intro/outro pair.

## Decisions (from brainstorming)

- **Playback:** loop the clip with its own audio, `restart_on_activate` from frame 0
  — 1:1 with the Intro scene. The director takes it live and later leaves it; no
  auto-cut on clip end.
- **Naming (confirmed with user):**

  | Aspect | Value |
  |---|---|
  | Sheet **Assets** label | `Trailer Video` |
  | Profile key (`profile.env`) | `TRAILER_URL=` |
  | Env override | `RACECAST_TRAILER_URL` |
  | File | `runtime/<profile>/media/trailer.mp4` |
  | OBS scene / source | `Trailer` / `Trailer Video` |
  | Panel / Companion label | `TRAILER` |

- **Sourcing:** identical to Intro/Outro — `get-media.py` resolves the URL
  (CLI > `RACECAST_TRAILER_URL` env > Sheet Assets tab) and downloads a local MP4;
  played as a local OBS media source. No relay streaming, no browser source.
- **Control surfaces:** Director Panel PGM macro **and** Companion button, matching
  how Intro/Outro are exposed. The Companion button uses the native OBS-WebSocket
  `set_scene` action (no relay call), like INTRO/OUTRO.

## Non-goals (YAGNI)

- No new relay endpoints — the generic `/obs/scene` handler already switches to any
  scene by name; the Trailer scene works through it unchanged.
- No auto-cut to a live scene at clip end (director switches manually; clip loops).
- No changes to `setup-assets.py`, `placeholders.py`, or `tools/tokenize-obs.py` —
  these are already template/token-driven and pick up a new
  `__RACECAST_MEDIA__/trailer.mp4` reference automatically.
- Not adding Trailer to the raw "Switch scene" bus (`CONFIG.scenes`) — Intro/Outro
  live only on the PGM-macro bus, and the Trailer mirrors that.

## Architecture

The Trailer reuses the entire Intro/Outro pipeline. Nothing structural is new; the
change is threading one more media key through the existing plumbing.

```
Google Sheet (Assets tab: "Trailer Video" label cell)
        │  gviz CSV (existing mechanism)
        ▼
src/relay/get-media.py ──yt-dlp──▶  runtime/<profile>/media/trailer.mp4
        │                                   │
        │ (racecast media, --out            │ (setup-assets.py resolves
        │  runtime/<profile>/media)         │  __RACECAST_MEDIA__ → abs path,
        ▼                                   │  placeholder if clip absent)
   TRAILER_URL (profile.env)                ▼
   → RACECAST_TRAILER_URL (injected) OBS scene "Trailer"
                                       (ffmpeg_source, looping, own audio)
                                            ▲
                                            │ set_scene "Trailer"
                          ┌─────────────────┴──────────────────┐
                  Director Panel PGM macro TRAILER      Companion PAGE 1 button
                  (POST /obs/scene → relay → OBS)       (native OBS-WS set_scene)
```

## Detailed component design

Grouped as **must-edit** (hard-coded to intro/outro today) and **already-generic**
(no change). File:line references are the current state from the codebase map.

### Must edit

#### 1. `src/relay/get-media.py` — asset download

- `MEDIA_LABELS` (≈line 50): add `"trailer video": "trailer"`.
- `--which` expansion (`both`/`all` set) and the `cli` dict (≈lines 355–385): add
  `trailer` so `all` includes it and `--trailer-url` maps in. Add the
  `--trailer-url` CLI flag (≈lines 365–366).
- The env-fetch gate, placeholder seed/reset (`seed_missing_media` /
  `reset_unlinked_media`), and the download command already iterate `which`, so they
  generalise once `trailer` is in the set — no per-key code.
- Writes `trailer.mp4` alongside `intro.mp4`/`outro.mp4`.

#### 2. `src/relay/get-graphics.py` — sync copy (skip-list)

- `get-graphics.py` keeps its **own** `MEDIA_LABELS` (≈line 123) to skip
  video/music rows during graphics download, with an explicit "KEEP IN SYNC" comment.
  Add `"trailer video"` here too, otherwise the Trailer row is misread as a
  broadcast graphic and downloaded as a PNG.

#### 3. `src/scripts/config.py` — resolver

- `ResolvedConfig` (≈lines 156–157): add `trailer_url: str = ""`.
- Populate from `profile.env` (≈lines 212–213): `trailer_url=prof.get("TRAILER_URL", "")`.

#### 4. `src/racecast.py` — profile → child env injection

- `_profile_env_vars(rc)` (≈lines 214–215): add
  `("RACECAST_TRAILER_URL", rc.trailer_url)`. All ~10 `_apply_active_profile_env()`
  call sites then inject it automatically.

#### 5. Profile env templates

- `profiles/example/profile.env` and `profiles/demo/profile.env` (the Intro/Outro
  block): add `TRAILER_URL=` with the same "Assets tab cell 'Trailer Video'" comment.

#### 6. `src/scripts/event.py` — asset-readiness fallback

- `required_media` (≈lines 219–226) derives keys from the Sheet when rows are
  present, but has an empty-rows fallback list `["intro.mp4","outro.mp4"]` (≈line
  225). Add `"trailer.mp4"` so readiness reporting includes it when the Sheet is
  unreadable. (When the Sheet has a Trailer row it already flows through.)

#### 7. `src/obs/GT_Endurance.json` — OBS collection

- Add `{"name": "Trailer"}` to `scene_order` (≈lines 298–301, cosmetic placement
  near Intro/Outro).
- Add a `Trailer` scene object and a `Trailer Video` `ffmpeg_source`, modelled on
  the Intro scene (≈lines 744–859), with:
  - `"local_file": "__RACECAST_MEDIA__/trailer.mp4"`
  - `"looping": true`, `"restart_on_activate": true`, `"close_when_inactive": true`
  - audio `mixers` bitmask matching Intro/Feed A so clip audio reaches the broadcast,
    `volume` 1.0, not muted.
  - **Fresh unique UUIDs** for both the scene and the source (must not collide with
    the Intro/Outro UUIDs).
- Precedent for cloning a scene programmatically: `tools/add_intermission_scene.py`
  deep-copies the Intro scene as a template — useful reference, but a hand-authored
  JSON block is fine given it's a one-off.

#### 8. `src/director/director-panel.html` — Director Panel

- `CONFIG.macros` (≈lines 881–884): add, next to INTRO/OUTRO,
  `{label:"TRAILER", scene:"Trailer", show:[], hide:[], unmute:[], mute:["Feed A","Feed B","Discord Audio Capture"]}`.
- Rendering (`#pgmBus`), `runMacro`, `obsScene` → `POST /obs/scene` are generic and
  need no change.

#### 9. `src/companion/racecast-buttons.companionconfig` — Companion / Web Buttons

- PAGE 1: add a `TRAILER` button on the next free key after OUTRO (key `6`) — target
  key `7` if free (verify during implementation), mirroring the INTRO (key 5) /
  OUTRO (key 6) buttons:
  - text `TRAILER`;
  - native OBS-WS `set_scene` action with `"scene": {"value": "Trailer"}` (same
    `connectionId`/`definitionId` as INTRO/OUTRO), fresh action id;
  - `sceneProgram` feedback lighting on scene `Trailer`.
- The Web Buttons view (`src/console/buttons.html`) renders this same config — no
  separate change.
- Use the `companion-buttons` skill to author/import/click-test the button.

### Already generic (verify, do not change)

- Relay `/obs/scene` handler (`racecast-feeds.py` ≈lines 8986–9001) — switches to any
  scene by name.
- `src/setup-assets.py` token injection — any `__RACECAST_MEDIA__/*.mp4` reference is
  resolved to the absolute media dir and auto-placeholdered if the file is missing.
- `src/scripts/placeholders.py` — template-driven media scan (`_MEDIA_REF_RE`,
  `expected_media_from_template`, `media_placeholder_for`).
- `tools/tokenize-obs.py` — folds any `local_file` back to `__RACECAST_MEDIA__/<name>`
  on re-commit.

## Tests

Mirror the existing Intro/Outro test coverage (stdlib-only runnable scripts):

- `tests/test_media.py` — add Trailer cases to `media_urls_from_csv` (label match,
  case/whitespace, column-agnostic), `resolve_urls` priority (CLI > env > sheet), and
  the `--which all` expansion.
- `tests/test_placeholders.py` — extend the fake collection to include
  `__RACECAST_MEDIA__/trailer.mp4` and assert a placeholder is written; add `trailer`
  to the `seed_missing_media` case.
- `tests/test_event.py` — assert `trailer.mp4` appears in the `required_media`
  fallback.
- `tests/test_director_panel.py` — extend the macro-list assertion to include TRAILER.
- `tests/test_companion.py` — extend the button/scene assertions for the Trailer button.
- Run `python3 tools/run-tests.py` (the full suite CI runs) + `python3 tools/lint.py`.

## Data flow (runtime)

1. League admin enters a `Trailer Video` URL in the Sheet Assets tab (or sets
   `TRAILER_URL` in `profile.env`).
2. Operator runs `racecast media` → `get-media.py` resolves the URL and `yt-dlp`
   writes `trailer.mp4` into `runtime/<profile>/media/`.
3. `racecast setup` (`setup-assets.py`) localises the OBS collection, resolving
   `__RACECAST_MEDIA__/trailer.mp4` to the absolute path (placeholder if absent).
4. Producer imports/refreshes the localised collection in OBS.
5. Director clicks **TRAILER** on the Panel (or the Companion button) → OBS switches
   to the `Trailer` scene → `restart_on_activate` plays from frame 0, `looping`
   repeats, audio is on the broadcast; feeds + Discord are muted by the panel macro.
6. Director clicks another scene to leave; `close_when_inactive` releases the clip.

## Error handling

- **Clip missing at show time:** `setup-assets.py` fills a neutral placeholder clip
  (existing generic behaviour); the broadcast is otherwise unaffected.
- **URL not in Sheet / fetch fails:** `get-media.py` reports it like intro/outro; the
  placeholder keeps OBS from showing a hard-missing source.
- **No new attack surface:** no new relay endpoint, no new secret, no new network
  listener. The Trailer URL is a public YouTube/Twitch link; the Sheet ID stays in
  `profile.env`.

## Docs + screenshots (same-change requirement)

- `CLAUDE.md`: extend the Intro/Outro mentions (≈lines 185, 247, 260–261, 304,
  329–331) to include the Trailer.
- Wiki under `src/docs/wiki/`: `OBS-Setup.md` (Trailer scene + Companion button),
  `Sheet-Template.md` (Assets `Trailer Video` row), `Director.md` (TRAILER macro /
  run-of-show), `Configuration.md` (`TRAILER_URL` profile key).
- **Screenshots (project rule — same change):** the Director Panel changed
  (`director-panel.png`) and the Companion PAGE 1 board changed
  (`companion-page1-*.png`). Regenerate via the `wiki-screenshots` and
  `companion-screenshots` skills and commit alongside the code.

## Open / to confirm during planning

- Exact free Companion key on PAGE 1 (7 assumed; verify against the current config).
- Exact `ffmpeg_source` audio `mixers` bitmask — copy verbatim from the Intro source
  in `GT_Endurance.json` so routing matches.
