# Console roles — Phase 1: Crew roster + role resolution (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Crew-tab CSV reader (`CrewSource`) and a pure `resolve_roles()` resolver to the relay, so a verified identity subject can be mapped to its `{commentator, director, producer}` capability set — with zero change to existing behavior (nothing consumes roles yet; that is Phase 2+).

**Architecture:** Mirror the existing `ScheduleSource` CSV-reading pattern (fetch + last-good cache + `_parse_rows` static method) for a new `Crew` tab with `Name | Director | Producer` boolean columns. Add a side-effect-free `resolve_roles(crew_rows, schedule_keys, subject)` function that unions the *commentator* capability (subject present in the live Schedule roster) with *director/producer* flags from the Crew tab. All additive; no routing, no Funnel, no consumption.

**Tech Stack:** Pure Python 3 stdlib (`csv`, `io`, `threading`, `urllib`). No new dependencies. No-pytest test convention (each `tests/test_*.py` is a runnable script with a `__main__` runner).

## Global Constraints

- Edit only under `src/` (plus `tests/`, `docs/`, `CLAUDE.md`); never `dist/` or `runtime/`.
- All code and docs are **English only**.
- No secrets, machine paths, or real IPs in committed files (Tailscale test IPs are `100.64.0.0/10` constants only). Phase 1 touches none of these but the rule stands.
- Python-only tooling; no `.sh`/`.bat`.
- The relay (`src/relay/racecast-feeds.py`) stays dependency-light (stdlib only) — do **not** import `src/scripts/config.py` or anything heavy into it.
- Tests must run on any machine and in CI (incl. `windows-latest`); no network in unit tests, no machine-specific values.
- Token format stays **unchanged** (identity ≠ authorization, locked decision #3) — Phase 1 introduces no token changes at all.
- Reference spec: `docs/superpowers/specs/2026-06-19-role-based-funnel-access-design.md`.

## File Structure

- **Modify** `src/relay/racecast-feeds.py`:
  - Add crew header/truthy constants near the existing `SCHEDULE_*_HEADERS` block (~line 588).
  - Add `_crew_truthy()` helper.
  - Add `CrewSource` class (modeled on `ScheduleSource`, ~line 1534) with a static `_parse_rows()`.
  - Add the pure `resolve_roles()` function (near `asset_key`, ~line 527, since it depends on `asset_key`).
- **Create** `tests/test_roles.py` — unit checks for crew CSV parsing + `resolve_roles` (auto-discovered by `tools/run-tests.py` via glob; no registration needed).
- **Modify** `CLAUDE.md` — add the `tests/test_roles.py` line to the documented test list.

How tests load the hyphenated relay module (copy verbatim from `tests/test_pov.py`):
```python
import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
```

Each test file ends with the project's runner:
```python
if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

---

### Task 1: Crew CSV parsing (`_parse_rows` + constants + truthy helper)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (constants after line 590; `_crew_truthy` + `CrewSource` skeleton after `ScheduleSource`, ~line 1643)
- Test: `tests/test_roles.py` (create)

**Interfaces:**
- Consumes: nothing (uses existing `csv`, `io`, `asset_key` already in the module).
- Produces:
  - `CREW_NAME_HEADERS = ("name", "crew", "person")`, `CREW_DIRECTOR_HEADERS = ("director",)`, `CREW_PRODUCER_HEADERS = ("producer",)`, `CREW_TRUTHY = frozenset({"x", "yes", "true", "1", "y", "✓"})`
  - `_crew_truthy(v) -> bool`
  - `CrewSource._parse_rows(text) -> list[tuple[str, bool, bool]] | None` — rows of `(name, is_director, is_producer)`; `None` when no usable rows. Header mode (recognized `Name` header) locates columns by name; positional fallback (no name header) uses col0=name, col1=director, col2=producer and skips a leading header-like row. Rows with an empty name are skipped.

- [ ] **Step 1: Write the failing test**

Create `tests/test_roles.py`:
```python
#!/usr/bin/env python3
"""Stdlib unit checks for the Crew roster + role resolution (#216 phase 1).
Run: python3 tests/test_roles.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_crew_truthy_allowlist():
    for yes in ("x", "X", " yes ", "TRUE", "1", "y", "✓"):
        assert m._crew_truthy(yes), yes
    for no in ("", " ", "0", "no", "false", "-", "maybe"):
        assert not m._crew_truthy(no), no


def t_parse_header_mode_locates_columns_by_name():
    text = "Name,Director,Producer\nAlice,X,X\nBob,x,\nCarol,,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, True),
                    ("Bob", True, False),
                    ("Carol", False, False)], rows


def t_parse_header_mode_columns_may_move_and_extras_ignored():
    # Producer left of Director, plus an unrelated Contact column.
    text = "Name,Contact,Producer,Director\nAlice,@a,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", False, True)], rows


def t_parse_skips_blank_name_rows():
    text = "Name,Director,Producer\n,X,\nBob,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Bob", True, False)], rows


def t_parse_positional_fallback_no_header():
    # No recognized name header -> col0=name, col1=director, col2=producer.
    text = "Alice,X,X\nBob,x,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, True), ("Bob", True, False)], rows


def t_parse_positional_fallback_skips_headerlike_first_row():
    # A header-like first row (col1/col2 are header words) is dropped even when
    # the name header itself is unrecognized.
    text = "Person?,Director,Producer\nAlice,X,\n"
    rows = m.CrewSource._parse_rows(text)
    assert rows == [("Alice", True, False)], rows


def t_parse_empty_returns_none():
    assert m.CrewSource._parse_rows("") is None
    assert m.CrewSource._parse_rows("\n") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute '_crew_truthy'` (or `CrewSource`).

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, add the constants right after the `SCHEDULE_STINT_HEADERS = ("stint",)` line (~line 590):
```python
# Crew tab headers (matched case-insensitively). The Crew tab carries
# Name | Director | Producer boolean columns; commentator capability is NOT
# listed here -- it is implied by presence in the live Schedule roster
# (see resolve_roles). See issue #216 / the role-based-funnel-access spec.
CREW_NAME_HEADERS = ("name", "crew", "person")
CREW_DIRECTOR_HEADERS = ("director",)
CREW_PRODUCER_HEADERS = ("producer",)
CREW_TRUTHY = frozenset({"x", "yes", "true", "1", "y", "✓"})


def _crew_truthy(v):
    """True iff a Crew cell marks the role set (case-insensitive, trimmed)."""
    return (v or "").strip().lower() in CREW_TRUTHY
```

Then add the `CrewSource` class immediately after the `ScheduleSource` class (after line 1643):
```python
class CrewSource:
    """Reads the Crew roster from the Google Sheet (CSV) with last-good + fallback.

    Mirrors ScheduleSource: a Name | Director | Producer tab giving the
    director/producer capabilities. Commentator capability is resolved
    separately from the live Schedule roster (see resolve_roles). A missing or
    empty tab is non-fatal -- it simply yields no director/producer rows."""

    def __init__(self, csv_url, cache_path=None):
        self.csv_url = csv_url
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.rows = []
        self.last_ok = None
        self.last_error = None

    @staticmethod
    def _parse_rows(text):
        """CSV -> [(name, is_director, is_producer)] or None.

        Header mode (opt-in): if a recognized Name header is present, the
        Name/Director/Producer columns are located by header text (so they may
        move and extra columns are ignored). Positional fallback (no name
        header): col0=name, col1=director, col2=producer, dropping a leading
        header-like row. Rows with an empty name are skipped."""
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return None
        header = [(h or "").strip().lower() for h in rows[0]]
        name_i = next((header.index(h) for h in CREW_NAME_HEADERS if h in header), None)
        if name_i is not None:
            dir_i = next((header.index(h) for h in CREW_DIRECTOR_HEADERS if h in header), None)
            prod_i = next((header.index(h) for h in CREW_PRODUCER_HEADERS if h in header), None)
            out = []
            for line, r in enumerate(rows, 1):
                if line == 1:
                    continue                       # the header row itself
                name = r[name_i].strip() if len(r) > name_i else ""
                if not name:
                    continue
                is_dir = _crew_truthy(r[dir_i]) if dir_i is not None and len(r) > dir_i else False
                is_prod = _crew_truthy(r[prod_i]) if prod_i is not None and len(r) > prod_i else False
                out.append((name, is_dir, is_prod))
            return out or None
        # Positional fallback: col0=name, col1=director, col2=producer.
        start = 0
        if rows:
            r0 = [(c or "").strip().lower() for c in rows[0]]
            if (len(r0) > 1 and r0[1] in CREW_DIRECTOR_HEADERS) or \
               (len(r0) > 2 and r0[2] in CREW_PRODUCER_HEADERS):
                start = 1                          # drop a header-like first row
        out = []
        for r in rows[start:]:
            name = r[0].strip() if r else ""
            if not name:
                continue
            is_dir = _crew_truthy(r[1]) if len(r) > 1 else False
            is_prod = _crew_truthy(r[2]) if len(r) > 2 else False
            out.append((name, is_dir, is_prod))
        return out or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_roles.py`
Expected: `ok t_crew_truthy_allowlist` … `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no errors.
```bash
git add src/relay/racecast-feeds.py tests/test_roles.py
git commit -m "$(cat <<'MSG'
feat(relay): parse the Crew roster tab (#216 phase 1)

Adds CrewSource._parse_rows + the Name/Director/Producer header constants and
the truthy-cell allow-list. Pure parsing only; nothing consumes it yet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: `CrewSource` fetch/refresh (last-good reader)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (extend `CrewSource` from Task 1)
- Test: `tests/test_roles.py` (extend)

**Interfaces:**
- Consumes: `CrewSource._parse_rows` (Task 1).
- Produces:
  - `CrewSource.fetch(timeout=15) -> list | None` — HTTP GET the CSV URL, parse; sets `last_error` on failure; returns `None` (never raises) on any network/parse error.
  - `CrewSource.refresh(timeout=15) -> bool` — on success stores `self.rows`, sets `last_ok`, clears `last_error`, returns `True`; on failure keeps last-good and returns `False`. No `csv_url` → `False`.
  - `CrewSource.get() -> list[tuple[str, bool, bool]]` — thread-safe snapshot of the current rows (empty list before first success).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roles.py` (before the `__main__` block):
```python
def t_crewsource_no_url_refresh_is_false_and_get_empty():
    src = m.CrewSource(csv_url="")
    assert src.refresh() is False
    assert src.get() == []


def t_crewsource_get_returns_snapshot_copy():
    src = m.CrewSource(csv_url="")
    src.rows = [("Alice", True, False)]
    snap = src.get()
    assert snap == [("Alice", True, False)]
    snap.append(("X", False, False))       # mutating the snapshot must not leak
    assert src.get() == [("Alice", True, False)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL — `AttributeError: 'CrewSource' object has no attribute 'refresh'` (or `get`).

- [ ] **Step 3: Write minimal implementation**

Add these methods inside `CrewSource` (after `_parse_rows`):
```python
    def get(self):
        with self.lock:
            return list(self.rows)

    def fetch(self, timeout=15):
        if not self.csv_url:
            return None
        try:
            req = Request(self.csv_url, headers={"User-Agent": "racecast-feeds/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            rows = self._parse_rows(text)
            if not rows:
                self.last_error = ("Crew tab reachable, but no rows found "
                                   "(correct tab name? a Name column?)")
                return None
            return rows
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def refresh(self, timeout=15):
        rows = self.fetch(timeout)
        if rows:
            with self.lock:
                self.rows = rows
                self.last_ok = time.time()
                self.last_error = None
            return True
        return False
```
(`Request`, `urlopen`, `time`, `threading` are already imported at the top of the module — confirm with `grep -n "from urllib.request import\|^import time\|^import threading" src/relay/racecast-feeds.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_roles.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/relay/racecast-feeds.py tests/test_roles.py
git commit -m "$(cat <<'MSG'
feat(relay): CrewSource fetch/refresh with last-good (#216 phase 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: `resolve_roles` pure resolver

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `resolve_roles` right after `asset_key`, ~line 527)
- Test: `tests/test_roles.py` (extend)

**Interfaces:**
- Consumes: `asset_key` (existing), the `(name, is_director, is_producer)` row shape from `CrewSource`.
- Produces:
  - `resolve_roles(crew_rows, schedule_keys, subject) -> set[str]` — capabilities drawn from `{"commentator", "director", "producer"}`. `commentator` iff `subject in schedule_keys`; `director`/`producer` from any crew row whose `asset_key(name) == subject` with the flag set. Unknown subject → empty set. `subject` is assumed already `asset_key`-normalized (the verified token's key).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roles.py` (before `__main__`):
```python
def t_resolve_commentator_from_schedule_only():
    roles = m.resolve_roles([], {"alice"}, "alice")
    assert roles == {"commentator"}, roles


def t_resolve_director_and_producer_from_crew():
    crew = [("Alice", True, True), ("Bob", True, False)]
    assert m.resolve_roles(crew, set(), "alice") == {"director", "producer"}
    assert m.resolve_roles(crew, set(), "bob") == {"director"}


def t_resolve_multi_role_union_commentator_plus_director():
    crew = [("Alice", True, False)]
    assert m.resolve_roles(crew, {"alice"}, "alice") == {"commentator", "director"}


def t_resolve_name_normalized_via_asset_key():
    # "Alice O'Brien" normalizes to the same key the token carries.
    subject = m.asset_key("Alice O'Brien")
    crew = [("Alice O'Brien", False, True)]
    assert m.resolve_roles(crew, set(), subject) == {"producer"}


def t_resolve_unknown_subject_is_empty():
    crew = [("Alice", True, True)]
    assert m.resolve_roles(crew, {"alice"}, "stranger") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_roles.py`
Expected: FAIL — `AttributeError: module 'irofeeds' has no attribute 'resolve_roles'`.

- [ ] **Step 3: Write minimal implementation**

Add right after the `asset_key` function (after line 527):
```python
def resolve_roles(crew_rows, schedule_keys, subject):
    """Resolve a verified identity *subject* to its capability set for this event.

    crew_rows: iterable of (name, is_director, is_producer) from CrewSource.get().
    schedule_keys: set of asset_key-normalized streamer names present in the live
        Schedule/Qualifying roster.
    subject: the asset_key-normalized person name from the verified token.

    Returns a subset of {"commentator", "director", "producer"}:
    - "commentator" iff subject appears in schedule_keys (own-row capability, as
      today -- streamers are never tagged for commentator in the Crew tab);
    - "director"/"producer" from any Crew row whose name normalizes to subject.
    An unknown subject (no crew row, not in the schedule) yields the empty set.
    Identity != authorization: this is the only place roles are derived, per the
    role-based-funnel-access spec (#216)."""
    roles = set()
    if subject in schedule_keys:
        roles.add("commentator")
    for name, is_dir, is_prod in crew_rows:
        if asset_key(name) != subject:
            continue
        if is_dir:
            roles.add("director")
        if is_prod:
            roles.add("producer")
    return roles
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_roles.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/relay/racecast-feeds.py tests/test_roles.py
git commit -m "$(cat <<'MSG'
feat(relay): resolve_roles maps a token subject to its capability set (#216 phase 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: Documentation + full local gate

**Files:**
- Modify: `CLAUDE.md` (test list)

**Interfaces:**
- Consumes: everything above.
- Produces: a green full suite + build, and a documented test entry.

- [ ] **Step 1: Add the test to the documented list**

In `CLAUDE.md`, in the `## Commands` test block, add a line after the existing
`tests/test_streams.py` entry (keep the column alignment of the surrounding lines):
```
python3 tests/test_roles.py          # crew roster (CrewSource) + role resolution (#216)
```

- [ ] **Step 2: Run the whole suite**

Run: `python3 tools/run-tests.py`
Expected: ends with `ALL TEST FILES PASS` (and the run includes `== test_roles.py`).

- [ ] **Step 3: Lint the repo**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Build self-verify**

Run: `python3 tools/build.py`
Expected: exits 0 (tokenization / blanked-password / no-secrets / no-shell-scripts checks all pass).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'MSG'
docs: list test_roles.py in the CLAUDE.md test index (#216 phase 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Self-Review

**Spec coverage (Phase 1 scope only):**
- Spec §B "Crew roster (`CrewSource`)": Task 1 (parsing + constants + truthy) + Task 2 (fetch/refresh/last-good). ✓
- Spec §A/§B "pure `resolve_roles(crew_rows, schedule_keys, subject)`": Task 3. ✓
- Spec "Testing → `tests/test_roles.py` (CrewSource parse + resolve_roles)": Tasks 1–3 + Task 4 wiring. ✓
- Deliberately **out of Phase 1** (later phases, not gaps): `--crew-tab` CLI flag and wiring `CrewSource` into the relay's live refresh loop (Phase 2/3, where `_console_auth` consumes roles); `_console_auth`, `/console/*`, Funnel, link CLI, crew editor, takeover, Companion proxy, docs/wiki. Keeping Phase 1 to inert, tested pure code is the "no behavior change" boundary from the spec's phasing.

**Placeholder scan:** none — every code/test step shows complete code and exact commands.

**Type consistency:** the row tuple `(name, is_director, is_producer)` is identical across `CrewSource._parse_rows`, `CrewSource.get`, and `resolve_roles`; `resolve_roles(crew_rows, schedule_keys, subject)` signature matches between the spec, Task 3 interface, and tests; capability strings are exactly `"commentator"`, `"director"`, `"producer"` everywhere.

**Minor deviation from spec note:** the spec's §B mentions a positional fallback "col 0 = name, col 1 = director, col 2 = producer"; Task 1 implements exactly that plus a header-like-first-row guard (cheap, testable robustness for a tab we own). No behavioral conflict.
