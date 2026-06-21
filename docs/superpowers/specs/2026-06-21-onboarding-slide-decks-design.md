# Onboarding slide decks (per crew role) — design

Date: 2026-06-21
Status: approved design, pre-plan

## Goal

Visual onboarding / walkthrough **slide decks**, one per crew role, that show *what
each role does and how an event runs*. Decks are the **entry point**; the GitHub Wiki
remains the searchable depth, and slides link into it. Six decks total:

- **Role walkthroughs:** Producer (event day), Director, Commentator, Race Control
- **Setup decks:** Producer setup, League Admin setup

The **Director deck is the pilot** — the richest role, so it stress-tests the template.
The other five follow afterwards (their own spec/plan) once look + depth are signed off.

All deck content is **English** (repo rule); chat about it is German.

## Decisions (locked)

| Topic | Decision |
|---|---|
| Distribution | **Both** — single source published to GitHub Pages *and* bundled into the shipped package. |
| Wiki relationship | Decks = visual entry/walkthrough; **link into** the existing wiki for depth. Minimal redundancy. |
| Engine | **Reveal.js, vendored** (committed, no CDN, no npm), content authored as **inline Markdown** per deck → works offline and over `file://`. |
| Diagrams | Mermaid sources → **Excalidraw look, build-time, static committed SVG**. Shipped artifacts stay JS-free. Seed-pinned for reproducible diffs. |
| Overflow guard | **Required.** Playwright visual guard (text/graphics/SVG vs. slide box). **Skill + maintainer script**, run before publishing — *not* a CI gate. |
| CI | Only the cheap structural/link test (`tests/test_slides.py`). Visual guards are skill-driven, consistent with `wiki-visual-test` / `companion-screenshots`. |
| Pages trigger | **Dispatch-only** workflow (publishing is a deliberate maintainer action, like `wiki.yml`). Flippable to on-push later. |
| Role accents | Producer `#d62828`, Director `#e08a00`, Commentator `#1f7a8c` (from `cheat_sheets.html`); **new:** Race Control = steel blue-grey (read-only/official), League Admin = violet. |

## File layout

```
src/docs/slides/
  index.html                 # Landing: role-colored cards → decks (5 as "coming soon" during pilot)
  director.html              # Pilot. Later: commentator/race-control/producer/
                             #   producer-setup/league-admin-setup .html
  assets/
    deck.css                 # shared design system (extends cheat_sheets.html) + role accents (data-role)
    deck.js                  # shared Reveal init (markdown + notes + highlight plugins, options)
    fonts/                   # Saira Condensed + IBM Plex Mono, vendored (offline, no CDN)
    img/                     # only the few screenshots a deck actually embeds
    img/diagrams/<name>.svg  # committed Excalidraw-look SVGs (generated, do not hand-edit)
  diagrams/<name>.mmd        # Mermaid sources (the single source for each diagram)
  vendor/reveal/             # pinned Reveal.js dist subset (committed)
  README.md                  # maintainer: how to edit decks + regenerate vendor/diagrams
```

Each deck is a **thin single file**: head + `data-role` on `<body>` + inline-Markdown
slides + `<link>`/`<script>` to the shared `assets/`. This keeps the six decks DRY and
visually consistent.

## Components

### 1. Deck engine (`deck.js` + `vendor/reveal/`)
Reveal.js initialized once in `deck.js` with the Markdown, Notes, and Highlight plugins
and shared options (controls, progress, slide number, `hash`). Slides are inline
Markdown in `<section data-markdown><script type="text/template">…</script></section>`
so a deck is one portable file that renders offline and over `file://` (no external
`fetch`). Vendored subset: `reveal.js`, `reveal.css`, the markdown/notes/highlight
plugins (+ one highlight CSS). The visual theme lives in our `deck.css`, layered over a
minimal Reveal base — not a stock Reveal theme.

