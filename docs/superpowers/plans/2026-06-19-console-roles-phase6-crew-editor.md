# Phase 6 — Crew editor in Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Crew-roster editor to the Control Center Profile view that reads the
Sheet `Crew` tab (via the running relay) and writes single rows back through the
existing `SHEET_PUSH_URL` webhook with a new **`crew`** action, mirroring the existing
`schedule` write action — plus the Apps Script / Sheet coordination docs.

**Architecture:** Three hops, exactly like the schedule editor. (1) **Relay**: a new
`SetupControl.crew_set/crew_delete` builds a `{"action":"crew",...}` webhook payload,
POSTs it via the existing `post_webhook`/`check_webhook_response`, and optimistically
echoes into `CrewSource` so `/crew/data` reflects the edit before the next poll. New
relay POST routes `/crew/set` + `/crew/delete`. (2) **`racecast.py` data layer**:
`crew_entries_data` reads the relay's `/crew/data`; `crew_write_data`/`crew_delete_data`
POST to the relay's new routes (the relay stays the trust boundary that holds the
webhook URL). (3) **Control Center**: a Crew section in the Profile view + `/api/crew`
routes. Per-row writes (the user-chosen granularity); delete is a separate action.

**Tech Stack:** Pure Python stdlib (relay + CLI), vanilla HTML/JS (Control Center),
runnable-script tests (no pytest), Google Apps Script (Sheet-side, documented only).

## Global Constraints

- **Edit only under `src/`** (and `docs/`, `tests/`). `dist/`/`runtime/` are generated.
- **All scripts and docs English only.**
- **Never hardcode secrets or machine paths / real IPs.** Tailscale test IPs are
  `100.64.0.0/10` only. Crew names in tests/screenshots are synthetic.
- **Relay stays stdlib-only** — no new deps in `src/relay/racecast-feeds.py`.
- **The webhook stays relay-held.** The Control Center never POSTs to `SHEET_PUSH_URL`
  directly — it talks to the running relay over loopback, like the schedule editor.
- **Per-row writes, mirroring the `schedule` action** (decided 2026-06-19). Delete is a
  separate logical operation carried by the same `action:"crew"` with `delete:true`.
- **`crew` name is free text** (crew may be director/producer-only people, not in the
  Configuration streamer vocabulary) — do NOT vocab-constrain it. Only `name` non-empty
  + `row >= 1` are validated.
- **Graceful degradation:** a missing `Crew` tab / outdated Apps Script must surface a
  clear error, never crash — same as the schedule path (`check_webhook_response` already
  reports a v1/timer-only script).
- **Wiki screenshot in the same change:** the Profile view gains a visible section →
  `src/docs/wiki/images/cc-profile.png` MUST be refreshed (dev build, no VERSION,
  synthetic crew rows). Per CLAUDE.md this is mandatory, not a follow-up.
- Local gate green before each PR: `python3 tools/run-tests.py`, `python3 tools/lint.py`,
  `python3 tools/build.py` (exit 0). Relay change ⇒ also `python3 tests/test_pov.py`.

---

### Task 1: Relay crew write path (`SetupControl.crew_set/crew_delete` + `CrewSource` echo + routes)

**Files:**
- Modify: `src/relay/racecast-feeds.py`
  - `CrewSource` (class at ~line 1764): add `inject_row` + `delete_row`.
  - `SetupControl.__init__` (~line 2030): add `crew_source=None` param + store.
  - `SetupControl` (after `qualifying_set`, ~line 2120): add `crew_set`, `crew_delete`,
    `_crew_rownum`.
  - `do_POST` routing (after the `qualifying/set` block, ~line 3431): add `crew/set` +
    `crew/delete`.
  - `SetupControl(...)` construction (~line 3769): pass `crew_source=crew_source`
    (`crew_source` is already defined at ~line 3657, before this call).
- Test: `tests/test_setup.py` (crew_set/crew_delete payloads + validation + echo),
  `tests/test_roles.py` (`CrewSource.inject_row` / `delete_row`).

**Interfaces:**
- Consumes: existing `post_webhook`, `check_webhook_response`, `SetupControl._push`,
  `CrewSource` (rows are `(name, is_director, is_producer)` 3-tuples), the `crew_source`
  local in `run()`.
