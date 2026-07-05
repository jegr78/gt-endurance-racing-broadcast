# OBS browser-source refresh: forced on `event start` + a Director-Panel action

**Date:** 2026-07-05
**Status:** Design approved, pending implementation

## Problem

The relay serves OBS browser sources (HUD, split-screen overlay, race timer). OBS's
CEF caches page JS aggressively, so after the relay changes what it serves — or after
OBS was already running with stale cached sources — the operator sees an old page until
a `refreshnocache` is pressed on each browser source.

Two gaps motivate this change, both sharpened by the **remote-producer (GCP)** setup
where the Director Panel is the only OBS console a remote director has:

1. **Bring-up is not guaranteed to clear stale sources.** `racecast event start` already
   runs, in order, `_check_scene_collection()` → `_refresh_obs_pages()`
   (`src/racecast.py:3235-3236`). But the second call is `force=False`, i.e. **hash-gated**:
   `_refresh_obs_pages` computes `served_pages_hash()` and, via `refresh_decision`, returns
   early with `skip-unchanged` when the served page bytes match the stored
   `runtime/obs-pages.hash`. In that case **no `refreshnocache` fires** and stale sources
   survive. This is exactly the re-run / takeover / "OBS was already up" case. (On a truly
   fresh GCP box the collection switch rebuilds every source and there is no stored hash,
   so it happens to work — but the guarantee is missing precisely where it is needed.)

2. **There is no way to trigger a refresh from the Director Panel.** The relay exposes
   `POST /obs/{scene,source,audio,state}` (director-gated) but **no** `/obs/refresh`. The
   refresh primitive `obs_ws.refresh_browser_inputs()` is imported into the relay as
   `_obs_ws` but never called by any relay path — the refresh logic lives entirely in the
   CLI (`racecast obs refresh` / the bring-up hook). A remote director on `/console/panel`
   therefore cannot clear stale sources without shell access to the producer machine.

## Goal

- Guarantee that every `event start` (and, transitively, `event takeover`) clears stale
  relay-served OBS browser sources, right after the scene-collection check/switch.
- Give the Director Panel a one-click **OBS Refresh** action in the SETUP tab that works
  over Funnel for a remote producer, using the existing security model (no new public
  surface, OBS-WebSocket never funnelled).

## Non-goals (YAGNI)

- No POV-box geometry sync in the panel refresh. The panel "OBS Refresh" means "reload the
  relay-served browser sources"; PiP geometry (`_sync_pov_transform`) is a separate concern
  and stays where it is (bring-up + `racecast obs refresh`).
- No hash gate inside the relay. The panel button is a deliberate manual action → an
  unconditional force is the correct semantic. The relay does not maintain
  `runtime/obs-pages.hash` (only the CLI does); leaving it untouched is harmless.
- No new CLI command — `racecast obs refresh` already exists and is unchanged.

## Design

### Part 1 — Force the bring-up refresh

`src/racecast.py`, in `event_start` (the line currently at `3236`):

```python
_check_scene_collection()
_refresh_obs_pages(force=True)   # was: _refresh_obs_pages()
```

- **Ordering is unchanged:** collection check/switch first (a switch rebuilds every source),
  then the forced refresh. This is the ordering the existing comment at
  `src/racecast.py:3230-3234` already documents.
- `force=True` bypasses **only** the hash gate (`refresh_decision`), not the relay-up gate
  (`wait_for(_relay_http_ok, wait)`). At this point relay + OBS are already confirmed up via
  `ev.wait_until_up`, so the forced refresh always reaches
  `obs_ws.refresh_browser_inputs(...)`.
- **Side benefit:** `_sync_pov_transform()` runs inside `_refresh_obs_pages` only on a
  non-skipped refresh; forcing therefore also guarantees the POV-box transform is synced at
  every bring-up (today it is skipped when the hash is unchanged).
- On success `_refresh_obs_pages` still calls `write_pages_hash(...)`, so subsequent CLI
  refreshes (`racecast obs refresh`, later overlay edits) keep gating normally.
- **`event takeover` inherits this** automatically — it calls `event_start(...)`
  (`src/racecast.py:3429`), so the remote/handover path is covered with no extra change.

No test asserts this call site today (bring-up spawns real processes). The change is a
single argument; correctness is covered by the existing `_refresh_obs_pages` unit behaviour.

### Part 2 — `POST /obs/refresh` relay endpoint

`src/relay/racecast-feeds.py`, in `do_POST`, a new branch next to the `["obs","scene"]`
block (~line 7274), following the identical guard pattern as the other `/obs/*` branches:

```python
elif p == ["obs", "refresh"]:
    if _obs_ws is None:
        # 503, JSON {"ok": false, "error": "obs unavailable"} — same as the other /obs/* branches
    else:
        port = self.server.server_address[1]     # the control port the browser sources point at
        names, note = _obs_ws.refresh_browser_inputs(needle=f"127.0.0.1:{port}")
        count = len(names)
        # 200, JSON {"ok": true, "count": count,
        #            "note": note or f"Refreshed {count} browser source(s)"}
```

