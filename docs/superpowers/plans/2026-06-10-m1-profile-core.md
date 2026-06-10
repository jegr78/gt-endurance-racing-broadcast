# M1 — Profile Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully unit-tested, profile-aware configuration resolver (`src/scripts/config.py`) plus non-breaking config scaffolding, so later milestones can make the toolkit serve multiple leagues.

**Architecture:** One new pure-stdlib module becomes the single source of truth for resolving the active *profile* (league) and loading its config from two layers — a machine-level `.env` (`RACECAST_*`, all leagues) and `profiles/<name>/profile.env` (the league: SHEET_ID, push URL, display name, overrides). The module is pure and table-tested with temp dirs; no runtime consumer is rewired in M1 (that is M2/M3), so the existing toolkit keeps working byte-for-byte.

**Tech Stack:** Python 3.11+ stdlib only (`os`, `dataclasses`, `tempfile` for tests). No third-party deps. Tests follow the repo's no-pytest idiom (`t_`-prefixed functions, bare `assert`, `importlib` module load, runnable as a script).

---

## Design Decision (resolved during planning)

The spec's M1 line "switch the four `load_dotenv` copies to the module" is implemented as **"the canonical loader lives in `config.py`; the four standalone scripts keep their self-contained synced copies"** — NOT as forced imports. Reason verified in the codebase: `src/relay/iro-feeds.py` is deliberately import-free (it also carries a synced copy of `detect_tailscale_ip`, which CLAUDE.md explicitly mandates keeping in sync), and all four scripts run in-process under the frozen binary. Forcing them to import a shared module would break that established, intentional pattern. M1 therefore introduces the canonical module and leaves the four scripts untouched; M3/M5 wire consumers to it where safe.

Consequently M1 is **purely additive and non-breaking**: it adds a new module + tests + scaffolding files, and keeps the existing `IRO_*` machine vars in `.env.example` intact (the full `.env.example` rebrand happens in M5, once consumers read from the new module).

## File Structure

- **Create:** `src/scripts/config.py` — the profile resolver (one responsibility: resolve active profile + load its config). New module, imported later by `src/racecast.py` (M2) and the Control Center (M4).
- **Create:** `tests/test_config.py` — full unit coverage (auto-discovered by `tools/run-tests.py` via glob).
- **Create:** `profiles/example/profile.env` — the shipped league template.
- **Modify:** `.gitignore` — ignore real `profiles/<league>/`, keep `profiles/example/`.
- **Modify:** `.env.example` — add one optional `RACECAST_PROFILE` line (additive, non-breaking).

`tools/run-tests.py` needs **no** edit: it globs `tests/test_*.py`.

---

### Task 1: `config.py` scaffold — project-root walk + env parser

**Files:**
- Create: `src/scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the profile-aware config resolver.
Run: python3 tests/test_config.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "racecast_config", os.path.join(ROOT, "src", "scripts", "config.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _mkroot(td):
    """A fake project root: a dir holding a .env.example marker."""
    root = os.path.join(td, "proj")
    os.makedirs(root)
    open(os.path.join(root, ".env.example"), "w").close()
    return root


def t_find_project_root_finds_marker_above_start():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        start = os.path.join(root, "src", "scripts")
        os.makedirs(start)
        assert m.find_project_root(start) == root


def t_find_project_root_returns_none_when_no_marker_within_bound():
    with tempfile.TemporaryDirectory() as td:
        deep = os.path.join(td, "a", "b", "c", "d", "e")
        os.makedirs(deep)
        # no marker anywhere -> None (bounded walk, never an unrelated parent)
        assert m.find_project_root(deep, max_levels=4) is None


def t_parse_env_text_ignores_blanks_comments_and_strips_quotes():
    text = '\n'.join([
        "# a comment",
        "",
        "SHEET_ID=abc123",
        '  NAME = "IRO Endurance" ',
        "URL='https://x/y?key=z'",   # '=' inside the value is kept
        "noequals",
    ])
    got = m.parse_env_text(text)
    assert got == {
        "SHEET_ID": "abc123",
        "NAME": "IRO Endurance",
        "URL": "https://x/y?key=z",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFound` because `src/scripts/config.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/config.py`:

