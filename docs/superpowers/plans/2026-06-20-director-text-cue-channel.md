# Director→Talent Text-Cue Channel (IFB-lite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a directed, text-only cue channel from the director to the talent cockpit — sticky-until-ack critical cues and auto-expiring info cues, targeting one commentator / all / on-air, with Sheet-managed presets plus free text, an ack receipt, and producer-takeover pull.

**Architecture:** Mirror the crew-chat stack one-to-one: a pure `cue_admin.py` module (sanitize/validate/active-set/prune/apply_pulled), a thread-safe `CueStore` ring buffer persisted to `runtime/<profile>/cues.json`, token-gated relay endpoints checked by `console_policy`, and poll-based UI in the panel + cockpit. Presets come from a `Cue Preset` column in the Configuration tab the existing `HudSource` already polls. Only `/console` is funnelled.

**Tech Stack:** Python 3 stdlib only (no framework, no pytest — each `tests/test_*.py` is a runnable script). Plain HTML/JS pages served by the relay. Google Sheets read as gviz CSV.

**Spec:** `docs/superpowers/specs/2026-06-20-director-text-cue-channel-design.md`

## Global Constraints

- **Edit only under `src/` and `tests/`.** `dist/`/`runtime/` are generated; `tools/` are maintainer scripts.
- **English only** in all code, comments, docs, and UI copy.
- **Stdlib only.** No new runtime dependencies. Tests are runnable scripts ending in `print("ALL PASS")`; `tools/run-tests.py` auto-discovers `tests/test_*.py` by glob.
- **No secrets / machine paths / real IPs** in code or tests.
- **Cross-platform** (CI matrix includes Windows): never `os.path.join` a known-foreign-OS path; cue paths are current-machine only, so `os.path.join` is correct here.
- **Funnel boundary is law:** only `/console` is publicly mounted. Feed URLs, `/status`, OBS-WebSocket never funnelled. Talent writes are identity-scoped.
- **Run `python3 tools/lint.py` after changing any Python file** (mirrors the CI lint job).
- **Changed UI surface ⇒ refresh its wiki screenshot in the SAME change** (Director Panel → `director-panel.png`; Cockpit → its image), captured from a local dev build.
- **Constants:** `INFO_CUE_TTL_S = 30`, `MAX_CUES = 100`, `MAX_CUE_TEXT = 200`, `MAX_NAME = 40`; ack rate limit `30/60 s` per identity; send has no limiter; `from` is the fixed label `"Director"`; `CUE_PRESET_HEADERS = ("cue preset", "cue presets", "cue")`.

---

### Task 1: Pure cue logic module `cue_admin.py`

The foundation: a dependency-free module mirroring `src/scripts/chat_admin.py`. Everything else builds on it. Fully TDD via `tests/test_cues.py`.

**Files:**
- Create: `src/scripts/cue_admin.py`
- Test: `tests/test_cues.py`

**Interfaces:**
- Produces (consumed by Tasks 3 & 6):
  - `MAX_CUES: int`, `INFO_CUE_TTL_S: float`, `MAX_CUE_TEXT: int`, `MAX_NAME: int`, `LEVELS: tuple`
  - `sanitize_cue(raw: dict) -> dict | None` — keys `{id, ts, target, level, text, from, ack}`
  - `resolve_target(raw_target: str, on_air_key: str | None, normalize: callable) -> str | None`
  - `active_cues_for(cues: list, streamer_key: str, now: float, info_ttl=INFO_CUE_TTL_S) -> list`
  - `prune(cues: list, now: float, info_ttl=INFO_CUE_TTL_S) -> list`
  - `validate_payload(payload: dict) -> list` (raises `ValueError` on malformed shape)
  - `load_cues(path: str) -> list`, `write_cues(path: str, cues: list) -> None`
  - `apply_pulled(path: str, payload: dict, now: float, info_ttl=INFO_CUE_TTL_S) -> int`

- [ ] **Step 1: Write the failing test file with the first cases**

Create `tests/test_cues.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the director text-cue channel. Run: python3 tests/test_cues.py"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


cu = _load("cue_admin", ("src", "scripts", "cue_admin.py"))


def t_sanitize_cue_basic():
    c = cu.sanitize_cue({"id": 1, "ts": 100.0, "target": "max", "level": "info",
                         "text": "wrap up", "from": "Director", "ack": None})
    assert c == {"id": 1, "ts": 100.0, "target": "max", "level": "info",
                 "text": "wrap up", "from": "Director", "ack": None}


def t_sanitize_cue_caps_and_strips():
    c = cu.sanitize_cue({"id": 2, "ts": 1.0, "target": "all", "level": "critical",
                         "text": "x" * 500, "from": "y" * 80})
    assert len(c["text"]) == cu.MAX_CUE_TEXT
    assert len(c["from"]) == cu.MAX_NAME


def t_sanitize_cue_folds_control_chars():
    c = cu.sanitize_cue({"id": 3, "ts": 1.0, "target": "max", "level": "info",
                         "text": "go\x07 now\nplease"})
    assert c["text"] == "go now please"
    assert c["from"] == "Director"          # blank -> default label


def t_sanitize_cue_rejects_bad():
    for bad in ({"id": 1, "ts": 1.0, "target": "max", "level": "loud", "text": "x"},
                {"id": 1, "ts": 1.0, "target": "", "level": "info", "text": "x"},
                {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "   "},
                {"id": 0, "ts": 1.0, "target": "max", "level": "info", "text": "x"},
                {"id": True, "ts": 1.0, "target": "max", "level": "info", "text": "x"},
                {"id": 1, "ts": "x", "target": "max", "level": "info", "text": "x"}):
        assert cu.sanitize_cue(bad) is None, bad


def t_sanitize_cue_ack_shape():
    c = cu.sanitize_cue({"id": 1, "ts": 1.0, "target": "max", "level": "critical",
                         "text": "hot", "ack": {"ts": 9.0, "junk": 1}})
    assert c["ack"] == {"ts": 9.0}
    c2 = cu.sanitize_cue({"id": 1, "ts": 1.0, "target": "max", "level": "critical",
                          "text": "hot", "ack": {"nope": 1}})
    assert c2["ack"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_cues.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFoundError` for `cue_admin.py` (module not created yet).

