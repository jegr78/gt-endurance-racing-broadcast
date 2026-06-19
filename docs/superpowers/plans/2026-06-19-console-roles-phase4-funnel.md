# Phase 4 — Funnel mount → /console (#216) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the public Tailscale-Funnel mount from `/cockpit` to `/console`, replace the `racecast cockpit funnel` subcommand with a canonical top-level `racecast funnel on|off`, repoint all reissued crew links to the role-adaptive `/console` launcher, and lock the boundary invariant (only `/console` is mounted) with a test.

**Architecture:** The relay already serves `/console/*` with `/console`-scoped cookies (Phase 3b, merged). Phase 4 changes only *which path Funnel exposes* and *where links point* — no relay (`racecast-feeds.py`) changes. The Funnel helpers in `tailscale.py` are already path-parameterized; we flip their defaults and the single CLI call site from `/cockpit` to `/console`. The `cockpit funnel` verb is removed (a new top-level `funnel` command replaces it); the auto-enable env is renamed `RACECAST_COCKPIT_FUNNEL` → `RACECAST_FUNNEL` with a one-release legacy read-fallback so event-day auto-enable does not silently break.

**Tech Stack:** Python 3.11+ stdlib only (no framework, no package manager). Tests are runnable `tests/test_*.py` scripts (no pytest); the relay is loaded via `importlib`. `tools/run-tests.py` auto-discovers test files.

## Global Constraints

- **Edit only under `src/`** (plus `tests/`, `docs/`, `.env.example`, `CLAUDE.md`, `README.md`). Never hand-edit `dist/`/`runtime/`.
- **English only** in all code and docs.
- **No machine paths / real IPs / secrets** in committed files. Tailscale test IPs are the `100.64.0.0/10` range only.
- **Cross-platform:** the test matrix includes Windows. Build fixed-OS absolute paths with explicit forward slashes, never `os.path.join`.
- **Relay stays stdlib-only.** Do not add imports to `racecast-feeds.py` (this phase does not touch it).
- **The single Funnel mount is the security boundary.** Only `/console` may be mounted publicly; no root path, no `/cockpit`, may appear in the Funnel argv. This is the invariant the boundary test locks.
- **User-locked decisions:** (1) the `cockpit funnel` verb is REMOVED — only `racecast funnel` remains; (2) reissued crew links point at the `/console` launcher (`…/console?t=<token>`), one role-adaptive link per person.
- **Conventional-commit PR title** (release-please parses the squash subject): `feat(cli): …` for this phase.
- **Commit trailer:** end every commit body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

### Deferred to later phases (do NOT do here — tracked so they are not silently dropped)

- **Control Center cockpit-card visible text + `cc-cockpit.png` refresh** → **Phase 5** ("Control Center surfacing"). Phase 4 changes the Control Center **data layer only** (link URLs, env key) — which is invisible in the committed screenshot — and must NOT edit `src/ui/control-center.html`. The help string "Exposes only `/cockpit` publicly" stays as-is until Phase 5 reshapes the card and refreshes the one screenshot. (Editing the HTML here would mandate an immediate screenshot refresh that Phase 5 would redo.)
- **Per-role link CLI generalization** (a `console links` command, role-aware naming) → **Phase 5**. Phase 4 only *repoints* the existing `cockpit links` / `cockpit_status_data` URLs to `/console`.
- **`Commentator-Cockpit.md` narrative + embedded-screenshot rewrite** → **Phase 5**. Phase 4 updates only the literal command token in that file (`racecast cockpit funnel` → `racecast funnel`) so the documented command exists; the surrounding prose and the embedded `cc-cockpit.png` are refreshed in Phase 5.

---

## File Structure

- `src/scripts/tailscale.py` — Funnel helper defaults flip `/cockpit` → `/console` (Task 1).
- `tests/test_tailscale.py` — boundary test + updated argv assertions (Task 1).
- `src/racecast.py` — new `funnel` top-level command; remove `cockpit funnel`; env rename; link repoint (Task 2).
- `tests/test_racecast.py` — route tests for the new command + removed verb (Task 2).
- `tests/test_ui_server.py` — update the mock cockpit-link fixture `/cockpit` → `/console` for realism (Task 2).
- `.env.example` — rename the env key + correct its comment (Task 2).
- `CLAUDE.md`, `README.md`, `src/docs/wiki/Commentator-Cockpit.md` — CLI command reference updates (Task 3).

