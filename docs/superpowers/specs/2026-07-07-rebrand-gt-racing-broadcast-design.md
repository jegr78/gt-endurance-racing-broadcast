# Rebrand to "GT Racing Broadcast" — Design (#308)

**Epic:** #300 (Solo mode & rebrand), sub-issue 8/9. Branch `feat/308-rebrand` off
`epic/300-solo-mode`; PR merges INTO the epic branch (not `main`).

## Goal

Rename the product/umbrella from **"GT Endurance Racing Broadcast" → "GT Racing
Broadcast"**, with endurance and solo as two symmetric modes underneath. The toolkit now
covers more than endurance, so the umbrella name should not read "Endurance". Solo is
unreleased and endurance is pre-release for this branding, so this is a **clean rename —
no legacy aliases, fallbacks, or old-name auto-detection**.

## Decisions (locked with Jens)

1. **The endurance OBS collection is renamed too** (symmetric with solo), accepting a
   one-time re-import for existing installs — not a docs-only rebrand. This is the issue's
   own proposal and Jens's clean-break preference; it is a deliberate, accepted break of
   the "existing endurance collections keep working without action" property.
2. **All committed template files follow one `GT_Racing_*` naming scheme** — the endurance
   file AND the (new, unreleased) solo files rename together for a consistent `src/obs/`.

## Canonical strings (single source of truth)

| Thing | Old | New |
|---|---|---|
| Umbrella product name | GT Endurance Racing Broadcast | **GT Racing Broadcast** |
| Endurance collection prefix (`config.PRODUCT_COLLECTION_PREFIX`) | GT Endurance Racing | **GT Racing Endurance** |
| Endurance base collection (`obs_ws.EXPECTED_SCENE_COLLECTION`) | GT Endurance Racing | **GT Racing Endurance** |
| Localized endurance collection | GT Endurance Racing — \<league\> | **GT Racing Endurance — \<league\>** |
| Solo collection prefix (`config.SOLO_COLLECTION_PREFIX`) | GT Racing Solo | *(unchanged)* |
| Localized solo collection | GT Racing Solo — \<profile\> | *(unchanged)* |

`PRODUCT_COLLECTION_PREFIX` and `EXPECTED_SCENE_COLLECTION` are two independent literals
that today both read `"GT Endurance Racing"`; both flip to `"GT Racing Endurance"`. The
solo prefix was already set to the new brand in #303 and does not change.

## Explicitly unchanged (out of scope)

- **Repo name** `gt-endurance-racing-broadcast` — not renamed (disruptive, not required).
- **CLI name** `racecast` and the **HTTP `User-Agent`** — branding only, per the issue.
- **The endurance feed/relay path** — byte-identical behaviour. Only branding strings and
  filenames change; the scene graph of the renamed endurance template is identical to
  today's (a `git show` diff must show only the `name` field).
- **Historical design records** `docs/superpowers/{specs,plans}/**` and the generated
  `CHANGELOG.md` — excluded from the text sweep (established convention, mirrors the
  "use commentator not talent" sweep scope). These record what was true when written.

## Components & changes

### A. Collection-name constants + OBS-WS logic
- `src/scripts/config.py`: `PRODUCT_COLLECTION_PREFIX = "GT Racing Endurance"`.
- `src/scripts/obs_ws.py`: `EXPECTED_SCENE_COLLECTION = "GT Racing Endurance"`; update the
  `renamed_variant` docstring/comment that references the `"GT Endurance Racing*"` family
  so it describes the new expected base.
- No behaviour change beyond the literal: `scene_collection_status`, `set_scene_collection`,
  and the localized-name builder in `config.py` (solo vs endurance branch) keep their shape.

### B. Template files (git mv + regenerate + references)
- `src/obs/GT_Endurance.json` → `src/obs/GT_Racing_Endurance.json`; inside it, `name`:
  `"GT Endurance Racing"` → `"GT Racing Endurance"`. Otherwise byte-identical.
- `src/obs/GT_Solo_Commentary.json` → `src/obs/GT_Racing_Solo_Commentary.json`.
- `src/obs/GT_Solo_POV.json` → `src/obs/GT_Racing_Solo_POV.json`.
  (Solo `name` field is already `"GT Racing Solo"` — unchanged; only the filenames move.)
- **Regenerate the solo files** via `tools/derive-solo-templates.py` after updating its
  input path (`GT_Racing_Endurance.json`) and `OUTPUTS` (the new solo filenames) — the
  regenerated content must be identical to the git-mv'd files (deterministic derivation),
  so the two approaches agree.
