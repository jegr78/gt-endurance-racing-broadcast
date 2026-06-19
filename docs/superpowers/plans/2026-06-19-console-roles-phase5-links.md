# Phase 5 — Link CLI generalization + Control Center surfacing (#216) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `racecast cockpit links` with a top-level `racecast links` that enumerates **people = Crew tab ∪ live Schedule roster** and mints ONE `/console?t=<token>` launcher link per person; expose the Crew roster to CLI/Control-Center code via a new tailnet-only `/crew/data` relay endpoint; and rename the Control Center cockpit view to **"Crew Console"**, surfacing per-person `/console` links (commentators + directors + producers) with corrected help text + a refreshed screenshot.

**Architecture:** The relay already instantiates `CrewSource` (Phase 1, `--crew-tab`) for server-side role resolution but exposes no HTTP view of it. We add a small `GET /crew/data` endpoint (mirrors `/schedule/data`) so CLI code — which is a thin relay client (`_cockpit_roster()` reads `/schedule/data` over loopback) — can read the crew roster the same way. `/crew/data` is a ROOT path, so it is **never funnelled** (only `/console` is mounted publicly); it stays tailnet/loopback-only like `/schedule/data`. The new `links_cmd` unions the schedule roster with the crew roster, deduped by `cpa.streamer_key` (which is behaviorally pinned to the relay's `asset_key`, so a crew-only director's minted token resolves their role through `resolve_roles`). The Control Center rename is visible-label-only; internal `data-view="cockpit"` ids and `/api/cockpit/*` endpoint names stay (minimizing churn).

**Tech Stack:** Python 3.11+ stdlib only. Tests are runnable `tests/test_*.py` scripts (no pytest); the relay is loaded via `importlib`. `tools/run-tests.py` auto-discovers test files.

## Global Constraints

- **Edit only under `src/`** (plus `tests/`, `docs/`, `CLAUDE.md`, `README.md`, and the wiki image). Never hand-edit `dist/`/`runtime/`.
- **English only**; **stdlib only** (the relay must not gain non-stdlib imports); **no machine paths / real IPs / secrets** in committed files (Tailscale test IPs = `100.64.0.0/10` only).
- **Cross-platform:** the matrix includes Windows; build fixed-OS absolute paths with explicit forward slashes, never `os.path.join`.
- **Security boundary unchanged:** `/crew/data` is a ROOT path and MUST stay out of the Funnel mount (only `/console` is mounted). It exposes crew names + role flags unauthenticated on the tailnet — exactly the trust model of `/schedule/data` (which already exposes streamer names + URLs). Do NOT add it under `/console` or `/cockpit`.
- **Token subject correctness:** mint link tokens with `cpa.streamer_key(name)` and dedupe people by that same key — it is pinned equal to `asset_key`, which `resolve_roles` uses. Do not introduce a second normalizer.
- **User-locked decisions:** (1) new top-level `racecast links`; the old `cockpit links` verb is **removed** (no alias). (2) Control Center view renamed **"Crew Console"** (visible label only), help text fixed `/cockpit`→`/console`, per-person `/console` links rendered, `cc-cockpit.png` refreshed.
- **Wiki-screenshot rule (CLAUDE.md):** the Control Center change makes `src/docs/wiki/images/cc-cockpit.png` stale; it MUST be regenerated from a **local dev build** (run `racecast ui` from `src/`, no `VERSION` stamped — so the badge reads "dev build") and committed in THIS branch. This is a controller-executed step (Playwright element screenshot of the Crew Console card), not delegated.
- **Conventional-commit PR title** (`feat(cli): …`); commit bodies end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

### Deferred to later phases (do NOT do here)

- **Crew EDITOR** in the Control Center (reading/writing the Crew tab via the `SHEET_PUSH_URL` webhook `crew` action) → **Phase 6** (spec §G). Phase 5 only READS the crew roster (via `/crew/data`) and surfaces links; it does NOT add crew-editing UI or a webhook `crew` write.
- **Producer takeover over Funnel** → **Phase 7** (spec §H).

---

## File Structure

