# POV box name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a free-text name to the OBS POV box that the producer enters in the Director Panel, stored in the existing Sheet `POV` tab; the whole POV box (frame + name) shows only while the POV feed is on air.

**Architecture:** The name lives in the existing `POV` tab's `name` column — read by the relay's `pov_source` (a `ScheduleSource`), written by the existing `pov` webhook action. The relay exposes two pure projections (`pov_active`, `pov_name`) merged into `/hud/data`; the HUD page renders/hides the box on `povActive`; the panel's existing POV row gains a name input. No Setup/Overlay tab is touched.

**Tech Stack:** Pure Python 3 + stdlib (relay `ThreadingHTTPServer`), HTML/CSS/vanilla JS (HUD page + Director Panel), Google Apps Script (embedded in a wiki markdown file). Tests are stdlib runnable scripts (no pytest).

**Spec:** `docs/superpowers/specs/2026-06-14-pov-box-name-design.md`

**Branch:** `feat/pov-box-name` (already created; spec already committed).

**Repo rules (CLAUDE.md):** edit only under `src/`; English only; no machine paths / real IPs; build fixed-OS paths with forward slashes (not `os.path.join`). The relay file is `src/relay/racecast-feeds.py` (filename has a hyphen — tests import it via `importlib`, already wired in `tests/test_pov.py` / `tests/test_setup.py`).

**Local gates (run before the PR — the closest mirror of CI):**
```bash
python3 tools/run-tests.py     # whole suite (what CI runs)
python3 tools/lint.py          # ruff (also runs on every edit via the hook)
python3 tools/build.py         # must exit 0 — its verify step ~= CI
python3 tests/test_pov.py      # relay change — explicit per CLAUDE.md
```

---

## File Structure

- `src/relay/racecast-feeds.py` — relay. Add the `name`-column read, `Relay.pov_active()` / `Relay.pov_name()`, the `/hud/data` route merge, `/status` `pov.name`, `SetupControl.pov_set(url, name)` + `pov_source` wiring, `/pov/set` route.
- `src/obs/hud.html` — HUD page. Add the `#pov-name` slot (markup + default CSS) and POV gating in `tick()`.
- `src/director/director-panel.html` — Director Panel. Add the POV-row name input, send it in `povSave`, prefill it from `/status`.
- `src/docs/wiki/Sheet-Webhook.md` — embedded Apps Script. Make `writePov` write the `name` cell; bump `v: 4` → `v: 5`; update the action table.
- `tests/test_pov.py` — relay projections (`pov_active`, `pov_name`) + HUD-page string checks.
- `tests/test_setup.py` — `_parse_rows` `name`-header read (+ `streamer` regression) and `SetupControl.pov_set(url, name)`.
- `src/docs/wiki/images/director-panel.png` — refreshed screenshot (required).
- `src/docs/wiki/images/cc-overlay-builder.png` — refreshed only if the new builder slot is visible in the captured frame (verify).

---

## Task 1: Relay reads the POV tab's `name` column

The POV tab header is `url,name`. The schedule parser only recognizes `streamer` today, so the POV name column is dropped. Make `name` an accepted streamer-column header (additive — `streamer` still wins when both exist).

