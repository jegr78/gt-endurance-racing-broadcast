# M4 — Control Center Profile Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Control Center web app multi-league aware: a profile switcher + "new profile" copy dialog, a two-part settings editor (machine `.env` vs the active profile's `profile.env`), reorganized by scope — profile-scoped graphics/media assets move into a new **Profile** view, machine-shared cookies move into **General Settings**, and the old scope-mixed **Assets** view is removed.

**Architecture:** Backend stays the thin pattern it already uses — pure `*_data()` providers in `src/iro.py` returning JSON dicts, wired into the `ctx` map and routed by `src/ui/ui_server.py`. Profile switch/create are **synchronous** writes (like the existing `/api/env` write), calling `profile_admin` directly — not console jobs. The single `src/ui/control-center.html` page gets a new Profile view, a renamed General Settings view, an active-profile sidebar badge, and JS wiring; switching offers to restart running services (auto-restart) via the existing `relay-restart`/`companion-restart` ops.

**Tech Stack:** Pure Python 3.11+ stdlib (no framework). Vanilla JS in one HTML file (no build step). Tests are stdlib runnable scripts (`t_`-prefixed, bare `assert`, `python3 tests/test_X.py`). Playwright MCP available for a UI smoke check.

**Locked design decisions (with Jens, 2026-06-11):**
- **Views by scope:** new **Profile** view = switcher + new-profile dialog + `profile.env` editor + graphics/media assets + post-switch auto-restart offer. **General Settings** (renamed from "Settings") = machine `.env` editor + cookies (status + refresh). The **Assets** view is deleted; its parts move by scope (graphics/media → Profile, cookies → General Settings).
- **Switch behavior:** switching flips the active-profile pointer immediately (synchronous), then — if relay/companion are running — the UI offers to restart them so they pick up the new league (running children only inherit the profile env at spawn).
- **Profile create** seeds from an existing profile or the `example` template (`iro profile new <name> [--from <src>]`), does NOT auto-switch.
- Reuse the existing key/value row editor component for BOTH `.env` and `profile.env`.

**Backend API reference (already implemented, do not reimplement):**
- `src/scripts/profile_admin.py` (imported in iro.py as `pa`): `create_profile(root, name, source="example") -> target_dir` (raises `ValueError` on bad/duplicate name or missing source); `set_active_profile(root, runtime_root, name)` (raises `ValueError` on unknown name); `valid_profile_name(name) -> bool`; `mask_secret(value)`.
- `src/scripts/config.py` (imported as `pcfg`): `list_profiles(root)`, `read_active_pointer(runtime_root)`, `resolve_config(root, *, override, runtime_root) -> ResolvedConfig` (raises `pcfg.ProfileError`), `profiles_dir(root)`, `PROFILE_ENV_NAME` (`"profile.env"`), `ProfileError`.
- iro.py helpers: `_env_base(IS_FROZEN, _real_executable(), HERE) -> root`, `_runtime_base_dir()`, `_active_profile_name()` (tolerant effective-active resolver), `parse_env_text`, `_validate_env_entries`, `merge_env_text`, `_env_file()`.
- The Control Center `ctx` map is built in `src/iro.py` (search `make_handler` / the `ctx = {` dict, ~line 2410-2430) and passed to `ui_server.make_handler`. New providers are added as keys there and routed in `ui_server.py`.

---

### Task 1: Extract a shared `_write_env_file` helper (DRY for both editors)

**Files:**
- Modify: `src/iro.py` (`env_write_data` ~1852-1873; add `_write_env_file` just above it)
- Test: `tests/test_ui_ops.py` (where `env_write_data` is currently tested — confirm by grep; if its tests live in `tests/test_iro.py`, add there instead)

**Context:** `env_write_data` and the new `profile_env_write_data` (Task 4) do identical work (validate → merge-preserve comments → atomic write) on different paths. Factor the body into `_write_env_file(path, entries)` so both reuse it. The refactor must be behavior-preserving for `env_write_data` (its error text "could not write .env: …" still holds because `os.path.basename(_env_file())` is `.env`).

- [ ] **Step 1: Find the existing env_write tests**

Run: `grep -rln "env_write_data\|env_entries_data" tests/`
Note which file tests `env_write_data` (likely `tests/test_ui_ops.py`). Read those tests so the refactor keeps them green.

- [ ] **Step 2: Add `_write_env_file` and route `env_write_data` through it**

In `src/iro.py`, add directly above `env_write_data`:

```python
def _write_env_file(path, entries):
    """Validate `entries`, merge into the file at `path` (preserving comments),
    write atomically (tmp + os.replace). {ok, path} or {ok:false, error}. Never
    raises. Shared by the machine .env and profile.env editors."""
    try:
        pairs, err = _validate_env_entries(entries)
        if err:
            return {"ok": False, "error": err}
        original = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
        text = merge_env_text(original, pairs)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": f"could not write {os.path.basename(path)}: {exc}"}
```

Replace the body of `env_write_data` with a thin wrapper:

```python
def env_write_data(entries, path=None):
    """Validate the Settings editor's entries and persist them to .env,
    preserving comments. Atomic. Writes ONLY the server-resolved path (or the
    test-supplied `path`), never a client value. {ok,path} or {ok:false,error}."""
    return _write_env_file(path or _env_file(), entries)
```

- [ ] **Step 3: Run the env-write tests to verify still green**

Run: `python3 tests/test_ui_ops.py` (and `python3 tests/test_iro.py` if the tests live there).
Expected: ALL PASS — the refactor is behavior-preserving.

- [ ] **Step 4: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py
git commit -m "refactor(ui): extract _write_env_file shared by the env editors"
```

---

### Task 2: `profiles_data()` provider (the switcher's data)

**Files:**
- Modify: `src/iro.py` (add `profiles_data` near the other `*_data` providers, e.g. after `obs_collection_data`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_iro.py` (these tests build a temp root + profiles; mirror how `test_config.py`/existing iro tests create `profiles/<name>/profile.env`). Use the monkeypatch-`_env_base`/`_runtime_base_dir` seam pattern already used by `t_active_obs_collection_falls_back_to_constant_without_profile`:

```python
def t_profiles_data_lists_active_and_available():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # root with two profiles; iro/ has SHEET_ID, erf/ does not
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "iro"))
        os.makedirs(os.path.join(prof, "erf"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "iro", "profile.env"), "w") as fh:
            fh.write("NAME=IRO Endurance\nSHEET_ID=abc\n")
        with open(os.path.join(prof, "erf", "profile.env"), "w") as fh:
            fh.write("NAME=ERF\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True
        assert d["active"] == "iro"
        names = {p["name"]: p for p in d["profiles"]}
        assert names["iro"]["display"] == "IRO Endurance"
        assert names["iro"]["sheet_set"] is True
        assert names["erf"]["sheet_set"] is False
```

Ensure the runner executes it (auto-discovery in test_iro — confirm by running).

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_iro.py` → FAIL (`AttributeError: module 'iro' has no attribute 'profiles_data'`).

- [ ] **Step 3: Implement**

```python
def profiles_data():
    """Control Center profile switcher data: the effective active profile plus
    every available profile with its display NAME and whether SHEET_ID is set.
    {ok, active, profiles:[{name, display, sheet_set}]} or {ok:false, error}.
    Never raises."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        runtime_root = _runtime_base_dir()
        active = _active_profile_name()
        out = []
        for n in pcfg.list_profiles(root):
            try:
                rc = pcfg.resolve_config(root, override=n, runtime_root=runtime_root)
                out.append({"name": n, "display": rc.name,
                            "sheet_set": bool(rc.sheet_id)})
            except pcfg.ProfileError:
                out.append({"name": n, "display": n, "sheet_set": False})
        return {"ok": True, "active": active, "profiles": out}
    except Exception as exc:
        return {"ok": False, "error": f"could not read profiles: {exc}"}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_iro.py` → ALL PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_iro.py
git commit -m "feat(ui): profiles_data provider for the Control Center switcher"
```

---

### Task 3: `profile_use_data` + `profile_new_data` (synchronous switch/create)

**Files:**
- Modify: `src/iro.py` (add both near `profiles_data`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

```python
def t_profile_use_data_switches_pointer():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("SHEET_ID=abc\n")
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_use_data("iro")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d == {"ok": True, "active": "iro"}
        with open(os.path.join(td, "runtime", "active-profile")) as fh:
            assert fh.read().strip() == "iro"


def t_profile_use_data_unknown_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_use_data("nope")
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is False and d["error"]


def t_profile_new_data_creates_from_example():
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as td:
        # seed an example profile to copy from
        ex = os.path.join(td, "profiles", "example")
        os.makedirs(ex)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(ex, "profile.env"), "w") as fh:
            fh.write("NAME=Example\nSHEET_ID=\n")
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("gt3", "example")
        finally:
            m._env_base = orig_b
        assert d["ok"] is True and d["name"] == "gt3"
        assert os.path.isfile(os.path.join(td, "profiles", "gt3", "profile.env"))


def t_profile_new_data_bad_name_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "profiles", "example"))
        open(os.path.join(td, ".env.example"), "w").close()
        open(os.path.join(td, "profiles", "example", "profile.env"), "w").close()
        orig_b = m._env_base
        m._env_base = lambda *a, **k: td
        try:
            d = m.profile_new_data("../evil", "example")
        finally:
            m._env_base = orig_b
        assert d["ok"] is False and d["error"]
```

- [ ] **Step 2: Run to verify fail**

Run: `python3 tests/test_iro.py` → FAIL (missing `profile_use_data`/`profile_new_data`).

- [ ] **Step 3: Implement**

```python
def profile_use_data(name, set_active=None):
    """Switch the active profile (synchronous pointer write, like env_write_data).
    {ok, active} or {ok:false, error}. `set_active` is a test seam."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        runtime_root = _runtime_base_dir()
        (set_active or pa.set_active_profile)(root, runtime_root, name)
        return {"ok": True, "active": name}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"could not switch profile: {exc}"}


