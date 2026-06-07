# Panel Sheet Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the stream director control all during-event sheet values (Setup fields Stint/Streamer/Session/Race Control, Schedule URLs+names, POV URL) from the relay's `/panel` instead of editing the Google Sheet.

**Architecture:** The sheet stays authoritative. Setup-field writes go through a generalized Apps Script webhook (v2 of the timer script) with an *optimistic echo*: the relay overlays the new value on `/hud/data` immediately, pushes to the sheet in the background, and the override clears when the Overlay poll confirms (or expires after 30 s). URL writes (Schedule/POV) are synchronous webhook calls with no local echo — feeds pick them up on the existing RELOAD/NEXT. `IRO_TIMER_PUSH_URL` is hard-renamed to `IRO_SHEET_PUSH_URL` (no fallback).

**Tech Stack:** Python 3 stdlib only (no pytest — each test file is a runnable script), vanilla JS in `director-panel.html`, Google Apps Script (documented in the wiki, not executable in-repo).

**Spec:** `docs/superpowers/specs/2026-06-07-panel-sheet-control-design.md` — read it first.

**Conventions that apply to every task:**
- Run `python3 tools/lint.py` after changing any Python file.
- Tests: `python3 tests/<file>.py` runs one file; `python3 tools/run-tests.py` runs the suite (auto-discovers `tests/test_*.py` — a new test file needs no registration).
- All code/docs English. No shell scripts. No secrets/machine paths in git.
- The relay module is loaded in tests via `importlib` (filename has a dash): see the header of `tests/test_hud.py`.

**Key terminology (from the spec):** the Setup-tab field "Stint" is the *HUD display label* ("Stint 4", "Intro"). It is unrelated to the relay's *feed stint index* (`/set/stint/<n>`, NEXT). Don't conflate them in code comments or docs.

---

### Task 1: Hard rename `IRO_TIMER_PUSH_URL` → `IRO_SHEET_PUSH_URL`

The webhook URL now powers timer sync AND the panel's sheet writes, so the name generalizes. No fallback (no production users yet). Historical records under `docs/superpowers/plans|specs/` (race-timer, director-panel-redesign) stay untouched.

**Files:**
- Modify: `tests/test_event.py:184`
- Modify: `src/scripts/event.py:227-233`
- Modify: `src/iro.py:711`, `src/iro.py:982`
- Modify: `src/relay/iro-feeds.py:1325`, `:1333`, `:1412`
- Modify: `src/director/director-panel.html:552`
- Modify: `.env.example:9-15`
- Modify: `CLAUDE.md:122`
- Modify: `src/docs/wiki/Configuration.md` (lines 22, 29, 45), `src/docs/wiki/Set-up-the-broadcast-PC.md:138`, `src/docs/wiki/Race-Timer.md:83`
- Modify: `src/docs/README_SETUP.md:108`, `src/docs/IRO_Broadcast_Setup_Guide.md:224`

- [ ] **Step 1: Update the test expectation first**

In `tests/test_event.py:184` change the assertion:

```python
    assert r.level == "WARN" and "IRO_SHEET_PUSH_URL" in r.detail
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 tests/test_event.py`
Expected: AssertionError on that test (the code still says `IRO_TIMER_PUSH_URL`).

- [ ] **Step 3: Rename in code**

`src/scripts/event.py` (`classify_env`, lines 227-233):

```python
def classify_env(sheet_id, push_url):
    """IRO_SHEET_ID is required (FAIL); the sheet-write webhook is optional —
    missing means no timer handover sync and a read-only panel Setup row (WARN)."""
    if not sheet_id:
        return Result(FAIL, ".env", "missing: IRO_SHEET_ID — fill it in "
                      "(.env next to the binary / repo root)")
    if not push_url:
        return Result(WARN, ".env", "IRO_SHEET_PUSH_URL unset — race-timer "
                      "handover sync and panel sheet controls disabled "
                      "(see the Sheet-Webhook wiki page)")
    return Result(PASS, ".env", "IRO_SHEET_ID and IRO_SHEET_PUSH_URL set")
```

`src/iro.py:711`: `os.environ.get("IRO_SHEET_PUSH_URL")`
`src/iro.py:982`: `f"Fill in IRO_SHEET_ID in {path} (IRO_SHEET_PUSH_URL is "`

`src/relay/iro-feeds.py`:
- line 1325 comment: `# (custom --sheet-csv-url -> local-only); push via IRO_SHEET_PUSH_URL.`
- line 1333: `timer_store = TimerStore(timer_csv, os.environ.get("IRO_SHEET_PUSH_URL"),`
- line 1412: `"sheet read-only (set IRO_SHEET_PUSH_URL for handover sync)"`

`src/director/director-panel.html:552`: `: d.sync.push === "disabled" ? "local only (IRO_SHEET_PUSH_URL unset)"`

`.env.example` — replace the `IRO_TIMER_PUSH_URL` block with:

```
# OPTIONAL: sheet-write webhook (Google Apps Script /exec URL INCLUDING its
# ?key=... secret). Lets Director actions write back to the Sheet: race-timer
# sync (Timer tab) and the panel's Setup/Schedule/POV controls. Unset = timer
# is local-only and the panel's sheet controls are read-only.
# Setup: see the wiki page "Sheet-Webhook".
IRO_SHEET_PUSH_URL=
```