- [ ] **Step 3: Create `src/scripts/cue_admin.py` with sanitize + constants**

```python
"""Pure logic for the director text-cue channel (runtime/<profile>/cues.json).

No network, no argv parsing — cue sanitization, the active-set filter, prune,
the takeover validation gate, and an atomic file write/load. Imported by the
relay (CueStore) and the `racecast event takeover` cue pull so both agree on the
on-disk shape and the caps. Mirrors chat_admin.py.
"""
import json
import os
import tempfile

MAX_CUES = 100          # ring-buffer cap (oldest dropped)
MAX_CUE_TEXT = 200      # per-cue character cap
MAX_NAME = 40           # sender-label / target character cap
INFO_CUE_TTL_S = 30     # info-cue auto-expiry window (seconds)
LEVELS = ("info", "critical")
DEFAULT_FROM = "Director"


def _clean_text(value):
    """Strip control characters, fold every line/paragraph separator to one
    space (cues render single-line). ASCII CR/LF/TAB plus Unicode NEL/LS/PS."""
    if not isinstance(value, str):
        return ""
    line_breaks = ("\t", "\n", "\r", "\x85", " ", " ")
    out = []
    for ch in value:
        if ch in line_breaks:
            out.append(" ")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            continue
        else:
            out.append(ch)
    return "".join(out)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sanitize_cue(raw):
    """Coerce one raw cue dict into {id, ts, target, level, text, from, ack} or
    None if unusable. Used on add, on load, and on every takeover pull."""
    if not isinstance(raw, dict) or not _is_num(raw.get("ts")):
        return None
    if isinstance(raw.get("id"), bool) or not isinstance(raw.get("id"), int) or raw["id"] < 1:
        return None
    if raw.get("level") not in LEVELS:
        return None
    target = _clean_text(raw.get("target")).strip()
    if not target:
        return None
    text = _clean_text(raw.get("text")).strip()
    if not text:
        return None
    frm = _clean_text(raw.get("from")).strip() or DEFAULT_FROM
    ack = raw.get("ack")
    if not (isinstance(ack, dict) and _is_num(ack.get("ts"))):
        ack = None
    else:
        ack = {"ts": float(ack["ts"])}
    return {"id": int(raw["id"]), "ts": float(raw["ts"]),
            "target": target[:MAX_NAME], "level": raw["level"],
            "text": text[:MAX_CUE_TEXT], "from": frm[:MAX_NAME], "ack": ack}
```

- [ ] **Step 4: Run the test to verify the sanitize cases pass**

Run: `python3 tests/test_cues.py`
Expected: PASS — prints `ok t_sanitize_*` lines and `ALL PASS`.

- [ ] **Step 5: Add the active-set + resolve_target + prune tests**

Append to `tests/test_cues.py` (before the `__main__` block):

```python
def t_resolve_target_all_and_key():
    norm = lambda s: s.strip().lower().replace(" ", "-")
    assert cu.resolve_target("all", None, norm) == "all"
    assert cu.resolve_target("Max Power", None, norm) == "max-power"
    assert cu.resolve_target("  ", None, norm) is None


def t_resolve_target_on_air():
    norm = lambda s: s.strip().lower()
    assert cu.resolve_target("on-air", "jegr", norm) == "jegr"
    assert cu.resolve_target("on-air", None, norm) is None   # nobody on air


def t_active_cues_info_ttl():
    cues = [{"id": 1, "ts": 100.0, "target": "max", "level": "info",
             "text": "hi", "from": "Director", "ack": None}]
    assert cu.active_cues_for(cues, "max", 120.0, info_ttl=30) == cues   # within TTL
    assert cu.active_cues_for(cues, "max", 131.0, info_ttl=30) == []     # expired


def t_active_cues_critical_sticky_until_ack():
    base = {"id": 1, "ts": 1.0, "target": "max", "level": "critical",
            "text": "hot", "from": "Director", "ack": None}
    assert cu.active_cues_for([base], "max", 1e9) == [base]              # sticky forever
    acked = dict(base, ack={"ts": 5.0})
    assert cu.active_cues_for([acked], "max", 1e9) == []                 # acked -> gone


def t_active_cues_target_scope():
    cues = [{"id": 1, "ts": 1.0, "target": "max", "level": "critical", "text": "a",
             "from": "Director", "ack": None},
            {"id": 2, "ts": 1.0, "target": "all", "level": "critical", "text": "b",
             "from": "Director", "ack": None}]
    got = cu.active_cues_for(cues, "ann", 1e9)
    assert [c["id"] for c in got] == [2]          # ann sees only the "all" cue, not max's


def t_prune_drops_stale_keeps_active():
    cues = [{"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "old",
             "from": "Director", "ack": None},                      # expired info
            {"id": 2, "ts": 1.0, "target": "max", "level": "critical", "text": "ack'd",
             "from": "Director", "ack": {"ts": 2.0}},                # acked critical
            {"id": 3, "ts": 1.0, "target": "max", "level": "critical", "text": "live",
             "from": "Director", "ack": None}]                      # still active
    kept = cu.prune(cues, now=1000.0, info_ttl=30)
    assert [c["id"] for c in kept] == [3]
```

- [ ] **Step 6: Run to verify the new tests fail**

Run: `python3 tests/test_cues.py`
Expected: FAIL — `AttributeError: module 'cue_admin' has no attribute 'resolve_target'`.

- [ ] **Step 7: Implement resolve_target, active_cues_for, prune**

Append to `src/scripts/cue_admin.py`:

