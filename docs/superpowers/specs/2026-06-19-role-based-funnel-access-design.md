# Role-based Funnel access — design (issue #216)

*Status: approved 2026-06-19. Builds on the #191/#193 commentator-cockpit + Funnel
foundation. Extends public Tailscale Funnel reach from the commentator cockpit to the
Director Panel, Producer takeover, and (spike-gated) Companion buttons, gated by
multi-role identity tokens.*

## Problem

Today the **commentator cockpit** is the only surface reachable over **Tailscale
Funnel**: exactly one path prefix (`/cockpit`) is mounted to the relay, and *anything
not mounted stays tailnet/loopback-only* — that path-scoping is the security boundary
(`src/scripts/tailscale.py`). We want directors, producers, and supporting crew to join
an event over the public Funnel **without each needing a Tailscale account**, lowering
the onboarding hurdle within the Tailscale free tier.

A token model also gives per-message **identity** everywhere — closing today's
spoofable, client-supplied Director-Panel chat name — and one place to express **who may
do what**.

**Crucial constraint:** a person can be **Commentator AND Director AND/OR Producer at
the same time**, and **roles change per event** (not fixed to the profile).

## Locked decisions

From the design discussion (2026-06-18) and the resolution of the open questions
(2026-06-19):

1. **Funnel scope = full parity, one mount.** All control surfaces become
   Funnel-exposable, fully role-gated, under a **single** new `/console` mount. The most
   irreversible producer ops additionally require a step-up.
2. **One link per person, multi-role.** A single identity token/link per person covers
   all their roles for the event.
3. **Identity ≠ authorization.** The token stays a pure **identity** proof (existing
   format **unchanged**: `<subject>.<version>.<sig>`). The relay resolves
   `subject → current roles` from a **live roster per request** — role changes apply
   immediately, no link re-issue. Rotation stays the existing `version` bump.
4. **Roster schema = boolean columns.** A new Sheet **`Crew`** tab with columns
   `Name | Director | Producer` (truthy "X" marks). **Commentator** is *implied* when the
   normalized name appears in the live Schedule/Qualifying roster — streamers are never
   listed in `Crew` for the commentator capability, only to *additionally* tag them
   Director/Producer.
5. **Console UI = separate gated pages under one mount.** `/console` is a role-adaptive
   **launcher**; the actual surfaces are separate pages (`/console/cockpit`,
   `/console/panel`, `/console/prod`), each independently role-gated. (Because only
   `/console` is Funnel-mounted, every public page lives under the `/console/*` prefix —
   the commentator page moves from `/cockpit` to `/console/cockpit` *for public reach*;
   legacy `/cockpit/*` stays tailnet-only.)
6. **Step-up = shared producer secret.** Reuse the existing `X-Cockpit-Secret`
   constant-time check (`cockpit_auth.secret_matches`, the per-league `COCKPIT_SECRET`)
   for irreversible producer ops. Producer enters it once in the console; it rides as a
   header on those ops only.
7. **Backward compat = migrate.** Funnel-mount **only** `/console`. Existing public
   `/cockpit?t=` links stop working over Funnel and are reissued at event setup (links are
   per-event anyway). Legacy `/cockpit/*` keeps working on tailnet/loopback.
8. **Companion = relay-proxied, token-gated** (spike-gated, defer candidate).

## Foundation reused (no behavior change)

| Concern | Reused as-is |
|---|---|
| Token mint/verify, constant-time sig | `src/scripts/cockpit_auth.py` (`mint_token`, `verify_token`, `secret_matches`, `safe_cookie_token`, `parse_cookie_token`, `RateLimiter`, `streamer_key`) |
| Revocation versions | `src/scripts/cockpit_admin.py` (`load_versions`, `current_version`, `bump_version`, `apply_pulled`) |
| Per-request cockpit auth | `_cockpit_auth()` / `_cockpit_token()` / `_send_html_with_cookie()` in `src/relay/racecast-feeds.py` |
| CSV Sheet-tab reading | `ScheduleSource` / `HudSource` pattern (fetch + last-good + brief TTL) |
| SSRF guard, asset-key normalization | `is_channel()`, `asset_key()` |
| Own-row write scoping | `own_submission_target()`, `cockpit_own_stints()` |
| Funnel control | `src/scripts/tailscale.py` (`funnel_args`, `funnel`, `funnel_capable`, `detect_magicdns_name`) |
| Link minting / roster | `racecast cockpit links`, `_cockpit_roster()`, `_ensure_active_cockpit_secret()` in `src/racecast.py` |
| Takeover state pull | `event_takeover()`, `_cockpit_pull_versions()` |