- Produces: relay endpoints `POST /crew/set {row,name,director,producer}` and
  `POST /crew/delete {row}`, each returning `{"ok":true,"row":N}` or `{"error":...}`;
  webhook payloads `{"action":"crew","row":N,"name":..,"director":bool,"producer":bool}`
  and `{"action":"crew","row":N,"delete":true}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_setup.py` (append; reuse the
  existing `_ctl(pushes)` harness that monkeypatches `m.post_webhook`):

```python
def t_crew_set_validates_and_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.crew_set("x", name="Dana")        # non-numeric row
        assert "error" in ctl.crew_set(0, name="Dana")          # row < 1
        assert "error" in ctl.crew_set(2, name="")              # empty name
        assert pushes == []                                     # all rejected pre-push
        r = ctl.crew_set(2, name="Dana", director=True, producer=False)
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "crew", "row": 2, "name": "Dana",
                              "director": True, "producer": False}
    finally:
        m.post_webhook = orig


def t_crew_set_coerces_flags_and_strips_name():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.crew_set(3, name="  Pia  ", director=0, producer="x")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "crew", "row": 3, "name": "Pia",
                              "director": False, "producer": True}
    finally:
        m.post_webhook = orig


def t_crew_delete_pushes_delete_flag():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.crew_delete(0)
        r = ctl.crew_delete(2)
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "crew", "row": 2, "delete": True}
    finally:
        m.post_webhook = orig


def t_crew_requires_webhook():
    ctl = m.SetupControl(None, _hs_stub())
    assert "error" in ctl.crew_set(1, name="Dana")
    assert "error" in ctl.crew_delete(1)


def t_crew_set_reflects_in_crew_source():
    # End-to-end echo: a successful write updates the in-memory CrewSource so
    # /crew/data shows it before the next poll (name/flags), like schedule.
    pushes = []
    hs = _hs_stub()
    cs = m.CrewSource("http://crew")
    cs.rows = [("Alice", True, False)]                 # 1 existing data row
    ctl = m.SetupControl("http://push", hs, crew_source=cs)
    def fake_post(url, payload, timeout=10):
        pushes.append(payload)
        return b'{"ok": true, "action": "crew", "v": 5}'
    m.post_webhook, orig = fake_post, m.post_webhook
    try:
        assert ctl.crew_set(2, name="Bob", director=False, producer=True).get("ok")
        assert cs.get() == [("Alice", True, False), ("Bob", False, True)]  # appended
        assert ctl.crew_set(1, name="Alice", director=False, producer=False).get("ok")
        assert cs.get()[0] == ("Alice", False, False)                     # edited in place
        assert ctl.crew_delete(2).get("ok")
        assert cs.get() == [("Alice", False, False)]                      # deleted
    finally:
        m.post_webhook = orig
```

And in `tests/test_roles.py` (append; `m` is the relay module loaded there):

```python
def t_crew_source_inject_row_edit_append_and_delete():
    cs = m.CrewSource("http://crew")
    cs.rows = [("Alice", True, False)]
    cs.inject_row(2, name="Bob", director=False, producer=True)   # append at len+1
    assert cs.get() == [("Alice", True, False), ("Bob", False, True)]
    cs.inject_row(1, director=False)                              # partial edit in place
    assert cs.get()[0] == ("Alice", False, False)
    cs.delete_row(1)
    assert cs.get() == [("Bob", False, True)]
    cs.delete_row(9)                                             # out of range = no-op
    assert cs.get() == [("Bob", False, True)]
```

- [ ] **Step 2: Run them — verify they fail**

Run: `python3 tests/test_setup.py` and `python3 tests/test_roles.py`
Expected: FAIL — `AttributeError: 'SetupControl' object has no attribute 'crew_set'`
(and `CrewSource` has no `inject_row`).

- [ ] **Step 3: Add `CrewSource.inject_row` + `delete_row`** (inside `class CrewSource`,
  e.g. right after `refresh`):

