# OBS Stream Target (Service + Key per Producer Part) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a producer set OBS's stream **service** (from the Sheet `Channel` tab) and stream **key** (from Apps Script Script Properties, referenced by a new optional `Producer`-tab column) per Producer Part — via CLI and Control Center — only while OBS is not streaming, never exposing a key in a viewer-readable Sheet cell.

**Architecture:** Pure helpers do the mapping/parsing (`obs_ws.stream_service_payload`, a new `src/scripts/stream_target.py`, and a `producer.py` column); a single best-effort OBS setter `obs_ws.set_stream_service` applies the change behind a hard "stream must be stopped" guard; one shared `_apply_stream_target(part)` in `src/racecast.py` fetches the Producer + Channel CSVs (via `http_util`) and the key (via the existing `SHEET_PUSH_URL` webhook), then calls the setter — reused by the CLI verb `racecast obs stream-target <part>` and the Control Center POST route. The key is fetched over HTTPS, applied to OBS, and never printed/logged/persisted.

**Tech Stack:** Python 3 stdlib only (no third-party deps, no pytest — each `tests/test_*.py` is a runnable script). OBS-WebSocket v5 (`obs_ws.py`). Google Sheets gviz CSV + an Apps Script web app (`SHEET_PUSH_URL`).

## Global Constraints

- **Edit only under `src/`** (plus `docs/…` and `tests/…`). Never hand-edit `dist/`/`runtime/`.
- **All scripts and docs must be English only.**
- **Never hardcode secrets or machine paths.** The stream key must never be written to a Sheet cell, a log line, a racecast state file, or any CLI/UI output — only "stream key set ✓" is shown.
- **No new machine/profile env property.** Reuse `SHEET_PUSH_URL` (env `RACECAST_SHEET_PUSH_URL`) as the capability-URL secret.
- **Outbound HTTP on the CLI/Control-Center (covered) side goes through `src/scripts/http_util.py`** — never bare `urllib`. (`tests/test_http_util.py` enforces this.)
- **`obs_ws` helpers are best-effort: they return `(ok, note)` and NEVER raise;** `_connect(...) is None` → `(False, note)`.
- **Backward compatible (v1.1.0 is released):** the new `Producer`-tab column is OPTIONAL; the existing `Part|Producer|MagicDNS` trio stays REQUIRED. Every missing piece degrades with a clear message and changes nothing else.
- **Cross-platform tests** — no real IPs/machine paths; use fixtures + the existing fake-OBS server harness.
- **Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` before the final commit.**
- **Any Control Center visual change requires refreshing `src/docs/wiki/images/cc-*.png` in the SAME change** (dev build, per CLAUDE.md).

---

### Task 1: `stream_service_payload` — pure platform→OBS-service builder

**Files:**
- Modify: `src/scripts/obs_ws.py` (add near `parse_stream_status`, ~line 464)
- Test: `tests/test_obsws.py`

**Interfaces:**
- Produces: `OBS_STREAM_SERVICE_NAMES: dict[str,str]` and `stream_service_payload(platform: str, key: str) -> dict` returning `{"streamServiceType": "rtmp_common", "streamServiceSettings": {"service": <name>, "server": "auto", "key": key}}`; unknown platform → `ValueError`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (before the `if __name__ == "__main__":` block):

```python
# --------------------------------------------------------------------------
# stream_service_payload — Sheet-driven OBS stream target (per Producer Part)
# --------------------------------------------------------------------------
def t_stream_service_payload_youtube():
    d = m.stream_service_payload("youtube", "live_abc")
    assert d == {"streamServiceType": "rtmp_common",
                 "streamServiceSettings": {"service": "YouTube - RTMPS",
                                           "server": "auto", "key": "live_abc"}}


def t_stream_service_payload_twitch_case_insensitive():
    d = m.stream_service_payload("  Twitch ", "sk_1")
    assert d["streamServiceSettings"]["service"] == "Twitch"
    assert d["streamServiceSettings"]["key"] == "sk_1"


def t_stream_service_payload_unknown_platform_raises():
    try:
        m.stream_service_payload("kick", "x")
    except ValueError as exc:
        assert "kick" in str(exc)
    else:
        assert False, "expected ValueError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -c "import sys; sys.path.insert(0,'src/scripts'); sys.path.insert(0,'tests'); import test_obsws as t; t.t_stream_service_payload_youtube()"`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'stream_service_payload'`.