Notes:
- `refresh_browser_inputs()` **already** returns `(refreshed_input_names, note)` and is
  best-effort (never raises; a failed connect yields `([], reason)`). So **no change to
  `obs_ws.py` is needed** — the endpoint just surfaces the count and note. A non-empty
  `note` (e.g. an obs-websocket connect failure) is passed through so the panel can show it;
  `ok` stays `true` because the call itself did not error (mirrors the best-effort contract
  of the other OBS endpoints, e.g. `get_program_screenshot`). An unreachable OBS therefore
  yields `{ok:true, count:0, note:"<reason>"}` and the panel logs it.
- **Needle:** OBS reaches the relay-served pages on the fixed loopback
  `127.0.0.1:<control-port>` (CLAUDE.md), and every bound server shares `args.http_port`, so
  `self.server.server_address[1]` is the correct port regardless of which bind (loopback or
  tailnet) served the POST. This mirrors the CLI's `needle=f"127.0.0.1:{RELAY_PORT}"`.
- **Auth is automatic:** `src/scripts/console_policy.py:77` already maps `p[0] == "obs"` to
  `Requirement(DIRECTOR, False)`, so `/console/obs/refresh` is director-gated over Funnel and
  `/obs/refresh` on the bare tailnet uses the tailnet trust boundary — identical to the
  existing OBS actions. **No new public surface** (sub-path of the existing `/console` mount);
  OBS-WebSocket is still only ever called locally by the relay, never funnelled.

### Part 3 — SETUP-tab button

`src/director/director-panel.html`, SETUP tab (`#tabSetup`), a small dedicated action row
directly at/below the Transition bar (`#txBar`, ~line 631):

```html
<div class="setup-actions">
  <button class="k act" id="obsRefreshBtn"
          title="Reload the relay-served OBS browser sources (HUD / overlay / timer) — clears stale caches">
    ↻ OBS Refresh
  </button>
</div>
```

Handler (near the other SETUP-tab JS, using the existing `obsPost` + `log` helpers):

```js
$("#obsRefreshBtn").addEventListener("click", async () => {
  const d = await obsPost("refresh", {});               // obsPost already drives the OBS status LED
  if (d && d.ok) log(`OBS refresh: ${d.note || "done"}`);
  else log("OBS refresh failed", "warn");
});
```

- `obsPost` (`director-panel.html:1016`) already prefixes `RC_API("/obs/refresh")` (→
  `/console/obs/refresh` over Funnel, `/obs/refresh` on tailnet), sends the cookie, and sets
  the OBS status LED from `r.ok && d.ok`. No new plumbing.
- Styling matches the existing SETUP-tab keys (`.k`); it is a plain action key, not part of
  the armed-transition selector (which is a state selector, not an action).

## Testing

- **`tests/test_obsws.py`** — the existing `refresh_browser_inputs` fake-session coverage
  already asserts it returns the matched names + presses `refreshnocache`; confirm it covers
  the "returns `(names, note)`" contract the endpoint relies on, and add an assertion for the
  empty/unreachable case (`([], reason)`) if not already present. No production `obs_ws.py`
  change.
- Relay `do_POST` dispatch is thin and follows the established `/obs/*` pattern; if a
  lightweight handler-dispatch test harness exists for the sibling endpoints, add a
  `["obs","refresh"]` case there (route → `_obs_ws.refresh_browser_inputs` called with the
  loopback needle; `_obs_ws is None` → 503). Otherwise rely on the obs_ws unit test + manual
  UAT.
- Full gates: `python3 tools/run-tests.py` and `python3 tools/lint.py`.

## Repo-rule obligations (same change, not a follow-up)

- **Wiki screenshot:** the Director Panel is a tracked UI surface. Regenerate
  `src/docs/wiki/images/director-panel.png` via the **`wiki-screenshots`** skill and commit it
  alongside the code.
- **Visual verification:** run the **`ui-visual-verification`** skill on the panel change
  (blocking Stop hook `ui_visual_verify_gate.py`) before claiming done.
- **CLAUDE.md:** extend the "Relay-mediated OBS control (Director Panel)" paragraph — it lists
  four director-gated endpoints (`/obs/scene`, `/obs/source`, `/obs/audio`, `/obs/state`); add
  the fifth, `POST /obs/refresh` (reloads the relay-served OBS browser sources; best-effort;
  director-gated; funnelled only under `/console`).

## Security & remote-producer notes

- The endpoint adds no public surface: it lives under the existing `/console` mount and is
  director-gated by the pre-existing `p[0]=="obs"` policy rule.
- OBS-WebSocket is still only ever spoken locally by the relay; the password never crosses the
  network and OBS-WebSocket is never funnelled — so a remote director on `/console/panel`
  refreshes the producer's OBS sources using only the per-person director token.
