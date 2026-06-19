# Companion buttons over Funnel (`/console/buttons`) — design

*Design spec for issue #236 (revived; the original Phase 8 deferral —
`docs/superpowers/specs/2026-06-19-companion-funnel-proxy-spike.md` — is superseded;
see #236's re-assessment comment). Goal: let a remote director **without a Tailscale
account** drive the physical Bitfocus Companion button UI over the public Tailscale
Funnel, by reverse-proxying Companion through the relay under a director-gated
`/console/buttons` sub-path.*

## Why this is feasible now (what changed)

The original spike deferred Phase 8 on two findings; both have moved:

- **F1 (no base-path support) — resolved upstream.** Companion **v4.1.0**
  (bitfocus/companion#3503, closing #2255) added **runtime** sub-path serving: a reverse
  proxy sets a `Companion-custom-prefix: <path>` request header and Companion's server
  rewrites a built-in placeholder (`/ROOT_URL_HERE`) in every served html/js/css; the UI
  builds URLs via `makeAbsolutePath`. A **stock binary ≥ v4.1.0** works — no custom build.
- **F2 (hand-rolled socket.io proxy) — de-risked.** socket.io starts over Engine.IO
  **HTTP long-polling** and only *upgrades* to WebSocket; if the upgrade fails it stays on
  polling. Polling is plain HTTP a simple stdlib reverse proxy handles. So the **mandatory**
  work is an HTTP reverse proxy; the WebSocket passthrough becomes an **optional latency
  optimization** with polling as a built-in fallback.

## Security posture (decided, deliberate)

This feature **exposes Companion to authenticated directors over the public internet**.
That is an accepted trade-off, decided with full knowledge of the facts below — it is
recorded here so it is never mistaken for an oversight.

- **Companion has no real auth boundary, by vendor design.** Its Admin Password is "only
  designed to stop casual browsers". Per bitfocus/companion#3814 (closed **NOT_PLANNED** by
  a core maintainer: *"it is not intended to be proper security, so currently this bypass is
  expected behaviour"*), the socket.io channel can **export the full configuration without
  auth** (including connection settings — potentially stored credentials such as the OBS
  WebSocket password or module API keys) and **mutate configuration**. There is **no**
  buttons-only / press-only mode and none planned (#2986 closed DUPLICATE).
- **Consequence:** "buttons-only" cannot be enforced at the Companion layer (one shared,
  unconstrained socket). We therefore proxy Companion **transparently** (Option C) and rely
  on the **relay's director token gate** as the boundary — the same gate that already
  protects `/console/panel`.
- **Why this is acceptable here.** A director on the tailnet today already reaches
  Companion's admin directly (`racecast companion start` binds Companion to the Tailscale
  IP), and a funnelled director already controls OBS via the relay's `/obs/*`. For a
  *trusted* director, Funnel vs. tailnet changes no capability. The one real delta is
  **blast radius on token leak**: on the tailnet the boundary is network membership **and**
  the token; over Funnel the token is the *sole* boundary, and a leaked director token now
  also yields Companion's full config export. The deployment owner accepts this, trusting
  the director roster.
- **Mitigations (documentation, not code):** recommend not storing reusable secrets in a
  funnelled Companion (rotate the OBS WebSocket password if it must live there); pin
  Companion ≥ v4.1.0; the existing `racecast cockpit token revoke` rotates a leaked link at
  once.

Activation is **fully automatic** (no opt-in flag, no step-up): whenever Companion is
reachable locally and the Funnel is on, `/console/buttons` is available to directors —
the same zero-config model as `/console/panel`.

## Architecture

```
Funnel: only /console  ->  relay :8088                 (UNCHANGED — single-mount invariant intact)
Relay:  /console/buttons/*  --[director gate]-->  http://127.0.0.1:8000/*   (Companion)
        - strip the /console/buttons prefix from the upstream path
        - inject  Companion-custom-prefix: /console/buttons
        - Phase 1: proxy HTTP (incl. Engine.IO long-polling) ; Phase 2 (opt): WS upgrade passthrough
Prereq: Companion >= v4.1.0 (stock binary)
```

The relay **must** be in the path (not a direct Funnel mount to port 8000) for two
reasons: (a) to keep the director token gate in front, and (b) to inject the
`Companion-custom-prefix` header. A direct Funnel mount is rejected: it would bypass the
gate, add a second Funnel mount (breaking the test-locked single-mount boundary), and
could not inject the prefix header (Tailscale serve/funnel cannot add request headers).

### Why polling-first

A pure HTTP reverse proxy needs no socket hijack and no RFC-6455 framing. Because there
is exactly **one** upstream (a single Companion instance), Engine.IO's `sid` polling needs
**no sticky-session routing** — every poll reaches the same Companion. The WebSocket
upgrade, if added later, is a transparent byte pump (no frame parsing) and degrades to
polling on any failure.

## Components

Each unit is small, single-purpose, and independently testable.

### U1 — Pure proxy helpers (`src/scripts/console_proxy.py`, new)
Pure functions, no I/O, fully unit-testable:
- `upstream_path(request_path)` — strip the `/console/buttons` prefix (map
  `/console/buttons/x/y` → `/x/y`, `/console/buttons` and `/console/buttons/` → `/`),
  preserving the query string.
- `forward_request_headers(headers, prefix)` — copy client headers, **drop hop-by-hop**
  headers (`Connection`, `Keep-Alive`, `Proxy-*`, `TE`, `Trailer`, `Transfer-Encoding`,
  `Upgrade` for the HTTP path), set `Host: 127.0.0.1:8000`, and inject
  `Companion-custom-prefix: <prefix>` (prefix = `/console/buttons`).
- `filter_response_headers(headers)` — drop hop-by-hop + length/encoding headers the proxy
  recomputes; pass the rest through.
- `is_websocket_upgrade(headers)` — detect `Upgrade: websocket` (used in Phase 2 only).

These have **no** Companion/socket knowledge beyond HTTP plumbing, so Companion upgrades
do not touch them.

### U2 — Relay HTTP proxy method (`src/relay/racecast-feeds.py`)
A handler method `_proxy_companion(self, request_path, method)` that:
1. builds the upstream URL `http://127.0.0.1:8000` + `upstream_path(...)`;
2. reads the client body (for POST polling frames) via `Content-Length`;
3. issues the upstream request with `urllib.request` (stdlib), forwarded+injected headers,
   a short connect timeout;
4. streams the upstream status, `filter_response_headers(...)`, and body back to the client;
5. on connection refused / timeout → **HTTP 502** with a plain-text note
   ("Companion not reachable on 127.0.0.1:8000").
It never raises out of the handler (best-effort contract, like `get_program_screenshot`).

### U3 — Gate wiring (`src/relay/racecast-feeds.py` `_console_gate` + `console_policy.py`)
- `console_policy`: map the `buttons` path segment to the **director** capability (no
  step-up). Mirrors how `panel` maps to director.
- `_console_gate`: when `sub and sub[0] == "buttons"`, run the normal identity + role
  resolution, call `console_policy.decide(...)`; on `ALLOW`, call
  `self._proxy_companion(self.path, method)` and **return None** (the gate handled the
  response — it does not fall through to the JSON API). On non-ALLOW, emit the existing
  403/404 exactly as today. Works for both GET and POST (Engine.IO uses both).

### U4 — Launcher entry (`src/console/console.html`)
For a director subject (`/console/whoami` roles), render a **"Companion Buttons"** link
that opens `/console/buttons/` in a new tab. Gate its visibility on a small availability
probe (see U5). Non-directors never see it. No new page is built — the target is
Companion's own web-buttons UI, served through the proxy.

### U5 — Availability/version signal (`/console/buttons/health`, relay; uses
`install_apps.companion_http_version`)
A tiny director-gated `GET /console/buttons/health` returning
`{ reachable: bool, version: str|null, ok: bool }` where `ok` = reachable **and** version
≥ `4.1.0`. The launcher calls it to decide: show the link (`ok`), show a disabled
"needs Companion ≥ 4.1" note (reachable but old), or hide it (not reachable). Version parse
reuses the existing `companion_http_version(base_url, fetch)` helper — no new HTTP-probe
code. **Routing:** `_console_gate` intercepts `sub == ["buttons", "health"]` and serves this
relay response **before** the `buttons[...]` proxy branch, so it shadows that one path on the
upstream (Companion's web-buttons UI does not use `/health`, so there is no collision).

### U6 — Phase 2 (optional) WebSocket passthrough
Only if polling latency proves insufficient. In `_proxy_companion`, when
`is_websocket_upgrade`, open a raw `socket.create_connection(("127.0.0.1", 8000))`, replay
the upgrade request (rewritten path + injected prefix), relay the upstream `101` to the
client socket (`self.connection`), then pump bytes bidirectionally (two directions via
`select`) until either side closes. Transparent — no socket.io frame parsing. Guarded so any
failure falls back to a closed upgrade and the client reverts to polling.

## Data flow (Phase 1)

1. Director opens `https://<host>/console/buttons/` (token in cookie from the launcher).
2. Funnel forwards `/console/*` to relay:8088. `do_GET` sees `console`, calls `_console_gate`.
3. Gate authenticates the token, resolves roles, `decide(... "buttons" ...)` → director →
   ALLOW → `_proxy_companion("/console/buttons/", "GET")`.
4. Proxy GETs `http://127.0.0.1:8000/` with `Companion-custom-prefix: /console/buttons`.
   Companion returns html/js/css with every URL rewritten to `/console/buttons/...`.
5. The browser loads assets and the Engine.IO handshake from `/console/buttons/socket.io/…`
   — each is gated + proxied identically (GET/POST polling). Buttons render and press; state
   updates flow over polling. (Phase 2 would upgrade this leg to WebSocket.)

## Error handling

- Companion down → `_proxy_companion` → **502** + plain note; launcher link hidden via U5.
- Companion < v4.1.0 → URLs would not be prefixed (UI breaks); U5 reports `ok:false` →
  launcher shows the "needs ≥ 4.1" note instead of a broken page.
- No `console_secret` configured → entire `/console` (incl. `/console/buttons`) 404s, exactly
  as `/cockpit` does today.
- Non-director token → 403 from the gate, unchanged.

## Testing

- `tests/test_console.py` / `tests/test_console_gate.py` — `buttons` → director capability;
  gate routes `/console/buttons/*` to the proxy on ALLOW and 403s a non-director.
- `tests/test_console_proxy.py` (new) — pure U1 helpers: path strip + query preservation,
  header injection, hop-by-hop filtering, websocket-upgrade detection.
- `tests/test_tailscale.py` — unchanged and still green: only `/console` is funnelled; assert
  no second mount is introduced.
- `tools/e2e.py` (synthetic, optional) — a stub upstream on a free port; assert
  `/console/buttons/*` proxies through with the prefix header and 502s when the stub is down.
- Phase 0 prototype validates the polling-only assumption against a **real** local Companion
  before Phase 1 is written (it is throwaway; not committed as production code).

## Docs impact (must ship in the same change)

Option C changes the **documented** security boundary, so the docs are corrected honestly,
not left stale:
- `src/docs/wiki/Remote-access.md` — the "Companion stays on the tailnet / admin+buttons port
  is never exposed publicly" section becomes: Companion *is* reachable over Funnel at
  `/console/buttons`, behind the director gate, with the explicit risk note (full Companion
  access incl. config export for authenticated directors; the credential-hygiene
  recommendations above; Companion ≥ v4.1.0).
- `src/docs/wiki/Architecture.md` — boundary paragraph + diagram updated to show
  `/console/buttons → Companion` through the relay.
- `src/docs/wiki/Companion.md` — add the remote-buttons-over-Funnel path alongside the
  existing Tailscale path.
- `CLAUDE.md` relay section — reconcile the "only `/console` is funnel-mounted" statement
  (still true) with the new sub-path proxy to Companion; note OBS-WebSocket is still never
  funnelled.
- No Control Center / Director Panel UI surface changes → no `cc-*.png` / `director-panel.png`
  screenshot refresh. The `/console` launcher is not a wiki-screenshotted surface.

## Phasing (becomes the implementation plan's task groups)

- **Phase 0 — Prototype/spike (throwaway).** Validate web-buttons through a relay HTTP proxy
  on **polling alone** against a real Companion ≥ v4.1.0; confirm the prefix header resolves
  all URLs. Go/No-Go for Phase 1. Records findings; ships no production code.
- **Phase 1 — Production HTTP/polling proxy.** U1–U5 + tests + docs. Shippable feature.
- **Phase 2 — Optional WebSocket passthrough (U6).** Only if polling latency is inadequate;
  has the polling fallback as a safety net.

## Out of scope (YAGNI)

- Socket.io message-level filtering / true buttons-only (rejected: chases an unsupported
  internal protocol; the owner accepted full transparent passthrough).
- Opt-in flag or producer step-up gate (the owner chose fully automatic, director-level).
- Reimplementing a native racecast button grid (that was Option B, not chosen).