## Architecture

### A. Identity vs. authorization

- **Token (unchanged):** `<subject>.<version>.<sig>` proves *who*. `subject` is the
  `asset_key`/`streamer_key`-normalized person name (streamer key for commentators; same
  normalization for director/producer-only people). `cockpit_auth.mint_token` /
  `verify_token` are reused verbatim.
- **Authorization (new):** a **`RoleSource`** resolves
  `subject → {commentator?, director?, producer?}`:
  - **Crew tab** gives `director` / `producer` (truthy column).
  - Anyone present in the live **Schedule** (or **Qualifying**) streamer set implicitly
    has the **commentator** capability for their own rows, exactly as today.
  - Resolved per request and cached briefly (mirror `ScheduleSource`/`HudSource` TTL).
- **Revocation:** unchanged `version` bump (`cockpit_admin.bump_version`) — used on
  departure *and* on **role downgrade** (a leaked token's blast radius tracks current
  roles, so downgrades must rotate; see Security).

### B. Crew roster (`CrewSource`)

- New Sheet `Crew` tab read as CSV like Schedule/Qualifying/Assets. Columns:
  `Name | Director | Producer`. A cell is truthy if it matches a small allow-list
  (`x`, `X`, `yes`, `true`, `1`, `✓` — case-insensitive, trimmed).
- New `CrewSource` class in `src/relay/racecast-feeds.py` mirroring `ScheduleSource`:
  URL fetch + last-good cache + brief TTL; header detection via `CREW_NAME_HEADERS`,
  `CREW_DIRECTOR_HEADERS`, `CREW_PRODUCER_HEADERS`; positional fallback (col 0 = name,
  col 1 = director, col 2 = producer) when no header row is detected.
- Pure resolver `resolve_roles(crew_rows, schedule_keys, subject) → set[str]` — fully
  unit-testable, no I/O. `crew_rows` = list of `(name, is_director, is_producer)`;
  `schedule_keys` = set of `asset_key`-normalized streamer names from the live schedule.
- Configurable tab name: `--crew-tab` CLI flag (default `Crew`), like `--overlay-tab` /
  `--config-tab`. Injected by `src/racecast.py` when present.
- Missing/empty Crew tab is non-fatal: `director`/`producer` simply resolve to empty,
  commentators still work from the Schedule (graceful degradation, like a missing Overlay
  tab).
- The Crew tab MUST carry a recognizable header row (a `Name`/`Crew`/`Person` column,
  optionally `Director`/`Producer`). A tab whose header uses none of these words falls
  into the positional fallback and consumes its own header row as a (capability-empty)
  phantom roster entry — harmless for authorization but it would surface as a stray name
  in the Phase F link enumeration. The Control Center crew editor (§G) writes a
  conformant header, so this only bites a hand-rolled tab.

### C. Auth + capability layer

- `_console_auth(required)` generalizes `_cockpit_auth()`:
  1. extract token (`?t=` query → cookie),
  2. `verify_token` against `cockpit-versions.json`,
  3. resolve roles via `RoleSource`,
  4. enforce `required` capability,
  5. on failure: 401 (bad/expired token), 403 (authenticated but lacks capability), 429
     (rate-limited) — reusing `RateLimiter` per-IP and per-identity.
  Returns `(subject, roles)`.
- **Capability matrix** (the single source of truth, a pure table mapping
  `/console/<subpath>` → minimum capability):

  | Endpoint (under `/console`) | Min capability |
  |---|---|
  | `/`, `/cockpit`, `/data`, `/status`, `/hud/data`, `/schedule/data`, `/timer` (read), `/program`, `/chat/data` | any authenticated |
  | `/chat/send` (identity **server-forced** from token) | any authenticated |
  | `/submit` (own-rows only — existing `own_submission_target`) | commentator |
  | `/panel`, `/timer/*`, `/setup/*`, `/pov/*`, `/submissions`, `/submissions/{approve,reject}`, `/schedule/set`, `/qualifying/set`, `/event/title`, `/next`, `/prev/*`, `/reload*`, `/set/A\|B/<n>` | director |
  | `/prod`, `/set/stint/<n>`, `/mode/*`, `/takeover/{status,chat,versions,event,timer}`, `/buttons*` | producer + step-up |

