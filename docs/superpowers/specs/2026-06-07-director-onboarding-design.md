# Director Onboarding — Design

**Date:** 2026-06-07
**Status:** Approved

## Problem

A new director gets a Tailscale invite and two URLs — and the wiki gives them no
path from "I got a link" to "I see the panel":

- **No director-facing setup page.** `Director.md` says "make sure Tailscale is
  running and you've accepted the producer's invite" and points to the
  *producer's* machine-setup page. Installing the Tailscale app, accepting the
  invite, and bookmarking the right URLs is undocumented for the one persona
  that cannot help themselves with the CLI.
- **`Director.md` is Companion-first.** The page opens with the button board;
  the panel — which runs in any browser with zero import steps and (since the
  Live Failure Visibility feature) carries the health banners and feed state —
  reads like an appendix.
- **The Feature-1 panel additions are undocumented.** Status banners, the
  LIVE/CONN feed pills, the health line, the RELOAD confirmation, the NEXT
  debounce, and the `FEEDS → STINT…` rename exist in the panel but nowhere in
  the wiki; two pages still say `SET STINT…`.
- **Director troubleshooting is written for the producer.** "Run
  `iro tailscale status`" is not something a director on a tablet can do.
- **The URLs are buried.** The panel URL appears only in `iro relay status`
  output, the tablet URL only when Companion starts. `Run-an-event.md` claims
  "`iro event start` prints the URL — just forward it", which is only
  indirectly true today.

Persona review (non-technical director) drove the scope. Feature 2 of 3.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Doc weighting | **Panel-first**: the restructured `Director.md` describes the browser panel as the primary path; the Companion button board stays fully documented as an equal alternative. Pure doc weighting — which path a crew uses is their call (mechanism only, no invented procedure). |
| Setup-page device scope | One shared 3-step path (install Tailscale → accept invite → bookmark URLs) with short platform notes only where platforms differ — iPad/iPhone, Android, Windows, macOS, **and Linux** (Linux note: distro package or tailscale.com/download/linux; may need `sudo tailscale up` in a terminal). |
| `iro event start` URL block | Prints **both** director URLs (panel `:8088/panel` + Companion tablet `:8000/tablet`) as a copy-paste block before the readiness report, with a one-line note that panel scene/audio control also needs the OBS WebSocket password. Without a Tailscale IP it prints a "directors cannot connect remotely" notice instead. |
| Troubleshooting location | Director-view "If you cannot connect" section lives on `Director-Setup.md` (only checks a director can perform themselves, each ending in "ask your producer to run …"). The producer-view table in `If-something-goes-wrong.md` stays and links to it. |
| Feature-1 panel docs | Documented in this feature (director-facing): banners, pills, health line, guards, `FEEDS → STINT…`. Feature 3 covers only the producer pages. |
| OBS WebSocket password | Explicitly documented as the key difference between the two paths: the **panel** needs the password from the producer for scene/audio control (entered once in the panel header — IP, port 4455, password; the browser remembers it via localStorage; FEEDS/TIMER/HUD/URLs work without it). **Companion buttons** need no password — the OBS connection lives on the producer's machine. |

## Architecture

Docs-heavy feature: two wiki pages (one new, one restructured), one small CLI
addition, and a set of cross-reference fixes.

```
src/docs/wiki/Director-Setup.md   NEW   connect-only: 3 steps + director-side troubleshooting
src/docs/wiki/Director.md         RESTRUCTURED  panel-first guide incl. Feature-1 panel docs
src/iro.py                        event_start prints "Share with your directors" block
src/scripts/event.py              pure helper director_urls(...) — unit-tested
Run-an-event.md, Who-does-what.md,
Home.md, _Sidebar.md,
If-something-goes-wrong.md        cross-reference + SET STINT fixes
```

### 1. New page: `Director-Setup.md`

Goal: a director with browser skills (no CLI) goes from "I got a link" to "I
see the panel" in 5 minutes, asking the producer only for the documented
inputs (invite, URLs, optionally the OBS WebSocket password).

Sections:

