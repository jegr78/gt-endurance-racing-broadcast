# Kind-conditional UI (Director Panel + Control Center)

Epic: #300 (Solo mode). Issue: **#307**. Builds on the profile `kind` field
(#301), the feed-less solo relay mode (#302), the solo OBS templates (#303) and
the device enumeration in General Settings (#304). This is the UI layer: adapt
the two operator surfaces to the active profile's `kind` so a **solo** profile
shows only what's relevant and never renders (or crashes on) the endurance
A/B-feed affordances.

## Context

Solo is the reframed *"endurance minus the A/B-feed schedule"* — the Sheet stays
always on, only the tabs that drive the A/B feeds (`Schedule`/`Qualifying`) are
irrelevant. The relay already runs feed-less in solo (#302) and reports its mode
via `/status`. The two surfaces have **not** been touched yet:

- **Director Panel** (`src/director/director-panel.html`) is served as a static
  page by the relay (`/panel`) and polls `/status`. It is currently **not
  solo-safe**: the status poll reads `d.feeds.A.stint` / `d.feeds.B.stint`
  unconditionally (director-panel.html:1414-1416), but solo's `_solo_status`
  returns `feeds: {}` (racecast-feeds.py:5399), so a solo relay would throw in
  the panel. #307 must fix this regardless of the cosmetic cut.
- **Control Center** (`src/ui/control-center.html` + `src/ui/ui_server.py` +
  `src/racecast.py`) knows **nothing** about a profile's `kind` today. Its
  new-profile dialog is endurance-only (Name + Copy-from), even though
  `pa.create_profile` and the CLI `profile new` already accept
  `--kind`/`--template` (#301).

## Key decisions

1. **Signal via the existing `mode`/`solo` status, not a new field.** The relay's
   `/status` already carries `mode:"solo"` / `solo:true` for a solo relay
   (racecast-feeds.py:5399) and the panel already gates race-vs-qualifying off
   `status.mode` via `applyMode()` (director-panel.html:1431, 2037-2043). #307
   extends that exact precedent with an `applySolo(d.solo)` toggle — no new relay
   field, no new endpoint on the panel side.
2. **Control Center learns `kind` from `/api/profiles`, not the relay.** The CC
   must gate views even when the relay is not running, so `kind` is read from the
   profile config (`resolve_config`/profile.env), not from the live relay status.
   `profiles_data()` gains a per-profile `kind` (and the active profile's kind is
   therefore available). This is static profile config — always available.
3. **Client-side `.hidden`/class toggling — the repo's dominant pattern.** Both
   surfaces are vanilla JS with no framework. The whole cut is expressed by
   toggling a `body.solo` class (panel) / gating a view (CC) after the data poll,
   matching the four existing precedents (`applyMode`, 404-self-hide,
   `?probe=1`-reveal, `os`-driven action hiding). No server-rendered variants.
4. **Endurance path stays byte-identical.** Every solo branch is additive and
   guarded on the solo signal; with `solo` false/absent the DOM, CSS, and data
   flow are unchanged. No existing test is disabled.

## Design

### A. The solo signal

**Director Panel.** In the `/status` poll handler:
- Read `d.solo === true` (equivalently `d.mode === "solo"`).
- Call a new `applySolo(isSolo)` that sets/clears `document.body.classList`
  `solo`. A `body.solo { ... }` CSS block hides the endurance-only containers
  (list in section B). This mirrors `applyMode()`.
- Make the existing feed reads solo-safe: guard `d.feeds && d.feeds.A` before
  dereferencing `.stint`/quality, so the poll never throws under `feeds: {}`.
  In solo the feed pills/tiles are hidden anyway, so the guarded values are just
  skipped.

**Control Center.** `profiles_data()` (racecast.py:4178-4198) adds `kind` to each
profile entry (resolved via the same profile-config read it already does for
`sheet_set`/`display`). The front-end resolves the **active** profile's kind from
that payload and toggles a `body.solo` class (or per-view gating — section C).

### B. Director Panel — the solo cut

Hidden when `body.solo` (endurance shows all of these unchanged):

| Container | id / selector | Why |
|---|---|---|
| Feeds section | `#feedsBus` (+ its `.bus` wrapper) | A/B feed health — no feeds in solo |
| Header feed pills | `#stA`, `#stB` | Feed A/B status pills |
| Preview feed tiles | `.pvtile[data-feed="A"]`, `.pvtile[data-feed="B"]` | A/B preview — keep program + POV tiles |
| Schedule editor (race) | `#raceSched` | A/B stint schedule |
| Schedule editor (qual) | `#qualSched` | qualifying schedule |
| Mode chip / switch | `#modeChip`, `#modeSwitch` | race⇄qualifying is meaningless in solo |
| Pending submissions | `#subsBox` | commentator stint-link submissions — no stints |
| Substitution | `#subSec` | stint substitution |

Kept and functional in solo (all feed-independent, already work under the solo
relay): Live Preview (program tile + **POV tile**), **Parts control**
`#partControl`/`#partActionBtn` (the chosen stream start/stop — a single
Producer "Part 1" row drives OBS stream key + start/stop + the post-event
report; `producer.active_producer_rows(rows, "solo")` already returns the
race/numeric parts), Cues `#cuesBus`, HUD/Setup value inputs
(`#setupRow`/`#teamRow`/`#condRow`/`#setupInfo` + the SETUP tab
Scn·Vis/Gfx/Flag-Gfx), **Timer** `#timerBus`, Audio `#audio`, Transition
`#txBar`, **OBS control** `#obsBus`, the chat rail, broadcast-chat, and the
program-audio bar.

**POV structural lift.** The POV editor (`#povName`/`#povUrl`/`#povSave`) lives
*inside* the `#urlsBox` "Schedule" `<details>`. Solo hides the schedule but keeps
POV, so POV is **lifted into its own top-level `.bus` card** that is visible in
both modes; in endurance it renders identically to today (same inputs, same
handlers, same POST to `/pov/set`) — only its DOM position moves out of
`#urlsBox`. This keeps a single POV code path and avoids POV being collateral of
the hidden schedule box. (Verify the move is byte-equivalent behaviorally: the
POV handlers bind by id, not by DOM ancestry.)

The header pills `#stA`/`#stB` and the transition/OBS/timer logic are otherwise
untouched.

### C. Control Center — creation dialog + view gating

**New-profile dialog** (`control-center.html:691-700`, `newProfile()` at
2882-2891, route `ui_server.py:704-715`, backing `profile_new_data`
racecast.py:4217):
- Add a **Kind** `<select>` (endurance | solo). When `solo` is selected, reveal a
  **Template** `<select>` (commentary | pov) and **disable the Copy-from**
  control (the CLI forbids `--from` with `--kind solo`,
  profile_admin.py:129-131) — mirror that rule client-side so the UI can't
  submit an invalid combo.
- `newProfile()` sends `{name, from, kind, template}`.
- `/api/profile/new` passes `kind`/`template` through; `profile_new_data(name,
  source, create, kind=..., template=...)` forwards them to
  `pa.create_profile` (already parameterized). Endurance default (`kind` absent
  ⇒ `endurance`, `template` empty) reproduces today's behavior exactly.

**View gating for an active solo profile:**
- Hide the **Streams** view (`data-view="streams"`, the feed/schedule surface)
  — both its nav entry and pane.
- Hide the feed-status block on the **Home** dashboard (the relay/feed rows that
  assume A/B).
- Make the **Solo devices** picker (added in #304, currently always in General
  Settings) **solo-only** — shown for a solo profile, hidden for endurance.
- Gating reads the active profile's `kind` from `/api/profiles`; a `body.solo`
  class (or equivalent per-nav `data-kind` gate) drives the CSS, matching the
  existing `showView`/nav pattern. Switching the active profile re-reads
  `/api/profiles` and re-applies.

### D. Interfaces touched (summary)

- `src/relay/racecast-feeds.py`: **no change** — the solo signal already exists
  on `/status`. (The panel is a static file; the relay serves it unchanged.)
- `src/director/director-panel.html`: `applySolo()`, `body.solo` CSS, solo-safe
  feed guards, POV lifted to its own card.
- `src/racecast.py`: `profiles_data()` adds `kind`; `profile_new_data` gains
  `kind`/`template` params forwarded to `create_profile`.
- `src/ui/ui_server.py`: `/api/profile/new` forwards `kind`/`template`.
- `src/ui/control-center.html`: kind/template in the new-profile dialog; view
  gating; solo-only devices picker.

## Testing (additive — nothing disabled)

- `tests/test_racecast.py`: `profile_new_data` forwards `kind`/`template` to a
  `create` seam (assert the call receives them; endurance default path
  unchanged). `profiles_data` includes `kind` per profile.
- `tests/test_ui_server.py`: `POST /api/profile/new` with a solo body reaches
  the backing function with `kind="solo"`/`template=...`; `GET /api/profiles`
  shape carries `kind`.
- Panel JS is not unit-tested in this repo; its correctness is covered by the
  visual verification + the e2e harness surface (the panel already loads under a
  solo relay in a dev build). The solo-safe feed guard is verified by loading the
  panel against a solo relay (no console throw).
- No real device ids / IPs / machine paths enter git; endurance path
  byte-identical.

### Visual verification + wiki screenshots (CLAUDE.md hard rule)

Any change to the Director Panel and Control Center requires the
`ui-visual-verification` look **and** refreshed committed wiki images in the same
change:
- `src/docs/wiki/images/director-panel.png` — the panel. A solo-variant capture
  demonstrates the cut (solo demo profile / solo relay stand-in). Decide during
  implementation whether to replace the canonical shot or add a solo companion
  image; at minimum the existing `director-panel.png` must still be accurate for
  endurance and must not regress.
- Affected `cc-*.png` — the new-profile dialog (with the kind/template selector)
  and, if a distinct solo dashboard state is shown, its capture. Captured from a
  local dev build (no `VERSION`), per the uniform dev-build-badge rule.

## Non-goals / boundaries

- No new relay endpoint or new `/status` field — the solo signal already exists.
- No change to the endurance panel/CC behavior or layout (byte-identical).
- Rebrand to "GT Racing Broadcast" — **#308**. GT7 telemetry POV HUD — **#324**.
- No server-rendered UI variants; the cut is client-side, matching the repo.

## Success criteria

- Loading the Director Panel against a **solo** relay: no console error, the
  feed/schedule/qualifying/submission affordances are hidden, and the Parts
  control, HUD/Setup inputs, timer, OBS control, and POV editor are present and
  functional. Against an **endurance** relay the panel is byte-identical to
  today.
- Control Center new-profile dialog can create a **solo** profile (kind +
  template, Copy-from disabled); with a solo profile active, the Streams view and
  the Home feed block are hidden and the Solo-devices picker is shown; with an
  endurance profile active, everything is exactly as today.
- `director-panel.png` + affected `cc-*.png` refreshed and committed; full suite
  green, no test disabled; endurance path unaffected.