- [ ] **Step 3: Implement the builder**

In `src/scripts/obs_ws.py`, add just after `parse_stream_status` (after its `return {...}` block, ~line 463):

```python
# Single-channel event -> OBS rtmp_common service name. Platform values come from
# the Sheet `Channel` tab (broadcast_chat.parse_channel_tab), lowercased.
OBS_STREAM_SERVICE_NAMES = {"youtube": "YouTube - RTMPS", "twitch": "Twitch"}


def stream_service_payload(platform, key):
    """Build SetStreamServiceSettings request data for a single-channel event.
    `platform` is the Channel-tab value ('youtube'/'twitch', case-insensitive);
    unknown -> ValueError (the caller turns it into a producer-facing note, never
    a crash). The key is passed through verbatim and never logged."""
    name = OBS_STREAM_SERVICE_NAMES.get((platform or "").strip().lower())
    if not name:
        raise ValueError(f"unknown stream platform: {platform!r}")
    return {"streamServiceType": "rtmp_common",
            "streamServiceSettings": {"service": name, "server": "auto", "key": key}}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `... ok t_stream_service_payload_youtube ...` and `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): stream_service_payload — platform->OBS rtmp_common builder"
```

---

### Task 2: `set_stream_service` — apply service+key behind a stream-stopped guard

**Files:**
- Modify: `src/scripts/obs_ws.py` (add after `set_stream`, ~line 756)
- Modify: `tests/test_obsws.py` (extend the fake OBS server `_fake_obs_server` to handle `SetStreamServiceSettings`; add tests)

**Interfaces:**
- Consumes: `stream_service_payload` (Task 1); existing `_connect`, `parse_stream_status`, `session.request`.
- Produces: `set_stream_service(platform: str, key: str, host="127.0.0.1", port=None, password=None, timeout=2.0) -> (ok: bool, note: str)`. Refuses while streaming with the exact note `"OBS is streaming — stop the broadcast before changing the stream target."`.

- [ ] **Step 1: Teach the fake OBS server the new request**

In `tests/test_obsws.py`, inside `_fake_obs_server`'s request dispatch, add a branch next to the existing `elif rtype == "GetStreamStatus":` block (mirroring the `SetInputSettings` recorder):

```python
        elif rtype == "SetStreamServiceSettings":
            state.setdefault("service_settings", []).append(rdata)
            resp = {}
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_obsws.py` (after the `set_stream` tests):

```python
# --------------------------------------------------------------------------
# set_stream_service — Sheet-driven OBS stream target (guarded)
# --------------------------------------------------------------------------
def t_set_stream_service_applies_when_offline():
    state = {"stream_active": False}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_stream_service("twitch", "sk_live", port=port,
                                    password="supersecret", timeout=5)
    assert ok and note == "", note
    assert state["service_settings"] == [
        {"streamServiceType": "rtmp_common",
         "streamServiceSettings": {"service": "Twitch", "server": "auto",
                                   "key": "sk_live"}}]
    srv.close()


def t_set_stream_service_refused_while_streaming():
    state = {"stream_active": True}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_stream_service("youtube", "sk", port=port,
                                    password="supersecret", timeout=5)
    assert ok is False
    assert "streaming" in note
    assert "service_settings" not in state          # nothing applied
    srv.close()


def t_set_stream_service_unknown_platform_is_note_not_crash():
    ok, note = m.set_stream_service("kick", "sk", port=1, password="x", timeout=0.5)
    assert ok is False
    assert "kick" in note                           # short-circuits before connect


def t_set_stream_service_unreachable_is_note_not_crash():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    ok, note = m.set_stream_service("twitch", "sk", port=free_port,
                                    password="x", timeout=0.5)
    assert ok is False and note
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `AttributeError: module 'obs_ws' has no attribute 'set_stream_service'`.

- [ ] **Step 4: Implement the guarded setter**

In `src/scripts/obs_ws.py`, add immediately after `set_stream` (after its `finally: session.close()`, ~line 756):