```python
def resolve_target(raw_target, on_air_key, normalize):
    """Map a panel target selection to a concrete cue target string, or None.
    'all' -> 'all'; 'on-air' -> the on-air streamer_key (or None when nobody is
    on air); anything else -> normalize(name) (the relay passes asset_key)."""
    t = (raw_target or "").strip()
    if t == "all":
        return "all"
    if t in ("on-air", "on_air", "onair"):
        return on_air_key or None
    return normalize(t) or None


def active_cues_for(cues, streamer_key, now, info_ttl=INFO_CUE_TTL_S):
    """The cues a given commentator should currently see: target is their key or
    'all', and the cue is still active — info while now < ts+ttl, critical while
    unacked."""
    out = []
    for c in cues:
        if c.get("target") not in (streamer_key, "all"):
            continue
        if c.get("level") == "critical":
            if c.get("ack") is None:
                out.append(c)
        elif now < c.get("ts", 0) + info_ttl:
            out.append(c)
    return out


def prune(cues, now, info_ttl=INFO_CUE_TTL_S):
    """Drop expired info + acked critical cues; bound to MAX_CUES. Applied on
    load and on a takeover pull (a restart/handover carries no stale cues)."""
    keep = []
    for c in cues:
        if c.get("level") == "critical":
            if c.get("ack") is None:
                keep.append(c)
        elif now < c.get("ts", 0) + info_ttl:
            keep.append(c)
    return keep[-MAX_CUES:]
```

- [ ] **Step 8: Run to verify all logic tests pass**

Run: `python3 tests/test_cues.py`
Expected: PASS — all `t_*` lines + `ALL PASS`.

- [ ] **Step 9: Add the file-IO + apply_pulled tests**

Append to `tests/test_cues.py` (before `__main__`):

```python
def t_validate_payload_sorts_and_caps():
    payload = {"cues": [
        {"id": 2, "ts": 2.0, "target": "max", "level": "info", "text": "b"},
        {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "a"},
        {"id": 3, "ts": 3.0, "target": "max", "level": "bogus", "text": "drop me"}]}
    clean = cu.validate_payload(payload)
    assert [c["id"] for c in clean] == [1, 2]        # sorted by id, bad entry dropped


def t_validate_payload_rejects_shape():
    for bad in ({}, {"cues": "nope"}, []):
        try:
            cu.validate_payload(bad); assert False, bad
        except ValueError:
            pass


def t_write_load_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", "cues.json")
        cu.write_cues(path, [{"id": 1, "ts": 1.0, "target": "max", "level": "info",
                              "text": "hi", "from": "Director", "ack": None}])
        assert cu.load_cues(path) == [{"id": 1, "ts": 1.0, "target": "max",
                                       "level": "info", "text": "hi",
                                       "from": "Director", "ack": None}]


def t_load_missing_is_empty():
    with tempfile.TemporaryDirectory() as d:
        assert cu.load_cues(os.path.join(d, "nope.json")) == []


def t_apply_pulled_prunes_and_writes():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cues.json")
        payload = {"cues": [
            {"id": 1, "ts": 1.0, "target": "max", "level": "info", "text": "stale"},
            {"id": 2, "ts": 1.0, "target": "max", "level": "critical", "text": "live"}]}
        n = cu.apply_pulled(path, payload, now=1000.0, info_ttl=30)
        assert n == 1                                  # the expired info pruned out
        assert [c["id"] for c in cu.load_cues(path)] == [2]
```

- [ ] **Step 10: Run to verify they fail**

Run: `python3 tests/test_cues.py`
Expected: FAIL — `AttributeError: module 'cue_admin' has no attribute 'validate_payload'`.

- [ ] **Step 11: Implement validate_payload, write_cues, load_cues, apply_pulled**

Append to `src/scripts/cue_admin.py`:

```python
def validate_payload(payload):
    """Validate a {'cues': [...]} object for a takeover pull. Returns the cleaned,
    id-sorted, capped list. Empty is valid; raises ValueError ONLY on a malformed
    shape (not a dict, or 'cues' not a list). Bad entries are dropped, not fatal."""
    if not isinstance(payload, dict) or not isinstance(payload.get("cues"), list):
        raise ValueError("expected an object with a 'cues' list")
    clean = [c for c in (sanitize_cue(x) for x in payload["cues"]) if c]
    clean.sort(key=lambda c: c["id"])
    return clean[-MAX_CUES:]


def write_cues(path, cues):
    """Atomically write {'cues': [...]} to path (temp file + os.replace)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"cues": list(cues)}, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_cues(path):
    """Read cues.json -> sanitized, capped list. Missing/corrupt -> []."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return []
    try:
        return validate_payload(payload)
    except ValueError:
        return []


def apply_pulled(path, payload, now, info_ttl=INFO_CUE_TTL_S):
    """Validate (raises on malformed shape), prune to active-only, THEN overwrite
    path. On failure the local file is untouched. Returns the count written."""
    cues = prune(validate_payload(payload), now, info_ttl)
    write_cues(path, cues)
    return len(cues)
```

- [ ] **Step 12: Run the full test file to verify it passes**

Run: `python3 tests/test_cues.py`
Expected: PASS — every `t_*` line + `ALL PASS`.

