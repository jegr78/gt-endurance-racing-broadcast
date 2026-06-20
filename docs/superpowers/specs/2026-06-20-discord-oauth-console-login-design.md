# Discord OAuth login for /console — design

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — ready for implementation plan
**Issue:** (to be filed) — follow-up to #216 (role-based Funnel access)

## Problem

`/console` access today is distributed as **per-person signed bearer links**
(`racecast links` → `https://<magicdns>/console?t=<token>`). Each link *is* an
identity: whoever holds it gets that person's role. Distribution is manual
copy & paste, and `--post` dumps **all** links into the shared crew chat (every
link visible to everyone). Two problems:

1. **Effort** — hand-delivering N personal links is tedious.
2. **Mis-delivery / security** — a personal link sent to the wrong person hands
   them someone else's identity and role.

Goal: solve **both** — make distribution effortless *and* eliminate the
mis-deliverable bearer link.

## Approach

Add a **second front door** to the existing `/console` mount: **Discord OAuth2
login** (`identify` scope only — *not* a bot, no server install, no message
access). The producer distributes **one generic URL** `https://<magicdns>/console`
(broadcast-safe — fine to post in the crew channel). A crew member opens it,
clicks **"Login with Discord"**, and the relay resolves their Discord identity to
a crew role server-side. There is **no personal bearer link to mis-deliver**.

The key insight: the `/console` gate already derives everything (roles, pages,
policy, revocation) from one `subject` (a `streamer_key`) that it reads from the
signed token (query `?t=` or the auth cookie). **Discord OAuth only needs to
produce that same cookie.** Everything downstream is unchanged.

OAuth is **additive**: the existing signed-link flow stays as a fallback for
last-minute substitutes / guests / when OAuth is not configured. Nothing breaks.

### Identity model — decided

- **Match key:** Discord **username** (the unique @handle), case-insensitive.
  A rename fails *closed* (locked out, never impersonation); admin updates the
  cell.
- **Linking:** pure **admin Sheet prep**, no approval flow. The league Sheet's
  **Crew tab** is the single management surface for **roles + logins**:

  | Name | Commentator | Director | Producer | Discord |
  |------|-------------|----------|----------|---------|

- **Role resolution (A1 — union):** `resolve_roles` is extended so
  `commentator = (subject in live Schedule) OR (Crew.Commentator flag)`;
  `director`/`producer` come from the Crew flags as today. The Schedule still
  auto-grants commentator, which (a) keeps the signed-link fallback working for a
  last-minute commentator who is only in the Schedule, and (b) stays consistent
  with the schedule-driven cockpit ON-AIR/UP-NEXT tally. The explicit
  `Commentator` column is for people who should have cockpit access **before/
  without** a stint (pre-event, reserve).

### Per-league OAuth app — decided

Each **league/profile** registers its **own** Discord OAuth app. Credentials live
in `profiles/<name>/profile.env` as `DISCORD_CLIENT_ID` + `DISCORD_CLIENT_SECRET`
(travel with `profile export`, like `CONSOLE_SECRET`). This decentralizes auth:
each league owner sets up and manages their own login rail, independent of the
racecast maintainer. If the two keys are absent, OAuth is simply off (clean
fallback to signed links).

## Flow

1. Crew opens the one generic URL `https://<magicdns>/console`.
2. Launcher shows **"Login with Discord"** → `GET /console/login`.
3. `/console/login` → 302 to Discord `authorize` (scope `identify`); `redirect_uri`
   built from the request `Host` header (behind Funnel = the MagicDNS host),
   `state` signed with `CONSOLE_SECRET`.
4. Discord → `GET /console/oauth/callback?code=…&state=…`.
5. Relay verifies `state`, exchanges `code` → access token (server-side; the
   browser never sees `client_secret`), calls `/users/@me`, gets `username`.
