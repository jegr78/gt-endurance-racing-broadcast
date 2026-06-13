# Twitch Relay Parity — Design

**Date:** 2026-06-13
**Status:** Approved
**Issue:** #105 — Follow-up: review Twitch support across the relay (channel_url, cookies, bare-ID path)

## Problem

The SSRF fix (security finding #4, PR #106) extended the relay's URL validation so
that **full Twitch watch URLs** (`https://www.twitch.tv/<channel>`) pass `is_channel`
and flow through `yt-dlp -g` → `streamlink`. The host allow-list in `_is_stream_url`
now accepts `twitch.tv` / `*.twitch.tv` alongside YouTube. Everything else in the relay
stayed YouTube-centric:

- `channel_url()` wraps a bare `UC…` ID into `youtube.com/channel/<id>/live`; Twitch has
  no equivalent bare-ID form.
- The cookie / bot-check pipeline (`cookies.txt`, `--cookies-from-browser`,
  `export_cookies` with a hardcoded YouTube URL, the 12 h rotation warning) is
  YouTube-only.
- The pull pipeline runs `yt-dlp -g <url>` → raw HLS → `streamlink <hls>` for **every**
  feed. For a raw `.m3u8` Streamlink uses its **generic** HLS plugin, never the Twitch
  plugin — so Twitch's automatic ad-filtering and low-latency handling would be lost
  (ad segments leak into the OBS feed).
- Docs/comments ("commentator YouTube stream per stint", CLI help, README, CLAUDE.md,
  wiki) assume YouTube.

YouTube is the predominant platform; Twitch is occasional. The goal is **full parity**:
Twitch treated as a first-class platform end-to-end (resolve strategy, auth, low-latency,
panel UX, docs), without regressing the YouTube path.

## Goal & non-goals

**Goal:** A Twitch feed works as reliably and is as operable as a YouTube feed —
correct resolve strategy, working low-latency, a concrete authentication path for gated
streams, platform-aware panel/UX, and complete docs. Clean and reliable, no fragile
shortcuts.

**Non-goals:**
- A Twitch bare-name short form (`<channel>` → `twitch.tv/<channel>`). Full URLs are the
  norm for **both** platforms; the bare `UC…` YouTube form is kept only for backward
  compatibility.
- Removing yt-dlp from the YouTube path (its bot-check + deno JS challenge + cookies
  handling is exactly what makes YouTube reliable).
- A reliable YouTube server-side (DAI/SSAI) ad **remover** — none exists; we detect and
  warn instead (see Known limits).

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| How far to support Twitch | **Full parity** — first-class platform end-to-end. |
| Bare-name short form for Twitch | **No.** Full URLs are the documented norm for both platforms. `channel_url()` keeps the bare `UC…`→YouTube wrap for backward compatibility only. |
| Resolve strategy | **Per-platform dispatch.** YouTube → `yt-dlp -g` → `streamlink <hls>` (unchanged). Twitch → `streamlink twitch.tv/<name>` **direct** (Twitch plugin resolves + filters ads + low-latency). |
| Twitch ad filtering | Rely on Streamlink's **automatic** Twitch ad filtering. Do **not** pass the deprecated `--twitch-disable-ads`. |
| Twitch low-latency | `--twitch-low-latency` + `--hls-live-edge 2` (overrides the global `4`) on the Twitch branch only. |
| YouTube ads | Inherent CSAI bypass (yt-dlp resolves the content manifest; client-side player ads are not in it). **Plus** SSAI/DAI marker **detection → `/status` warning** (no skip). |
| Twitch auth model | **OAuth token**, not a Netscape cookies file. Streamlink wants `--twitch-api-header "Authorization=OAuth <token>"` where the token is the `auth-token` cookie of a logged-in twitch.tv browser. |
| Twitch feed type (public vs gated) | Unknown / varies. **Public is the default** (no auth). The auth path is built concretely now (CLI + Control Center + guide), not deferred — but never required. |
| Cookie filename | Rename `cookies.txt` → **`yt-cookies.txt`** (consistent now that a Twitch file exists), with legacy `cookies.txt` fallback + one-time migration. Twitch file: `twitch-cookies.txt`. |
| Producer accounts | Wiki/docs recommend the producer keep **both** a logged-in YouTube and a Twitch account ready (YouTube mandatory for the bot-check; Twitch for gated feeds). |

## Architecture — per-platform resolve dispatch

A new pure helper `platform_of(url) → "youtube" | "twitch"` (host-based, reusing the
existing `_is_stream_url` host logic) drives a branch in the `Feed` pull loop. The
branch and the auth decision happen **per pull** (when a feed picks up the stint's URL),
not once at `Feed` construction — because one feed (A/B) serves different stints over
time and a stint may be YouTube or Twitch.

| | **YouTube branch** | **Twitch branch** (new) |
|---|---|---|
| Resolve | `yt-dlp -g` (bot-check, deno, cookies) → HLS URL | no yt-dlp |
| Ad detection | `manifest_has_ssai_markers(text)` on the resolved manifest → on hit, set `youtube_ssai_warning` in `/status` (no skip) | n/a (Twitch plugin filters automatically) |
| Serve | `streamlink <hls> best` | `streamlink twitch.tv/<name> best` **direct** |
| Extra flags | — (inherent CSAI bypass) | `--twitch-low-latency --hls-live-edge 2` |
| Hardening | `--` before the URL (unchanged) | `--` before the URL (unchanged) |

Properties:
- `resolve_hls()` is only called on the YouTube branch. The Twitch branch hands the
  `twitch.tv` URL straight to the Streamlink serve command — no yt-dlp hop.
- `streamlink_serve_cmd()` gains an optional `platform` parameter that appends the Twitch
  flags. Pure, unit-testable argv construction; `--` stays before the positional URL.
- `channel_url()` is unchanged: bare `UC…` → YouTube (backward compat); full URLs pass
  through (the new norm for both platforms).
- `manifest_has_ssai_markers(text)` is best-effort and non-fatal: a network/parse failure
  leaves the feed running normally — the warning is a bonus reliability signal, never a
  blocker. Exact marker catalog (SCTE-35 `EXT-X-CUE-OUT`, ad-class `EXT-X-DATERANGE`) and
  probe cadence (once at resolve vs. periodic re-probe) are a research item for the plan.

## Cookies / Auth

### Rename `cookies.txt` → `yt-cookies.txt`

~105 references across `src/ tools/ tests/ .github/ README.md CLAUDE.md` (grep the whole
repo per the CLAUDE.md hard rule before changing any flag/name).

- Canonical name becomes `yt-cookies.txt`; `racecast cookies firefox` writes it.
- **Backward compatible:** auto-detect prefers `yt-cookies.txt`, falls back to legacy
  `cookies.txt`, and migrates once (rename + notice). Existing installs (including the
  `~/Documents/racecast` test environment) keep working.
- `cookie_health` / 12 h rotation warning / preflight `cookies_status` use the new name
  with the legacy fallback.

### Twitch auth — OAuth token (first-class, not a hook)

Twitch authentication is an OAuth token, **not** a Netscape cookies file. Model:

- **Storage:** `twitch-cookies.txt` (Netscape export limited to `twitch.tv`), symmetric
  with `yt-cookies.txt`. File mode `0600` (live session credential).
- **Pure extractor:** `twitch_oauth_from_cookies(text) → token | None` pulls the
  `auth-token` value. The Twitch serve command builds
  `--twitch-api-header "Authorization=OAuth <token>"` from it.
- **New CLI:** `racecast cookies twitch <browser>` — exports via
  `yt-dlp --cookies-from-browser <browser>` filtered to twitch.tv into
  `runtime/twitch-cookies.txt`. Mirror of `racecast cookies firefox`. Same Windows
  Chrome/Edge app-bound-encryption caveat → Firefox recommended.
- **Control Center:** General Settings gains a second row "Twitch login (optional)" next
  to the YouTube cookie refresh — same browser picker + status (present / age / missing).
- **Default stays public:** if `twitch-cookies.txt` is absent, Twitch runs without auth.
  No dead path, no requirement.

### `cookies_for(platform, runtime) → path | None`

Replaces the single `self.cookies` threading. Pure, testable (platform + runtime dir in,
path/None out, no network):

| Platform | Behavior |
|---|---|
| YouTube | `yt-cookies.txt` from the runtime dir (legacy `cookies.txt` fallback). No behavior change. |
| Twitch | `twitch-cookies.txt` if present, else `None` (public). |

`export_cookies()` / `--cookies-from-browser` startup auto-export stay YouTube-only (the
hardcoded YouTube probe URL remains). `Feed`'s external interface stays stable; only the
`(platform, cookies)` decision moves into the pull loop.

## Panel UX & Docs

**Panel:**
- Schedule/POV stream-entry help text: "YouTube **or** Twitch — full watch URL", with an
  example for each host.
- Per-feed platform badge (`YT`/`TW`) from `/status`, plus the `youtube_ssai_warning`
  when set — so operators immediately see which source a stuck feed is on.

**Docs/Wiki** (change "YouTube" → "YouTube/Twitch" wherever the mechanism means both):
- Relay header comment, CLI help (`--cookies`, the `cookies` subcommand), `README.md`,
  `CLAUDE.md`, wiki onboarding.
- **New wiki "Producer accounts" section + pre-event checklist:** recommend the producer
  keep both a logged-in **YouTube** and **Twitch** browser session ready — YouTube for the
  bot-check / `yt-cookies.txt` (mandatory), Twitch for `twitch-cookies.txt` (only for
  gated feeds, but set up ahead avoids event-day stress). Mirrored into `src/docs/`
  (Setup Guide) and the cookie-refresh section.
- Describe the **mechanism** only (what the logins enable); whether/when a league uses
  Twitch is a team decision, not asserted (CLAUDE.md: never invent crew rules).

## Testing

stdlib style (each file a runnable script, no pytest). Likely a new
`tests/test_platform.py` plus additions to existing files:

- `platform_of(url)` — YouTube/Twitch hosts, `youtu.be`, case-insensitivity, the
  userinfo trick (`https://youtube.com@evil.com/`).
- `streamlink_serve_cmd(..., platform)` — Twitch appends `--twitch-low-latency` /
  `--hls-live-edge 2`, YouTube does not; `--` stays before the URL.
- `manifest_has_ssai_markers(text)` — SCTE-35 / ad-`DATERANGE` positive, clean manifest
  negative, garbage → `False` (non-fatal).
- `cookies_for(platform, runtime)` — YouTube = `yt-cookies.txt` (+ legacy `cookies.txt`
  fallback), Twitch = `twitch-cookies.txt` | `None`.
- `twitch_oauth_from_cookies(text)` — extracts `auth-token`, missing → `None`.
- Existing `is_channel` / bind tests stay green.

After changes: `python3 tests/test_pov.py`, `python3 tools/lint.py`, and
`python3 tools/build.py` (its verify step is the closest thing to CI).

## Known limits (documented, not built against)

- **YouTube DAI/SSAI ads are detected and warned, not removed** — no reliable
  open-source skip for server-side YouTube ads exists; a pattern-matching skipper would
  break on every YouTube change. The clean solution remains an ad-free source
  (league-owned, unlisted, unmonetized stint streams). The detection warning is the
  safety net for the rare monetized-third-party case.
- **Twitch ad filtering relies on Streamlink's automatic behavior** → note a minimum
  Streamlink version in preflight/docs; `install-tools` pulls current anyway.
- **No Twitch `channel_url` short form** — the full URL is the norm for both platforms.

## Out of scope / future

- Automated Twitch auth-token refresh / rotation warning (YouTube-style). Twitch tokens
  do not rotate on the YouTube 12 h cadence; revisit only if gated Twitch feeds become
  common.
- Server-side YouTube ad removal (see Known limits).