- [ ] **Step 13: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/cue_admin.py tests/test_cues.py
git commit -m "feat(cues): pure cue_admin logic module (#243)"
```

---

### Task 2: Authorization policy entries

Wire the new routes into the pure `console_policy` matrix so the Funnel gate authorizes them: director for `cues/*`, any-auth for `cockpit/cues` + `cockpit/cues/ack`. The takeover route `/console/takeover/cues` is already covered by the generic `takeover/*` → producer+step-up rule.

**Files:**
- Modify: `src/scripts/console_policy.py`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `console_policy.decide(roles, segments, method, has_step_up)`, constants `DIRECTOR`, `ANY`, `ALLOW`, `FORBIDDEN`.
- Produces: `min_capability(["cues", *])` → `Requirement(DIRECTOR, False)`; `min_capability(["cockpit","cues"])` and `(["cockpit","cues","ack"])` → `Requirement(ANY, False)`.

- [ ] **Step 1: Add failing policy tests**

Find the test runner convention in `tests/test_console.py` (it loads `console_policy` as a module, e.g. `cp = _load(...)`, and defines `t_*` functions). Append these tests, using the module alias already defined at the top of that file (it is `cp`):

```python
def t_policy_cues_director_only():
    # Director may send/read cues; a bare commentator may not.
    for seg in (["cues", "send"], ["cues", "data"], ["cues", "presets"], ["cues", "reload"]):
        assert cp.decide({"director"}, seg, "POST", False) == cp.ALLOW, seg
        assert cp.decide({"commentator"}, seg, "POST", False) == cp.FORBIDDEN, seg


def t_policy_cockpit_cues_any_auth():
    # Any authenticated subject may read their cues and ack one.
    for seg in (["cockpit", "cues"], ["cockpit", "cues", "ack"]):
        assert cp.decide({"commentator"}, seg, "POST", False) == cp.ALLOW, seg
        assert cp.decide(set(), seg, "GET", False) == cp.ALLOW, seg


def t_policy_takeover_cues_producer_stepup():
    seg = ["takeover", "cues"]
    assert cp.decide({"producer"}, seg, "GET", True) == cp.ALLOW
    assert cp.decide({"producer"}, seg, "GET", False) == cp.STEP_UP_REQUIRED
    assert cp.decide({"director"}, seg, "GET", True) == cp.FORBIDDEN
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_console.py`
Expected: FAIL on `t_policy_cues_director_only` — `cues/*` currently returns `NOT_FOUND` (no matrix entry), so `decide(... ) == ALLOW` assertion fails.

- [ ] **Step 3: Add the matrix entries**

In `src/scripts/console_policy.py`, inside `min_capability`, add the director entry in the director block (after the `submissions` entry, before the `# --- commentator` comment at line ~91):

```python
        if p and p[0] == "cues":                    # /cues/send|data|presets|reload
            return Requirement(DIRECTOR, False)
```

Then add the cockpit cue routes to the any-authenticated cockpit tuple (extend the existing `if p in (["cockpit"], ...)` membership list at line ~111):

```python
        if p in (["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
                 ["cockpit", "timer"], ["cockpit", "chat", "data"],
                 ["cockpit", "chat", "send"],
                 ["cockpit", "cues"], ["cockpit", "cues", "ack"]):
            return Requirement(ANY, False)
```

(The `takeover/cues` case needs no change — `min_capability` already maps `p[0] == "takeover" and len(p) >= 2` to `Requirement(PRODUCER, True)`.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_console.py`
Expected: PASS — `ALL PASS`.

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "feat(cues): authorize /cues, /cockpit/cues, takeover/cues (#243)"
```

---

### Task 3: Relay store, preset parsing, endpoints & gate

Wire the cue channel into the relay: a `CueStore` (mirrors `ChatStore`), a `parse_cue_presets` Configuration-column parser surfaced through `HudSource`, the six endpoints, the takeover gate rewrite, and the `make_handler` plumbing. Unit-test `parse_cue_presets` and `CueStore` via the importable relay module.

**Files:**
- Modify: `src/relay/racecast-feeds.py`
- Test: `tests/test_cues.py` (extend)

**Interfaces:**
- Consumes: `cue_admin.*` (Task 1); `asset_key`, `live_schedule_row`, `parse_config_vocab` precedent, `HudSource`, `ChatStore`, `make_handler`, `console_auth.RateLimiter`.
- Produces (consumed by Tasks 4, 5, 6): endpoints `GET /cues/data`, `GET /cues/presets`, `GET /cues/reload`, `POST /cues/send`, `GET /cockpit/cues`, `POST /cockpit/cues/ack`, plus the Funnel mappings `/console/cues/*`, `/console/cockpit/cues`, `/console/cockpit/cues/ack`, `/console/takeover/cues`. `cue_store.data()` shape `{"cues": [...]}`.

- [ ] **Step 1: Import cue_admin next to chat_admin**

Find the import of `chat_admin` in `src/relay/racecast-feeds.py` (search `import chat_admin`). Add an adjacent import:

```python
import cue_admin
```

(Match the existing style — if `chat_admin` is imported as `import chat_admin`, mirror it exactly so the `sys.path` setup that makes `scripts/` importable is reused.)

- [ ] **Step 2: Write the failing parse_cue_presets + CueStore tests**

Append to `tests/test_cues.py` (before `__main__`). This loads the relay module the same way `tests/test_hud.py` does:

```python
_relay = _load("irofeeds", ("src", "relay", "racecast-feeds.py"))


def t_parse_cue_presets_by_header():
    csv_text = ("Stints,Streamers,Cue Preset\n"
                "Stint 1,JeGr,Wrap up\n"
                "Stint 2,Ann,Throw to pit\n"
                ",,Wrap up\n")                 # duplicate dropped, blanks skipped
    assert _relay.parse_cue_presets(csv_text) == ["Wrap up", "Throw to pit"]


def t_parse_cue_presets_absent_column():
    assert _relay.parse_cue_presets("Stints,Streamers\nStint 1,JeGr\n") == []


def t_cuestore_add_list_ack_round_trip():
    with tempfile.TemporaryDirectory() as d:
        store = _relay.CueStore(os.path.join(d, "cues.json"))
        r = store.add(target="max", level="critical", text="hot", now=100.0)
        assert r["ok"] and r["cue"]["id"] == 1 and r["cue"]["from"] == "Director"
        # a foreign commentator cannot ack max's cue
        assert "error" in store.ack(1, "ann", now=101.0)
        assert store.list()[0]["ack"] is None
        # the addressee can
        assert store.ack(1, "max", now=102.0)["ok"] is True
        assert store.list()[0]["ack"] == {"ts": 102.0}


def t_cuestore_rejects_bad_level():
    with tempfile.TemporaryDirectory() as d:
        store = _relay.CueStore(os.path.join(d, "cues.json"))
        assert "error" in store.add(target="max", level="loud", text="x")
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 tests/test_cues.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'parse_cue_presets'`.

- [ ] **Step 4: Add `parse_cue_presets` near `parse_config_vocab`**

In `src/relay/racecast-feeds.py`, immediately after `parse_config_vocab` (ends ~line 742), add:

```python
# Configuration-tab column of director cue presets (admin-managed, read-only in
# the panel). Located by header like the vocab columns; blanks/dupes dropped.
CUE_PRESET_HEADERS = ("cue preset", "cue presets", "cue")


def parse_cue_presets(text):
    """Configuration tab CSV -> [preset strings] for the panel's cue buttons."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [(h or "").strip().lower() for h in rows[0]]
    i = next((header.index(h) for h in CUE_PRESET_HEADERS if h in header), None)
    if i is None:
        return []
    out, seen = [], set()
    for row in rows[1:]:
        v = (row[i] or "").strip() if len(row) > i else ""
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out
```

- [ ] **Step 5: Surface presets through `HudSource`**

In `HudSource.__init__` (line ~2000), after `self._vocab = {...}`, add:

```python
        self._cue_presets = []
```

In `HudSource.refresh` (line ~2022), after `vocab = parse_config_vocab(config_text)`, add:

```python
            cue_presets = parse_cue_presets(config_text)
```

Inside the `with self.lock:` block of `refresh` (after `self._vocab = vocab`), add:

```python
            self._cue_presets = cue_presets
```

After the `vocab(self)` accessor (line ~2091), add:

```python
        def cue_presets(self):
            with self.lock:
                return list(self._cue_presets)
```

(Indent to match the other `HudSource` methods — `cue_presets` is a method on the class, so 4-space method indentation, NOT the 8 shown here if the surrounding methods use 4. Match the file.)

- [ ] **Step 6: Add the `CueStore` class after `ChatStore`**

In `src/relay/racecast-feeds.py`, immediately after the `ChatStore` class (ends line ~1221), add:

```python
class CueStore:
    """Director text-cue ring buffer + best-effort JSON file
    (runtime/<profile>/cues.json), loaded + pruned on construction. Mirrors
    ChatStore. add() is the director write; ack() is the talent write (scoped to
    the cue's target); reload() re-reads the file (takeover). ts is server clock."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            pass
        self.cues = cue_admin.prune(cue_admin.load_cues(self.path), time.time())

    def add(self, target, level, text, from_name=cue_admin.DEFAULT_FROM, now=None):
        now = time.time() if now is None else now
        with self.lock:
            nid = max([0] + [c["id"] for c in self.cues]) + 1
            entry = cue_admin.sanitize_cue({"id": nid, "ts": now, "target": target,
                                            "level": level, "text": text,
                                            "from": from_name, "ack": None})
            if entry is None:
                return {"error": "cue needs target, level (info|critical) and text"}
            self.cues.append(entry)
            del self.cues[: -cue_admin.MAX_CUES]
            try:
                cue_admin.write_cues(self.path, self.cues)
            except OSError:
                pass
            return {"ok": True, "cue": entry}

    def list(self):
        with self.lock:
            return list(self.cues)

    def data(self):
        with self.lock:
            return {"cues": list(self.cues)}

    def ack(self, cue_id, streamer_key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            for c in self.cues:
                if c["id"] == cue_id:
                    if c["target"] not in (streamer_key, "all"):
                        return {"error": "not your cue"}
                    c["ack"] = {"ts": now}
                    try:
                        cue_admin.write_cues(self.path, self.cues)
                    except OSError:
                        pass
                    return {"ok": True, "id": cue_id}
            return {"error": "no such cue"}

    def reload(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                payload = json.load(fh)
            cues = cue_admin.prune(cue_admin.validate_payload(payload), time.time())
        except (OSError, ValueError) as e:
            return {"error": f"reload failed: {type(e).__name__}: {e}"}
        with self.lock:
            self.cues = cues
        return {"ok": True, "count": len(cues)}
```

- [ ] **Step 7: Run to verify the relay-module tests pass**

Run: `python3 tests/test_cues.py`
Expected: PASS — including `t_parse_cue_presets_*` and `t_cuestore_*`, then `ALL PASS`.

- [ ] **Step 8: Add `cue_store` to `make_handler` + an ack rate limiter**

In `make_handler`'s signature (line ~2958), add a `cue_store=None` parameter (next to `chat_store=None`):

```python
                 chat_store=None, cue_store=None, preview_path=None, graphics_dir=None,
```

After the `_cockpit_submit_rl = ...` limiter (line ~2982), add:

```python
    # Talent ack is a funnelled write; key on the authed identity (like chat), not
    # the shared proxy IP. The director SEND has no limiter (director-gated /
    # tailnet-trusted, like /next).
    _cockpit_cue_ack_rl = console_auth.RateLimiter(limit=30, window_s=60)
```

- [ ] **Step 9: Add the GET endpoints**

In `do_GET`, add a `cues` block right after the `chat` block (after line ~3695, before `if p[:1] == ["cockpit"]:`):

```python
                if p[:1] == ["cues"]:
                    if not cue_store:
                        return self._send({"error": "cues disabled"}, 404)
                    if p == ["cues", "data"]:
                        return self._send(cue_store.data())
                    if p == ["cues", "presets"]:
                        return self._send({"presets": hud_source.cue_presets()
                                           if hud_source else []})
                    if p == ["cues", "reload"]:
                        return self._send(cue_store.reload())
                    return self._send({"error": "unknown", "path": self.path}, 404)
```

Inside the `cockpit` GET block (after `["cockpit", "chat", "data"]`, ~line 3752), add:

```python
                    if p == ["cockpit", "cues"]:
                        me = self._console_auth()
                        if me is None:
                            return None
                        if not cue_store:
                            return self._send({"error": "cues disabled"}, 404)
                        return self._send({"cues": cue_admin.active_cues_for(
                            cue_store.list(), me, time.time())})
```

- [ ] **Step 10: Add the POST endpoints**

In `do_POST`, inside the `cockpit` block (after `["cockpit", "submit"]`, ~line 3923, before its trailing `return self._send({"error": "unknown"...})`), add:

```python
                    if p == ["cockpit", "cues", "ack"]:
                        me = self._console_auth()
                        if me is None:
                            return None
                        if not cue_store:
                            return self._send({"error": "cues disabled"}, 404)
                        if not _cockpit_cue_ack_rl.allow(me):
                            return self._send({"error": "rate limited"}, 429)
                        try:
                            cid = int(body.get("id"))
                        except (TypeError, ValueError):
                            return self._send({"error": "id must be an integer"}, 400)
                        return self._send(cue_store.ack(cid, me))
```

After the root `["chat", "send"]` POST block (~line 3929), add the director send:

```python
                if p == ["cues", "send"]:
                    if not cue_store:
                        return self._send({"error": "cues disabled"}, 404)
                    rows = relay.source.get_rows()
                    live_idx = relay.feeds[relay.live_feed()].idx
                    cur = live_schedule_row(rows, live_idx)
                    on_air_key = asset_key(cur["streamer"]) if cur else None
                    target = cue_admin.resolve_target(body.get("target"),
                                                      on_air_key, asset_key)
                    if not target:
                        return self._send({"error": "unknown target (nobody on air?)"}, 400)
                    return self._send(cue_store.add(
                        target=target, level=(body.get("level") or "").strip(),
                        text=body.get("text")))
```

- [ ] **Step 11: Add the takeover gate rewrite**

In `_console_gate`, next to the existing `takeover` rewrites (after `if sub == ["takeover", "versions"]:` at line ~3489), add:

```python
                if sub == ["takeover", "cues"]:
                    return ["cues", "data"]          # full list, gated producer+step-up
```

- [ ] **Step 12: Construct `CueStore` and pass it to `make_handler`**

After `chat_store = ChatStore(os.path.join(runtime, "chat.json"))` (line ~4361), add:

```python
    cue_store = CueStore(os.path.join(runtime, "cues.json"))
```

In the `make_handler(...)` call (line ~4427), pass it next to `chat_store`:

```python
                           overlay_dir=args.overlay_dir, chat_store=chat_store,
                           cue_store=cue_store,
```

- [ ] **Step 13: Run the cue tests + the relay smoke tests**

Run: `python3 tests/test_cues.py && python3 tests/test_pov.py && python3 tests/test_hud.py`
Expected: PASS for all three (`ALL PASS` each). `test_pov`/`test_hud` confirm the relay module still imports cleanly after the edits.

- [ ] **Step 14: Lint and commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_cues.py
git commit -m "feat(cues): relay CueStore, presets, endpoints & takeover gate (#243)"
```

---

### Task 4: Director Panel — Cues section

Add the send UI: preset buttons fetched read-only from `/cues/presets`, a free-text field, target + level selectors, and a recent-cues list with ack receipts.

**Files:**
- Modify: `src/director/director-panel.html`

**Interfaces:**
- Consumes: `GET /cues/presets` → `{"presets": [str]}`; `GET /cues/data` → `{"cues": [...]}`; `GET /schedule/data` → `{"rows": [{name, ...}]}` (for the target list); `POST /cues/send` `{target, level, text}`.
- Produces: nothing downstream.

- [ ] **Step 1: Read the panel to match its conventions**

Open `src/director/director-panel.html`. Identify (a) how other sections (e.g. the submissions or schedule section) are marked up as a card, (b) the existing `fetch`/poll helper and how it prefixes `window.RC_API_BASE` (the `RC_API()` wrapper), and (c) the existing polling registration. Reuse those — do NOT introduce a new fetch pattern.

- [ ] **Step 2: Add the Cues card markup**

Add a section consistent with the surrounding cards (place it near the chat/submissions section). Use the page's existing class names; the structure must contain:

```html
<section class="card" id="cuesCard">
  <h2>Cues</h2>
  <div id="cuePresets" class="cue-presets"><!-- buttons injected from /cues/presets --></div>
  <div class="cue-compose">
    <select id="cueTarget" aria-label="Cue target"></select>
    <select id="cueLevel" aria-label="Cue level">
      <option value="info">Info</option>
      <option value="critical">Critical</option>
    </select>
    <input id="cueText" type="text" maxlength="200" placeholder="Cue text…" />
    <button id="cueSend" type="button">Send</button>
  </div>
  <ul id="cueRecent" class="cue-recent"><!-- recent cues + ack status --></ul>
</section>
```

- [ ] **Step 3: Populate presets + target dropdown**

In the page script, add (using the page's `RC_API()` wrapper — shown here as `RC_API`):

```javascript
async function loadCuePresets() {
  try {
    const r = await fetch(RC_API('/cues/presets'), { cache: 'no-store' });
    const { presets } = await r.json();
    const box = document.getElementById('cuePresets');
    box.innerHTML = '';
    (presets || []).forEach(text => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'cue-preset'; b.textContent = text;
      b.addEventListener('click', () => { document.getElementById('cueText').value = text; });
      box.appendChild(b);
    });
  } catch (e) { /* presets are optional (e.g. --no-hud); leave free-text only */ }
}