- `src/relay/racecast-feeds.py` — add `GET /crew/data` (Task 1).
- `tests/test_roles.py` — add a live-HTTP test for `/crew/data` (Task 1).
- `src/racecast.py` — `_crew_roster()`/`_crew_roster_safe()`; new `links_cmd` + route/main wiring; remove `links` from `COCKPIT_VERBS`/`cockpit_cmd`; `cockpit_status_data` crew union (Tasks 2 & 3).
- `tests/test_racecast.py` — route tests + `links_cmd` roster-union unit test (Task 2).
- `tests/test_ui_server.py` — `cockpit_status_data` crew-union fixture (Task 3).
- `src/ui/control-center.html` — "Crew Console" rename + help-text + link-section labels (Task 3).
- `src/docs/wiki/images/cc-cockpit.png` — refreshed screenshot (Task 3, controller step).
- `CLAUDE.md`, `README.md`, `src/docs/wiki/Commentator-Cockpit.md` — command + behavior docs (Task 4).

---

### Task 1: Relay `GET /crew/data` endpoint (tailnet-only crew roster view)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add a route next to `/schedule/data`, ~line 3225; the handler already closes over `crew_source`, used at ~line 2927)
- Test: `tests/test_roles.py` (add a live-HTTP test mirroring `tests/test_submissions.py`'s `_client` harness)

**Interfaces:**
- Consumes: the existing `crew_source` closure variable in the handler (a `CrewSource` or `None`); `CrewSource.get()` returns `[(name, is_director, is_producer), …]`.
- Produces: `GET /crew/data` → `{"rows": [{"name": str, "director": bool, "producer": bool}, …]}`; `{"rows": []}` when `crew_source` is `None` (crew disabled / `--sheet-csv-url`).

- [ ] **Step 1: Write the failing live-HTTP test**

In `tests/test_roles.py`, add a small server harness (adapt it from `tests/test_submissions.py` `_client`, lines ~204-272 — read that for the exact `make_handler` + `ThreadingHTTPServer` pattern) and a test. The relay module is already imported as `m` at the top of `test_roles.py`. Add:

```python
# ---- live HTTP surface: /crew/data ------------------------------------------

def _crew_client(crew_rows):
    """make_handler over a real loopback server, wired with a fake crew_source
    (or None). Returns (server, get)."""
    import threading as _t, json as _json
    from urllib.request import urlopen

    class _Feed:
        def __init__(self, idx): self.idx = idx

    class _Source:
        def get_rows(self): return []
        def health(self): return {"count": 0}

    class _Relay:
        def __init__(self):
            self.source = _Source(); self.mode = "race"
            self.feeds = {"A": _Feed(0), "B": _Feed(1)}

    class _Crew:
        def __init__(self, rows): self._rows = rows
        def get(self): return list(self._rows)

    crew = _Crew(crew_rows) if crew_rows is not None else None
    handler = m.make_handler(_Relay(), crew_source=crew)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path):
        with urlopen(base + path, timeout=5) as r:
            return r.status, _json.loads(r.read().decode())
    return srv, get


def t_crew_data_endpoint_returns_rows():
    srv, get = _crew_client([("Alice", True, True), ("Bob", True, False)])
    try:
        status, body = get("/crew/data")
        assert status == 200, status
        assert body == {"rows": [
            {"name": "Alice", "director": True, "producer": True},
            {"name": "Bob", "director": True, "producer": False}]}, body
    finally:
        srv.shutdown()


def t_crew_data_endpoint_empty_when_disabled():
    srv, get = _crew_client(None)   # no crew_source -> crew disabled
    try:
        status, body = get("/crew/data")
        assert status == 200, status
        assert body == {"rows": []}, body
    finally:
        srv.shutdown()
```

> Note: confirm the real `make_handler` signature accepts `crew_source=` as a keyword (the map shows it does, ~line 2782). If `make_handler` requires other positional args, supply the minimal ones the `_client` in `test_submissions.py` uses. Keep the fake `_Relay` minimal — `/crew/data` only needs `crew_source`, not the schedule.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL — `/crew/data` 404s (no route yet).

- [ ] **Step 3: Add the `/crew/data` route**

In `src/relay/racecast-feeds.py`, immediately AFTER the `/schedule/data` block (~line 3232) and BEFORE `/qualifying/data`, add:

```python
                if p == ["crew", "data"]:
                    # Tailnet-only crew roster view (#216 phase 5). A ROOT path —
                    # NOT under the funnelled /console prefix, so the public
                    # ingress never reaches it (same trust model as
                    # /schedule/data). Lets the `racecast links` CLI enumerate
                    # Crew ∪ Schedule over loopback. Empty when crew is disabled.
                    rows = crew_source.get() if crew_source else []
                    return self._send({"rows": [
                        {"name": n, "director": bool(d), "producer": bool(pr)}
                        for (n, d, pr) in rows]})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_roles.py`
Expected: PASS (all, including the two new tests).

- [ ] **Step 5: Relay sanity — run the relay unit checks**

Run: `python3 tests/test_pov.py`
Expected: PASS (no regression in the relay's core paths).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_roles.py
git commit -m "feat(relay): add tailnet-only GET /crew/data roster endpoint (#216)

Expose the CrewSource roster as JSON (mirrors /schedule/data) so CLI code
can enumerate Crew ∪ Schedule. A root path — never funnelled (only
/console is mounted); empty when crew is disabled.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: New `racecast links` command (Crew ∪ Schedule), remove `cockpit links`

**Files:**
- Modify: `src/racecast.py` (`route`, `main`, new `links_cmd`, new `_crew_roster`/`_crew_roster_safe`, `COCKPIT_VERBS`, `cockpit_cmd`)
- Test: `tests/test_racecast.py` (`t_route_cockpit`, new `t_route_links`, new `t_links_roster_union`)

**Interfaces:**
- Consumes: `/crew/data` from Task 1; existing `_cockpit_roster()`, `_ensure_active_cockpit_secret()`, `_tailscale_ip()`, `_tailscale_magicdns()`, `_post_chat_message()`, `_apply_active_profile_env()`, `cpa.streamer_key`, `cpa.mint_token`, `cpadm.load_versions`, `cpadm.current_version`, `_cockpit_versions_path()`, `RELAY_PORT`.
- Produces:
  - `_crew_roster()` → list of crew names from `/crew/data` (raises on unreachable relay, like `_cockpit_roster`).
  - `_crew_roster_safe()` → `[]` on any failure (for the Control Center).
  - `_links_roster()` → ordered, deduped union of schedule + crew names (schedule first).
  - `links_cmd(rest)` — handles `racecast links [--post]`.
  - `route(["links"]) == {"kind": "links", "rest": []}`.
  - `COCKPIT_VERBS == ("setup-funnel", "token", "pull-versions")`.

- [ ] **Step 1: Write the failing route + roster-union tests**

In `tests/test_racecast.py`: edit `t_route_cockpit` to drop the `["cockpit","links"]` success assertion and assert it is now rejected; add `t_route_links` and `t_links_roster_union`:

```python
def t_route_links():
    assert m.route(["links"]) == {"kind": "links", "rest": []}
    assert m.route(["links", "--post"]) == {"kind": "links", "rest": ["--post"]}


def t_links_roster_union():
    # People = Schedule ∪ Crew, deduped by streamer_key (== asset_key), schedule
    # first. A crew-only director joins the list; a person in both appears once.
    orig_sched = m._cockpit_roster
    orig_crew = m._crew_roster
    try:
        m._cockpit_roster = lambda: ["Alice", "Bob"]          # schedule (streamers)
        m._crew_roster = lambda: ["Bob", "Dana the Director"]  # crew tab
        assert m._links_roster() == ["Alice", "Bob", "Dana the Director"]
    finally:
        m._cockpit_roster = orig_sched
        m._crew_roster = orig_crew
```

(Update the existing `t_route_cockpit` `bad` loop to include `["cockpit", "links"]`.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); sys.path.insert(0,'src'); import test_racecast as t; t.t_route_links()"`
Expected: FAIL — `route` raises `unknown command: links`.

- [ ] **Step 3: Add `_crew_roster`, `_crew_roster_safe`, `_links_roster`**

In `src/racecast.py`, near `_cockpit_roster` (~line 1070), add:

```python
def _crew_roster():
    """Distinct crew names (Director/Producer) from the running relay's
    /crew/data (first-seen order). Raises on an unreachable relay — mirrors
    _cockpit_roster. Empty list when the league has no Crew tab."""
    data = _relay_fetch_json(f"http://127.0.0.1:{RELAY_PORT}/crew/data")
    seen, roster = set(), []
    for row in (data or {}).get("rows", []):
        name = (row.get("name") or "").strip()
        key = cpa.streamer_key(name)
        if key and key not in seen:
            seen.add(key)
            roster.append(name)
    return roster


def _crew_roster_safe():
    """_crew_roster() that returns [] instead of raising (Control Center poll)."""
    try:
        return _crew_roster()
    except Exception:
        return []


def _links_roster():
    """People to mint console links for = live Schedule roster ∪ Crew tab,
    deduped by streamer_key (pinned == asset_key, the key resolve_roles uses),
    schedule first so commentators keep their existing order. Raises if the
    schedule is unreadable (relay down); crew is best-effort."""
    roster = list(_cockpit_roster())            # may raise if relay is down
    seen = {cpa.streamer_key(n) for n in roster}
    for name in _crew_roster_safe():
        key = cpa.streamer_key(name)
        if key and key not in seen:
            seen.add(key)
            roster.append(name)
    return roster
```

> Confirm `_relay_fetch_json` exists and is what `_cockpit_roster` uses (the map shows `_cockpit_roster` reads `/schedule/data`; reuse the same fetch helper — grep its exact name in `_cockpit_roster` and match it).

- [ ] **Step 4: Add `links_cmd` and remove the cockpit `links` verb**

Add a new `links_cmd` (adapt the body of the old `cockpit links` handler, but iterate `_links_roster()` and speak as a top-level command):

```python
def links_cmd(rest):
    """`racecast links [--post]` — print one /console launcher link per person
    (Crew tab ∪ live Schedule). Each link carries a signed identity token; the
    relay resolves the person's roles server-side, so one link adapts to
    commentator/director/producer. --post drops them into crew chat. (#216)"""
    _apply_active_profile_env()
    secret = _ensure_active_cockpit_secret()
    if not secret:
        sys.exit("racecast: no active league profile — create or select one first.")
    try:
        roster = _links_roster()
    except Exception:
        sys.exit("racecast: could not read the schedule (is the relay running?).")
    if not roster:
        sys.exit("racecast: no crew or streamers found (is the relay running?).")
    host = _tailscale_ip() or "<tailscale-ip>"
    magic = _tailscale_magicdns() or "<your-magicdns-host>"
    versions = cpadm.load_versions(_cockpit_versions_path())
    post = "--post" in rest
    lines = []
    for name in roster:
        key = cpa.streamer_key(name)
        tok = cpa.mint_token(secret, key, cpadm.current_version(versions, key))
        url = f"https://{magic}/console?t={tok}"                # Funnel host
        lan = f"http://{host}:{RELAY_PORT}/console?t={tok}"      # tailnet fallback
        print(f"{name}:\n  funnel:  {url}\n  tailnet: {lan}")
        lines.append(f"{name}: {url}")
    if post:
        try:
            _post_chat_message("Console links:\n" + "\n".join(lines))
            print("posted links into crew chat.")
        except Exception:
            print("note: could not post to crew chat (relay not running?).")
    return None
```

- In `route()` (after the `funnel` block, ~line 871), add:
  ```python
      if cmd == "links":
          return {"kind": "links", "rest": rest}
  ```
- In `main()` (next to the `funnel` dispatch), add:
  ```python
      if action["kind"] == "links":
          return links_cmd(action["rest"])
  ```
- `COCKPIT_VERBS` (~line 1042): change to `("setup-funnel", "token", "pull-versions")`.
- In `cockpit_cmd`, DELETE the entire `if verb == "links": …` block (the old handler, ~lines 1213-1242). Update the `cockpit_cmd` docstring to drop `links`.

- [ ] **Step 5: Run the affected suite + CLI smoke**

Run: `python3 tests/test_racecast.py`
Expected: PASS.
Run: `python3 src/racecast.py cockpit links`
Expected: rejected — `links` is no longer a cockpit verb (cockpit usage error).
Run: `python3 src/racecast.py links`
Expected: errors with `no active league profile …` OR `could not read the schedule …` (depending on env) — i.e. the command DISPATCHES (not "unknown command").

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(cli): add \`racecast links\` (Crew ∪ Schedule), retire \`cockpit links\` (#216)

One /console launcher link per person across the Crew tab and the live
Schedule, deduped by streamer_key. The relay resolves roles server-side,
so a single link adapts per role. Replaces the commentator-only
\`cockpit links\`.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Control Center "Crew Console" rename + crew-union links

**Files:**
- Modify: `src/racecast.py` (`cockpit_status_data` — union crew into `links`)
- Modify: `src/ui/control-center.html` (visible labels: nav button, heading, help text, link-section title)
- Test: `tests/test_ui_server.py` (crew-union fixture for the status payload)
- Refresh: `src/docs/wiki/images/cc-cockpit.png` (controller step — see Step 6)

**Interfaces:**
- Consumes: `_crew_roster_safe()` from Task 2; existing `_cockpit_roster_safe()`.
- Produces: `cockpit_status_data()["links"]` now spans Schedule ∪ Crew (deduped), unchanged dict shape `{"name", "internal", "funnel"}`.

- [ ] **Step 1: Write the failing data-layer test**

In `tests/test_ui_server.py`, add (or extend the existing `cockpit_status_data` test) a check that the link list unions crew. Since `cockpit_status_data` calls `_cockpit_roster_safe` + `_crew_roster_safe` + mints tokens, monkeypatch those at the `racecast` module. Add to `tests/test_racecast.py` instead if that is where `cockpit_status_data` is unit-tested — pick the file that already imports the `racecast` module as `m` and tests `cockpit_status_data`. Minimal test:

```python
def t_cockpit_status_links_union_crew():
    import m_or_racecast as _  # use the module alias already in this test file
    orig_sched = m._cockpit_roster_safe
    orig_crew = m._crew_roster_safe
    orig_secret = m._ensure_active_cockpit_secret
    try:
        m._cockpit_roster_safe = lambda: ["Alice"]
        m._crew_roster_safe = lambda: ["Dana the Director"]
        m._ensure_active_cockpit_secret = lambda: "s" * 64
        data = m.cockpit_status_data()
        names = [l["name"] for l in data["links"]]
        assert names == ["Alice", "Dana the Director"], names
        assert all("/console?t=" in l["internal"] for l in data["links"])
    finally:
        m._cockpit_roster_safe = orig_sched
        m._crew_roster_safe = orig_crew
        m._ensure_active_cockpit_secret = orig_secret
```

> Adjust the import line to the test file's existing module alias (`m`). Place the test in whichever file already exercises `cockpit_status_data` (grep `cockpit_status_data` under `tests/`); if none does, add it to `tests/test_racecast.py`.

- [ ] **Step 2: Run to verify failure**

Run the new test; Expected: FAIL — `cockpit_status_data` currently lists only the schedule roster (`["Alice"]`), not the crew union.

- [ ] **Step 3: Union crew into `cockpit_status_data`**

In `src/racecast.py`, in `cockpit_status_data` (~line 3367), replace the roster loop so it iterates the deduped union. Change:

```python
            for name in _cockpit_roster_safe():
```

to a union identical in spirit to `_links_roster` but built from the *safe* variants (the Control Center must never raise):

```python
            seen_keys = set()
            roster = []
            for name in list(_cockpit_roster_safe()) + list(_crew_roster_safe()):
                key = cpa.streamer_key(name)
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    roster.append(name)
            for name in roster:
```

(Leave the token-minting + link-dict body inside the loop unchanged.)

- [ ] **Step 4: Run the data test + ui server suite**

Run: `python3 tests/test_ui_server.py` and the file holding the new test.
Expected: PASS.

- [ ] **Step 5: Rename the Control Center view to "Crew Console" (visible labels only)**

In `src/ui/control-center.html` (keep `data-nav="cockpit"`, `data-view="cockpit"`, `showView('cockpit')`, and the `#cp-*` ids — internal, unchanged):

- Nav button text (~line 439): `Cockpit` → `Crew Console`.
- View heading (~line 870): `<h2>Commentator Cockpit</h2>` → `<h2>Crew Console</h2>`; the sub (~line 871) `talent-facing program monitor, tally, chat & timer` → `role-adaptive crew links — commentator, director & producer`.
- Intro `<p class="sub">` (~lines 876-879): reword so it is accurate for /console, e.g.: `Zero-config: the relay serves the role-adaptive <code>/console</code> launcher automatically — a per-league secret is generated on first relay start. Every request is token-gated (links below). It is exposed <b>publicly</b> only when you also turn the Funnel on.`
- Funnel help `<p class="sub">` (~lines 889-890): `Exposes only <code>/cockpit</code> publicly.` → `Exposes only <code>/console</code> publicly.`
- Link-section heading (~the `<h3>Commentator links</h3>`): → `<h3>Crew links</h3>`. In its description, `<b>Funnel link</b> …` text may stay; if it says "commentator", generalize to "crew".
- The `Copy funnel link` / `Copy internal link` / `Revoke` button labels in the JS (`loadCockpit`) stay as-is (per-row, role-agnostic).

- [ ] **Step 6: (CONTROLLER STEP — not delegated) Refresh `cc-cockpit.png`**

The controller regenerates the screenshot from a LOCAL DEV BUILD (no `VERSION` file, so the badge reads "dev build", matching every other `cc-*.png`):
1. Run `python3 src/racecast.py ui` from the repo (dev build).
2. Drive the running Control Center with the Playwright MCP: open the UI, `showView('cockpit')` (now "Crew Console"), and take an **element** screenshot of the view card (the `[data-view="cockpit"]` section) so framing matches the existing image.
3. Save to `src/docs/wiki/images/cc-cockpit.png` (overwrite). Verify it shows the "Crew Console" heading + the `/console` help text.
4. Stage it for the Task-3 commit.

- [ ] **Step 7: Commit (code + screenshot together — CLAUDE.md same-change rule)**

```bash
git add src/racecast.py src/ui/control-center.html tests/test_ui_server.py \
        tests/test_racecast.py src/docs/wiki/images/cc-cockpit.png
git commit -m "feat(ui): rename Control Center cockpit view to Crew Console (#216)

Surface role-adaptive /console links across Crew ∪ Schedule, correct the
/cockpit→/console help text, and refresh cc-cockpit.png. Internal ids and
/api/cockpit/* endpoints unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Docs + full local gate

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `src/docs/wiki/Commentator-Cockpit.md`

- [ ] **Step 1: Update `CLAUDE.md`**

- The cockpit command list (~lines 175-177): replace the `cockpit links` line with a top-level `racecast links` entry, e.g.: `python3 src/racecast.py links  # print per-person /console launcher links (Crew tab ∪ live Schedule); --post drops them into crew chat`.
- In the architecture/cockpit section (~lines 406-425): add one sentence that the crew roster is exposed via the tailnet-only `GET /crew/data` (root path, never funnelled) and that `racecast links` unions Crew ∪ Schedule. Mention the Control Center view is now "Crew Console".

- [ ] **Step 2: Update `README.md`**

- Replace any `racecast cockpit links` reference with `racecast links` + the Crew∪Schedule description.

- [ ] **Step 3: Update `src/docs/wiki/Commentator-Cockpit.md`**

- Replace `racecast cockpit links` → `racecast links` (the command example, ~lines 52-58). Update the surrounding line to say it prints one role-adaptive `/console` link per person (Crew ∪ Schedule), not "every commentator". The embedded `cc-cockpit.png` was refreshed in Task 3.

- [ ] **Step 4: Full local gate (CI mirror)**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: `ALL TEST FILES PASS`; `All checks passed!`; build exit 0.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md src/docs/wiki/Commentator-Cockpit.md
git commit -m "docs(links): document \`racecast links\` + /crew/data + Crew Console (#216)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (controller, before dispatch)

- **Spec coverage:** Phase-5 spec = "Link CLI generalization + Control Center surfacing" (§F + surfacing). → Task 1 (crew roster access), Task 2 (generalized `racecast links`, Crew∪Schedule, remove old), Task 3 (Crew Console rename + crew-union links + screenshot), Task 4 (docs). ✓
- **Crew editor / takeover** correctly deferred to Phases 6/7. ✓
- **Boundary:** `/crew/data` is a root path, explicitly NOT funnelled — comment + constraint state it; the Funnel mount set (Phase 4) is unchanged. ✓
- **Token correctness:** dedupe + mint by `cpa.streamer_key` (pinned == `asset_key`); a crew-only director's token resolves via `resolve_roles`. ✓
- **Screenshot rule:** `cc-cockpit.png` refreshed in the same branch (Task 3, controller step), from a dev build. ✓
- **No new non-stdlib relay import.** ✓
- **Type consistency:** `_crew_roster`/`_crew_roster_safe`/`_links_roster` names used consistently across Tasks 2-3 and the tests. ✓