```python
def set_stream_service(platform, key, host="127.0.0.1", port=None,
                       password=None, timeout=2.0):
    """Set OBS's stream service + key for a single-channel event (best effort).
    HARD GUARD: refuses while OBS is streaming — a live service/key change is
    unsafe — returning (False, "OBS is streaming — stop the broadcast before
    changing the stream target."). Unknown platform / unreachable OBS -> (False,
    note). The key is applied to OBS and NEVER logged. (ok, note); never raises."""
    try:
        data = stream_service_payload(platform, key)
    except ValueError as exc:
        return False, str(exc)
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active"):
            return False, ("OBS is streaming — stop the broadcast before "
                           "changing the stream target.")
        session.request("SetStreamServiceSettings", data)
        return True, ""
    except Exception as exc:                       # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: `ALL PASS`.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "feat(obs): set_stream_service applies service+key only while stopped"
```

---

### Task 3: Optional `Stream Key` column on the `Producer` tab

**Files:**
- Modify: `src/scripts/producer.py`
- Test: `tests/test_producer.py`

**Interfaces:**
- Produces: `PRODUCER_STREAMKEY_HEADERS`; `parse_producer_rows` row dicts gain `"stream_key"` (empty string when the column is absent or blank). The three existing columns stay REQUIRED.

- [ ] **Step 1: Write the failing tests**

`tests/test_producer.py` imports the module as `p` (`import producer as p`) and auto-collects `t_*` functions at the bottom. Add:

```python
def t_parse_producer_rows_reads_optional_stream_key():
    text = ("Part,Producer,MagicDNS,Stream Key\r\n"
            "1,Alice,alice.ts.net,key1\r\n"
            "2,Bob,bob.ts.net,key2\r\n")
    rows = p.parse_producer_rows(text)
    assert [r["stream_key"] for r in rows] == ["key1", "key2"]


def t_parse_producer_rows_stream_key_absent_defaults_blank():
    text = "Part,Producer,MagicDNS\r\n1,Alice,alice.ts.net\r\n"
    rows = p.parse_producer_rows(text)
    assert rows[0]["stream_key"] == ""
    assert rows[0]["part"] == "1" and rows[0]["producer"] == "Alice"


def t_parse_producer_rows_still_requires_core_trio():
    # Missing MagicDNS header -> empty (unchanged behaviour), even with Stream Key.
    text = "Part,Producer,Stream Key\r\n1,Alice,key1\r\n"
    assert p.parse_producer_rows(text) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_producer.py`
Expected: FAIL — `KeyError: 'stream_key'`.

- [ ] **Step 3: Implement the optional column**

In `src/scripts/producer.py`:

Add the header constant next to the others (~line 15):

```python
PRODUCER_STREAMKEY_HEADERS = ("stream key", "streamkey", "key ref", "stream key ref")
```

In `parse_producer_rows`, after `mi = _find(header, PRODUCER_MAGICDNS_HEADERS)` and its required-trio guard, add the optional lookup and include it per row:

```python
    ki = _find(header, PRODUCER_STREAMKEY_HEADERS)   # optional -> None if absent
    out = []
    for row in rows[1:]:
        part, prod, magic = _cell(row, pi), _cell(row, ri), _cell(row, mi)
        if not prod and not magic:
            continue
        skey = _cell(row, ki) if ki is not None else ""
        out.append({"part": part, "producer": prod, "magicdns": magic,
                    "stream_key": skey})
    return out
```

