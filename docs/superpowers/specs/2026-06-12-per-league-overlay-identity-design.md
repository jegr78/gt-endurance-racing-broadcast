# Per-League Overlay Identity — Design

**Date:** 2026-06-12
**Status:** Design — pending implementation
**Issues:** #80 (Director: extend Sheet/Overlay/Panel options) + #81 (Backup & Restore for profile assets)
**Build order:** Part 1 (#80) before Part 2 (#81).

## Context

Two new issues push in the same direction: the relay-served overlay/HUD becomes a
**per-league, panel-driven, versionable artifact**.

- **#80** wants the team identity split: today a team is a single `Name #Number` string
  (Overlay tab rows `Teams P1/P2/P3`, matched against the Configuration tab `Teams`
  column for the brand logo). The HUD renders it as one `.name` span per podium slot
  (`src/obs/hud.html`), so name and number cannot be positioned independently. #80 also
  wants the Top-3 podium teams switchable **from the director panel** — the same
  async-optimistic, sheet-synced mechanism the panel already uses for
  Streamer/Stint/Session/Race Control.
- **#81** wants **backup & restore of a league's look** (overlay CSS, graphics, media),
  because the style flips back and forth between events. Its open research question:
  must `hud.html` move into the profile, or do CSS overrides suffice?

The per-profile overlay-override mechanism already exists (see
`2026-06-11-per-profile-overlay-overrides-design.md`): a shared `src/obs/hud.html` plus a
cascade-wins `profiles/<name>/overlay/{hud,timer}.css` (+ `fonts/`), served per request,
auto-refreshed in OBS via the `OBS_PAGE_PATHS` hash gate. This feature builds directly on
it. The settled research answer for #81 is recorded under Decisions below.

## Decisions (locked during brainstorming)

1. **HUD name/number** become **two separate elements** per podium slot. Default
   arrangement = a **number badge before the name** (visual option A). The name is
   **auto-fit**: single line, font shrinks to fit width down to a minimum, `max`/`min`
   font size as CSS variables; short names stay large. Per-league `override.css` can
   reposition/restyle badge and name freely.
2. **Data model = roster-based.** The Configuration tab becomes a clean roster:
   `Team Name | Number | Brand`. The Overlay tab `Teams P1/P2/P3` stores only *which
   team* sits in each podium slot. The relay looks up number + brand from the roster
   keyed by team name. **Fallback:** when no `Number` column exists, the relay parses a
   trailing `#NNN` from the team string (backward compatible with today's sheets).
3. **Panel Top-3 control** = three new setup-style dropdowns (P1/P2/P3). Vocabulary =
   the **full roster**, no free-text escape. Async-optimistic writeback (like the
   existing setup fields), targeting the Overlay tab `Teams P1/P2/P3` rows.
4. **`hud.html` stays shared.** Per-league customization is **CSS-only** — `override.css`
   can hide/show any block (`display:none`), reposition, and restyle. No per-profile HTML
   fork (it would be a maintenance multiplier). Revisit only if a concrete need for new
   DOM structure appears.
5. **Backup = library of named looks** (not a single safety-net slot). Each snapshot is a
   **zip** containing `overlay/ + graphics/ + media/` + a `manifest.json`. Restore does a
   **full replace** of the three live asset locations. CLI verb = **`racecast backup`**.

## Goals

1. Position and style team name and number independently in the HUD, per league.
2. Switch the three podium teams live from the director panel, sheet-synced, with the
   number + logo following automatically from the roster.
3. Keep a single shared `hud.html`; all per-league visual identity lives in
   `override.css` + runtime assets.
4. Capture/restore a league's complete look as named, portable snapshots, without
   re-downloading from the sheet.
5. No regression for leagues that have not added a `Number` column or any backups.

## Non-Goals (v1)

- **No per-profile HTML.** `hud.html`/`timer.html` stay shared (Decision 4).
- **No free-text team entry** in the panel — strictly the roster vocabulary (Decision 3).
- **`profile.env` is not part of a backup** — it is league config (Sheet ID, URLs), not
  "look". Backups cover overlay CSS/fonts + graphics + media only.
- **No backup of `hud.html`** (it is shared and committed).
- **No cloud/remote backup store** — snapshots are local zips under
  `runtime/<profile>/backups/` (portable by hand, like a `chat export`).
- **No automatic snapshot before restore** — the producer creates one first if they want
  to keep the current look. Restore is a deliberate, confirmed overwrite.

---

## Part 1 — #80: Split team name/number + panel-controlled Top-3

### 1.1 HUD rendering (`src/obs/hud.html`, shared)

Each podium slot today is:

```html
<div id="team0" class="el team white"><img alt=""><span class="name"></span></div>
```

Becomes a slot with **two independently-targetable text elements** plus the brand image:

```html
<div id="team0" class="el team white">
  <img alt="">
  <span class="num"></span>
  <span class="name"></span>
</div>
```

- **Default arrangement (base inline `<style>`):** badge-style `.num` before `.name`
  (option A). `.num` is a compact box (the existing red accent), `.name` follows.
- **Auto-fit name:** a small vanilla-JS routine measures each `.name` and reduces its
  `font-size` until it fits the slot width on one line, bounded by two CSS variables
  (e.g. `--team-name-max`, `--team-name-min`). Short names render at max; only long names
  shrink. No wrapping (the podium band is ~56 px tall; wrapping risks colliding with the
  `Overlay.png` frame). Replaces today's `text-overflow: ellipsis` truncation.
- **Per-league control:** because `.num` and `.name` are separate elements with ids,
  `override.css` can reposition either one, change the badge look, or re-tune the auto-fit
  bounds via the CSS variables. The base layout is the byte-stable default for leagues
  with no override.

`setTeam(i, team)` is extended to set `.num` (`team.number`) and `.name` (`team.name`)
separately, hide `.num` when empty, and run the auto-fit pass after setting text.

### 1.2 Data model: roster in the Configuration tab

**Configuration tab (the roster):**

| Today | New |
| --- | --- |
| `Teams` = `"OVO eSports #111"`, `Brand` = `"porsche"` | `Team Name` = `"OVO eSports"`, `Number` = `"111"`, `Brand` = `"porsche"` |

- A new optional `Number` column sits alongside the team-name column. `BRAND_TEXT_HEADERS`
  matching is unchanged. The team-name header keeps being located by text
  (`"teams"`/`"team name"`), so column order stays free.
- **`parse_config_brands` → `parse_config_roster`:** returns
  `{team_name: {"number": <str>, "brandKey": <key>}}` instead of `{team_name: brand_key}`.
  When the `Number` column is absent, `number` is derived by the `#NNN` fallback (below).

**Overlay tab (`Teams P1/P2/P3`):** now stores just the **team name** that occupies each
podium slot (was the full `Name #Number` string). The relay joins it to the roster.

**`#NNN` fallback (backward compat):** a helper `split_team_label(s)` →
`(name, number)` splits a trailing `#NNN` off a label (`"OVO eSports #111"` →
`("OVO eSports", "111")`; no `#` → `(s, "")`). Used (a) to normalize an Overlay
`Teams P1` value that still carries the old combined string, and (b) to derive `Number`
in `parse_config_roster` when the column is missing. This means a league that has not
migrated its sheet still renders correctly — name and number are split at read time, just
not independently editable in the sheet.

**`build_hud_data`:** the `teams` array gains `number`:

```python
"teams": [team_entry(n, roster) for n in overlay.get("teams", ["", "", ""])]
# team_entry -> {"name": <name>, "number": <number>, "brandKey": <key>}
```

`/hud/data` contract gains `number` per team object (additive; existing consumers ignore
it). HUD data flow is otherwise unchanged.

### 1.3 Panel control (Top-3 dropdowns)

**`SetupControl` / `SETUP_FIELDS`:** add three podium fields. Unlike the current setup
fields (which write the **Setup** tab), these write the **Overlay** tab rows
`Teams P1/P2/P3`. Their vocabulary is the **roster team names** (already available to the
relay from the Configuration tab), surfaced through `/setup/data` like the other
dropdowns. The async-optimistic flow is reused verbatim:

- optimistic HUD override now (`HudSource.set_override`) — the override target is the
  corresponding `teams[i].name`,
- background push to the webhook,
- sheet poll confirms or 30 s expiry,
- strict vocabulary check (value must be a known roster team).

**Director panel (`src/director/director-panel.html`):** three new dropdowns (P1/P2/P3) in
the HUD section, rendered and wired exactly like the existing `SETUP_FIELDS` selects
(poll `/setup/data`, `GET /setup/set/<field>/<value>`, pending/amber state, read-only when
the webhook is unconfigured). Selecting `P1 = OVO eSports` switches the whole team — name,
number, and logo all follow from the roster.

### 1.4 Apps Script webhook (wiki: `Sheet-Webhook`)

The webhook gains an Overlay-teams write path. The Overlay tab uses **label rows**
(`Teams P1/P2/P3` in column B, value from column C), unlike the Setup tab's
header-above-value layout, so it needs its own writer rather than reusing `writeSetup`.
Proposed: a new `action: "teams"` carrying `{slot: 1|2|3, name: <team>}` (or a small batch
`{teams: {P1, P2, P3}}`), locating the `Teams P<slot>` label row in the Overlay tab and
writing the team name into its value cell. The relay's strict roster check keeps the
written value valid. The v2-script `action` echo / `ok` contract (`check_webhook_response`)
is unchanged. Exact action shape is an implementation detail resolved in the plan.

### 1.5 Files touched (Part 1)

- `src/obs/hud.html` — split `.num`/`.name` elements, default badge layout, auto-fit JS,
  CSS variables for name min/max.
- `src/relay/racecast-feeds.py` — `split_team_label`; `parse_config_roster` (number +
  brand); `parse_overlay` team values normalized to names; `build_hud_data` adds
  `number`; `SETUP_FIELDS`/`SetupControl` P1/P2/P3 fields + Overlay-tab writeback +
  roster vocabulary; `HudSource` team-name overrides.
- `src/director/director-panel.html` — three P1/P2/P3 dropdowns.
- `src/docs/wiki/Sheet-Webhook.md` — the Overlay-teams action + Apps Script writer; the
  Configuration-tab `Number` column and the roster/Overlay schema change.
- Tests: `tests/test_hud.py` (roster parse, `#` fallback, `number` in `/hud/data`,
  auto-fit data), `tests/test_setup.py` (P1/P2/P3 fields, roster vocabulary, Overlay
  writeback payload).

---

## Part 2 — #81: Backup & Restore (library of named looks)

### 2.1 What a snapshot contains

Per active profile:

- `profiles/<name>/overlay/` — `hud.css`, `timer.css`, `fonts/`
- `runtime/<profile>/graphics/` — downloaded still graphics
- `runtime/<profile>/media/` — Intro/Outro clips

A snapshot spans both the committed-profile tree (`overlay/`) and the runtime tree
(`graphics/`, `media/`); the backup module reads from both and restores to both.

### 2.2 Storage format and location

```
runtime/<profile>/backups/<label>.zip
   overlay/{hud.css,timer.css,fonts/*}
   graphics/*.png
   media/*.mp4
   manifest.json   # {label, created (ISO UTC), profile, files:[...], counts}
```

- One **zip per snapshot** — atomic, easy to `list`/`delete`, and portable (hand a zip to
  another producer; they drop it in their `backups/` dir). Gitignored (under `runtime/`).
- `label` is sanitized to a safe filename stem (reuse the `asset_key` normalization
  style: lowercase, spaces→`-`, strip other punctuation); the original label is preserved
  verbatim in `manifest.json`.
- Creating an existing label errors unless `--force` (then it overwrites).

### 2.3 Operations (`src/scripts/backup_admin.py`, new — mirrors `chat_admin.py`)

Pure, testable functions; validate before writing; atomic; on failure the live state is
untouched.

| Verb | Behavior |
| --- | --- |
| `create <label>` | Zip the three asset locations + `manifest.json` to a temp file, then `os.replace` into `backups/<label>.zip`. Empty source dirs are allowed (recorded as empty). |
| `list` | Read each zip's `manifest.json`; return label, created, size, file counts. |
| `restore <label>` | Validate the archive (expected top-level dirs, manifest present/parseable, no path traversal in members). Extract to a temp dir, then **fully replace** the three live locations (swap-in: move current aside, move new in, drop the old). On any error, roll back so the live look is unchanged. |
| `delete <label>` | Remove `backups/<label>.zip`. |

**Restore is a full replace** (Decision 5): each of `overlay/`, `graphics/`, `media/`
becomes exactly the snapshot's contents (live-only files not in the snapshot are dropped)
— "switch to this look" makes the live state identical to the snapshot, not a merge.

**Zip safety:** on extract, every member name is validated (no absolute paths, no `..`
traversal, confined under the temp root) before it is written — same defensive posture as
the relay's font/asset resolvers.

### 2.4 OBS refresh after restore

- `overlay/*.css` changes are picked up by the existing `OBS_PAGE_PATHS` served-hash gate
  → browser sources refresh automatically on the next `relay start`/`obs refresh`.
- `graphics/`/`media/` are separate OBS **image/media** inputs (not browser sources), so
  the CSS hash gate does not cover them. `restore` therefore also invokes the existing
  best-effort OBS refresh path (the `obs_ws` client) to reload the affected sources — the
  same mechanism `racecast obs refresh` and the relay-stop feed-release already use. If
  obs-websocket is unreachable it prints one notice and the restore still succeeds; the
  manual right-click → Refresh remains the fallback. The exact reload call for
  image/media inputs is an implementation detail resolved in the plan.

### 2.5 UX

- **CLI** (`src/racecast.py`, a `backup_cmd` dispatcher modeled on `chat_cmd`):
  `racecast backup create|list|restore|delete <label>` (`create` accepts `--force`).
  Profile-scoped via the active-profile resolution already in the CLI; `--profile NAME`
  runs against another profile like every other command.
- **Control Center** (`src/ui/`): a "Looks" card in the **Profile** view (next to the
  overlay-CSS editor and scoped graphics/media): list snapshots (label/date/size), a
  create dialog (label input), restore (confirm dialog — it overwrites the live look),
  and delete (confirm). New pure data providers + routes `/api/backup` (list/create) and
  `/api/backup/{restore,delete}`, following the existing `/api/overlay` and
  `/api/profile/*` patterns.

### 2.6 Files touched (Part 2)

- `src/scripts/backup_admin.py` — new module (create/list/restore/delete, manifest,
  validation, atomic swap, zip-member safety).
- `src/racecast.py` — `backup_cmd` dispatch; UI data providers for the backup routes;
  OBS-refresh hook on restore.
- `src/ui/ui_server.py` (+ `src/ui/ui_ops.py` and the Profile-view frontend) — "Looks"
  card + `/api/backup*` routes.
- Tests: `tests/test_backup.py` (new — create/list/restore/delete round-trip, full-replace
  semantics, label sanitization/collision, zip-traversal rejection, fail-safe restore),
  plus route coverage in `tests/test_ui_server.py`.

---

## Data flow (Part 1)

```
Configuration tab (roster: Team Name | Number | Brand)
Overlay tab (Teams P1/P2/P3 = team name per slot)
        │  CSV via gviz (no API key)
        ▼
HudSource: parse_config_roster + parse_overlay (+ split_team_label fallback)
        │  build_hud_data → teams:[{name, number, brandKey}]
        ▼
/hud/data ──► hud.html setTeam(): .num + .name separate, name auto-fit
        ▲
panel P1/P2/P3 dropdown ──► /setup/set/<slot>/<team>
        │  SetupControl: optimistic override now + async webhook push
        ▼
Apps Script action:"teams" ──► Overlay tab Teams P<slot> value cell
        │  next sheet poll confirms (or 30s expiry)
        ▼
HudSource refresh
```

## Security

- **Roster writeback:** the relay enforces the value is a known roster team before any
  push; the webhook stays the only sheet-write path; trust boundary (tailnet-only relay)
  unchanged.
- **Backup zips:** every archive member is path-validated on extract (no absolute paths,
  no `..`, confined to a temp root) before writing — reuses the proven resolver posture.
  Labels are sanitized to safe filename stems; restore is atomic with rollback.
- **No new network surface, no new secrets.** Backups are local files under the gitignored
  `runtime/`; portability is a manual file copy (same trust level as `chat export`).

## Testing strategy (TDD, stdlib only)

- **Roster parse** (`tests/test_hud.py`): `Number` column → `{number, brandKey}`; missing
  column → `#NNN` fallback derives the number; brand mapping unchanged; `/hud/data` carries
  `number`.
- **`split_team_label`:** `"X #12"` → `("X","12")`, `"X"` → `("X","")`, names containing
  `#` mid-string handled per the trailing-token rule.
- **Panel teams** (`tests/test_setup.py`): P1/P2/P3 vocabulary = roster; non-roster value
  rejected; Overlay-tab writeback payload shape; optimistic override targets `teams[i]`.
- **Backup** (`tests/test_backup.py`): create→list→restore round-trip restores all three
  dirs; full-replace drops live-only files; label sanitization + collision (`--force`);
  zip with a `../` member is rejected; a restore that fails mid-way leaves the live look
  unchanged; empty source dirs handled.
- **UI routes** (`tests/test_ui_server.py`): `/api/backup` list/create and
  restore/delete; confirm-gated destructive actions return structured results.

## Sequencing

Single PR off `main` (branch `feat/per-league-overlay-identity`).

1. **Part 1 (#80)** first — it fixes the final `override.css`/asset surface a league can
   customize, which Part 2 then snapshots. Order: `split_team_label` + roster parse +
   `build_hud_data` (with tests) → `hud.html` split elements + auto-fit → panel dropdowns +
   `SetupControl` Overlay writeback → Apps Script writer + wiki/sheet-schema docs.
2. **Part 2 (#81)** — `backup_admin.py` (with tests) → `racecast backup` CLI → OBS-refresh
   hook on restore → Control Center "Looks" card.
3. Build (`python3 tools/build.py`) + lint (`python3 tools/lint.py`) + full suite
   (`python3 tools/run-tests.py`) green; CI watched.

## Open questions

None blocking. Implementation-detail decisions deferred to the plan:

- Exact Apps Script action shape for the Overlay-teams write (`action:"teams"` per-slot vs.
  a P1/P2/P3 batch).
- Exact obs-websocket call to reload image/media inputs after a `backup restore` (vs. the
  browser-source `refreshnocache` the CSS gate already uses).
- Label sanitization/collision policy details (overwrite-on-`--force` confirmed; reserved
  characters list finalized in the plan).
