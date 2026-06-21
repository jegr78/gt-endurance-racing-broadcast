# Onboarding slide decks — remaining 6 decks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the five remaining role/setup decks plus a new **Overlay Package
Designer** deck, to the finished linear Director-pilot template, published to the
existing Pages site + bundled package.

**Architecture:** Each deck is a thin single HTML file under `src/docs/slides/`:
`<head>` + `<body data-role="…">` + inline-Markdown `<section>`s + the shared
`assets/deck.css` / `assets/deck.js` + vendored Reveal. No per-deck JS/CSS. Two
build-time Excalidraw-look SVG diagrams. Content distils *mechanism* from the wiki
and links there for depth.

**Tech Stack:** Vendored Reveal.js 5.2.1 (committed), inline Markdown, build-time
Mermaid→Excalidraw SVG (`tools/build-diagrams.py`), Playwright overflow guard
(`tools/check-slides.py`), stdlib test (`tests/test_slides.py`).

## Global Constraints

- **English-only** deck content (repo rule). No `.sh`/`.bat` under `slides/`.
- **Never invent domain rules / crew procedure** (CLAUDE.md). Every factual claim
  in a deck must trace to its source wiki page; describe the *mechanism*, link the
  wiki for depth. When unsure, omit rather than assert.
- **Linear/flat decks only** — no Reveal vertical stacks (the pilot's flattening
  decision). One `<section data-markdown>` per slide, top-level only.
