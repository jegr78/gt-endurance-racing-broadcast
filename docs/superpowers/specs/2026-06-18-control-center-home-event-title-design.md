# Control Center Home — editable Event Title

**Date:** 2026-06-18
**Status:** Design approved
**Builds on:** #207 (free-text event title across Director Panel, Cockpit & Discord)

## Problem

The free-text event title (#207) can be set three ways today: the profile default
`EVENT_TITLE` (`profiles/<name>/profile.env`), the launch flag
`racecast event start --title "…"`, and a **live inline editor in the Director Panel**
(`/panel`, persisted to `runtime/<profile>/event.json`).

The Control Center Home view — the producer's primary local control surface — neither
displays nor edits the title. A producer who lives in the Control Center has to know
about a second surface (the Panel) to change the round label. Expectation gap: the
title looks like it is "only a profile env var".

## Goal

Add a **display + inline-edit** field for the live event title to the Control Center
**Home** view, so the title can be set/changed from the Control Center without opening
the Director Panel — whether the relay is running or stopped.

Non-goal: editing the profile *default* `EVENT_TITLE` from Home (that stays in the
Profile view's env editor). Non-goal: Sheet sync (the title is producer-side runtime
state, deliberately never written to the Sheet, per #207).

## Background — how the title flows today

- The relay owns the live title via `EventTitleStore` (`src/relay/racecast-feeds.py`),
  persisted to `runtime/<profile>/event.json`. Startup precedence:
  `event.json` (if present, even blank) > profile default `EVENT_TITLE` > empty.
- The relay exposes `POST /event/title` (`{"title": …}` → `{"ok": True, "title": …}`)
  and includes `event_title` in `GET /status`.
- `sanitize_event_title(raw)` + `EVENT_TITLE_MAX` (relay module) are the single
  normalization rule (strip control chars, trim, cap length). Every surface renders
  the title as a text node — never HTML.
- The **Director Panel** is served by the relay (same origin), so it edits the title by
  POSTing straight to `/event/title`.
- The **Control Center** is a *separate* server (`src/ui/ui_server.py`, port 8089). It
  already reads the relay's `/status` over localhost (`relay_live_data` in
  `racecast.py`) but has **no write path** to the relay and currently ignores
  `event_title`.
- `takeover()` in `racecast.py` already writes `event.json` directly (before bring-up)
  via `_event_title_path()` — the pattern the relay-down write path mirrors.

## Design

### Backend providers (`src/racecast.py`)

Two pure-ish provider functions with injection seams (matching the existing
`relay_live_data` / `*_data` providers), wired into the `run_ui` `ctx` dict.

**Read — `event_title_read_data(fetch=None, alive=None, read_file=None, default=None)`**
→ served at `GET /api/event-title`.

- If the relay is alive (`_relay_is_alive()`): GET `/status`, return its `event_title`
  (authoritative live value), `source: "relay"`.
- Else: read `runtime/<profile>/event.json`; if it has a string `title`, return it with
  `source: "file"`. If the file is absent/corrupt, fall back to the active profile's
  `EVENT_TITLE` default (`ResolvedConfig.event_title`), `source: "default"`.
- Returns `{"title": str, "source": "relay"|"file"|"default", "relay_alive": bool}`.
- Never raises; on any error returns the profile default (or "") with a degraded source.

**Write — `event_title_write_data(value, alive=None, post=None, write_file=None)`**
→ served at `POST /api/event-title` (`{"title": …}`).

- Sanitize `value` via `sanitize_event_title` loaded from the relay module
  (`_load_relay_module`) — one source of truth for the rule and `EVENT_TITLE_MAX`,
  no duplication/drift.
- If the relay is alive: `POST /event/title` to the relay (updates the live in-memory
  store *and* persists `event.json` in one place). Return the relay's stored title.
  Path `"relay"`.
- Else: write `runtime/<profile>/event.json` as `{"title": sanitized}` directly
  (mirrors `takeover()`: `os.makedirs(dirname, exist_ok=True)` + `json.dump`). The next
  `event start` adopts it via `EventTitleStore` startup precedence. Path `"file"`.
- Returns `{"ok": True, "title": sanitized, "applied": "relay"|"file"}`; on failure
  `{"ok": False, "error": …}`.

Rationale for the relay-up vs relay-down split: a running `EventTitleStore` only loads
`event.json` at startup, so a direct file write while the relay is live would *not*
update the in-memory store — the title would silently differ until restart. Therefore
relay-up must go through `/event/title`, relay-down writes the file.

### UI server routes (`src/ui/ui_server.py`)

- `GET /api/event-title` → `ctx["event_title_read"]()`.
- `POST /api/event-title` → `ctx["event_title_write"](body.get("title"))`, behind the
  existing `_allowed` + `request_csrf_ok` gates, `_json` responses with the same
  malformed-body / 500 handling as `/api/env`.
- `ctx` gains `"event_title_read"` and `"event_title_write"` in `run_ui`.

### Home view (`src/ui/control-center.html`)

- A new `<section>` at the top of `data-view="home"` (directly under the `viewhead`,
  before the services section): one row labelled **"Event title"** showing the current
  title (or a muted placeholder when empty) and a ✎ edit affordance.
- Inline editor mirrors the Panel: click ✎ → text input (maxlength = `EVENT_TITLE_MAX`,
  same placeholder example as the Panel) → Enter saves (POST `/api/event-title`),
  Esc cancels. Title rendered via `textContent` (XSS-safe).
- Loaded when entering Home and refreshed alongside the existing Home/`relay-live`
  refresh, so it reflects a Panel edit or a relay (re)start without a manual reload.

### Separation of concerns (unchanged)

Home edits the **live** title (`event.json` / running relay). The profile **default**
`EVENT_TITLE` remains editable only in the Profile view's env editor. Same two-layer
model as the Panel today.

## Testing

- **`tests/test_event_title.py`** (extend) — the two new providers:
  - read precedence: relay alive → relay value; relay down + file present → file value;
    relay down + no file → profile default.
  - write: relay alive → POSTs to `/event/title` (seam asserts the call + returns its
    title); relay down → writes `event.json` with the sanitized title.
  - sanitization applied on write (control chars stripped, length capped) — reuse the
    relay rule so the cap matches.
  - never-raises behaviour on a failing seam.
- **`tests/test_ui_server.py`** (extend) — `GET /api/event-title` returns the provider
  payload; `POST /api/event-title` calls the write provider and echoes its result;
  CSRF/`_allowed` gate rejects a cross-origin POST.

## Wiki screenshot (CLAUDE.md hard rule)

The Home view changes, so `src/docs/wiki/images/cc-home.png` is stale and MUST be
regenerated **in this change** from a local dev build (run `racecast ui` from `src/`,
no `VERSION` stamped), as an element screenshot of the Home view matching the existing
framing.

## Out of scope (YAGNI)

- Editing the profile default from Home.
- Any Sheet write of the title.
- Validation UI beyond the existing sanitization.
- A second copy of `sanitize_event_title` in the Control Center layer (load the relay's).