**Files:**
- Modify: `src/relay/racecast-feeds.py` (the `SCHEDULE_STREAMER_HEADERS` constant, currently `("streamer",)`)
- Test: `tests/test_setup.py` (alongside the existing `t_parse_rows_*` header-mode tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_setup.py` after `t_parse_rows_header_mode_planned_streamer_only` (around line 132):

```python
def t_parse_rows_reads_name_header_for_pov_tab():
    # The POV tab uses a 'name' column (no 'streamer'); header mode reads it into
    # the row's name field so the relay can surface the POV name.
    text = "url,name\nhttps://www.youtube.com/watch?v=p,JeGr\n"
    rows = m.ScheduleSource._parse_rows(text)
    assert rows == [("https://www.youtube.com/watch?v=p", "JeGr", "", 2)], rows


def t_parse_rows_streamer_still_wins_over_name():
    # Additive change must not regress the Schedule tab: when both 'streamer' and
    # 'name' headers exist, 'streamer' is the one read (first match wins).
    text = ("url,streamer,name\n"
            "https://www.youtube.com/watch?v=p,RealStreamer,SomethingElse\n")
    rows = m.ScheduleSource._parse_rows(text)
    assert rows == [("https://www.youtube.com/watch?v=p", "RealStreamer", "", 2)], rows
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_setup as t; t.t_parse_rows_reads_name_header_for_pov_tab()"
```
Expected: FAIL — `AssertionError` showing the name field is `""` (the `name` column is not read yet).

- [ ] **Step 3: Make `name` an accepted streamer header**

In `src/relay/racecast-feeds.py`, change the constant (currently `SCHEDULE_STREAMER_HEADERS = ("streamer",)`):

```python
SCHEDULE_STREAMER_HEADERS = ("streamer", "name")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_setup as t; t.t_parse_rows_reads_name_header_for_pov_tab(); t.t_parse_rows_streamer_still_wins_over_name(); print('ok')"
python3 tests/test_setup.py
```
Expected: both new tests pass and `tests/test_setup.py` prints `ALL PASS` (no regression in the other `_parse_rows` tests, which all use a `streamer`/positional layout).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(relay): read the POV tab's name column (#130)"
```

---

## Task 2: Relay projections `pov_active()` and `pov_name()`

Two pure read-only methods on `Relay`, mirroring #129's `splitscreen_state()`.

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add methods to the `Relay` class — place them right after the existing `splitscreen_state()` method)
- Test: `tests/test_pov.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` after `t_splitscreen_state_hides_next_in_qualifying` (the `_relay`, `_StubSource`, and `HERE` helpers already exist in this file):

```python
def t_pov_active_tracks_feed_paused():
    r = _relay(["s1", "s2"])
    assert r.pov is None
    assert r.pov_active() is False                 # no POV feed wired
    r.pov = m.Feed("POV", 53003, 0, lambda: ["https://youtu.be/p"], HERE)
    r.pov.paused = True
    assert r.pov_active() is False                  # off
    r.pov.paused = False
    assert r.pov_active() is True                   # live


def t_pov_name_reads_pov_source_row():
    r = _relay(["s1", "s2"])
    assert r.pov_name() == ""                        # no pov_source
    r.pov_source = _StubSource(["https://youtu.be/p"],
                               rows=[("https://youtu.be/p", "JeGr", "", 2)])
    assert r.pov_name() == "JeGr"
    r.pov_source = _StubSource([], rows=[])          # source but no row
    assert r.pov_name() == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pov_active_tracks_feed_paused()"
```
Expected: FAIL — `AttributeError: 'Relay' object has no attribute 'pov_active'`.

- [ ] **Step 3: Add the projections**

In `src/relay/racecast-feeds.py`, in the `Relay` class immediately after the `splitscreen_state()` method, add:

```python
    def pov_active(self):
        """True when the POV picture-in-picture feed is live (started, not
        paused). Drives the HUD: the whole POV box — frame and name — shows
        only while the POV is on air."""
        return bool(self.pov and not self.pov.paused)

    def pov_name(self):
        """The POV name from the POV tab's one data row (the 'name' column),
        or '' when there is no POV source / row."""
        if not self.pov_source:
            return ""
        rows = self.pov_source.get_rows()
        return rows[0][1] if rows else ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_pov_active_tracks_feed_paused(); t.t_pov_name_reads_pov_source_row(); print('ok')"
python3 tests/test_pov.py
```
Expected: both new tests pass; `tests/test_pov.py` prints `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): pov_active/pov_name projections (#130)"
```

---

## Task 3: Merge `povActive` + `povName` into `/hud/data`; add `pov.name` to `/status`

Thin glue at the route/status layer (the projections from Task 2 carry the logic). Verified live; no new unit test (route handlers need a running server — the build + a live probe cover this).

**Files:**
- Modify: `src/relay/racecast-feeds.py` — the `["hud", "data"]` route branch in `make_handler` (currently `return self._send(hud_source.data())`), and the `out["pov"]` dict in `status()` (the `if self.pov:` block).

- [ ] **Step 1: Merge the relay-owned POV state into `/hud/data`**