(Replace the existing `out = []`/loop/`return out` block with the version above; the only changes are the `ki` line, the `skey` line, and the new dict key.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_producer.py`
Expected: all `ok …`, no failures.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/producer.py tests/test_producer.py
git commit -m "feat(producer): optional Stream Key column (key reference per part)"
```

---

### Task 4: `stream_target.py` — pure resolve + webhook-response parse

**Files:**
- Create: `src/scripts/stream_target.py`
- Create: `tests/test_stream_target.py`

**Interfaces:**
- Consumes: parsed `Producer` rows (Task 3, dicts with `part`/`stream_key`); parsed `Channel` rows `[(platform, channel)]` from `broadcast_chat.parse_channel_tab`.
- Produces:
  - `resolve_part_ref(producer_rows, part) -> str` (ref or `""`)
  - `event_platform(channel_rows) -> str` (lowercased platform or `""`)
  - `parse_stream_key_response(body) -> (key: str, error: str)` — success `(key, "")`, else `("", <message>)`; never raises.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stream_target.py`:

```python
#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import stream_target as st


def t_resolve_part_ref_matches_case_insensitively():
    rows = [{"part": "1", "stream_key": "key1"}, {"part": "Q", "stream_key": "keyq"}]
    assert st.resolve_part_ref(rows, "1") == "key1"
    assert st.resolve_part_ref(rows, " q ") == "keyq"


def t_resolve_part_ref_missing_or_blank_is_empty():
    rows = [{"part": "1", "stream_key": ""}, {"part": "2", "stream_key": "key2"}]
    assert st.resolve_part_ref(rows, "1") == ""      # matched row, no ref
    assert st.resolve_part_ref(rows, "9") == ""      # no such part
    assert st.resolve_part_ref([], "1") == ""


def t_event_platform_first_non_empty():
    assert st.event_platform([("youtube", "chan")]) == "youtube"
    assert st.event_platform([("", "chan"), ("Twitch", "c2")]) == "twitch"
    assert st.event_platform([]) == ""


def t_parse_stream_key_response_ok():
    body = b'{"ok": true, "action": "get_stream_key", "key": "live_x"}'
    assert st.parse_stream_key_response(body) == ("live_x", "")


def t_parse_stream_key_response_error_when_not_ok():
    body = b'{"ok": false, "action": "get_stream_key", "error": "no key for ref \'key1\'"}'
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "no key" in err


def t_parse_stream_key_response_outdated_script_no_action_echo():
    body = b'{"ok": true, "key": "x"}'          # no action echo -> outdated
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "outdated" in err


def t_parse_stream_key_response_missing_key():
    body = b'{"ok": true, "action": "get_stream_key"}'
    key, err = st.parse_stream_key_response(body)
    assert key == "" and "no key" in err


def t_parse_stream_key_response_malformed_json_is_error_not_crash():
    key, err = st.parse_stream_key_response(b"<html>500</html>")
    assert key == "" and err


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_stream_target.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'stream_target'`.

- [ ] **Step 3: Implement the module**

Create `src/scripts/stream_target.py`:

```python
#!/usr/bin/env python3
"""Pure helpers for the Sheet-driven OBS stream target (service + key per Producer
Part). No I/O: the CLI / Control Center fetch the Producer + Channel CSVs, call the
`get_stream_key` webhook, and drive OBS. Keeping resolution + response parsing here
makes them unit-testable and keeps the key out of any log/print path.

Security: the stream key only ever appears as the return of parse_stream_key_response
(handed straight to obs_ws.set_stream_service). It is never rendered by callers."""
import json


def resolve_part_ref(producer_rows, part):
    """The stream-key reference for a Part label from parsed Producer rows
    (dicts with 'part' + 'stream_key'). Case-insensitive exact match on the
    trimmed Part. Returns the ref, or "" when no row matches or the row has no
    reference. Pure."""
    want = (part or "").strip().lower()
    for r in producer_rows or []:
        if (r.get("part") or "").strip().lower() == want:
            return (r.get("stream_key") or "").strip()
    return ""


def event_platform(channel_rows):
    """The single event platform from parsed Channel rows [(platform, channel)]:
    the first non-empty platform, lowercased, or "". Pure (KISS: one channel per
    event)."""
    for platform, _chan in channel_rows or []:
        p = (platform or "").strip().lower()
        if p:
            return p
    return ""


def parse_stream_key_response(body):
    """Parse an Apps Script `get_stream_key` response (bytes or str) -> (key, error).
    Success {"ok":true,"action":"get_stream_key","key":"..."} -> (key, "").
    ok:false -> ("", <error>). Missing action echo -> ("", outdated-script msg).
    Malformed / non-JSON -> ("", msg). Never raises."""
    try:
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
        d = json.loads(text)
    except (ValueError, AttributeError, TypeError):
        return "", "webhook returned a non-JSON response"
    if not isinstance(d, dict):
        return "", "webhook returned an unexpected response"
    if not d.get("ok"):
        return "", str(d.get("error") or "webhook rejected the request")
    if d.get("action") != "get_stream_key":
        return "", ("webhook script outdated (no get_stream_key action) — redeploy "
                    "the Apps Script")
    key = d.get("key")
    if not key:
        return "", "webhook returned no key for that reference"
    return str(key), ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_stream_target.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/stream_target.py tests/test_stream_target.py
git commit -m "feat(stream-target): pure part-ref/platform resolve + webhook parse"
```

---

### Task 5: CLI `racecast obs stream-target <part>` + shared apply helper

**Files:**
- Modify: `src/racecast.py` (add `_apply_stream_target`, `obs_stream_target_cmd`, `OBS_VERBS`, `DISPATCH`, usage doc line)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `obs_ws.set_stream_service` (Task 2); `producer.parse_producer_rows` (Task 3); `broadcast_chat.parse_channel_tab`; `stream_target.*` (Task 4); `http_util.get_bytes` / `http_util.post_json`; env `RACECAST_SHEET_ID`, `RACECAST_SHEET_PUSH_URL`.
- Produces: `_apply_stream_target(part, fetch=None, post=None, apply_obs=None, refresh_env=None) -> (ok: bool, note: str)` — the single path reused by the CLI (this task) and the Control Center provider (Task 6). `note` NEVER contains the key. `route(["obs","stream-target"])` is accepted.

- [ ] **Step 1: Write the failing tests**

`tests/test_racecast.py` loads the module via importlib as `m` and calls `m.route(...)`. Add (using `m.`):

```python
def t_route_obs_stream_target_is_accepted():
    action = m.route(["obs", "stream-target", "1"])
    assert action["command"] == "obs" and action["verb"] == "stream-target"
    assert action["rest"] == ["1"]


def t_apply_stream_target_happy_path_sets_service_and_hides_key():
    # Seams: fetch(url)->csv text by tab, post(url,obj)->webhook bytes,
    # apply_obs(platform,key)->(ok,note). refresh_env no-op.
    producer_csv = "Part,Producer,MagicDNS,Stream Key\r\n1,Alice,a.ts.net,key1\r\n"
    channel_csv = "Platform,Channel\r\ntwitch,https://twitch.tv/foo\r\n"

    def fetch(url):
        return producer_csv if "Producer" in url else channel_csv

    def post(url, obj):
        assert obj == {"action": "get_stream_key", "ref": "key1"}
        return b'{"ok": true, "action": "get_stream_key", "key": "SECRET"}'

    seen = {}
    def apply_obs(platform, key):
        seen["platform"], seen["key"] = platform, key
        return True, ""

    os.environ["RACECAST_SHEET_ID"] = "SID"
    os.environ["RACECAST_SHEET_PUSH_URL"] = "https://script.example/exec"
    ok, note = m._apply_stream_target("1", fetch=fetch, post=post,
                                      apply_obs=apply_obs, refresh_env=lambda: None)
    assert ok is True, note
    assert seen == {"platform": "twitch", "key": "SECRET"}
    assert "SECRET" not in note                       # key never surfaced


def t_apply_stream_target_no_ref_is_clear_error():
    producer_csv = "Part,Producer,MagicDNS,Stream Key\r\n1,Alice,a.ts.net,\r\n"
    channel_csv = "Platform,Channel\r\ntwitch,x\r\n"
    os.environ["RACECAST_SHEET_ID"] = "SID"
    os.environ["RACECAST_SHEET_PUSH_URL"] = "https://script.example/exec"
    ok, note = m._apply_stream_target(
        "1", fetch=lambda u: producer_csv if "Producer" in u else channel_csv,
        post=lambda u, o: b"{}", apply_obs=lambda p, k: (True, ""),
        refresh_env=lambda: None)
    assert ok is False and "reference" in note.lower()


def t_apply_stream_target_webhook_error_surfaces_and_skips_obs():
    producer_csv = "Part,Producer,MagicDNS,Stream Key\r\n1,Alice,a.ts.net,key1\r\n"
    channel_csv = "Platform,Channel\r\ntwitch,x\r\n"
    os.environ["RACECAST_SHEET_ID"] = "SID"
    os.environ["RACECAST_SHEET_PUSH_URL"] = "https://script.example/exec"
    called = {"obs": 0}
    def apply_obs(p, k):
        called["obs"] += 1; return True, ""
    ok, note = m._apply_stream_target(
        "1", fetch=lambda u: producer_csv if "Producer" in u else channel_csv,
        post=lambda u, o: b'{"ok": false, "error": "no key for ref \'key1\'"}',
        apply_obs=apply_obs, refresh_env=lambda: None)
    assert ok is False and "no key" in note
    assert called["obs"] == 0                          # never touched OBS
```

(`os` is already imported at the top of `tests/test_racecast.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute '_apply_stream_target'` (and the route test fails on the usage `ValueError`).

- [ ] **Step 3: Register the verb**

In `src/racecast.py`, change `OBS_VERBS` (~line 885):

```python
OBS_VERBS = ("refresh", "collection", "logs", "stream-target")
```

- [ ] **Step 4: Implement the shared apply helper + CLI handler**

In `src/racecast.py`, add near the other `obs_*` handlers (after `obs_collection_cmd`, ~line 2160):

`PRODUCER_TAB = "Producer"` already exists (~line 3716). Add only the Channel-tab constant + helpers:

```python
CHANNEL_TAB = "Channel"               # single-event platform (YT/Twitch)


def _gviz_csv_url(sheet_id, tab):
    from urllib.parse import quote
    return ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s"
            % (sheet_id, quote(tab)))


