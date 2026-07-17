# Residential egress fallback for cloud events — design

**Status:** design (not scheduled for build)
**Date:** 2026-07-17
**Related:** the AWS YouTube bot-flag incident (2026-07-17), `#493` robust-ingest quality
tiers, `RACECAST_FEED_FANOUT`. Feed pull pipeline in `src/relay/racecast-feeds.py`.

## Problem

When the cloud producer box runs in a datacenter (AWS/GCP), YouTube can flag the box's
**egress IP range** with a bot-check ("Sign in to confirm you're not a bot"). On
2026-07-17 this was verified on the real relay resolve path against a live stream, across
two IPs (a stop/start rotates the box's public IP because there is no Elastic IP) and every
`player_client` override, with fresh cookies + deno — i.e. a **region-wide, hard** block
that fresh cookies and IP rotation do not clear. A flagged range means **no YouTube feed
resolves**, which kills the broadcast. The only reliable escapes are a **non-flagged
residential egress IP** or **Twitch** (never bot-checked).

That day the event was saved by producing from a home Mac (residential IP). This spec
pre-stages that escape so a flagged datacenter range can no longer kill an event: route the
relay's YouTube **feed pulls** through a residential egress, on demand, without moving the
whole broadcast off the cloud box.

## Goals / non-goals

**Goals**
- A **pre-configured, reactive** fallback that sends only the relay's `yt-dlp`/`streamlink`
  feed pulls through a residential proxy, keeping the OBS RTMP broadcast on the cloud uplink.
- **Fully automatic** activation: the relay detects the bot-flag and enables the fallback
  itself (no operator action required mid-event).
- Fit a modest home uplink (~20 Mbps up, measured) by **capping feed quality to 720p** while
  the fallback is active.
- A code-free **Tailscale exit-node runbook** as a secondary escape for the rare
  "whole region flagged, including non-YouTube egress" case.

**Non-goals (deferred / out of scope)**
- **Own-feed-over-tailnet direct ingest** — when the producer commentates from home, the box
  could pull that one feed straight from the home Streaming PC over the tailnet (no YouTube
  round-trip, no double home-uplink transit). Real win, but a distinct feature → **separate
  follow-up spec**.
- Auto-revert while flagged (see Detection).
- Changing the broadcast (RTMP) egress path — it stays on the cloud uplink.

## Approach

**A — scoped residential proxy for feed pulls (primary, this spec).** A small HTTP(S) proxy
(tinyproxy/squid) runs on a residential Tailnet node (e.g. the home Streaming PC). The relay
injects `HTTPS_PROXY` into **only** the feed-pull subprocess environment (the existing
`external_tool_env()` seam in `services.py`, already used for every spawned external tool),
so `yt-dlp` (manifest resolve) and `streamlink` (segment fetch) egress via the residential
IP. RTMP, Discord, Sheet and everything else are untouched.

**B — Tailscale exit-node (secondary, runbook only, no code).** `tailscale up
--exit-node=<home-node>` routes **all** box egress via home. Simpler but the home uplink then
carries the full broadcast RTMP too. Kept as a documented manual escape hatch for the rare
case where non-YouTube datacenter egress is also blocked.

The proxy **endpoint is a plain config value**, so a paid residential/mobile proxy service
drops in with zero code change (same `HTTPS_PROXY` knob) for events with no reliable home
node — at the cost of routing the league's YouTube cookies through a third party.

## Components

### Config (machine `.env`, alongside `RACECAST_FEED_FANOUT`)
- `RACECAST_FEED_PROXY` — the residential proxy endpoint on a **home/local Tailnet node**,
  e.g. `http://100.115.69.85:8888` (the home Streaming PC). **Empty ⇒ the fallback is
  disabled** (nothing pre-staged ⇒ nothing automatic). This is a machine/transport knob,
  never a league setting.
- **Endpoint choice — home/local proxy only (decided).** A **paid residential/mobile proxy**
  and a **mobile/4G** egress are **rejected**: metered per-GB proxies are billed by data, and
  the AWS box is **flagged more often than not** right now, so the fallback would fire on most
  events, not rarely — the cost is effectively continuous, not bounded to occasional incidents.
  A self-hosted home/local residential proxy has no per-GB cost and is therefore the only
  endpoint this design targets. (The knob stays a plain URL, so a paid endpoint remains
  *technically* droppable-in, but it is not a supported path here.) Rejected egress options
  (verified): a PO-token provider (tested on the flagged AWS box, no effect on the live-HLS
  bot-flag) and consumer VPNs (Nord/CyberGhost exit via datacenter/known-VPN ranges that
  YouTube flags harder than plain cloud).
- `RACECAST_FEED_PROXY_AUTO` — default **on**; `=0` makes the fallback manual-only (for events
  where the home uplink cannot take it).
- Quality cap is a fixed 720p tier while active (reuses `#493` tiers); a constant, not a knob,
  unless a later need surfaces.

### Home proxy (operator runbook, one-time)
tinyproxy (or squid) on a residential Tailnet node, **bound to the node's Tailnet IP**, with
HTTPS `CONNECT` tunneling allowed (yt-dlp/streamlink talk TLS to googlevideo). The tailnet is
the trust boundary — no public exposure. Documented in the cloud runbook and the wiki
"Remote producer" page.

### Relay
- **Env injection:** when the fallback is active, add `HTTPS_PROXY`/`HTTP_PROXY` to the feed
  subprocess env only (via `external_tool_env()` / the feed-cmd env). Off ⇒ unchanged direct
  pulls. Pure builder for the env delta → unit-tested.
- **Segment fetcher must be proxied too (live-HLS caveat):** for a LIVE stream the
  bytes are fetched by **streamlink** (and ffmpeg), not just yt-dlp's manifest resolve — an
  env-only `HTTPS_PROXY` may not reach it, so yt-dlp would resolve via the proxy while
  streamlink pulls segments directly and stays flagged (yt-dlp #17165). Pass streamlink
  `--http-proxy`/`--https-proxy` explicitly (and ffmpeg as needed) when active, not just the
  env var. Both the resolve AND the segment fetch must egress residential.
- **Quality cap:** while active, clamp each feed's quality tier to **720p** so the proxied
  bytes fit the home uplink. Reuses the existing tier machinery; removed when the fallback
  turns off (which, per Detection, is only at the next `event start`).
- **State:** `Relay.feed_proxy_active` (bool), settable by the detector and the manual
  override, surfaced in `/status`.

### Detection (fully automatic, session-sticky)
- Reuse the existing feed-diagnostic classifier to recognise the **bot-check** signature
  ("Sign in to confirm you're not a bot") distinctly from a normal not-live / transient
  failure.
- Trip after **N consecutive bot-check failures** across feeds (hysteresis, so a single
  transient blip does not flip it). Pure `should_enable_feed_proxy(recent_failures, …)` →
  unit-tested.
- **No auto-revert probing.** A direct (non-proxy) resolve against a flagged IP prolongs the
  flag (the "no outbound probes during an event" lesson). So once enabled, the fallback
  **stays on for the rest of the session** and resets on the next `event start`.
- Requires `RACECAST_FEED_PROXY` to be set **and** `RACECAST_FEED_PROXY_AUTO` on; otherwise
  auto is a no-op and the relay only emits today's bot-flag warning.

### Control & observability
- **Status:** `feed_proxy` (active bool + endpoint host, never the full URL) in `/status` and
  the Control Center.
- **Manual override / kill switch:** force on/off via CLI (`racecast feed proxy on|off`) and a
  Director-Panel / Control-Center control — needed because "fully automatic" can saturate the
  home uplink while the producer is also commentating.
- **On switch:** a single **log line** (INFO) — `feed proxy fallback ON — feeds 720p via
  <host>` — plus the status flag. **No Discord `@here`** (deliberately quiet).

## Data flow & bandwidth (home uplink ~20 Mbps up)

| Phase (fallback ACTIVE, producer also commentating) | Home UP |
|---|---|
| Single feed on air (720p ≈ 3 Mbps) | own stream 5.5 + proxied pull 3 ≈ **8.5** |
| Handover overlap A+B (both 720p) | 5.5 + 3 + 3 ≈ **11.5** |

Comfortably under 20. When the producer's own feed is the on-air feed, it transits the home
uplink twice (once as the original upload to YouTube, once as the proxied pull back to the
box) — the motivation for the deferred own-feed-over-tailnet path. **Inactive** (the normal
case, IP not flagged): the home uplink carries nothing but the producer's own stream, exactly
as today.

## Failure handling

- **Proxy node down while active:** feeds resolve neither directly (flagged) nor via the proxy.
  The relay must surface this **loudly** (red health + the existing bot-flag path), never
  silently fall back to direct (which would just re-hit the flag). The kill switch + runbook B
  are the manual escape.
- **No endpoint configured:** auto is a no-op; behaviour is exactly today's (a bot-flag
  warning, feeds fail).
- **False-positive detection:** the N-consecutive + classifier hysteresis guards against a
  transient blip flipping the fallback; the kill switch reverts a mistaken activation.

## Testing

- Pure, unit-tested: `should_enable_feed_proxy` (hysteresis trigger), the feed-env proxy-delta
  builder (proxy present only when active; absent otherwise), the 720p tier clamp while active,
  and `.env` parsing (`RACECAST_FEED_PROXY`, `RACECAST_FEED_PROXY_AUTO`).
- Live validation (maintainer): a real tinyproxy on a home Tailnet node, the box forced into
  the fallback, confirming feeds resolve via the residential IP and the broadcast RTMP stays on
  the cloud uplink.

## Runbook (B — exit-node, no code)

Advertise the exit node on the home node (`tailscale up --advertise-exit-node`, approve in the
admin console), then on the box `tailscale up --exit-node=<home-node>`. All box egress
(including RTMP) then flows via home — use only when non-YouTube egress is also blocked.
Revert with `tailscale up --exit-node=`.