async function loadCueTargets() {
  const sel = document.getElementById('cueTarget');
  sel.innerHTML = '<option value="all">All talent</option>'
                + '<option value="on-air">On air</option>';
  try {
    const r = await fetch(RC_API('/schedule/data'), { cache: 'no-store' });
    const { rows } = await r.json();
    const seen = new Set();
    (rows || []).forEach(row => {
      const name = (row.name || '').trim();
      if (name && !seen.has(name)) {
        seen.add(name);
        const o = document.createElement('option');
        o.value = name; o.textContent = name;   // server normalizes via asset_key
        sel.appendChild(o);
      }
    });
  } catch (e) { /* keep All / On air */ }
}
```

- [ ] **Step 4: Wire send + recent list**

```javascript
async function sendCue() {
  const target = document.getElementById('cueTarget').value;
  const level = document.getElementById('cueLevel').value;
  const text = document.getElementById('cueText').value.trim();
  if (!text) return;
  const r = await fetch(RC_API('/cues/send'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, level, text }) });
  const res = await r.json();
  if (res.error) { alert('Cue failed: ' + res.error); return; }
  document.getElementById('cueText').value = '';
  pollCueRecent();
}

async function pollCueRecent() {
  try {
    const r = await fetch(RC_API('/cues/data'), { cache: 'no-store' });
    const { cues } = await r.json();
    const ul = document.getElementById('cueRecent');
    ul.innerHTML = '';
    (cues || []).slice(-12).reverse().forEach(c => {
      const li = document.createElement('li');
      const seen = c.ack ? ' ✓ seen' : (c.level === 'critical' ? ' …pending' : '');
      li.textContent = `[${c.level}] → ${c.target}: ${c.text}${seen}`;
      if (c.level === 'critical' && c.ack) li.className = 'cue-acked';
      ul.appendChild(li);
    });
  } catch (e) { /* transient; next poll retries */ }
}

