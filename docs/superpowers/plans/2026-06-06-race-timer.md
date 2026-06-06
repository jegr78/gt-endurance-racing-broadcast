# Relay-Hosted Race Timer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stagetimer.io browser source with a relay-hosted race countdown, controlled by the Director via `/panel` + Companion, whose state survives relay restarts and producer-machine handover (Sheet anchor + Apps Script webhook).

**Architecture:** All timer logic lives in `src/relay/iro-feeds.py` (HudSource precedent): pure functions (parse/format/mode/merge) + a `TimerStore` class (local `runtime/timer.json`, Sheet-tab CSV poll, webhook push, newest-wins merge). The existing control server gains `/timer*` routes; a new `src/obs/timer.html` browser-source page ticks client-side against the absolute end anchor. stagetimer (`__IRO_TIMER__` / `IRO_TIMER_URL`) is removed everywhere.

**Tech Stack:** Python stdlib only (project rule), vanilla HTML/JS for the page, Google Apps Script (copy-paste, documented) for the write path.

**Spec:** `docs/superpowers/specs/2026-06-06-race-timer-design.md`

---

## Locked data contracts (used by every task)

**In-memory / `runtime/timer.json` state dict:**
```python
{"end": 1781380800.0,    # epoch seconds UTC, or None = not started
 "duration": 21600,      # seconds (race length)
 "visible": True,
 "updated": 1781359198.0}  # epoch seconds of the last write (merge stamp)
```
Default state: `{"end": None, "duration": 21600, "visible": True, "updated": 0.0}`.

**Sheet tab `Timer`** (column A = label, column B = value):
`Race End (UTC)` (ISO string or empty), `Duration` (`H:MM:SS`), `Visible` (`TRUE`/`FALSE`), `Updated (UTC)` (ISO, written by Apps Script). Labels are matched case-insensitively; row order does not matter.

**`/timer/data` JSON:**
```json
{"visible": true, "end": 1781380800.0, "duration_s": 21600,
 "server_now": 1781359200.0, "mode": "running",
 "sync": {"push": "ok", "sheet_last_ok_age_s": 3.1, "last_error": null}}
```
`mode` ∈ `hidden | prestart | running | finished`. `sync.push` ∈ `disabled | ok | failed | never`.

**Webhook push body (POST, JSON; key travels in the URL):**
```json
{"end": "2026-06-13T20:00:00Z", "duration": "6:00:00", "visible": "TRUE"}
```
(`end` is `""` when not started. Every push writes the full state.)

**New optional `.env` var:** `IRO_TIMER_PUSH_URL` — the Apps Script `/exec` URL **including** its `?key=<shared secret>` query parameter. Unset ⇒ local-only mode (degraded, never an error).

---

### Task 1: Pure timer logic in the relay

**Files:**
- Modify: `src/relay/iro-feeds.py` (new functions after `build_hud_data`, ~line 320; add `datetime` to the import line 55)
- Create: `tests/test_timer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timer.py` (same loader pattern as `tests/test_hud.py`):

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the relay race timer. Run: python3 tests/test_timer.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_parse_duration():
    assert m.parse_duration("6:00:00") == 21600
    assert m.parse_duration("06:00:00") == 21600
    assert m.parse_duration("0:00:30") == 30
    assert m.parse_duration("24:00:00") == 86400
    assert m.parse_duration(" 1:02:03 ") == 3723
    for bad in ("", None, "90", "1:2", "1:60:00", "1:00:60", "abc", "-1:00:00"):
        assert m.parse_duration(bad) is None, bad


def t_format_duration():
    assert m.format_duration(21600) == "6:00:00"
    assert m.format_duration(3723) == "1:02:03"
    assert m.format_duration(0) == "0:00:00"
    assert m.format_duration(86400) == "24:00:00"


def t_parse_utc_ts():
    # canonical ISO, Apps Script toISOString (fractional), gviz-reformatted
    assert m.parse_utc_ts("2026-06-13T20:00:00Z") == 1781380800.0
    assert m.parse_utc_ts("2026-06-13T20:00:00.000Z") == 1781380800.0
    assert m.parse_utc_ts("2026-06-13 20:00:00") == 1781380800.0
    for bad in ("", None, "tomorrow", "2026-06-13", "20:00:00"):
        assert m.parse_utc_ts(bad) is None, bad


def t_iso_utc_roundtrip():
    assert m.iso_utc(1781380800.0) == "2026-06-13T20:00:00Z"
    assert m.parse_utc_ts(m.iso_utc(1781380800.0)) == 1781380800.0


TIMER_CSV = (
    "Race End (UTC),2026-06-13T20:00:00Z\n"
    "Duration,6:00:00\n"
    "Visible,FALSE\n"
    "Updated (UTC),2026-06-13T13:59:58Z\n"
)


def t_parse_timer_tab():
    st = m.parse_timer_tab(TIMER_CSV)
    assert st["end"] == 1781380800.0
    assert st["duration"] == 21600
    assert st["visible"] is False
    assert st["updated"] == 1781359198.0


def t_parse_timer_tab_defaults_and_garbage():
    # empty/missing values fall back to the default state fields; never throws
    st = m.parse_timer_tab("Race End (UTC),\nDuration,\nVisible,\n")
    assert st["end"] is None and st["duration"] == 21600
    assert st["visible"] is True and st["updated"] == 0.0
    st = m.parse_timer_tab("")
    assert st["end"] is None
    st = m.parse_timer_tab("garbage,x\nmore,y\n")
    assert st["end"] is None and st["visible"] is True
    # label match is case-insensitive; gviz may reformat the ISO timestamp
    st = m.parse_timer_tab("race end (utc),2026-06-13 20:00:00\n")
    assert st["end"] == 1781380800.0


def t_timer_mode():
    base = {"end": 1000.0, "duration": 21600, "visible": True, "updated": 0.0}
    assert m.timer_mode(dict(base, visible=False), 500.0) == "hidden"
    assert m.timer_mode(dict(base, end=None), 500.0) == "prestart"
    assert m.timer_mode(base, 500.0) == "running"
    assert m.timer_mode(base, 1000.0) == "finished"
    assert m.timer_mode(base, 2000.0) == "finished"
    # hidden wins over everything
    assert m.timer_mode(dict(base, end=None, visible=False), 0.0) == "hidden"


