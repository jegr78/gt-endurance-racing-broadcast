# e2e / regression test harness — design

**Issue:** #199 — *e2e/regression test harness (drive relay + cockpit + Control
Center headlessly)*
**Date:** 2026-06-17
**Status:** Approved design, pending implementation plan.

## Motivation

The Commentator Cockpit work (#191) shipped four bugs that the unit tests never
caught because they were integration / runtime / UI problems, all found by hand
and late:

- `racecast cockpit enable` wiped other `profile.env`/`.env` keys (a single-pair
  write through the full-set `merge_env_text`).
- The cockpit timer rendered `—` (the page read non-existent timer fields).
- The tally double-printed "stint" (the sheet label already includes it).
- The funnel-capability pre-check looked for the wrong Tailscale CapMap key.

This is a *class* of defect — the unit suite asserts pure functions, but nothing
stands the system up and drives its live HTTP surface. A scripted end-to-end
harness closes that gap and makes every future feature/bugfix faster to verify.

## Goals

- Stand up a **real-ish dev build** (run from `src/`) and drive it headlessly,
  asserting on the **live HTTP surface** (and optionally the rendered UI).
- A **CI-runnable** synthetic path that touches **no** real IPs / Sheets /
  cookies / OBS / Tailscale (CLAUDE.md hard rule) — runs on any machine.
- A **local-only real-league** path that automates the existing manual UAT
  procedure, sharing the same assertion code; never runs in CI.
- Regression-guard the four #191 bugs at the level where they were observable.

## Non-goals

- Not replacing the unit suite (`tests/test_*.py`) — it stays the fast inner
  loop. This harness is the slower outer loop.
- Not asserting real **feed bytes** (no actual YouTube/Twitch pull, no OBS
  program pixels) — the synthetic path asserts the *control surface*, not media.
- Not a general load/perf tool. Functional correctness only.
- `POST /cockpit/submit` *publishing* is out of scope for assertions beyond the
  pending-store round-trip (approval writes the Sheet — real-league only).

## Overview

A single thin maintainer driver, **`tools/e2e.py`** (stdlib only, not shipped,
mirrors `tools/build.py`'s style), plus a small reusable assertion core. It:

1. Builds an ephemeral synthetic environment (temp profile + in-process CSV
   server) — or, in real-league mode, reuses the deployed instance's copied
   profile/runtime per the `racecast-local-uat` skill.
2. Spawns the relay (and Control Center) from `src/` as subprocesses it owns,
   bound to `127.0.0.1` on OS-assigned free ports.
3. Polls readiness, runs the check registry, prints a summary, and tears every
   process down in a `finally`.
4. Exits non-zero on any assertion failure (the `tests/` ethos).

### Invocation

```bash
python3 tools/e2e.py                      # synthetic mode (default, CI-runnable)
python3 tools/e2e.py --real-league iro-gtec   # local-only, real data, never CI
python3 tools/e2e.py --playwright         # also run gated rendered checks
```

- `--playwright` (or auto-detect) enables optional rendered checks; when the
  MCP/browser is unavailable they **skip** (printed notice), never fail, so a
  browserless CI stays green.
- Real-league mode is **skipped entirely** under CI (detected by the absence of
  `--real-league` plus the `CI` env var); it is opt-in and local only.

### CI wiring

A new job/step in `.github/workflows/ci.yml` runs `python3 tools/e2e.py`
(synthetic mode) on the Linux runner. It does **not** go through
`tools/run-tests.py` (that suite stays the fast unit loop); the e2e step is
separate so its longer runtime and process spawning are isolated.

## Components

### `tools/e2e.py` — the driver

Owns process lifecycle and mode selection. Responsibilities:

- Parse args (`--real-league NAME`, `--playwright`, `--timeout`, `--keep` for
  debugging).
- In synthetic mode: scaffold the ephemeral environment (below), set the cockpit
  env vars, spawn services, run checks, tear down.
- In real-league mode: resolve the copied profile (reusing `config.py`), spawn
  services against it, run the same checks that are safe against real data.
- Guaranteed teardown of every spawned process in a `finally` (kill + reap),
  even on assertion failure or `KeyboardInterrupt`.

### `tools/e2e_checks.py` — the assertion core

A reusable, **import-testable** library shared by both modes. Pure where
possible; the HTTP-touching checks take a base URL + minted token so they can be
exercised against either a synthetic or a real relay. Pieces:

- **Free-port helper** — bind `:0`, read back the port, close; hand it to a
  child. No hardcoded ports → no CI collisions.
- **Synthetic-CSV builder** — produce a valid schedule CSV string (URL/Streamer/
  Stint rows) with fake-but-well-formed YouTube/Twitch URLs.
- **Check registry** — each check is a named callable returning a structured
  result `(name, status ∈ {pass, fail, skip}, message)`. The driver runs the
  registry, prints a summary table, and exits non-zero iff any `fail`.
- **Skip/fail classifier** — decides `skip` vs `fail` for optional capabilities
  (browser absent → skip; assertion wrong → fail).

### Ephemeral synthetic environment

- **Schedule:** an in-process `http.server` (its own thread) serves the
  synthetic CSV at `http://127.0.0.1:<port>/schedule.csv`. The relay is spawned
  with `--sheet-csv-url <that>`, which already disables POV/qualifying/HUD-push
  — so no real Sheet is contacted.
- **Profile:** a synthetic profile scaffolded from `profiles/example` into a
  temp dir so Control Center profile resolution resolves. The cockpit secret is
  supplied via `RACECAST_COCKPIT_SECRET` env + `RACECAST_COCKPIT_ENABLED=1`
  (the relay reads both straight from the environment — confirmed at
  `src/relay/racecast-feeds.py:3415`), so no `profile.env` write is needed to
  bring cockpit up.
- **Relay process:** `python3 src/racecast.py relay run` (foreground), bound to
  `127.0.0.1` on a free `--http-port`, owned by the harness. Polled on `/status`
  until ready. Feed threads will fail to pull the fake streams — expected and
  ignored; the control server comes up on its own thread regardless (confirmed:
  feeds are best-effort daemon threads, server start is independent).
- **A second, cockpit-*disabled* relay** (or a pre-enable assertion window) to
  prove `/cockpit/*` returns **404 when disabled**.
- **Control Center:** `python3 src/racecast.py ui --no-browser` on a free
  `RACECAST_UI_PORT`, owned by the harness, polled on its health route.
- **OBS / Tailscale:** never invoked. `--bind auto` falls back to localhost when
  Tailscale is absent; the cockpit program-screenshot (needs OBS) is simply not
  asserted in synthetic mode.

## Checks

Core API checks (run in **both** modes unless noted):

| Check | Asserts | Guards |
|---|---|---|
| `status_ok` | `/status` → 200, valid JSON, expected feed/mode shape | baseline |
| `cockpit_requires_token` | `/cockpit` and `/cockpit/data` → **401** without a token | auth boundary |
| `cockpit_accepts_token` | with a valid `mint_token` → **200** + `Set-Cookie: rc_cockpit` | auth boundary |
| `cockpit_404_when_disabled` | second relay w/o the enable flag → `/cockpit/*` **404** | gating |
| `cockpit_tally` | `/cockpit/data` `on_air`/`up_next` correct for the synthetic schedule, **no double "stint"** | #191 tally bug |
| `cockpit_timer_renders` | `/cockpit/timer` returns real values, not `—` | #191 timer bug |
| `chat_round_trip` | `POST /chat/send` then `GET /chat/data` returns the message | chat |
| `submission_pending` | own-row `POST /cockpit/submit` lands **pending**; `/submissions/*` (tailnet) lists it | submissions |
| `cc_api_cockpit` | Control Center `/api/cockpit/*` responds | CC integration |
| `enable_preserves_keys` | `cockpit enable` against the synthetic profile **keeps** pre-existing `profile.env`/`.env` keys | #191 env-clobber bug |

Optional Playwright checks (gated, **skip** when unavailable):

| Check | Asserts |
|---|---|
| `render_tally_pill` | `/cockpit` renders the ON AIR / UP NEXT tally pill correctly |
| `render_funnel_pill` | the funnel-state pill renders the expected state |

The funnel-CapMap-key #191 bug is covered by the existing
`tests/test_funnel_setup.py` unit path; it is not HTTP-observable in synthetic
mode (no real tailnet), so it is **not** re-asserted here — noted so the gap is
explicit rather than assumed-covered.

## Error handling & teardown

- **Guaranteed teardown:** every spawned process (both relays, Control Center,
  CSV server thread) is killed + reaped in a `finally`, even on assertion
  failure or `KeyboardInterrupt`. `--keep` skips teardown for manual debugging.
- **Readiness, not sleeps:** poll `/status` and the UI health route with a
  bounded `--timeout`; on a service that never comes up, fail fast and dump the
  captured child stdout/stderr for diagnosis.
- **Skip vs fail:** optional capabilities skip with a notice; only real
  assertion failures exit non-zero.
- **No leaked state:** all writes land in a temp dir (synthetic) or the
  gitignored repo `profiles/`/`runtime/` copies (real-league) — never the
  deployed instance, never a committed path.

## Self-testing

The harness's **pure** pieces get a unit test, `tests/test_e2e.py` (runnable
script, stdlib, picked up by `tools/run-tests.py` and CI):

- synthetic-CSV builder produces a valid, parseable schedule;
- free-port helper returns a bindable port;
- check-registry runner aggregates pass/fail/skip and computes the right exit
  status;
- skip/fail classifier maps an absent capability to `skip` and a wrong assertion
  to `fail`.

The heavy end-to-end run (spawning real relays) is **not** in the unit suite —
it is the dedicated `tools/e2e.py` CI step. This keeps the fast inner loop fast
while still TDD-guarding the driver's own logic.

## File touch-list

- **New:** `tools/e2e.py` (driver), `tools/e2e_checks.py` (assertion core),
  `tests/test_e2e.py` (unit tests for the pure pieces).
- **Edit:** `.github/workflows/ci.yml` (add the synthetic e2e step).
- **Docs:** a short note in the relevant wiki/maintainer page that
  `tools/e2e.py` exists and how to run both modes (the `racecast-local-uat`
  skill already documents the real-league setup it builds on).

## Open questions / assumptions

- **Assumption:** the relay tolerates missing `yt-dlp`/`streamlink`/`ffmpeg`/
  `deno` at startup (feeds fail in daemon threads, server stays up). Verified by
  reading the startup path; the first implementation test confirms it on the CI
  runner, which has none of those installed.
- **Assumption:** `racecast ui` exposes a pollable health/route to detect
  readiness without a browser; if not, add a tiny `/api/health`-style probe or
  poll an existing cheap `/api/*` route. To confirm during implementation.