def _apply_stream_target(part, fetch=None, post=None, apply_obs=None,
                         refresh_env=None):
    """Resolve a Producer Part -> (platform from Channel tab, key from the
    get_stream_key webhook) and apply it to OBS via set_stream_service. Returns
    (ok, note); `note` NEVER contains the key. Seams (fetch/post/apply_obs/
    refresh_env) are test hooks — production uses http_util + obs_ws. The OBS
    apply is only reached after a key is obtained; the stopped-stream guard lives
    in set_stream_service."""
    import producer as prod
    import broadcast_chat as bc
    import stream_target as st
    import obs_ws
    (refresh_env or _apply_active_profile_env)()
    sheet_id = os.environ.get("RACECAST_SHEET_ID") or ""
    if not sheet_id:
        return False, "no SHEET_ID set for the active profile"
    push_url = os.environ.get("RACECAST_SHEET_PUSH_URL") or ""
    if not push_url:
        return False, ("no SHEET_PUSH_URL in the active profile — the stream-key "
                       "webhook is required")
    fetch = fetch or (lambda u: http_util.get_bytes(u, timeout=15)
                      .decode("utf-8", "replace"))
    post = post or (lambda u, o: http_util.post_json(u, o, timeout=15))
    apply_obs = apply_obs or obs_ws.set_stream_service
    try:
        prod_rows = prod.parse_producer_rows(fetch(_gviz_csv_url(sheet_id, PRODUCER_TAB)))
        chan_rows = bc.parse_channel_tab(fetch(_gviz_csv_url(sheet_id, CHANNEL_TAB)))
    except Exception as exc:                           # noqa: BLE001 — tolerant fetch
        return False, f"sheet fetch failed: {type(exc).__name__}"
    ref = st.resolve_part_ref(prod_rows, part)
    if not ref:
        return False, f"no stream-key reference for Part {part!r} (Producer tab)"
    platform = st.event_platform(chan_rows)
    if not platform:
        return False, "no channel/platform configured (Channel tab)"
    try:
        body = post(push_url, {"action": "get_stream_key", "ref": ref})
    except Exception as exc:                           # noqa: BLE001 — tolerant webhook
        return False, f"stream-key webhook failed: {type(exc).__name__}"
    key, err = st.parse_stream_key_response(body)
    if err:
        return False, err
    ok, note = apply_obs(platform, key)
    del key                                            # drop the secret promptly
    if not ok:
        return False, note
    return True, f"stream target set for Part {part} on {platform} — stream key set"