document.getElementById('cueSend').addEventListener('click', sendCue);
```

Register `pollCueRecent` on the page's existing poll interval (match how `pollChat`/submissions polling is registered — e.g. add it to the same `setInterval` group, ~3 s). Call `loadCuePresets()`, `loadCueTargets()`, and `pollCueRecent()` once on load.

- [ ] **Step 5: Verify rendering manually against a running relay**

Use the **racecast-local-uat** skill to stand up a real-league dev build (relay + panel) and confirm: presets render from the Sheet column, sending a cue to a target shows it in "recent", a critical cue shows "…pending" then "✓ seen" after the cockpit acks. (No unit test — HTML/JS surface.)

- [ ] **Step 6: Lint (Python untouched) and commit**

```bash
python3 tools/lint.py
git add src/director/director-panel.html
git commit -m "feat(cues): director panel send UI + ack receipts (#243)"
```

---

### Task 5: Commentator Cockpit — cue receiver

Add the talent side: a 4th poller that renders critical cues as a sticky banner with an Acknowledge button and info cues as auto-fading toasts.

**Files:**
- Modify: `src/cockpit/cockpit.html`

**Interfaces:**
- Consumes: `GET /cockpit/cues` → `{"cues": [{id, level, text, from, ...}]}`; `POST /cockpit/cues/ack` `{id}`.
- Produces: nothing downstream.

- [ ] **Step 1: Read the cockpit to match its conventions**

Open `src/cockpit/cockpit.html`. Note (a) the existing pollers (`pollTally`, `pollProgram`, `pollTimer`, `pollChat`) and their interval registration, (b) the `RC_API()`/fetch wrapper, and (c) where the tally banner sits (the cue banner should sit at the top, above the program monitor, so it is unmissable). Reuse the existing fetch + DOM idioms; render text via `textContent` (XSS-safe).

- [ ] **Step 2: Add the cue banner container**

Near the top of the cockpit body (above the program monitor):

```html
<div id="cueCritical" class="cue-critical" hidden></div>
<div id="cueToasts" class="cue-toasts"></div>
```

- [ ] **Step 3: Add the cue poller + ack**

In the page script:

```javascript
const _shownInfo = new Set();   // info cue ids already toasted (avoid re-toasting each poll)