```python
    def inject_row(self, row, name=None, director=None, producer=None):
        """Optimistically merge a Control-Center crew write into the in-memory
        roster so /crew/data reflects it before the next sheet poll. `row` is the
        1-based data-row index (header excluded); row == len+1 appends a row whose
        name is non-empty. Each of name/director/producer is applied when given and
        LEFT UNCHANGED when None. The next CSV poll reconciles against the sheet."""
        with self.lock:
            rows = list(self.rows)
            i = int(row) - 1
            cur_n, cur_d, cur_p = rows[i] if 0 <= i < len(rows) else ("", False, False)
            entry = (cur_n if name is None else (name or "").strip(),
                     cur_d if director is None else bool(director),
                     cur_p if producer is None else bool(producer))
            if 0 <= i < len(rows):
                rows[i] = entry
            elif i == len(rows) and entry[0]:
                rows.append(entry)
            self.rows = rows

    def delete_row(self, row):
        """Drop the 1-based data row from the in-memory roster (optimistic echo of
        a Control-Center crew delete). Out-of-range is a no-op."""
        with self.lock:
            i = int(row) - 1
            if 0 <= i < len(self.rows):
                rows = list(self.rows)
                del rows[i]
                self.rows = rows
```

- [ ] **Step 4: Add `crew_source` to `SetupControl.__init__`** — change the signature and
  store it:

```python
    def __init__(self, push_url, hud_source, schedule_source=None, qual_source=None,
                 pov_source=None, crew_source=None):
        self.push_url = push_url
        self.hud = hud_source
        self.schedule_source = schedule_source
        self.qual_source = qual_source
        self.pov_source = pov_source
        self.crew_source = crew_source
        self.push_status = "disabled" if not push_url else "never"
        self.last_error = None
```

- [ ] **Step 5: Add `crew_set`, `crew_delete`, `_crew_rownum`** (after `qualifying_set`):

```python
    # -- crew roster writes (Crew tab: Name | Director | Producer) -------------
    def crew_set(self, row, name=None, director=None, producer=None):
        """Write one Crew tab row via the webhook (per-row, mirrors schedule).
        `name` is free text (crew may be director/producer-only people, not in
        the streamer vocabulary); director/producer are coerced to booleans."""
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        rownum = self._crew_rownum(row)
        if isinstance(rownum, dict):
            return rownum
        name = (name or "").strip()
        if not name:
            return {"error": "name is required"}
        payload = {"action": "crew", "row": rownum, "name": name,
                   "director": bool(director), "producer": bool(producer)}
        ok, err = self._push(payload, "crew")
        if ok and self.crew_source is not None:
            self.crew_source.inject_row(rownum, name, bool(director), bool(producer))
        return {"ok": True, "row": rownum} if ok else {"error": err}

    def crew_delete(self, row):
        """Delete one Crew tab row by 1-based index via the webhook."""
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        rownum = self._crew_rownum(row)
        if isinstance(rownum, dict):
            return rownum
        ok, err = self._push({"action": "crew", "row": rownum, "delete": True}, "crew")
        if ok and self.crew_source is not None:
            self.crew_source.delete_row(rownum)
        return {"ok": True, "row": rownum} if ok else {"error": err}

    @staticmethod
    def _crew_rownum(row):
        """A 1-based crew row as int, or an error dict. Mirrors the schedule row
        validation (rejects bool, non-numeric, < 1)."""
        if isinstance(row, bool) or not isinstance(row, (int, str)):
            return {"error": "row must be a whole number (1-based)"}
        try:
            row = int(row)
        except (TypeError, ValueError):
            return {"error": "row must be a number (1-based)"}
        if row < 1:
            return {"error": "row must be >= 1"}
        return row
```

- [ ] **Step 6: Add the relay POST routes** — right after the `qualifying/set` block in
  `do_POST` (which already sits under the `if not setup_ctl: return 404` guard):

```python
                if p == ["crew", "set"]:
                    return self._send(setup_ctl.crew_set(
                        body.get("row"), body.get("name"),
                        body.get("director"), body.get("producer")))
                if p == ["crew", "delete"]:
                    return self._send(setup_ctl.crew_delete(body.get("row")))
```

- [ ] **Step 7: Pass `crew_source` into `SetupControl`** at construction (~line 3769):

```python
    setup_ctl = (SetupControl(push_url, hud_source, schedule_source=source,
                              qual_source=qual_source, pov_source=pov_source,
                              crew_source=crew_source)
                 if hud_source else None)
```

- [ ] **Step 8: Run the tests — verify they pass**

Run: `python3 tests/test_setup.py` and `python3 tests/test_roles.py`
Expected: PASS (both files: `ALL PASS`).

- [ ] **Step 9: Relay regression + lint**

Run: `python3 tests/test_pov.py` (Expected: ALL PASS) and `python3 tools/lint.py`
(Expected: clean).