6. Relay looks `username` up in the Crew **Discord** column → crew name →
   `streamer_key`. **Match:** mint the same token
   (`console_auth.mint_token` at the current `console-versions.json` version) →
   set the **`rc_console`** cookie `Path=/console` → 302 to `/console`. *From here
   it is identical to the existing link login.* **No match:** deny page naming the
   handle. **Error:** error page with retry.

**Constraints:**
- Discord OAuth works **only over Funnel** (Discord requires an HTTPS redirect).
  The tailnet path (`http://<ip>:8088/console`) keeps using the signed link /
  cookie — the distribution pain only exists in the public Funnel scenario anyway.
- `redirect_uri` is **host-specific** (Discord requires an exact registered match,
  no wildcards). Each producer host that runs the league registers its own
  `https://<magicdns>/console/oauth/callback` in the same app (one-time, like the
  Funnel nodeAttr step). A helper prints each host's exact line.

## Rename: cockpit → console (clean break, no fallback)

racecast has **no production use yet**, so no compat shims. Drawing the line
**"cockpit = the commentator's talent page; console = the auth umbrella + role
launcher":**

**Rename to console (console-wide auth/identity):**
- Cookie `rc_cockpit` → **`rc_console`** (no legacy dual-read).
- `src/scripts/cockpit_auth.py` → **`console_auth.py`** (`COOKIE_NAME`, all importers,
  `console_proxy.RELAY_COOKIE`).
- `src/scripts/cockpit_admin.py` → **`console_admin.py`**;
  `runtime/<profile>/cockpit-versions.json` → **`console-versions.json`** (the
  console-wide token-revocation store).

**Keep "cockpit" (the real talent product surface):**
- `src/cockpit/cockpit.html`, the `/cockpit/*` endpoint namespace, the
  "Commentator Cockpit" titles.
- `src/scripts/cockpit_submissions.py` (stream-link submission is a talent-cockpit
  feature).

All tests referencing `rc_cockpit` / `cockpit_auth` / `cockpit_admin` /
`cockpit-versions.json` update to the new names.

## Components

### New: `src/scripts/discord_oauth.py` (stdlib-only, pure + thin wrapper)
Pure, unit-testable helpers:
- `authorize_url(client_id, redirect_uri, state)` — build the Discord `authorize`
  URL (scope `identify`).
- `sign_state(secret, nonce, ts)` / `verify_state(secret, state, now, ttl)` —
  HMAC-signed CSRF `state`, **no server state** (TTL ~5 min).
- `parse_identity(user_json)` — extract `username` from a `/users/@me` response
  (pure, over raw JSON).
- `match_subject(username, crew_discord_map)` — `streamer_key` or `None`
  (case-insensitive).

The two real HTTPS calls (`code` → token POST to
`https://discord.com/api/oauth2/token`; `GET /users/@me`) are a **thin wrapper**
the relay invokes; response *parsing* stays in the pure helpers so tests run
offline (inject a fake transport/opener).

### Crew data model — `src/scripts/crew_source.py`
- Parse the new **`Commentator`** and **`Discord`** columns from the Crew tab
  (canonical header `Name | Commentator | Director | Producer | Discord`).
  Parsing is header-name based, so column order is not significant.
- Expose `discord_map()` → `{username_lower: crew_name}`.
- Expose the per-row `commentator` flag for the A1 union in `resolve_roles`.
- Degrade gracefully when the columns are absent (older Sheet) — surfaces the
  existing outdated-script path; OAuth login just finds no match.

### Relay endpoints (`src/relay/racecast-feeds.py`) under `/console`
These **are** the auth, so they run **before** the `_cockpit_auth()` requirement
in `_console_gate`:
- `GET /console/login` — 302 to Discord authorize when OAuth is configured; else
  404. Builds `redirect_uri` from the validated `Host` header; signs `state`.
- `GET /console/oauth/callback` — verify `state`; exchange code; fetch username;
  match; mint token + set `rc_console` cookie + 302; deny / error pages otherwise.

All best-effort: any failure renders a friendly HTML page; the relay never raises
(matching the `get_program_screenshot` / OBS-helper contract).

