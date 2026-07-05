# OBS Refresh: forced on `event start` + Director-Panel action — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee `racecast event start`/`takeover` always clears stale relay-served OBS browser sources, and add a one-click **OBS Refresh** action to the Director Panel SETUP tab (works over Funnel for a remote producer).

**Architecture:** Three small, independent changes on the existing rails. (1) Flip the bring-up refresh at `src/racecast.py:3236` to `force=True` (bypasses only the hash gate). (2) Add a thin `POST /obs/refresh` branch to the relay `do_POST`, mirroring the sibling `/obs/*` branches, dispatching to the already-imported `_obs_ws.refresh_browser_inputs`. (3) Add a SETUP-tab button that calls the existing `obsPost` shim. Auth is automatic: `console_policy.py:77` already director-gates `p[0]=="obs"`.

**Tech Stack:** Pure Python 3 stdlib (no framework), a single inline-HTML/JS Director Panel file, stdlib-only test scripts (no pytest).

**Spec:** `docs/superpowers/specs/2026-07-05-obs-refresh-event-start-and-panel-design.md`

## Global Constraints

- **Edit only under `src/`** (+ `docs/` for the spec/plan and `src/docs/wiki/images/` for the screenshot). `dist/`/`runtime/` are generated — never hand-edit.
- **English only** in all shipped scripts, docs, comments, and UI copy.
- **No new public surface.** `/console/obs/refresh` is a sub-path of the existing `/console` mount, director-gated by the pre-existing policy; OBS-WebSocket is never funnelled.
- **Best-effort OBS contract:** OBS helpers never raise; an unreachable OBS yields a note, not a crash.
- **Changed UI surface (Director Panel) ⇒ refresh its wiki screenshot in the SAME change:** regenerate `src/docs/wiki/images/director-panel.png` (Task 4). Run `ui-visual-verification` before claiming done (blocking Stop hook).
- **Gates:** `python3 tools/run-tests.py` and `python3 tools/lint.py` must pass.
- Tests are stdlib-only runnable scripts under `tests/` (function names prefixed `t_`); run one file with `python3 tests/test_<x>.py`.

---

## File Structure

- `src/racecast.py` — bring-up sequence (`event_start`). One-line change at the refresh call.
- `src/relay/racecast-feeds.py` — relay HTTP dispatch (`do_POST`). New `["obs","refresh"]` branch.
- `src/director/director-panel.html` — SETUP tab. New `OBS` bus section + click handler.
- `CLAUDE.md` — architecture note listing the OBS endpoints (four → five).
- `src/docs/wiki/images/director-panel.png` — regenerated screenshot.

No new files. No test changes: the `refresh_browser_inputs` `(names, note)` contract is already fully covered in `tests/test_obsws.py` (success `t_refresh_browser_inputs_end_to_end_against_fake_server` + unreachable `t_refresh_browser_inputs_unreachable_is_quiet`), and the sibling `/obs/{scene,source,audio,state}` branches carry no do_POST-level tests — the new branch is the same thin dispatch pattern, verified end-to-end by `ui-visual-verification` (Task 4) + the full suite.

---

## Task 1: Force the bring-up OBS refresh

**Files:**
- Modify: `src/racecast.py:3236`

**Interfaces:**
- Consumes: `_refresh_obs_pages(force=False, wait=0)` (already defined at `src/racecast.py:2160`); `_check_scene_collection()` (already at `3114`).
- Produces: nothing new — behavioural change only. `event_takeover` inherits it via its `event_start(...)` call at `3429`.

- [ ] **Step 1: Read the exact call site to confirm the line**

Run: `grep -n "_check_scene_collection()" src/racecast.py`
Expected: a hit at line ~3235, immediately followed by `_refresh_obs_pages()` at ~3236. Confirm the preceding comment block (lines ~3230-3234) documents "refresh must come after" the collection switch.

- [ ] **Step 2: Make the one-line change**

In `src/racecast.py`, in `event_start`, change the refresh call so it is forced:

```python
    # OBS may not have been running when relay_start's refresh hook fired
    # (event start launches OBS AFTER the relay) — retry now that both sides
    # are up. Forced (not hash-gated): a re-run / takeover where the served
    # page bytes are unchanged must still clear OBS's cached browser sources,
    # otherwise stale HUD/overlay pages survive the bring-up. Also guarantees
    # _sync_pov_transform runs (it is nested inside the refresh).
    _check_scene_collection()
    _refresh_obs_pages(force=True)
```

(The only functional edit is `_refresh_obs_pages()` → `_refresh_obs_pages(force=True)`; update the adjacent comment as shown so the intent is documented.)

- [ ] **Step 3: Verify the relay-up gate is preserved (read-only check)**

Run: `sed -n '2160,2205p' src/racecast.py`
Expected: `_refresh_obs_pages` still starts with the relay-up wait (`wait_for(_relay_http_ok, wait)`); `force` only bypasses `refresh_decision`. No change needed here — this step just confirms forcing does not skip the liveness gate.

- [ ] **Step 4: Smoke-test the CLI still imports and the racecast unit tests pass**

Run: `python3 tests/test_racecast.py && python3 -c "import ast; ast.parse(open('src/racecast.py').read()); print('parse ok')"`
Expected: tests print OK / no failures, then `parse ok`.

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py
git commit -m "fix(obs): force the OBS page refresh at event start bring-up

A re-run or takeover where the served overlay bytes are unchanged left the
hash gate skipping refreshnocache, so OBS kept stale HUD/overlay browser
sources. Force it after the scene-collection check so every bring-up (and
event takeover, via event_start) clears them; also guarantees the nested
_sync_pov_transform runs.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add the `POST /obs/refresh` relay endpoint

**Files:**
- Modify: `src/relay/racecast-feeds.py` (insert a branch right after the `["obs","state"]` block, currently ending at line 7327)

**Interfaces:**
- Consumes: `_obs_ws.refresh_browser_inputs(needle=...)` → returns `(refreshed_input_names: list[str], note: str)`, best-effort (never raises; unreachable → `([], reason)`), defined at `src/scripts/obs_ws.py:599`. `self._send(payload: dict, status: int = 200)`. `self.server.server_address` → `(host, port)`.
- Produces: HTTP `POST /obs/refresh` (and `/console/obs/refresh` behind Funnel) returning JSON `{"ok": true, "count": <int>, "note": <str>}`, or `503 {"error": "obs unavailable"}` when the relay was started without the `obs_ws` module. Consumed by the panel handler in Task 3.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n 'p == \["obs", "state"\]' src/relay/racecast-feeds.py`
Expected: a hit at ~7319. The block ends with `return self._send({"ok": True, **state})` at ~7327; insert the new branch immediately after that line (before `if p == ["parts", "start"]:`).

- [ ] **Step 2: Add the endpoint branch**

Insert into `do_POST`, right after the `["obs", "state"]` block:

```python
                if p == ["obs", "refresh"]:
                    # Reload the relay-served OBS browser sources (HUD / overlay /
                    # timer) — the programmatic right-click -> Refresh. Unconditional
                    # force (no hash gate; the CLI owns obs-pages.hash): the director
                    # presses this precisely to clear stale caches. Best-effort like
                    # the other /obs/* branches. Auto director-gated by console_policy
                    # (p[0] == "obs"); reachable over Funnel only under /console.
                    if _obs_ws is None:
                        return self._send({"error": "obs unavailable"}, 503)
                    port = self.server.server_address[1]
                    names, note = _obs_ws.refresh_browser_inputs(
                        needle=f"127.0.0.1:{port}")
                    return self._send({"ok": True, "count": len(names),
                                       "note": note or
                                       f"Refreshed {len(names)} browser source(s)"})