async function ackCue(id) {
  try {
    await fetch(RC_API('/cockpit/cues/ack'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }) });
  } catch (e) { /* next poll re-shows the banner if the ack failed */ }
  pollCues();
}

async function pollCues() {
  let cues = [];
  try {
    const r = await fetch(RC_API('/cockpit/cues'), { cache: 'no-store' });
    cues = (await r.json()).cues || [];
  } catch (e) { return; }
  // Critical: the most recent active one as a sticky banner with Acknowledge.
  const crit = cues.filter(c => c.level === 'critical');
  const banner = document.getElementById('cueCritical');
  if (crit.length) {
    const c = crit[crit.length - 1];
    banner.textContent = c.text + '  ';
    const btn = document.createElement('button');
    btn.type = 'button'; btn.textContent = 'Acknowledge';
    btn.addEventListener('click', () => ackCue(c.id));
    banner.appendChild(btn);
    banner.hidden = false;
  } else {
    banner.hidden = true; banner.textContent = '';
  }
  // Info: show each new one once as an auto-fading toast.
  cues.filter(c => c.level === 'info' && !_shownInfo.has(c.id)).forEach(c => {
    _shownInfo.add(c.id);
    const t = document.createElement('div');
    t.className = 'cue-toast'; t.textContent = c.text;
    document.getElementById('cueToasts').appendChild(t);
    setTimeout(() => t.remove(), 8000);
  });
}
```

Register `pollCues` on the page's existing interval group (~3 s, alongside `pollChat`) and call it once on load.

- [ ] **Step 4: Add minimal styling**

Add CSS consistent with the page's existing styles so the critical banner is large and high-contrast (e.g. red background, full-width, bold) and toasts are lighter. Match the file's existing CSS conventions (variables/classes).

- [ ] **Step 5: Verify manually against a running relay**

Continuing the **racecast-local-uat** instance: mint a token for a real streamer, open the cockpit, send (from the panel) an info cue (toast appears, fades) and a critical cue to that streamer (sticky banner), click Acknowledge (banner clears; the panel's recent list flips to "✓ seen"). Confirm an "all" cue reaches the commentator and a cue addressed to a different streamer does not.

- [ ] **Step 6: Lint (Python untouched) and commit**

```bash
python3 tools/lint.py
git add src/cockpit/cockpit.html
git commit -m "feat(cues): cockpit cue banner/toast + acknowledge (#243)"
```

---

### Task 6: Producer takeover — pull cues like chat

Make `racecast event takeover` adopt A's active cues over both the tailnet and the Funnel, mirroring the chat pull.

**Files:**
- Modify: `src/racecast.py`

**Interfaces:**
- Consumes: `cue_admin.apply_pulled` (Task 1); `/console/takeover/cues` + `/cues/data` (Task 3); existing `_takeover_get`, `_runtime_dir`, `_fetch_relay_page`, `event_takeover`.
- Produces: nothing downstream.

- [ ] **Step 1: Import cue_admin + add path/reload helpers**

Near `import chat_admin as ca` (line ~47), add:

```python
import cue_admin as cue
```

After `_chat_reload_if_running` (line ~961), add:

```python
def _cues_path():
    return os.path.join(_runtime_dir(), "cues.json")


