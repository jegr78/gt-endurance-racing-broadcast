# Director-Panel Unified Mode-Aware Schedule Block — Design

**Status:** Approved (brainstorm), ready for implementation plan
**Date:** 2026-07-06
**Related:** #124 (qualifying live mode toggle), `2026-07-05-qualifying-event-lifecycle-design.md`
(qualifying as a first-class broadcast Part), `src/director/director-panel.html`
(`#urlsBox`, `#qualBox`), relay `set_mode` / `/mode/*` / `/qualifying/*` / `/schedule/*` /
`/pov/*` (`src/relay/racecast-feeds.py`), `tests/test_director_panel.py`.

## Goal

Collapse the Director Panel's **two** schedule-editing sections — `URLs · Schedule + POV`
(`#urlsBox`) and `Qualifying` (`#qualBox`) — into **one mode-aware "Schedule" block** whose
body reflects the relay's current mode, with **one** visible mode indicator and **one**
race↔qualifying switch. Keep the live mode toggle fully functional (both entry paths stay:
`event start --qualifying` *and* the live in-panel switch), keep the **POV editor reachable
in both modes**, and remove the confusing duplication.

## Background — the confusion this fixes

Qualifying (#124) originally shipped as a standalone panel section with its own
`QUALIFYING MODE` / `RACE MODE` buttons that call `/mode/*`. That predates the
qualifying-event-lifecycle work, which made qualifying a first-class broadcast **Part**
(`Q` row in the `Producer` tab, own OBS stream key, started via `event start --qualifying`
or the Control Center toggle). The result today:

- **Duplication.** In race mode the panel shows *both* the race schedule editor and the
  Qualifying section — two schedule-like blocks, one of which is irrelevant to the current
  mode.
- **Invisible mode.** The only mode indicator is a small `ON AIR` badge on the Qualifying
  header (`#qualModeBadge`). Pressing the toggle changes `relay.mode` (re-points Feed A to
  the Qualifying tab, resets the Part pointer, mode-gates the Parts control), but the visible
  change is so subtle it reads as "only the feed changed, not the mode" — the exact
  complaint that triggered this work.

Underlying truth that drives the design:

- There is **one** mode state: `relay.mode ∈ {race, qualifying}`. It has two *setters*
  (at `event start`, or live via `/mode/*`) but one *value*. The UI should therefore show
  **one** mode concept.
- **POV is mode-independent.** The POV PiP is a third, separate feed (`/pov/*`, its own
  `POV` sheet tab); `set_mode` only re-points Feed A/B and never touches POV. POV editing
  must be available in **both** race and qualifying. (Today POV lives inside `#urlsBox`,
  which the panel intends to hide in qualifying mode — so POV editing is unreachable in
  qualifying. This design fixes that by pulling POV out of the mode-gated region.)

## What already exists (reused, not rebuilt)

- **Mode switch endpoints:** `GET /mode/race` / `GET /mode/qualifying` → `Relay.set_mode`
  (re-points feeds, resets Part pointer unless a Part is on air, returns `/status`).
  Unchanged.
- **Status carries the mode:** `GET /status` returns `mode: "race"|"qualifying"` — the panel
  already reads `d.mode` in `relayPoll` and (post-bugfix) toggles section visibility from it.
- **Race schedule editor data/writes:** `#schedBody` rows, `/schedule/data`, `/schedule/set`
  (via `SetupControl.schedule_set`), `+ ADD ROW`. Unchanged.
- **Qualifying row data/writes:** `/qualifying/data` (`available`, `mode`, `rows[0]`),
  `/qualifying/set`. Unchanged.
- **POV editor:** `#povName` / `#povUrl` / `#povSave` → `POST /pov/set`. Unchanged.
- **Availability signal:** `/qualifying/data` returns `available: false` when there is no
  `Qualifying` tab / `--no-qualifying` / a custom `--sheet-csv-url`. The switch must respect
  this.

**No relay change is required.** This is a front-end (`director-panel.html`) restructure.

## Design — the unified block

Merge `#qualBox` into `#urlsBox` (reuse the existing `details.urls` styling and the stable
`#urlsBox` id / `#schedBody`, `#qualRow`, POV ids). One `<details class="bus urls">` titled
**Schedule**, laid out as:

```
┌ SCHEDULE · ● QUALIFYING ───────────────── [ switch → RACE ] ┐   header: mode chip + ONE switch
│                                                              │
│  (race mode)   1 [A] JeGr | STINT 1 | https://…   SAVE CLEAR │   #schedBody rows + "+ ADD ROW"
│                + ADD ROW                                     │
│                                                              │
│  (quali mode)  Q [A] JeGr | QUALIFYING | https://…  SAVE CLR │   the single #qualRow
│                                                              │
│  POV (always)  [name (max 20)]   [url]              SAVE     │   POV row — shown in BOTH modes
│                                                              │
│  <hint text, adapted to the active mode>                     │
└──────────────────────────────────────────────────────────────┘
```

### 1. One mode indicator + one switch (header)
- The `<summary>` shows a **mode chip**: `● RACE` or `● QUALIFYING` (reusing the amber/blue
  palette; the qualifying state visually distinct). This replaces the hidden-until-qualifying
  `#qualModeBadge`, so the mode is always visible at the section a director actually works in.
- A **single switch button** to the right of the summary whose label reflects the *target*:
  `switch → QUALIFYING` in race mode, `switch → RACE` in qualifying mode. It keeps the
  existing confirm dialog ("interrupts a running pull — use between sessions") and calls
  `/mode/qualifying` or `/mode/race` accordingly. (Replaces the two separate
  `QUALIFYING MODE` / `RACE MODE` buttons; same underlying calls, same confirm.)
- **Availability:** when `/qualifying/data.available` is false, the switch is **hidden**
  (the install is race-only) and the block behaves exactly like today's race editor.

### 2. Mode-aware body
Driven by the mode the panel already polls. Two mutually-exclusive regions plus one shared:
- **Race region** (`#schedBody` table + `+ ADD ROW`): shown iff `mode === "race"`.
- **Qualifying region** (the single `#qualRow`): shown iff `mode === "qualifying"`.
- **POV region** (`#povName`/`#povUrl`/`#povSave`): shown in **both** modes — pulled out of
  the mode-gated region so it is never hidden.

Visibility uses the `hidden` attribute. Because `details.urls{display:block}` overrides the
UA `[hidden]` rule, the interim bugfix rule **`details.urls[hidden]{display:none}`** stays,
and any inner containers toggled via `hidden` must be plain elements (`<tbody>`/`<div>`),
not `details.urls`. The regression this supersedes (duplicate block in qualifying) is now
handled structurally: only one region renders per mode, and it lives in one section.

### 3. Hint text
One adaptive hint below the rows. In race mode: the existing race-schedule hint (RELOAD A/B,
CLEAR URL, Streamer/Stint → HUD). In qualifying mode: the existing qualifying hint
(one stream on Feed A, writes the Qualifying tab). The mode-switch caveat ("interrupts a
running pull — use between sessions") lives on the switch button's confirm and a short note
in the header area, not duplicated per row. POV keeps its short "applies on POV RELOAD" note.

## Data flow (unchanged endpoints)
- Mode chip + region selection ← `relayPoll` reading `/status`.`mode` (already polled).
- Switch button availability ← `/qualifying/data`.`available`.
- Race rows ← `/schedule/data`; writes → `/schedule/set`.
- Q row ← `/qualifying/data`.`rows[0]`; writes → `/qualifying/set`.
- POV ← existing POV load; writes → `/pov/set`.
- Switch → `/mode/race` | `/mode/qualifying`.

The existing pollers (`schedPoll`, `qualPoll`) are kept but gated by the active mode so the
hidden region does not poll needlessly; both still fire on the section's `toggle`.

## Error handling
- Mode switch failure: unchanged — the existing `relayCall` error/toast path.
- Qualifying unavailable: switch hidden, race-only behaviour, hint unchanged from today's
  "Qualifying tab not available…" message when relevant.
- Relay unreachable: the whole block degrades like the rest of the panel (existing behaviour).

## Testing
`tests/test_director_panel.py` (string-assertion tests over the static HTML — the established
pattern):
- **Replace** `t_mode_drives_section_visibility` (asserted the old `#urlsBox`/`#qualRow`
  hidden wiring) with assertions for the merged block: race region hidden iff qualifying,
  qualifying region hidden iff race, and the switch button label flips by mode.
- **Keep** `t_urls_section_honors_hidden_rule` (`details.urls[hidden]{display:none}` guard).
- **Add** `t_pov_visible_in_both_modes`: the POV editor is outside the mode-gated regions
  (not inside the race-only or qualifying-only container).
- **Add** `t_single_schedule_section`: `#qualBox` no longer exists as a separate `<details>`
  (guards against reintroducing the duplication).
- Update `t_setup_tab_order` (currently asserts `'id="urlsBox"', 'id="qualBox"'` order) to
  the merged structure.

## Non-goals / YAGNI
- No change to `set_mode` semantics, the Parts control, or `event start --qualifying`.
- No global mode switch relocated into the top status/Parts strip (considered; rejected as a
  bigger change to an already dense header — the in-section chip + switch is enough to make
  the mode visible).
- No change to POV behaviour itself — only its placement so it stays reachable in both modes.

## Docs / wiki
The **race-mode** appearance of the panel changes (the standalone Qualifying box disappears;
the schedule header gains a mode chip + switch), so `director-panel.png` is stale and MUST be
regenerated via the `wiki-screenshots` skill and committed alongside the code (CLAUDE.md hard
rule). Visual pre-flight via `ui-visual-verification` in both modes.

## Relationship to the interim bugfix
The working tree already carries a minimal fix for the CSS-cascade bug that made `#urlsBox`
ignore `hidden` (`details.urls[hidden]{display:none}` + `t_urls_section_honors_hidden_rule`).
That fix is correct but too coarse (it hides POV in qualifying). This redesign subsumes it:
the CSS guard is retained; the coarse "hide the whole race section" behaviour is replaced by
the mode-aware regions with POV always visible.