```python
#!/usr/bin/env python3
"""Profile-aware configuration resolver for the GT Endurance Racing Broadcast
toolkit (binary: racecast).

Single source of truth for resolving which league ("profile") is active and
loading its config. Two layers:

  * machine .env  (repo root / next to the binary) — RACECAST_* vars, all leagues
  * profiles/<name>/profile.env — the league: SHEET_ID, SHEET_PUSH_URL, NAME, ...

The bounded .env loader here is the CANONICAL copy. The standalone scripts
(relay/iro-feeds.py, setup-assets.py, relay/get-media.py, relay/get-graphics.py)
keep their own self-contained load_dotenv on purpose — the relay is deliberately
import-free (same rationale as its duplicated detect_tailscale_ip) and all four
run in-process under the frozen binary. Keep the parsing/boundary rules in sync.
"""

import os

PROJECT_MARKERS = (".git", ".env.example")


def find_project_root(start, markers=PROJECT_MARKERS, max_levels=4):
    """Walk up from `start` (at most `max_levels`) to the nearest ancestor that
    holds a marker. Returns that directory, or None. Bounded on purpose: never
    reaches an unrelated parent (same security boundary as the scripts)."""
    d = start
    for _ in range(max_levels):
        if any(os.path.exists(os.path.join(d, mk)) for mk in markers):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def parse_env_text(text):
    """Parse KEY=VALUE lines into a dict. Ignores blank lines, '#' comments and
    lines without '='; strips surrounding whitespace and a single layer of
    matching quotes. '=' inside a value is preserved. Pure."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_config.py`
Expected: prints `ok t_find_project_root_finds_marker_above_start`, `ok t_find_project_root_returns_none_when_no_marker_within_bound`, `ok t_parse_env_text_ignores_blanks_comments_and_strips_quotes`, then `ALL PASS`.

> The runner block is added in Task 6 (last task touching this file). Until then, run individual checks if needed via:
> `python3 -c "import sys; sys.path.insert(0,'tests'); import test_config as t; t.t_parse_env_text_ignores_blanks_comments_and_strips_quotes()"`
> To keep each task self-verifying, add the runner block now at the END of `tests/test_config.py`:

```python
if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

Re-run `python3 tests/test_config.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): project-root walk + env parser for profile resolver"
```

---

### Task 2: machine `.env` loader

**Files:**
- Modify: `src/scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (before the `if __name__` block):

```python
def t_load_machine_env_reads_dotenv_at_root():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        with open(os.path.join(root, ".env"), "w", encoding="utf-8") as fh:
            fh.write("RACECAST_PROFILE=iro\nRACECAST_UI_PORT=8089\n")
        got = m.load_machine_env(root)
        assert got == {"RACECAST_PROFILE": "iro", "RACECAST_UI_PORT": "8089"}


def t_load_machine_env_returns_empty_when_no_dotenv():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)   # marker present, but no .env file
        assert m.load_machine_env(root) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'load_machine_env'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/config.py`:

```python
def load_machine_env(start):
    """Read the machine .env (from `start` or the project root above it) into a
    dict. Does NOT mutate os.environ — callers decide precedence. Bounded to the
    project (same boundary as find_project_root). Returns {} if no .env."""
    candidates = [start]
    root = find_project_root(start)
    if root and root != start:
        candidates.append(root)
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return parse_env_text(fh.read())
    return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_config.py`
Expected: `ALL PASS` (now includes the two new `ok` lines).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): bounded machine .env loader"
```

---

### Task 3: profile discovery + profile.env parsing

**Files:**
- Modify: `src/scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def _mkprofile(root, name, body):
    pdir = os.path.join(root, "profiles", name)
    os.makedirs(pdir)
    with open(os.path.join(pdir, "profile.env"), "w", encoding="utf-8") as fh:
        fh.write(body)
    return pdir