`CLAUDE.md:122`: rename the var and adjust the parenthetical: `IRO_SHEET_PUSH_URL` (optional Apps Script webhook that lets the relay write to the Sheet: race-timer state + the panel's Setup/Schedule/POV controls).

Wiki/docs (`Configuration.md`, `Set-up-the-broadcast-PC.md`, `Race-Timer.md`, `README_SETUP.md`, `IRO_Broadcast_Setup_Guide.md`): mechanical rename of the variable name only (Task 10 reworks the surrounding prose).

- [ ] **Step 4: Verify nothing live still references the old name**

Run: `grep -rn "IRO_TIMER_PUSH_URL" . --exclude-dir=runtime --exclude-dir=dist --exclude-dir=.git --exclude-dir=incoming`
Expected: hits ONLY under `docs/superpowers/` (historical specs/plans) — nothing in `src/`, `tests/`, `tools/`, `.github/`, `.env.example`, `CLAUDE.md`.

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_event.py && python3 tools/run-tests.py && python3 tools/lint.py`
Expected: ALL PASS, lint clean.

- [ ] **Step 6: Commit**

```bash
git add -A
# NOTE: deliberately NOT marked as a breaking change ("!" / BREAKING CHANGE
# footer) — no production users yet, and release-please would force 2.0.0.
git commit -m "refactor(env): rename IRO_TIMER_PUSH_URL to IRO_SHEET_PUSH_URL (no fallback)"
```

---

### Task 2: Shared webhook helpers (`post_webhook`, `check_webhook_response`)

Extract the Apps-Script POST + ok-check from `TimerStore` so the new setup/schedule/pov writes reuse it, and add the v2 `action`-echo check (a v1 script answering a non-timer write must be reported as "outdated", not success).

**Files:**
- Create: `tests/test_setup.py`
- Modify: `src/relay/iro-feeds.py` (module level near `TimerStore`, and `TimerStore._push` at lines 500-526)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the panel sheet-control additions.
Run: python3 tests/test_setup.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# ---------- webhook response check (v2 action echo) ----------

def t_webhook_ok_plain():
    ok, err = m.check_webhook_response(b'{"ok": true}')
    assert ok and err is None


def t_webhook_ok_with_echo():
    ok, err = m.check_webhook_response(b'{"ok": true, "action": "setup", "v": 2}',
                                       expected_action="setup")
    assert ok and err is None


def t_webhook_v1_script_is_outdated_for_actions():
    # a v1 timer-only script answers ok WITHOUT the action echo -> not a success
    ok, err = m.check_webhook_response(b'{"ok": true}', expected_action="setup")
    assert not ok and "outdated" in err


def t_webhook_error_body():
    ok, err = m.check_webhook_response(b'{"error": "bad key"}')
    assert not ok and "bad key" in err


def t_webhook_garbage_body():
    ok, err = m.check_webhook_response(b"<html>Apps Script error page</html>")
    assert not ok and "did not confirm" in err
    ok, err = m.check_webhook_response(b"")
    assert not ok


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_setup.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'check_webhook_response'`

- [ ] **Step 3: Implement the helpers**

In `src/relay/iro-feeds.py`, directly above `class TimerStore` (module level):

```python
def post_webhook(url, payload, timeout=10):
    """POST JSON to the Apps-Script sheet-write webhook -> raw response bytes."""
    req = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                  headers={"User-Agent": "iro-feeds/1.0",
                           "Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_webhook_response(body, expected_action=None):
    """(ok, error) from an Apps-Script response body. Apps Script answers
    HTTP 200 even for errors, so only its own {"ok": true} counts. The v2
    script echoes the action; an ok WITHOUT the echo on an action write is a
    still-deployed v1 (timer-only) script -> report it, never a false success."""
    try:
        d = json.loads((body or b"{}").decode("utf-8", "replace"))
    except ValueError:
        d = None
    if not isinstance(d, dict) or d.get("ok") is not True:
        snippet = (body or b"")[:120].decode("utf-8", "replace")
        return False, f"webhook did not confirm: {snippet!r}"
    if expected_action and d.get("action") != expected_action:
        return False, ("webhook script outdated (no action echo) — redeploy "
                       "the v2 script (wiki: Sheet-Webhook)")
    return True, None
```

Refactor `TimerStore._push` (lines 508-526) to use them — delete the
`TimerStore._post` staticmethod (lines 500-506) and replace `_push` with:

```python
    def _push(self, payload):
        """Success = the Apps Script's own {"ok": true} (see
        check_webhook_response). Timer pushes carry no expected_action: a v1
        script keeps working for the timer."""
        try:
            body = post_webhook(self.push_url, payload)
        except Exception as e:
            self.push_status = "failed"
            self.last_error = f"push: {type(e).__name__}: {e}"
            return
        ok, err = check_webhook_response(body)
        if ok:
            self.push_status = "ok"  # diagnostics: single ref assignments, no lock needed
        else:
            self.push_status = "failed"
            self.last_error = f"push: {err}"
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_setup.py && python3 tests/test_timer.py && python3 tools/lint.py`
Expected: both ALL PASS (timer behavior unchanged), lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_setup.py src/relay/iro-feeds.py
git commit -m "feat(relay): shared webhook helpers with v2 action-echo check"
```

---

### Task 3: Configuration vocabulary (`parse_config_vocab` + `HudSource.vocab()`)

The panel dropdowns are strictly limited to the Configuration tab's vocabulary columns. `HudSource.refresh()` already fetches that CSV for brands — parse the option lists from the same fetch.

**Files:**
- Modify: `tests/test_hud.py`
- Modify: `src/relay/iro-feeds.py` (near `parse_config_brands` ~line 288, and `HudSource` ~line 797)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hud.py` (before the `__main__` block; reuses the existing `CONFIG_CSV` constant):

```python
def t_parse_config_vocab():
    v = m.parse_config_vocab(CONFIG_CSV)
    assert v["stint"] == ["Stint 1", "Stint 2", "Stint 3"], v
    assert v["streamer"] == ["JeGr", "GT45"], v
    assert v["session"] == ["Qualifier", "Race"], v
    assert v["racecontrol"] == ["Formation Lap", "Final Lap"], v


def t_parse_config_vocab_missing_columns_safe():
    v = m.parse_config_vocab("a,b\n1,2\n")
    assert v == {"stint": [], "streamer": [], "session": [], "racecontrol": []}
    assert m.parse_config_vocab("") == {"stint": [], "streamer": [],
                                        "session": [], "racecontrol": []}


def t_parse_config_vocab_dedupes_keeps_order():
    v = m.parse_config_vocab("Streamers\nB\nA\nB\n\nA\n")
    assert v["streamer"] == ["B", "A"], v


def t_hudsource_vocab_from_refresh():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    assert hs.vocab() == {"stint": [], "streamer": [], "session": [],
                          "racecontrol": []}   # before any refresh
    hs.refresh()
    assert hs.vocab()["streamer"] == ["JeGr", "GT45"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_hud.py`
Expected: `AttributeError ... parse_config_vocab`

- [ ] **Step 3: Implement**

In `src/relay/iro-feeds.py`, below `parse_config_brands`:

```python
# Configuration-tab vocabulary columns feeding the panel's Setup dropdowns
# (strict: the panel offers ONLY these values — spec: panel-sheet-control).
VOCAB_COLUMNS = {"stint": "stints", "streamer": "streamers",
                 "session": "session", "racecontrol": "race control"}


def parse_config_vocab(text):
    """Configuration tab CSV -> {field_key: [options]} for the panel
    dropdowns. Columns located by header name (parse_config_brands precedent);
    blanks skipped, duplicates dropped, sheet order kept."""
    rows = list(csv.reader(io.StringIO(text)))
    out = {k: [] for k in VOCAB_COLUMNS}
    if not rows:
        return out
    header = [(h or "").strip().lower() for h in rows[0]]
    for key, name in VOCAB_COLUMNS.items():
        if name not in header:
            continue
        i = header.index(name)
        seen = set()
        for row in rows[1:]:
            v = (row[i] or "").strip() if len(row) > i else ""
            if v and v not in seen:
                seen.add(v)
                out[key].append(v)
    return out
```

In `HudSource.__init__` (after `self._data = None`): add `self._vocab = {k: [] for k in VOCAB_COLUMNS}`.

In `HudSource.refresh()` — the config CSV is currently fetched and parsed in one line; split it so the text is parsed twice:

```python
    def refresh(self, timeout=10):
        try:
            overlay = parse_overlay(self._fetch(self.overlay_url, timeout))
            config_text = self._fetch(self.config_url, timeout)
            brands = parse_config_brands(config_text)
            vocab = parse_config_vocab(config_text)
            data = build_hud_data(overlay, brands)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            self._data = data
            self._vocab = vocab
        ...
```

(keep the rest of the method — `last_ok`, cache write — unchanged).

Add the accessor:

```python
    def vocab(self):
        with self.lock:
            return {k: list(v) for k, v in self._vocab.items()}
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_hud.py && python3 tools/lint.py`
Expected: ALL PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(relay): parse Configuration vocabulary for the panel dropdowns"
```

---

### Task 4: Optimistic overrides in `HudSource`

Per-field pending override: applied to `data()` immediately, cleared when the sheet poll confirms the same value, expired after 30 s (webhook down → HUD reverts to sheet truth). Time is injectable — no sleeps in tests.

**Files:**
- Modify: `tests/test_hud.py`
- Modify: `src/relay/iro-feeds.py` (`HudSource`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hud.py`:

```python
def _hs():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    return hs


def t_override_applies_immediately():
    hs = _hs()
    hs.set_override("raceControl", "Formation Lap", now=1000.0)
    assert hs.data(now=1001.0)["raceControl"] == "Formation Lap"
    assert hs.data(now=1001.0)["streamer"] == "JeGr"   # others untouched
    assert hs.pending() == {"raceControl"}


def t_override_expires_back_to_sheet_truth():
    hs = _hs()
    hs.set_override("raceControl", "Formation Lap", now=1000.0)
    assert hs.data(now=1000.0 + m.OVERRIDE_TTL + 1)["raceControl"] == ""
    assert hs.pending() == set()


def t_override_cleared_when_sheet_confirms():
    hs = _hs()
    hs.set_override("streamer", "GT45", now=1000.0)
    confirmed = OVERLAY_CSV.replace(",Streamer,JeGr,", ",Streamer,GT45,")
    hs._fetch = lambda url, timeout=10: confirmed if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    assert hs.pending() == set()
    assert hs.data(now=1001.0)["streamer"] == "GT45"


def t_override_survives_unconfirmed_refresh():
    hs = _hs()   # sheet still says JeGr
    hs.set_override("streamer", "GT45", now=1000.0)
    hs.refresh()                                       # poll without the new value yet
    assert hs.data(now=1001.0)["streamer"] == "GT45"   # echo still pending
    assert hs.pending() == {"streamer"}
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_hud.py`
Expected: `AttributeError ... set_override`

- [ ] **Step 3: Implement**

Module-level constant above `HudSource`:

```python
OVERRIDE_TTL = 30  # s: unconfirmed panel write -> HUD falls back to sheet truth
```

In `HudSource.__init__`: add `self.overrides = {}   # hud-data key -> (value, expires_ts)`.

New methods + a change to `data()`:

```python
    def set_override(self, key, value, now=None):
        """Optimistic echo for a panel write: /hud/data shows the value NOW;
        the sheet poll confirms (clears) it, or it expires after OVERRIDE_TTL."""
        now = time.time() if now is None else now
        with self.lock:
            self.overrides[key] = (value, now + OVERRIDE_TTL)

    def pending(self):
        with self.lock:
            return set(self.overrides)

    def data(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.overrides = {k: (v, exp) for k, (v, exp) in self.overrides.items()
                              if exp > now}
            base = self._data if self._data is not None else dict(self.EMPTY)
            if not self.overrides:
                return base
            out = dict(base)
            out.update({k: v for k, (v, _exp) in self.overrides.items()})
            return out
```

In `refresh()`, inside the `with self.lock:` block right after `self._data = data` / `self._vocab = vocab`:

```python
            # a sheet poll that already shows the pushed value = confirmation
            self.overrides = {k: (v, exp) for k, (v, exp) in self.overrides.items()
                              if data.get(k) != v}
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_hud.py && python3 tools/lint.py`
Expected: ALL PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hud.py src/relay/iro-feeds.py
git commit -m "feat(relay): optimistic per-field HUD overrides with confirm/expiry"
```

---

### Task 5: `ScheduleSource` keeps row names

`/schedule/data` shows name + URL per stint. Add `_parse_rows` returning `(url, name)` tuples (name = the cell right of the detected URL column); `_parse_csv` stays as a URL-only wrapper so `tests/test_pov.py` and all feed logic stay untouched.

**Files:**
- Modify: `tests/test_setup.py`
- Modify: `src/relay/iro-feeds.py` (`ScheduleSource`, lines 696-794)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup.py`:

```python
# ---------- schedule rows (url + name) ----------

SCHED_CSV = ('"https://www.youtube.com/watch?v=abc",Matt\n'
             '"UCLA_DiR1FfKNvjuUpBHmylQ",NASA\n'
             '"UCoMdktPbSTixAyNGwb-UYkQ"\n')


def t_parse_rows_url_and_name():
    rows = m.ScheduleSource._parse_rows(SCHED_CSV)
    assert rows == [("https://www.youtube.com/watch?v=abc", "Matt"),
                    ("UCLA_DiR1FfKNvjuUpBHmylQ", "NASA"),
                    ("UCoMdktPbSTixAyNGwb-UYkQ", "")], rows


def t_parse_rows_empty_is_none():
    assert m.ScheduleSource._parse_rows("url\n\n") is None


def t_parse_csv_still_returns_urls():
    items = m.ScheduleSource._parse_csv(SCHED_CSV)
    assert items[0] == "https://www.youtube.com/watch?v=abc"
    assert len(items) == 3


def t_schedule_source_get_rows():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    s = m.ScheduleSource("http://sched", _os.path.join(d, "cache.txt"), None)
    s.fetch = lambda timeout=15: m.ScheduleSource._parse_rows(SCHED_CSV)
    assert s.refresh() is True
    assert s.get() == ["https://www.youtube.com/watch?v=abc",
                       "UCLA_DiR1FfKNvjuUpBHmylQ", "UCoMdktPbSTixAyNGwb-UYkQ"]
    assert s.get_rows()[1] == ("UCLA_DiR1FfKNvjuUpBHmylQ", "NASA")
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_setup.py`
Expected: `AttributeError ... _parse_rows`

- [ ] **Step 3: Implement**

In `ScheduleSource.__init__`: add `self.rows = []` next to `self.items = []`.

Replace `_parse_csv` (lines 707-722) with:

```python
    @staticmethod
    def _parse_rows(text):
        """CSV -> [(url, name)] rows. The URL column is auto-detected (most
        cells matching is_channel); the name is the cell right of it."""
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return None
        ncols = max((len(r) for r in rows), default=0)
        best_col, best_cnt = None, 0
        for c in range(ncols):
            cnt = sum(1 for r in rows if len(r) > c and is_channel(r[c]))
            if cnt > best_cnt:
                best_cnt, best_col = cnt, c
        if best_col is None or best_cnt == 0:
            return None
        out = [(r[best_col].strip(),
                (r[best_col + 1].strip() if len(r) > best_col + 1 else ""))
               for r in rows if len(r) > best_col and is_channel(r[best_col])]
        return out or None

    @staticmethod
    def _parse_csv(text):
        rows = ScheduleSource._parse_rows(text)
        return [u for u, _n in rows] if rows else None
```

`fetch()` (lines 724-739): change `items = self._parse_csv(text)` to `items = self._parse_rows(text)` (the error message stays).

`refresh()` (lines 741-754): the fetch result is now rows:

```python
    def refresh(self, timeout=15):
        rows = self.fetch(timeout)
        if rows:
            with self.lock:
                self.rows = rows
                self.items = [u for u, _n in rows]
                self.last_ok = time.time()
                self.last_error = None
            try:
                with open(self.cache_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(self.get()) + "\n")
            except Exception:
                pass  # cache write is best-effort; the in-memory schedule is current
            return True
        return False
```

`load_initial()` fallback branch — after `self.items = items` add `self.rows = [(u, "") for u in items]` (cache/local files carry URLs only).

New accessor next to `get()`:

```python
    def get_rows(self):
        with self.lock:
            return list(self.rows)
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_setup.py && python3 tests/test_pov.py && python3 tools/lint.py`
Expected: ALL PASS (test_pov untouched and green), lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_setup.py src/relay/iro-feeds.py
git commit -m "feat(relay): schedule rows keep the name column for /schedule/data"
```

---

### Task 6: `SetupControl` — the write logic

One class owning the panel writes: setup fields (validate against vocabulary → optimistic override → background push → immediate confirm-poll), schedule rows + POV URL (synchronous push). Mirrors `TimerStore`'s `push_status` diagnostics.

**Files:**
- Modify: `tests/test_setup.py`
- Modify: `src/relay/iro-feeds.py` (new class after `HudSource`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup.py` (note: `_hs_stub` builds a real `HudSource` with stubbed fetch — same pattern as `tests/test_hud.py`; pushes are tested by stubbing module-level `post_webhook`):

```python
# ---------- SetupControl ----------

OVERLAY_CSV = (",Stint,Intro,,,,,,,\n,Streamer,JeGr,,,,,,,\n"
               ",Session,Warmup,,,,,,,\n,Race Control,,,,,,,,\n")
CONFIG_CSV = ("Stints,Streamers,Session,Race Control,Teams,Brand Name\n"
              "Stint 1,JeGr,Qualifier,Formation Lap,T #1,Porsche\n"
              "Stint 2,GT45,Race,Final Lap,T #2,BMW\n")


def _hs_stub():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    hs._fetch = lambda url, timeout=10: OVERLAY_CSV if url == "http://overlay" else CONFIG_CSV
    hs.refresh()
    return hs


def _ctl(pushes, response=b'{"ok": true, "action": "%s", "v": 2}'):
    hs = _hs_stub()
    ctl = m.SetupControl("http://push", hs)
    def fake_post(url, payload, timeout=10):
        pushes.append(payload)
        return response % payload["action"].encode() if b"%s" in response else response
    m.post_webhook, orig = fake_post, m.post_webhook
    return ctl, hs, orig


def t_set_field_unknown_field_and_value():
    ctl = m.SetupControl("http://push", _hs_stub())
    assert "error" in ctl.set_field("nope", "x")
    assert "error" in ctl.set_field("streamer", "Not In Vocab")
    assert "error" in ctl.set_field("streamer", "")   # only racecontrol clears


def t_set_field_requires_webhook():
    r = m.SetupControl(None, _hs_stub()).set_field("streamer", "GT45")
    assert "error" in r and "webhook" in r["error"]


def t_set_field_sets_override_and_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.set_field("streamer", "GT45", now=1000.0)
        assert r.get("ok") and r.get("pending")
        assert hs.data(now=1001.0)["streamer"] == "GT45"   # echo immediate
        ctl._push_setup("Streamer", "GT45")                # the thread body, run sync
        assert pushes[-1] == {"action": "setup", "fields": {"Streamer": "GT45"}}
        assert ctl.push_status == "ok"
    finally:
        m.post_webhook = orig


def t_clear_racecontrol_allowed():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        r = ctl.set_field("racecontrol", "", now=1000.0)
        assert r.get("ok")
        ctl._push_setup("Race Control", "")
        assert pushes[-1]["fields"] == {"Race Control": ""}
    finally:
        m.post_webhook = orig


def t_v1_script_reported_outdated():
    pushes = []
    ctl, hs, orig = _ctl(pushes, response=b'{"ok": true}')   # no action echo
    try:
        ctl._push_setup("Streamer", "GT45")
        assert ctl.push_status == "failed"
        assert "outdated" in ctl.last_error
    finally:
        m.post_webhook = orig


def t_schedule_set_validates_and_pushes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    try:
        assert "error" in ctl.schedule_set("x", url="https://youtu.be/a")
        assert "error" in ctl.schedule_set(0, url="https://youtu.be/a")
        assert "error" in ctl.schedule_set(1, url="not a url")
        r = ctl.schedule_set(2, url="https://www.youtube.com/watch?v=x", name="Matt")
        assert r.get("ok"), r
        assert pushes[-1] == {"action": "schedule", "row": 2,
                              "url": "https://www.youtube.com/watch?v=x", "name": "Matt"}
    finally:
        m.post_webhook = orig


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


def t_setup_data_shape():
    ctl = m.SetupControl(None, _hs_stub())
    d = ctl.data()
    assert d["fields"] == {"stint": "Intro", "streamer": "JeGr",
                           "session": "Warmup", "racecontrol": ""}
    assert d["options"]["racecontrol"] == ["Formation Lap", "Final Lap"]
    assert d["pending"] == [] and d["push"] == "disabled"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_setup.py`
Expected: `AttributeError ... SetupControl`

- [ ] **Step 3: Implement**

In `src/relay/iro-feeds.py`, after `HudSource`:

```python
# Panel setup fields: URL segment -> (Setup-tab header, /hud/data key).
# NOTE: the Setup "Stint" is the HUD display LABEL — it has no relationship
# to the relay's feed stint index (/set/stint, NEXT).
SETUP_FIELDS = {
    "stint": ("Stint", "stint"),
    "streamer": ("Streamer", "streamer"),
    "session": ("Session", "session"),
    "racecontrol": ("Race Control", "raceControl"),
}


class SetupControl:
    """Panel -> sheet writes (spec: panel-sheet-control). Setup fields are
    async-optimistic (override now, push in the background, the sheet poll
    confirms); Schedule/POV URL writes are synchronous (no local echo target,
    and answering after the webhook confirm removes the save-vs-RELOAD race).
    The sheet stays authoritative throughout."""

    def __init__(self, push_url, hud_source):
        self.push_url = push_url
        self.hud = hud_source
        self.push_status = "disabled" if not push_url else "never"
        self.last_error = None

    # -- shared blocking push -> (ok, error); diagnostics like TimerStore ----
    def _push(self, payload, expected_action):
        try:
            body = post_webhook(self.push_url, payload)
        except Exception as e:
            self.push_status = "failed"
            self.last_error = f"push: {type(e).__name__}: {e}"
            return False, self.last_error
        ok, err = check_webhook_response(body, expected_action)
        self.push_status = "ok" if ok else "failed"
        self.last_error = None if ok else err
        return ok, err

    # -- setup fields (async-optimistic) -------------------------------------
    def set_field(self, key, value, now=None):
        if key not in SETUP_FIELDS:
            return {"error": f"unknown field: {key!r} "
                             f"(one of {', '.join(sorted(SETUP_FIELDS))})"}
        if not self.push_url:
            return {"error": "webhook not configured — set IRO_SHEET_PUSH_URL "
                             "in .env (wiki: Sheet-Webhook)"}
        header, hud_key = SETUP_FIELDS[key]
        if not value and key != "racecontrol":
            return {"error": "empty value only allowed for racecontrol"}
        if value and value not in self.hud.vocab().get(key, []):
            return {"error": f"not in the Configuration vocabulary: {value!r} "
                             "(add it to the Configuration tab first)"}
        self.hud.set_override(hud_key, value, now)
        threading.Thread(target=self._push_setup, args=(header, value),
                         daemon=True).start()
        return {"ok": True, "field": key, "value": value, "pending": True}

    def _push_setup(self, header, value):
        ok, _err = self._push({"action": "setup", "fields": {header: value}},
                              "setup")
        if ok:
            self.hud.refresh()   # confirm now, not at the next poll tick

    # -- URL writes (synchronous) --------------------------------------------
    def schedule_set(self, row, url=None, name=None):
        if not self.push_url:
            return {"error": "webhook not configured — set IRO_SHEET_PUSH_URL "
                             "in .env (wiki: Sheet-Webhook)"}
        try:
            row = int(row)
        except (TypeError, ValueError):
            return {"error": "row must be a number (1-based)"}
        if row < 1:
            return {"error": "row must be >= 1"}
        payload = {"action": "schedule", "row": row}
        if url is not None:
            url = url.strip()
            if url and not is_channel(url):
                return {"error": "url must be a watch URL or UC… channel ID"}
            payload["url"] = url
        if name is not None:
            payload["name"] = name.strip()
        ok, err = self._push(payload, "schedule")
        return {"ok": True, "row": row} if ok else {"error": err}

    def pov_set(self, url):
        if not self.push_url:
            return {"error": "webhook not configured — set IRO_SHEET_PUSH_URL "
                             "in .env (wiki: Sheet-Webhook)"}
        url = (url or "").strip()
        if url and not is_channel(url):
            return {"error": "url must be a watch URL or UC… channel ID"}
        ok, err = self._push({"action": "pov", "url": url}, "pov")
        return {"ok": True} if ok else {"error": err}

    # -- panel poll ------------------------------------------------------------
    def data(self):
        hud = self.hud.data()
        pending = self.hud.pending()
        return {"fields": {k: hud.get(hk, "") for k, (_h, hk) in SETUP_FIELDS.items()},
                "options": self.hud.vocab(),
                "pending": sorted(k for k, (_h, hk) in SETUP_FIELDS.items()
                                  if hk in pending),
                "push": self.push_status,
                "last_error": self.last_error}
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_setup.py && python3 tools/lint.py`
Expected: ALL PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_setup.py src/relay/iro-feeds.py
git commit -m "feat(relay): SetupControl — validated sheet writes for the panel"
```

---

### Task 7: HTTP endpoints — `do_GET` additions + new `do_POST`

`/setup/data`, `/setup/set/<field>/<value>` (URL-encoded), `/setup/clear/<field>`, `/schedule/data` (GET) and `/schedule/set`, `/pov/set` (POST JSON). Tested through a real `ThreadingHTTPServer` on an ephemeral port (stdlib, loopback only — CI-safe).

**Files:**
- Modify: `tests/test_setup.py`
- Modify: `src/relay/iro-feeds.py` (`make_handler`, lines 1046-1134)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup.py`:

```python
# ---------- endpoint routing (real server, ephemeral port) ----------

def _client(setup_ctl):
    import json as _json, threading as _t, urllib.error
    from urllib.request import urlopen, Request

    class _StubFeed:
        def __init__(self, idx): self.idx = idx

    class _StubSource:
        def __init__(self, rows): self._rows = rows
        def get_rows(self): return list(self._rows)
        def health(self): return {"count": len(self._rows),
                                  "last_ok_age_s": 0.0, "last_error": None}

    class _StubRelay:
        def __init__(self):
            self.source = _StubSource([("https://www.youtube.com/watch?v=a", "Alpha"),
                                       ("UCLA_DiR1FfKNvjuUpBHmylQ", "Beta")])
            self.feeds = {"A": _StubFeed(0), "B": _StubFeed(1)}
        def status(self): return {"schedule_len": 2, "feeds": {}}

    handler = m.make_handler(_StubRelay(), setup_ctl=setup_ctl)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def _read(req):
        # error endpoints answer 404 etc. with a JSON body -> read it either way
        try:
            with urlopen(req, timeout=5) as r:
                return _json.loads(r.read())
        except urllib.error.HTTPError as e:
            return _json.loads(e.read())

    def get(path):
        return _read(base + path)

    def post(path, body):
        return _read(Request(base + path, data=_json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"},
                             method="POST"))

    return srv, get, post


def t_endpoints_setup_data_and_set():
    ctl = m.SetupControl(None, _hs_stub())   # push disabled -> set errors cleanly
    srv, get, post = _client(ctl)
    try:
        d = get("/setup/data")
        assert d["fields"]["streamer"] == "JeGr" and d["push"] == "disabled"
        r = get("/setup/set/streamer/GT45")
        assert "webhook not configured" in r["error"]
        r = get("/setup/clear/racecontrol")
        assert "webhook not configured" in r["error"]
        assert "error" in get("/setup/bogus")
    finally:
        srv.shutdown()


def t_endpoints_setup_set_urlencoded_value():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    srv, get, post = _client(ctl)
    try:
        r = get("/setup/set/racecontrol/Formation%20Lap")
        assert r.get("ok") and r["value"] == "Formation Lap", r
    finally:
        srv.shutdown(); m.post_webhook = orig


def t_endpoints_schedule_data_marks_live():
    ctl = m.SetupControl(None, _hs_stub())
    srv, get, post = _client(ctl)
    try:
        d = get("/schedule/data")
        assert d["rows"][0] == {"row": 1, "url": "https://www.youtube.com/watch?v=a",
                                "name": "Alpha", "live": "A"}
        assert d["rows"][1]["live"] == "B"
    finally:
        srv.shutdown()


def t_endpoints_post_writes():
    pushes = []
    ctl, hs, orig = _ctl(pushes)
    srv, get, post = _client(ctl)
    try:
        r = post("/schedule/set", {"row": 1, "url": "https://youtu.be/x", "name": "N"})
        assert r.get("ok"), r
        assert pushes[-1]["action"] == "schedule"
        r = post("/pov/set", {"url": "https://youtu.be/p"})
        assert r.get("ok"), r
        assert pushes[-1]["action"] == "pov"
        assert "error" in post("/pov/bogus", {})
    finally:
        srv.shutdown(); m.post_webhook = orig


def t_endpoints_post_rejects_bad_json():
    import urllib.error
    from urllib.request import urlopen, Request
    ctl = m.SetupControl(None, _hs_stub())
    srv, get, post = _client(ctl)
    try:
        req = Request(f"http://127.0.0.1:{srv.server_address[1]}/pov/set",
                      data=b"not json", method="POST")
        try:
            urlopen(req, timeout=5)
            raise AssertionError("expected HTTP 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 tests/test_setup.py`
Expected: TypeError (`make_handler` has no `setup_ctl` parameter).

- [ ] **Step 3: Implement**

`make_handler` signature (line 1046) gains the new dependency:

```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, timer_path=None, setup_ctl=None):
```

Add `unquote` to the existing `urllib.parse` import at the top of the file.

In `do_GET`, after the `/timer` block (line 1119) and before `/next`:

```python
                if p[:1] == ["setup"]:
                    if not setup_ctl:
                        return self._send({"error": "setup control disabled"}, 404)
                    if p == ["setup", "data"]:
                        return self._send(setup_ctl.data())
                    if len(p) == 4 and p[1] == "set":
                        return self._send(setup_ctl.set_field(p[2].lower(),
                                                              unquote(p[3])))
                    if len(p) == 3 and p[1] == "clear":
                        return self._send(setup_ctl.set_field(p[2].lower(), ""))
                    return self._send({"error": "unknown", "path": self.path}, 404)
                if p == ["schedule", "data"]:
                    rows = relay.source.get_rows()
                    live = {f.idx: k for k, f in relay.feeds.items()}
                    return self._send({"rows": [{"row": i + 1, "url": u, "name": n,
                                                 "live": live.get(i)}
                                                for i, (u, n) in enumerate(rows)],
                                       "source": relay.source.health()})
```

New `do_POST` method on the handler class (next to `do_GET`):

```python
        def do_POST(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 65536:
                    return self._send({"error": "body too large"}, 413)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send({"error": "body must be JSON"}, 400)
                if not isinstance(body, dict):
                    return self._send({"error": "body must be a JSON object"}, 400)
                if not setup_ctl:
                    return self._send({"error": "setup control disabled"}, 404)
                if p == ["schedule", "set"]:
                    return self._send(setup_ctl.schedule_set(
                        body.get("row"), body.get("url"), body.get("name")))
                if p == ["pov", "set"]:
                    return self._send(setup_ctl.pov_set(body.get("url")))
                return self._send({"error": "unknown", "path": self.path}, 404)
            except Exception as e:
                return self._send({"error": str(e)}, 500)
```

- [ ] **Step 4: Run tests + lint**

Run: `python3 tests/test_setup.py && python3 tools/lint.py`
Expected: ALL PASS, lint clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_setup.py src/relay/iro-feeds.py
git commit -m "feat(relay): /setup, /schedule, /pov sheet-control endpoints"
```

---

### Task 8: Wire `SetupControl` into `main()`

**Files:**
- Modify: `src/relay/iro-feeds.py` (main, lines 1324-1416)

- [ ] **Step 1: Implement the wiring**

Read the push URL once and share it (replaces the inline `os.environ.get` from Task 1):

```python
    # One sheet-write webhook powers the race timer AND the panel's
    # Setup/Schedule/POV controls (wiki: Sheet-Webhook).
    push_url = os.environ.get("IRO_SHEET_PUSH_URL")
```

Pass it to `TimerStore` (line ~1333): `timer_store = TimerStore(timer_csv, push_url, ...)`.

After the timer block, create the control (needs the HUD source for vocabulary + overrides — without `hud_source` the setup endpoints stay 404/disabled):

```python
    setup_ctl = SetupControl(push_url, hud_source) if hud_source else None
```

Pass it to the handler (line ~1364):

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, timer_path, setup_ctl)
```

In the startup prints, after the HUD line (~1409), add:

```python
    if setup_ctl:
        mode = "writes ON" if push_url else "read-only (set IRO_SHEET_PUSH_URL)"
        print(f"  Panel sheet controls (/setup /schedule /pov/set): {mode}")
```

- [ ] **Step 2: Smoke-check startup wiring**

Run: `python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('f', 'src/relay/iro-feeds.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ctl = m.SetupControl(None, None)
print('push:', ctl.push_status)"`
Expected: `push: disabled` (module loads, class constructs).

- [ ] **Step 3: Run the full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: ALL TEST FILES PASS, lint clean.

- [ ] **Step 4: Commit**

```bash
git add src/relay/iro-feeds.py
git commit -m "feat(relay): wire SetupControl into the control server"
```

---

### Task 9: Panel UI — SETUP row + URLS section

All-JS additions to the existing vision-mixer layout. No unit tests (the panel has none by convention) — verification is manual against a running relay.

**Files:**
- Modify: `src/director/director-panel.html`

- [ ] **Step 1: Add CSS** (inside the existing `<style>`, after the `.hint` rule, line ~117)

```css
  /* ---------- setup dropdowns (sheet-backed) ---------- */
  .setrow{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
  .fld select{background:#0c0f13;border:1px solid var(--edge);color:var(--ink);
    font-family:var(--mono);font-size:13px;padding:10px 12px;border-radius:9px;
    min-width:150px;outline:none}
  .fld select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(58,160,255,.18)}
  .fld select.pending{border-color:var(--amber);box-shadow:0 0 0 3px var(--amber-glow)}
  .fld select:disabled{opacity:.45}

  /* ---------- URLs section ---------- */
  details.urls{display:block}
  details.urls summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;
    font-family:var(--head);font-weight:700;letter-spacing:.12em;font-size:14px;text-transform:uppercase}
  details.urls summary::before{content:"";width:6px;height:16px;background:var(--amber);
    border-radius:2px;box-shadow:0 0 10px var(--amber-glow)}
  details.urls summary::after{content:"▸";color:var(--muted);margin-left:4px}
  details.urls[open] summary::after{content:"▾"}
  .urls table{width:100%;border-collapse:collapse;margin-top:10px;font-size:12px}
  .urls td{padding:4px 6px;vertical-align:middle}
  .urls td.rn{width:54px;color:var(--muted);white-space:nowrap}
  .urls .livebadge{display:inline-block;margin-left:5px;padding:1px 6px;border-radius:6px;
    font-size:10px;font-weight:600;color:var(--air);border:1px solid var(--air)}
  .urls .livebadge:empty{display:none}
  .urls input{width:100%;background:#0c0f13;border:1px solid var(--edge);color:var(--ink);
    font-family:var(--mono);font-size:12px;padding:7px 9px;border-radius:8px;outline:none}
  .urls input:focus{border-color:var(--blue)}
  .urls td.act{width:84px}
  .urls .save,.urls .add{padding:7px 10px;font-size:11px;letter-spacing:.1em;border-radius:8px;
    border:1px solid var(--edge);background:#141921;color:var(--muted);cursor:pointer;width:100%}
  .urls .save.ok{border-color:var(--live);color:var(--live)}
  .urls .add{width:auto;margin-top:8px}
```

- [ ] **Step 2: Add the markup**

Between the FEEDS and SCN·VIS sections (after line 161):

```html
  <section class="bus"><div class="cap">Setup</div>
    <div class="body">
      <div class="setrow" id="setupRow"></div>
      <div class="hint" id="setupInfo">Setup: connecting to relay…</div>
    </div>
  </section>
```

Between the AUDIO section and the `#log` div (after line 174):

```html
  <details class="bus urls" id="urlsBox">
    <summary>URLs · Schedule + POV</summary>
    <div class="body">
      <table><tbody id="schedBody"></tbody></table>
      <button class="add" id="schedAdd">+ ADD ROW</button>
      <table><tbody>
        <tr><td class="rn">POV</td>
            <td><input id="povUrl" placeholder="https://www.youtube.com/watch?v=… or UC…"></td>
            <td class="act"><button class="save" id="povSave">SAVE</button></td></tr>
      </tbody></table>
      <div class="hint">Saves write the Google Sheet only — a feed picks the new URL up
        on RELOAD A/B / NEXT (rows marked <b>A</b>/<b>B</b> are live now); the POV URL
        applies on POV RELOAD. Names/URLs can still be edited in the Sheet directly.</div>
    </div>
  </details>
```

- [ ] **Step 3: Add the JS** (before the `/* ---------- boot ---------- */` block, line ~575)

```js
/* ---------- SETUP row (sheet-backed dropdowns; relay-only) ----------
   The "STINT" here is the HUD display LABEL (Setup tab) — unrelated to the
   feed stint index handled by NEXT / SET STINT in the FEEDS row. */
const SETUP_FIELDS = [
  ["stint","STINT (HUD LABEL)"], ["streamer","STREAMER"],
  ["session","SESSION"], ["racecontrol","RACE CONTROL"],
];
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
SETUP_FIELDS.forEach(([key,label])=>{
  const w = document.createElement("div"); w.className = "fld";
  w.innerHTML = `<label>${label}</label><select data-setup="${key}" disabled></select>`;
  w.querySelector("select").addEventListener("change", e=>setupSet(key, e.target.value));
  $("#setupRow").appendChild(w);
});
{ const b = document.createElement("button");
  b.className = "pill stop"; b.textContent = "CLEAR RC";
  b.addEventListener("click", ()=>setupSet("racecontrol",""));
  $("#setupRow").appendChild(b); }

async function setupSet(field, value){
  const path = value === "" ? "setup/clear/" + field
                            : "setup/set/" + field + "/" + encodeURIComponent(value);
  try{
    const r = await fetch("/" + path, {cache:"no-store"});
    const d = await r.json();
    if (d.error){ log("Setup " + field + ": " + d.error, "err"); setupPoll(); return; }
    log("Setup " + field + " → " + (value || "(cleared)"));
    setupPoll();
  }catch(e){ log("Setup " + field + " failed (relay reachable?): " + e, "err"); }
}

async function setupPoll(){
  let d;
  try{
    const r = await fetch("/setup/data", {cache:"no-store"});
    d = await r.json();
  }catch(e){ $("#setupInfo").textContent = "Setup: relay not reachable."; return; }
  if (d.error){ $("#setupInfo").textContent = "Setup: " + d.error; return; }
  const ro = d.push === "disabled";
  for (const [key] of SETUP_FIELDS){
    const sel = document.querySelector(`select[data-setup="${key}"]`);
    if (!sel || sel === document.activeElement) continue;   // never yank an open menu
    const opts = (key === "racecontrol" ? [""] : []).concat(d.options[key] || []);
    const sig = JSON.stringify(opts);
    if (sel.dataset.sig !== sig){
      sel.innerHTML = opts.map(o=>`<option value="${escapeHtml(o)}">${o===""?"— none —":escapeHtml(o)}</option>`).join("");
      sel.dataset.sig = sig;
    }
    const cur = d.fields[key] || "";
    if ([...sel.options].some(o=>o.value===cur)) sel.value = cur;
    sel.classList.toggle("pending", d.pending.includes(key));
    sel.disabled = ro;
  }
  $("#setupInfo").textContent = "Setup: " +
      (d.push === "ok" ? "sheet sync OK"
     : ro ? "read-only — set IRO_SHEET_PUSH_URL in .env (wiki: Sheet-Webhook)"
     : d.push === "failed" ? "SHEET SYNC FAILED — " + (d.last_error || "see relay log")
     : "sheet sync not yet attempted");
}

/* ---------- URLs section (Schedule rows + POV; sheet writes, no reloads) -- */
const SAVE_GUARD_MS = 30000;   // a just-saved value wins over a stale CSV poll
function rowBusy(tr){
  return tr.dataset.dirty ||
         tr.contains(document.activeElement) ||
         Date.now() - Number(tr.dataset.saved||0) < SAVE_GUARD_MS;
}
function schedRow(i){
  let tr = document.querySelector(`#schedBody tr[data-row="${i}"]`);
  if (tr) return tr;
  tr = document.createElement("tr"); tr.dataset.row = i;
  tr.innerHTML = `<td class="rn">${i}<span class="livebadge"></span></td>
    <td style="width:24%"><input class="nm" placeholder="name"></td>
    <td><input class="u" placeholder="https://www.youtube.com/watch?v=… or UC…"></td>
    <td class="act"><button class="save">SAVE</button></td>`;
  tr.querySelectorAll("input").forEach(inp=>inp.addEventListener("input", ()=>tr.dataset.dirty = 1));
  tr.querySelector(".save").addEventListener("click", ()=>schedSave(tr, i));
  $("#schedBody").appendChild(tr);
  return tr;
}
async function schedSave(tr, row){
  const btn = tr.querySelector(".save");
  btn.disabled = true; btn.textContent = "…"; btn.classList.remove("ok");
  try{
    const r = await fetch("/schedule/set", {method:"POST", cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({row, url: tr.querySelector(".u").value.trim(),
                            name: tr.querySelector(".nm").value.trim()})});
    const d = await r.json();
    if (d.error){ log("Schedule row " + row + ": " + d.error, "err"); btn.textContent = "RETRY"; return; }
    delete tr.dataset.dirty; tr.dataset.saved = Date.now();
    btn.textContent = "SAVED ✓"; btn.classList.add("ok");
    const live = tr.querySelector(".livebadge").textContent;
    log("Schedule row " + row + " saved" +
        (live ? ` — feed ${live} picks it up on RELOAD ${live} / NEXT` : ""));
  }catch(e){ log("Schedule save failed: " + e, "err"); btn.textContent = "RETRY"; }
  finally{
    btn.disabled = false;
    setTimeout(()=>{ if (btn.textContent === "SAVED ✓"){ btn.textContent = "SAVE"; btn.classList.remove("ok"); } }, 4000);
  }
}
$("#schedAdd").addEventListener("click", ()=>{
  const next = document.querySelectorAll("#schedBody tr").length + 1;
  const tr = schedRow(next); tr.dataset.dirty = 1;
  tr.querySelector(".nm").focus();
});
$("#povSave").addEventListener("click", async ()=>{
  const btn = $("#povSave");
  btn.disabled = true; btn.textContent = "…"; btn.classList.remove("ok");
  try{
    const r = await fetch("/pov/set", {method:"POST", cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({url: $("#povUrl").value.trim()})});
    const d = await r.json();
    if (d.error){ log("POV URL: " + d.error, "err"); btn.textContent = "RETRY"; return; }
    delete $("#povUrl").dataset.dirty; $("#povUrl").dataset.saved = Date.now();
    btn.textContent = "SAVED ✓"; btn.classList.add("ok");
    log("POV URL saved — applies on POV RELOAD.");
  }catch(e){ log("POV save failed: " + e, "err"); btn.textContent = "RETRY"; }
  finally{
    btn.disabled = false;
    setTimeout(()=>{ if (btn.textContent === "SAVED ✓"){ btn.textContent = "SAVE"; btn.classList.remove("ok"); } }, 4000);
  }
});
$("#povUrl").addEventListener("input", ()=>$("#povUrl").dataset.dirty = 1);