- **Step-up** `_require_step_up()` = `secret_matches(header X-Cockpit-Secret,
  COCKPIT_SECRET)` for the producer+step-up rows. Constant-time, reused verbatim.

### D. Single `/console/*` namespace (one Funnel mount)

- **Pages**
  - `GET /console` → role-adaptive **launcher**: lists links only to the surfaces the
    resolved roles permit (any authenticated).
  - `GET /console/cockpit` → `src/cockpit/cockpit.html` (commentator monitor; any
    authenticated, data scoped to own rows by subject).
  - `GET /console/panel` → `src/director/director-panel.html` (director).
  - `GET /console/prod` → producer page (producer; step-up prompt for irreversible ops).
- **APIs** mirrored under `/console/*`. Each is a **thin authenticated wrapper** that runs
  `_console_auth(required)` then dispatches to the **same internal handler** the root
  endpoint uses — *no business logic is duplicated*. Where a root handler is currently
  inline in `do_GET`/`do_POST`, it is refactored into a shared method callable by both the
  root path and the `/console` mirror.
- **Base-path switch** in `director-panel.html` (and cockpit.html): when served under
  `/console`, the page prefixes its fetch/XHR calls with `/console` and relies on the
  `rc_cockpit` cookie (set by `_send_html_with_cookie`, `Path=/console`). Root-served
  copies (tailnet) keep calling the root paths with no token. Implemented as a single
  injected `<base>`-style JS constant (`window.RC_API_BASE`), defaulting to `""`.
- **Boundary invariant:** root endpoints + legacy `/cockpit/*` stay
  tailnet/loopback-only, **unmounted, no token required** — the trusted
  local/OBS/Companion workflow is unchanged.

### E. Funnel

- Generalize `tailscale.funnel*` from the hardcoded `/cockpit` to a configurable path;
  mount **only** `/console`: `funnel_args(path="/console", target_port=8088, enable=True)`
  → `["funnel", "--bg", "--set-path=/console", "http://127.0.0.1:8088/console"]`.
- New top-level `racecast funnel on|off [--force]`; keep `racecast cockpit funnel` as a
  thin alias for one release.
- **Boundary-invariant test** asserts the enable args mount exactly `{/console}` and no
  root path is ever passed to `--set-path`.

### F. Link CLI

- Generalize `racecast cockpit links` into an access-link command that:
  - enumerates **people** = **Crew tab** ∪ live **Schedule** roster,
  - mints **one** identity token + **one** `/console?t=<token>` link per person,
  - prints both the Funnel (public MagicDNS) and tailnet URLs,
  - supports `--post` to crew chat (as today).
- Keep `racecast cockpit links` working (alias) for one release.

### G. Control Center crew editor

- Profile-view editor: read the Crew tab, write via the existing `SHEET_PUSH_URL`
  webhook with a **new `crew` action** mirroring the existing `schedule` write action.
  Routes added to `src/ui/ui_server.py`; tests in `tests/test_ui_server.py`.
- **Coordination item (outside this repo):** the league's Apps Script webhook must learn
  to handle the `crew` action / write the `Crew` tab, and the `Crew` tab must exist in
  each league's Sheet. Docs must call this out; the relay degrades gracefully without it.

### H. Producer takeover over Funnel

- Expose the takeover **pull** endpoints under `/console`, gated **producer + step-up**:
  `/console/takeover/{status,chat,versions,event,timer}` — the same state set that travels
  today (on-air stint, chat history, cockpit/role versions, event title, timer).
- Extend `event_takeover()` to accept a **Funnel MagicDNS host** + the producer secret,
  so producer B can take over A's state over the public Funnel. Bringing services up stays
  a local `event start --stint N`.

### I. Companion buttons (relay-proxied) — spike-gated, defer candidate

- A token-gated `/console/buttons` route (director) that the relay **reverse-proxies** to
  Companion's local port **only after** `_console_auth` passes. Companion keeps binding to
  loopback/tailnet (`companion_common.py` unchanged); its admin GUI is **never** exposed
  publicly.
- **Risk:** Companion's button UI is socket.io/WebSocket-heavy and the repo is **pure
  stdlib, no framework** — a stdlib WebSocket reverse proxy is non-trivial. This phase is
  **spike-first**, and is the strongest candidate to split into a follow-up issue if the
  spike shows the effort is disproportionate to the value.

