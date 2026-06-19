# Phase 8 spike — Companion buttons over Funnel (relay-proxied)

*Spike for issue #216 phase 8 (spec §I). Goal: decide whether a token-gated
`/console/buttons` route that the relay reverse-proxies to Bitfocus Companion is
worth building, or whether Phase 8 should be deferred to its own issue. This is a
feasibility assessment — no production code.*

## Question

Spec §I proposes a director-gated `/console/buttons` route that the relay
reverse-proxies to Companion's local port (only after `_console_auth` passes), so a
remote director without a Tailscale account can drive the physical Companion button
UI over the public Funnel. The spec flagged it **spike-first** and the strongest
candidate to split off, because the relay is pure stdlib (no framework) and
Companion's UI is socket.io/WebSocket-heavy.

## What was investigated

1. **Companion's web transport** — what `/tablet` + the web-buttons UI actually require.
2. **The relay's proxy capability** — can a stdlib `BaseHTTPRequestHandler` /
   `ThreadingHTTPServer` (the relay's server, `src/relay/racecast-feeds.py:70,2879`)
   reverse-proxy that traffic, including the WebSocket upgrade?
3. **Path-prefix compatibility** — the epic mounts **only** `/console` on Funnel
   (`tailscale.funnel_args` → `--set-path=/console`), so Companion would have to live
   under `/console/buttons/*`.
4. **Incremental value** — what a remote director already gets over Funnel without it.

## Findings

### F1 — Companion has no base-path support → a sub-path mount is fundamentally broken (BLOCKER)

Companion's frontend (the React admin **and** `/tablet`/web-buttons) hardcodes
**root-absolute** URLs: static assets resolve to `/…` and the realtime channel is
`/socket.io/`. There is no "base URL / sub-path" configuration — this is a long-standing,
unresolved upstream limitation (bitfocus/companion #2255: serving Companion under an
nginx sub-path like `/companion/` "loads blank because every resource still points to
`/`").

Consequence for us: mounting Companion under `/console/buttons/` cannot work without the
proxy **rewriting every HTML/JS/CSS/socket URL on the fly** (root-absolute → `/console/
buttons`-relative), including inside minified bundles and the Engine.IO handshake. The
single Funnel mount is `/console`; Companion's `/socket.io/` requests would target the
host root, which is **not** Funnel-mounted, and 404. We cannot add a second root mount
for Companion without exposing its shared admin+tablet socket API publicly — which the
epic's boundary (only `/console` is public; Companion's admin password is "a casual
deterrent, not a boundary", CLAUDE.md) explicitly forbids.

### F2 — A stdlib socket.io reverse proxy is high-effort, high-maintenance

Even setting F1 aside, proxying Companion in pure stdlib means hand-rolling, inside a
hijacked `BaseHTTPRequestHandler` connection:
- the **WebSocket** server+client handshake (Sec-WebSocket-Key/Accept) and full RFC-6455
  framing (masking, opcodes, fragmentation, ping/pong, close) in both directions;
- the **Engine.IO HTTP long-polling** fallback (the socket.io handshake starts as
  polling), with **sticky `sid` sessions** so successive polls reach the same upstream
  state;
- streaming bidirectional relay threads per connection.
This is a non-trivial protocol implementation to build **and to keep working** across
Companion's frequent upgrades — for a repo whose deliberate design is "pure Python +
stdlib, no framework."

### F3 — The remote-director need is already met by `/console/panel`

Phase 3b already serves the **Director Panel** over Funnel at `/console/panel`
(`src/relay/racecast-feeds.py:3794`, director-gated), giving a remote director the live
broadcast controls — feed handover, schedule/POV/setup writes, timer, mode — over the
exact same relay endpoints the Companion buttons trigger. Companion-over-Funnel would
add only the *physical-button input surface* for controls a remote director can already
operate from `/console/panel`. Low incremental value.

### F4 — Security surface

Proxying Companion's shared admin+tablet socket API to the public internet (even
token-gated at the entry) widens the trust boundary from "HTTP endpoints the relay fully
controls" to "a third-party app's live WebSocket protocol." The epic's clean,
auditable boundary is HTTP-only `/console`. Companion's own model conflates admin and
tablet on one socket (`companion_common.py:10-11`), so the proxy could not cleanly
expose buttons-only.

## Options

- **A — Defer to its own issue (recommended).** Record the spike, close Phase 8 as
  "spiked → deferred", open a follow-up issue. Remote Companion access stays on the
  **existing Tailscale path** (`racecast companion start` binds Companion to the
  Tailscale IP — `companion_common.py`); a remote director **without** Tailscale uses
  `/console/panel`, which already covers the live-control workflow.
- **B — Build a minimal stdlib proxy anyway.** Blocked by F1 (no base-path) unless we
  also build on-the-fly URL rewriting of Companion's bundles + a second root Funnel mount
  — which breaks the security boundary. Effort is disproportionate to F3's value.
- **C — Drop Phase 8 from the epic entirely.** Same as A without a follow-up issue.

## Recommendation

**Defer (Option A).** F1 is a hard upstream blocker (Companion can't be served under a
sub-path, and the epic only funnels `/console`); F2 makes even the unblocked version
costly; F3 shows the core remote-director value is already delivered by `/console/panel`.
Building a stdlib socket.io reverse proxy is the disproportionate effort the spec
anticipated. Keep remote Companion on Tailscale; revisit only if Companion ships
base-path support (track #2255) **and** a real need for physical buttons over Funnel
(beyond `/console/panel`) emerges.

## Sources

- bitfocus/companion #2255 — nginx proxy base url (no sub-path support)
  <https://github.com/bitfocus/companion/issues/2255>
- Socket.IO — Behind a reverse proxy <https://socket.io/docs/v3/reverse-proxy/>
- nginx — WebSocket proxying <https://nginx.org/en/docs/http/websocket.html>