- [ ] **Step 10: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py tests/test_roles.py
git commit -m "feat(relay): crew-roster webhook writes (crew_set/crew_delete + /crew/* routes)"
```

---

### Task 2: Control Center data layer (`racecast.py` funcs + `ui_server.py` routes)

**Files:**
- Modify: `src/racecast.py` — add `crew_entries_data`, `crew_write_data`,
  `crew_delete_data` (near the other Control-Center data providers, e.g. beside
  `cockpit_status_data`); register them in the `ctx` dict (~line 4720, beside
  `profile_env_read`).
- Modify: `src/ui/ui_server.py` — add `GET /api/crew`, `POST /api/crew`,
  `POST /api/crew/delete`, mirroring the adjacent `/api/profile/env` GET+POST and
  `/api/overlay/layout` POST handlers **exactly** (same `self._json` / body-parse
  helpers, same `ok → 200 else 400` status mapping the existing routes use).
- Test: `tests/test_racecast.py` (the three data funcs against a stubbed relay client),
  `tests/test_ui_server.py` (routes via the `_ctx()` stub).

**Interfaces:**
- Consumes: `_relay_fetch_json`, `_relay_post_json`, `RELAY_PORT` (all in `racecast.py`);
  the relay routes from Task 1.
- Produces: `ctx` keys `"crew_read"` → `{ok, entries:[{name,director,producer}]}`,
  `"crew_write"(row,name,director,producer)`, `"crew_delete"(row)` → relay result dict;
  Control Center endpoints `GET /api/crew`, `POST /api/crew`, `POST /api/crew/delete`.

- [ ] **Step 1: Write the failing data-layer tests** in `tests/test_racecast.py` (append;
  `r` is the imported `racecast` module — match the file's existing import alias):

```python
def t_crew_entries_data_maps_relay_rows():
    seen = {}
    def fake_fetch(url, timeout=3):
        seen["url"] = url
        return {"rows": [{"name": "Dana", "director": True, "producer": False},
                         {"name": "Pia", "director": 0, "producer": "x"}]}
    orig = r._relay_fetch_json
    r._relay_fetch_json = fake_fetch
    try:
        out = r.crew_entries_data()
    finally:
        r._relay_fetch_json = orig
    assert out["ok"] is True, out
    assert out["entries"] == [{"name": "Dana", "director": True, "producer": False},
                              {"name": "Pia", "director": False, "producer": True}]
    assert seen["url"].endswith("/crew/data")


def t_crew_entries_data_relay_down_is_error_not_raise():
    def boom(url, timeout=3):
        raise OSError("connection refused")
    orig = r._relay_fetch_json
    r._relay_fetch_json = boom
    try:
        out = r.crew_entries_data()
    finally:
        r._relay_fetch_json = orig
    assert out["ok"] is False and "error" in out


def t_crew_write_and_delete_post_to_relay():
    posts = []
    def fake_post(url, payload, timeout=3):
        posts.append((url, payload))
        return {"ok": True, "row": payload.get("row")}
    orig = r._relay_post_json
    r._relay_post_json = fake_post
    try:
        w = r.crew_write_data(2, "Dana", True, False)
        d = r.crew_delete_data(3)
    finally:
        r._relay_post_json = orig
    assert w == {"ok": True, "row": 2}
    assert posts[0][0].endswith("/crew/set")
    assert posts[0][1] == {"row": 2, "name": "Dana", "director": True, "producer": False}
    assert d == {"ok": True, "row": 3}
    assert posts[1][0].endswith("/crew/delete") and posts[1][1] == {"row": 3}
```

- [ ] **Step 2: Run — verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute 'crew_entries_data'`.

- [ ] **Step 3: Implement the data funcs** in `src/racecast.py`:

```python
def crew_entries_data():
    """Crew roster for the Control Center, read live from the running relay's
    /crew/data. {ok, entries:[{name,director,producer}]} or {ok:false, error}."""
    try:
        data = _relay_fetch_json("http://127.0.0.1:%d/crew/data" % RELAY_PORT)
    except Exception as exc:
        return {"ok": False,
                "error": "relay not reachable (start the relay): %s" % exc}
    entries = [{"name": row.get("name", ""),
                "director": bool(row.get("director")),
                "producer": bool(row.get("producer"))}
               for row in (data.get("rows") or [])]
    return {"ok": True, "entries": entries}


def crew_write_data(row, name, director, producer):
    """Write one crew row via the relay's /crew/set (the relay holds the webhook
    URL — the Control Center never POSTs to SHEET_PUSH_URL directly)."""
    try:
        return _relay_post_json(
            "http://127.0.0.1:%d/crew/set" % RELAY_PORT,
            {"row": row, "name": name,
             "director": bool(director), "producer": bool(producer)})
    except Exception as exc:
        return {"ok": False,
                "error": "relay not reachable (start the relay): %s" % exc}


def crew_delete_data(row):
    """Delete one crew row via the relay's /crew/delete."""
    try:
        return _relay_post_json("http://127.0.0.1:%d/crew/delete" % RELAY_PORT,
                                {"row": row})
    except Exception as exc:
        return {"ok": False,
                "error": "relay not reachable (start the relay): %s" % exc}
```

- [ ] **Step 4: Register in the `ctx` dict** (beside `"profile_env_read"`):

```python
        "crew_read": crew_entries_data,
        "crew_write": crew_write_data,
        "crew_delete": crew_delete_data,
```

- [ ] **Step 5: Write the failing route tests** in `tests/test_ui_server.py`. Extend the
  `_ctx(...)` stub with crew stubs and add route tests that mirror the existing
  `profile_env` route tests (use the same request helper the file already uses):

```python
# add to the dict returned by _ctx(...):
        "crew_read": lambda: {"ok": True, "entries": [
            {"name": "Dana", "director": True, "producer": False}]},
        "crew_write": lambda row, name, director, producer: {
            "ok": True, "row": row, "_got": (row, name, director, producer)},
        "crew_delete": lambda row: {"ok": True, "row": row, "_got": row},
```

```python
def t_api_crew_get_returns_entries():
    code, body = _get(_ctx(), "/api/crew")          # use the file's GET helper
    assert code == 200
    assert body["entries"][0]["name"] == "Dana"


def t_api_crew_post_writes_row():
    code, body = _post(_ctx(), "/api/crew",          # use the file's POST helper
                       {"row": 2, "name": "Pia", "director": False, "producer": True})
    assert code == 200 and body["ok"] is True
    assert body["_got"] == (2, "Pia", False, True)


def t_api_crew_delete_post():
    code, body = _post(_ctx(), "/api/crew/delete", {"row": 3})
    assert code == 200 and body["_got"] == 3
```

> Note: `_get`/`_post` are placeholders for whatever request helpers `test_ui_server.py`
> already defines — match the existing tests in that file (do not invent new helpers).

- [ ] **Step 6: Run — verify they fail**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the `/api/crew` routes 404 (unknown path).

- [ ] **Step 7: Add the routes in `src/ui/ui_server.py`**, mirroring the adjacent
  `/api/profile/env` (GET + POST) and `/api/overlay/layout` (POST) handlers exactly —
  same body-parse + `self._json` helpers + `ok → 200 else 400` mapping:

```python
# in do_GET dispatch, beside the other /api/* GETs:
        if path == "/api/crew":
            return self._json(ctx["crew_read"]())

# in do_POST dispatch, beside /api/profile/env:
        if path == "/api/crew":
            body = <parse-json-body, same helper the env POST uses>
            res = ctx["crew_write"](body.get("row"), body.get("name"),
                                    body.get("director"), body.get("producer"))
            return self._json(res, <200 if res.get("ok") else 400 — match env POST>)
        if path == "/api/crew/delete":
            body = <parse-json-body>
            res = ctx["crew_delete"](body.get("row"))
            return self._json(res, <200 if res.get("ok") else 400>)
```

- [ ] **Step 8: Run the route + data tests — verify they pass**

Run: `python3 tests/test_ui_server.py` and `python3 tests/test_racecast.py`
Expected: PASS (both `ALL PASS`).

- [ ] **Step 9: Lint**

Run: `python3 tools/lint.py` → clean.