---

### Task 1: Generalize the Funnel helpers to `/console` + boundary test

**Files:**
- Modify: `src/scripts/tailscale.py` (defaults at the `parse_funnel_serving` and `funnel_on` definitions; the `funnel_args` docstring comment ~line 279)
- Test: `tests/test_tailscale.py` (`t_funnel_args`, `t_parse_funnel_serving`; add `t_funnel_args_mounts_only_console`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `funnel_args(path, target_port, enable)` unchanged in signature; its callers now pass `/console`. `parse_funnel_serving(output, path="/console")` and `funnel_on(path="/console", timeout=5)` default to `/console`.

- [ ] **Step 1: Update the boundary/argv test to assert `/console` (write the failing test first)**

In `tests/test_tailscale.py`, change `t_funnel_args` to assert the `/console` argv, and ADD a dedicated boundary test directly after it:

```python
def t_funnel_args():
    on = ts.funnel_args(path="/console", target_port=8088, enable=True)
    assert on == ["funnel", "--bg", "--set-path=/console",
                  "http://127.0.0.1:8088/console"]
    # Teardown ignores path/port and resets the funnel config wholesale: the
    # path-specific `--set-path=… off` form silently failed with "handler does
    # not exist" (#200). `funnel reset` is the only form Tailscale verifiably
    # tears down across the versions we target.
    off = ts.funnel_args(path="/console", target_port=8088, enable=False)
    assert off == ["funnel", "reset"]


def t_funnel_args_mounts_only_console():
    # Boundary invariant (#216): the public Funnel exposes ONLY /console. The
    # enable argv must mount exactly one path-prefix, that prefix must be
    # /console, the reverse-proxy target must stay under /console, and nothing
    # may mount the root ("/") or the old /cockpit prefix. Root control
    # endpoints therefore remain unreachable from the public internet.
    argv = ts.funnel_args(path="/console", target_port=8088, enable=True)
    set_paths = [a for a in argv if a.startswith("--set-path=")]
    assert set_paths == ["--set-path=/console"], set_paths
    assert argv[-1] == "http://127.0.0.1:8088/console"
    assert not any(a == "--set-path=/" or a.endswith("=/cockpit")
                   or a.rstrip("/").endswith("/cockpit") for a in argv)
    assert "/cockpit" not in " ".join(argv)
```

- [ ] **Step 2: Update `t_parse_funnel_serving` to prove the default is `/console` AND the path is still parameterizable**

Replace the body of `t_parse_funnel_serving` (currently asserting `/cockpit`) with:

```python
def t_parse_funnel_serving():
    on = "https://host.ts.net:443\n|-- /console  proxy http://127.0.0.1:8088/console (Funnel on)"
    # Default path is now /console (the #216 migration).
    assert ts.parse_funnel_serving(on) is True
    assert ts.parse_funnel_serving(on, "/console") is True
    # Still parameterizable — an explicit foreign path is not matched.
    assert ts.parse_funnel_serving(on, "/cockpit") is False
    assert ts.parse_funnel_serving("nothing here") is False
    assert ts.parse_funnel_serving("") is False
```

> Note: keep the sample text shape consistent with the existing test's fixture (a `funnel status` line containing the path and "Funnel on"). If the existing fixture string differs, preserve its structure and only swap `/cockpit` → `/console`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_tailscale.py`
Expected: FAIL — `funnel_args` still emits `/cockpit`, `parse_funnel_serving` default still matches `/cockpit`.

- [ ] **Step 4: Flip the helper defaults in `tailscale.py`**

- At the `parse_funnel_serving` definition (~line 139): change `def parse_funnel_serving(output, path="/cockpit"):` → `def parse_funnel_serving(output, path="/console"):`. Update its docstring's `/cockpit` mention to `/console`.
- At the `funnel_on` definition (~line 151): change `def funnel_on(path="/cockpit", timeout=5):` → `def funnel_on(path="/console", timeout=5):`. Update its docstring's `/cockpit` mention to `/console`.
- In the `funnel_args` docstring (~line 279): change the comment `\`racecast cockpit funnel\` only ever mounts /cockpit, so resetting the whole funnel config is the precise teardown here.` → `\`racecast funnel\` only ever mounts /console, so resetting the whole funnel config is the precise teardown here.`
- In the `parse_funnel_capable` docstring (~line 105): change `Lets \`cockpit funnel on\` fail fast` → `Lets \`racecast funnel on\` fail fast`.

Leave `funnel_args` and `funnel` bodies unchanged — they are already path-parameterized.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_tailscale.py`
Expected: PASS (all, including the new boundary test).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/tailscale.py tests/test_tailscale.py
git commit -m "feat(funnel): mount /console as the public Funnel prefix (#216)

Flip the Funnel helper defaults from /cockpit to /console and lock the
boundary invariant — only /console is ever mounted — with a unit test
over funnel_args. The relay already serves /console/* (Phase 3b); this is
the helper-layer half of the migration.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `racecast funnel` command, remove `cockpit funnel`, repoint links + auto-enable env

**Files:**
- Modify: `src/racecast.py` (`route`, `main`, rename `_cockpit_funnel`→`funnel_cmd`, `_cockpit_funnel_auto_enabled`→`_funnel_auto_enabled`, `COCKPIT_VERBS`, `cockpit_cmd`, `cockpit links` URLs, `cockpit_status_data`, `cockpit_set_funnel_auto_data`, the event-start auto-enable block, `cockpit_funnel_data`)
- Modify: `.env.example` (rename `RACECAST_COCKPIT_FUNNEL` → `RACECAST_FUNNEL`)
- Test: `tests/test_racecast.py` (`t_route_cockpit`, add `t_route_funnel`)
- Test: `tests/test_ui_server.py` (mock cockpit-link fixture `/cockpit` → `/console`)

**Interfaces:**
- Consumes: `tailscale.funnel(binary, path="/console", target_port, enable)` from Task 1 (pass `path="/console"` explicitly at the call site).
- Produces:
  - `funnel_cmd(rest)` — top-level handler for `racecast funnel on|off [--force]`; mounts `/console`; replaces `_cockpit_funnel`.
  - `route(["funnel", "on"]) == {"kind": "funnel", "rest": ["on"]}`.
  - `_funnel_auto_enabled()` — reads `RACECAST_FUNNEL` (falls back to legacy `RACECAST_COCKPIT_FUNNEL`).
  - `COCKPIT_VERBS == ("setup-funnel", "links", "token", "pull-versions")` (no `funnel`).

- [ ] **Step 1: Write the failing route tests**

In `tests/test_racecast.py`, edit `t_route_cockpit` to drop the `cockpit funnel` expectation and assert it is now rejected, and ADD a new `t_route_funnel`:

```python
def t_route_cockpit():
    assert m.route(["cockpit", "links"]) == {"kind": "cockpit", "rest": ["links"]}
    assert m.route(["cockpit", "token", "revoke", "Alpha"]) == {
        "kind": "cockpit", "rest": ["token", "revoke", "Alpha"]}
    # `funnel` is no longer a cockpit verb (#216 — it is a top-level command now);
    # like the removed enable/disable verbs it is rejected at route() time.
    for bad in (["cockpit"], ["cockpit", "bogus"], ["cockpit", "enable"],
                ["cockpit", "disable"], ["cockpit", "funnel", "on"]):
        try:
            m.route(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def t_route_funnel():
    assert m.route(["funnel", "on"]) == {"kind": "funnel", "rest": ["on"]}
    assert m.route(["funnel", "off"]) == {"kind": "funnel", "rest": ["off"]}
    # Validation of on|off happens in funnel_cmd, not route(): route stays a
    # pure pass-through for the funnel command (like chat/profile).
    assert m.route(["funnel"]) == {"kind": "funnel", "rest": []}
```

- [ ] **Step 2: Run the route tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); sys.path.insert(0,'src'); import test_racecast as t; t.t_route_funnel()"`
Expected: FAIL — `route` raises `unknown command: funnel`.

- [ ] **Step 3: Add the `funnel` command to `route()` and `main()`**

In `route()` (after the `cockpit` block, ~line 869), add:

```python
    if cmd == "funnel":
        return {"kind": "funnel", "rest": rest}
```

In `main()` (next to the `cockpit` dispatch, ~line 4786), add:

```python
    if action["kind"] == "funnel":
        return funnel_cmd(action["rest"])
```

- [ ] **Step 4: Rename `_cockpit_funnel` → `funnel_cmd`, mount `/console`, retarget messages**

Rename the function (currently `_cockpit_funnel(args)`, ~line 1092) to `funnel_cmd(rest)` and update its body so it mounts `/console` and speaks as a top-level command. Replace the whole function with:

```python
def funnel_cmd(rest):
    """`racecast funnel on|off` — public ingress for ONLY /console via Tailscale
    Funnel (the role-adaptive crew launcher; #216). Requires MagicDNS + HTTPS +
    the 'funnel' nodeAttr (one-time tailnet-admin step); funnel() surfaces the
    verbatim error if missing. Only /console is mounted — root control endpoints
    stay tailnet/loopback-only (the security boundary)."""
    import tailscale as ts
    if not rest or rest[0] not in ("on", "off"):
        sys.exit("usage: racecast funnel {on|off} [--force]")
    enable = rest[0] == "on"
    binary, _state, _ip = ts.tailscale_backend()
    if not binary:
        sys.exit("racecast: Tailscale CLI not found / backend not running.")
    # Fail fast on the one-time prerequisite: without the 'funnel' nodeAttr the
    # `tailscale funnel` CLI blocks on an interactive enable prompt (a 20 s hang
    # with no stdin). Detect it and print the exact admin steps instead.
    if enable and "--force" not in rest and not ts.funnel_capable():
        sys.exit(
            "racecast: this node is not authorized for Tailscale Funnel yet.\n"
            "One-time tailnet-admin setup at https://login.tailscale.com/admin :\n"
            "  1. DNS -> enable MagicDNS AND HTTPS Certificates\n"
            "  2. Access Controls -> grant the 'funnel' nodeAttr, e.g.:\n"
            '       "nodeAttrs": [{ "target": ["autogroup:member"], "attr": ["funnel"] }]\n'
            "Then re-run 'racecast funnel on'. (Use --force to skip this check.)")
    ok, detail = ts.funnel(binary, path="/console", target_port=RELAY_PORT,
                           enable=enable)
    if not ok:
        sys.exit(f"racecast: funnel {'on' if enable else 'off'} failed: {detail}\n"
                 "Hint: enable MagicDNS + HTTPS and add the 'funnel' nodeAttr in the "
                 "tailnet policy (one-time admin step).")
    print(f"funnel {'enabled' if enable else 'disabled'}. {detail}".strip())
    return None
```

- [ ] **Step 5: Remove the `funnel` verb from the cockpit command surface**

- `COCKPIT_VERBS` (~line 1040): change to `COCKPIT_VERBS = ("setup-funnel", "links", "token", "pull-versions")`.
- In `cockpit_cmd` (~line 1239): delete the two lines

  ```python
      if verb == "funnel":
          return _cockpit_funnel(args)
  ```

- Update the `cockpit_cmd` docstring (~line 1202-1205): change `funnel|links|token|setup-funnel|pull-versions` → `links|token|setup-funnel|pull-versions` and the final sentence `PUBLIC exposure is \`cockpit funnel\`.` → `PUBLIC exposure is the top-level \`racecast funnel\` command.`

- [ ] **Step 6: Repoint the remaining `_cockpit_funnel` callers to `funnel_cmd`**

- Event-start auto-enable (~line 2393-2398): replace `_cockpit_funnel(["on"])` with `funnel_cmd(["on"])`; update the comment block (~line 2390-2392) `opt-in via RACECAST_COCKPIT_FUNNEL): publish /cockpit publicly` → `opt-in via RACECAST_FUNNEL): publish /console publicly`; and the catch line (~line 2398) `print("cockpit funnel: skipped — " ...)` → `print("funnel: skipped — " ...)`.
- `cockpit_funnel_data(on)` (~line 3413-3418): replace `_cockpit_funnel(["on" if on else "off"])` with `funnel_cmd(["on" if on else "off"])`.

- [ ] **Step 7: Rename the auto-enable helper + env key (with legacy fallback)**

Rename `_cockpit_funnel_auto_enabled` → `_funnel_auto_enabled` (~line 3327) and read the new env key with a one-release legacy fallback:

```python
def _funnel_auto_enabled():
    """Opt-in: bring the public /console Funnel up on `event start`. Requires the
    machine flag RACECAST_FUNNEL (legacy RACECAST_COCKPIT_FUNNEL still honored for
    one release) AND the cockpit actually usable (a league secret + enabled) —
    reads on-disk truth via cockpit_status_data()."""
    epath = _env_file()
    if not os.path.exists(epath):
        return False
    with open(epath, encoding="utf-8") as fh:
        env = parse_env_text(fh.read())
    flag = env.get("RACECAST_FUNNEL", env.get("RACECAST_COCKPIT_FUNNEL", ""))
    if flag.strip().lower() not in ("1", "true", "yes", "on"):
        return False
    st = cockpit_status_data()
    return bool(st.get("ok") and st.get("enabled") and st.get("has_secret"))
```

Update the event-start call site (Step 6) to call `_funnel_auto_enabled()`.

> Note: `cockpit_status_data()` may not actually return an `enabled` key (zero-config). Preserve whatever gate the ORIGINAL `_cockpit_funnel_auto_enabled` used verbatim — copy its `st.get(...)` expression exactly; only the env read and the function name change here. If the original checked `st.get("ok") and st.get("enabled") and st.get("has_secret")`, keep that; if it checked something else, keep that instead.

- [ ] **Step 8: Repoint link builders and the funnel-auto writer to `/console` + `RACECAST_FUNNEL`**

- `cockpit links` (~line 1227-1228): change
  - `url = f"https://{magic}/cockpit?t={tok}"` → `url = f"https://{magic}/console?t={tok}"`
  - `lan = f"http://{host}:{RELAY_PORT}/cockpit?t={tok}"` → `lan = f"http://{host}:{RELAY_PORT}/console?t={tok}"`
- `cockpit_status_data` (~line 3370): change the env read `menv.get("RACECAST_COCKPIT_FUNNEL", "")` → `menv.get("RACECAST_FUNNEL", menv.get("RACECAST_COCKPIT_FUNNEL", ""))`.
- `cockpit_status_data` links (~line 3383-3385): change both URLs:
  - `f"http://{host}:{RELAY_PORT}/cockpit?t={tok}"` → `f"http://{host}:{RELAY_PORT}/console?t={tok}"`
  - `f"https://{magic}/cockpit?t={tok}"` → `f"https://{magic}/console?t={tok}"`
  - `f"https://<magicdns-host>/cockpit?t={tok}"` → `f"https://<magicdns-host>/console?t={tok}"`
- `cockpit_set_funnel_auto_data` (~line 3404): change `_set_env_key(_env_file(), "RACECAST_COCKPIT_FUNNEL", ...)` → `_set_env_key(_env_file(), "RACECAST_FUNNEL", ...)`; update its docstring's `RACECAST_COCKPIT_FUNNEL` mention to `RACECAST_FUNNEL`.

- [ ] **Step 9: Rename the env key in `.env.example`**

In `.env.example`, change the key on (~line 48) `RACECAST_COCKPIT_FUNNEL=false` → `RACECAST_FUNNEL=false`, and update the surrounding comment block (~line 44-47) so it reads (preserve the existing comment style/width):

```
# OPTIONAL: bring the public Funnel up automatically on `racecast event start`.
# When true, event start exposes ONLY /console (the role-adaptive crew launcher)
# on https://<your-magicdns-host>/console. Off by default — the relay stays
# tailnet/loopback-only unless you ask for it. Toggle in the Control Center
# Cockpit view or set here. (Renamed from RACECAST_COCKPIT_FUNNEL.)
RACECAST_FUNNEL=false
```

- [ ] **Step 10: Update the `test_ui_server.py` mock cockpit-link fixture for realism**

In `tests/test_ui_server.py`, change the mock link fixture (~line 180) and its assertions (~line 1152-1153) from `/cockpit?t=x` to `/console?t=x`:

```python
        "funnel": "https://h/console?t=x",
        ...
    assert data["links"][0]["funnel"] == "https://h/console?t=x"
    assert data["links"][0]["internal"] == "http://127.0.0.1:8088/console?t=x"
```

(These are mock fixtures exercising the UI server's pass-through, not the real builder — update fixture and assertion together so they stay consistent.)

- [ ] **Step 11: Run the affected suites to verify they pass**

Run:
```bash
python3 tests/test_racecast.py
python3 tests/test_ui_server.py
python3 tests/test_tailscale.py
```
Expected: PASS for all three.

- [ ] **Step 12: Verify the new command end-to-end at the CLI seam (no Tailscale needed)**

Run: `python3 src/racecast.py funnel`
Expected: prints `usage: racecast funnel {on|off} [--force]` and exits non-zero (validates dispatch wiring without a tailnet).
Run: `python3 src/racecast.py cockpit funnel on`
Expected: errors with the cockpit usage (`funnel` is no longer a cockpit verb).

- [ ] **Step 13: Commit**

```bash
git add src/racecast.py .env.example tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(cli): add top-level \`racecast funnel\`, retire \`cockpit funnel\` (#216)

Replace the cockpit-scoped funnel verb with a canonical \`racecast funnel
on|off\` that mounts /console. Reissued crew links now point at the
/console launcher. Rename the auto-enable flag RACECAST_COCKPIT_FUNNEL ->
RACECAST_FUNNEL (legacy name honored for one release).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Docs (CLI command reference) + full local gate

**Files:**
- Modify: `CLAUDE.md` (command list line ~178; spec mention ~420)
- Modify: `README.md` (command list line ~162)
- Modify: `src/docs/wiki/Commentator-Cockpit.md` (literal command tokens only — see deferral note)

**Interfaces:** none (docs).

- [ ] **Step 1: Update `CLAUDE.md`**

- Line ~178 (the `cockpit funnel on|off` command line): replace with a top-level entry, e.g.:
  `python3 src/racecast.py funnel on|off  # public ingress for ONLY /console (the role-adaptive crew launcher) via Tailscale Funnel (needs MagicDNS+HTTPS+funnel nodeAttr)`
  Remove `funnel on|off` from the `cockpit …` line if it is enumerated there.
- Line ~420 (architecture/spec section): change `PUBLIC exposure is the **independent Funnel switch** (\`cockpit funnel on\`)` → `PUBLIC exposure is the **independent Funnel switch** (\`racecast funnel on\`), which mounts **only** \`/console\``. Also update the nearby sentence that says Funnel "maps **only** the \`/cockpit\` path prefix" to say it maps **only** the `/console` path prefix (the migration). Leave the `/cockpit/*` *namespace* descriptions (the relay's tailnet handlers) intact — only the **public Funnel mount path** changed.

- [ ] **Step 2: Update `README.md`**

- Line ~162: replace `racecast cockpit funnel on|off  # public ingress for ONLY /cockpit via Tailscale Funnel` with `racecast funnel on|off  # public ingress for ONLY /console (crew launcher) via Tailscale Funnel`.

- [ ] **Step 3: Update the literal command in `src/docs/wiki/Commentator-Cockpit.md`**

Replace every literal `racecast cockpit funnel` → `racecast funnel` in that file (lines ~61, 67, 131, 132, 135). Do NOT rewrite the surrounding narrative and do NOT touch the embedded `cc-cockpit.png` — the prose + screenshot reshape is deferred to Phase 5 (see the deferral note). Only fix the command token so the documented command exists. Where a line says `publish ONLY /cockpit on https://<magicdns-host>`, change `/cockpit` → `/console` on that single command-description line for accuracy.

- [ ] **Step 4: Run the full local gate (the CI mirror)**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: `ALL TEST FILES PASS`; `All checks passed!`; build exits 0.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md src/docs/wiki/Commentator-Cockpit.md
git commit -m "docs(funnel): point command reference at \`racecast funnel\` /console (#216)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (controller, before dispatch)

- **Spec coverage:** Phase-4 spec line = "generalize tailscale.funnel*, `racecast funnel` CLI, boundary test. The migration; reissue links." → Task 1 (generalize + boundary test), Task 2 (CLI + reissue links + env), Task 3 (docs). ✓
- **Boundary test** present (Task 1 Step 1, `t_funnel_args_mounts_only_console`). ✓
- **No relay changes** (Phase 3b already serves `/console/*`). ✓
- **No `tools/`/`.github/` callers of the removed verb or env** (grepped clean). ✓
- **Deferrals** (CC card text, `cc-cockpit.png`, link CLI generalization, wiki narrative) explicitly tracked for Phase 5. ✓
- **Legacy env fallback** prevents silent event-day breakage. ✓