def obs_stream_target_cmd(rest):
    """`racecast obs stream-target <part>`: set OBS's stream service+key for a
    Producer Part. Only works while OBS is NOT streaming; the key is fetched from
    the Sheet webhook and never printed."""
    if len(rest) != 1:
        sys.exit("usage: racecast obs stream-target <part>")
    ok, note = _apply_stream_target(rest[0])
    if not ok:
        sys.exit(f"obs: stream target not set — {note}")
    print(f"obs: {note} ✓")
```

Then add to the `DISPATCH` dict (~line 3291, next to the other `("obs", …)` entries):

```python
    ("obs", "stream-target"): obs_stream_target_cmd,
```

And add a usage line to the module docstring near the other `obs` lines (~line 18):

```
  racecast obs stream-target <part>          # set OBS stream service+key for a Producer Part (OBS must be stopped)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_racecast.py`
Expected: all `ok …`, no failures.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(cli): racecast obs stream-target <part> (key never printed)"
```

---

### Task 6: Control Center "Set Stream Target" action

**Files:**
- Modify: `src/racecast.py` (add `obs_stream_target_data` provider; register in the `ctx` dict ~line 5627)
- Modify: `src/ui/ui_server.py` (add POST route `/api/obs/stream-target`)
- Modify: `src/ui/control-center.html` (a Part picker + "Set Stream Target" button on the Home/Producer card)
- Test: `tests/test_ui_server.py`
- Modify: `src/docs/wiki/images/cc-home.png` (or the relevant `cc-*.png`) — refresh via the wiki-screenshots skill

**Interfaces:**
- Consumes: `_apply_stream_target` (Task 5); the existing `producer_schedule` provider (Part list is already shown on the Home view).
- Produces: `obs_stream_target_data(part) -> {"ok": bool, "note": str}` (note never carries the key); POST `/api/obs/stream-target` `{part}` → that dict, `code=200` on ok else `400`.

- [ ] **Step 1: Write the failing test**

`tests/test_ui_server.py` builds providers with `_ctx()`, starts an ephemeral server with `_serve(ctx)` → `(httpd, port)`, and POSTs JSON with `_post_json(port, path, obj)` → `(code, body_bytes)` (see `t_event_title_post_route_saves`). Mirror that shape:

```python
def t_post_obs_stream_target_routes_to_provider():
    calls = {}
    def provider(part):
        calls["part"] = part
        return {"ok": True, "note": "stream target set for Part 1 on twitch — stream key set"}
    ctx = _ctx()
    ctx["obs_stream_target"] = provider
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/obs/stream-target", {"part": "1"})
        d = json.loads(body)
        assert code == 200 and d["ok"] is True
        assert calls["part"] == "1"
        assert "key set" in d["note"] and "SECRET" not in d["note"]
    finally:
        httpd.shutdown()