### Launcher (`src/console/console.html`)
Show **"Login with Discord"** only when OAuth is configured (a flag injected into
the page like `RC_API_BASE`). The signed-link flow is unchanged.

### Config plumbing (`src/racecast.py`)
- `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` in `profile.env` → injected as
  `RACECAST_DISCORD_CLIENT_ID/SECRET` (`_profile_env_vars` /
  `_apply_active_profile_env`) → passed to the relay handler at startup (like
  `console_secret`). Editable in `profile.env` directly or the Control Center
  Profile env editor.
- `racecast links` is **extended** (no separate command) to additionally print
  **(a)** the generic share URL `https://<magicdns>/console` and **(b)** the
  redirect URI to register `https://<magicdns>/console/oauth/callback`.

## Security

- `state` = `HMAC(CONSOLE_SECRET, nonce|ts)`, TTL ~5 min — CSRF-safe, stateless.
- `client_secret` never leaves the producer machine; only the relay performs the
  server-side code exchange. Scope strictly `identify` (no email/guilds/bot).
- `redirect_uri` derived from the `Host` header but validated to `https` + the
  machine's own MagicDNS host; Discord's exact registered-redirect match is the
  real guard.
- Callback lives under `/console`, so it stays inside the **only** Funnel-mounted
  prefix. Root control endpoints + OBS-WebSocket remain never funnelled.
- **Two revocation mechanisms, documented:** kill a *leaked link* = bump the
  version (`console-versions.json`, as today); remove a *person* = blank their
  Discord handle / role flags in the Crew tab → no match → no login. Bumping a
  version does **not** lock out the legitimate person — they log in fresh at the
  current version (correct: revoking a leaked link must not ban the person).

## Testing

- `tests/test_discord_oauth.py` (new, pure): `authorize_url`; `sign/verify_state`
  (valid / expired / tampered); `parse_identity`; `match_subject`
  (hit / miss / case-insensitive).
- `discord_map` parsing + the A1 union in `resolve_roles` (commentator from Crew
  flag OR Schedule) — `tests/test_roles.py` / `tests/test_console.py`.
- Relay endpoints (`tests/test_cockpit.py` / `tests/test_console_gate.py`):
  `/console/login` redirects when configured / 404 when not; callback with a
  **stubbed** code-exchange + identity (injected fake transport) → sets
  `rc_console` cookie + 302; no-match → deny; bad state → 400.
- **Rename fallout:** every test referencing `rc_cockpit` / `cockpit_auth` /
  `cockpit_admin` / `cockpit-versions.json` → new names.
- e2e: OAuth needs Discord and is **not** exercised (can't reach Discord in CI);
  the signed-link path stays covered. The rename must keep the synthetic e2e green.

## Docs & Wiki (same-change deliverable)

- New **League-Owner / Admin** section: `src/docs/` operator material + a new wiki
  page (e.g. `League-Owner-Setup.md`, or extend the role-based-Funnel-access page).
  Content: create the Discord OAuth app, fill `profile.env`, register the
  redirect URI per producer host, maintain the Crew tab (Discord handles + role
  flags incl. the new `Commentator` column), and the share-URL-vs-link model +
  the two revocation mechanisms.
- **Screenshot rule (CLAUDE.md):** the Control Center Profile view gains Discord
  fields → refresh the matching `cc-*.png`; the `/console` launcher gains the
  "Login with Discord" button → refresh its wiki image. Both in the same change,
  captured from a local dev build.

## Out of scope / YAGNI

- No Discord **bot** (no server install, no intents, no message access).
- No DM delivery (a webhook can't DM; a bot is explicitly unwanted).
- No on-disk identity store / `discord-links.json` — identity binding lives in the
  Sheet, the session in the cookie.
- No director/producer approval flow for claims — pure admin Sheet prep.
- No OAuth over the tailnet path (HTTPS-only; Funnel scenario only).
