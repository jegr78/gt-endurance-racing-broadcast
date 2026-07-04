# Director-Panel Broadcast Part Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Director Panel the single control surface for a broadcast's Parts on the GCP cloud producer — go live with Part N, end Part N, continue with the next Part — each live-state change gated by a typed confirmation; plus the minimal changes that let `racecast event start` bring OBS + Discord up over plain SSH.

**Architecture:** Server-side atomic Part actions: the panel sends one high-level request per boundary; the relay resolves Part → stream-key, fetches the real key via the `get_stream_key` webhook, applies it with `obs_ws.set_stream_service`, and starts/stops the stream. A persisted `part.json` pointer (`{index, live}`) is reset at `event start`. Pure logic lives in a new `src/scripts/parts.py`; the relay holds the I/O.

**Tech Stack:** Python stdlib only (no framework, no pytest — each test file is a runnable script). Relay = `src/relay/racecast-feeds.py`. OBS via the existing stdlib obs-websocket client `src/scripts/obs_ws.py`. Panel = `src/director/director-panel.html`. Cloud = `tools/cloud/provision.sh`.

**Spec:** `docs/superpowers/specs/2026-07-04-director-panel-part-control-design.md`

## Global Constraints

- **English only** for all shipped scripts/docs/UI copy (chat with the user is German).
- **Edit only under `src/`** for shipped code; `tools/cloud/provision.sh` + `tools/cloud/README.md` are maintainer glue (allowed, outside `dist/`); specs/plans under `docs/superpowers/`. Never hand-edit `dist/`/`runtime/`.
- **Never hardcode secrets or machine paths.** The **stream key never reaches the browser, `/parts/data`, logs, or any print/return path** — fetched server-side, applied over localhost obs-websocket only (preserves the Script-Properties model).
- **Outbound HTTP:** the relay is exempt from the `http_util` UA guard — it uses its own `post_webhook()` / `Request(..., headers={"User-Agent":"racecast-feeds/1.0"})`. Do NOT import `http_util` into the relay.
- **Tests run on any machine + CI incl. `windows-latest`.** Stdlib only, `t_*` functions, sorted-globals runner. A fixed-OS absolute path (e.g. a Linux `~/.Xauthority`) is built with explicit `/`, never `os.path.join`.
- **TDD:** failing test first, then the fix. **Racecast is released (v1.x): backward compatibility matters** — a league with no `Producer` tab keeps today's plain GO-LIVE button (graceful fallback), and no CLI flag is renamed/removed.
- **Auth/security:** `/parts/*` is director-gated via `console_policy` (`Requirement(DIRECTOR, False)`); the typed-intent phrase is the anti-accident layer, enforced in the handler. Only `/console` is Funnel-mounted; OBS-WebSocket is never funnelled.
- **UI changes require visual verification** (superpowers gate) **and** the wiki screenshot `src/docs/wiki/images/director-panel.png` must be refreshed in the SAME change (`wiki-screenshots` skill; demo profile + `tools/obs-sim.py`). Running the demo relay mutates `profiles/demo/profile.env` (`CONSOLE_SECRET`) — **revert that before committing.**
- After any Python change run `python3 tools/lint.py`; run the touched test file, and `python3 tools/run-tests.py` before finishing. After a wiki page edit run `python3 tests/test_wiki.py`. `provision.sh` must pass `shellcheck`.

## File Structure

- **`src/scripts/parts.py`** *(new, pure)* — `normalize_intent`, `parts_intent_phrase`, `parts_view_model`, `validate_start`, `validate_end`. No I/O. The single source of the panel's Part logic.
- **`src/relay/racecast-feeds.py`** *(modify)* — `PartStore` (persisted pointer), `ProducerSource` (Sheet reader), `apply_stream_service_for_ref` (relay-side key apply), `/parts/*` GET+POST routes, `main()` wiring (`--producer-tab`/`--no-parts`, sources, store, poller), new imports (`producer`, `stream_target`, `parts`).
- **`src/scripts/console_policy.py`** *(modify)* — `parts` → `Requirement(DIRECTOR, False)`.
- **`src/scripts/event.py`** *(modify)* — pure `launch_env(app, platform, env, exists)` (headless DISPLAY/XAUTHORITY).
- **`src/racecast.py`** *(modify)* — `_part_index`, `_part_path`, `_write_part_reset` + `event_start` reset; `_event_launch` passes `env=` from `ev.launch_env`.
- **`src/director/director-panel.html`** *(modify)* — Part-aware control + typed-confirm `<dialog>` + fallback.
- **`tools/cloud/provision.sh`** *(modify)* — xfce autostart entries for OBS + Discord.
- **Tests:** `tests/test_parts.py` *(new)*; extend `tests/test_console.py`, `tests/test_event.py`, `tests/test_racecast.py`.
- **Docs:** `src/docs/wiki/images/director-panel.png`, `src/docs/wiki/Run-an-event.md`, `tools/cloud/README.md`, `src/docs/wiki/Sheet-Webhook.md`.

---

### Task 1: Pure Part logic — `src/scripts/parts.py`

**Files:**
- Create: `src/scripts/parts.py`
- Test: `tests/test_parts.py`