def _cues_reload_if_running():
    """Best-effort: tell a running local relay to re-read cues.json (handover
    while it is up). A relay that is down loads the file on next start."""
    try:
        _fetch_relay_page("/cues/reload")
        return True
    except Exception:
        return False
```

- [ ] **Step 2: Pull cues inside `event_takeover`**

In `event_takeover`, immediately after the console-versions pull block (after line ~2621, before the event-title adoption at ~2623), add a parallel cue pull. `_takeover_get` works for both the funnel URL (with `secret`) and a plain tailnet URL (no secret), and `time` is already imported by `racecast.py`:

```python
    # Adopt A's active cues (#243), like the chat pull — best-effort, never aborts.
    try:
        if funnel:
            payload = _takeover_get(base + "/cues", secret)
        else:
            payload = _takeover_get("http://%s:%d/cues/data" % (host, port))
        n = cue.apply_pulled(_cues_path(), payload, time.time())
        _cues_reload_if_running()
        print(f"Pulled {n} cue(s) from A.")
    except Exception as exc:
        print(f"note: cue pull failed ({type(exc).__name__}) — continuing takeover.")
```

- [ ] **Step 3: Verify the CLI module imports + routes**

Run: `python3 tests/test_racecast.py`
Expected: PASS (`ALL PASS`) — confirms `racecast.py` still imports and its routing is intact after the edit.

- [ ] **Step 4: Verify the funnel base + endpoint shape line up**

Confirm by reading: `_funnel_takeover_base(host)` returns `https://<host>/console/takeover`, so `base + "/cues"` = `/console/takeover/cues`, which the Task 3 gate rewrites to `["cues","data"]` (producer+step-up). The tailnet branch hits root `/cues/data`. No code change — this is a consistency check; note it in the commit if anything is off.

- [ ] **Step 5: Lint and commit**

```bash
python3 tools/lint.py
git add src/racecast.py
git commit -m "feat(cues): pull cues at producer takeover, tailnet + funnel (#243)"
```

---

### Task 7: Docs, wiki note & screenshots

Document the channel and refresh the two screenshots whose surfaces changed (hard repo rule — same change, not a follow-up).

**Files:**
- Modify: `CLAUDE.md` (relay section — one paragraph), `src/docs/wiki/` (the relay/panel/cockpit page + the `Sheet-Webhook`/Configuration page for the `Cue Preset` column)
- Replace: `src/docs/wiki/images/director-panel.png`, and the cockpit wiki image (whichever file the cockpit page embeds)

**Interfaces:** none.

- [ ] **Step 1: Document the cue channel**

Add a short paragraph to the relay section of `CLAUDE.md` describing: the director cue channel (`/cues/*` director, `/cockpit/cues` + ack identity-scoped, only `/console` funnelled), info-auto-expire vs critical-sticky-until-ack, presets from the Configuration tab `Cue Preset` column, and takeover pull. Add the matching note to the relevant `src/docs/wiki/` page and the `Cue Preset` column to the Configuration-tab documentation on the `Sheet-Webhook` (or Sheet) wiki page.

- [ ] **Step 2: Capture the Director Panel screenshot from a local dev build**

Per the repo rule, run a dev build from `src/` (no `VERSION` stamped) so the version badge stays uniform. Stand up the panel (racecast-local-uat), drive it with the Playwright MCP, and take an **element** screenshot of the panel framed like the existing `director-panel.png`. Save to `src/docs/wiki/images/director-panel.png`.

- [ ] **Step 3: Capture the Cockpit screenshot from the same dev build**

Open the cockpit with a valid token, send a critical cue so the banner is visible, and take the element screenshot framed like the existing cockpit image. Overwrite that file under `src/docs/wiki/images/`.

- [ ] **Step 4: Commit docs + images**

```bash
git add CLAUDE.md src/docs/wiki
git commit -m "docs(cues): document the director cue channel + refresh screenshots (#243)"
```

---

### Task 8: Full verification

Run the exact gates CI runs before opening the PR.

- [ ] **Step 1: Whole test suite**

Run: `python3 tools/run-tests.py`
Expected: every `tests/test_*.py` reports `ALL PASS` (including the new `tests/test_cues.py` and the extended `tests/test_console.py`), and the runner exits 0.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (exit 0).

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: build succeeds; its verify step (tokenization, blanked password, no secrets, preflight present, no shell scripts) passes.

- [ ] **Step 4: Optional synthetic e2e**

Run: `python3 tools/e2e.py`
Expected: the synthetic relay + Control Center come up and the checks pass. (Optional but recommended; the cue endpoints share the relay this harness exercises.)

- [ ] **Step 5: Final commit if anything changed**

```bash
git add -A
git commit -m "chore(cues): verification pass (#243)" || echo "nothing to commit"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** Task 1 = pure logic + takeover `apply_pulled`; Task 2 = policy; Task 3 = store/presets/endpoints/gate; Task 4 = panel send + ack receipt; Task 5 = cockpit banner/toast + ack; Task 6 = takeover pull (tailnet + funnel); Task 7 = docs + screenshots; Task 8 = gates. Every spec section maps to a task.
- **Funnel boundary:** no new public mount — all cue routes ride the existing `/console` gate; `/cues/*` director, `/cockpit/cues*` identity-scoped, `/console/takeover/cues` producer+step-up.
- **Naming consistency:** `cue_admin` functions (`sanitize_cue`, `resolve_target`, `active_cues_for`, `prune`, `validate_payload`, `load_cues`, `write_cues`, `apply_pulled`), `CueStore` methods (`add`, `list`, `data`, `ack`, `reload`), and endpoint paths are used identically across Tasks 1, 3, 4, 5, 6.
- **TDD:** Tasks 1–3 (pure logic, policy, store/parse) are test-first. Tasks 4–5 (HTML/JS) are manually verified against a running relay — the repo has no JS unit harness; the unit guarantees live in the Python layer those pages call.