async function schedPoll(){
  if (!$("#urlsBox").open) return;   // closed section -> no traffic
  try{
    const r = await fetch("/schedule/data", {cache:"no-store"});
    const d = await r.json();
    if (d.error) return;
    d.rows.forEach(row=>{
      const tr = schedRow(row.row);
      tr.querySelector(".livebadge").textContent = row.live || "";
      if (rowBusy(tr)) return;
      tr.querySelector(".nm").value = row.name;
      tr.querySelector(".u").value = row.url;
    });
  }catch(e){}
  try{
    const r = await fetch("/status", {cache:"no-store"});
    const d = await r.json();
    const inp = $("#povUrl");
    if (d.pov && !inp.dataset.dirty && inp !== document.activeElement &&
        Date.now() - Number(inp.dataset.saved||0) > SAVE_GUARD_MS)
      inp.value = d.pov.url || "";
  }catch(e){}
}
$("#urlsBox").addEventListener("toggle", ()=>schedPoll());
```

In the boot block (lines 576-579), add the two pollers:

```js
setupPoll(); setInterval(setupPoll, 2000);
setInterval(schedPoll, 2000);
```

- [ ] **Step 4: Manual verification against a running relay**

Run: `python3 src/iro.py relay run` (needs `.env` with `IRO_SHEET_ID`; `IRO_SHEET_PUSH_URL` optional), open `http://127.0.0.1:8088/panel`:
- SETUP row shows four dropdowns populated from the Configuration tab; without `IRO_SHEET_PUSH_URL` they are disabled with the read-only hint.
- With the webhook configured: changing RACE CONTROL shows the amber pending outline, `/hud` updates instantly, the Setup tab cell updates in the sheet, the outline clears within a few seconds.
- URLS section: rows match the Schedule tab with A/B badges on the live stints; saving a row updates the sheet; the saved value does not get overwritten by the next poll; POV save writes POV!A2. No feed reconnects on any save.
- Stop the relay (Ctrl+C).

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): SETUP dropdowns + Schedule/POV URL editing"
```

---

### Task 10: Apps Script v2 + `Sheet-Webhook.md` wiki page

The webhook script moves out of `Race-Timer.md` into its own page with the v2 listing; Race-Timer links there. The script is documentation (deployed by hand into the sheet), so exactness matters — copy it verbatim.

**Files:**
- Create: `src/docs/wiki/Sheet-Webhook.md`
- Modify: `src/docs/wiki/Race-Timer.md` (lines 43-90, the "One-time setup" section)
- Modify: `src/docs/wiki/_Sidebar.md`

- [ ] **Step 1: Create `src/docs/wiki/Sheet-Webhook.md`**

````markdown
# Sheet-Webhook — the write path back into the Google Sheet

The relay reads the Sheet via CSV export (no key needed). Writing back —
race-timer sync and the director panel's Setup/Schedule/POV controls — goes
through **one** Google Apps Script web app deployed inside the broadcast
Sheet. One URL + key in `.env` powers all of it:

```
IRO_SHEET_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
```

Without it everything still works read-only: the timer stays local to one
machine and the panel's SETUP row + URLs section are display-only.

## What it writes

| Action (sent by the relay) | Sheet target |
|---|---|
| `timer` | Timer tab (race-timer state — see [Race-Timer](Race-Timer)) |
| `setup` | Setup tab: the cell **below** a header (`Stint`, `Streamer`, `Session`, `Race Control`) — found by text, so the tab layout may move |
| `schedule` | Schedule tab row N: URL (col A) + name (col B); row `last+1` appends |
| `pov` | POV tab cell `A2` |

The relay only sends Setup values that exist in the Configuration tab's
vocabulary columns — the same lists the sheet's own dropdowns use.

## One-time setup (per sheet)

1. Open the broadcast Google Sheet → **Extensions → Apps Script**.
2. Replace the editor contents with this script (set `KEY` to a random secret):

   ```javascript
   const KEY = 'change-me';            // must match the key=... in the URL below
   const TABS = {setup: 'Setup', schedule: 'Schedule', pov: 'POV', timer: 'Timer'};
   const SETUP_FIELDS = ['Stint', 'Streamer', 'Session', 'Race Control'];
   const TIMER_ROWS = {'Race End (UTC)': 1, 'Duration': 2, 'Visible': 3,
                       'Updated (UTC)': 4, 'Remaining': 5};

   function doPost(e) {
     const out = (o) => ContentService.createTextOutput(JSON.stringify(o))
         .setMimeType(ContentService.MimeType.JSON);
     if (((e.parameter && e.parameter.key) || '') !== KEY) return out({error: 'bad key'});
     try {
       const p = JSON.parse(e.postData.contents);
       const ss = SpreadsheetApp.getActiveSpreadsheet();
       const action = p.action || 'timer';
       if (action === 'timer') writeTimer(ss, p);
       else if (action === 'setup') writeSetup(ss, p.fields || {});
       else if (action === 'schedule') writeSchedule(ss, p);
       else if (action === 'pov') writePov(ss, p);
       else return out({error: 'unknown action: ' + action});
       return out({ok: true, action: action, v: 2});
     } catch (err) { return out({error: String(err)}); }
   }

   function tab(ss, name) {
     const sheet = ss.getSheetByName(name);
     if (!sheet) throw 'tab not found: ' + name;
     return sheet;
   }

   function writeTimer(ss, p) {
     const sheet = ss.getSheetByName(TABS.timer) || ss.insertSheet(TABS.timer);
     const write = (label, value) => {
       sheet.getRange(TIMER_ROWS[label], 1).setValue(label);
       sheet.getRange(TIMER_ROWS[label], 2).setNumberFormat('@').setValue(value);
     };
     if ('end' in p) write('Race End (UTC)', p.end);
     if ('duration' in p) write('Duration', p.duration);
     if ('visible' in p) write('Visible', p.visible);
     if ('remaining' in p) write('Remaining', p.remaining);
     write('Updated (UTC)', new Date().toISOString());
   }

   function writeSetup(ss, fields) {
     // Locate every header first, then write — an unknown/renamed header
     // aborts the whole write with a clear error.
     const sheet = tab(ss, TABS.setup);
     const grid = sheet.getDataRange().getValues();
     const targets = {};
     Object.keys(fields).forEach((name) => {
       if (SETUP_FIELDS.indexOf(name) === -1) throw 'unknown setup field: ' + name;
       let hit = null;
       for (let r = 0; r < grid.length && !hit; r++)
         for (let c = 0; c < grid[r].length && !hit; c++)
           if (String(grid[r][c]).trim().toLowerCase() === name.toLowerCase())
             hit = [r + 2, c + 1];          // the value cell sits BELOW the header
       if (!hit) throw 'header not found in Setup tab: ' + name;
       targets[name] = hit;
     });
     Object.keys(targets).forEach((name) => {
       sheet.getRange(targets[name][0], targets[name][1])
            .setNumberFormat('@').setValue(fields[name]);
     });
   }

   function writeSchedule(ss, p) {
     const sheet = tab(ss, TABS.schedule);
     const row = Number(p.row);
     const last = sheet.getLastRow();
     if (!row || row < 1 || row > last + 1) throw 'row out of range: ' + p.row;
     if ('url' in p) sheet.getRange(row, 1).setNumberFormat('@').setValue(p.url);
     if ('name' in p) sheet.getRange(row, 2).setNumberFormat('@').setValue(p.name);
   }

   function writePov(ss, p) {
     tab(ss, TABS.pov).getRange(2, 1).setNumberFormat('@').setValue(p.url || '');
   }
   ```

3. **Deploy → New deployment → Web app**, execute as **Me**, access:
   **Anyone**. Copy the `/exec` URL.
4. In `.env` on every producer machine:

   ```
   IRO_SHEET_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
   ```

5. Restart the relay. `iro event status` shows the `.env` check as PASS; the
   panel's Setup line reports `sheet sync OK` after the first action.

## Updating the script later

**Manage deployments → ✎ Edit → Version: New version → Deploy.** This keeps
the `/exec` URL — no `.env` change on any machine. (A *New deployment*
instead creates a NEW URL and every `.env` must be updated.)

The relay detects an outdated (v1, timer-only) script: panel writes then
report *"webhook script outdated — redeploy"* instead of failing silently.

## Security

The URL+key is a write credential for the Sheet — treat it like the other
`.env` secrets (never commit it). The endpoints the panel uses sit on the
relay's unauthenticated control server: the tailnet is the trust boundary,
same as all other `/panel` controls.
````

- [ ] **Step 2: Slim down `Race-Timer.md`**

Replace the whole "## One-time setup: the write webhook (optional but recommended)" section (lines 43-90, including the script listing) with:

```markdown
## One-time setup: the write webhook (optional but recommended)