## Security analysis

- **Trust shift:** from "Tailscale network membership" to "signed identity token + live
  role lookup, over the public internet." Accepted (full-parity decision), bounded by:
  per-request verification, **per-identity + per-IP rate limits** (`RateLimiter`),
  HTTPS-only Funnel, `HttpOnly; Secure; SameSite=Lax` cookies, cookie-injection allow-list
  (`safe_cookie_token`), `is_channel()` SSRF guard on URL writes — all already in place
  for `/cockpit`.
- **Leaked-token blast radius = current roles.** Mitigations: `version` rotation on
  departure *and on downgrade*; **step-up** (shared producer secret) on irreversible
  producer ops; never log tokens or the secret.
- **Boundary invariant preserved:** only `/console` is mounted; root control endpoints
  remain unreachable from outside the tailnet. Locked by a test over the `funnel_args`
  mount set.
- **Identity everywhere:** funnelled chat/writes carry **server-derived** identity from
  the token — closing the current spoofable Director-Panel chat-name hole.
- **Free-tier reality:** Funnel is available on all plans incl. free; no documented
  concurrent-user cap; **best-effort, non-configurable bandwidth** on ports 443/8443/10000.
  `/console/program` serves polled JPEG screenshots (not video), so per-crew bandwidth is
  modest — fine for a handful of remote crew, not for many concurrent video consumers.

## Testing

- **`tests/test_roles.py`** (new): `CrewSource` CSV parse (header + positional + truthy
  allow-list + missing tab) and `resolve_roles` (commentator-from-schedule,
  director/producer-from-crew, multi-role union, unknown subject → empty).
- **`tests/test_console.py`** (new): `_console_auth` capability gating per matrix row
  (commentator blocked from director ops, director allowed, producer step-up enforced /
  rejected without secret), identity-server-forced chat, 401/403/429 paths.
- **`tests/test_tailscale.py`**: `funnel_args` mounts exactly `/console`; boundary
  invariant (no root path mounted).
- **`tests/test_ui_server.py`**: crew editor read + webhook `crew` write payload shape.
- **`tools/e2e.py`** synthetic mode: add a `Crew` roster CSV + a multi-role token; assert
  capability gating (commentator blocked from `/console/next`, director allowed, producer
  step-up enforced) and that only `/console` is funnel-mounted.

## Phasing — one PR per phase, each ships green

1. **Roster + roles** — `CrewSource`, `resolve_roles`, `--crew-tab`, `tests/test_roles.py`.
   No behavior change (pure additive read path). *(includes this spec doc)*
2. **Console auth + capability matrix** — `_console_auth`, step-up check, the pure
   capability table + `tests/test_console.py`. Minimal/no new routes.
3. **`/console/*` mirror routing + pages** — launcher + cockpit/panel/prod pages
   (base-path switch) + mirrored APIs dispatching to shared handlers. Largest PR; may
   split GET-reads vs writes.
4. **Funnel mount → `/console`** — generalize `tailscale.funnel*`, `racecast funnel`
   CLI, boundary test. The migration; reissue links.
5. **Link CLI generalization** + Control Center surfacing.
6. **Crew editor in Control Center** (+ Apps Script / Crew-tab coordination, documented).
7. **Takeover over Funnel** — producer-gated pull endpoints + `event_takeover` Funnel host.
8. **Companion reverse-proxy** — spike-gated; defer candidate (possibly its own issue).
9. **Docs + wiki** — Tailscale/Funnel/security pages; refresh affected wiki screenshots
   (`director-panel.png`; Control Center crew editor `cc-*.png`) per CLAUDE.md.

Each phase runs the full local gate (`run-tests.py` + `lint.py` + `build.py` exit 0) and
waits for green CI (incl. Windows) before merge. The wiki-screenshot refresh attaches to
whichever phase changes a visible UI surface (the panel served under `/console`, the crew
editor).

## Out of scope / follow-ups

- Apps Script webhook changes and `Crew`-tab creation in each league Sheet (Sheet-side,
  coordinated with each league).
- Companion proxy may become its own issue if the spike (phase 8) shows disproportionate
  effort.
- Tailscale free-tier concurrent-crew ceiling is undocumented; revisit if a league needs
  many concurrent remote consumers.
