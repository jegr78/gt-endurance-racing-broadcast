# Console roles — Phase 2: Authorization policy (capability matrix + decision) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure, dependency-free authorization-policy module (`src/scripts/console_policy.py`) that maps a `/console` request (path segments + HTTP method) to its minimum capability + step-up requirement, and decides allow/forbidden/step-up/not-found given a resolved role set — with zero behavior change (nothing consumes it yet; Phase 3's `_console_auth` handler will).

**Architecture:** A single pure module. `min_capability(segments, method) -> Requirement | None` encodes the spec's capability matrix (§C) over the relay's real segment-list routes (mirroring the relay's own `p == [...]` / `len(p)` dispatch ordering, most-specific first). `decide(roles, segments, method, has_step_up) -> str` returns one of `"allow" | "forbidden" | "step_up_required" | "not_found"`. The module imports nothing but `collections` — token verification (`cockpit_auth`) and role resolution (`resolve_roles`) stay in their own units; the Phase 3 handler wires identity → roles → `decide`.

**Tech Stack:** Pure Python 3 stdlib (`collections.namedtuple`). No-pytest test convention.

## Global Constraints

- Edit only under `src/`, `tests/`, `docs/`, `CLAUDE.md`; never `dist/` or `runtime/`.
- All code and docs are **English only**.
- No secrets, machine paths, or real IPs in committed files.
- `src/scripts/console_policy.py` is **pure**: no I/O, no network, no token/crypto logic, and it imports only `collections`. It must NOT import `cockpit_auth`, `config.py`, or the relay.
- Identity ≠ authorization (locked decision #3): this module never sees or verifies a token. `decide()` receives an already-resolved role set and an already-computed `has_step_up` boolean.
- Capability strings are exactly `"commentator"`, `"director"`, `"producer"`; the policy keyword for "any authenticated identity" is `"any"`.
- Tests must run on any machine and in CI (incl. `windows-latest`); pure, no network.
- The matrix must mirror the relay's real routes — the source of truth is the segment-list dispatch in `src/relay/racecast-feeds.py` `do_GET`/`do_POST` (e.g. `["set","stint",n]`, `["mode",x]`, `["timer","start"]`, `["next"]`, `["set",feed,n]`). A drift between this table and the real routes is the bug class this phase must avoid.
- Reference spec: `docs/superpowers/specs/2026-06-19-role-based-funnel-access-design.md` §C (capability matrix) and §D (step-up).

### The capability matrix (spec §C, over real segment-list routes)

Segments are the path AFTER the `/console` prefix is stripped (so `/console/set/stint/4` → `["set","stint","4"]`). "Read" routes are `GET`; control routes may be `GET` (Companion HTTP module style) or `POST` — capability does not depend on method here, except where noted.

| Segments (after `/console`) | Capability | Step-up |
|---|---|---|
| `[]`, `["status"]`, `["console"]` | any | no |
| `["data"]`, `["program"]` | any | no |
| `["hud", ...]` (all: `["hud"]`, `["hud","data"]`, `["hud","override.css"]`, `["hud","preview",...]`, `["hud","assets",...]`) | any | no |
| `["preview", ...]` (program monitor frames) | any | no |
| `["timer","data"]`, `["setup","data"]`, `["schedule","data"]`, `["qualifying","data"]` | any | no |
| `["chat","data"]`, `["chat","reload"]`, `["chat","send"]` | any | no |
| `["cockpit"]`, `["cockpit","data"]`, `["cockpit","program"]`, `["cockpit","timer"]`, `["cockpit","chat","data"]` | any | no |
| `["submit"]`, `["cockpit","submit"]` | commentator | no |
| `["next"]`, `["prev",x]`, `["reload"]`, `["reload",feed]`, `["set",feed,n]` (feed = `A`/`B`) | director | no |
| `["panel"]`, `["pov",...]`, `["setup",...]` (except `["setup","data"]`), `["timer",x]` (x≠`data`), `["schedule","set"]`, `["qualifying","set"]`, `["event","title"]`, `["submissions"]`, `["submissions",x]` | director | no |
| `["prod"]` (producer landing page — view only) | producer | no |
| `["set","stint",n]`, `["mode",x]`, `["takeover",...]`, `["cockpit","versions"]` | producer | **yes** |
| anything else | — (`min_capability` → `None`, i.e. `decide` → `"not_found"`) | — |

---

## File Structure

- **Create** `src/scripts/console_policy.py` — the pure policy module (matrix + decision + constants).
- **Create** `tests/test_console.py` — exhaustive unit checks for `min_capability` and `decide`.
- **Modify** `CLAUDE.md` — add the `tests/test_console.py` line to the documented test list.

Test loader (this module is a normal underscore-importable file, so no importlib gymnastics — but `src/scripts` is not a package on `sys.path` by default; load it the same way `tests/test_streams.py` loads scripts):
```python
import importlib.util, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod
cp = _load("console_policy", os.path.join("src", "scripts", "console_policy.py"))
```

Each test file ends with the runner:
```python
if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

---

### Task 1: Capability matrix (`min_capability`)

**Files:**
- Create: `src/scripts/console_policy.py`
- Test: `tests/test_console.py` (create)

**Interfaces:**
- Consumes: nothing (stdlib `collections`).
- Produces:
  - Constants `COMMENTATOR = "commentator"`, `DIRECTOR = "director"`, `PRODUCER = "producer"`, `ANY = "any"`.
  - `Requirement = collections.namedtuple("Requirement", ("capability", "step_up"))`.
  - `min_capability(segments, method="GET") -> Requirement | None` — `segments` is a list/tuple of path parts after `/console`. Returns the minimum `Requirement`, or `None` if the route is not a recognized console route.

- [ ] **Step 1: Write the failing test**

Create `tests/test_console.py`:
```python
#!/usr/bin/env python3
"""Stdlib unit checks for the /console authorization policy (#216 phase 2).
Run: python3 tests/test_console.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


cp = _load("console_policy", os.path.join("src", "scripts", "console_policy.py"))


def _cap(segs, method="GET"):
    r = cp.min_capability(segs, method)
    return None if r is None else (r.capability, r.step_up)


def t_any_authenticated_reads():
    for segs in ([], ["status"], ["console"], ["data"], ["program"],
                 ["hud"], ["hud", "data"], ["hud", "override.css"],
                 ["hud", "preview"], ["hud", "assets", "flags", "de.png"],
                 ["preview", "program"], ["preview", "feed", "A"],
                 ["timer", "data"], ["setup", "data"],
                 ["schedule", "data"], ["qualifying", "data"],
                 ["chat", "data"], ["chat", "reload"],
                 ["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
                 ["cockpit", "timer"], ["cockpit", "chat", "data"]):
        assert _cap(segs) == ("any", False), segs


def t_chat_send_is_any_authenticated():
    assert _cap(["chat", "send"], "POST") == ("any", False)


def t_submit_is_commentator():
    assert _cap(["submit"], "POST") == ("commentator", False)
    assert _cap(["cockpit", "submit"], "POST") == ("commentator", False)


def t_director_feed_and_schedule_control():
    for segs in (["next"], ["prev", "A"], ["reload"], ["reload", "A"],
                 ["set", "A", "3"], ["set", "B", "12"]):
        assert _cap(segs) == ("director", False), segs


def t_director_panel_setup_timer_pov_submissions():
    for segs in (["panel"], ["pov", "reload"], ["pov", "set"],
                 ["setup", "set", "stint", "Alice"],
                 ["timer", "start"], ["timer", "stop"], ["timer", "set", "1:00:00"],
                 ["schedule", "set"], ["qualifying", "set"], ["event", "title"],
                 ["submissions"], ["submissions", "approve"], ["submissions", "reject"]):
        assert _cap(segs) == ("director", False), segs


def t_setup_data_and_timer_data_are_reads_not_director():
    # The read endpoints under setup/timer must stay "any", not escalate to director.
    assert _cap(["setup", "data"]) == ("any", False)
    assert _cap(["timer", "data"]) == ("any", False)


def t_producer_stepup_irreversible_ops():
    for segs in (["set", "stint", "4"], ["mode", "race"], ["mode", "qualifying"],
                 ["takeover", "status"], ["takeover", "chat"], ["takeover", "versions"],
                 ["cockpit", "versions"]):
        assert _cap(segs) == ("producer", True), segs


def t_prod_page_is_producer_view_no_stepup():
    assert _cap(["prod"]) == ("producer", False)


def t_set_stint_not_confused_with_set_feed():
    # set/stint/<n> is producer+stepup; set/<feed>/<n> is director. Ordering matters.
    assert _cap(["set", "stint", "4"]) == ("producer", True)
    assert _cap(["set", "A", "4"]) == ("director", False)


def t_unknown_route_is_none():
    for segs in (["bogus"], ["timer"], ["set"], ["set", "A"],
                 ["cockpit", "nope"], ["mode"]):
        assert cp.min_capability(segs) is None, segs


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFound` for `console_policy.py` (it doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/console_policy.py`:
```python
#!/usr/bin/env python3
"""Pure authorization policy for the funnelled /console namespace (#216 phase 2).

Identity != authorization (locked decision #3): a verified token proves *who*
(see cockpit_auth), the live roster resolves *roles* (see resolve_roles in the
relay), and THIS module decides whether a given role set may reach a given
/console subpath. No I/O, no token/crypto logic, no routes -- the Phase 3
_console_auth handler wires identity -> roles -> decide().

The matrix mirrors the relay's real segment-list routes (do_GET/do_POST in
src/relay/racecast-feeds.py); keep the two in sync. Spec: the
role-based-funnel-access design, sections C (matrix) and D (step-up).
"""

import collections

# Capabilities. A resolved role set is a subset of {COMMENTATOR, DIRECTOR,
# PRODUCER}. ANY is the policy keyword meaning "any authenticated identity,
# regardless of roles" -- it is never a member of a role set.
COMMENTATOR = "commentator"
DIRECTOR = "director"
PRODUCER = "producer"
ANY = "any"

# Decision outcomes returned by decide().
ALLOW = "allow"
FORBIDDEN = "forbidden"
STEP_UP_REQUIRED = "step_up_required"
NOT_FOUND = "not_found"

Requirement = collections.namedtuple("Requirement", ("capability", "step_up"))


def min_capability(segments, method="GET"):
    """Map a /console request to its minimum Requirement, or None if the route is
    not a recognized console route. *segments* is the path AFTER the /console
    prefix (e.g. /console/set/stint/4 -> ["set","stint","4"]). Ordering is
    most-specific-first, matching the relay's own dispatch."""
    p = list(segments)

    # --- producer + step-up: irreversible broadcast-control ops (spec D) ---
    if len(p) == 3 and p[:2] == ["set", "stint"]:
        return Requirement(PRODUCER, True)
    if len(p) == 2 and p[0] == "mode":
        return Requirement(PRODUCER, True)
    if p and p[0] == "takeover" and len(p) >= 2:
        return Requirement(PRODUCER, True)
    if p == ["cockpit", "versions"]:
        return Requirement(PRODUCER, True)

    # --- producer view (no step-up to merely open the page) ---
    if p == ["prod"]:
        return Requirement(PRODUCER, False)

    # --- director: feed / schedule / timer / setup / pov control ---
    if p == ["next"]:
        return Requirement(DIRECTOR, False)
    if len(p) == 2 and p[0] == "prev":
        return Requirement(DIRECTOR, False)
    if p == ["reload"] or (len(p) == 2 and p[0] == "reload"):
        return Requirement(DIRECTOR, False)
    if len(p) == 3 and p[0] == "set":          # ["set", A|B, n]; stint handled above
        return Requirement(DIRECTOR, False)
    if p == ["panel"]:
        return Requirement(DIRECTOR, False)
    if p and p[0] == "pov":                     # all /pov/* are control
        return Requirement(DIRECTOR, False)
    if p and p[0] == "setup" and p != ["setup", "data"]:
        return Requirement(DIRECTOR, False)
    if len(p) >= 2 and p[0] == "timer" and p[1] != "data":
        return Requirement(DIRECTOR, False)
    if p == ["schedule", "set"] or p == ["qualifying", "set"]:
        return Requirement(DIRECTOR, False)
    if p == ["event", "title"]:
        return Requirement(DIRECTOR, False)
    if p == ["submissions"] or (len(p) == 2 and p[0] == "submissions"):
        return Requirement(DIRECTOR, False)

    # --- commentator: own-row stream-link submission ---
    if p == ["submit"] or p == ["cockpit", "submit"]:
        return Requirement(COMMENTATOR, False)

    # --- any authenticated: read-only monitors + identity-forced chat ---
    if p in ([], ["status"], ["console"], ["data"], ["program"]):
        return Requirement(ANY, False)
    if p and p[0] in ("hud", "preview"):
        return Requirement(ANY, False)
    if p in (["timer", "data"], ["setup", "data"],
             ["schedule", "data"], ["qualifying", "data"]):
        return Requirement(ANY, False)
    if p in (["chat", "data"], ["chat", "reload"], ["chat", "send"]):
        return Requirement(ANY, False)
    if p in (["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
             ["cockpit", "timer"], ["cockpit", "chat", "data"]):
        return Requirement(ANY, False)

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_console.py`
Expected: `ok t_any_authenticated_reads` … `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
Expected: no errors.
```bash
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "$(cat <<'MSG'
feat(relay): /console capability matrix (#216 phase 2)

Pure console_policy.min_capability mapping a /console request (segments +
method) to its minimum capability + step-up requirement, mirroring the relay's
real segment-list routes. Nothing consumes it yet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: Decision function (`decide`)

**Files:**
- Modify: `src/scripts/console_policy.py` (add `decide` after `min_capability`)
- Test: `tests/test_console.py` (extend)

**Interfaces:**
- Consumes: `min_capability`, the decision-outcome constants.
- Produces:
  - `decide(roles, segments, method="GET", has_step_up=False) -> str` — returns `ALLOW` / `FORBIDDEN` / `STEP_UP_REQUIRED` / `NOT_FOUND`. `roles` is the already-resolved set (a subset of `{"commentator","director","producer"}`, possibly empty). Identity is assumed already verified by the caller (Phase 3); `decide` is policy only. `has_step_up` is the caller's already-computed result of the shared-producer-secret check.

  Logic: look up `Requirement`; `None` → `NOT_FOUND`. If `capability != ANY` and `capability not in roles` → `FORBIDDEN`. Else if `step_up` and not `has_step_up` → `STEP_UP_REQUIRED`. Else `ALLOW`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_console.py` (before the `__main__` runner):
```python
def t_decide_any_allows_even_empty_roles():
    # A valid identity with no roles can still reach read-only monitors.
    assert cp.decide(set(), ["status"]) == cp.ALLOW
    assert cp.decide(set(), ["cockpit", "data"]) == cp.ALLOW


def t_decide_unknown_route_is_not_found():
    assert cp.decide({"director"}, ["bogus"]) == cp.NOT_FOUND


def t_decide_commentator_blocked_from_director_op():
    assert cp.decide({"commentator"}, ["next"]) == cp.FORBIDDEN


def t_decide_director_allowed_director_op():
    assert cp.decide({"director"}, ["next"]) == cp.ALLOW
    assert cp.decide({"commentator", "director"}, ["set", "A", "3"]) == cp.ALLOW


def t_decide_commentator_allowed_submit():
    assert cp.decide({"commentator"}, ["cockpit", "submit"], "POST") == cp.ALLOW
    assert cp.decide({"director"}, ["cockpit", "submit"], "POST") == cp.FORBIDDEN


def t_decide_producer_stepup_enforced():
    # Producer without the second factor is told to step up, not allowed.
    assert cp.decide({"producer"}, ["set", "stint", "4"]) == cp.STEP_UP_REQUIRED
    assert cp.decide({"producer"}, ["set", "stint", "4"], has_step_up=True) == cp.ALLOW


def t_decide_stepup_route_still_requires_the_role_first():
    # A director (not producer) hitting a producer op is FORBIDDEN regardless of step-up.
    assert cp.decide({"director"}, ["mode", "race"]) == cp.FORBIDDEN
    assert cp.decide({"director"}, ["mode", "race"], has_step_up=True) == cp.FORBIDDEN


def t_decide_prod_page_needs_producer_no_stepup():
    assert cp.decide({"producer"}, ["prod"]) == cp.ALLOW
    assert cp.decide({"director"}, ["prod"]) == cp.FORBIDDEN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_console.py`
Expected: FAIL — `AttributeError: module 'console_policy' has no attribute 'decide'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/console_policy.py` after `min_capability`:
```python
def decide(roles, segments, method="GET", has_step_up=False):
    """Policy decision for a /console request. Identity is assumed already
    verified by the caller; *roles* is the resolved capability set (possibly
    empty), *has_step_up* the caller's shared-producer-secret check result.
    Returns ALLOW / FORBIDDEN / STEP_UP_REQUIRED / NOT_FOUND."""
    req = min_capability(segments, method)
    if req is None:
        return NOT_FOUND
    if req.capability != ANY and req.capability not in roles:
        return FORBIDDEN
    if req.step_up and not has_step_up:
        return STEP_UP_REQUIRED
    return ALLOW
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_console.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

Run: `python3 tools/lint.py`
```bash
git add src/scripts/console_policy.py tests/test_console.py
git commit -m "$(cat <<'MSG'
feat(relay): /console authorization decision (#216 phase 2)

console_policy.decide(roles, segments, method, has_step_up) -> allow/forbidden/
step_up_required/not_found. Role gate first, then step-up; identity is the
caller's concern. Pure; nothing consumes it yet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: Documentation + full local gate

**Files:**
- Modify: `CLAUDE.md` (test list)

**Interfaces:**
- Consumes: everything above.
- Produces: green full suite + build, and a documented test entry.

- [ ] **Step 1: Add the test to the documented list**

In `CLAUDE.md`, in the `## Commands` test block, add a line right after the existing
`tests/test_roles.py` entry (match the column alignment of the surrounding lines):
```
python3 tests/test_console.py        # /console authorization policy: capability matrix + decision (#216)
```

- [ ] **Step 2: Run the whole suite**

Run: `python3 tools/run-tests.py`
Expected: ends with `ALL TEST FILES PASS` (and the run includes `== test_console.py`).

- [ ] **Step 3: Lint the repo**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Build self-verify**

Run: `python3 tools/build.py`
Expected: exits 0. (`tools/build.py` writes into the gitignored `dist/` — do NOT `git add` anything it produces; `git status` before committing must show only `CLAUDE.md`.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'MSG'
docs: list test_console.py in the CLAUDE.md test index (#216 phase 2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
)"
```

---

## Self-Review

**Spec coverage (Phase 2 scope only):**
- Spec §C capability matrix → Task 1 `min_capability` + exhaustive route tests. ✓
- Spec §D step-up on irreversible producer ops → encoded as `Requirement.step_up=True` on `set/stint`, `mode/*`, `takeover/*`, `cockpit/versions`; enforced in Task 2 `decide`. ✓
- Spec "Testing → `tests/test_console.py` (auth + matrix + step-up)" → Tasks 1–2. ✓ (The full `_console_auth` *handler* — token extraction, RoleSource lookup, 401/403/429 emission, route mirroring — is **Phase 3**, deliberately out of scope here; Phase 2 ships only the pure policy it will call.)
- Deliberately out of Phase 2: `_console_auth`, `/console/*` routing + pages, the `X-Cockpit-Secret` read in the handler (Phase 3), Funnel mount (Phase 4). Keeping Phase 2 to a pure, inert, exhaustively-tested module is the "no behavior change" boundary.

**Placeholder scan:** none — every code/test step shows complete code and exact commands.

**Type consistency:** `Requirement(capability, step_up)` is consistent across `min_capability` (producer) and `decide`; capability strings `"commentator"/"director"/"producer"/"any"` match between constants, matrix, tests, and `decide`; outcome strings `ALLOW/FORBIDDEN/STEP_UP_REQUIRED/NOT_FOUND` are module constants used uniformly in `decide` and asserted via `cp.ALLOW` etc. in tests.

**Drift risk (called out in Global Constraints):** the matrix mirrors the relay's segment-list dispatch. Task 1's tests pin every matrix row; Phase 3 will additionally wire each real `/console` route through `decide`, and an e2e check (Phase 3/later) asserts live gating — so a future route addition that forgets the table is caught there, not silently mis-gated.