- **Images are block-level:** every embedded image gets a **blank line before it**
  in the Markdown (else marked merges it into the preceding caption `<p>` — the
  pilot's slide-4 bug). Use plain Markdown `![alt](assets/img/<file>)`.
- Global image cap is already `max-height:480px` in `deck.css` — do not raise it.
- Each deck **ends with a "Go deeper" wiki cross-link slide**.
- Deck dimensions are 1280×720 (set in `deck.js`); author for that box. The
  **overflow guard must pass** (`tools/check-slides.py`) before completion.
- Wiki links use the bare page name form `[label](Page-Name)` resolving to
  `src/docs/wiki/<Page-Name>.md` (the test enforces this) **only inside `.md`** —
  but decks are HTML and link to the **published wiki URL**
  `https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/<Page-Name>`
  (the pilot's convention — see `director.html`). Match that exact URL base.
- Role accents in `deck.css`: producer `#d62828`, director `#e08a00`, commentator
  `#1f7a8c`, race-control `#5b7186`, league-admin `#7a4fb5`, **overlay-designer
  `#b5359c`** (new). `data-role` slugs: `producer`, `commentator`, `race-control`,
  `league-admin`, `overlay-designer`.
- Generated artifacts (`assets/img/diagrams/*.svg`, captured PNGs, vendor) are
  committed but never hand-edited — regenerate via the maintainer tools.

## Deck → file → role → source wiki → screenshot/diagram

| Deck | File | data-role | Source wiki | Visual |
|---|---|---|---|---|
| Producer (event) | `producer.html` | `producer` | `Run-an-event`, `Control-Center` | `cc-home.png`; **producer-event-flow.svg**; **who-does-what.svg** |
| Commentator | `commentator.html` | `commentator` | `Commentator-Cockpit`, `Console` | `console-landing.png`; **who-does-what.svg** |
| Race Control | `race-control.html` | `race-control` | `Who-does-what`, `Console` | `console-race-control.png`; **who-does-what.svg** |
| Producer setup | `producer-setup.html` | `producer` | `Set-up-the-broadcast-PC`, `Control-Center` | `cc-setup.png` |
| League Admin setup | `league-admin-setup.html` | `league-admin` | `League-Owner-Setup`, `Profiles`, `Sheet-Webhook` | `cc-crew-editor.png`, `console-login.png` |
| Overlay Package Designer | `overlay-designer.html` | `overlay-designer` | `HUD-Overlays`, `Control-Center` | `cc-overlay-builder.png`, **overlay-live-preview.png** (fresh) |

---

## Task 1: Magenta accent for the Overlay Package Designer

**Files:**
- Modify: `src/docs/slides/assets/deck.css` (the `:root` accent vars + the
  `body[data-role=…]` block, lines ~12-21)

**Interfaces:**
- Produces: `--overlay-designer` CSS var + `body[data-role="overlay-designer"]`
  selector that Task 8 (`overlay-designer.html`) consumes.

- [ ] **Step 1:** Add `--overlay-designer:#b5359c;` to the `:root` block alongside
  the existing accent vars.
- [ ] **Step 2:** Add `body[data-role="overlay-designer"]{--accent:var(--overlay-designer)}`
  alongside the other `data-role` rules.
- [ ] **Step 3:** Confirm no other change (the rest of `deck.css` is shared).
- [ ] **Step 4:** Commit: `style(slides): add overlay-designer magenta accent`.

---

## Task 2: Diagram sources + generated SVGs (who-does-what, producer-event-flow)

**Files:**
- Create: `src/docs/slides/diagrams/who-does-what.mmd`
- Create: `src/docs/slides/diagrams/producer-event-flow.mmd`
- Generate (committed, do not hand-edit): `assets/img/diagrams/who-does-what.svg`,
  `assets/img/diagrams/producer-event-flow.svg`

> **Controller note:** SVG generation runs `tools/build-diagrams.py` via the
> `slides-diagrams` skill (Playwright). The CONTROLLER performs the generation
> step (Playwright env), commits the SVGs, then this task's *authoring* of the
> `.mmd` sources is what a subagent does. Keep the `.mmd` faithful to the wiki
> Mermaid so the diagram matches documented procedure.

- [ ] **Step 1:** Author `who-does-what.mmd` from the Mermaid in `Who-does-what.md`
  (Producer / Director / Race Control read-only — the three-lane flowchart).
  Keep node text verbatim where possible.
- [ ] **Step 2:** Author `producer-event-flow.mmd` from the Mermaid in
  `Run-an-event.md` "The shape of an event": Prepare → Go live → Race →
  Interviews → Outro → Wrap up.
- [ ] **Step 3 (controller):** Generate both SVGs with the `slides-diagrams` skill
  (`tools/build-diagrams.py`); verify each `<name>.mmd` has a matching committed
  `assets/img/diagrams/<name>.svg`.
- [ ] **Step 4:** Commit: `feat(slides): add who-does-what + producer-event-flow diagrams`.

---

## Task 3: Live-preview capture (Overlay deck) — demo profile + obs-sim

**Files:**
- Create (committed): `src/docs/slides/assets/img/overlay-live-preview.png`

> **Controller-only task** (Playwright + running relay). Not a text subagent.

- [ ] **Step 1:** `racecast --profile demo graphics` (fetch the demo `Overlay.png`
  backdrop into `runtime/demo/graphics/`).
- [ ] **Step 2:** Start `tools/obs-sim.py` (stand-in OBS) on a free port; start the
  demo relay pointed at it via `RACECAST_OBS_WS_HOST/PORT` (no real OBS).
- [ ] **Step 3:** Open `http://127.0.0.1:8088/hud/preview` in Playwright at
  1280×720, screenshot it to `overlay-live-preview.png`. Verify the frame shows
  the demo HUD over the GT backdrop — **no Tailscale IP, no secrets**.
- [ ] **Step 4:** Tear down relay + obs-sim. Commit the PNG:
  `feat(slides): capture demo /hud/preview live-preview shot`.

---

## Task 4: Copy the reused wiki screenshots into the slides asset dir

**Files:**
- Copy: `src/docs/wiki/images/{cc-home,cc-setup,cc-crew-editor,console-landing,console-race-control,console-login,cc-overlay-builder}.png`
  → `src/docs/slides/assets/img/`

- [ ] **Step 1:** Copy the seven PNGs above into `src/docs/slides/assets/img/`
  (same basenames). These are current, accurate shots — no UI changed, so no
  re-capture needed (screenshot-discipline rule unaffected).
- [ ] **Step 2:** Commit: `chore(slides): vendor reused wiki screenshots for decks`.

---

## Task 5: Producer (event) deck — `producer.html`

**Files:**
- Create: `src/docs/slides/producer.html`

**Read first:** `src/docs/wiki/Run-an-event.md` (the producer checklist + event
shape) and `Control-Center.md` (Home dashboard / Start event).

**Linear slide outline** (`<body data-role="producer">`, copy the `<head>` +
script scaffolding verbatim from `director.html`, swapping title/role):

1. **Title** — "Producer (event day)". One line: you start and stop the show and
   keep the machine healthy; the director runs everything in between
   (`Who-does-what`).
2. **Your job in one sentence** — bring the station up, watch the machine, bring it
   down. Interviews: only the **last-part** producer joins Discord voice.
3. **The shape of an event** — blank line, then `![Event shape](assets/img/diagrams/producer-event-flow.svg)`.
4. **One-click bring-up** — open the Control Center, confirm the active league,
   press **Start event** (launches Tailscale, Discord, relay, OBS, Companion).
   Blank line, then `![Control Center Home](assets/img/cc-home.png)`. Link
   `Run-an-event`, `Control-Center`.
5. **~30 min before you go live** — the prep list distilled: update tool, reboot,
   Tools → Update all, refresh cookies, refresh media/graphics, Preflight → Run,
   Start event, enter the stream key in OBS. Link `Run-an-event`.
6. **Go live** — OBS on **Standby** → **Start Streaming**; the director opens with
   the Intro and cuts into the race look. From here the director runs the show.
7. **Who does what** — blank line, then `![Who does what](assets/img/diagrams/who-does-what.svg)`.
   One line that the director presses Feeds Next at each change; the producer just
   watches the machine. Link `Who-does-what`.
8. **Producer handover (12h/24h)** — incoming producer reads the on-air stint off
   A's panel/status, **Start event** with that stint, verify Feed A, start their
   own stream key, the YouTube redirect carries viewers over. Link `Run-an-event`,
   `Remote-access`.
9. **Interviews + Outro** — final-part producer **joins the Discord Interviews
   voice channel before race end** (OBS captures local Discord); director cuts to
   the Interview scene, then **OUTRO**. Link `Run-an-event`.
10. **When things go wrong** — `racecast preflight` first; common live fixes
   (feed won't show → cookies/deno; HUD blank → relay running; port in use →
   `racecast freeport`). Link `If-something-goes-wrong`.
11. **Stop + recap** — press **Stop event** (stops relay + Companion; OBS/Discord/
   Tailscale keep running). Recap the 3 producer beats. "Go deeper": `Run-an-event`,
   `Control-Center`, `Who-does-what`.

- [ ] **Step 1:** Write `producer.html` to the outline (faithful to the wiki).
- [ ] **Step 2:** Verify every image has a blank line before it and every wiki link
  uses the published-wiki URL base.
- [ ] **Step 3:** Commit: `feat(slides): producer (event) deck`.

---

## Task 6: Commentator deck — `commentator.html`

**Files:**
- Create: `src/docs/slides/commentator.html`

**Read first:** `Commentator-Cockpit.md`, `Console.md`, and the
"Commentators / streamers" section of `Who-does-what.md`.

**Linear slide outline** (`data-role="commentator"`):

1. **Title** — "Commentator". One line: you stream your stint on your own channel
   and the producer's relay pulls it in.
2. **Stream settings** — from `Who-does-what`: own YouTube/Twitch set **Unlisted**,
   **same channel** every event; **Low** latency (not Ultra-low); 1080p target,
   never below 720p; CBR, 2 s keyframes, hardware encoder; **no personal overlays**.
   Link `Who-does-what`.
3. **Streaming from a PlayStation (no PC)** — PS5 1080p60 + Unlisted on console;
   PS4 Pro 1080p / base PS4 720p; set **Low latency once, beforehand** on the
   channel (no console latency knob). Link `Who-does-what`.
4. **Send your watch link** — post your `youtube.com/watch?v=…` / `twitch.tv/<you>`
   link in the crew Discord before your stint, or **submit it from the cockpit**
   (your own stints only; lands as a pending request the director approves).
5. **Open your Console** — blank line, then `![The Console launcher](assets/img/console-landing.png)`.
   Sign in with Discord (or a personal link); the cockpit appears as a role card.
   Link `Console`, `Commentator-Cockpit`.
6. **Your cockpit** — program monitor, the big **YOU ARE ON AIR** / **UP NEXT ·
   stint N · in X handovers** tally, crew chat (as you), the race timer, submit a
   stream link. Link `Commentator-Cockpit`.
7. **Director cues** — **Info** = brief auto-fading toast (30 s); **Critical** =
   sticky banner you must **Acknowledge** (director then sees ✓ seen). You only get
   cues to you or **All talent**. Link `Commentator-Cockpit`.
8. **Recap / go deeper** — your channel settings + open the Console + watch the
   tally + acknowledge critical cues. "Go deeper": `Commentator-Cockpit`,
   `Console`, `Who-does-what`.

- [ ] **Step 1:** Write `commentator.html` to the outline.
- [ ] **Step 2:** Verify image blank-lines + wiki URL base.
- [ ] **Step 3:** Commit: `feat(slides): commentator deck`.

---

## Task 7: Race Control deck — `race-control.html`

**Files:**
- Create: `src/docs/slides/race-control.html`

**Read first:** the "Race Control" sections of `Who-does-what.md` and `Console.md`.

**Linear slide outline** (`data-role="race-control"`):

1. **Title** — "Race Control". One line: a **read-only** monitoring desk — watch the
   race without touching the broadcast.
2. **Read-only by design** — triggers **no broadcast actions**; the **director keeps
   full control**. The desk only watches. Link `Who-does-what`.
3. **What you see** — blank line, then
   `![Race Control desk](assets/img/console-race-control.png)`. live program
   preview, the **redacted** streamer/stint schedule (stream URLs never leave the
   tailnet), the race timer, crew chat (under your own name). Link `Console`.
4. **How the crew fits together** — blank line, then
   `![Who does what](assets/img/diagrams/who-does-what.svg)`. The role is
   **additive** — the same person can direct *and* run Race Control. Link
   `Who-does-what`.
5. **Getting in** — open the personal **Console** link the producer sends; the
   **Race Control** card appears for anyone flagged for it (Crew tab Race Control
   column / crew editor). Works over the tailnet or the public Funnel. Link
   `Console`, `Console-Setup`.
6. **Naming note + recap** — the `race_control` role ≠ the director-only HUD "Race
   Control" banner. Recap: read-only, redacted schedule, additive role. "Go
   deeper": `Console`, `Who-does-what`.

- [ ] **Step 1:** Write `race-control.html` to the outline.
- [ ] **Step 2:** Verify image blank-lines + wiki URL base.
- [ ] **Step 3:** Commit: `feat(slides): race control deck`.

---

## Task 8: Producer setup deck — `producer-setup.html`

**Files:**
- Create: `src/docs/slides/producer-setup.html`

**Read first:** `Set-up-the-broadcast-PC.md` and the `Control-Center.md` Setup
section.

**Linear slide outline** (`data-role="producer"`):

1. **Title** — "Producer setup (once per machine)". One line: ~30 min, then you're
   ready to run events.
2. **What you need** — modern PC (macOS/Win/Linux, 16 GB tight / 32 GB comfy),
   **wired** ≥ 25/10 Mbps (50/20 recommended), a YouTube login + the shared Sheet
   link. Link `Set-up-the-broadcast-PC`.
3. **Why download matters too** — the station pulls 2–3 feeds **in** while pushing
   one program **out**; the handover worst case is Feed A + B + POV down + program
   up at once. Wired only. Link `Set-up-the-broadcast-PC`.
4. **The easy way — the Setup wizard** — blank line, then
   `![Setup wizard](assets/img/cc-setup.png)`. Double-click `racecast-ui`, the
   **Setup** view walks every step with a checklist (`racecast init` is the CLI
   equivalent). Link `Control-Center`, `Set-up-the-broadcast-PC`.
5. **The steps** — get the tool, **install-tools** (yt-dlp/streamlink/ffmpeg/**deno**),
   **install-apps** (OBS/Companion/Tailscale/Discord), create the league profile
   (`SHEET_ID`), import the OBS scenes, import the Companion buttons. Link
   `Set-up-the-broadcast-PC`.
6. **Let Companion control OBS** — OBS → WebSocket Server (port 4455, password),
   enter the same password in Companion → connection goes **green**. Link
   `Set-up-the-broadcast-PC`.
7. **Connect remote directors (Tailscale)** — sign in (Linux: `sudo tailscale up`
   + `sudo tailscale set --operator=$USER`), invite directors (free, up to 6).
   Link `Set-up-the-broadcast-PC`, `Director-Setup`.
8. **Preflight + recap** — `racecast preflight` (Control Center Preflight → Run),
   fix anything flagged. "Go deeper": `Set-up-the-broadcast-PC`, `Control-Center`,
   then `Run-an-event` for event day.

- [ ] **Step 1:** Write `producer-setup.html` to the outline.
- [ ] **Step 2:** Verify image blank-lines + wiki URL base.
- [ ] **Step 3:** Commit: `feat(slides): producer setup deck`.

---

## Task 9: League Admin setup deck — `league-admin-setup.html`

**Files:**
- Create: `src/docs/slides/league-admin-setup.html`

**Read first:** `League-Owner-Setup.md`, `Profiles.md`, and the Crew section of
`Sheet-Webhook.md`.

**Linear slide outline** (`data-role="league-admin"`):

1. **Title** — "League Admin setup". One line: you own the Sheet + the crew roster
   + (optionally) Discord login, so producers just run the show.
2. **A league is a profile** — `profiles/<name>/profile.env` (`SHEET_ID`,
   optional `SHEET_PUSH_URL`, …); one machine runs several; hand a league to a new
   producer with `profile export` / `import` (carries `CONSOLE_SECRET`). Link
   `Profiles`.
3. **The Sheet drives everything** — schedule, HUD/overlay, timer all read the
   shared Google Sheet; the optional Apps Script webhook (`SHEET_PUSH_URL`) is the
   write-back path. Link `Sheet-Template`, `Sheet-Webhook`.
4. **Maintain the Crew tab** — blank line, then
   `![Crew editor](assets/img/cc-crew-editor.png)`. header
   `Name | Commentator | Director | Producer | Race Control | Discord`; flags grant
   `/console` access; edit by hand or via the Control Center crew editor (needs the
   `crew` webhook v7+). Link `League-Owner-Setup`, `Control-Center`.
5. **Discord login for /console (optional)** — blank line, then
   `![Console login](assets/img/console-login.png)`. create a Discord OAuth app
   (scope `identify`, not a bot), add `DISCORD_CLIENT_ID/SECRET` to `profile.env`,
   register the `…/console/oauth/callback` redirect URI per producer host. Link
   `League-Owner-Setup`.
6. **Share one URL** — post the single generic `…/console` link; roles resolve live
   per request (add/remove people on the Crew tab, effective immediately). Signed
   `racecast links` remain the fallback. Link `Console`, `League-Owner-Setup`.
7. **Revocation + recap** — blank a person's Crew row to remove access; `racecast
   console token revoke <name>` rotates a leaked signed link. "Go deeper":
   `League-Owner-Setup`, `Profiles`, `Sheet-Webhook`.

- [ ] **Step 1:** Write `league-admin-setup.html` to the outline.
- [ ] **Step 2:** Verify image blank-lines + wiki URL base.
- [ ] **Step 3:** Commit: `feat(slides): league admin setup deck`.

---

## Task 10: Overlay Package Designer deck — `overlay-designer.html`

**Files:**
- Create: `src/docs/slides/overlay-designer.html`

**Read first:** `HUD-Overlays.md` and the `Control-Center.md` Profile / Overlay
Builder section.

**Linear slide outline** (`data-role="overlay-designer"`):

1. **Title** — "Overlay Package Designer". One line: restyle the on-screen HUD
   (incl. the race timer + POV) per league — visually, no CSS required.
2. **One shared page, per-league look** — the relay serves the same `hud.html` for
   every league; a profile ships a small CSS override (`profiles/<name>/overlay/`)
   that **wins the cascade** — no forking. Link `HUD-Overlays`, `Profiles`.
3. **The visual Overlay Builder** — blank line, then
   `![Overlay Builder](assets/img/cc-overlay-builder.png)`. Control Center →
   Profile → Overlay Builder: click a slot, drag to move, drag handles to resize,
   set position/font/color/background in the property panel (fields pre-fill with
   the real template values). Link `HUD-Overlays`, `Control-Center`.
4. **Live preview with a running relay** — blank line, then
   `![Live HUD preview](assets/img/overlay-live-preview.png)`. **Save** writes the
   files, **Apply in OBS** reloads the browser source, **Preview ↗** opens the live
   `/hud/preview` (real base page + live sheet data over your `Overlay.png` frame).
   Link `HUD-Overlays`.
5. **Fonts** — a curated Google-Fonts set ships with every install; add more by name
   in General Settings (self-hosted into the machine-wide library); a league's
   fonts are copied into its `overlay/fonts/` on save so `profile export` stays
   self-contained. Link `HUD-Overlays`.
6. **First-override caveat + advanced CSS** — the very first override on a profile
   whose `overlay/` did not exist needs **one `racecast relay restart`**; later
   edits apply live via **Apply in OBS**. Advanced-CSS box = raw escape hatch
   appended after the generated rules; pairs with a per-league OBS collection
   (`GT Endurance Racing — <league>`). Link `HUD-Overlays`, `Profiles`.
7. **Recap / go deeper** — drag the slots, Save, Apply, Preview; ship it in the
   profile. "Go deeper": `HUD-Overlays`, `Control-Center`, `Profiles`.

- [ ] **Step 1:** Write `overlay-designer.html` to the outline.
- [ ] **Step 2:** Verify image blank-lines + wiki URL base + `data-role="overlay-designer"`.
- [ ] **Step 3:** Commit: `feat(slides): overlay package designer deck`.

---

## Task 11: Wire up the landing page (link all 7 cards + add the new one)

**Files:**
- Modify: `src/docs/slides/index.html`

- [ ] **Step 1:** Turn each of the five "Coming soon" cards into a live
  `<a href="…">Open walkthrough →</a>` pointing at the new deck files
  (commentator/producer/race-control/producer-setup/league-admin-setup).
- [ ] **Step 2:** Add a 7th card — **Overlay Package Designer**, accent
  `--overlay-designer`, `href="overlay-designer.html"`. Keep the existing card
  markup pattern.
- [ ] **Step 3:** Commit: `feat(slides): link all role decks on the landing page`.

---

## Task 12: Tests + structural guard (`tests/test_slides.py`)

**Files:**
- Modify: `tests/test_slides.py`

- [ ] **Step 1:** Extend the expected-deck list to include all seven deck files
  (director + the six new ones) and assert each has the required scaffolding
  (`data-role`, the Reveal `<script>` includes, the `assets/deck.css` link).
- [ ] **Step 2:** Assert the two new diagram `.mmd` files each have a committed
  `assets/img/diagrams/<name>.svg`, and that every referenced `assets/img/*` exists
  on disk (incl. the copied PNGs + `overlay-live-preview.png`).
- [ ] **Step 3:** Assert `index.html` links every deck file that exists (no dead
  card, no orphan deck).
- [ ] **Step 4:** Run `python3 tests/test_slides.py` → `ALL PASS`; run
  `python3 tools/lint.py`.
- [ ] **Step 5:** Commit: `test(slides): cover the six new decks + diagrams`.

---

## Task 13: Overflow guard (controller, pre-publish)

> **Controller-only**, via the `slides-overflow` skill (Playwright).

- [ ] **Step 1:** Run `tools/check-slides.py` over all seven decks (1280×720).
- [ ] **Step 2:** Fix any overflow (text trim / image already capped at 480px).
  Re-run until clean. Screenshot tour to eyeball each deck.
- [ ] **Step 3:** Commit any fixes.

---

## Task 14: Wiki cross-links + build verify

**Files:**
- Modify: `src/docs/wiki/{Run-an-event,Commentator-Cockpit,Console,Set-up-the-broadcast-PC,League-Owner-Setup,HUD-Overlays}.md`
  (add an "Onboarding deck ↗" link to the matching Pages deck, mirroring the
  Director page's pattern)
- Modify: `tools/build.py` (extend the slides verify assertion list if it pins
  specific deck files — keep it representative, not exhaustive)

- [ ] **Step 1:** Add a one-line deck cross-link near the top of each role/setup
  wiki page (published-wiki convention: link to the Pages deck URL).
- [ ] **Step 2:** If `build.py`'s verify hook pins deck filenames, add at least
  `index.html` already covered + one new deck; otherwise leave as-is.
- [ ] **Step 3:** Run `python3 tests/test_wiki.py` (link/anchor guard) and
  `python3 tools/run-tests.py`.
- [ ] **Step 4:** Commit: `docs(wiki): cross-link the new onboarding decks`.

---

## Final: whole-branch review + finish

- Dispatch the final whole-branch code review (most capable model) over the full
  branch diff; fix Critical/Important in one pass.
- Then `superpowers:finishing-a-development-branch` → push + PR; merge on green;
  dispatch `pages.yml` to republish.

## Self-review notes
- Spec coverage: 6 decks + the new accent + 2 diagrams + live-preview capture +
  index + tests + wiki links — all mapped to tasks 1–14.
- No invented procedure: every deck task names its source wiki page(s) and says
  "read first"; outlines paraphrase documented mechanism only.
- Type consistency: `data-role` slugs and accent var names match `deck.css`
  (Task 1) across Tasks 5–11.