- Reference updates (grepped whole-repo incl. `tools/` per CLAUDE.md):
  - `tools/build.py`: ships `GT_Racing_Endurance.template.json` + `GT_Racing_Solo_*.template.json`;
    the verify step reads the renamed template.
  - `tools/tokenize-obs.py`: default fold-back target → `src/obs/GT_Racing_Endurance.json`.
  - `src/setup-assets.py`: kind-aware template base (`resolve_template_base`) → new filenames.
  - `src/scripts/placeholders.py` + `tests/test_placeholders.py`: template-filename reference.
  - `src/racecast.py` `_setup_import_name`: runtime import files →
    `GT_Racing_Endurance.import.json` / `GT_Racing_Solo.import.json` (gitignored; safe rename).

### C. Docs / wiki text sweep
Umbrella + collection strings across `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`
(descriptive product-name text only — not the hard-rule mechanics), `src/docs/*`
(guides + `src/docs/wiki/*`). Run `tests/test_wiki.py` after (validates every wiki
link/anchor; a renamed heading would break inbound anchors).

### D. UI text (visual-verify gate)
- `src/ui/control-center.html`: the `obs-collection-set` confirm string ("Switch OBS to
  the **GT Racing Endurance** scene collection?…") + a JS comment.
- `src/director/director-panel.html`: the `<title>` tab title ("**GT Racing** · Director
  Console") incl. its dynamic ternary counterpart, + two HTML comments that name the
  template file (`src/obs/GT_Racing_Endurance.json`).
- These strings do **not** appear in the *standing* `cc-*.png` / `director-panel.png`
  element screenshots (confirm dialog / browser-tab title / comments). Still, editing
  `src/ui/*` and `src/director/*` trips the `ui-visual-verify` Stop gate, so the controller
  renders the surface, eyeballs it, and records the marker
  (`python3 .claude/hooks/record_ui_verified.py …`). A committed wiki screenshot is
  regenerated **only if** its pixels actually change (expected: they don't).

### E. Slides / decks
Text sweep across `src/docs/slides/*` (incl. `favicon.svg` label text if any) →
`tools/check-slides.py` for overflow/render sanity. The **narrated walkthrough videos**
(rendered from the decks via the TTS pipeline) are **left stale** — re-rendering is a
heavy, separate pipeline and is out of scope for this rename; noted as a known follow-up.

## Migration (documented; no code shim)

After updating the binary, an existing endurance install's OBS still holds the old
`GT Endurance Racing — <league>` collection. The tooling now expects `GT Racing Endurance
— <league>` and will not find/switch to the old one, so `racecast event start` warns that
the expected collection is absent. Remedy, once:

1. `racecast setup` — regenerates the localized import JSON under the new name.
2. Import it into OBS; delete the old `GT Endurance Racing — <league>` collection manually.

No auto-rename inside OBS and **no legacy-name detection** — a compatibility shim would
reintroduce exactly the old-name alias this rename removes. The note lands in the wiki
OBS-Setup page and the PR body.

## Testing

- **Constants:** update `tests/test_obsws.py` (and any test asserting the old base name)
  to `"GT Racing Endurance"`; assert the localized endurance/solo builders in
  `tests/test_config.py`/profile tests produce the new prefixes.
- **Filenames:** update `tests/test_build.py`, `tests/test_solo_obs.py`,
  `tests/test_racecast.py`, `tests/test_overlay.py`, `tests/test_discord_audio.py`,
  `tests/test_intermission_scene.py`, `tests/test_placeholders.py` to the renamed files.
- **Endurance byte-identical guard:** verify `GT_Racing_Endurance.json` differs from the
  prior `GT_Endurance.json` only in the `name` line (diff check in the plan).
- **Wiki:** `tests/test_wiki.py` green after the doc sweep.
- **Build:** `python3 tools/build.py` exits 0 (its verify step reads the renamed
  template + asserts the new `name`).
- **Final residual check:** repo-wide grep for "GT Endurance" branding outside the
  excluded historical dirs returns nothing; `tools/run-tests.py` + `tools/lint.py` green.

## Non-goals

- No repo rename, no CLI/User-Agent change, no walkthrough-video re-render.
- No backward-compatible old-collection detection or auto-migration.
- No change to endurance broadcast behaviour or the relay feed path.