In `src/relay/racecast-feeds.py`, replace the `["hud", "data"]` branch:

```python
                if p == ["hud", "data"]:
                    if not hud_source:
                        return self._send({"error": "hud disabled"}, 404)
                    return self._send(hud_source.data())
```

with:

```python
                if p == ["hud", "data"]:
                    if not hud_source:
                        return self._send({"error": "hud disabled"}, 404)
                    data = hud_source.data()           # already a shallow copy
                    data["povActive"] = relay.pov_active()
                    data["povName"] = relay.pov_name()
                    return self._send(data)
```

- [ ] **Step 2: Add `name` to the `/status` POV object**

In `status()`, the `if self.pov:` block currently builds:

```python
            out["pov"] = {"port": self.pov.port, "url": raw,
                          "state": "stopped" if self.pov.paused else self.pov.phase,
                          "state_age_s": round(now - self.pov.phase_since, 1),
                          "source": self.pov_source.health() if self.pov_source else None}
```

Add the `name` key:

```python
            out["pov"] = {"port": self.pov.port, "url": raw,
                          "name": self.pov_name(),
                          "state": "stopped" if self.pov.paused else self.pov.phase,
                          "state_age_s": round(now - self.pov.phase_since, 1),
                          "source": self.pov_source.health() if self.pov_source else None}
```

- [ ] **Step 3: Verify nothing broke**

Run:
```bash
python3 tests/test_pov.py && python3 tests/test_setup.py && python3 tests/test_racecast.py
```
Expected: each prints `ALL PASS` (the `HudSource.data()` shallow-copy means adding keys at the route does not mutate cached state).

