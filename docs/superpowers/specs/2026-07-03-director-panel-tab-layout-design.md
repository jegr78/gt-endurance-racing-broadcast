# Director Panel Tab Layout — Design

**Date:** 2026-07-03
**Surface:** `src/director/director-panel.html` (served at `/panel` and `/console/panel`)
**Status:** Approved design, ready for implementation plan

## Goal

Split the Director Panel's single, ever-growing scroll column into a **two-tab
layout** so the live program preview and the most-used live actions stay in view
without scrolling, and the setup/config controls move out of the way onto a
second tab.

## Problem

The panel's left column (`.mainpane`) is one long vertical stack of ~15 sections
(PGM, Cues, Live Preview, Feeds, HUD, Transition, Scn·Vis, Gfx, Flag Gfx, Timer,
Audio, URLs, Pending, Qualifying, Substitution, log). As features accumulated, a
director must scroll to reach lower sections, and the live program preview — which
the Commentator Cockpit and Race Control keep permanently visible — scrolls out of
view. The sticky right rail (Chat · Broadcast Chat · Graphics) already stays put;
the left column is the problem.

## Scope

**In scope:** front-end only — DOM restructure of `src/director/director-panel.html`
(wrap the left-column sections into two tab panels + a tab bar), the supporting
CSS (tab bar, active state, panel show/hide), and a small amount of JS (tab
switching, persistence, the SETUP badge, the TX-armed chip). Refresh the committed
`director-panel.png` wiki/slides screenshot.

**Out of scope:** no relay/Python changes, no new endpoints, no change to any
control's behavior or wiring. Every existing element keeps its `id` and event
bindings; only its position in the DOM (and which tab panel wraps it) changes. The
right rail is untouched. `/console/panel` (Funnel) serves the same file, so it
inherits the layout with no auth or routing change.

## Layout

### Tab bar

A two-segment tab bar at the **top of the left column** (`.mainpane`), directly
under `#banners`, above the tab panels. It controls **only** the left column — the
right rail is a persistent context panel shown on both tabs, deliberately not
governed by the tabs. The tab bar is sticky (`top:0`) so it stays reachable while
the PROGRAM tab scrolls on shorter windows.

Tabs: **`PROGRAM`** (default) and **`SETUP`**.

### Tab 1 — PROGRAM (live operation)

Ordered most-frequently-used first, so the live loop needs no scrolling:

1. **Live Preview** (`#previewSec`) — PROGRAM output + Feed tiles A/B/POV.
   **Default shown** now (was default-hidden). The SHOW/HIDE toggle (`#pvToggle`)
   stays so a director can collapse it for more room.
2. **PGM** macros (`#pgmBus` / `.pgm`) — the primary "who is on air" switch, right
   under the picture. Carries the **TX-armed chip** (below).
3. **Cues** (`#cuesBus`) — the most frequent interaction between handovers.
4. **Feeds** (`#feedsBus` + `#feedHealth`) — NEXT/RELOAD + health, the handover cluster.
5. **HUD** (`#setupRow` / `#teamRow` / `#condRow` + `#setupInfo`) — streamer/stint
   labels set around the handover.

### Tab 2 — SETUP (config / between sessions)

Grouped from "still occasionally live" down to "pre-event / reactive":

6. **Scn·Vis** (`#scnBus`) — individual scene switches
7. **Gfx** (`#gfxBus`)
8. **Flag Gfx** (`#flagGfxBus`)
9. **Timer** (`#timerBus` + `#timerInfo`)
10. **Audio** (`#audio`)
11. **Transition** (`#txBar`) — parked here; its `activeTransition` JS state stays
    live (see below)
12. **URLs** (`#urlsBox`) — schedule list + POV
13. **Qualifying** (`#qualBox`)
14. **Pending submissions** (`#subsBox`)
15. **Substitution** (`#subSec`) — self-hiding reason note

### Right rail (both tabs, unchanged)

`.rail` stays exactly as today: Chat (`#chatBox`) · Broadcast Chat (`#bchatBox`) ·
Graphics browser (`#gfxBrowseBox`), sticky, constant across both tabs. Chat unread
therefore stays visible on both tabs — no tab badge needed for it.

### Persistent log

`#log` stays in `.mainpane` **below** the tab panels (outside both), so the last
action's status line shows on both tabs — actions are triggered from either tab.

## Visual design

Reuse the existing token system — no new palette. The tab bar uses `--panel` /
`--panel-2` / `--edge` / `--ink` / `--muted`, IBM Plex Mono, uppercase,
`.12em` letter-spacing (matching the `.cap` section labels).

- **Inactive tab:** `--muted` text on the panel-gradient background, `--edge` border.
- **Active tab** (`nav-state-active`): brighter `--ink` text, a 2px accent underline
  in the panel's existing accent tone, slightly raised background. `aria-selected`
  drives the style.
