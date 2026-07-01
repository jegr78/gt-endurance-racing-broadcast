# Sheet-driven OBS Stream Target (Service + Key per Producer Part)

**Date:** 2026-07-01
**Status:** Design — awaiting review

## Problem

A producer streams the finished program out of OBS to the league's single event
channel (YouTube **or** Twitch). An event is split into **Parts**, and each Part is
a separate live event on that platform with its **own stream key**. Today the same
producer, doing two Parts back-to-back, must stop the broadcast, paste a **new stream
key** into OBS by hand, and go live again — the key having been sent to them by
Discord DM per Part.

We want to drive OBS's stream **service** and **stream key** from the Sheet, per
Producer Part, so the producer no longer hand-pastes keys — **without** exposing any
stream key in cleartext to Sheet *viewers* (the whole crew has view access to the
league Sheet; only the league owner is an editor).

## Non-goals

- No automatic switching of a **live** output. The key/service is only ever set while
  OBS streaming is **stopped**. Racecast never stops or starts the broadcast itself.
- No per-Part *platform* switching. An event stays on one platform (one `Channel`).
- No new machine/profile secret. We reuse the existing `SHEET_PUSH_URL`.
- No custom cryptography. The keys are never placed in Sheet cells, so nothing needs
  encrypting there.

## Trust boundary (the security core)

| Store | Who can read it | What lives there |
|---|---|---|
| Sheet cells (CSV export) | anyone with the Sheet/CSV link — **incl. viewers** | Part → **key reference** (e.g. `key1`), plaintext, non-secret |
| Apps Script Script Properties | **editors only** (Extensions → Apps Script) = league owner | `ref → stream key` (the secret) |
| `SHEET_PUSH_URL` (capability URL) | whoever holds the URL — in `profile.env`, gitignored, **not** in the Sheet | the bearer secret that gates `get_stream_key` |
| OBS `service.json` | the producer's own machine | the applied key (unavoidable; replaces the Discord DM) |

Viewers see only the **reference** in the Sheet. The **key** lives in Script
Properties, which only Sheet editors (the owner) can open — verified against the
league's real access model (owner = editor, everyone else = viewer). Racecast fetches
the key at switch time over the already-secret `SHEET_PUSH_URL` (HTTPS), so no new
secret and no key ever reaches a viewer-readable surface.

## Data model

### `Producer` tab — new optional column
`src/scripts/producer.py` already parses `Part | Producer | MagicDNS` into
`{part, producer, magicdns}` rows. Add an **optional** `Stream Key` column carrying the
**reference** (not the key):

- New headers constant `PRODUCER_STREAMKEY_HEADERS = ("stream key", "streamkey", "key ref", "stream key ref")`.
- Located like the others but **optional**: absent → `stream_key: ""` on every row.
  The three existing columns stay REQUIRED (unchanged); adding a 4th required column
  would break every already-deployed Sheet / released v1.1.0 (backward-compat rule).
- Row dict gains `"stream_key"`.

### `Channel` tab — reused, unchanged
`broadcast_chat.parse_channel_tab` already yields `[(platform, channel)]` with
`platform ∈ {"youtube","twitch"}` (explicit `Platform` column or inferred from the
URL). The first/only row's platform is the event's OBS service. No change to that
parser; racecast reads it to pick the service.

### Apps Script Script Properties — owner-maintained
`ref → key`, e.g. `key1 = live_xxx`, `key2 = live_yyy`. Only the reference and the
key; **no platform** (platform comes from `Channel`). Maintained by the owner in the
Apps Script UI (Project Settings → Script Properties).

## Webhook: new `get_stream_key` action

The existing Apps Script web app (behind `SHEET_PUSH_URL`) gains one read action.
It is protected exactly like today's write actions: knowledge of the capability URL.

Request (POST JSON, same shape as existing pushes):
```json
{ "action": "get_stream_key", "ref": "key1" }
```
Response (echoes the action, per `check_webhook_response`):
```json
{ "ok": true, "action": "get_stream_key", "key": "live_xxx" }
```
Failure modes returned as `{ "ok": false, "action": "get_stream_key", "error": "..." }`:
- unknown `ref` → `"no key for ref 'key1'"`
- outdated script (no action echo) → handled by existing `check_webhook_response`
  ("webhook script outdated — redeploy").

The Apps Script never returns the full property map; it looks up **one** ref. The key
is returned over HTTPS and is **never echoed into any Sheet cell**.

## Flow

1. Producer picks their Part in the Control Center Home takeover list (**exists
   today**) → the selected Part's `stream_key` reference is known to racecast.