def t_post_obs_stream_target_error_is_400():
    ctx = _ctx()
    ctx["obs_stream_target"] = lambda part: {
        "ok": False,
        "note": "OBS is streaming — stop the broadcast before changing the stream target."}
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/obs/stream-target", {"part": "1"})
        d = json.loads(body)
        assert code == 400 and d["ok"] is False
    finally:
        httpd.shutdown()
```

Note: `_ctx()` does not include `obs_stream_target` by default; only these two tests set it, and the route only reads `ctx["obs_stream_target"]` for this path, so existing `_serve(_ctx())` tests are unaffected.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the route returns 404 / the `obs_stream_target` ctx key is missing.

- [ ] **Step 3: Add the POST route**

In `src/ui/ui_server.py` `do_POST`, add next to the other action routes (e.g. after `/api/event-title`), following that block's exact shape:

```python
            if path == "/api/obs/stream-target":
                body = self._body_json()
                if body is None:
                    return self._json({"ok": False, "error": "malformed JSON body"},
                                      code=400)
                try:
                    result = ctx["obs_stream_target"]((body.get("part") or "").strip())
                except Exception as exc:               # noqa: BLE001 — provider is best-effort
                    return self._json({"ok": False, "note": str(exc)}, code=400)
                return self._json(result, code=200 if result.get("ok") else 400)
```

- [ ] **Step 4: Add the provider + register it**

In `src/racecast.py`, add a provider near `obs_collection_data` (~line 3561):

```python
def obs_stream_target_data(part):
    """Control Center action: set OBS's stream service+key for a Producer Part.
    Wraps _apply_stream_target -> {"ok", "note"} (note never carries the key)."""
    ok, note = _apply_stream_target(part or "")
    return {"ok": ok, "note": note}
```

Register it in the `ctx` provider dict (~line 5627, next to `"obs_collection": obs_collection_data,`):

```python
        "obs_stream_target": obs_stream_target_data,
```

- [ ] **Step 5: Wire the button in the Home view**

In `src/ui/control-center.html`, on the Producer/Home card that already renders the `producer_schedule` rows, add a Part `<select>` populated from those rows plus a "Set Stream Target" button that POSTs `{part}` to `/api/obs/stream-target` and shows `result.note` inline (green on `ok`, red otherwise). Follow the page's existing fetch/render helper (the same one used by the Producer schedule card and other POST actions). Show ONLY `note` — never any key. Keep the button disabled while a request is in flight.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_ui_server.py`
Expected: all `ok …`, no failures.

