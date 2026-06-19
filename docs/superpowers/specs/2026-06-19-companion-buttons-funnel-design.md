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
- **F2 (hand-rolled socket.io proxy) — different, and smaller, than the spike feared.**
  Current Companion (validated on **v4.3.4**) no longer uses socket.io at all: its realtime
  channel is **tRPC over a single raw WebSocket** at `/trpc`. There is **no HTTP
  long-polling fallback** — without the WebSocket the web-buttons page hangs on a loading
  spinner. So a WebSocket passthrough is **mandatory**, not optional. The upside: a *raw*
  WebSocket is materially **simpler** to proxy than socket.io — no Engine.IO handshake, no
  `sid` sticky sessions, no polling transport. With a single upstream, the proxy is a
  transparent byte pump after one Upgrade handshake (no frame parsing).

### Phase 0 validation (completed 2026-06-19, against a live local Companion v4.3.4)

A throwaway stdlib proxy + a real browser confirmed the design and corrected three
assumptions — these are now load-bearing facts, not guesses:

1. **Companion v4.3.4** (≥ v4.1.0); the `Companion-custom-prefix` mechanism is present.
2. **The header value must have NO leading slash** — `console/buttons`, not `/console/buttons`
   (the latter makes Companion emit broken `//console/buttons/…` protocol-relative URLs).
   The relay therefore keeps two distinct strings: the **path prefix** `/console/buttons`
   (to strip/route) and the **header value** `console/buttons`.
3. **The realtime channel is a raw WebSocket at `/trpc`** (tRPC), with no polling fallback.
   A polling-only proxy renders a permanent spinner; the WebSocket passthrough is required.
4. **WS passthrough works:** with a transparent raw-WebSocket byte pump, the full live
   button page renders (0 console errors, live button colours) through the proxy.
5. **Companion binds to the Tailscale IP, not loopback.** `racecast companion start` launches
   Companion with `--admin-address=<tailscale-ip>` (e.g. `…:8000`), so the relay must
   **resolve** Companion's bind address, not assume `127.0.0.1` (see "Companion address
   resolution" below).

## Security posture (decided, deliberate)

This feature **exposes Companion to authenticated directors over the public internet**.
That is an accepted trade-off, decided with full knowledge of the facts below — it is
recorded here so it is never mistaken for an oversight.

- **Companion has no real auth boundary, by vendor design.** Its Admin Password is "only
  designed to stop casual browsers". Per bitfocus/companion#3814 (closed **NOT_PLANNED** by
  a core maintainer: *"it is not intended to be proper security, so currently this bypass is
  expected behaviour"*), Companion's realtime control channel can **export the full
  configuration without auth** (including connection settings — potentially stored
  credentials such as the OBS WebSocket password or module API keys) and **mutate
  configuration**. There is **no** buttons-only / press-only mode and none planned (#2986
  closed DUPLICATE).