1. **What you need** — a device with a browser (tablet, laptop, or phone), the
   producer's Tailscale invite, the two URLs from the producer. One sentence on
   what Tailscale is ("a private network app — it makes the producer's machine
   reachable from your device, nothing else").
2. **Step 1: Install Tailscale** — shared path; platform lines only for the
   install source: iPad/iPhone (App Store), Android (Play Store),
   Windows/macOS (tailscale.com/download), Linux (distro package or
   tailscale.com/download/linux, may need `sudo tailscale up` in a terminal).
3. **Step 2: Accept the invite** — tap the producer's invite link, sign in with
   your own account, done when the app shows "Connected". The page says only
   "your producer sends it" — who invites is the team's call.
4. **Step 3: Bookmark your two pages** — table: `http://<producer-ip>:8088/panel`
   = director panel (everything in one browser tab),
   `http://<producer-ip>:8000/tablet` = Companion buttons. `<producer-ip>` comes
   from the producer (`iro event start` prints both URLs ready to forward —
   cross-reference). Recommend a bookmark / home-screen icon. Note at the panel
   URL: "Using the panel for scene/audio control? Ask your producer for the OBS
   WebSocket password too — you enter it once at the top of the panel."
5. **If you cannot connect** — director-view table, only self-checkable items:
   Tailscale app on and "Connected"? · right URL (a `100.x` address, not
   localhost)? · device signed into the same Tailscale account that was
   invited? · panel loads but shows the red "RELAY UNREACHABLE" banner?
   (= you ARE connected; the problem is on the producer side) · panel loads but
   scene/audio buttons stay grey or ON AIR shows "OBS OFFLINE"? (check IP /
   port 4455 / password in the panel header, press Connect). Each row ends in
   the matching "ask your producer to run `iro tailscale status` / `iro status`".
6. Closing link: "Connected? → [Director guide](Director) for what the buttons do."

### 2. Restructured page: `Director.md` (panel-first)

New order; the workflow content is unchanged in substance:

1. **Intro** — "you direct from a browser" + link to Director-Setup for
   connecting. New short section **"Panel or Companion buttons?"**: both drive
   the same show; panel = one page with everything incl. status/health;
   Companion = big buttons, good for muscle memory / Stream Deck; the explicit
   password difference (see Decisions); *which path your crew uses is your
   call* (mechanism, not a rule).
2. **The director panel** (promoted above the Companion tables) — bus overview
   (PGM/FEEDS/HUD/SCN·VIS/GFX/TIMER/AUDIO/URLs; align with — don't duplicate —
   the table in Run-an-event) **plus the Feature-1 panel documentation**:
   - Status strip: pills `A S3 · LIVE` (green) / `CONN` (amber), the FEEDS
     health line, the "connecting … for 0:47 — stream may not be live yet"
     warning after 30 s;
   - Banners: red RELAY UNREACHABLE / SHEET SYNC FAILED, amber COOKIES N H
     OLD — what each means and who acts (banner = tell the producer; CONN =
     usually the streamer isn't live yet);
   - Guards: RELOAD asks for confirmation, NEXT is locked for 3 s after a
     press;
   - `FEEDS → STINT…` re-targets the feeds (≠ the HUD row's `STINT LABEL`).
3. **The Companion button board** — existing page-1/page-2 tables unchanged,
   framed as the equal alternative.
4. **HUD row / URLs section** — existing sections, editorially adjusted to the
   panel-first layout; the stale `SET STINT` at ~line 66 becomes
   `FEEDS → STINT…`.
5. **Workflow sections** (Through the broadcast / At a driver change / POV /
   Interviews) — unchanged in substance; where only a Companion button is
   named, the panel equivalent is added (e.g. "**Feeds Next** (Companion) /
   **NEXT** (panel)"). POV step 4 simplifies: the panel health line now shows
   the POV state directly — `/status` stays mentioned as the alternative.

### 3. CLI: "Share with your directors" block

After the "Waiting for the launched services…" section and **before** the
readiness report (which ends in `SystemExit`), `event_start` prints:

```
Share with your directors:
  Director panel:     http://100.x.y.z:8088/panel
  Companion buttons:  http://100.x.y.z:8000/tablet
  (panel scene/audio control also needs the OBS WebSocket password —
   OBS → Tools → WebSocket Server Settings)
```

- Tailscale IP from the existing `_tailscale_ip()`; tablet port from the
  Companion config (same source as the existing `companion status` extra,
  fallback 8000).
- Without a Tailscale IP, print instead:
  `Tailscale not connected — directors cannot connect remotely (iro tailscale up).`
- The line assembly is a pure helper in `src/scripts/event.py`
  (`director_urls(ts_ip, companion_port) -> list[str]`, returning the printable
  lines), unit-tested with `100.64.0.0/10` test constants — no real IPs, same
  convention as the existing classifier tests.

### 4. Cross-reference fixes (carry-overs)

| Location | Change |
|---|---|
| `Run-an-event.md` FEEDS bus row (~88) | `SET STINT…` → `FEEDS → STINT…` |
| `Run-an-event.md` step 9 + panel section | director-reachability mentions link to **Director-Setup**; the "prints the URL" claim now matches the real block |
| `Who-does-what.md` | "via Companion — no machine access" → "from a browser (panel or Companion buttons) — no machine access" + Director-Setup link |
| `_Sidebar.md` | new entry **Director setup** under "For operators" (before Director guide) |
| `Home.md` "Pick your path" | director line becomes: first time → Director-Setup, then → Director guide |
| `If-something-goes-wrong.md` | "The director can't connect" gains a pointer to Director-Setup's director-side checks |

## Testing

- New unit test for the URL-block helper (both cases: with / without a
  Tailscale IP) in `tests/test_event.py` — pure function, no network, no
  real IPs.
- Existing suite, `tools/lint.py`, and `tools/build.py` (verify step) stay
  green.
- Wiki pages: review-read for broken intra-wiki links (`[…](Director-Setup)`
  etc.); publication happens after merge via `python3 tools/sync-wiki.py`.

## Out of scope (deliberate)

- Producer docs consolidation, glossary, "Terminal in 60 seconds",
  "what you should see now" checkpoints, screenshots of the new panel
  surfaces — all Feature 3. The existing screenshots stay; no placeholder
  images are added.
- Companion button renames or config changes (separate export artifact).
- Any statement about *who* invites directors or *which* control path a crew
  must use — the docs describe mechanism only.