Without it the timer still works on the producer machine, but Director actions
cannot sync to the Sheet — a takeover machine would not pick up the running
countdown. The timer shares the sheet-write webhook with the panel's
Setup/Schedule/POV controls — set it up once per sheet: see
**[Sheet-Webhook](Sheet-Webhook)**.
```

(The "Producer handover" section below it stays.)

- [ ] **Step 3: Add to `_Sidebar.md`** under "Technical reference", after the Race Timer line:

```markdown
- [Sheet-Webhook (write path)](Sheet-Webhook)
```

- [ ] **Step 4: Verify**

Run: `grep -rn "doPost" src/docs/wiki/ | cut -d: -f1 | sort -u`
Expected: only `src/docs/wiki/Sheet-Webhook.md`.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/Sheet-Webhook.md src/docs/wiki/Race-Timer.md src/docs/wiki/_Sidebar.md
git commit -m "docs(wiki): Sheet-Webhook page with the v2 write script"
```

---

### Task 11: Operator docs + CLAUDE.md

Document the new panel controls (mechanism only — no crew procedure) and register the new test file.

**Files:**
- Modify: `src/docs/wiki/Director.md`
- Modify: `src/docs/wiki/Configuration.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `src/docs/wiki/Director.md`** — read the page first, then add a section describing the two new panel areas, following its existing tone/structure. Content to convey (adapt wording to the page):

```markdown
## Setup row — HUD values without touching the Sheet