2. Producer triggers **Set Stream Target** (Control Center button + CLI
   `racecast stream set <part>`):
   1. **Guard:** read OBS `GetStreamStatus`. If `outputActive` is true →
      **error to the producer**: "OBS is streaming — stop the broadcast before
      changing the stream target." Nothing is changed.
   2. Resolve `service` from the `Channel` tab platform
      (`youtube` → `YouTube - RTMPS`, `twitch` → `Twitch`).
   3. Resolve `ref` from the selected Part row; `POST get_stream_key{ref}` to
      `SHEET_PUSH_URL` → `key`.
   4. `SetStreamServiceSettings(rtmp_common, {service, server:"auto", key})` on OBS.
   5. Report success (service + Part label + **"stream key set ✓"** — the key value
      is **never** displayed, only the confirmation that one was applied).
3. The producer goes live in OBS deliberately.
4. **Two Parts back-to-back:** after Part 1, the producer stops the broadcast and
   re-runs Set Stream Target selecting their next Part (ref `key2`) — one takeover,
   two key applies.

## Code changes

### `src/scripts/obs_ws.py`
- Pure builder `stream_service_payload(platform, key)` →
  `("rtmp_common", {"service": <name>, "server": "auto", "key": key})`,
  mapping `youtube`/`twitch` → the OBS service names; unknown platform → a clear
  `ValueError` (caller turns it into a producer-facing error, never a crash).
- `get_stream_service_settings(...)` / `set_stream_service_settings(platform, key, ...)`
  — thin wrappers over `.request()`, same best-effort "never raise; `_connect()` None →
  descriptive note" contract as `set_stream`/`set_input_volume`.
- Reuse/extend the stream-status read (a `stream_is_active(...)` helper over
  `GetStreamStatus.outputActive`) for the guard.

### Relay / CLI (`src/relay/racecast-feeds.py`, `src/racecast.py`)
- A `get_stream_key(push_url, ref)` client next to `post_webhook`
  (POST `{action, ref}`, parse via `check_webhook_response`, return the key or an
  error). Relay-side, dependency-light, its own UA — consistent with `post_webhook`.
- `racecast stream set <part>` CLI: resolve part → ref (Producer tab) + platform
  (Channel tab), run the guard, fetch key, apply. Prints the service + Part label +
  a "stream key set ✓" confirmation only — never the key value.

### Control Center (`src/ui/`, `src/racecast_ui.py`)
- A **Set Stream Target** action on the Home/takeover surface, using the already-shown
  Part selection. Wired to the same resolve→guard→fetch→apply path. On the
  stream-active guard it shows the error inline.

### Apps Script (documented, owner-applied)
- The `get_stream_key` action + the Script-Properties setup documented in the
  `Sheet-Webhook` wiki page. Not shipped code (it lives in the league's Sheet).

## Security invariants (must hold)

- The stream key is **never** written to any Sheet cell, log line, or racecast state
  file. CLI/UI/log output **never** shows the key value — only a "stream key set ✓"
  confirmation.
- `get_stream_key` returns exactly one ref's key and only to a caller holding the
  `SHEET_PUSH_URL`. No enumeration endpoint.
- Service/key are applied **only** when OBS streaming is stopped (hard guard).
- OBS-WebSocket is never funnelled; this whole path is producer-machine-local plus the
  HTTPS webhook fetch.

## Graceful degradation (backward compat — v1.1.0 is released)

Every missing piece degrades with a clear message and changes nothing else:
- No `Stream Key` column / blank ref on the Part → "no stream-key reference for this
  Part".
- No matching Script Property → webhook `ok:false` → surfaced verbatim.
- Outdated Apps Script (no `get_stream_key`) → existing outdated-script message.
- OBS unreachable → best-effort note (like every other `obs_ws` helper).

Existing timer/panel webhook writes and the current `Producer`-tab Home card are
unaffected.

## Testing

- `test_streams`/new: `stream_service_payload` platform→service mapping + unknown
  platform `ValueError`.
- `test_obsws`: `set_stream_service_settings` request shape + the stream-active guard
  (fake socket), matching the existing `set_stream` test style.
- Producer parser: optional `Stream Key` column present/absent (required trio still
  enforced).
- Webhook: `get_stream_key` request/response parsing incl. `ok:false` and
  outdated-script.
- Wiki `Sheet-Webhook`: the `get_stream_key` action + Script-Properties recipe.
- Any Control Center UI change refreshes `cc-*.png` per the CLAUDE.md wiki-screenshot
  rule (dev build).

## Open questions

None blocking. Director-Panel exposure is intentionally out of scope (producer-output
concern, not a director/commentator surface).