### 2. Design system (`deck.css`)
Carries over `cheat_sheets.html`: Saira Condensed (headings) + IBM Plex Mono (body),
accent bars, ink-friendly palette. Role accent is selected by `<body data-role="…">`
(producer / director / commentator / race-control / league-admin). Fonts are **vendored
locally** (`assets/fonts/`, `@font-face`) so decks need no font CDN at view time —
matching the repo's bundle-don't-CDN stance.

### 3. Content model (entry-level walkthrough, links to wiki depth)
The **horizontal** track is the event story; **detail is one arrow-down away** (Reveal
vertical stacks), so the top line stays a clean walkthrough. Director pilot outline:

1. Title + "Your job in one sentence"
2. **Before the event** (Console link, browser, Discord) → links `Director-Setup`
3. **Panel tour** (what the Director Panel does) → embeds `director-panel.png`, links `Director`
4. **Event flow timeline:** Standby → Go live → at each driver change press *Feeds Next*
   → scenes/graphics → cues to talent → interview cut + broadcast audio → end
5. **When things go wrong** → links `If-something-goes-wrong`
6. Cheat recap + "Go deeper" slide (wiki links)

Speaker notes optional and short. Every deck ends with a wiki cross-link slide.

### 4. Diagram pipeline (`tools/build-diagrams.py`)
Maintainer-only. Reads each `src/docs/slides/diagrams/<name>.mmd`, drives a headless
browser (Playwright Python) over a tiny local harness that loads
`@excalidraw/mermaid-to-excalidraw` + Excalidraw `exportToSvg` (converter libs pinned by
version; build-time network only, like the other `fetch-*` maintainer tools), and writes
the **committed** `assets/img/diagrams/<name>.svg`. Decks reference only the static SVG,
so the shipped/published site is JS-free for diagrams. **Seeds are pinned** (fixed
Excalidraw element seed / roughness before export) so regeneration is reproducible and
git diffs stay quiet. Decks must reference a generated SVG, never inline Mermaid.

### 5. Overflow guard (`tools/check-slides.py` + skill)
Playwright loads each deck at Reveal's configured resolution and, per slide, flags:
- text/content where `scrollHeight/Width` exceeds the slide box,
- images/SVG whose rendered box exceeds the slide,
- (diagrams are static SVG → measured the same way).
Reports the offending deck + slide index and writes a screenshot for the eye. Run before
publishing via a dedicated **skill** (mirrors `wiki-visual-test` / `companion-screenshots`).
Not wired into CI.

### 6. Maintainer fetch (`tools/fetch-reveal.py`)
Python/stdlib. Downloads a **pinned, SHA-256-verified** Reveal.js release and extracts
the dist subset into `vendor/reveal/` — exactly the `fetch-fonts.py` / deno pattern.
Also fetches the two vendored webfonts into `assets/fonts/`. Vendor stays committed so
Pages/build need no network. Sets a `User-Agent` (maintainer tool; outside the
`http_util` covered set, but UA-safe against Cloudflare-fronted hosts).

### 7. Distribution
- **Package:** `build.py` already copies `src/docs/` → `dist/`, so decks ship
  automatically. Add a verify assertion: `vendor/reveal/` + `index.html` present.