- [ ] **Step 7: Refresh the Control Center screenshot (dev build)**

Per CLAUDE.md, a Control Center visual change must refresh its `cc-*.png` in the same change. Use the **wiki-screenshots** skill against a local dev build (run `racecast ui` from `src/`, demo profile + `tools/obs-sim.py`), capture the Home/Producer card element, and overwrite the matching `src/docs/wiki/images/cc-*.png`.

- [ ] **Step 8: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py src/ui/ui_server.py src/ui/control-center.html tests/test_ui_server.py src/docs/wiki/images/
git commit -m "feat(ui): Set Stream Target action on the Control Center Home view"
```

---

### Task 7: Apps Script `get_stream_key` action + wiki docs

**Files:**
- Modify: `src/docs/wiki/Sheet-Webhook.md` (document the `get_stream_key` action + the Script-Properties recipe + the optional `Producer` `Stream Key` column)
- Modify: `src/docs/wiki/Producer.md` and/or `src/docs/wiki/Configuration.md` if they enumerate the `Producer`/`Channel` tab columns (add the `Stream Key` reference column note)
- Test: `python3 tests/test_wiki.py` (link/anchor integrity)

**Interfaces:**
- Produces: operator-facing documentation only (no shipped code — the Apps Script lives in each league's Sheet). The documented request/response contract MUST match `stream_target.parse_stream_key_response` (Task 4): request `{"action":"get_stream_key","ref":"<ref>"}`; success `{"ok":true,"action":"get_stream_key","key":"<key>"}`; unknown ref `{"ok":false,"action":"get_stream_key","error":"no key for ref '<ref>'"}`.

- [ ] **Step 1: Document the Script-Properties recipe**

In `src/docs/wiki/Sheet-Webhook.md`, add a section "Stream keys (per Producer Part)" covering, in English:
- Add an optional `Stream Key` column to the `Producer` tab holding a **reference** (`key1`, `key2`, …), NOT the key. Only the reference is ever in a cell.
- In the Apps Script editor: **Project Settings → Script Properties**, add one property per reference: name = `key1`, value = the real stream key. Only Sheet **editors** (the league owner) can see these; viewers cannot.
- Why: the key never lands in a viewer-readable cell / CSV export; racecast fetches it at switch time over the existing `SHEET_PUSH_URL`.

- [ ] **Step 2: Document the `get_stream_key` handler**

In the same page, add the `doPost` action snippet (Apps Script, for the league owner to paste), reading from Script Properties and echoing the action:

```javascript
// inside doPost(e), after parsing `body`:
if (body.action === 'get_stream_key') {
  var ref = String(body.ref || '');
  var key = PropertiesService.getScriptProperties().getProperty(ref);
  if (!key) {
    return json({ ok: false, action: 'get_stream_key',
                  error: "no key for ref '" + ref + "'" });
  }
  return json({ ok: true, action: 'get_stream_key', key: key });
}
```

Note explicitly: the property name is the reference from the `Producer` tab's `Stream Key` column; the key is returned over HTTPS and is never written back to any cell.

- [ ] **Step 3: Document the operator flow**

Add a short "Set the stream target" note (Control Center Home button **and** `racecast obs stream-target <part>`), stating the hard rule: **it only works while OBS is not streaming** — to switch keys between two back-to-back Parts, stop the broadcast, set the target for the next Part, then go live again.

- [ ] **Step 4: Run the wiki test to verify links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: PASS (no broken links/anchors introduced).

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/
git commit -m "docs(wiki): get_stream_key webhook action + Script-Properties stream keys"
```

---

### Final verification

- [ ] **Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: the whole suite passes (this is exactly what CI runs).

- [ ] **Run the build self-verify**

Run: `python3 tools/build.py`
Expected: build + verify succeed (no secrets, no shell scripts, tokenization intact).

- [ ] **Optional: e2e smoke (synthetic)**

Run: `python3 tools/e2e.py`
Expected: PASS (the new route degrades gracefully with the synthetic profile — no Producer/Channel tabs, so `stream-target` returns a clear "no reference" note; nothing else regresses).