def profile_new_data(name, source="example", create=None):
    """Create a new profile by copying `source` (default the example template).
    Does NOT switch to it. {ok, name, path} or {ok:false, error}. `create` seam."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        target = (create or pa.create_profile)(root, name, source or "example")
        return {"ok": True, "name": name, "path": target}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"could not create profile: {exc}"}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_iro.py` → ALL PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_iro.py
git commit -m "feat(ui): synchronous profile_use_data / profile_new_data providers"
```

---

### Task 4: Active-profile `profile.env` editor providers

**Files:**
- Modify: `src/iro.py` (add `profile_env_entries_data` + `profile_env_write_data` near `env_entries_data`)
- Test: `tests/test_iro.py`

**Context:** Mirror `env_entries_data`/`env_write_data` but resolve the path to the ACTIVE profile's `profile.env`, and return a clear error when no profile is active. Reuse `_write_env_file` (Task 1) for the write.

- [ ] **Step 1: Write the failing tests**

```python
def t_profile_env_entries_data_reads_active():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# comment\nSHEET_ID=abc\nNAME=IRO\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_entries_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True and d["active"] == "iro"
        keys = [e["key"] for e in d["entries"]]
        assert "SHEET_ID" in keys and "NAME" in keys


def t_profile_env_entries_data_no_profile_is_error():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, ".env.example"), "w").close()
        os.makedirs(os.path.join(td, "runtime"))
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_entries_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is False and d["error"]


def t_profile_env_write_data_persists_to_active():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles", "iro")
        os.makedirs(prof)
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "profile.env"), "w") as fh:
            fh.write("# keep me\nSHEET_ID=old\n")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            d = m.profile_env_write_data([{"key": "SHEET_ID", "value": "new"},
                                          {"key": "OBS_COLLECTION", "value": "GT3"}])
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert d["ok"] is True
        text = open(os.path.join(prof, "profile.env")).read()
        assert "SHEET_ID=new" in text and "OBS_COLLECTION=GT3" in text
        assert "# keep me" in text          # comments preserved
```

- [ ] **Step 2: Run to verify fail**

Run: `python3 tests/test_iro.py` → FAIL (missing functions).

- [ ] **Step 3: Implement**

```python
def _active_profile_env_strict():
    """(active_name, profile.env path) for the active profile, or (None, None)
    when no profile resolves. Distinct from _active_profile_env_path(), which
    falls back to the machine .env — the Profile editor must never edit .env."""
    active = _active_profile_name()
    if not active:
        return None, None
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    return active, os.path.join(pcfg.profiles_dir(root), active, pcfg.PROFILE_ENV_NAME)


def profile_env_entries_data():
    """The active profile's profile.env as {key,value} entries for the Profile
    editor. {ok, path, active, entries} or {ok:false, error}. Never raises."""
    try:
        active, path = _active_profile_env_strict()
        if not active:
            return {"ok": False, "error": "no active profile — create or select one first"}
        text = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        entries = [{"key": k, "value": v} for k, v in parse_env_text(text).items()]
        return {"ok": True, "path": path, "active": active, "entries": entries}
    except Exception as exc:
        return {"ok": False, "error": f"could not read profile.env: {exc}"}


def profile_env_write_data(entries):
    """Persist the Profile editor entries to the active profile's profile.env
    (validate + comment-preserving merge, atomic). {ok,path} or {ok:false,error}.
    Server resolves the path from the active profile, never a client value."""
    active, path = _active_profile_env_strict()
    if not active:
        return {"ok": False, "error": "no active profile — create or select one first"}
    return _write_env_file(path, entries)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_iro.py` → ALL PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py tests/test_iro.py
git commit -m "feat(ui): active-profile profile.env editor providers"
```

---

### Task 5: Routes + ctx wiring in the UI server

**Files:**
- Modify: `src/ui/ui_server.py` (add GET + POST routes); `src/iro.py` (extend the `ctx` map)
- Test: `tests/test_ui_server.py`

**Context:** Read `src/ui/ui_server.py` `do_GET`/`do_POST` to see the exact dispatch idiom and how `/api/env` GET (`ctx["env_read"]`) and `/api/env` POST (`ctx["env_write"](body.get("entries"))`) are wired. Read `src/iro.py`'s `ctx = { … }` construction (search the keys `"env_read"`, `"env_write"`, `"obs_collection"`). Mirror exactly.

New endpoints:
| Method | Path | ctx key | call |
|---|---|---|---|
| GET | `/api/profiles` | `profiles` | `ctx["profiles"]()` |
| POST | `/api/profile/use` | `profile_use` | `ctx["profile_use"](body.get("name"))` |
| POST | `/api/profile/new` | `profile_new` | `ctx["profile_new"](body.get("name"), body.get("from"))` |
| GET | `/api/profile/env` | `profile_env_read` | `ctx["profile_env_read"]()` |
| POST | `/api/profile/env` | `profile_env_write` | `ctx["profile_env_write"](body.get("entries"))` |

- [ ] **Step 1: Write failing route tests**

Read `tests/test_ui_server.py` first to copy its handler-construction harness (it builds a handler with a fake `ctx` of lambdas and drives requests). Add tests that the five routes dispatch to the right ctx callables and return their JSON. Example shape (adapt to the file's actual harness):

```python
def t_profiles_route_returns_provider_json():
    ctx = _ctx(profiles=lambda: {"ok": True, "active": "iro", "profiles": []})
    status, body = _get(ctx, "/api/profiles")
    assert status == 200
    assert json.loads(body)["active"] == "iro"


def t_profile_use_route_passes_name():
    seen = {}
    def use(name): seen["name"] = name; return {"ok": True, "active": name}
    ctx = _ctx(profile_use=use)
    status, body = _post(ctx, "/api/profile/use", {"name": "erf"})
    assert status == 200 and seen["name"] == "erf"
    assert json.loads(body)["active"] == "erf"


def t_profile_new_route_passes_name_and_from():
    seen = {}
    def new(name, src): seen.update(name=name, src=src); return {"ok": True, "name": name}
    ctx = _ctx(profile_new=new)
    status, body = _post(ctx, "/api/profile/new", {"name": "gt3", "from": "iro"})
    assert status == 200 and seen == {"name": "gt3", "src": "iro"}


def t_profile_env_get_and_post():
    ctx = _ctx(profile_env_read=lambda: {"ok": True, "entries": []},
               profile_env_write=lambda entries: {"ok": True, "path": "p"})
    s1, _ = _get(ctx, "/api/profile/env"); assert s1 == 200
    s2, b2 = _post(ctx, "/api/profile/env", {"entries": [{"key": "SHEET_ID", "value": "x"}]})
    assert s2 == 200 and json.loads(b2)["ok"] is True
```

(`_ctx`, `_get`, `_post` are whatever the file already uses — reuse the existing helpers; do not invent new harness names if the file already names them differently.)

- [ ] **Step 2: Run to verify fail**

Run: `python3 tests/test_ui_server.py` → FAIL (routes 404 / KeyError).

- [ ] **Step 3: Implement the routes**

In `src/ui/ui_server.py` `do_GET`, alongside the other `/api/...` GET branches:

```python
        if path == "/api/profiles":
            return self._json(ctx["profiles"]())
        if path == "/api/profile/env":
            return self._json(ctx["profile_env_read"]())
```

In `do_POST`, alongside the `/api/env` POST branch:

```python
        if path == "/api/profile/use":
            return self._json(ctx["profile_use"]((self._body_json() or {}).get("name")))
        if path == "/api/profile/new":
            body = self._body_json() or {}
            return self._json(ctx["profile_new"](body.get("name"), body.get("from")))
        if path == "/api/profile/env":
            body = self._body_json() or {}
            return self._json(ctx["profile_env_write"](body.get("entries")))
```

(Match the real method names — if the file calls it `self._read_json()` not `self._body_json()`, use that; if GET branches `return` differently, mirror the surrounding ones exactly.)

In `src/iro.py`, extend the `ctx` dict with:

```python
        "profiles": profiles_data,
        "profile_use": profile_use_data,
        "profile_new": profile_new_data,
        "profile_env_read": profile_env_entries_data,
        "profile_env_write": profile_env_write_data,
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_ui_server.py && python3 tests/test_ui_ops.py` → ALL PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_server.py src/iro.py tests/test_ui_server.py
git commit -m "feat(ui): wire profile + profile.env API routes"
```

---

### Task 6: HTML — Profile view, General Settings, remove Assets, nav + sidebar badge

**Files:**
- Modify: `src/ui/control-center.html`

**Context:** Read these regions first: the nav (~351-373), the views `assets` (~514-549), `settings` (~593-610), the sidebar/brand (~345-385), and the JS for `showView` + lazy-load flags (~687-735), `loadSettings`/`saveSettings`/`settingsRow` (~1609-1692), the assets JS (`checkAssets`, gallery render, `fetchSetup`), and the cookies badge render (search `b-cookies`/`d-cookies`). This task is STRUCTURE + MOVES; Task 7 wires the new JS.

This is one file — make surgical edits, keep the page valid, and verify by loading it (Task 7 does the live smoke). Work in this order:

- [ ] **Step 1: Nav changes**

In the `.nav` block: REMOVE the `assets` navitem (line ~366). ADD a `profile` navitem near the top (after `home`, before `wizard` is fine), and RENAME the `settings` navitem label to "General Settings" (keep `data-nav="settings"` / `showView('settings')` unchanged to avoid churn). Add a `profile` button:

```html
      <button class="navitem" data-nav="profile" onclick="showView('profile')">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>Profile</button>
```

(Use an icon consistent with the others — single-color stroke SVG. The exact path is not critical.)

- [ ] **Step 2: Add the Profile view**

Insert a new `<div class="view" data-view="profile" hidden>` (put it near the top of the views, e.g. right after the `home` view block ends). It contains four sections — switcher, new-profile dialog, profile.env editor, and the graphics/media assets MOVED from the old Assets view. Use the existing classes (`viewhead`, `section`, `row`, `badge`, `dim`, `gallery`, `envhead`, `envrow`, `addrow`, `enverr`, `envpath`, `envhint`) so it inherits styling:

```html
      <!-- ===== Profile (active league: config + assets) ===== -->
      <div class="view" data-view="profile" hidden>
        <div class="viewhead"><h2>Profile</h2>
          <span class="sub" id="profile-active-sub">…</span>
          <span class="spacer"></span>
          <button onclick="loadProfiles(true)">
            <svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>Reload</button></div>

        <section>
          <div class="row"><span class="name">Active profile</span>
            <select id="profile-select" aria-label="Active league profile" onchange="useProfile(this.value)"></select>
            <span class="dim grow" id="profile-hint"></span></div>
          <div class="enverr" id="profile-switch-note" hidden></div>
        </section>

        <section>
          <div class="viewhead"><h3>New profile</h3></div>
          <div class="row"><span class="name">Name</span>
            <input id="newprofile-name" placeholder="e.g. erf" aria-label="New profile name">
            <span class="name">Copy from</span>
            <select id="newprofile-from" aria-label="Template to copy from"></select>
            <button onclick="newProfile()">
              <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Create</button></div>
          <div class="enverr" id="newprofile-err" hidden></div>
        </section>

        <section>
          <div class="viewhead"><h3>League config</h3>
            <span class="sub">profile.env</span><span class="spacer"></span>
            <button onclick="loadProfileEnv(true)">
              <svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>Reload</button>
            <button id="penv-save" onclick="saveProfileEnv()">
              <svg viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save</button></div>
          <div class="enverr" id="penv-err" hidden></div>
          <div class="envpath" id="penv-path"></div>
          <div class="envhead"><span class="k">Key</span><span class="v">Value</span></div>
          <div id="penvrows"></div>
          <div class="addrow"><button onclick="addProfileEnvRow()">
            <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Add entry</button></div>
          <p class="envhint">League config for the <b>active profile</b> — Sheet ID, push URL, intro/outro, logo, and the OBS scene-collection name (<b>OBS_COLLECTION</b>). Stored in <b>profiles/&lt;active&gt;/profile.env</b>. Values are masked; click the eye to reveal. Changes apply when you next (re)start the relay.</p>
        </section>

        <div class="viewhead"><h3>Assets</h3>
          <span class="sub">graphics + media for the active profile</span>
          <span class="spacer"></span>
          <button onclick="checkAssets()">
            <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>Check vs sheet</button></div>
        <section>
          <div class="row"><span class="name">Graphics</span>
            <span class="badge" id="b-graphics"><span class="dot"></span><span>…</span></span>
            <span class="dim grow" id="d-graphics"></span>
            <button onclick="op('graphics')">
              <svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>Download</button></div>
          <div class="gallery" id="gfx-gallery"></div>
        </section>
        <section>
          <div class="row"><span class="name">Media</span>
            <span class="badge" id="b-media"><span class="dot"></span><span>…</span></span>
            <span class="dim grow" id="d-media"></span>
            <button onclick="op('media')">
              <svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>Download</button></div>
          <div class="gallery" id="media-gallery"></div>
        </section>
      </div>
```

(If `h3` has no style, it inherits fine; the existing CSS uses `viewhead h2` — add a minimal `.viewhead h3{font-size:14px;…}` rule near the `viewhead h2` rule if needed for visual consistency, but do not over-style.)

- [ ] **Step 3: Move cookies into General Settings + relabel**

In the `settings` view (~593): change the `<h2>Settings</h2>` to `<h2>General Settings</h2>`. ADD a cookies section ABOVE the env editor section (move the cookies `<div class="row">` + `<select id="browser">` + Refresh button block VERBATIM from the old Assets view, wrapped in its own `<section>` with a small `<div class="viewhead"><h3>Cookies</h3><span class="sub">shared across all leagues</span></div>` above it). Update the closing env hint to clarify scope:

Replace the env hint text with:
```html
        <p class="envhint">Machine-level <b>.env</b> on this computer (ports, OBS-WebSocket password, Companion path) — shared across all leagues. League config (Sheet, OBS collection, …) lives under <b>Profile</b>. Values are masked; comments are preserved. Changes apply when you next (re)start the affected service.</p>
```

- [ ] **Step 4: Delete the old Assets view**

Remove the entire `<div class="view" data-view="assets" hidden> … </div>` block (~514-549) now that graphics/media moved to Profile and cookies moved to General Settings.

- [ ] **Step 5: Active-profile sidebar badge**

In the `.brand` / sidebar header area (~345-350), add a small element showing the active profile, e.g. directly under the brand title:

```html
      <div class="brandsub" id="active-profile-badge" title="Active league profile">—</div>
```

Add a minimal CSS rule near the brand styles: `.brandsub{font-size:11px;color:var(--dim);padding:0 14px 8px;cursor:pointer}` and make it open the Profile view: set `onclick="showView('profile')"` on the element.

- [ ] **Step 6: Fix cross-references to the removed Assets view**

Grep the file for `'assets'`, `"assets"`, `data-nav="assets"`, `assetsLoaded`, and any Home tile / link that targets the Assets view. Re-point any nav/link that pointed at `assets` to `profile` (graphics/media now live there). Leave the status-poll badges on Home as-is (they are read-only summaries, not links) unless one is an anchor to the assets view — then re-point it to `profile`.

- [ ] **Step 7: Quick structural sanity (no JS yet)**

Run a tag-balance/parse check:
```bash
python3 - <<'PY'
import html.parser, sys
class P(html.parser.HTMLParser):
    def error(self, m): print("PARSE ERROR:", m); sys.exit(1)
P().feed(open("src/ui/control-center.html", encoding="utf-8").read())
print("parsed OK")
PY
```
Also confirm exactly one `data-view="profile"`, no `data-view="assets"`, and the moved ids (`b-graphics`, `gfx-gallery`, `b-cookies`, `browser`) each appear exactly once:
```bash
grep -c 'data-view="assets"' src/ui/control-center.html   # expect 0
grep -c 'data-view="profile"' src/ui/control-center.html  # expect 1
for id in b-graphics gfx-gallery media-gallery b-cookies browser b-media; do echo -n "$id "; grep -c "id=\"$id\"" src/ui/control-center.html; done   # each expect 1
```

- [ ] **Step 8: Commit (structure only; JS wired next)**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): Profile view + General Settings; remove Assets view (structure)"
```

---

### Task 7: HTML — JS wiring (switcher, new dialog, profile.env editor, auto-restart) + live smoke

**Files:**
- Modify: `src/ui/control-center.html`

**Context:** Now wire the JS for the new ids. Reuse the existing patterns: the `$` helper, `fetch(..., {cache:'no-store'})`, the `settingsRow`/`collectSettings`/`saveSettings` machine-env editor as the template for the profile.env editor, the `op(name, confirm, params)` trigger, and the `showView` lazy-load + the `/api/status` poll. Read those functions before editing.

- [ ] **Step 1: Profile editor — clone the env-editor functions**

Add JS mirroring `loadSettings`/`addSettingsRow`/`collectSettings`/`saveSettings`/`settingsRow`, but against `/api/profile/env`, the `penvrows`/`penv-*` ids, and POST `/api/profile/env`. Concretely add:
- `loadProfileEnv(force)` → GET `/api/profile/env`; if `!d.ok` show `d.error` in `#penv-err` and clear rows; else render rows into `#penvrows` (reuse the same row builder — factor the existing `settingsRow(key,value)` to accept a container, or add a parallel `profileEnvRow`), set `#penv-path`.
- `addProfileEnvRow()` → append an empty row to `#penvrows`.
- `saveProfileEnv()` → confirm, POST collected `#penvrows` entries to `/api/profile/env`, show "Saved ✓" on `#penv-save`, reload to re-mask.

DRY option (preferred): generalize the existing `settingsRow`/`collectX` to take an id prefix + container so both editors share one builder. If that's too invasive, a parallel set is acceptable — keep it small.

- [ ] **Step 2: Switcher + new-profile dialog**

Add:
- `loadProfiles(force)` → GET `/api/profiles`; populate `#profile-select` (options = each `p.name`, label `p.display` + a "— no sheet" suffix when `!p.sheet_set`), select `d.active`; populate `#newprofile-from` with each profile name plus an `example` option; set `#profile-active-sub` and the sidebar `#active-profile-badge` to `d.active` (or "no profile"). Also call `loadProfileEnv()` after, so the editor reflects the active profile.
- `useProfile(name)` → if `name===currentActive` return; POST `/api/profile/use` `{name}`; on `!ok` show `#profile-switch-note` with the error and revert the select; on ok: refresh `loadProfiles()` + `loadProfileEnv()` + the status poll, then call `offerRestart()` (Step 3).
- `newProfile()` → read `#newprofile-name` + `#newprofile-from`; POST `/api/profile/new` `{name, from}`; on `!ok` show `#newprofile-err`; on ok clear the name field, `loadProfiles()`, and show a hint "created — select it above to activate".

- [ ] **Step 3: Auto-restart offer after switch**

Add `offerRestart()`: read the last `/api/status` (`lastStatus`) to see if relay and/or companion are running. If neither runs, do nothing. If one/both run, show a non-blocking note in `#profile-switch-note` like: "Relay/Companion still serving the previous league. Restart to apply." with a "Restart now" button that triggers the existing ops (`op('relay-restart')` and/or `op('companion-restart')`) for whichever is running, then hides the note. Keep it best-effort and explicit (the user clicks Restart; nothing auto-runs without the click — the "auto" is the offered one-click, not an unattended restart). Use a `confirm()`-gated button via the existing `op(name, true)` form.

- [ ] **Step 4: Lazy-load + view registration**

In `showView`, register the `profile` view's first-open loader (call `loadProfiles()` once, like `settingsLoaded`/`setupLoaded`). Ensure the OLD `assets` lazy-load branch is removed/renamed: the graphics/media (`checkAssets`, galleries) and cookies status now render under `profile`/`settings` respectively. Move the cookies badge update (the code that sets `#b-cookies`/`#d-cookies` from `/api/status`) so it still runs — it likely already runs from the status poll regardless of view; just confirm the ids still exist (they moved to General Settings, same ids) so the poll keeps updating them. Make the General Settings view's first-open also ensure cookies/browser render (the status poll already feeds `#b-cookies`).

- [ ] **Step 5: Sidebar badge from the status poll**

In the `/api/status` render path, also refresh `#active-profile-badge` if the status payload carries the active profile; if it does NOT, fetch `/api/profiles` once on load to set it. (Simplest: set the badge in `loadProfiles()`, and call `loadProfiles()` once at startup so the badge is populated regardless of which view opens first.)

- [ ] **Step 6: Structural + unit gate**

```bash
python3 - <<'PY'
import html.parser
html.parser.HTMLParser().feed(open("src/ui/control-center.html", encoding="utf-8").read())
print("parsed OK")
PY
python3 tools/run-tests.py
python3 tools/lint.py
```
All green (the HTML isn't unit-tested, but the server/provider tests must stay green and lint clean).

- [ ] **Step 7: Live UI smoke (Playwright MCP)**

Start the Control Center on a test port and drive it:
```bash
IRO_UI_PORT=8099 python3 src/iro.py ui --no-browser &
sleep 2
```
Using the Playwright MCP tools, navigate to `http://127.0.0.1:8099/`, then:
- Take a snapshot; confirm the sidebar shows a **Profile** nav item and **General Settings**, and NO **Assets** item.
- Click **Profile**; confirm the switcher `#profile-select`, the New-profile row, the League-config (`profile.env`) editor, and the Graphics/Media sections render.
- Confirm the active-profile **sidebar badge** shows a value.
- Click **General Settings**; confirm the **Cookies** section and the machine `.env` editor render.
- Capture a screenshot for the record.
Then stop the server:
```bash
IRO_UI_PORT=8099 python3 src/iro.py ui --quit 2>/dev/null || pkill -f "iro.py ui" || true
```
(If `--quit` isn't a flag, kill the backgrounded PID. Verify no stray process remains.)

Note any rendering error in the report. If a profile exists locally, optionally exercise a switch and confirm the restart-offer note logic (only when a service is running — do not start services just to test this; a code-read confirmation is acceptable if no service is running).

- [ ] **Step 8: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): wire profile switcher, profile.env editor, and auto-restart offer"
```

---

### Task 8: Milestone gate + cross-cutting review prep

**Files:** none (verification only)

- [ ] **Step 1: Full suite + lint + build**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # clean
python3 tools/build.py         # verify passes (graphics/media warnings expected)
```

- [ ] **Step 2: Confirm the build ships the new UI**

The build verify already checks "ui page shipped" / "ui server shipped". Confirm those `[OK]` lines are present in the build output and the page in `dist/` contains `data-view="profile"` and no `data-view="assets"`:
```bash
grep -c 'data-view="profile"' dist/IRO_Broadcast_Package/ui/control-center.html   # expect 1
grep -c 'data-view="assets"' dist/IRO_Broadcast_Package/ui/control-center.html    # expect 0
```
(Adjust the dist path to wherever build.py places the UI — confirm from the build log.)

- [ ] **Step 3: Commit any gate fix (only if needed)**

```bash
git add -A && git commit -m "test(m4): milestone gate green"
```

---

## Self-Review

**Spec coverage** (against the locked M4 decisions):
- Profile switcher → Task 2 (`profiles_data`) + Task 5 (route) + Task 6/7 (`#profile-select`, `loadProfiles`/`useProfile`).
- New-profile copy dialog → Task 3 (`profile_new_data`) + Task 6/7 (`newProfile`, `--from` select).
- Two-part settings editor → Task 1 (shared `_write_env_file`) + Task 4 (profile.env providers) + Task 6/7 (Profile `profile.env` editor + General Settings machine `.env`).
- Reorg by scope: graphics/media → Profile, cookies → General Settings, Assets view removed → Task 6.
- Auto-restart after switch → Task 7 Step 3.
- Sidebar active badge → Task 6 Step 5 + Task 7 Step 5.
- Stale hint text fixed → Task 6 Step 3.

**Placeholder scan:** Backend tasks carry full code. HTML tasks carry full new markup + precise move/delete/grep instructions; JS is specified function-by-function with the existing functions named as the template (the implementer must read them — unavoidable for a 1900-line single-file page, but every new function's contract and ids are pinned).

**Type/name consistency:** ctx keys (`profiles`, `profile_use`, `profile_new`, `profile_env_read`, `profile_env_write`) match between Task 5's route table and the `ctx` dict additions. Provider names (`profiles_data`, `profile_use_data`, `profile_new_data`, `profile_env_entries_data`, `profile_env_write_data`) are consistent across tasks. HTML ids (`profile-select`, `newprofile-name`/`-from`/`-err`, `penvrows`/`penv-save`/`penv-err`/`penv-path`, `b-graphics`/`gfx-gallery`/`media-gallery`/`b-media`, `b-cookies`/`browser`, `active-profile-badge`) are used identically in Tasks 6 and 7. `profile_use_data` returns `{ok, active}`; `useProfile` reads `.active`. `profiles_data` returns `{active, profiles:[{name,display,sheet_set}]}`; `loadProfiles` consumes those exact keys.

**Risk notes:** The moved cookies badge ids (`b-cookies`/`d-cookies`) must keep the SAME ids so the existing `/api/status` poll render keeps updating them after the move (Task 7 Step 4 calls this out). The graphics/media ids (`b-graphics`/`gfx-gallery`/etc.) likewise keep their names so `checkAssets`/gallery JS needs no rename — only its host view changed. `_active_profile_env_strict` is deliberately distinct from the existing `_active_profile_env_path()` (which falls back to `.env`) so the Profile editor can never write the machine `.env`.
