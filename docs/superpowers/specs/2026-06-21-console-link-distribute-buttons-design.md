# Crew Console: distribute the landing-page link (Copy / Post to Discord)

**Date:** 2026-06-21
**Status:** Design approved

## Problem

The Control Center's **Crew Console** view lets a producer copy *per-person*
`/console` launcher links (each carrying a signed token). What it lacks is a
one-click way to distribute the **shared** public landing-page link
`https://<magicdns>/console` — the role-adaptive launcher where any crew member
signs in (Discord OAuth or their personal link). Today the producer has to look
up their own MagicDNS host by hand to share that URL.

## Goal

Add two general buttons to the **Public access (Tailscale Funnel)** section of the
Crew Console view:

1. **Copy Link** — copy `https://<magicdns>/console` to the clipboard.
2. **Post to Discord** — post that link to the league's Discord channel (with an
   `@here` ping).

The link points at the **shared landing page** (no token). The existing per-member
"Copy funnel link" buttons are untouched.

## Non-goals

- No per-person/token variant of these two buttons (that already exists per row).
- No new Discord integration config: reuse the existing per-league
  `DISCORD_WEBHOOK_URL` (the same webhook used for broadcast-health alerts).
- No change to funnel enable/disable or revocation flows.

## Design

### 1. Backend — expose the shared link in console status

`console_status()` in `src/racecast.py` already resolves the MagicDNS host via
`_tailscale_magicdns()` to build the per-member funnel links. Add **one field** to
its returned payload:

- `console_url`: `https://<magic>/console`, or `""` when MagicDNS is unavailable.

No new Tailscale logic; reuse the already-resolved `magic` value.

### 2. New endpoint — `POST /api/console/post-link`

In `src/ui/ui_server.py`, mirror the existing `POST /api/console/funnel`
pattern (in `do_POST`): dispatch to `ctx["console_post_link"]()` and return its
`{ok, error?}` dict as JSON. No request body is required — the **server** computes
the link itself (never trusts a client-supplied URL).

### 3. Handler — `console_post_link()` in `src/racecast.py`

Registered in the UI context dict alongside `console_status` / `console_funnel`.

Behavior (best-effort, never raises — matches the rest of racecast):
1. Resolve the active profile config → `discord_webhook_url`; resolve MagicDNS →
   `console_url`.
2. `{"ok": False, "error": "No DISCORD_WEBHOOK_URL configured for this league"}`
   when the webhook is empty.
3. `{"ok": False, "error": "MagicDNS unavailable — is Tailscale up?"}` when there
   is no MagicDNS host.
4. Otherwise build the payload via the pure helper (below) and `POST` it to the
   webhook with `urllib`. On HTTP/network failure return
   `{"ok": False, "error": "<detail>"}`; on success `{"ok": True}`.

### 4. Pure helper — `console_link_discord_payload(console_url, league_name)`

Lives in `src/scripts/console_admin.py` (the console domain module). Returns the
Discord webhook JSON dict:

- `content`: an `@here` ping + a short message + the link, e.g.
  `"@here 🎙️ **Crew Console** — open the launcher and sign in with Discord or your personal link: <https://magic/console>"`
  (league name woven in when non-empty).
- `allowed_mentions`: `{"parse": ["everyone"]}` so the `@here` actually pings
  (the `"everyone"` parse type covers `@here`), set explicitly rather than relying
  on Discord's default parsing.

Pure and deterministic → unit-tested.

### 5. Front-end — `src/ui/control-center.html`

In the **Public access (Tailscale Funnel)** section of the `console` view:

- Add **Copy Link** and **Post to Discord** buttons.
- `loadConsole()` stores `consoleUrl` from the `/api/console/status` payload.
- **Copy Link**: pure client-side `navigator.clipboard.writeText(consoleUrl)` with
  brief "Copied ✓" button feedback — no server round-trip.
- **Post to Discord**: `POST /api/console/post-link`; show inline success/error
  (reuse the existing `cp-err` error surface; brief success feedback on the button).
- Both buttons are **disabled with a hint** when `consoleUrl` is empty (no MagicDNS
  / Tailscale down).

### 6. Wiki screenshot (CLAUDE.md hard rule)

The Crew Console is a Control Center view, so its `cc-*.png` under
`src/docs/wiki/images/` is now stale. Regenerate it from a **local dev build**
(no `VERSION` stamped, per project convention) via a Playwright **element**
screenshot of the Crew Console view, committed in the same change.

## Testing

- `tests/test_console.py` (or the matching console test file): unit-test
  `console_link_discord_payload` — `@here` present, link present, league name
  woven in, `allowed_mentions` set.
- `tests/test_ui_server.py`: `POST /api/console/post-link` dispatches to the ctx
  handler; `GET /api/console/status` payload includes `console_url`.
- Run `python3 tools/lint.py` and `python3 tools/run-tests.py`.

## Trust boundary note

Nothing here widens the public surface: the link is the already-public
`/console` mount; the Discord post happens **server-side** from the producer's
machine using a secret already in `profile.env`; the webhook URL never reaches the
browser.