def t_merge_timer_states_newest_wins():
    local = {"end": 1.0, "duration": 60, "visible": True, "updated": 100.0}
    sheet = {"end": 2.0, "duration": 90, "visible": False, "updated": 200.0}
    assert m.merge_timer_states(local, sheet) == sheet
    assert m.merge_timer_states(sheet, local) == sheet     # order-insensitive
    # tie -> first arg (local) wins; sheet None -> local
    tie = dict(sheet, updated=100.0)
    assert m.merge_timer_states(local, tie) == local
    assert m.merge_timer_states(local, None) == local


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_timer.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'parse_duration'`

- [ ] **Step 3: Implement the pure functions**

In `src/relay/iro-feeds.py`: change line 55 to add `datetime`:
```python
import argparse, csv, datetime, io, ipaddress, json, os, re, shutil, signal, subprocess, sys, threading, time
```

Insert after `build_hud_data` (before `def channel_url`):

```python
# ---------- Race timer (relay-hosted countdown, replaces stagetimer) ----------
# State model (spec: docs/superpowers/specs/2026-06-06-race-timer-design.md):
# one absolute end anchor + duration + visibility + an "updated" stamp that
# drives the newest-wins merge between the local file and the Sheet tab.
TIMER_DEFAULT_DURATION = 6 * 3600          # seconds, until the Director sets one
DURATION_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")


def default_timer_state():
    return {"end": None, "duration": TIMER_DEFAULT_DURATION,
            "visible": True, "updated": 0.0}


def parse_duration(s):
    """'H:MM:SS' (or HH:MM:SS) -> seconds, else None."""
    mt = DURATION_RE.match((s or "").strip())
    if not mt:
        return None
    h, mi, sec = (int(g) for g in mt.groups())
    return h * 3600 + mi * 60 + sec


def format_duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_utc_ts(s):
    """Lenient UTC timestamp -> epoch seconds, else None. Accepts the canonical
    '...T..Z', Apps Script's toISOString ('.000Z'), and the 'YYYY-MM-DD HH:MM:SS'
    form gviz CSV produces when Sheets re-types the cell as a date."""
    s = (s or "").strip().replace("T", " ").rstrip("Zz").strip()
    s = s.split(".", 1)[0]                     # drop fractional seconds
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=datetime.timezone.utc).timestamp()


def iso_utc(epoch):
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timer_tab(text):
    """Timer tab CSV (label col A, value col B) -> state dict. Unknown labels
    and unparseable values fall back to the defaults — never throws."""
    raw = {}
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) >= 2 and (row[0] or "").strip():
            raw[row[0].strip().lower()] = (row[1] or "").strip()
    st = default_timer_state()
    st["end"] = parse_utc_ts(raw.get("race end (utc)", ""))
    dur = parse_duration(raw.get("duration", ""))
    if dur is not None:
        st["duration"] = dur
    st["visible"] = raw.get("visible", "").upper() != "FALSE"
    st["updated"] = parse_utc_ts(raw.get("updated (utc)", "")) or 0.0
    return st


def timer_mode(state, now):
    """hidden | prestart | running | finished (pure; the page renders blank
    for hidden and finished — spec: no 0:00:00 left standing)."""
    if not state.get("visible", True):
        return "hidden"
    end = state.get("end")
    if end is None:
        return "prestart"
    return "running" if now < end else "finished"


def merge_timer_states(local, sheet):
    """Newest write wins; tie (or no sheet state) -> local. Makes a producer
    takeover adopt the Sheet anchor without letting a stale Sheet revert a
    fresh local action whose webhook push failed."""
    if sheet is None:
        return local
    return sheet if sheet.get("updated", 0.0) > local.get("updated", 0.0) else local
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_timer.py`
Expected: all `ok t_...` lines + `ALL PASS`

- [ ] **Step 5: Lint and commit**

Run: `python3 tools/lint.py` — expected: no findings.
```bash
git add src/relay/iro-feeds.py tests/test_timer.py
git commit -m "feat(relay): pure race-timer logic (parse/format/mode/merge)"
```

---

### Task 2: TimerStore (persistence, Sheet poll, webhook push, actions)

**Files:**
- Modify: `src/relay/iro-feeds.py` (insert `TimerStore` directly after `merge_timer_states`)
- Modify: `tests/test_timer.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_timer.py` (before the `__main__` block):

```python
def _store(tmp=None, push_url=None, csv_url="http://sheet"):
    import tempfile, os as _os
    tmp = tmp or tempfile.mkdtemp()
    return m.TimerStore(csv_url, push_url, _os.path.join(tmp, "timer.json")), tmp


def t_timerstore_actions_update_state_and_stamp():
    ts, _ = _store()
    ts.set_duration(7200, now=900.0)
    assert ts.state["duration"] == 7200 and ts.state["updated"] == 900.0
    ts.start(now=1000.0)
    assert ts.state["end"] == 1000.0 + 7200
    assert ts.state["updated"] == 1000.0
    ts.adjust(-60)
    assert ts.state["end"] == 1000.0 + 7200 - 60
    ts.hide(); assert ts.state["visible"] is False
    ts.show(); assert ts.state["visible"] is True
    ts.stop(); assert ts.state["end"] is None


def t_timerstore_adjust_requires_running():
    ts, _ = _store()
    r = ts.adjust(60)
    assert "error" in r and ts.state["end"] is None


def t_timerstore_persists_and_reloads():
    import os as _os
    ts, tmp = _store()
    ts.set_duration(3600); ts.start(now=5000.0); ts.hide()
    ts2, _ = _store(tmp=tmp)
    assert ts2.state["end"] == 5000.0 + 3600
    assert ts2.state["duration"] == 3600
    assert ts2.state["visible"] is False
    assert _os.path.exists(_os.path.join(tmp, "timer.json"))


def t_timerstore_refresh_adopts_newer_sheet():
    ts, _ = _store()
    ts.set_duration(3600)                       # local write, updated = now
    newer = m.iso_utc(ts.state["updated"] + 100)
    ts._fetch = lambda url, timeout=10: (
        f"Race End (UTC),2026-06-13T20:00:00Z\nDuration,4:00:00\n"
        f"Visible,TRUE\nUpdated (UTC),{newer}\n")
    assert ts.refresh() is True
    assert ts.state["end"] == 1781380800.0 and ts.state["duration"] == 14400


def t_timerstore_refresh_keeps_newer_local():
    ts, _ = _store()
    ts._fetch = lambda url, timeout=10: (
        "Race End (UTC),2026-06-13T20:00:00Z\nDuration,4:00:00\n"
        "Visible,TRUE\nUpdated (UTC),2000-01-01T00:00:00Z\n")
    ts.refresh()
    ts.set_duration(3600)                       # local now newer than sheet
    ts.refresh()
    assert ts.state["duration"] == 3600         # stale sheet did not revert it