- Touch/click target ≥ 40px tall; visible `:focus` ring (keyboard).
- **SETUP badge:** a small count/dot on the SETUP tab (see Behavior).

## TX-armed chip (Tab 1)

Because Transition moved to SETUP, Tab 1 carries a compact read-only chip in the
PGM row, e.g. `TX: CUT`, showing `activeTransition` in uppercase. It updates from
the same `renderTxBar()` path that the Transition buttons already call, so it
always reflects what the next scene switch will do. Clicking it switches to the
SETUP tab (optionally focusing `#txBar`). Styled as a subtle chip
(`--edge` border, `--muted` label + `--ink` value), right-aligned in the PGM
section so it never competes with the macro buttons.

## Behavior

- **Default tab:** `PROGRAM` on load.
- **Persistence:** the selected tab is stored in `localStorage`
  (`rc_panel_tab`); a reload restores it. Unknown/absent value → `PROGRAM`.
- **Tab switch = CSS `display` only.** Both panels stay in the DOM; the inactive
  one is `display:none`. All polling, timers, and the preview image loop keep
  running, so switching tabs never loses in-progress input (e.g. a half-typed cue
  or URL), scroll position, or a fresh preview frame. Nothing is torn down or
  re-initialized.
- **SETUP badge:** appears when there is something on SETUP needing attention —
  **pending submissions > 0** OR a **substitution awaiting a reason** (i.e.
  `#subSec` is visible). It shows the pending-submissions **count**; when the count
  is 0 but a substitution is pending, it shows a `•` dot. This preserves the
  visibility of the now-hidden Pending/Substitution items that today sit in the
  scroll column. Reuses the existing `#subsCount` value and the existing
  substitution-visible state; no new data source.
- **Accessibility / keyboard:** `role="tablist"` on the bar, `role="tab"` +
  `aria-selected` + `aria-controls` on each tab button, `role="tabpanel"` +
  `aria-labelledby` on each panel. `←`/`→` move between tabs when the tab bar has
  focus; global `1` / `2` shortcuts jump to PROGRAM / SETUP (guarded so they don't
  fire while typing in an input/textarea/select). Focus order stays visual order.
- **Responsive:** under 900px the rail already stacks under `.mainpane`
  (`.panes` becomes `display:block`); the tab bar stays at the top of the column
  and the tab panels stack normally. Under 760px the `.bus` sections already go
  single-column — unaffected. Two tabs never need to wrap.

## Implementation notes

- Wrap the Tab 1 sections in `<div id="tabProgram" role="tabpanel">` and the Tab 2
  sections in `<div id="tabSetup" role="tabpanel" hidden>`, both inside
  `.mainpane`, with the tab bar (`<div class="tabbar" role="tablist">`) before them
  and `#log` after them. Reorder the sections within each wrapper to the order
  above.
- **Preserve every `id` and existing event binding.** JS binds controls by `id`
  after load, so moving a `<section>` in the source is safe as long as its `id`
  and inner structure are intact. Do a grep for any CSS/JS that depends on the
  sections being *direct* children of `.mainpane` or on `:nth-child()` ordering and
  fix if found (the current `.bus` styling is class-based, so this should be a
  no-op — verify during implementation).
- Preview default-shown: flip `#pvBody` from `hidden` to shown and set
  `#pvToggle` to the "HIDE" state (and the JS initial state that mirrors it), so the
  toggle stays consistent.
- Tab logic is a small self-contained block: a `setTab(name)` that toggles the
  `hidden` attribute on the two panels + `aria-selected` on the two buttons +
  writes `localStorage`, called on click, on the keyboard shortcuts, and once on
  load from the stored value.

## Testing

Front-end only, so no Python unit test changes. Verification:

- **`ui-visual-verification`** (mandatory for a Director Panel change): boot the
  demo relay + obs-sim, render `/panel`, and eyeball **both** tabs — active-state
  styling, the TX chip, the SETUP badge with a seeded pending submission, preview
  default-shown, and the rail unchanged on both tabs. Check `:focus` on the tab
  buttons and a keyboard `1`/`2` switch.
- **Wiki screenshot:** regenerate `src/docs/wiki/images/director-panel.png` (and the
  `src/docs/slides/assets/img/director-panel.png` copy) via the `wiki-screenshots`
  recipe, showing the PROGRAM tab, and commit alongside the code (CLAUDE.md hard rule).
- **Optional e2e:** if the Playwright pass is run, assert both tab panels exist and
  the SETUP panel is `hidden` by default — but this is not a required CI gate (the
  synthetic e2e job does not run Playwright).

## Non-goals

- No floating/z-index preview overlay (the earlier follow-up idea) — tabs solve the
  scroll problem instead; the persistent-preview-in-rail alternative was considered
  and rejected (rail is already tightly packed).
- No change to which controls exist or what they do.
- No third tab or nested sub-navigation — two flat tabs only.