- **Consequence:** "buttons-only" cannot be enforced at the Companion layer (one shared,
  unconstrained control channel). We therefore proxy Companion **transparently** (Option C) and rely
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
Relay:  /console/buttons/*  --[director gate]-->  http://<companion-bind>:8000/*   (Companion)
        - strip the /console/buttons path prefix from the upstream path
        - inject  Companion-custom-prefix: console/buttons   (NO leading slash)
        - proxy HTTP for html/js/css/assets  AND  raw-WebSocket passthrough for /trpc
        - <companion-bind> is RESOLVED (Companion's config.json bind_ip / Tailscale IP), not 127.0.0.1
Prereq: Companion >= v4.1.0 (stock binary)
```

### Companion address resolution

`racecast companion start` binds Companion to the Tailscale IP (`--admin-address`), so the
relay cannot assume loopback. A small resolver returns the Companion base URL, in order:
Companion's own `config.json` `bind_ip` (the same file `companion_common.py` reads/writes) →
`tailscale.detect_tailscale_ip()` → `127.0.0.1`, each on the admin port `8000`. The relay
proxies to that base.

The relay **must** be in the path (not a direct Funnel mount to port 8000) for two
reasons: (a) to keep the director token gate in front, and (b) to inject the
`Companion-custom-prefix` header. A direct Funnel mount is rejected: it would bypass the
gate, add a second Funnel mount (breaking the test-locked single-mount boundary), and
could not inject the prefix header (Tailscale serve/funnel cannot add request headers).

### Why the WebSocket passthrough is simple here

Although the WS is mandatory, it is a *raw* WebSocket to a **single** upstream, so the proxy
never parses or understands frames: it forwards the client's Upgrade request to Companion
(rewritten path + injected prefix), relays the `101 Switching Protocols` back, then pumps
bytes in both directions until either side closes. No Engine.IO handshake, no `sid` sticky
sessions, no polling transport — the spike's feared socket.io complexity does not apply.

## Components

Each unit is small, single-purpose, and independently testable.

### U1 — Pure proxy helpers (`src/scripts/console_proxy.py`, new)
Pure functions, no I/O, fully unit-testable. Two distinct prefix strings:
`MOUNT_PREFIX = "/console/buttons"` (path) and `PREFIX_HEADER_VALUE = "console/buttons"`
(the no-leading-slash header value — Phase 0 fact #2).
- `upstream_path(request_path)` — strip `MOUNT_PREFIX` (map `/console/buttons/x/y` → `/x/y`,
  `/console/buttons` and `/console/buttons/` → `/`), preserving the query string.
- `forward_request_headers(headers, prefix=PREFIX_HEADER_VALUE, host=...)` — copy client
  headers, **drop hop-by-hop** (`Connection`, `Keep-Alive`, `Proxy-*`, `TE`, `Trailer`,
  `Transfer-Encoding`, `Upgrade`) **and** `Accept-Encoding` (force identity), set `Host`,
  inject `Companion-custom-prefix: console/buttons`. (For the WS path, the upgrade headers
  are forwarded raw instead — see U2.)
- `filter_response_headers(headers)` — drop hop-by-hop + length/type/encoding headers the
  proxy recomputes; pass the rest through.
- `is_websocket_upgrade(headers)` — detect `Upgrade: websocket` + `Connection: upgrade`.
- `version_ge(ver_str, floor)` — dotted-version compare for the health gate.

These have **no** Companion/socket knowledge beyond HTTP plumbing, so Companion upgrades
do not touch them.

### U2 — Relay proxy method (`src/relay/racecast-feeds.py`) — HTTP **and** WebSocket
A handler method `_proxy_companion(self, method)` that:
1. resolves the Companion base (see "Companion address resolution") and builds the upstream
   URL + `upstream_path(self.path)`;
2. **WebSocket branch (mandatory):** when `is_websocket_upgrade(self.headers)` (the `/trpc`
   tRPC channel), open a raw `socket.create_connection((host, 8000))`, replay the Upgrade
   request line (rewritten path) with the upgrade headers + injected prefix forwarded raw,
   relay the upstream `101 Switching Protocols` to the client socket (`self.connection`), then
   pump bytes bidirectionally via `select` until either side closes. Transparent — no frame
   parsing. Any failure → close the upgrade; never raises.
3. **HTTP branch:** read the client body via `Content-Length`; issue the upstream request with
   `urllib.request` (stdlib), forwarded+injected headers; stream the upstream status,
   `filter_response_headers(...)`, and body back.
4. on connection refused / timeout → **HTTP 502** with a JSON note.
It never raises out of the handler (best-effort contract, like `get_program_screenshot`).

### U2a — Companion address resolver (`src/relay/racecast-feeds.py` or a small helper)
`_resolve_companion_base()` → `http://<host>:8000`, trying Companion's `config.json` `bind_ip`,
then `tailscale.detect_tailscale_ip()`, then `127.0.0.1`. Pure-ish (filesystem read of the
known config path); injected/overridable in tests via the `companion_url` make_handler kwarg.

### U3 — Gate wiring (`src/relay/racecast-feeds.py` `_console_gate` + `console_policy.py`)
- `console_policy`: map the `buttons` path segment to the **director** capability (no
  step-up). Mirrors how `panel` maps to director.
- `_console_gate`: when `sub and sub[0] == "buttons"`, run the normal identity + role
  resolution, call `console_policy.decide(...)`; on `ALLOW`, call
  `self._proxy_companion(method)` and **return None** (the gate handled the
  response — it does not fall through to the JSON API). On non-ALLOW, emit the existing
  403/404 exactly as today. Works for GET (incl. the WS upgrade) and POST.

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

## Data flow

1. Director opens `https://<host>/console/buttons/` (token in cookie from the launcher).
2. Funnel forwards `/console/*` to relay:8088. `do_GET` sees `console`, calls `_console_gate`.
3. Gate authenticates the token, resolves roles, `decide(... "buttons" ...)` → director →
   ALLOW → `_proxy_companion("/console/buttons/", "GET")`.
4. Proxy GETs `http://<companion-bind>:8000/` with `Companion-custom-prefix: console/buttons`.
   Companion returns html/js/css with every URL rewritten to `/console/buttons/...`.
5. The browser loads assets (gated + HTTP-proxied) and opens the tRPC **WebSocket** at
   `/console/buttons/trpc` — the gate routes it to `_proxy_companion`, which hijacks the
   connection and transparently pumps it to Companion's `/trpc`. Buttons render with live
   state and presses actuate Companion. (No polling fallback exists; the WS is required.)

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
  header injection (no-leading-slash prefix), hop-by-hop + Accept-Encoding filtering,
  websocket-upgrade detection, `version_ge`.
- `tests/test_console_gate.py` — `buttons` → director; HTTP proxy to a stub upstream (asserts
  the injected `Companion-custom-prefix: console/buttons` and stripped path); 502 when the
  stub is down; **WS upgrade** to a raw-socket stub that completes a `101` and echoes a frame.
- `tests/test_tailscale.py` — unchanged and still green: only `/console` is funnelled; assert
  no second mount is introduced.
- `tools/e2e.py` (synthetic, optional) — a stub upstream on a free port; assert
  `/console/buttons/*` proxies through with the prefix header and 502s when the stub is down.
- Phase 0 (done 2026-06-19) validated the design against a **real** local Companion v4.3.4
  with a throwaway proxy + a browser (not committed). Its findings are folded in above.

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

## Phasing

- **Phase 0 — Prototype/spike (throwaway). DONE 2026-06-19.** Validated against a real
  Companion v4.3.4: prefix header works (no leading slash), the realtime channel is a raw
  WebSocket at `/trpc` (no polling fallback), WS passthrough renders the live button page,
  and Companion binds to the Tailscale IP. Verdict: GO. Shipped no production code.
- **Phase 1 — Production proxy (HTTP + mandatory WebSocket).** U1, U2, U2a, U3, U4, U5 +
  tests + docs. Shippable feature. (The WebSocket is part of Phase 1, not deferred.)

## Out of scope (YAGNI)

- Socket.io message-level filtering / true buttons-only (rejected: chases an unsupported
  internal protocol; the owner accepted full transparent passthrough).
- Opt-in flag or producer step-up gate (the owner chose fully automatic, director-level).
- Reimplementing a native racecast button grid (that was Option B, not chosen).