- [ ] **Step 10: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(ui): Control Center crew-editor data layer + /api/crew routes"
```

---

### Task 3: Control Center Crew editor UI + screenshot

**Files:**
- Modify: `src/ui/control-center.html` — add a **Crew** card in the Profile view
  (`data-view="profile"`), after the existing League-config card. A table of crew rows:
  per row a `name` text input, `Director` checkbox, `Producer` checkbox, a **Save**
  button and a **Delete** button; plus an **Add person** button that appends a blank
  row (its 1-based index = current row count + 1). Load via `GET /api/crew`; Save →
  `POST /api/crew {row,name,director,producer}`; Delete → `POST /api/crew/delete {row}`.
  After any successful Save/Delete, reload from `/api/crew` to resync row indices. Show
  a status line; on a not-ok response render `body.error`. **Match the existing Profile
  cards' markup, CSS classes, and the file's `fetch`/status helpers — do not introduce a
  new style.**
- Refresh: `src/docs/wiki/images/cc-profile.png` (controller step — see Step 4).

**Interfaces:**
- Consumes: the `/api/crew` routes from Task 2.
- Produces: no API; the rendered Crew section the screenshot captures.

- [ ] **Step 1: Add the Crew card markup + JS** to `control-center.html`. Mirror an
  existing Profile card for structure; the behavior is:
  - On Profile-view show (or on load), `fetch('/api/crew', {cache:'no-store'})` →
    render one editable table row per entry, 1-based row numbers in display order.
  - **Save** posts `{row, name, director, producer}` to `/api/crew`; **Delete** posts
    `{row}` to `/api/crew/delete`; **Add person** appends a blank row at index
    `count + 1` (editable, Save creates it).
  - After a successful Save/Delete, re-`fetch('/api/crew')` to resync indices.
  - A relay-down / webhook error response (`{ok:false, error}`) shows `error` verbatim
    in the status line (e.g. "relay not reachable (start the relay)") — never a silent
    failure.
  - A short helper note in the card: *"Director/Producer tag who may reach the Director
    Panel / producer ops over the console. Needs the Sheet `Crew` tab + the `crew`
    webhook action (wiki: Sheet-Webhook)."*

- [ ] **Step 2: Manual smoke (controller-assisted, optional but recommended)** — run the
  dev Control Center from `src/` and confirm the card renders and the relay-down path
  shows the error string (no JS console errors). This needs no running relay; the
  error branch is the expected state without one.

Run: `python3 src/racecast.py ui` (then open the Profile view; stop with Ctrl-C).

- [ ] **Step 3: Run the suite + lint + build** (HTML change ⇒ build verify still must
  pass):

Run: `python3 tools/run-tests.py` (Expected: ALL TEST FILES PASS), `python3 tools/lint.py`
(clean), `python3 tools/build.py` (exit 0).

- [ ] **Step 4: Refresh the wiki screenshot — `cc-profile.png` (CONTROLLER step).**
  Capture from a **local dev build** (`racecast ui` straight from `src/`, no `VERSION`
  file, so the dev-build badge matches every other `cc-*.png`). Drive the running
  instance with the Playwright MCP, **route-mock `/api/crew`** to return synthetic rows
  (e.g. `DirectorDana` director, `ProducerPia` producer — NO real league roster), open
  the Profile view, and take an **element screenshot framed like the existing
  `cc-profile.png`** (match its width/region — inspect the current image first). Save
  over `src/docs/wiki/images/cc-profile.png`. Verify it is a dev build (badge) and
  contains no real names/IPs/tokens.

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html src/docs/wiki/images/cc-profile.png
git commit -m "feat(ui): Crew editor in the Control Center Profile view (+ cc-profile.png)"
```

---

### Task 4: Docs + Apps Script coordination artifact + full gate

**Files:**
- Modify: `src/docs/wiki/Sheet-Webhook.md` — document the new `crew` action.
- Modify: `CLAUDE.md` — Control Center Profile-view bullet: mention the crew editor +
  `/api/crew*` routes + the `crew` webhook action + the Crew-tab coordination.
- Modify: `README.md` — one line where Control Center / crew/console features are listed
  (only if the file documents the Profile view; keep minimal).
- Create/commit: this plan doc.

**Interfaces:** none (docs only).

- [ ] **Step 1: Add the `crew` action to `Sheet-Webhook.md`.** Add a table row beside
  `schedule`/`teams`:

```
| `crew` | **Crew** tab (`Name | Director | Producer`, header in row 1). `{"action":"crew","row":N,"name":..,"director":bool,"producer":bool}` writes **data row N** (sheet row N+1; `row last+1` appends); `director`/`producer` booleans write `X` / clear the cell. `{"action":"crew","row":N,"delete":true}` deletes data row N (rows shift up). The tab must start at row 1 with the header and have no interior blank rows (the Control Center editor maintains this). |
```

  Then add a `## Crew` subsection with the Apps Script `writeCrew` function and wire it
  into the dispatch (the doc's `doPost` switch and the `TABS`/response-`v` note):

```javascript
// in TABS:  crew: 'Crew'
// in the action switch:
//   else if (action === 'crew') writeCrew(ss, p);

function writeCrew(ss, p) {
  const sheet = ss.getSheetByName(TABS.crew) || ss.insertSheet(TABS.crew);
  if (sheet.getLastRow() < 1) {
    sheet.getRange(1, 1, 1, 3).setValues([['Name', 'Director', 'Producer']]);
  }
  const row = parseInt(p.row, 10);                 // 1-based data row (header is row 1)
  if (!(row >= 1)) throw 'crew: row must be >= 1';
  const target = row + 1;                          // sheet row (skip the header)
  if (p['delete'] === true) {
    if (target <= sheet.getLastRow()) sheet.deleteRow(target);
    return;
  }
  const name = (p.name || '').toString().trim();
  if (!name) throw 'crew: name is required';
  sheet.getRange(target, 1, 1, 3).setValues([[
    name, p.director ? 'X' : '', p.producer ? 'X' : '']]);
}
```

  Bump the documented response version note to include `crew` (the script answers
  `{"ok":true,"action":"crew","v":<n>}`; the relay's `check_webhook_response` requires
  the action echo).

- [ ] **Step 2: Add the coordination call-out** (in `Sheet-Webhook.md` near the crew
  subsection AND a one-liner in the wiki crew/console page): the league's Sheet needs a
  `Crew` tab with the `Name | Director | Producer` header and the redeployed v-script
  handling `crew`; **without it, director/producer roles simply resolve to empty
  (commentators still work from the Schedule) — the editor surfaces the outdated-script
  error, nothing crashes.**

- [ ] **Step 3: Update `CLAUDE.md`** — in the Control Center "Profile view" description,
  add the crew editor (reads `Crew` tab via the relay, writes via the `crew` webhook
  action, routes `/api/crew`, `/api/crew/delete`) and that the Crew tab + Apps Script
  `crew` action are a league Sheet-side coordination item (documented in Sheet-Webhook).

- [ ] **Step 4: Update `README.md`** if it enumerates Control Center features — one line
  for the crew editor; otherwise skip (note "n/a" in the commit body).

- [ ] **Step 5: Full local gate**

Run: `python3 tools/run-tests.py` (ALL TEST FILES PASS), `python3 tools/lint.py` (clean),
`python3 tools/build.py` (exit 0), `python3 tests/test_pov.py` (ALL PASS).

- [ ] **Step 6: Commit (docs + plan)**

```bash
git add docs/superpowers/plans/2026-06-19-console-roles-phase6-crew-editor.md \
        src/docs/wiki/Sheet-Webhook.md CLAUDE.md README.md
git commit -m "docs(crew): Sheet-Webhook crew action + Control Center crew-editor docs"
```

---

## Self-Review

- **Spec coverage (§G):** crew editor in Profile view ✓ (Task 3); read Crew tab ✓
  (Task 2 via existing `/crew/data`); write via `SHEET_PUSH_URL` + new `crew` action ✓
  (Task 1); routes in `ui_server.py` ✓ (Task 2); tests in `test_ui_server.py` ✓ (Task 2);
  Apps Script / Crew-tab coordination documented + graceful degradation ✓ (Task 4);
  wiki screenshot refreshed in the same change ✓ (Task 3).
- **Granularity decision honored:** per-row writes mirroring `schedule`; delete a
  separate `delete:true` op (Task 1).
- **Trust boundary:** Control Center → relay → webhook; no direct webhook POST from the
  CC (Global Constraints, Task 2 funcs).
- **Type consistency:** `crew_set(row,name,director,producer)` / `crew_delete(row)` and
  the `/crew/set` `{row,name,director,producer}` / `/crew/delete` `{row}` bodies and the
  `ctx` `crew_write(row,name,director,producer)` / `crew_delete(row)` signatures all
  line up across Tasks 1–2. `CrewSource` rows stay `(name, is_director, is_producer)`.
- **Boundary unchanged:** `/crew/*` are root (tailnet/loopback) relay paths, never under
  `/console`, never funnel-mounted — Phase 6 adds no public surface.
```