def t_list_profiles_sorted_excludes_example_and_dirs_without_profile_env():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "SHEET_ID=a\n")
        _mkprofile(root, "erf", "SHEET_ID=b\n")
        _mkprofile(root, "example", "SHEET_ID=\n")           # template, excluded
        os.makedirs(os.path.join(root, "profiles", "empty"))  # no profile.env
        assert m.list_profiles(root) == ["erf", "iro"]


def t_list_profiles_empty_when_no_profiles_dir():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        assert m.list_profiles(root) == []


def t_parse_profile_reads_named_profile():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "NAME=IRO Endurance\nSHEET_ID=abc\n")
        assert m.parse_profile(root, "iro") == {
            "NAME": "IRO Endurance", "SHEET_ID": "abc"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `AttributeError: ... has no attribute 'list_profiles'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/config.py`:

```python
PROFILE_ENV_NAME = "profile.env"


def profiles_dir(root):
    return os.path.join(root, "profiles")


def list_profiles(root):
    """Sorted names of profiles/<name>/ dirs that contain a profile.env.
    'example' (the shipped template) is excluded — it is not a usable league."""
    pdir = profiles_dir(root)
    if not os.path.isdir(pdir):
        return []
    names = []
    for name in sorted(os.listdir(pdir)):
        if name == "example":
            continue
        if os.path.isfile(os.path.join(pdir, name, PROFILE_ENV_NAME)):
            names.append(name)
    return names


def parse_profile(root, name):
    """Read profiles/<name>/profile.env into a dict. Raises FileNotFoundError if
    the profile.env is missing."""
    p = os.path.join(profiles_dir(root), name, PROFILE_ENV_NAME)
    with open(p, encoding="utf-8") as fh:
        return parse_env_text(fh.read())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_config.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): profile discovery + profile.env parsing"
```

---

### Task 4: active-profile resolution (precedence + errors)

**Files:**
- Modify: `src/scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def t_read_active_pointer_reads_and_strips():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "active-profile"), "w", encoding="utf-8") as fh:
            fh.write("erf\n")
        assert m.read_active_pointer(td) == "erf"
        os.remove(os.path.join(td, "active-profile"))
        assert m.read_active_pointer(td) is None


def t_resolve_active_profile_precedence_override_beats_env_and_pointer():
    avail = ["erf", "iro"]
    assert m.resolve_active_profile(
        avail, override="iro", env_value="erf", pointer="erf") == "iro"


def t_resolve_active_profile_env_beats_pointer():
    assert m.resolve_active_profile(
        ["erf", "iro"], env_value="erf", pointer="iro") == "erf"


def t_resolve_active_profile_pointer_used_when_no_override_or_env():
    assert m.resolve_active_profile(["erf", "iro"], pointer="iro") == "iro"


def t_resolve_active_profile_single_profile_is_implicit():
    assert m.resolve_active_profile(["iro"]) == "iro"


def t_resolve_active_profile_unknown_name_raises():
    try:
        m.resolve_active_profile(["iro"], override="ghost")
        assert False, "expected ProfileError"
    except m.ProfileError as e:
        assert "ghost" in str(e) and "iro" in str(e)


def t_resolve_active_profile_ambiguous_raises():
    try:
        m.resolve_active_profile(["erf", "iro"])
        assert False, "expected ProfileError"
    except m.ProfileError as e:
        assert "--profile" in str(e)


def t_resolve_active_profile_none_raises():
    try:
        m.resolve_active_profile([])
        assert False, "expected ProfileError"
    except m.ProfileError as e:
        assert "no profiles" in str(e)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `AttributeError: ... has no attribute 'read_active_pointer'` (and `ProfileError`).

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/config.py`:

```python
ACTIVE_PROFILE_FILE = "active-profile"   # lives under runtime/


def read_active_pointer(runtime_root):
    """Return the persisted active-profile name from runtime/active-profile, or
    None if the pointer file is absent/empty."""
    p = os.path.join(runtime_root, ACTIVE_PROFILE_FILE)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            return fh.read().strip() or None
    return None


class ProfileError(Exception):
    """The active profile could not be resolved (none / ambiguous / unknown)."""


def resolve_active_profile(available, *, override=None, env_value=None,
                           pointer=None):
    """Resolve the active profile by precedence:
        override (--profile) > env_value (RACECAST_PROFILE) > pointer
        (runtime/active-profile) > the sole profile when exactly one exists.
    `available` is the list of known profile names. Raises ProfileError with a
    helpful message on an unknown name, ambiguity, or no profiles at all."""
    for source, value in (("--profile", override),
                          ("RACECAST_PROFILE", env_value),
                          ("active-profile", pointer)):
        if value:
            if value not in available:
                raise ProfileError(
                    f"{source}={value!r} is not a known profile "
                    f"(available: {', '.join(available) or 'none'})")
            return value
    if len(available) == 1:
        return available[0]
    if not available:
        raise ProfileError(
            "no profiles found — create one under profiles/<name>/profile.env")
    raise ProfileError(
        "multiple profiles exist; choose one with --profile or "
        f"'racecast profile use <name>' (available: {', '.join(available)})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_config.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): active-profile resolution with precedence + errors"
```

---

### Task 5: `ResolvedConfig` + top-level `resolve_config`

**Files:**
- Modify: `src/scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def t_profile_runtime_dir_is_runtime_slash_name():
    assert m.profile_runtime_dir("/p", "erf") == os.path.join("/p", "runtime", "erf")


def t_resolve_config_end_to_end_single_profile():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro",
                   "NAME=IRO Endurance\nSHEET_ID=abc\nSHEET_PUSH_URL=https://x?key=y\n")
        cfg = m.resolve_config(root, environ={})
        assert cfg.profile == "iro"
        assert cfg.name == "IRO Endurance"
        assert cfg.sheet_id == "abc"
        assert cfg.sheet_push_url == "https://x?key=y"
        assert cfg.intro_url == "" and cfg.outro_url == ""
        assert cfg.logo_path == ""              # no LOGO set
        assert cfg.profile_dir == os.path.join(root, "profiles", "iro")
        assert cfg.runtime_dir == os.path.join(root, "runtime", "iro")


def t_resolve_config_name_defaults_to_profile_when_unset():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "erf", "SHEET_ID=zzz\n")
        cfg = m.resolve_config(root, environ={})
        assert cfg.name == "erf"


def t_resolve_config_override_selects_among_many():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "SHEET_ID=a\n")
        _mkprofile(root, "erf", "SHEET_ID=b\n")
        cfg = m.resolve_config(root, override="erf", environ={})
        assert cfg.profile == "erf" and cfg.sheet_id == "b"


def t_resolve_config_env_var_selects_among_many():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "SHEET_ID=a\n")
        _mkprofile(root, "erf", "SHEET_ID=b\n")
        cfg = m.resolve_config(root, environ={"RACECAST_PROFILE": "iro"})
        assert cfg.profile == "iro"


def t_resolve_config_logo_path_resolved_when_file_present():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        pdir = _mkprofile(root, "iro", "SHEET_ID=a\nLOGO=logo.png\n")
        open(os.path.join(pdir, "logo.png"), "w").close()
        cfg = m.resolve_config(root, environ={})
        assert cfg.logo_path == os.path.join(pdir, "logo.png")


def t_resolve_config_logo_path_blank_when_file_missing():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(td)
        _mkprofile(root, "iro", "SHEET_ID=a\nLOGO=missing.png\n")
        cfg = m.resolve_config(root, environ={})
        assert cfg.logo_path == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `AttributeError: ... has no attribute 'profile_runtime_dir'` (and `resolve_config` / `ResolvedConfig`).

- [ ] **Step 3: Write minimal implementation**

Add to the imports at the TOP of `src/scripts/config.py` (replace the lone `import os` line):

```python
import os
from dataclasses import dataclass, field
```

Then add at the END of `src/scripts/config.py`:

```python
@dataclass
class ResolvedConfig:
    profile: str
    name: str
    sheet_id: str
    sheet_push_url: str = ""
    intro_url: str = ""
    outro_url: str = ""
    logo_path: str = ""          # absolute path, or "" if unset/missing
    profile_dir: str = ""
    runtime_dir: str = ""
    machine_env: dict = field(default_factory=dict)


def profile_runtime_dir(root, name):
    """Profile-scoped runtime dir: <root>/runtime/<name>."""
    return os.path.join(root, "runtime", name)


def resolve_config(root, *, override=None, runtime_root=None, environ=None):
    """Machine .env + active profile -> ResolvedConfig. `root` is the project
    root; `runtime_root` defaults to <root>/runtime; `environ` defaults to
    os.environ (a real RACECAST_PROFILE wins over the machine .env's). Raises
    ProfileError if no profile can be resolved."""
    environ = os.environ if environ is None else environ
    runtime_root = runtime_root or os.path.join(root, "runtime")
    machine = load_machine_env(root)
    available = list_profiles(root)
    name = resolve_active_profile(
        available,
        override=override,
        env_value=environ.get("RACECAST_PROFILE") or machine.get("RACECAST_PROFILE"),
        pointer=read_active_pointer(runtime_root),
    )
    prof = parse_profile(root, name)
    pdir = os.path.join(profiles_dir(root), name)
    logo = prof.get("LOGO", "")
    logo_path = os.path.join(pdir, logo) if logo else ""
    if logo_path and not os.path.isfile(logo_path):
        logo_path = ""
    return ResolvedConfig(
        profile=name,
        name=prof.get("NAME", name),
        sheet_id=prof.get("SHEET_ID", ""),
        sheet_push_url=prof.get("SHEET_PUSH_URL", ""),
        intro_url=prof.get("INTRO_URL", ""),
        outro_url=prof.get("OUTRO_URL", ""),
        logo_path=logo_path,
        profile_dir=pdir,
        runtime_dir=profile_runtime_dir(root, name),
        machine_env=machine,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_config.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(config): ResolvedConfig + top-level resolve_config"
```

---

### Task 6: scaffolding files (template, gitignore, env example) + full gate

**Files:**
- Create: `profiles/example/profile.env`
- Modify: `.gitignore`
- Modify: `.env.example`

This task ships the league template, makes real profiles machine-local, and announces the new `RACECAST_PROFILE` selector — all non-breaking (the existing `IRO_*` machine vars stay; their full rename is M5).

- [ ] **Step 1: Create the league template**

Create `profiles/example/profile.env`:

```
# Profile (league) config — copy this whole directory to profiles/<your-league>/
#   and fill in the values, OR use:  racecast profile new <name> --from example
# Real environment variables and the machine .env do NOT override these league
# values; this file IS the league.

# Display name shown in the CLI / Control Center / docs (not the HUD).
NAME=Example League

# Google Sheet that drives the HUD + relay stint schedule (the long ID from the
# sheet URL: https://docs.google.com/spreadsheets/d/<THIS_PART>/edit).
SHEET_ID=

# OPTIONAL: sheet-write webhook (Google Apps Script /exec URL INCLUDING its
# ?key=... secret). Enables Director write-back (timer + panel controls).
SHEET_PUSH_URL=

# OPTIONAL: override the Intro/Outro clip URLs (normally taken from the sheet's
# Assets tab cells "Intro Video" / "Outro Video").
INTRO_URL=
OUTRO_URL=

# OPTIONAL: a logo image (relative to this profile dir) for the Control Center.
LOGO=
```

- [ ] **Step 2: Make real profiles machine-local, keep the template**

Edit `.gitignore` — add these lines after the existing `runtime/` / `dist/` block (anywhere in the file is fine, but keep them together):

```
# league profiles are machine-local; only the example template ships
profiles/*
!profiles/example/
```

- [ ] **Step 3: Announce the profile selector in the machine env example**

Edit `.env.example`: add the following block at the END of the file (additive — do NOT remove the existing `IRO_*` lines yet; they are renamed in M5):

```
# Default active profile (league) when neither --profile nor an explicit
# RACECAST_PROFILE env var is given. Each league lives in profiles/<name>/.
# Leave unset if you keep exactly one profile (it is then selected implicitly).
RACECAST_PROFILE=
```

- [ ] **Step 4: Verify the template is parseable and git-tracked correctly**

Run:
```bash
python3 -c "import importlib.util,os; s=importlib.util.spec_from_file_location('c','src/scripts/config.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.parse_profile('.', 'example'))"
git add -A && git status --short
```
Expected: the `parse_profile` call prints the dict with `NAME='Example League'` and empty `SHEET_ID`. `git status` shows `profiles/example/profile.env` staged; a scratch `profiles/iro/` (if you create one to test) is **NOT** listed (ignored).

> Verify the ignore rule: `mkdir -p profiles/iro && touch profiles/iro/profile.env && git status --short` must NOT list `profiles/iro/`. Then `rm -rf profiles/iro`.

- [ ] **Step 5: Run the full project gate**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected:
- `run-tests.py` → ends with `ALL TEST FILES PASS` (and the `== test_config.py` line shows `ALL PASS`).
- `lint.py` → no errors.
- `build.py` → completes its verify step with no secret/shell-script/tokenization failures (config.py ships under `src/scripts/`; `profiles/` is at repo root and is not part of the package — that is expected for M1; packaging the template ships in M2/M5).

- [ ] **Step 6: Commit**

```bash
git add profiles/example/profile.env .gitignore .env.example
git commit -m "feat(config): ship example profile template + RACECAST_PROFILE selector"
```

---

## Self-Review

**Spec coverage (M1 lines):**
- "config.py resolver, machine .env + profile.env, resolution order, ResolvedConfig, profile-scoped runtime/<name>/" → Tasks 1–5. ✅
- "New tests/test_config.py" → Tasks 1–5 (auto-run by run-tests.py via glob). ✅
- "Switch the four load_dotenv copies to the module" → reinterpreted as "canonical loader in config.py; scripts keep synced copies" (Design Decision above); the four scripts are intentionally NOT imported/edited in M1. Documented in config.py docstring. ✅ (consumer wiring is M3/M5)
- "The RACECAST_* names + profiles/ are born here" → Task 6 (`RACECAST_PROFILE`, `profiles/example/`). ✅

**Deferred to later milestones (intentionally NOT in M1):** `racecast profile` subcommands + global `--profile` flag wiring into `src/iro.py` (M2); rewiring relay/get-graphics/get-media/setup-assets to profile-scoped runtime + env rename (M3); full `.env.example` IRO_*→RACECAST_* rename (M5).

**Placeholder scan:** none — every step has full code/commands/expected output.

**Type/name consistency:** `find_project_root`, `parse_env_text`, `load_machine_env`, `profiles_dir`, `list_profiles`, `parse_profile`, `read_active_pointer`, `ProfileError`, `resolve_active_profile`, `ResolvedConfig`, `profile_runtime_dir`, `resolve_config` — names used identically in tests and implementation across Tasks 1–6. `profile.env`, `active-profile`, `profiles/example/` constants match between code and scaffolding.

---

## CI Gate (must stay green at the end of M1)

- `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- `python3 tools/lint.py` → clean
- `python3 tools/build.py` → verify passes
- No existing behavior changed (the four scripts + `.env` `IRO_*` vars untouched).