- [ ] **Step 4: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): surface povActive/povName on /hud/data and /status (#130)"
```

---

## Task 4: Write the name through `SetupControl.pov_set(url, name)`

Extend the existing POV write to carry the name and refresh `pov_source` so the name applies immediately.

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `SetupControl.__init__` (add `pov_source=None`), `SetupControl.pov_set` (add `name` param), the `SetupControl(...)` construction site (pass `pov_source=pov_source`), and the `["pov", "set"]` route (pass `body.get("name")`).
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_setup.py`, first extend the `_ctl` helper so a test can supply a stub `pov_source` (replace the existing `_ctl` definition around line 174):

```python
def _ctl(pushes, response=b'{"ok": true, "action": "%s", "v": 2}', pov_source=None):
    hs = _hs_stub()
    ctl = m.SetupControl("http://push", hs, pov_source=pov_source)
    def fake_post(url, payload, timeout=10):
        pushes.append(payload)
        return response % payload["action"].encode() if b"%s" in response else response
    m.post_webhook, orig = fake_post, m.post_webhook
    return ctl, hs, orig
```

Then update the existing `t_pov_set_pushes` to assert the URL-only call stays backward-compatible (no `name` key), and add a new test. Replace `t_pov_set_pushes` (around line 267) with:

```python
def t_pov_set_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.pov_set("nonsense")
        r = ctl.pov_set("https://www.youtube.com/watch?v=p")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "pov", "url": "https://www.youtube.com/watch?v=p"}
    finally:
        m.post_webhook = orig


class _RefreshSpy:
    """Minimal pov_source stub: records refresh() calls."""
    def __init__(self):
        self.refreshed = 0
    def refresh(self, timeout=6):
        self.refreshed += 1
        return True


def t_pov_set_with_name_pushes_clamped_and_refreshes():
    pushes = []
    spy = _RefreshSpy()
    ctl, hs, orig = _ctl(pushes, pov_source=spy)
    try:
        r = ctl.pov_set("https://www.youtube.com/watch?v=p", "A Very Long Driver Name Here")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "pov",
                              "url": "https://www.youtube.com/watch?v=p",
                              "name": "A Very Long Driver N"}    # clamped to 20 chars
        assert len(pushes[-1]["name"]) == 20
        assert spy.refreshed == 1                                 # name applied immediately
    finally:
        m.post_webhook = orig


def t_pov_set_empty_name_clears():
    pushes = []
    spy = _RefreshSpy()
    ctl, hs, orig = _ctl(pushes, pov_source=spy)
    try:
        r = ctl.pov_set("https://www.youtube.com/watch?v=p", "")
        assert r.get("ok"), r
        assert pushes[-1]["name"] == ""                           # explicit clear
    finally:
        m.post_webhook = orig
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_setup as t; t.t_pov_set_with_name_pushes_clamped_and_refreshes()"
```
Expected: FAIL — `TypeError: pov_set() takes 2 positional arguments but 3 were given` (or a missing-`name`-key assertion).

- [ ] **Step 3: Implement the signature + wiring**

In `src/relay/racecast-feeds.py`:

3a. `SetupControl.__init__` — add the `pov_source` parameter (current signature: `def __init__(self, push_url, hud_source, schedule_source=None, qual_source=None):`):

```python
    def __init__(self, push_url, hud_source, schedule_source=None, qual_source=None,
                 pov_source=None):
        self.push_url = push_url
        self.hud = hud_source
        self.schedule_source = schedule_source
        self.qual_source = qual_source
        self.pov_source = pov_source
        self.push_status = "disabled" if not push_url else "never"
        self.last_error = None
```

3b. `SetupControl.pov_set` — add the `name` param, clamp, and refresh on success (current body pushes `{"action": "pov", "url": url}`):

```python
    def pov_set(self, url, name=None):
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        if url is not None and not isinstance(url, str):
            return {"error": "url must be a string"}
        url = (url or "").strip()
        if url and not is_channel(url):
            return {"error": "url must be a watch URL or UC… channel ID"}
        payload = {"action": "pov", "url": url}
        if name is not None:
            payload["name"] = (name or "")[:20]
        ok, err = self._push(payload, "pov")
        if ok and self.pov_source is not None:
            self.pov_source.refresh()    # name (and stored url) live immediately
        return {"ok": True} if ok else {"error": err}
```

3c. Construction site — pass `pov_source` (current call at the `setup_ctl = (SetupControl(...))` line):

```python
    setup_ctl = (SetupControl(push_url, hud_source, schedule_source=source,
                              qual_source=qual_source, pov_source=pov_source)
                 if hud_source else None)
```

3d. Route — pass the name (current branch: `if p == ["pov", "set"]: return self._send(setup_ctl.pov_set(body.get("url")))`):

```python
                if p == ["pov", "set"]:
                    return self._send(setup_ctl.pov_set(body.get("url"),
                                                        body.get("name")))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python3 tests/test_setup.py && python3 tests/test_pov.py
```
Expected: both print `ALL PASS` (the updated `t_pov_set_pushes` confirms URL-only back-compat; the two new tests confirm clamp + refresh + clear).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(relay): pov_set writes the POV name and refreshes the source (#130)"
```

---

## Task 5: HUD page — `#pov-name` slot + POV gating in `tick()`

**Files:**
- Modify: `src/obs/hud.html` (the `#pov` CSS rule ~line 63, the markup `<div id="pov" …>` ~line 103, and the `tick()` function ~line 177)
- Test: `tests/test_pov.py` (string checks against the page)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pov.py` (after the Task 2 tests). `HERE` is the relay dir; the HUD page is `src/obs/hud.html`, i.e. `HERE/../obs/hud.html`:

```python
def t_hud_page_has_pov_name_slot_and_gating():
    import os as _os
    path = _os.path.join(HERE, "..", "obs", "hud.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    # The name slot exists and is a builder slot (data-edit marker).
    assert 'id="pov-name"' in html
    assert 'data-edit="POV name"' in html
    # tick() hides the whole POV box (frame) when the POV feed is off.
    assert "povActive" in html
    assert 'getElementById("pov").classList.toggle("empty"' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_hud_page_has_pov_name_slot_and_gating()"
```
Expected: FAIL — `AssertionError` on `'id="pov-name"' in html`.

- [ ] **Step 3a: Add the default CSS**

In `src/obs/hud.html`, after the `#pov { … }` rule (around line 63):

```css
  /* POV name label — top-right of the POV frame, splitscreen-label look (#130).
     A normal builder box (left/top/width/height + text props); grey-pill look is
     the default fill. Shown only while the POV feed is on air (see tick()). */
  #pov-name { left: 1592px; top: 618px; width: 288px; height: 38px;
    justify-content: flex-end;
    background: rgba(38,44,52,.92); border: 1px solid #4a5560; border-radius: 7px;
    padding: 0 12px; color: #fff;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-weight: 600; font-size: 22px; letter-spacing: .04em; }
```

- [ ] **Step 3b: Add the markup**

In `src/obs/hud.html`, immediately after the `<div id="pov" …></div>` line (around line 103):

```html
  <div id="pov-name" class="el" data-edit="POV name" data-edit-props="left,top,width,height,fontSize,fontFamily,color,background,borderStyle,borderColor,borderWidth,align"></div>
```

- [ ] **Step 3c: Gate the box in `tick()`**

In `src/obs/hud.html`, inside `tick()`, after the `setText("race-control", d.raceControl);` line (around line 188):

```js
      const povOn = !!d.povActive;
      document.getElementById("pov").classList.toggle("empty", !povOn);
      setText("pov-name", povOn ? (d.povName || "") : "");
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'tests'); import test_pov as t; t.t_hud_page_has_pov_name_slot_and_gating(); print('ok')"
python3 tests/test_pov.py
```
Expected: the new test passes; `tests/test_pov.py` prints `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/obs/hud.html tests/test_pov.py
git commit -m "feat(overlay): POV name slot on the HUD, gated on POV-active (#130)"
```

---

## Task 6: Director Panel — POV-row name input, save, and prefill

**Files:**
- Modify: `src/director/director-panel.html` — the POV row markup (~line 319), the `#povSave` click handler (~line 1157), the `#povUrl` input listener (~line 1175), and the `/status` prefill in `schedPoll` (~line 1200).

No unit test (the panel is static HTML/JS verified live + via the screenshot refresh in Task 8).

- [ ] **Step 1: Add the name input to the POV row**

In `src/director/director-panel.html`, replace the POV row (currently a single URL cell):

```html
        <tr><td class="rn">POV</td>
            <td><input id="povUrl" placeholder="youtube.com/watch?v=… · twitch.tv/<channel> · UC…"></td>
            <td class="act"><button class="save" id="povSave">SAVE</button></td></tr>
```

with a two-input row (name + URL share the one SAVE):

```html
        <tr><td class="rn">POV</td>
            <td><input id="povName" maxlength="20" placeholder="name (max 20)"></td>
            <td><input id="povUrl" placeholder="youtube.com/watch?v=… · twitch.tv/<channel> · UC…"></td>
            <td class="act"><button class="save" id="povSave">SAVE</button></td></tr>
```

- [ ] **Step 2: Send the name in `povSave`**

In the `#povSave` click handler, change the request body (currently `body: JSON.stringify({url: $("#povUrl").value.trim()})`) to send both fields, and stamp `#povName.dataset.saved` on success alongside `#povUrl`:

```js
      body: JSON.stringify({url: $("#povUrl").value.trim(),
                            name: $("#povName").value.trim()})});
```

and in the success branch (currently `delete $("#povUrl").dataset.dirty; $("#povUrl").dataset.saved = Date.now();`):

```js
    delete $("#povUrl").dataset.dirty; $("#povUrl").dataset.saved = Date.now();
    delete $("#povName").dataset.dirty; $("#povName").dataset.saved = Date.now();
```

Also update the success log line (currently `log("POV URL saved — applies on POV RELOAD.");`) to reflect both:

```js
    log("POV name + URL saved — name applies now, URL on POV RELOAD.");
```

- [ ] **Step 3: Track dirty on the name input**

After the existing `$("#povUrl").addEventListener("input", …)` line (~line 1175), add:

```js
$("#povName").addEventListener("input", ()=>$("#povName").dataset.dirty = 1);
```

- [ ] **Step 4: Prefill the name from `/status`**

In `schedPoll`, the `/status` block currently prefills only `#povUrl`:

```js
    const inp = $("#povUrl");
    if (d.pov && !inp.dataset.dirty && inp !== document.activeElement &&
        Date.now() - Number(inp.dataset.saved||0) > SAVE_GUARD_MS)
      inp.value = d.pov.url || "";
```

Add the parallel prefill for `#povName` (using the new `d.pov.name`):

```js
    const inp = $("#povUrl");
    if (d.pov && !inp.dataset.dirty && inp !== document.activeElement &&
        Date.now() - Number(inp.dataset.saved||0) > SAVE_GUARD_MS)
      inp.value = d.pov.url || "";
    const ninp = $("#povName");
    if (d.pov && !ninp.dataset.dirty && ninp !== document.activeElement &&
        Date.now() - Number(ninp.dataset.saved||0) > SAVE_GUARD_MS)
      ninp.value = d.pov.name || "";
```

- [ ] **Step 5: Verify the suite still passes + lint**

Run:
```bash
python3 tools/run-tests.py && python3 tools/lint.py
```
Expected: suite `ALL PASS`, lint clean (the panel is not unit-tested but `run-tests.py` must stay green; lint covers Python only — this step guards against accidental relay edits).

- [ ] **Step 6: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): POV name input on the POV row (#130)"
```

---

## Task 7: Apps Script (wiki) — write the POV `name` cell

The webhook script is embedded in `src/docs/wiki/Sheet-Webhook.md` and must be updated alongside the relay setup change.

**Files:**
- Modify: `src/docs/wiki/Sheet-Webhook.md` — the `writePov` function in the embedded script, the `v: 4` version literal in `doPost`, and the action table row for `pov`.

- [ ] **Step 1: Make `writePov` header-aware and write the `name` cell**

In `src/docs/wiki/Sheet-Webhook.md`, replace the embedded `writePov` (currently `tab(ss, TABS.pov).getRange(2, 1).setNumberFormat('@').setValue(p.url || '');`) with:

```javascript
   function writePov(ss, p) {
     const sheet = tab(ss, TABS.pov);
     const lastCol = Math.max(1, sheet.getLastColumn());
     const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
     const colOf = (name) => {
       for (let c = 0; c < header.length; c++)
         if (String(header[c]).trim().toLowerCase() === name) return c + 1;
       return 0;
     };
     if ('url' in p)  sheet.getRange(2, colOf('url')  || 1).setNumberFormat('@').setValue(p.url  || '');
     if ('name' in p) sheet.getRange(2, colOf('name') || 2).setNumberFormat('@').setValue(p.name || '');
   }
```

- [ ] **Step 2: Bump the response version**

In the embedded `doPost`, change `return out({ok: true, action: action, v: 4});` to:

```javascript
       return out({ok: true, action: action, v: 5});
```

- [ ] **Step 3: Update the action table**

The action table (around line 20) documents each action's target. Update the `pov` row to note it now writes the `name` cell too. The current table lists `setup`, `teams`, etc.; find the `pov`/POV-tab row (or the prose that describes the `pov` action writing the POV tab `A2` cell) and extend it to:

> `pov` | POV tab row 2: writes the `url` and/or `name` cell (located by header text, so columns may move)

Also update the trailing footnote near line 153 / line 202 if it pins "POV tab A2" specifically — change "A2" wording to "row 2 (url/name columns)".

- [ ] **Step 4: Sanity-check the markdown still renders the script block**

Run:
```bash
python3 -c "open('src/docs/wiki/Sheet-Webhook.md').read().index('function writePov'); print('writePov present')"
grep -n "v: 5" src/docs/wiki/Sheet-Webhook.md
```
Expected: prints `writePov present` and shows the `v: 5` line (no other `v: 4` left in the script).

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/Sheet-Webhook.md
git commit -m "feat(sheet): writePov stores the POV name cell, script v5 (#130)"
```

---

## Task 8: Live verification + wiki screenshots + gates

The Director Panel changed (a covered UI surface), so its wiki screenshot must be refreshed in this same change (CLAUDE.md). Verify the new builder slot's effect on the overlay-builder screenshot too.

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png` (required)
- Modify (conditional): `src/docs/wiki/images/cc-overlay-builder.png` (only if the new `POV name` slot is visible in the captured frame)

- [ ] **Step 1: Run the full local gates**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
python3 tests/test_pov.py
```
Expected: suite `ALL PASS`, lint clean, `tools/build.py` exits 0 with its verify checks passing.

- [ ] **Step 2: Live-probe the relay endpoints**

Start the relay against the borrowed test profile (memory: a real install + `iro-gtec` profile lives at `~/Documents/racecast`; copy its `profiles/iro-gtec` + a `.env` with `SHEET_ID`/`SHEET_PUSH_URL` into the dev repo to drive real data — do NOT commit it). Then:

```bash
python3 src/racecast.py relay start
# POV off -> box hidden, no name:
curl -s http://127.0.0.1:8088/hud/data | python3 -m json.tool | grep -E 'povActive|povName'
# Bring POV on air, then re-check povActive flips true:
curl -s http://127.0.0.1:8088/pov/reload
curl -s http://127.0.0.1:8088/hud/data | python3 -m json.tool | grep -E 'povActive|povName'
# /status carries the name for panel prefill:
curl -s http://127.0.0.1:8088/status | python3 -m json.tool | grep -A6 '"pov"'
python3 src/racecast.py relay stop
```
Expected: `povActive` is `false` then `true` after `/pov/reload`; `povName` reflects the POV tab's `name` cell; `/status` `pov` object includes `"name"`.

- [ ] **Step 3: Recapture the Director Panel screenshot**

With the relay running and the borrowed profile loaded, open `http://127.0.0.1:8088/panel` in the Playwright MCP at the SAME viewport width as the existing image (1400px wide — the prior `director-panel.png` framing). Expand the **URLs · Schedule + POV** section so the new POV name input is visible, and take a full-page screenshot. Save it over `src/docs/wiki/images/director-panel.png`. Confirm the dimensions/width match the previous image's framing (see the #152 recapture: resize the viewport to 1400px wide, not a narrow tablet viewport).

- [ ] **Step 4: Check the overlay-builder screenshot**

Start the Control Center, open the overlay builder (HUD page), and look at whether the new `POV name` slot box appears within the captured canvas frame used by `src/docs/wiki/images/cc-overlay-builder.png`:

```bash
python3 src/racecast.py ui     # then drive with the Playwright MCP
```
- If the `POV name` slot is visible in the builder canvas at the existing screenshot's framing → recapture an **element** screenshot of the same card/modal (match the existing image's framing, e.g. `#ov-modal .ovmodal-card`) and save over `src/docs/wiki/images/cc-overlay-builder.png`.
- If it is NOT visible at that framing (e.g. cropped out top-right) → leave the image unchanged and note in the PR body that the builder screenshot was checked and is unaffected.

- [ ] **Step 5: Commit the screenshot(s)**

```bash
git add src/docs/wiki/images/director-panel.png
# add cc-overlay-builder.png too ONLY if it changed in Step 4
git commit -m "docs(wiki): refresh Director Panel screenshot for the POV name field (#130)"
```

- [ ] **Step 6: Final gate before PR**

Run once more to confirm the committed tree is green:
```bash
python3 tools/run-tests.py && python3 tools/lint.py && python3 tools/build.py && echo GREEN
```
Expected: `GREEN`.

---

## Definition of done

- [ ] `pov_active()` / `pov_name()` projections exist and are unit-tested.
- [ ] `/hud/data` carries `povActive` + `povName`; `/status` `pov` carries `name`.
- [ ] `SetupControl.pov_set(url, name)` clamps to 20, refreshes `pov_source`, stays URL-only backward-compatible; `/pov/set` passes the name.
- [ ] The POV tab `name` column is read (`SCHEDULE_STREAMER_HEADERS`), with the `streamer`-wins regression covered.
- [ ] `src/obs/hud.html` has the `#pov-name` builder slot and hides the whole POV box (frame + name) when `povActive` is false.
- [ ] The Director Panel POV row has a `maxlength=20` name input that saves with the URL and prefills from `/status`.
- [ ] The embedded Apps Script writes the `name` cell and reports `v: 5`; the action table is updated.
- [ ] `director-panel.png` refreshed; `cc-overlay-builder.png` checked (refreshed iff the new slot is visible).
- [ ] `run-tests.py` + `lint.py` + `build.py` (exit 0) + `test_pov.py` all green locally.
- [ ] One PR titled `feat(overlay): POV box name` (or similar) with `Closes #130`.