The SETUP row mirrors the Sheet's Setup-tab dropdowns: **Stint (HUD label)**,
**Streamer**, **Session**, **Race Control** (+ CLEAR RC). Options come from
the Configuration tab — new streamers or messages are added there, the panel
picks them up automatically. A change shows on the HUD immediately and is
written to the Sheet in the background (amber outline = write pending; the
Setup line shows the sync state). Editing the Sheet dropdowns directly still
works exactly as before.

> The STINT here is the *HUD display label*. Advancing the actual feeds is
> NEXT / SET STINT in the FEEDS row — two different things.

## URLs section — Schedule + POV

The collapsible URLs section edits the Schedule tab (per-stint name + URL,
rows marked A/B are live on a feed right now) and the POV URL. SAVE writes
the Sheet only — **no feed is ever reconnected automatically**: a changed URL
takes effect at the next RELOAD A/B / NEXT (POV: POV RELOAD), exactly as if
the Sheet had been edited directly.

Both areas need the sheet-write webhook ([Sheet-Webhook](Sheet-Webhook));
without it they are read-only.
```

- [ ] **Step 2: `src/docs/wiki/Configuration.md`** — extend the `IRO_SHEET_PUSH_URL` bullet (renamed in Task 1) to mention it powers the timer sync AND the panel Setup/Schedule/POV controls, and point to the Sheet-Webhook page for setup.

  Also skim `src/docs/wiki/Run-an-event.md`: if it walks the director through
  editing the Sheet for stint/streamer/race-control changes, add one sentence
  that these are also available on the panel's SETUP row (mechanism only — do
  not prescribe which to use).

- [ ] **Step 3: `CLAUDE.md`** — two edits:
  1. In the test-commands block, after the `test_timer.py` line:
     `python3 tests/test_setup.py          # panel sheet-control (webhook payloads, SetupControl, endpoints)`
  2. In the relay architecture section (after the HUD paragraph), add a short paragraph:

```markdown
The panel's **sheet controls** write back through one Apps Script webhook
(`IRO_SHEET_PUSH_URL`, shared with the race timer — wiki: Sheet-Webhook):
Setup fields (Stint label/Streamer/Session/Race Control) are async-optimistic
(`HudSource` override now, sheet poll confirms, 30 s expiry), Schedule/POV URL
writes are synchronous; URL changes never auto-reload a feed. Setup "Stint" =
HUD display label, NOT the feed stint index. `SetupControl` + endpoints
`/setup/*`, `/schedule/*`, `/pov/set` (POST). Tests: `tests/test_setup.py`.
```

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/Director.md src/docs/wiki/Configuration.md CLAUDE.md
git commit -m "docs: panel sheet controls (Director guide, Configuration, CLAUDE.md)"
```

---

### Task 12: Final verification

- [ ] **Step 1: Full suite + lint**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: ALL TEST FILES PASS, lint clean.

- [ ] **Step 2: Build with self-verify**

Run: `python3 tools/build.py`
Expected: build completes; the verify step passes (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 3: Stale-reference sweep**

Run: `grep -rn "IRO_TIMER_PUSH_URL" src/ tests/ tools/ .github/ CLAUDE.md .env.example README.md`
Expected: no output.

- [ ] **Step 4: Commit anything the build touched** (normally nothing — `dist/` is gitignored)

```bash
git status --short
```
Expected: clean tree.