- **Pages:** new `.github/workflows/pages.yml`, artifact root = `src/docs/slides/`,
  **dispatch-only** (matches `wiki.yml`'s deliberate-publish ethos). One-time: set repo
  Pages source to "GitHub Actions" (note alongside the wiki bootstrap note).
- **Discoverability:** landing link from wiki `Home` + `_Sidebar` ("Onboarding decks ↗",
  the Pages URL); each role wiki page links to its deck.

### 8. Tests (`tests/test_slides.py`, CI-runnable, stdlib)
- every expected deck file exists and has the required scaffolding;
- outbound `[…](Wiki-Page)` links resolve to a real `src/docs/wiki/<Page>.md`;
- referenced assets exist on disk (vendor files, fonts, `img/`, diagram SVGs);
- every `diagrams/<name>.mmd` has a committed `assets/img/diagrams/<name>.svg`;
- no `.sh`/`.bat` under `src/docs/slides/`.

### New skills
- **`slides-overflow`** — run `tools/check-slides.py` (Playwright), report overflowing
  slides with screenshots. Pre-publish gate.
- **`slides-diagrams`** — regenerate Excalidraw-look SVGs from `.mmd` via
  `tools/build-diagrams.py`.

(Both authored via the `writing-skills` skill during implementation.)

## Guardrails

- English-only deck content; no `.sh`/`.bat` anywhere under `slides/`.
- `lint.py` stays green; new Python tools obey ruff rules.
- **Screenshot discipline:** if a deck embeds a Control Center / Director Panel shot, the
  CLAUDE.md "refresh the wiki screenshot in the same change" rule applies to that image.
- Generated artifacts (`vendor/reveal/`, `assets/img/diagrams/*.svg`) are committed but
  never hand-edited — regenerate via the maintainer tools.

## Scope: pilot vs. later

**Pilot (next plan):**
- Deck engine: `deck.css`, `deck.js`, vendored Reveal (`fetch-reveal.py`), vendored fonts.
- `index.html` landing with all six cards (five marked "coming soon").
- **Director deck complete**, including at least one Excalidraw-look diagram (exercises
  `build-diagrams.py` end-to-end).
- `tools/check-slides.py` + `tools/build-diagrams.py` + the two skills.
- `.github/workflows/pages.yml`, `build.py` verify hook, `tests/test_slides.py`.
- Wiki cross-links for the Director deck.

**Later (separate spec/plan):** the remaining five decks built to the finished pattern.

## Confirmed at spec review (2026-06-21)
- Pages workflow is **dispatch-only** (not auto-deploy on push).
- New role accents confirmed: Race Control = steel blue-grey, League Admin = violet.

## Addendum — remaining decks + Overlay Package Designer (2026-06-21)

The Director pilot is merged and published. This addendum scopes the **remaining
decks**, built to the now-finished linear (flat, no vertical stacks) template.

**Decks to build (6):**
- Role walkthroughs: **Producer (event)**, **Commentator**, **Race Control**.
- Setup: **Producer setup**, **League Admin setup**.
- **NEW — Overlay Package Designer**: a 7th card focused on the Control Center's
  **visual Overlay Builder** + the **live HUD preview with a running relay**
  (`/hud/preview`). Accent: **magenta `#b5359c`** (new `--overlay-designer` /
  `data-role="overlay-designer"`).

**Content sourcing (CLAUDE.md: never invent crew procedure).** Each deck distils
*mechanism* from its wiki page(s) and links there for depth:
- Producer (event) → `Run-an-event`, `Control-Center` (Home); Commentator →
  `Commentator-Cockpit`, `Console`; Race Control → `Who-does-what`,
  `Console` (Race Control); Producer setup → `Set-up-the-broadcast-PC`,
  `Control-Center` (Setup); League Admin setup → `League-Owner-Setup`,
  `Profiles`, `Sheet-Webhook`; Overlay Package Designer → `HUD-Overlays`,
  `Control-Center` (Profile/Overlay Builder).

**Diagrams (build-time Excalidraw-look SVGs):** a **producer-event-flow** diagram
(Producer event deck) **plus a shared `who-does-what` crew-map** (reused in the
Producer, Race Control and Commentator decks), both from the Mermaid already in
the wiki.

**Screenshots:** reuse the committed wiki shots (`cc-home`, `cc-setup`,
`cc-crew-editor`, `console-landing`, `console-race-control`, `console-login`,
`cc-overlay-builder`) copied into `slides/assets/img/`. The Overlay deck also gets
**one freshly-captured** `/hud/preview` live-preview image, produced reproducibly
with the **`demo` profile + the `tools/obs-sim.py` OBS stand-in** + a running relay
(no real OBS, public read-only Sheet, no secrets/Tailscale IP in the frame → safe
to commit).