def t_timerstore_refresh_failure_keeps_state():
    ts, _ = _store()
    ts.set_duration(3600)
    def boom(url, timeout=10):
        raise RuntimeError("sheet down")
    ts._fetch = boom
    assert ts.refresh() is False
    assert ts.state["duration"] == 3600 and ts.last_error


def t_timerstore_push_payload_and_status():
    ts, _ = _store(push_url="http://push?key=k")
    sent = []
    ts._post = lambda url, body: sent.append((url, body))
    ts._spawn_push = ts._push                   # synchronous for the test
    ts.set_duration(7200); ts.start(now=1000.0)
    url, body = sent[-1]
    import json as _json
    p = _json.loads(body)
    assert url == "http://push?key=k"
    assert p == {"end": m.iso_utc(8200.0), "duration": "2:00:00", "visible": "TRUE"}
    assert ts.push_status == "ok"
    def fail(url, body):
        raise RuntimeError("403")
    ts._post = fail
    ts.hide()
    assert ts.push_status == "failed"


def t_timerstore_push_disabled_without_url():
    ts, _ = _store(push_url=None)
    ts.set_duration(7200)
    assert ts.push_status == "disabled"


def t_timerstore_data_contract():
    ts, _ = _store()
    d = ts.data(now=123.0)
    assert d["mode"] == "prestart" and d["visible"] is True
    assert d["end"] is None and d["duration_s"] == m.TIMER_DEFAULT_DURATION
    assert d["server_now"] == 123.0
    assert d["sync"]["push"] == "disabled"
    assert set(d["sync"]) == {"push", "sheet_last_ok_age_s", "last_error"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_timer.py`
Expected: `AttributeError: ... no attribute 'TimerStore'`

- [ ] **Step 3: Implement `TimerStore`**

Insert after `merge_timer_states` in `src/relay/iro-feeds.py`:

```python
class TimerStore:
    """Race-timer state with three layers (spec §3): in-memory + local JSON
    file (restart-safe) + Sheet tab via CSV poll / Apps-Script webhook push
    (producer-handover-safe). Director actions apply locally first and push in
    the background — a webhook failure degrades, never breaks."""

    def __init__(self, csv_url, push_url, path):
        self.csv_url = csv_url            # None -> local-only (no sheet poll)
        self.push_url = push_url          # None -> push disabled
        self.path = path
        self.lock = threading.Lock()
        self.state = default_timer_state()
        self.last_ok = None               # last successful sheet read
        self.last_error = None
        self.push_status = "disabled" if not push_url else "never"
        self._load_file()

    # -- persistence ------------------------------------------------------
    def _load_file(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                saved = json.load(fh)
            st = default_timer_state()
            st.update({k: saved[k] for k in st if k in saved})
            self.state = st
        except (OSError, ValueError):
            pass  # no/corrupt file -> defaults; the sheet poll may catch us up

    def _save_file(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh)
        except OSError:
            pass  # best-effort, same contract as the schedule/HUD caches

    # -- sheet read (poller + adopt-if-newer merge) -------------------------
    @staticmethod
    def _fetch(url, timeout=10):
        req = Request(url, headers={"User-Agent": "iro-feeds/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def refresh(self, timeout=10):
        if not self.csv_url:
            return False
        try:
            sheet = parse_timer_tab(self._fetch(self.csv_url, timeout))
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            merged = merge_timer_states(self.state, sheet)
            if merged is not self.state:
                self.state = merged
                self._save_file()
        self.last_ok = time.time()
        self.last_error = None
        return True

    # -- webhook push (Apps Script writes the Timer tab) --------------------
    @staticmethod
    def _post(url, body):
        req = Request(url, data=body, method="POST",
                      headers={"User-Agent": "iro-feeds/1.0",
                               "Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            resp.read()

    def _push(self, payload):
        try:
            self._post(self.push_url, json.dumps(payload).encode("utf-8"))
            self.push_status = "ok"
        except Exception as e:
            self.push_status = "failed"
            self.last_error = f"push: {type(e).__name__}: {e}"

    def _spawn_push(self, payload):
        threading.Thread(target=self._push, args=(payload,), daemon=True).start()

    # -- director actions ---------------------------------------------------
    def _apply(self, now=None, **changes):
        """Local-first write: update + stamp + save, then push full state."""
        now = time.time() if now is None else now
        with self.lock:
            self.state.update(changes)
            self.state["updated"] = now
            self._save_file()
            st = dict(self.state)
        if self.push_url:
            self._spawn_push({
                "end": iso_utc(st["end"]) if st["end"] is not None else "",
                "duration": format_duration(st["duration"]),
                "visible": "TRUE" if st["visible"] else "FALSE"})
        return self.data(now)

    def start(self, now=None):
        now = time.time() if now is None else now
        return self._apply(now=now, end=now + self.state["duration"])

    def stop(self, now=None):
        return self._apply(now=now, end=None)

    def show(self, now=None):
        return self._apply(now=now, visible=True)

    def hide(self, now=None):
        return self._apply(now=now, visible=False)

    def set_duration(self, seconds, now=None):
        # Never re-anchors a running timer (spec §5) — corrections use adjust.
        return self._apply(now=now, duration=int(seconds))

    def adjust(self, delta_s, now=None):
        with self.lock:
            running = self.state["end"] is not None
        if not running:
            return {"error": "timer not running — /timer/start first", **self.data(now)}
        return self._apply(now=now, end=self.state["end"] + int(delta_s))

    # -- read side ----------------------------------------------------------
    def data(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            st = dict(self.state)
        return {"visible": st["visible"], "end": st["end"],
                "duration_s": st["duration"], "server_now": now,
                "mode": timer_mode(st, now),
                "sync": {"push": self.push_status,
                         "sheet_last_ok_age_s": (round(now - self.last_ok, 1)
                                                 if self.last_ok else None),
                         "last_error": self.last_error}}

    def summary(self):
        """Compact line for /status and `iro status`."""
        d = self.data()
        return {"mode": d["mode"], "visible": d["visible"],
                "remaining_s": (max(0, int(d["end"] - d["server_now"]))
                                if d["end"] is not None else None),
                "push": d["sync"]["push"]}
```

Note for `data(now=...)` in `adjust`/`_apply` error path: `data()` takes `now=None`
and handles it — passing the caller's `now` through is fine.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_timer.py`
Expected: all `ok t_...` + `ALL PASS`. Also run `python3 tests/test_pov.py`, `python3 tests/test_hud.py`, `python3 tests/test_bind.py` (same module — must still pass).

- [ ] **Step 5: Lint and commit**

Run: `python3 tools/lint.py` — expected: no findings.
```bash
git add src/relay/iro-feeds.py tests/test_timer.py
git commit -m "feat(relay): TimerStore — file persistence, sheet poll, webhook push"
```

---

### Task 3: Wire the timer into the relay (routes, flags, poller) + `/timer` page

**Files:**
- Modify: `src/relay/iro-feeds.py` (`make_handler`, `main`, module docstring controls list)
- Create: `src/obs/timer.html`

- [ ] **Step 1: Extend `make_handler`**

Change the signature (line 718) to:
```python
def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, timer_path=None):
```

In `do_GET`, replace the `/status` line and add timer routes after the `hud/assets` route:
```python
                if not p or p == ["status"]:
                    base = relay.status()
                    if timer_store: base["timer"] = timer_store.summary()
                    return self._send(base)
```
```python
                if p[:1] == ["timer"]:
                    if p == ["timer"]:
                        if not timer_path: return self._send({"error": "timer disabled"}, 404)
                        return self._send_file(timer_path, "text/html; charset=utf-8")
                    if not timer_store:
                        return self._send({"error": "timer disabled"}, 404)
                    if p == ["timer", "data"]:   return self._send(timer_store.data())
                    if p == ["timer", "start"]:  return self._send(timer_store.start())
                    if p == ["timer", "stop"]:   return self._send(timer_store.stop())
                    if p == ["timer", "show"]:   return self._send(timer_store.show())
                    if p == ["timer", "hide"]:   return self._send(timer_store.hide())
                    if len(p) == 3 and p[1] == "set":
                        dur = parse_duration(p[2])
                        if dur is None:
                            return self._send({"error": "duration must be H:MM:SS"}, 400)
                        return self._send(timer_store.set_duration(dur))
                    if len(p) == 3 and p[1] == "adjust":
                        try: delta = int(p[2])
                        except ValueError:
                            return self._send({"error": "adjust takes +/- seconds"}, 400)
                        return self._send(timer_store.adjust(delta))
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

- [ ] **Step 2: Wire up in `main()`**

Add CLI flags next to `--no-hud` (after line 863):
```python
    ap.add_argument("--timer-tab", default="Timer",
                    help="Google-Sheet tab holding the race-timer anchor (default 'Timer').")
    ap.add_argument("--no-timer", action="store_true",
                    help="Do not serve the race timer at /timer.")
```

After the HUD block (after line 963), create the store + locate the page:
```python
    # Race timer: local file always; sheet sync derived from sheet-id/tab
    # (custom --sheet-csv-url -> local-only); push via IRO_TIMER_PUSH_URL.
    timer_store = None
    timer_path = None
    if not args.no_timer:
        timer_csv = None
        if not args.sheet_csv_url:
            timer_csv = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                         f"/gviz/tq?tqx=out:csv&sheet={quote(args.timer_tab)}")
        timer_store = TimerStore(timer_csv, os.environ.get("IRO_TIMER_PUSH_URL"),
                                 os.path.join(runtime, "timer.json"))
        timer_store.refresh()   # non-fatal: adopt a newer sheet anchor on startup
        for cand in (os.path.join(here, "timer.html"),
                     os.path.join(here, "..", "timer.html"),
                     os.path.join(here, "..", "obs", "timer.html")):
            if os.path.exists(cand):
                timer_path = os.path.abspath(cand); break
        if not timer_path:
            print("WARN: timer.html not found — /timer will 404.")
```

Add a poller thread next to the HUD poller (after line 980):
```python
    if timer_store and timer_store.csv_url:
        threading.Thread(target=poller, args=(timer_store, args.hud_poll, stop_evt),
                         daemon=True).start()
```

Pass the new args to `make_handler` (line 982):
```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, timer_path)
```

Add a startup print next to the HUD print (after line 1026):
```python
    if timer_store and timer_path:
        push = "sheet+push" if timer_store.push_url else (
            "sheet read-only (set IRO_TIMER_PUSH_URL for handover sync)"
            if timer_store.csv_url else "local only")
        print(f"  Race timer (OBS source): http://127.0.0.1:{args.http_port}/timer  "
              f"(tab '{args.timer_tab}', {push}; controls /timer/start | /timer/stop)")
```

Update the module docstring's controls list (after line 51's `/pov/stop` line):
```
  GET /timer           -> race-timer browser-source page (OBS 'HUD Race Timer')
  GET /timer/data      -> timer state JSON (anchor, mode, sync health)
  GET /timer/start | /timer/stop | /timer/show | /timer/hide
  GET /timer/set/<H:MM:SS>     -> set the race duration (next start)
  GET /timer/adjust/<±seconds> -> shift a RUNNING timer (correction)
```

- [ ] **Step 3: Create `src/obs/timer.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IRO Race Timer</title>
<style>
  /* Mirrors the old stagetimer output geometry: the OBS scene items crop this
     1920x1080 page to y[217..895] and scale it down, so the digits live inside
     that window. Tweak font-size/position here to fine-tune live (same model
     as hud.html). */
  html, body { margin: 0; width: 1920px; height: 1080px;
    background: transparent; overflow: hidden; }
  #clock { position: absolute; left: 0; top: 217px; width: 1920px; height: 678px;
    display: flex; align-items: center; justify-content: center;
    font-family: "SF Mono", "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-weight: 700; font-size: 420px; color: #ffffff;
    text-shadow: 0 4px 12px rgba(0,0,0,.6); font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <div id="clock"></div>
<script>
  // Ticks locally against the absolute end anchor; the poll only re-syncs the
  // anchor/visibility (sheet edits, director actions, server clock offset).
  const POLL_MS = 2000, TICK_MS = 250;
  let state = null, clockOffset = 0;   // serverNow - clientNow at last poll

  function fmt(s) {
    s = Math.max(0, Math.ceil(s));
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
  }
  function render() {
    const el = document.getElementById("clock");
    if (!state || !state.visible) { el.textContent = ""; return; }
    if (state.end === null) { el.textContent = fmt(state.duration_s); return; }
    const remaining = state.end - (Date.now() / 1000 + clockOffset);
    el.textContent = remaining > 0 ? fmt(remaining) : "";   // blank at zero
  }
  async function poll() {
    try {
      const r = await fetch("/timer/data", { cache: "no-store" });
      const d = await r.json();
      if (!d.error) { state = d; clockOffset = d.server_now - Date.now() / 1000; }
    } catch (e) { /* keep last good state on transient errors */ }
  }
  poll();
  setInterval(poll, POLL_MS);
  setInterval(render, TICK_MS);
</script>
</body>
</html>
```

- [ ] **Step 4: Verify (tests + a live smoke test)**

Run: `python3 tests/test_timer.py && python3 tests/test_pov.py && python3 tests/test_hud.py && python3 tests/test_bind.py`
Expected: all pass.

Smoke test (needs `.env` with `IRO_SHEET_ID`; Ctrl+C to stop):
```bash
python3 src/iro.py relay run &
sleep 5
curl -s http://127.0.0.1:8088/timer/data            # mode prestart, push disabled/…
curl -s http://127.0.0.1:8088/timer/set/0:00:10     # duration 10 s
curl -s http://127.0.0.1:8088/timer/start           # mode running
curl -s http://127.0.0.1:8088/status | head -20     # has "timer" summary
open http://127.0.0.1:8088/timer                    # digits count down, blank at 0
kill %1
```
Expected: JSON responses as annotated; `runtime/timer.json` exists.

- [ ] **Step 5: Lint and commit**

Run: `python3 tools/lint.py` — expected: no findings.
```bash
git add src/relay/iro-feeds.py src/obs/timer.html
git commit -m "feat(relay): /timer page + control endpoints, sheet-synced race timer"
```

---

### Task 4: Point the OBS collection at `/timer`; drop the `__IRO_TIMER__` round-trip

**Files:**
- Modify: `src/obs/IRO_Endurance.json` (line 439: the `HUD Race Timer` browser source)
- Modify: `src/setup-assets.py` (remove `TIMER_TOKEN`, `--timer-url`, its mapping block and prints)
- Modify: `tools/tokenize-obs.py` (remove `TIMER_TOKEN`/`TIMER_RE` and their use)
- Modify: `tools/build.py` (line 131: replace the timer check)

- [ ] **Step 1: Swap the browser-source URL**

In `src/obs/IRO_Endurance.json` line 439 change:
```json
                "url": "__IRO_TIMER__",
```
to the fixed loopback URL (no token — machine-independent, like the HUD):
```json
                "url": "http://127.0.0.1:8088/timer",
```
Scene-item transforms (crop/scale/pos) stay untouched — `timer.html` mimics the
old page geometry inside the same crop window.

- [ ] **Step 2: Remove the token from `setup-assets.py`**

Delete line 12 (`TIMER_TOKEN = "__IRO_TIMER__"`), the `--timer-url` argument
(lines 140–142), the `if TIMER_TOKEN in raw:` block (lines 173–178), and the
`if TIMER_TOKEN in mapping:` print (lines 206–207).

- [ ] **Step 3: Remove the token from `tokenize-obs.py`**

Delete `TIMER_TOKEN` (line 14) and `TIMER_RE` (lines 17–18); in
`tokenize_sheets` drop the `TIMER_RE.subn` line and change the counter line to
`counter[0] += c`; update the final print to `... sheet URL(s) ...`. Keep the
docstring accurate (it never mentioned the timer).

- [ ] **Step 4: Update the build verify check**

In `tools/build.py` replace line 131 with (template must carry the relay URL
and no stagetimer leftovers; the relay must ship the endpoints):
```python
        "obs timer is relay-served": "http://127.0.0.1:8088/timer" in tpl
            and "__IRO_TIMER__" not in tpl and "stagetimer" not in tpl,
        "relay timer endpoint": "/timer/data" in relay,
```
(`/timer/data` appears literally in the relay module docstring's controls list
added in Task 3 — same style as the existing `"relay pov endpoint"` check.)

- [ ] **Step 5: Verify build + full suite**

Run: `python3 tools/run-tests.py` — expected: ALL TEST FILES PASS.
Run: `python3 tools/build.py` — expected: every verify line `[OK]`, including the two new checks.
Run: `python3 tools/lint.py` — expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add src/obs/IRO_Endurance.json src/setup-assets.py tools/tokenize-obs.py tools/build.py
git commit -m "feat(obs): timer browser source -> relay /timer; retire __IRO_TIMER__ round-trip"
```

---

### Task 5: Retire `IRO_TIMER_URL` from env/init/event; introduce `IRO_TIMER_PUSH_URL`

**Files:**
- Modify: `.env.example` (lines 10–13)
- Modify: `src/scripts/init_setup.py` (line 11, 67)
- Modify: `src/iro.py` (lines 99, 711, 982)
- Modify: `src/scripts/event.py` (`classify_env`, lines 224–230)
- Modify: `tests/test_init.py` (line 61–63 area), `tests/test_event.py` (lines 181–186)

- [ ] **Step 1: Update the failing tests first**

`tests/test_init.py` — replace the env_done assertions with:
```python
    assert m.env_done({"IRO_SHEET_ID": "x"}) is not None
    assert m.env_done({"IRO_SHEET_ID": ""}) is None
    assert m.env_done({}) is None
```

`tests/test_event.py` — replace `t_classify_env` with:
```python
def t_classify_env():
    assert m.classify_env("sheet", "http://push").level == "PASS"
    r = m.classify_env("sheet", "")          # push URL optional -> WARN, not FAIL
    assert r.level == "WARN" and "IRO_TIMER_PUSH_URL" in r.detail
    r = m.classify_env("", "http://push")
    assert r.level == "FAIL" and "IRO_SHEET_ID" in r.detail
```

Run: `python3 tests/test_init.py; python3 tests/test_event.py`
Expected: both FAIL (old names still in the modules).

- [ ] **Step 2: `.env.example`** — replace lines 10–13 with:

```bash
# OPTIONAL: race-timer write webhook (Google Apps Script /exec URL INCLUDING its
# ?key=... secret). Lets Director timer actions (start/stop/show/hide/correct)
# sync to the Sheet "Timer" tab so a second producer machine takes over with the
# exact same countdown. Unset = timer works on this machine only.
# Setup: see the wiki page "Race-Timer".
IRO_TIMER_PUSH_URL=
```

- [ ] **Step 3: `init_setup.py`** — line 11:
```python
REQUIRED_ENV = ("IRO_SHEET_ID",)
```
and `env_done`'s return string (line 67): `return "IRO_SHEET_ID set"`.

- [ ] **Step 4: `iro.py`** — line 982:
```python
        _init_pause(f"Fill in IRO_SHEET_ID in {path} (IRO_TIMER_PUSH_URL is "
                    "optional — see the Race-Timer wiki page)")
```
Lines 98–99 (the created-`.env` hint): replace
```python
    print("created .env next to the binary — fill in IRO_SHEET_ID and "
          "IRO_TIMER_URL (see the comments inside).", file=sys.stderr)
```
with
```python
    print("created .env next to the binary — fill in IRO_SHEET_ID "
          "(see the comments inside).", file=sys.stderr)
```
Line 711: pass the new var:
```python
    config = [ev.classify_env(os.environ.get("IRO_SHEET_ID"),
                              os.environ.get("IRO_TIMER_PUSH_URL"))]
```

- [ ] **Step 5: `event.py`** — replace `classify_env` (lines 224–230):
```python
def classify_env(sheet_id, timer_push_url):
    """IRO_SHEET_ID is required (FAIL); the race-timer webhook is optional —
    missing means the timer cannot sync across producer machines (WARN)."""
    if not sheet_id:
        return Result(FAIL, ".env", "missing: IRO_SHEET_ID — fill it in "
                      "(.env next to the binary / repo root)")
    if not timer_push_url:
        return Result(WARN, ".env", "IRO_TIMER_PUSH_URL unset — race-timer "
                      "handover sync disabled (see the Race-Timer wiki page)")
    return Result(PASS, ".env", "IRO_SHEET_ID and IRO_TIMER_PUSH_URL set")
```

- [ ] **Step 6: Run the suite**

Run: `python3 tools/run-tests.py`
Expected: ALL TEST FILES PASS.
Run: `python3 tools/lint.py` — expected: no findings.

- [ ] **Step 7: Commit**

```bash
git add .env.example src/scripts/init_setup.py src/iro.py src/scripts/event.py tests/test_init.py tests/test_event.py
git commit -m "feat(env): IRO_TIMER_URL -> optional IRO_TIMER_PUSH_URL (init gate, event check)"
```

---

### Task 6: Companion timer buttons

**Files:**
- Modify: `src/companion/iro-buttons.companionconfig` (page 2, row 0, columns 1–6 are free)

- [ ] **Step 1: Add six buttons via a one-off script**

The config is Companion-export JSON (`version: 12`); existing relay buttons are
`definitionId: "get"` actions on the Generic-HTTP connection. Reuse that
connection id dynamically. Run this from the repo root:

```bash
python3 - <<'EOF'
import json
p = "src/companion/iro-buttons.companionconfig"
d = json.load(open(p, encoding="utf-8"))

# find the Generic-HTTP connectionId from any existing relay button
conn = None
for page in d["pages"].values():
    for cols in (page.get("controls") or {}).values():
        for ctl in cols.values():
            for act in ctl.get("steps", {}).get("0", {}).get("action_sets", {}).get("down", []):
                if act.get("definitionId") == "get":
                    conn = act["connectionId"]
assert conn, "no Generic-HTTP action found"

def btn(text, path, bg=0, color=16777215):
    return {
      "type": "button",
      "style": {"text": text, "textExpression": False, "size": "14",
                "png64": None, "alignment": "center:center",
                "pngalignment": "center:center", "color": color, "bgcolor": bg,
                "show_topbar": "default"},
      "options": {"stepProgression": "auto", "stepExpression": "",
                  "rotaryActions": False},
      "feedbacks": [],
      "steps": {"0": {"action_sets": {"down": [{
          "id": f"iro-timer-{path.replace('/', '-')}",
          "definitionId": "get", "connectionId": conn,
          "options": {"url": {"value": f"http://127.0.0.1:8088/timer/{path}",
                              "isExpression": False},
                      "header": {"isExpression": False, "value": ""},
                      "jsonResultDataVariable": {"isExpression": False},
                      "result_stringify": {"isExpression": False, "value": True},
                      "statusCodeVariable": {"isExpression": False}},
          "upgradeIndex": 1, "type": "action"}], "up": []},
          "options": {"runWhileHeld": []}}},
      "localVariables": [],
    }

row0 = d["pages"]["2"]["controls"].setdefault("0", {})
GREEN, RED = 26112, 9109504
for col, (text, path, bg) in enumerate([
        ("TIMER\nSTART", "start", GREEN),
        ("TIMER\nSTOP",  "stop", RED),
        ("TIMER\nSHOW",  "show", 0),
        ("TIMER\nHIDE",  "hide", 0),
        ("TIMER\n+1 MIN", "adjust/60", 0),
        ("TIMER\n-1 MIN", "adjust/-60", 0)], start=1):
    assert str(col) not in row0, f"slot 0/{col} on page 2 is occupied"
    row0[str(col)] = btn(text, path, bg)

json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
print("added 6 timer buttons to page 2 row 0")
EOF
```

- [ ] **Step 2: Verify the config**

Run: `python3 tests/test_companion.py && python3 tools/build.py`
Expected: tests pass; build verify still shows `[OK] companion password empty`
and `[OK] companion pov buttons`.
Manual check (operator step, note it in the PR/commit body): import
`runtime/iro-buttons.companionconfig` (`python3 src/iro.py export companion`)
into a running Companion once and confirm the six buttons appear and fire.

- [ ] **Step 3: Commit**

```bash
git add src/companion/iro-buttons.companionconfig
git commit -m "feat(companion): race-timer buttons (start/stop/show/hide/±1min)"
```

---

### Task 7: Director-panel timer section

**Files:**
- Modify: `src/director/director-panel.html`

- [ ] **Step 1: Add the Timer panel markup**

Insert as the FIRST child of `<div class="grid">` (before the Scenes panel,
line 137 — the timer is relay-served and works even before OBS is connected):

```html
    <div class="panel span2">
      <h2>Race Timer</h2>
      <div class="btns" id="timerBtns"></div>
      <div class="hint" id="timerInfo">Timer: connecting to relay…</div>
    </div>
```

- [ ] **Step 2: Add the timer JS**

Append inside the `<script>` block (after the `CurrentProgramSceneChanged`
handler). The panel is served by the relay, so same-origin relative fetches hit
the control server directly — independent of the OBS websocket connection:

```javascript
/* ---------- race timer (relay-served; works without the OBS connection) --- */
const TIMER_ACTIONS = [
  ["START",  "timer/start"],  ["STOP",   "timer/stop"],
  ["SHOW",   "timer/show"],   ["HIDE",   "timer/hide"],
  ["+1 MIN", "timer/adjust/60"], ["−1 MIN", "timer/adjust/-60"],
  ["+10 S",  "timer/adjust/10"], ["−10 S",  "timer/adjust/-10"],
];
async function timerCall(path){
  try{
    const r = await fetch("/" + path, {cache:"no-store"});
    const d = await r.json();
    if (d.error) log("Timer: " + d.error, "err"); else timerRender(d);
  }catch(e){ log("Timer action failed (relay reachable?): " + e, "err"); }
}
TIMER_ACTIONS.forEach(([label, path])=>{
  const b = mkBtn(label, "timer", ()=>timerCall(path));
  b.classList.add("timer"); b.disabled = false;
  document.getElementById("timerBtns").appendChild(b);
});
{ // duration setter (prompt keeps the panel dependency-free)
  const b = mkBtn("SET DURATION", "timer", ()=>{
    const v = prompt("Race duration (H:MM:SS):", "6:00:00");
    if (v) timerCall("timer/set/" + encodeURIComponent(v.trim()));
  });
  b.classList.add("timer"); b.disabled = false;
  document.getElementById("timerBtns").appendChild(b);
}
function timerFmt(s){
  s = Math.max(0, Math.ceil(s));
  return `${Math.floor(s/3600)}:${String(Math.floor(s%3600/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;
}
function timerRender(d){
  const rem = d.end !== null ? d.end - d.server_now : null;
  const head = d.mode === "running" ? `RUNNING · ${timerFmt(rem)} left`
             : d.mode === "prestart" ? `READY · duration ${timerFmt(d.duration_s)}`
             : d.mode === "finished" ? "FINISHED (display blank)"
             : "HIDDEN";
  const sync = d.sync.push === "ok" ? "sheet sync OK"
             : d.sync.push === "disabled" ? "local only (IRO_TIMER_PUSH_URL unset)"
             : d.sync.push === "failed" ? "SHEET SYNC FAILED — handover not safe"
             : "sheet sync not yet attempted";
  document.getElementById("timerInfo").textContent = `Timer: ${head} · ${sync}`;
}
async function timerPoll(){
  try{
    const r = await fetch("/timer/data", {cache:"no-store"});
    const d = await r.json();
    if (!d.error) timerRender(d);
    else document.getElementById("timerInfo").textContent = "Timer: disabled on this relay.";
  }catch(e){
    document.getElementById("timerInfo").textContent =
      "Timer: relay not reachable (panel opened from file://? open it via http://<relay>:8088/panel).";
  }
}
timerPoll();
setInterval(timerPoll, 2000);
```

- [ ] **Step 3: Keep `setEnabled` from disabling timer buttons**

Change the `setEnabled` selector (line 324) to exclude them:
```javascript
  document.querySelectorAll("button.b:not(.timer), .mute, #audio input[type=range]").forEach(el=>el.disabled=!on);
```

- [ ] **Step 4: Verify in a browser**

Start the relay (`python3 src/iro.py relay run`), open
`http://127.0.0.1:8088/panel`: the Race Timer section shows `READY · duration
6:00:00 · local only…` (without push URL), START switches it to `RUNNING`,
HIDE → `HIDDEN`, and the buttons stay clickable while OBS is disconnected.
Stop the relay.

- [ ] **Step 5: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): race-timer section (start/stop/show/hide/correct/set)"
```

---

### Task 8: Docs — Apps Script setup page, operator docs, CLAUDE.md

**Files:**
- Create: `src/docs/wiki/Race-Timer.md`
- Modify: `src/docs/wiki/Configuration.md`, `src/docs/wiki/Architecture.md`, `src/docs/wiki/OBS-Setup.md`, `src/docs/wiki/Who-does-what.md`, `src/docs/wiki/Set-up-the-broadcast-PC.md`
- Modify: `src/docs/README_SETUP.md`, `src/docs/IRO_Broadcast_Setup_Guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the new wiki page**

`src/docs/wiki/Race-Timer.md` — full content:

````markdown
# Race Timer

The remaining-race-time overlay is served by the relay itself at
`http://127.0.0.1:8088/timer` (the OBS `HUD Race Timer` browser source points
there). No external service is involved.

## How it works

The timer is **one absolute end timestamp** plus a duration and a visibility
flag. The browser source computes `end − now` locally and ticks smoothly; the
state lives in three places:

| Layer | Purpose |
|---|---|
| Relay memory + `runtime/timer.json` | survives a relay/OBS restart on this machine |
| Sheet tab **Timer** | survives a producer-machine handover — every relay reads the same anchor |
| Apps Script webhook | lets Director buttons write that Sheet tab |

Newest write wins (both sides carry an `Updated (UTC)` stamp), so a stale
Sheet never reverts a fresh local action. Machines must have normal NTP clock
sync (macOS/Windows default).

## Director controls

Available on the **director panel** (`http://<producer-tailscale-ip>:8088/panel`,
Race Timer section) and as **Companion buttons** (page 2, top row):

| Action | Endpoint | Effect |
|---|---|---|
| Start | `/timer/start` | end = now + duration |
| Stop | `/timer/stop` | back to "not started" (shows the full duration) |
| Show / Hide | `/timer/show`, `/timer/hide` | blanks/unblanks the overlay on every producer machine |
| Set duration | `/timer/set/6:00:00` | race length for the next start |
| Correct | `/timer/adjust/-60` | shift a running timer by ± seconds |

Display behaviour: before start → static full duration; running → countdown;
at zero → blank (no `0:00:00` left standing); hidden → blank.

## One-time setup: the write webhook (optional but recommended)

Without it the timer still works on the producer machine, but Director actions
cannot sync to the Sheet — a takeover machine would not pick up the running
countdown. Set it up once per sheet:

1. Open the broadcast Google Sheet → **Extensions → Apps Script**.
2. Paste this script (replace `change-me` with a random secret):

   ```javascript
   const KEY = 'change-me';            // must match the key=... in the URL below
   const TAB = 'Timer';
   const ROWS = {'Race End (UTC)': 1, 'Duration': 2, 'Visible': 3, 'Updated (UTC)': 4};

   function doPost(e) {
     const out = (o) => ContentService.createTextOutput(JSON.stringify(o))
         .setMimeType(ContentService.MimeType.JSON);
     if (((e.parameter && e.parameter.key) || '') !== KEY) return out({error: 'bad key'});
     const p = JSON.parse(e.postData.contents);
     const ss = SpreadsheetApp.getActiveSpreadsheet();
     const sheet = ss.getSheetByName(TAB) || ss.insertSheet(TAB);
     const write = (label, value) => {
       sheet.getRange(ROWS[label], 1).setValue(label);
       sheet.getRange(ROWS[label], 2).setNumberFormat('@').setValue(value);
     };
     if ('end' in p) write('Race End (UTC)', p.end);
     if ('duration' in p) write('Duration', p.duration);
     if ('visible' in p) write('Visible', p.visible);
     write('Updated (UTC)', new Date().toISOString());
     return out({ok: true});
   }
   ```

3. **Deploy → New deployment → Web app**, execute as **Me**, access:
   **Anyone**. Copy the `/exec` URL.
4. In `.env` on every producer machine:

   ```
   IRO_TIMER_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
   ```

5. Restart the relay. `iro event status` shows the `.env` check as PASS, and
   the panel's timer line reports `sheet sync OK` after the first action.

The URL+key is a write credential for the Timer tab — treat it like the other
`.env` secrets (never commit it).

## Producer handover

Nothing to do: the new machine's relay reads the Sheet anchor on startup and
shows the identical countdown. If the webhook was never set up, set the
remaining time manually after takeover: `/timer/set/<H:MM:SS>` + `/timer/start`
won't match mid-race — instead start, then `/timer/adjust/±seconds` until it
matches the official clock.
````

- [ ] **Step 2: Update the stagetimer references**

In each file, replace stagetimer/`IRO_TIMER_URL` content with the relay-timer
equivalent (link `Race-Timer.md` in the wiki pages):

- `src/docs/wiki/Configuration.md`: replace the `IRO_TIMER_URL` row/section
  with `IRO_TIMER_PUSH_URL` — "optional; Apps Script write webhook for the
  race timer, see [Race-Timer](Race-Timer)".
- `src/docs/wiki/Architecture.md`: in the component list/diagram text, replace
  the "stagetimer.io output URL" browser source with "relay-served `/timer`
  countdown (state: Sheet tab `Timer` + `runtime/timer.json`)".
- `src/docs/wiki/OBS-Setup.md`: the `HUD Race Timer` source now points at the
  fixed `http://127.0.0.1:8088/timer` — remove the "paste your signed
  stagetimer URL" instruction; note that no per-machine edit is needed.
- `src/docs/wiki/Who-does-what.md`: the Director's timer duties (start/stop/
  show/hide/correct) move from "stagetimer controller" to "panel Race Timer
  section / Companion page 2" — describe the mechanism only (no invented crew
  procedures).
- `src/docs/wiki/Set-up-the-broadcast-PC.md`: drop the stagetimer account/URL
  step; add "(optional) set `IRO_TIMER_PUSH_URL` — see [Race-Timer](Race-Timer)".
- `src/docs/README_SETUP.md` + `src/docs/IRO_Broadcast_Setup_Guide.md`: same
  two substitutions (source URL fixed; env var renamed + optional).
- Add `Race-Timer` to the wiki sidebar/home page list if
  `src/docs/wiki/Home.md` (or `_Sidebar.md`) enumerates pages — check with
  `grep -l "OBS-Setup" src/docs/wiki/*.md`.

- [ ] **Step 3: Update CLAUDE.md**

- In **Secrets via `.env`**: replace `IRO_TIMER_URL (signed stagetimer output
  URL)` with `IRO_TIMER_PUSH_URL (optional Apps Script webhook that lets the
  relay write race-timer state to the Sheet's Timer tab)`.
- In **Two token round-trips**: remove `__IRO_TIMER__` from the OBS token list
  and add one sentence: "The race timer is relay-served (`/timer`, fixed
  loopback URL in the collection — no token); state = Sheet tab `Timer` +
  `runtime/timer.json`, Director-controlled via `/timer/*` endpoints."
- In the **relay** section's endpoint list add `/timer/*`; in **Commands** add
  `python3 tests/test_timer.py  # relay race-timer unit checks`.

- [ ] **Step 4: Verify English-only + build**

Run: `python3 tools/build.py` — expected: all `[OK]`.
Run: `grep -rn "stagetimer\|IRO_TIMER_URL" src/ CLAUDE.md README.md .env.example` — expected: no hits.

- [ ] **Step 5: Commit**

```bash
git add src/docs CLAUDE.md
git commit -m "docs: relay race timer — Apps Script setup page, operator docs, CLAUDE.md"
```

---

### Task 9: Final verification

- [ ] **Step 1: Full suite + lint + build**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # no findings
python3 tools/build.py         # all verify checks [OK]
```

- [ ] **Step 2: End-to-end handover simulation (manual)**

1. `.env` with `IRO_SHEET_ID` + deployed `IRO_TIMER_PUSH_URL`; start the relay.
2. `curl http://127.0.0.1:8088/timer/set/0:30:00` then `/timer/start` — check
   the Sheet's `Timer` tab updates within seconds.
3. Simulate "machine 2": `python3 src/relay/iro-feeds.py --http-port 8089 --ports 53011,53012 --pov-port 53013 --runtime-dir /tmp/iro-takeover` — its
   `/timer/data` (port 8089) must show the same `end` anchor (mode `running`).
4. `/timer/hide` on 8088 → within ~10 s, 8089's `/timer/data` shows
   `visible: false` (sheet poll).
5. Stop both relays; delete `/tmp/iro-takeover`.

- [ ] **Step 3: Wiki publish (after merge, maintainer)**

```bash
python3 tools/sync-wiki.py --dry-run    # review, then run without --dry-run
```
Then regenerate the Companion wiki screenshots (companion-screenshots skill)
since page 2 gained a row of buttons.

- [ ] **Step 4: Commit anything outstanding, then hand off**

Follow `superpowers:finishing-a-development-branch`.
```bash
git status   # expect: clean
```

---

## Spec-coverage map

| Spec section | Task |
|---|---|
| §3 state model, read/write/merge | 1, 2 |
| §4 display page + OBS URL swap | 3, 4 |
| §5 control endpoints + /status summary | 3 |
| §6 panel + Companion surfaces | 6, 7 |
| §7 error handling | 1 (parse-never-throws), 2 (push/refresh degraded) |
| §8 testing | 1, 2, 9 (manual handover) |
| §10 cleanup checklist | 4, 5, 8 |
