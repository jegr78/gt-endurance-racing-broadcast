# Wiki Restructure — Operator-First, Technical Reference Separated

**Date:** 2026-06-04
**Status:** Design approved, ready for planning

## Problem

The GitHub wiki (`src/docs/wiki/`, published via `tools/sync-wiki.py`) is written at a
developer's level of detail. That is fine for the maintainer but too technical for the
people who actually run a broadcast — the **producer** (at the machine) and the **remote
director**. They need plain "what to do" guidance, not architecture and ports.

A secondary issue: OS-specific instructions are inconsistent. Windows and macOS are named
in several places (Installation, Home, Runbook, OBS-Setup, Troubleshooting, Relay-Mode);
**Linux is never mentioned**, and some entries name only one OS (e.g. "No Discord audio
(macOS)" with no Windows/Linux counterpart).

## Goals

1. **Operator-first.** The main, front-and-center documentation is a simple, task-oriented
   guide for producers and directors — reduced to the essentials, plain language.
2. **Keep all technical depth, just separated.** Existing technical content moves into a
   clearly delimited "Technical reference" chapter at the back. Nothing is deleted; the
   maintainer still finds everything.
3. **Add simplified high-level diagrams** for the overview and the key flows (no ports, no
   tool names).
4. **Consistent OS coverage.** Windows, macOS, and Linux are treated as supported and
   named together everywhere an OS matters — never one alone. Unverified Linux specifics
   are labelled honestly.

Non-goals: changing the toolkit behaviour; translating to other languages (docs stay
**English** per the project rule — the team is international); redesigning `sync-wiki.py`.

## Audience

- **Producer** — runs the broadcast on the station: one-time setup, then start → run →
  stop at the event. Non-developer.
- **Remote director** — drives scenes/graphics via Companion over Tailscale; never touches
  the machine internals.
- **Maintainer (developer)** — the reader of the Technical reference chapter.

## Information architecture

Two-tier sidebar (`_Sidebar.md`): operators first, technical reference clearly separated
at the bottom.

```
### IRO Broadcast

Start here
  - Home                       (overview + big-picture diagram)

For operators
  - Set up the broadcast PC
  - Run an event
  - Director guide
  - Who does what
  - If something goes wrong

Technical reference
  - Architecture
  - Relay (how the feeds work)
  - OBS & scenes
  - Companion (button config)
  - Configuration & secrets
  - Static mode
  - Build & maintenance
```

### Operator pages (new / heavily simplified)

| Page (file) | Purpose — plain "what to do" | Diagram |
|---|---|---|
| **Home** (`Home.md`) | 4–5 sentences: what this is, who does what, "pick your role" links to the two operator journeys. | **Big picture** |
| **Set up the broadcast PC** (`Set-up-the-broadcast-PC.md`, repurposes `Installation.md`) | One numbered walkthrough: install tools → fill `.env` → import the OBS collection → import Companion → get YouTube cookies → run preflight. Practical gotchas only (Discord windowed, OBS permission). Deep "why" linked to the technical chapter. | — |
| **Run an event** (`Run-an-event.md`, repurposes `Runbook.md`) | The producer's event page: a simple start → go live → stints & handovers → interviews → stop checklist. | **Event timeline** + **Handover (simple)** |
| **Director guide** (`Director.md`) | For the remote director: which scenes/buttons to use, the handover button, interviews. Plain language. | (references Who-does-what) |
| **Who does what** (`Who-does-what.md`, repurposes `Roles.md`) | Producer vs director responsibilities side by side. | **Who does what** |
| **If something goes wrong** (`If-something-goes-wrong.md`, repurposes `Troubleshooting.md`) | Common problems in everyday language (HUD blank → is the relay running?, a feed won't appear, no Discord audio, lag). | — |

### Technical reference chapter (content preserved, relocated/consolidated)

All current depth is retained, grouped at the back. Source → target:

| Target page | Keeps / absorbs |
|---|---|
| **Architecture** (`Architecture.md`) | The 4 detailed Mermaid diagrams, topology, relay ping-pong internals, control flow, ports table. (Already exists — stays technical.) |
| **Relay (how the feeds work)** (`Relay-Mode.md`) | `yt-dlp → streamlink` pull pipeline, endpoints, cookies, HUD serving (`/hud`), POV PiP. |
| **OBS & scenes** (`OBS-Setup.md`) | Scene collection internals, the HUD overlay technicals, tokenization round-trip, Discord audio source details. |
| **Companion** (`Companion.md`) | Building/exporting the button config, the round-trip. |
| **Configuration & secrets** (`Configuration.md`) | `.env`, tokens (`__IRO_ASSETS__`, `__IRO_TIMER__`), `setup-assets.py`, security. |
| **Static mode** (`Static-Mode.md`) | The public-stream fallback internals. |
| **Build & maintenance** (`Build-and-maintenance.md`, repurposes `Maintaining-this-Wiki.md`) | `build.py`, repo structure, OBS/Companion round-trips, **publishing this wiki**. |

Operator pages link "for the full detail, see <technical page>"; technical pages link back
"to just run it, see <operator page>." No content is duplicated — the operator version is
the short path, the technical version is the reference.

## The four new operator diagrams

Simple Mermaid, deliberately free of ports, tool names, and jargon.

1. **Big picture** (`Home`) — Commentators → the producer's PC ("mixes video + audio") →
   YouTube, with Producer and Director drawn as the two people involved.
2. **Event timeline** (`Run an event`) — left-to-right: Prepare → Go live → Stints &
   driver changes → Interviews → End.
3. **Who does what** (`Who does what`) — two columns, Producer (at the PC) vs Director
   (remote), each with their tasks.
4. **Handover (simple)** (`Run an event`) — two feeds taking turns "on air", swapped by a
   button at each driver change — the principle only, no `/next`, no yt-dlp.

The four existing **detailed** Mermaid diagrams stay in **Architecture** unchanged.

## OS coverage policy

Windows, macOS, and Linux are treated as supported and named **together** wherever an OS
matters — never one alone. Applies to: tool install commands, OBS Discord-audio capture,
YouTube-cookie export, and update commands.

- **Install:** macOS `brew …`; Windows `winget …` / `pip install -U …`; Linux
  `brew …` or the distro package manager (`apt`/`dnf`) + `pip install -U …`.
- **Discord audio in OBS:** macOS = *App Audio Capture* (`sck_audio_capture`); Windows =
  *Application Audio Capture (BETA)*; Linux = *Application Audio Capture* (PipeWire) or an
  *Audio Output Capture* monitor source.
- **Cookies:** macOS Keychain / Safari Full Disk Access; Windows/Linux browser export.
- Anything not verified on Linux is labelled **"should work — not yet tested on Linux."**
- **`CLAUDE.md` update:** change the stated target from "Windows or macOS" to "Windows,
  macOS, or Linux" so the codebase guidance and the docs agree. (The relay and scripts are
  pure cross-platform Python; the external tools all run on Linux.)

## Mechanics / constraints

- **English only** (project hard rule), but simplified, plain English on the operator pages.
- **No content loss:** technical material is moved, not removed; cross-linked both ways.
- **Page renames/removals** are handled by `tools/sync-wiki.py`, which mirrors the source
  and deletes wiki pages no longer present (verified: it tracks `removed` and `os.remove`s
  them). Renamed files (`Installation.md` → `Set-up-the-broadcast-PC.md`, etc.) therefore
  cleanly replace the old pages.
- **Internal links** use the new page names; update every cross-reference and `_Sidebar.md`.
- **Verification:** after publishing, re-check the rendered pages on GitHub — Mermaid
  diagrams render (watch for syntax pitfalls like `;` in notes), tables render, no broken
  internal links, sidebar groups correct.

## File changes summary

- Rewrite/simplify (operator): `Home.md`, `Installation.md`→`Set-up-the-broadcast-PC.md`,
  `Runbook.md`→`Run-an-event.md`, `Director.md`, `Roles.md`→`Who-does-what.md`,
  `Troubleshooting.md`→`If-something-goes-wrong.md`.
- Keep/relabel (technical): `Architecture.md`, `Relay-Mode.md`, `OBS-Setup.md`,
  `Companion.md`, `Configuration.md`, `Static-Mode.md`,
  `Maintaining-this-Wiki.md`→`Build-and-maintenance.md`.
- `_Sidebar.md` — new two-tier grouping.
- `CLAUDE.md` — target-platform line includes Linux.
- Apply the OS policy across all pages.

## Out of scope

- Changing any toolkit behaviour or scripts (docs only, plus the one `CLAUDE.md` line).
- New diagrams beyond the four agreed.
- Non-English translations.