```

Notes for the implementer:
- Match the surrounding indentation exactly (these branches sit at 16-space indent inside the `try` in `do_POST`). Use the same `if p == [...]:` form (not `elif`) as its neighbours — each branch `return`s.
- `self.server.server_address[1]` is the control port (`args.http_port`, default 8088) regardless of which bind (loopback or tailnet) served the request; OBS browser sources always point at `127.0.0.1:<that port>`, mirroring the CLI's `needle=f"127.0.0.1:{RELAY_PORT}"`.
- Do **not** call `_sync_pov_transform` or touch `obs-pages.hash` here — out of scope (KISS); the panel refresh means "reload the browser sources" only.

- [ ] **Step 3: Confirm the underlying contract is already tested (read-only)**

Run: `python3 tests/test_obsws.py`
Expected: OK — including `t_refresh_browser_inputs_end_to_end_against_fake_server` (returns `(names, note)`, presses `refreshnocache`) and `t_refresh_browser_inputs_unreachable_is_quiet` (`([], reason)`). No new test is required; the branch is a thin dispatch over this proven primitive (the sibling `/obs/*` branches likewise have no do_POST test).

- [ ] **Step 4: Import-smoke the relay module (catches syntax/indent errors)**

Run:
```bash
python3 -c "import importlib.util, os; s=importlib.util.spec_from_file_location('irofeeds', os.path.join('src','relay','racecast-feeds.py')); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('relay import ok')"
```
Expected: `relay import ok` (this is how `tests/test_parts.py` loads the relay — a clean load proves the new branch parses).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(obs): POST /obs/refresh relay endpoint (reload OBS browser sources)

Thin director-gated dispatch to obs_ws.refresh_browser_inputs, mirroring the
sibling /obs/* branches. Unconditional force; best-effort. Auto-gated by the
existing console_policy p[0]=='obs' rule, so it reaches /console/obs/refresh
over Funnel with no new public surface.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add the SETUP-tab OBS Refresh button

**Files:**
- Modify: `src/director/director-panel.html` (HTML: new bus section after `#txBar`, ~line 631; JS: handler near `obsScene`, ~line 1048)

**Interfaces:**
- Consumes: `obsPost(path, body)` (defined at `director-panel.html:1016`, POSTs `RC_API("/obs/"+path)`, drives the OBS status LED, returns the parsed JSON); `log(msg, level)` (existing, `level` optional — `"warn"` used at line 1046); `$(sel)` (existing shorthand). Server endpoint `POST /obs/refresh` from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the button — a new `OBS` bus section right after `#txBar`**

In `src/director/director-panel.html`, insert immediately after the closing `</section>` of `#txBar` (after line 631, before the `<details ... id="urlsBox">` block):

```html
  <section class="bus" id="obsBus"
           title="Reload the relay-served OBS browser sources (HUD / overlay / timer) — clears OBS's cached pages">
    <div class="cap">OBS</div>
    <div class="keys">
      <button class="k" id="obsRefreshBtn">↻ REFRESH</button>
    </div>
  </section>
```

This reuses the existing `bus` / `cap` / `keys` / `k` pattern (same as Scn·Vis, Gfx, Timer, Audio, Transition) so it needs no new CSS, and it is its own action section beside the Transition bar (not part of the armed-transition selector).

- [ ] **Step 2: Wire the click handler**

In the JS, right after the `obsScene` / `obsSource` / `obsStream` definitions (after line 1052), add:

```javascript
{ const b = $("#obsRefreshBtn"); if (b) b.addEventListener("click", async () => {
    const d = await obsPost("refresh", {});
    if (d && d.ok) log("OBS refresh — " + (d.note || (d.count + " source(s)")));
    else log("OBS refresh failed" + (d && d.error ? ": " + d.error : ""), "warn");
  }); }
```

`obsPost` already sets the OBS status LED from the HTTP result, so no extra LED handling is needed.

- [ ] **Step 3: Static sanity check of the edited HTML**

Run:
```bash
grep -n 'id="obsRefreshBtn"' src/director/director-panel.html && grep -c 'id="obsBus"' src/director/director-panel.html
```
Expected: the button line prints once and the section count is `1`.

- [ ] **Step 4: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): OBS Refresh action in the SETUP tab

New OBS bus section beside the Transition bar; posts /obs/refresh via the
existing obsPost shim (director-gated, works over Funnel for a remote
producer) and logs how many browser sources were refreshed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Visual verification + regenerate the wiki screenshot

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` (regenerated)

This task has no code; it satisfies the repo's hard "changed UI surface ⇒ refresh its wiki screenshot in the same change" rule and the `ui-visual-verification` Stop-hook gate. It requires a running dev build (relay from `src/`, no `VERSION` stamped) with the fake-content recipe (demo profile + `tools/obs-sim.py` OBS stand-in) as documented in the `wiki-screenshots` skill.

- [ ] **Step 1: Invoke the `ui-visual-verification` skill on the Director Panel change**

Render the SETUP tab, confirm the new **OBS ↻ REFRESH** button appears in its own `OBS` bus beside the Transition bar and is styled like the other keys. Click it against the obs-sim stand-in and confirm: the OBS status LED reacts, and the log shows `OBS refresh — N source(s)` (or a best-effort note when OBS is unreachable). Record the marker the Stop hook requires.

- [ ] **Step 2: Regenerate the wiki screenshot**

Invoke the `wiki-screenshots` skill to recapture the Director Panel image (element screenshot framed like the existing one) and write it to `src/docs/wiki/images/director-panel.png`. Follow the skill's reproducible fake-content recipe (demo profile + obs-sim); capture from the local dev build so the version badge stays uniform.

- [ ] **Step 3: Confirm the image changed**

Run: `git status --porcelain src/docs/wiki/images/director-panel.png`
Expected: the file shows as modified (` M ...`).

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/director-panel.png
git commit -m "docs(wiki): refresh Director Panel screenshot for the OBS Refresh action

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Docs (CLAUDE.md) + full gates

**Files:**
- Modify: `CLAUDE.md` (the "Relay-mediated OBS control (Director Panel)" paragraph)

**Interfaces:** none (documentation + verification).

- [ ] **Step 1: Update the endpoint list in CLAUDE.md**

Find the paragraph beginning "**Relay-mediated OBS control (Director Panel).**". It currently says "Four director-gated endpoints … `POST /obs/scene` … `POST /obs/source` … `POST /obs/audio` … `POST /obs/state`". Change "Four" → "Five" and add the new endpoint to the list, e.g. after `/obs/state`:

```
`POST /obs/refresh` (reload the relay-served OBS browser sources — the
programmatic right-click → Refresh; best-effort; unconditional force)
```

Keep the existing sentences about relay-mediation, the best-effort contract, and OBS-WebSocket never being funnelled — the new endpoint follows all of them.

Run: `grep -n "POST /obs/refresh" CLAUDE.md`
Expected: one hit.

- [ ] **Step 2: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass (exactly what CI runs).

- [ ] **Step 3: Run the linter**

Run: `python3 tools/lint.py`
Expected: no findings (rules mirror the CodeQL alert classes).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note the new POST /obs/refresh relay endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** Part 1 (force bring-up refresh) → Task 1. Part 2 (`POST /obs/refresh`) → Task 2. Part 3 (SETUP-tab button) → Task 3. Repo obligations: wiki screenshot + visual verification → Task 4; CLAUDE.md endpoint note → Task 5; test/lint gates → Task 5. `event takeover` coverage → Task 1 (inherited via `event_start`). No spec requirement is unmapped.
- **Placeholder scan:** none — every code step shows the exact code; verification steps show exact commands + expected output.
- **Type consistency:** `refresh_browser_inputs` is used as `(names, note)` everywhere (matches `obs_ws.py:599` + its tests). The endpoint returns `{ok, count, note}`; the panel handler reads exactly `d.ok`, `d.note`, `d.count`, `d.error`. `obsPost("refresh", {})` matches the `POST /obs/refresh` route. `self._send(payload, status=200)` matches the sibling branches.
- **No-test-change rationale (explicit):** the `(names, note)` contract is fully covered by `tests/test_obsws.py`; the do_POST branch is a thin dispatch with no sibling precedent for a handler-level test, and is verified end-to-end by `ui-visual-verification` (Task 4) plus `tools/run-tests.py` (Task 5). This is a deliberate, honest choice, not an omission.