**Interfaces:**
- Produces:
  - `normalize_intent(text) -> str` — collapse whitespace + uppercase.
  - `parts_intent_phrase(action, index) -> str` — e.g. `("start", 2)` → `"START PART 2"`.
  - `parts_view_model(producer_rows, state, stream_active=None) -> dict` — the `/parts/data` payload. `producer_rows` = list of `{"part","producer","magicdns","stream_key"}`; `state` = `{"index":int,"live":bool}`; `stream_active` = OBS truth (None → use `state["live"]`). Keys: `enabled, count, index, live, parts[], platform, complete, current_label, producer, action("start"|"end"|None), confirm_phrase, next_index`. Never includes a stream key/ref.
  - `validate_start(body, state, count) -> (True, index) | (False, (error, http_status))`.
  - `validate_end(body, state) -> (True, index) | (False, (error, http_status))`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parts.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for broadcast Part control (src/scripts/parts.py + relay
PartStore/ProducerSource/apply). Run: python3 tests/test_parts.py"""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import parts as m  # pure module

# relay module (hyphenated filename -> load by path); used from Task 2 on.
_rspec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
R = importlib.util.module_from_spec(_rspec); _rspec.loader.exec_module(R)

ROWS3 = [{"part": "Part 1", "producer": "A", "magicdns": "a", "stream_key": "key1"},
         {"part": "Part 2", "producer": "B", "magicdns": "b", "stream_key": "key2"},
         {"part": "Part 3", "producer": "C", "magicdns": "c", "stream_key": "key3"}]


def t_parts_intent_phrase():
    assert m.parts_intent_phrase("start", 1) == "START PART 1"
    assert m.parts_intent_phrase("end", 3) == "END PART 3"


def t_normalize_intent():
    assert m.normalize_intent("  end   part 2 ") == "END PART 2"
    assert m.normalize_intent("Start Part 1") == "START PART 1"
    assert m.normalize_intent(None) == ""


def t_view_model_ready_offers_start():
    vm = m.parts_view_model(ROWS3, {"index": 1, "live": False}, stream_active=False)
    assert vm["enabled"] and vm["count"] == 3
    assert vm["action"] == "start" and vm["index"] == 1
    assert vm["confirm_phrase"] == "START PART 1" and vm["complete"] is False
    assert len(vm["parts"]) == 3 and vm["parts"][1]["label"] == "Part 2"


def t_view_model_live_offers_end_from_obs():
    # file says not live, OBS says active -> OBS wins (authoritative)
    vm = m.parts_view_model(ROWS3, {"index": 1, "live": False}, stream_active=True)
    assert vm["live"] is True and vm["action"] == "end"
    assert vm["confirm_phrase"] == "END PART 1"


def t_view_model_after_end_offers_next():
    vm = m.parts_view_model(ROWS3, {"index": 2, "live": False}, stream_active=False)
    assert vm["action"] == "start" and vm["index"] == 2
    assert vm["confirm_phrase"] == "START PART 2" and vm["next_index"] == 3


def t_view_model_last_part_complete():
    vm = m.parts_view_model(ROWS3, {"index": 4, "live": False}, stream_active=False)
    assert vm["complete"] is True and vm["action"] is None


def t_view_model_no_parts_disabled():
    vm = m.parts_view_model([], {"index": 1, "live": False}, stream_active=False)
    assert vm["enabled"] is False and vm["action"] is None


def t_view_model_falls_back_to_file_live():
    vm = m.parts_view_model(ROWS3, {"index": 2, "live": True}, stream_active=None)
    assert vm["live"] is True and vm["action"] == "end" and vm["index"] == 2


def t_validate_start_ok():
    ok, res = m.validate_start({"index": 1, "intent": "START PART 1"},
                               {"index": 1, "live": False}, 3)
    assert ok and res == 1


def t_validate_start_bad_phrase():
    ok, res = m.validate_start({"index": 1, "intent": "go"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 403


def t_validate_start_wrong_index():
    ok, res = m.validate_start({"index": 2, "intent": "START PART 2"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 409


def t_validate_start_bad_index_type():
    ok, res = m.validate_start({"index": "x", "intent": "START PART x"},
                               {"index": 1, "live": False}, 3)
    assert not ok and res[1] == 400


def t_validate_end_ok():
    ok, res = m.validate_end({"intent": "END PART 2"}, {"index": 2, "live": True})
    assert ok and res == 2


def t_validate_end_bad_phrase():
    ok, res = m.validate_end({"intent": "nope"}, {"index": 2, "live": True})
    assert not ok and res[1] == 403


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run the pure-module tests to verify they fail**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'parts'` (the module does not exist yet). (The relay-module load `R` is only exercised from Task 2; if it errors first, that is fine — create `parts.py` next.)

- [ ] **Step 3: Create `src/scripts/parts.py`**

```python
"""Pure helpers for Director-Panel broadcast Part control (#395 follow-up).

Broadcast Parts (from the Sheet `Producer` tab) are the coarse segments a long
race is split into — each a separate YouTube broadcast with its own stream key.
This module holds the side-effect-free logic behind the panel's Part control:
the typed-confirmation phrase, the /parts/data view model, and the request
validators. All I/O (Sheet fetch, obs-websocket, the get_stream_key webhook)
lives in the relay; nothing here touches the network, disk, or a stream key."""


def normalize_intent(text):
    """Collapse whitespace and uppercase, so '  end  part 2 ' == 'END PART 2'."""
    return " ".join((text or "").split()).upper()


def parts_intent_phrase(action, index):
    """The exact confirmation phrase for an action on a 1-based Part index —
    ('start', 2) -> 'START PART 2'. The panel shows it and the relay
    re-validates the typed value against it."""
    return "{} PART {}".format(str(action).upper(), int(index))


def parts_view_model(producer_rows, state, stream_active=None):
    """Build the /parts/data payload from the parsed Producer rows, the persisted
    part state ({"index","live"}), and the OBS live truth (stream_active; None ->
    trust the stored flag). Pure. Never returns a stream key or ref.

    Semantics of {index, live}: `index` is 1-based into the Producer order and is
    the Part to act on — the currently-live Part while live, or the next Part to
    start while offline. The End action advances `index`; Start marks it live."""
    rows = producer_rows or []
    count = len(rows)
    index = int(state.get("index", 1))
    live = bool(state.get("live", False)) if stream_active is None else bool(stream_active)
    parts = [{"index": i + 1,
              "label": (r.get("part") or "Part {}".format(i + 1)),
              "producer": r.get("producer") or ""}
             for i, r in enumerate(rows)]
    vm = {"enabled": count > 0, "count": count, "index": index, "live": live,
          "parts": parts, "platform": None, "complete": False,
          "current_label": "", "producer": "",
          "action": None, "confirm_phrase": None, "next_index": None}
    if count == 0:
        return vm
    if live:
        li = index if 1 <= index <= count else count
        vm["index"] = li
        vm["current_label"] = parts[li - 1]["label"]
        vm["producer"] = parts[li - 1]["producer"]
        vm["action"] = "end"
        vm["confirm_phrase"] = parts_intent_phrase("end", li)
    elif index > count:
        vm["complete"] = True
    else:
        vm["current_label"] = parts[index - 1]["label"]
        vm["producer"] = parts[index - 1]["producer"]
        vm["action"] = "start"
        vm["confirm_phrase"] = parts_intent_phrase("start", index)
        vm["next_index"] = index + 1 if index + 1 <= count else None
    return vm


def validate_start(body, state, count):
    """Validate a /parts/start request. Pure. Returns (True, index) or
    (False, (error, http_status)). The intent phrase is the anti-accident gate;
    the index must equal the expected next Part (stale-tablet guard)."""
    try:
        idx = int(body.get("index"))
    except (TypeError, ValueError):
        return False, ("index must be a number", 400)
    if normalize_intent(body.get("intent")) != parts_intent_phrase("start", idx):
        return False, ("confirmation phrase mismatch", 403)
    if idx != int(state.get("index", 1)) or not (1 <= idx <= count):
        return False, ("Part {} is not the next Part to start".format(idx), 409)
    return True, idx


def validate_end(body, state):
    """Validate a /parts/end request against the currently-focused Part. Pure."""
    idx = int(state.get("index", 1))
    if normalize_intent(body.get("intent")) != parts_intent_phrase("end", idx):
        return False, ("confirmation phrase mismatch", 403)
    return True, idx
```

- [ ] **Step 4: Run the pure-module tests to verify they pass**

Run: `python3 tests/test_parts.py`
Expected: `ok t_normalize_intent` … through all `t_view_model_*` / `t_validate_*` … `ALL PASS`. (The relay `R` load must succeed too — the relay imports nothing new yet, so it loads fine.)

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no findings.

```bash
git add src/scripts/parts.py tests/test_parts.py
git commit -m "feat(parts): pure Part logic — intent phrase, view model, validators"
```

---

### Task 2: Relay `PartStore` + `apply_stream_service_for_ref`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add near `EventTitleStore`, ~line 1366; add the module-level apply function near `post_webhook`, ~line 1324; add imports near the other `src/scripts` imports, ~line 100)
- Test: `tests/test_parts.py` (extend)

**Interfaces:**
- Consumes: `producer.parse_producer_rows`, `stream_target.event_platform`, `stream_target.parse_stream_key_response`, `broadcast_chat.parse_channel_tab`, `post_webhook`, `TimerStore._fetch`, `obs_ws.set_stream_service`.
- Produces:
  - `default_part_state() -> {"index":1,"live":False}`.
  - `PartStore(path)` with `.get() -> dict`, `.mark_live(index) -> dict` (`{index, True}`), `.end() -> dict` (`{index+1, False}`). Best-effort, lock-guarded, type-checked load (mirrors `TimerStore`/`EventTitleStore`).
  - `apply_stream_service_for_ref(ref, channel_csv_url, push_url, set_service, fetch=None, post=None) -> (ok, note)` — note NEVER contains the key.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_parts.py`, before the `__main__` block)

```python
def t_partstore_default_and_transitions():
    d = tempfile.mkdtemp()
    ps = R.PartStore(os.path.join(d, "part.json"))
    assert ps.get() == {"index": 1, "live": False}
    assert ps.mark_live(1) == {"index": 1, "live": True}
    assert ps.end() == {"index": 2, "live": False}
    # persisted -> a fresh store reloads the advanced pointer
    ps2 = R.PartStore(os.path.join(d, "part.json"))
    assert ps2.get() == {"index": 2, "live": False}


def t_partstore_ignores_corrupt_file():
    d = tempfile.mkdtemp(); p = os.path.join(d, "part.json")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert R.PartStore(p).get() == {"index": 1, "live": False}


def t_partstore_type_checks_load():
    d = tempfile.mkdtemp(); p = os.path.join(d, "part.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"index": "x", "live": "yes"}, fh)
    assert R.PartStore(p).get() == {"index": 1, "live": False}


def t_apply_stream_service_for_ref_happy():
    calls, seen = {}, {}
    def fetch(u):
        return "Platform,Channel\nyoutube,@x\n"
    def post(u, o):
        calls["ref"] = o["ref"]
        return b'{"ok":true,"action":"get_stream_key","key":"SECRET"}'
    def set_service(platform, key):
        seen["p"] = platform; seen["k"] = key; return True, "ok"
    ok, note = R.apply_stream_service_for_ref("key2", "http://chan", "http://push",
                                              set_service, fetch=fetch, post=post)
    assert ok and calls["ref"] == "key2" and seen["p"] == "youtube" and seen["k"] == "SECRET"
    assert "SECRET" not in note   # key never leaks into the note


def t_apply_stream_service_for_ref_webhook_error():
    def fetch(u):
        return "Platform,Channel\nyoutube,@x\n"
    def post(u, o):
        return b'{"ok":false,"error":"bad ref"}'
    ok, note = R.apply_stream_service_for_ref("keyX", "c", "p",
                                              lambda a, b: (True, ""),
                                              fetch=fetch, post=post)
    assert not ok and note == "bad ref"


def t_apply_stream_service_for_ref_no_push_url():
    ok, note = R.apply_stream_service_for_ref("k", "c", "",
                                              lambda a, b: (True, ""))
    assert not ok and "SHEET_PUSH_URL" in note
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'PartStore'`.

- [ ] **Step 3: Add the imports** (near the block that does `import broadcast_chat` / `import cue_admin`, ~line 100 of `src/relay/racecast-feeds.py`)

```python
import producer        # noqa: E402 — pure Producer-tab parser (Part -> stream-key ref)
import stream_target   # noqa: E402 — pure stream-target resolver (ref/platform/key response)
import parts           # noqa: E402 — pure Part view-model + validators (#395)
```

- [ ] **Step 4: Add `apply_stream_service_for_ref`** (module-level, right after `check_webhook_response`, ~line 1349)

```python
def apply_stream_service_for_ref(ref, channel_csv_url, push_url, set_service,
                                 fetch=None, post=None):
    """Resolve the event platform (Channel tab) + the real stream key
    (get_stream_key webhook) for a stream-key `ref`, and apply it to OBS via
    set_service(platform, key). Returns (ok, note); `note` NEVER contains the
    key. Relay-side twin of racecast.py::_apply_stream_target. Seams: `fetch`
    (CSV text) and `post` (webhook) for tests."""
    fetch = fetch or (lambda u: TimerStore._fetch(u))
    post = post or post_webhook
    if not push_url:
        return False, "no SHEET_PUSH_URL — the stream-key webhook is required"
    try:
        chan_rows = broadcast_chat.parse_channel_tab(fetch(channel_csv_url))
    except Exception as exc:                            # noqa: BLE001 — tolerant fetch
        return False, "channel fetch failed: {}".format(type(exc).__name__)
    platform = stream_target.event_platform(chan_rows)
    if not platform:
        return False, "no channel/platform configured (Channel tab)"
    try:
        body = post(push_url, {"action": "get_stream_key", "ref": ref})
    except Exception as exc:                            # noqa: BLE001 — tolerant webhook
        return False, "stream-key webhook failed: {}".format(type(exc).__name__)
    key, err = stream_target.parse_stream_key_response(body)
    if err:
        return False, err
    ok, note = set_service(platform, key)
    del key   # drop our last named reference to the key before returning
    if not ok:
        return False, note
    return True, "stream target set on {}".format(platform)
```

- [ ] **Step 5: Add `default_part_state` + `PartStore`** (right before the `EventTitleStore` class, ~line 1366)

```python
def default_part_state():
    return {"index": 1, "live": False}


class PartStore:
    """Persisted broadcast-Part pointer at runtime/<profile>/part.json.

    State {"index": N (1-based into the Producer order), "live": bool}. Reset to
    Part 1 by `racecast event start`; End advances `index`; Start marks it live.
    `live` is a written record only — the panel derives the authoritative live
    state from OBS. Same best-effort, lock-guarded, type-checked-load contract as
    TimerStore/EventTitleStore (a hand-edited file must never crash later)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.state = default_part_state()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            pass  # fresh layout; _save_file degrades per-write if the dir is missing
        self._load_file()

    def _load_file(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return  # no/corrupt file -> defaults
        st = default_part_state()
        if isinstance(saved, dict):
            idx = saved.get("index")
            if isinstance(idx, int) and not isinstance(idx, bool) and idx >= 1:
                st["index"] = idx
            if isinstance(saved.get("live"), bool):
                st["live"] = saved["live"]
        self.state = st

    def _save_file(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh)
        except OSError:
            pass  # best-effort, same contract as the timer/event caches

    def get(self):
        with self.lock:
            return dict(self.state)

    def mark_live(self, index):
        with self.lock:
            self.state = {"index": int(index), "live": True}
            self._save_file()
            return dict(self.state)

    def end(self):
        with self.lock:
            self.state = {"index": int(self.state["index"]) + 1, "live": False}
            self._save_file()
            return dict(self.state)
```

- [ ] **Step 6: Run to verify they pass**

Run: `python3 tests/test_parts.py`
Expected: all `t_partstore_*` and `t_apply_stream_service_for_ref_*` print `ok …`; `ALL PASS`.

- [ ] **Step 7: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no findings.

```bash
git add src/relay/racecast-feeds.py tests/test_parts.py
git commit -m "feat(parts): relay PartStore + stream-key apply (key stays server-side)"
```

---

### Task 3: Relay `ProducerSource`, `/parts/*` routes, wiring, policy

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `ProducerSource` near `ChannelSource` ~line 1850; add GET block in `do_GET` near the `/timer`/`/chat` blocks ~line 6600; add POST blocks in `do_POST` near the `/obs/*` blocks ~line 7150; add argparse + source/store construction in `main()` ~lines 7291/7458)
- Modify: `src/scripts/console_policy.py` (after the `p[0] == "obs"` rule, ~line 77)
- Test: `tests/test_parts.py` (ProducerSource), `tests/test_console.py` (policy)

**Interfaces:**
- Consumes: `PartStore`, `apply_stream_service_for_ref`, `parts.*`, `producer.parse_producer_rows`, `stream_target.event_platform`, `_obs_ws.read_obs_state`, `_obs_ws.set_stream`, `_obs_ws.set_stream_service`, `post_webhook`.
- Produces: `ProducerSource(csv_url, cache_path=None)` with `.refresh()` / `.get() -> list[dict]`; the relay endpoints `GET /parts/data`, `POST /parts/start`, `POST /parts/end`; the closure locals `producer_source`, `part_store`, `channel_csv_url`, `push_url`.

- [ ] **Step 1: Write the failing ProducerSource + policy tests**

Append to `tests/test_parts.py` (before `__main__`):

```python
def t_producer_source_empty_when_no_url():
    assert R.ProducerSource(None).get() == []


def t_producer_source_parses_on_refresh():
    ps = R.ProducerSource("http://x")
    ps._fetch_text = lambda timeout=15: (
        "Part,Producer,MagicDNS,Stream Key\nPart 1,A,a,key1\nPart 2,B,b,key2\n")
    assert ps.refresh() is True
    assert ps.get() == [
        {"part": "Part 1", "producer": "A", "magicdns": "a", "stream_key": "key1"},
        {"part": "Part 2", "producer": "B", "magicdns": "b", "stream_key": "key2"}]
```

Add to `tests/test_console.py` (follow that file's existing module-load alias — here shown as `m`; place beside the existing OBS-policy test):

```python
def t_parts_requires_director():
    assert m.min_capability(["parts", "data"]) == m.Requirement(m.DIRECTOR, False)
    assert m.min_capability(["parts", "start"]) == m.Requirement(m.DIRECTOR, False)
    assert m.min_capability(["parts", "end"]) == m.Requirement(m.DIRECTOR, False)
```

- [ ] **Step 2: Run both to verify they fail**

Run: `python3 tests/test_parts.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'ProducerSource'`.
Run: `python3 tests/test_console.py`
Expected: FAIL — `t_parts_requires_director` gets `NOT_FOUND`/`None`, not `Requirement(DIRECTOR, False)`.

- [ ] **Step 3: Add the `parts` policy rule** (`src/scripts/console_policy.py`, immediately after the `p[0] == "obs"` rule at ~line 77)

```python
    if p and p[0] == "parts":                   # relay-mediated broadcast Part control (#395)
        return Requirement(DIRECTOR, False)
```

- [ ] **Step 4: Add `ProducerSource`** (`src/relay/racecast-feeds.py`, right after `ChannelSource`, ~line 1888)

```python
class ProducerSource:
    """Reads the Sheet `Producer` tab (CSV) -> [{"part","producer","magicdns",
    "stream_key"}] via the pure producer.parse_producer_rows. Same tolerant
    fetch+lock+cache shape as ChannelSource; a missing/empty/unreachable tab
    yields no parts, so the panel falls back to the plain GO-LIVE button."""

    def __init__(self, csv_url, cache_path=None):
        self.csv_url = csv_url
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.rows = []
        self.last_error = None

    def _fetch_text(self, timeout=15):
        if not self.csv_url:
            return None
        try:
            req = Request(self.csv_url, headers={"User-Agent": "racecast-feeds/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:                          # noqa: BLE001 — tolerant
            self.last_error = "{}: {}".format(type(e).__name__, e)
            return None

    def refresh(self, timeout=15):
        text = self._fetch_text(timeout)
        if text is None:
            return False
        rows = producer.parse_producer_rows(text)
        with self.lock:
            self.rows = rows
            self.last_error = None
        return True

    def get(self):
        with self.lock:
            return list(self.rows)
```

- [ ] **Step 5: Add the `GET /parts/data` route** (`do_GET`, beside the `/timer`/`/chat` blocks, ~line 6620)

```python
                if p[:1] == ["parts"]:
                    if part_store is None or producer_source is None:
                        return self._send({"enabled": False})   # feature off -> panel fallback
                    if p == ["parts", "data"]:
                        rows = producer_source.get()
                        active = None
                        if _obs_ws is not None:
                            st, _n = _obs_ws.read_obs_state([], [])
                            if isinstance(st, dict) and isinstance(st.get("stream"), dict):
                                active = bool(st["stream"].get("active"))
                        vm = parts.parts_view_model(rows, part_store.get(), active)
                        if channel_source is not None:
                            vm["platform"] = stream_target.event_platform(
                                channel_source.get()) or None
                        return self._send(vm)
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

- [ ] **Step 6: Add the `POST /parts/start` + `/parts/end` routes** (`do_POST`, beside the `/obs/*` blocks, ~line 7169)

```python
                if p == ["parts", "start"]:
                    if part_store is None or producer_source is None or _obs_ws is None:
                        return self._send({"ok": False, "error": "parts unavailable"}, 503)
                    rows = producer_source.get()
                    ok, res = parts.validate_start(body, part_store.get(), len(rows))
                    if not ok:
                        return self._send({"ok": False, "error": res[0]}, res[1])
                    idx = res
                    st, _n = _obs_ws.read_obs_state([], [])
                    if (isinstance(st, dict) and isinstance(st.get("stream"), dict)
                            and st["stream"].get("active")):
                        return self._send({"ok": False,
                            "error": "already streaming — end the current Part first"}, 409)
                    ref = (rows[idx - 1].get("stream_key") or "").strip()
                    if not ref:
                        return self._send({"ok": False,
                            "error": "Part {} has no stream-key reference "
                                     "(Producer tab)".format(idx)}, 400)
                    ok2, note = apply_stream_service_for_ref(
                        ref, channel_csv_url, push_url, _obs_ws.set_stream_service)
                    if not ok2:
                        return self._send({"ok": False, "error": note}, 502)
                    ok3, note3 = _obs_ws.set_stream(True)
                    if not ok3:
                        return self._send({"ok": False, "error": note3}, 503)
                    part_store.mark_live(idx)
                    return self._send({"ok": True, "index": idx})
                if p == ["parts", "end"]:
                    if part_store is None or _obs_ws is None:
                        return self._send({"ok": False, "error": "parts unavailable"}, 503)
                    ok, res = parts.validate_end(body, part_store.get())
                    if not ok:
                        return self._send({"ok": False, "error": res[0]}, res[1])
                    ok2, note = _obs_ws.set_stream(False)
                    if not ok2:
                        return self._send({"ok": False, "error": note}, 503)
                    part_store.end()
                    return self._send({"ok": True, "index": res})
```

- [ ] **Step 7: Wire `main()` — argparse flags** (after the `--channel-tab` argument, ~line 7292)

```python
    ap.add_argument("--producer-tab", default="Producer",
                    help="Sheet tab mapping broadcast Part -> stream-key ref (#395)")
    ap.add_argument("--no-parts", action="store_true",
                    help="disable the Director-Panel broadcast Part control")
```

- [ ] **Step 8: Wire `main()` — build the channel URL once, construct the sources + store**

Hoist `channel_csv_url` so both the broadcast-chat reader and the Part control use it. Replace the existing `channel_source` construction block (~lines 7458-7465) with:

```python
    channel_csv_url = None
    if not args.sheet_csv_url:
        channel_csv_url = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                           f"/gviz/tq?tqx=out:csv&sheet={quote(args.channel_tab)}")
    channel_source = None
    broadcast_chat_store = None
    if channel_csv_url and not args.no_broadcast_chat:
        channel_cache = os.path.join(runtime, "channel.cache.txt")
        channel_source = ChannelSource(channel_csv_url, channel_cache)
        broadcast_chat_store = BroadcastChatStore()

    # Broadcast Part control (#395): the Producer-tab Part list + the persisted
    # part.json pointer. Disabled under a custom --sheet-csv-url or --no-parts;
    # part_store is always present (a missing file -> {index:1, live:False}).
    producer_source = None
    if channel_csv_url and not args.no_parts:
        producer_csv_url = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                            f"/gviz/tq?tqx=out:csv&sheet={quote(args.producer_tab)}")
        producer_source = ProducerSource(producer_csv_url,
                                         os.path.join(runtime, "producer.cache.txt"))
        producer_source.refresh()   # non-fatal: prime the Part list on startup
    part_store = PartStore(os.path.join(runtime, "part.json"))
```

- [ ] **Step 9: Wire `main()` — periodic refresh**

Find the background refresher that calls `channel_source.refresh()` (grep `channel_source.refresh`) and add, right beside it:

```python
                if producer_source is not None:
                    producer_source.refresh()   # Parts change rarely; same cadence is fine
```

Confirm `producer_source`, `part_store`, `channel_csv_url`, and `push_url` are in scope for the handler (they are `main()` locals captured by the nested handler class, defined before `make_handler`/`run` — same as `timer_store`/`chat_store`).

- [ ] **Step 10: Run the tests to verify they pass**

Run: `python3 tests/test_parts.py`
Expected: `t_producer_source_*` print `ok …`; `ALL PASS`.
Run: `python3 tests/test_console.py`
Expected: `ok t_parts_requires_director`; suite passes.

- [ ] **Step 11: Smoke-check the relay imports cleanly, then lint + commit**

Run: `python3 -c "import importlib.util,os; s=importlib.util.spec_from_file_location('r','src/relay/racecast-feeds.py'); mm=importlib.util.module_from_spec(s); s.loader.exec_module(mm); print('relay import OK')"`
Expected: `relay import OK` (no ImportError from the new `producer`/`stream_target`/`parts` imports).

Run: `python3 tools/lint.py`
Expected: no findings.

```bash
git add src/relay/racecast-feeds.py src/scripts/console_policy.py tests/test_parts.py tests/test_console.py
git commit -m "feat(parts): relay /parts/* routes + ProducerSource + director policy"
```

---

### Task 4: `event start` Part reset + `--part N`

**Files:**
- Modify: `src/racecast.py` (add helpers near `_stint_args` ~line 2628 and `_event_title_path` ~line 618; call in `event_start` ~line 3034)
- Test: `tests/test_racecast.py` (extend; follow that file's existing module-load alias)

**Interfaces:**
- Consumes: `_runtime_dir()`.
- Produces: `_part_index(rest) -> int` (default 1; `sys.exit` on invalid); `_part_path() -> str`; `_write_part_reset(index)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_racecast.py`; `m` = its loaded `racecast` module)

```python
def t_part_index_default_and_parse():
    assert m._part_index([]) == 1
    assert m._part_index(["--part", "2"]) == 2
    assert m._part_index(["--part=3"]) == 3


def t_part_index_rejects_bad():
    for bad in (["--part", "0"], ["--part", "x"], ["--part=-1"]):
        try:
            m._part_index(bad)
            raise AssertionError("expected SystemExit for {!r}".format(bad))
        except SystemExit:
            pass


def t_write_part_reset_writes_file():
    import json as _json, tempfile as _tf
    d = _tf.mkdtemp()
    orig = m._runtime_dir
    m._runtime_dir = lambda: d
    try:
        m._write_part_reset(2)
        with open(m._part_path(), encoding="utf-8") as fh:
            assert _json.load(fh) == {"index": 2, "live": False}
    finally:
        m._runtime_dir = orig
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module '…' has no attribute '_part_index'`.

- [ ] **Step 3: Add the helpers** (`src/racecast.py`, near `_event_title_path`, ~line 622)

```python
def _part_index(rest):
    """Extract + validate a --part flag ("--part 2" / "--part=2"), mirroring
    _stint_args. Default 1. Exits on an invalid value (fail fast before the
    detached relay is spawned)."""
    for i, tok in enumerate(rest):
        val = None
        if tok == "--part" and i + 1 < len(rest):
            val = rest[i + 1]
        elif tok.startswith("--part="):
            val = tok.split("=", 1)[1]
        if val is not None:
            if not val.isdigit() or int(val) < 1:
                sys.exit("--part must be a 1-based Part number (got {!r}).".format(val))
            return int(val)
    return 1


def _part_path():
    """The active profile's persisted broadcast-Part pointer. The relay's
    PartStore loads this on construction, so writing it before bring-up sets the
    Part the relay comes up on."""
    return os.path.join(_runtime_dir(), "part.json")


def _write_part_reset(index):
    """Reset the broadcast-Part pointer to Part `index`, not-live. `event start`
    is the one reliable reset point (every event begins with it; a clean
    last-Part-stop / event stop can't be detected). A fresh relay adopts this on
    construction; writing while a relay already runs is inert (PartStore loads
    once at start) — so a mid-event re-run does not disturb the live pointer, and
    recovery is `event start --part N` + a relay restart. Best-effort."""
    path = _part_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"index": int(index), "live": False}, fh)
    except OSError as exc:
        print("note: could not reset part.json ({}) — continuing.".format(exc))
```

- [ ] **Step 4: Call it in `event_start`** (`src/racecast.py`, immediately before the `relay_start(...)` call at ~line 3034)

```python
    # 3. Relay (before OBS — see docstring). Reset the broadcast-Part pointer to
    # Part 1 (or --part N for a mid-event recovery restart) BEFORE the relay
    # starts, so its PartStore comes up on the right Part.
    _write_part_reset(_part_index(rest))
    relay_start(_stint_args(rest) + _qualifying_args(rest) + _title_args(rest))
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: `ok t_part_index_default_and_parse`, `ok t_part_index_rejects_bad`, `ok t_write_part_reset_writes_file`; suite passes.

- [ ] **Step 6: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no findings.

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(event): reset the broadcast-Part pointer at event start (--part N)"
```

---

### Task 5: Headless GUI launch env (SSH, no RustDesk)

**Files:**
- Modify: `src/scripts/event.py` (add `launch_env` after `launch_command`, ~line 123)
- Modify: `src/racecast.py` (`_event_launch`, ~line 2857 — pass `env=`)
- Test: `tests/test_event.py` (extend)

**Interfaces:**
- Produces: `launch_env(app, platform, env=None, exists=os.path.exists) -> dict` — env overrides (`DISPLAY`, optional `XAUTHORITY`) for a headless GUI launch, `{}` when none are needed.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_event.py`, before `__main__`)

```python
def t_launch_env_linux_ssh_sets_display():
    env = {"HOME": "/home/op"}
    out = m.launch_env("obs", "linux", env, exists=lambda p: p == "/home/op/.Xauthority")
    assert out == {"DISPLAY": ":0", "XAUTHORITY": "/home/op/.Xauthority"}


def t_launch_env_display_without_xauthority():
    out = m.launch_env("discord", "linux", {"HOME": "/h"}, exists=lambda p: False)
    assert out == {"DISPLAY": ":0"}


def t_launch_env_respects_existing_display():
    assert m.launch_env("obs", "linux", {"DISPLAY": ":1", "HOME": "/h"}) == {}


def t_launch_env_racecast_display_override():
    out = m.launch_env("discord", "linux",
                       {"RACECAST_DISPLAY": ":7", "HOME": "/h"}, exists=lambda p: False)
    assert out == {"DISPLAY": ":7"}


def t_launch_env_noop_non_linux():
    assert m.launch_env("obs", "darwin", {}) == {}
    assert m.launch_env("obs", "win32", {}) == {}


def t_launch_env_noop_non_gui():
    assert m.launch_env("tailscale", "linux", {"HOME": "/h"}) == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_event.py`
Expected: FAIL — `AttributeError: module 'event' has no attribute 'launch_env'`.

- [ ] **Step 3: Add `launch_env`** (`src/scripts/event.py`, after `launch_command`, ~line 123)

```python
def launch_env(app, platform, env=None, exists=os.path.exists):
    """Environment overrides for a headless GUI launch, or {} when none are
    needed. On Linux, launching a GUI app (obs/discord) from a shell with no
    DISPLAY (a bare SSH session) can't reach the autologin X session; point it
    there so `racecast event start` works over SSH without RustDesk.
    RACECAST_DISPLAY overrides the display (default ':0'); XAUTHORITY is
    discovered from the login user's ~/.Xauthority. A non-Linux platform, a
    non-GUI app, or an already-set DISPLAY -> {} (leave the env untouched)."""
    env = os.environ if env is None else env
    if not platform.startswith("linux"):
        return {}
    if app not in ("obs", "discord"):
        return {}
    if env.get("DISPLAY"):
        return {}
    out = {"DISPLAY": env.get("RACECAST_DISPLAY") or ":0"}
    xauth = env.get("XAUTHORITY")
    if not xauth:
        home = env.get("HOME") or ""
        # Explicit '/': this is a Linux-only path — os.path.join would inject a
        # backslash on the Windows CI runner (CLAUDE cross-platform-paths rule).
        cand = home + "/.Xauthority" if home else ""
        if cand and exists(cand):
            xauth = cand
    if xauth:
        out["XAUTHORITY"] = xauth
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_event.py`
Expected: all `t_launch_env_*` print `ok …`; `ALL PASS`.

- [ ] **Step 5: Wire `_event_launch` to pass the env** (`src/racecast.py`, ~line 2871 — replace the `argv, cwd = cmd` … `subprocess.Popen(...)` region)

```python
    argv, cwd = cmd
    overrides = ev.launch_env(app, sys.platform)
    launch_env = None
    if overrides:
        launch_env = dict(os.environ)
        launch_env.update(overrides)
        print("{}: targeting the autologin session ({}).".format(
            app, ", ".join("{}={}".format(k, v) for k, v in sorted(overrides.items()))))
    print(f"{app}: launching…")
    try:
        subprocess.Popen(argv, cwd=cwd, env=launch_env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sv.spawn_kwargs(os.name))
    except OSError as exc:
        print(f"{app}: launch failed ({exc}).")
        return False
    return True
```

(`env=None` preserves today's behavior — the child inherits `os.environ`. Only a non-empty `overrides` builds an augmented env.)

- [ ] **Step 6: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no findings.

```bash
git add src/scripts/event.py src/racecast.py tests/test_event.py
git commit -m "feat(event): headless DISPLAY/XAUTHORITY for OBS+Discord launch over SSH"
```

---

### Task 6: Director Panel — Part-aware control + typed-confirm modal

**Files:**
- Modify: `src/director/director-panel.html`
- Modify (regenerate): `src/docs/wiki/images/director-panel.png`

**Interfaces:**
- Consumes: `GET /parts/data`, `POST /parts/start {index,intent}`, `POST /parts/end {intent}` (Task 3); `RC_API`, the patched `fetch`, `renderStreamBtn`, `obsStatePoll`, `#obsStreamBtn`, `log`.

**No unit test** (HTML/JS). Correctness of the underlying logic is covered by Tasks 1–3; this task is verified by the superpowers UI **visual-verification** gate and the refreshed wiki screenshot. Recipe: run a local dev build from `src/` (`python3 src/racecast.py ui` / relay) against the **demo** profile with `tools/obs-sim.py` as the OBS stand-in (see the `wiki-screenshots` skill).

- [ ] **Step 1: Add the Part control markup** — next to the stream button (`src/director/director-panel.html`, replace line 510's `<button … id="obsStreamBtn" hidden>OFFLINE</button></div>`)

```html
      <button class="k stream" id="obsStreamBtn" hidden>OFFLINE</button>
      <div id="partControl" class="partctl" hidden>
        <span id="partStatus" class="partstatus">Part —</span>
        <button class="k stream" id="partActionBtn" hidden>Start Part 1</button>
      </div></div>
```

- [ ] **Step 2: Add the typed-confirmation `<dialog>`** — beside the existing `#notesModal` (~line 2419)

```html
<dialog id="partModal" class="notesmodal partmodal">
  <h3 id="partModalTitle">Confirm</h3>
  <div id="partModalBody" class="notesbody"></div>
  <p class="partphraseline">Type <code id="partModalPhrase"></code> to confirm:</p>
  <input id="partModalInput" type="text" autocomplete="off" autocapitalize="characters"
         spellcheck="false" class="partinput" />
  <div class="notesactions">
    <button type="button" onclick="document.getElementById('partModal').close()">Cancel</button>
    <button type="button" id="partModalConfirm" onclick="submitPart()" disabled>Confirm</button>
  </div>
</dialog>
```

- [ ] **Step 3: Add the CSS** — after the `.notesmodal` block (~line 448)

```css
  .partctl { display: flex; align-items: center; gap: 8px; }
  .partstatus { font-weight: 700; font-size: 13px; opacity: .85; }
  .partstatus.live { color: #ff5a5a; }
  .partstatus.done { opacity: .6; }
  .partmodal .partphraseline { margin: 14px 0 6px; }
  .partmodal code { background: #0d0f14; padding: 2px 6px; border-radius: 4px; }
  .partinput { width: 100%; padding: 8px; font: 700 15px monospace; letter-spacing: .5px;
    background: #0d0f14; color: #e8eaed; border: 1px solid #3a3f4a; border-radius: 6px; }
  #partModalConfirm:disabled { opacity: .4; cursor: not-allowed; }
```

- [ ] **Step 4: Add the JS** — a `partsPoll`, the renderer, the modal, and the submit; and make `renderStreamBtn` yield to the Part control. Insert near `renderStreamBtn`/`obsStatePoll` (~line 1056) and bootstrap beside the existing `obsStatePoll()` bootstrap (~line 2380).

```javascript
let partsEnabled = false, partsState = null;
const normIntent = s => (s || "").trim().replace(/\s+/g, " ").toUpperCase();

async function partsPoll(){
  let d;
  try { d = await (await fetch(RC_API("/parts/data"), {cache:"no-store"})).json(); }
  catch(e){ return; }
  partsState = d;
  renderPartControl(d);
}

function renderPartControl(d){
  const wrap = $("#partControl"), btn = $("#partActionBtn"), status = $("#partStatus");
  partsEnabled = !!(d && d.enabled);
  if (!partsEnabled){ wrap.hidden = true; return; }   // fallback: #obsStreamBtn (obsStatePoll)
  wrap.hidden = false;
  $("#obsStreamBtn").hidden = true;                   // Part control supersedes the generic button
  const M = d.count;
  if (d.action === "end"){
    status.textContent = `● LIVE — Part ${d.index} of ${M}`;
    status.className = "partstatus live";
    btn.hidden = false; btn.textContent = `End Part ${d.index}`; btn.className = "k stream live";
  } else if (d.action === "start"){
    status.textContent = d.index > 1
      ? `Part ${d.index - 1} ended — Next: Part ${d.index} of ${M}`
      : `Part ${d.index} of ${M} — OFFLINE`;
    status.className = "partstatus";
    btn.hidden = false; btn.textContent = `Start Part ${d.index}`; btn.className = "k stream";
  } else {
    status.textContent = `Event complete — all ${M} Parts done`;
    status.className = "partstatus done";
    btn.hidden = true;
  }
}

function openPartModal(d){
  const isEnd = d.action === "end";
  $("#partModalTitle").textContent =
    (isEnd ? "⚠ END " : "GO LIVE — START ") + `PART ${d.index} of ${d.count}`;
  $("#partModalBody").textContent = isEnd
    ? `This STOPS the live broadcast (Part ${d.index}). Viewers see the stream end.`
    : `This GOES LIVE (Part ${d.index}${d.current_label ? " — " + d.current_label : ""}).`;
  $("#partModalPhrase").textContent = d.confirm_phrase;
  const inp = $("#partModalInput"), ok = $("#partModalConfirm");
  inp.value = ""; ok.disabled = true;
  inp.oninput = () => { ok.disabled = normIntent(inp.value) !== d.confirm_phrase; };
  $("#partModal").showModal();
  setTimeout(() => inp.focus(), 50);
}

async function submitPart(){
  const d = partsState; if (!d || !d.action) return;
  const body = { intent: normIntent($("#partModalInput").value) };
  const path = d.action === "end" ? "/parts/end" : "/parts/start";
  if (d.action === "start") body.index = d.index;
  let res;
  try {
    const r = await fetch(RC_API(path), {method:"POST",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    res = await r.json().catch(() => ({ok:false, error:"bad response"}));
  } catch(e){ res = {ok:false, error:String(e)}; }
  $("#partModal").close();
  if (!res.ok) log("Part: " + (res.error || "failed"), "err");
  partsPoll(); obsStatePoll();
}

$("#partActionBtn").addEventListener("click", () => {
  if (partsState && partsState.action) openPartModal(partsState);
});
partsPoll(); setInterval(partsPoll, 2000);
```

And guard `renderStreamBtn` so the Part control owns the button when enabled — change its top (line 1045) from `b.hidden = false;` to:

```javascript
  if (partsEnabled){ b.hidden = true; return; }   // Part control owns the stream button
  b.hidden = false;
```

- [ ] **Step 5: Visual-verify the panel**

Use the superpowers **ui-visual-verification** gate: render the Director Panel from a local dev build against the demo profile + `tools/obs-sim.py`, and eyeball all three states — offline (`Start Part 1`), live (`● LIVE — Part 1 of 3` + `End Part 1`), and the typed-confirm modal (Confirm disabled until `END PART 1` is typed). Confirm a no-Producer-tab profile still shows the plain GO-LIVE button (fallback).

- [ ] **Step 6: Refresh the wiki screenshot**

Use the **wiki-screenshots** skill to recapture `src/docs/wiki/images/director-panel.png` (element screenshot framed like the existing image). **Then revert the demo profile's mutated `CONSOLE_SECRET`:**

Run: `git checkout profiles/demo/profile.env`
Expected: the demo `CONSOLE_SECRET` change (from running the demo relay) is discarded; `git status` shows only `director-panel.html` + `director-panel.png`.

- [ ] **Step 7: Commit**

```bash
git add src/director/director-panel.html src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): Part-aware stream control with typed-confirm modal"
```

---

### Task 7: Cloud autostart + docs

**Files:**
- Modify: `tools/cloud/provision.sh` (xfce autostart entries in the desktop/autologin step)
- Modify: `tools/cloud/README.md`, `src/docs/wiki/Run-an-event.md`, `src/docs/wiki/Sheet-Webhook.md`

- [ ] **Step 1: Add the autostart writer to `provision.sh`** — a helper plus a call in the xfce/autologin step (the block that writes the lightdm autologin conf, ~line 175). Add the helper near `write_headless_xorg`:

```bash
# GUI autostart so `racecast event start` over SSH finds OBS + Discord already
# running in the autologin session (belt-and-suspenders with event start's
# DISPLAY=:0 launch). Harmless if a binary is absent — the entry just no-ops.
write_gui_autostart() {
  local user_home="$1" user_name="$2"
  install -d -o "$user_name" -g "$user_name" "$user_home/.config/autostart"
  cat > "$user_home/.config/autostart/racecast-obs.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=OBS Studio (racecast)
Exec=obs
X-GNOME-Autostart-enabled=true
EOF
  cat > "$user_home/.config/autostart/racecast-discord.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Discord (racecast)
Exec=discord
X-GNOME-Autostart-enabled=true
EOF
  chown "$user_name:$user_name" \
    "$user_home/.config/autostart/racecast-obs.desktop" \
    "$user_home/.config/autostart/racecast-discord.desktop"
}
```

Then call it in the desktop/autologin step (right after the lightdm autologin conf is written), using the same user-home / user-name variables that step already uses (e.g. `$USER_NAME` and its home):

```bash
  write_gui_autostart "$(getent passwd "$USER_NAME" | cut -d: -f6)" "$USER_NAME"
  log "   GUI autostart written (OBS + Discord launch with the session; takes effect next boot)"
```

- [ ] **Step 2: Shellcheck the script**

Run: `shellcheck tools/cloud/provision.sh`
Expected: clean (no new warnings from `write_gui_autostart`).

- [ ] **Step 3: Update `tools/cloud/README.md`** — in the "Finish" / event-day section, add:

```markdown
- **Event day is SSH-only — no RustDesk needed.** The autologin xfce session
  comes up at boot, and `provision.sh` installs autostart entries so OBS +
  Discord launch with it. From your laptop: `gcloud compute ssh spike-gpu … ` then
  `racecast preflight` and `racecast event start` — `event start` also (re)launches
  OBS/Discord into the running session over SSH (it sets `DISPLAY=:0`; override
  with `RACECAST_DISPLAY`). RustDesk stays only for the one-time per-league OBS
  scene-collection import.
```

- [ ] **Step 4: Update `src/docs/wiki/Run-an-event.md`** — add a "Broadcast Parts from the Director Panel" subsection (Control-Center/Funnel-first per house style):

```markdown
### Broadcast Parts (Director Panel)

Long races are split into **Parts** (each a separate YouTube broadcast with its
own stream key, from the Sheet **Producer** tab). The Director Panel drives them —
no producer machine access needed:

1. `racecast event start` resets to **Part 1** (offline). Recovery after a mid-event
   restart: `racecast event start --part N`.
2. In the panel, click **Start Part N** → type the confirmation phrase
   (`START PART N`) → the relay sets that Part's stream key and goes live.
3. **End Part N** (type `END PART N`) stops the broadcast. If a next Part exists the
   panel offers **Start Part N+1**; the last (or only) Part just stops.

Every go-live / end requires the typed phrase — a stray tap can't change the live
state. A league with no Producer tab keeps the plain **GO LIVE** button.
```

- [ ] **Step 5: Note the relay use of `get_stream_key` in `src/docs/wiki/Sheet-Webhook.md`** — in the stream-keys section add one line:

```markdown
> The relay also calls `get_stream_key` server-side when the Director Panel starts a
> broadcast Part (#395) — the key is applied to OBS over localhost and never reaches
> the browser.
```

- [ ] **Step 6: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (no broken links/anchors from the edits).

- [ ] **Step 7: Commit**

```bash
git add tools/cloud/provision.sh tools/cloud/README.md src/docs/wiki/Run-an-event.md src/docs/wiki/Sheet-Webhook.md
git commit -m "feat(cloud): GUI autostart + SSH-only event-day docs for Part control"
```

---

## Final verification

- [ ] **Full suite:** `python3 tools/run-tests.py` → all pass (exactly what CI runs).
- [ ] **Lint:** `python3 tools/lint.py` → no findings.
- [ ] **Build self-verify:** `python3 tools/build.py` → passes (tokenization, blanked password, no secrets, no shell scripts shipped).
- [ ] **Optional e2e smoke:** `python3 tools/e2e.py` (synthetic) still green — the parts feature is disabled under the synthetic `--sheet-csv-url`, so `/parts/data` returns `{"enabled": false}` and the panel falls back; confirm no regression.
- [ ] Then use **superpowers:finishing-a-development-branch** to complete (branch `feat/director-panel-part-control` already exists with the spec commit).

## Notes for the executor

- **The stream key is the crown jewel.** It is fetched server-side in
  `apply_stream_service_for_ref`, applied via `obs_ws.set_stream_service`, and
  `del`-eted before returning. Never add it to a log line, a response, or
  `/parts/data`. The `t_apply_stream_service_for_ref_happy` test asserts it is
  absent from the note.
- **`set_stream_service` refuses while streaming** — the state machine only ever
  retargets in the offline window (Start guards on "already streaming" first), so
  this is never hit in the happy path; the 409 guard is the safety net.
- **Backward compatibility:** every guard degrades to the plain GO-LIVE button
  when `producer_source is None` or the Producer tab is empty. Do not remove or
  rename `#obsStreamBtn`, `/obs/stream`, or `racecast obs stream-target`.
- **`--part N` is inert against a running relay** (PartStore loads once at start).
  That is intentional (documented in `_write_part_reset`): recovery is
  `event start --part N` after the relay is down.
