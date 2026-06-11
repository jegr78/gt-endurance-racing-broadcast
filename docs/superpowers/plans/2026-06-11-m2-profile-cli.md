# M2 — Profile CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `profile` command group (`list` / `show` / `use` / `new --from`) and a global `--profile` flag to the CLI, so operators can manage leagues from the terminal on top of the M1 resolver.

**Architecture:** A new pure-stdlib module `src/scripts/profile_admin.py` owns the WRITE side (create a profile dir, set the active pointer) plus CLI arg-parsing and output formatting, sitting on top of M1's read-only `src/scripts/config.py`. `src/iro.py` thin-wraps it: `route()` recognizes `profile`, `main()` strips a global `--profile` (exporting it as `RACECAST_PROFILE` so M3 consumers pick it up), and `profile_cmd()` dispatches verbs. No runtime consumer (relay/setup/graphics) and no `IRO_*` var is touched — that is M3/M5.

**Tech Stack:** Python 3.11+ stdlib only (`os`, `re`, `shutil`). Tests use the repo's no-pytest idiom (`t_`-prefixed functions, bare `assert`/`raise AssertionError`, `importlib` module load, runner block printing `ok <name>`/`ALL PASS`, auto-discovered by `tools/run-tests.py`).

---

## Scope Decision (resolved during planning)

The spec's M2 line says "Profile CLI **+ init**". The init wizard's existing `env` step gates on `IRO_SHEET_ID` in the machine `.env`, and the relay/setup/graphics consumers still read `IRO_SHEET_ID` until **M3**. Making init profile-aware now would force the operator to enter the Sheet ID twice (once in `profile.env`, once in `.env`) or break events. The init-wizard reconciliation therefore moves to **M3**, alongside the consumer rewiring where `SHEET_ID` genuinely relocates to `profile.env`. **M2 ships the profile CLI + global flag only.** This keeps every milestone shippable.

CLI strings in M2 say `iro` (the binary is still `iro`; the global `iro`→`racecast` rename is the M5 sweep, which will catch these too). The `profiles/example/profile.env` template comment already says `racecast profile new` — that forward-looking doc text is fine and needs no change.

## File Structure

- **Create:** `src/scripts/profile_admin.py` — profile management logic (arg parse, create, set-active, formatting). One responsibility: the operator-facing profile commands. Imports `config` for reads.
- **Create:** `tests/test_profile.py` — unit tests for `profile_admin` (auto-discovered).
- **Modify:** `src/iro.py` — add two imports, a `route()` branch, a `main()` flag-strip + dispatch branch, the `profile_cmd()` handler, and two `USAGE` lines.
- **Modify:** `tests/test_iro.py` — add `profile` routing tests.

`config.py` is reused unchanged. Functions relied on (all present from M1): `cfg.profiles_dir`, `cfg.PROFILE_ENV_NAME`, `cfg.ACTIVE_PROFILE_FILE`, `cfg.list_profiles`, `cfg.read_active_pointer`, `cfg.resolve_config`, `cfg.ProfileError`.

---

### Task 1: `profile_admin` — arg parsing + global flag split + name validation

**Files:**
- Create: `src/scripts/profile_admin.py`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the profile management commands
(src/scripts/profile_admin.py). Run: python3 tests/test_profile.py"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "src", "scripts")
sys.path.insert(0, SCRIPTS)   # so profile_admin's `import config` resolves
spec = importlib.util.spec_from_file_location(
    "profile_admin", os.path.join(SCRIPTS, "profile_admin.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    raise AssertionError("expected exception")


def t_parse_list_takes_no_args():
    assert m.parse_profile_args(["list"]) == {
        "verb": "list", "name": None, "source": "example"}
    _raises(lambda: m.parse_profile_args(["list", "extra"]))


def t_parse_show_optional_name():
    assert m.parse_profile_args(["show"])["name"] is None
    assert m.parse_profile_args(["show", "iro"])["name"] == "iro"
    _raises(lambda: m.parse_profile_args(["show", "a", "b"]))


def t_parse_use_requires_one_name():
    assert m.parse_profile_args(["use", "erf"]) == {
        "verb": "use", "name": "erf", "source": "example"}
    _raises(lambda: m.parse_profile_args(["use"]))
    _raises(lambda: m.parse_profile_args(["use", "a", "b"]))


def t_parse_new_with_from():
    assert m.parse_profile_args(["new", "erf"]) == {
        "verb": "new", "name": "erf", "source": "example"}
    assert m.parse_profile_args(["new", "erf", "--from", "iro"])["source"] == "iro"
    assert m.parse_profile_args(["new", "erf", "--from=iro"])["source"] == "iro"
    _raises(lambda: m.parse_profile_args(["new"]))
    _raises(lambda: m.parse_profile_args(["new", "erf", "--bogus"]))


def t_parse_unknown_verb_raises():
    _raises(lambda: m.parse_profile_args([]))
    _raises(lambda: m.parse_profile_args(["frobnicate"]))


def t_split_profile_flag_extracts_anywhere():
    assert m.split_profile_flag(["relay", "start"]) == (["relay", "start"], None)
    assert m.split_profile_flag(["--profile", "erf", "relay", "start"]) == (
        ["relay", "start"], "erf")
    assert m.split_profile_flag(["relay", "--profile=erf", "start"]) == (
        ["relay", "start"], "erf")


def t_split_profile_flag_missing_value_raises():
    _raises(lambda: m.split_profile_flag(["--profile"]))


def t_valid_profile_name():
    assert m.valid_profile_name("erf")
    assert m.valid_profile_name("gt-2026_a")
    assert not m.valid_profile_name("ERF")
    assert not m.valid_profile_name("-bad")
    assert not m.valid_profile_name("has space")
    assert not m.valid_profile_name("")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_profile.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFound` because `src/scripts/profile_admin.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/profile_admin.py`:

```python
#!/usr/bin/env python3
"""Profile (league) management commands for the operator CLI: list / show /
use / new. Pure logic over config.py + the filesystem; iro.py thin-wraps these.

config.py owns the READ side (resolve the active profile, load its values).
This module owns the WRITE side (create a profile directory, set the active
pointer) plus CLI arg-parsing, the global --profile splitter, and output
formatting. Stdlib only."""

import os
import re
import shutil

import config as cfg   # sibling in src/scripts (sys.path injected by iro.py/tests)

PROFILE_VERBS = ("list", "show", "use", "new")
_USAGE = ("usage: iro profile {list | show [<name>] | use <name> | "
          "new <name> [--from <source>]}")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def valid_profile_name(name):
    """A profile name is a lowercase slug: starts alphanumeric, then letters,
    digits, '-' or '_'. (It becomes a directory name + an env-var value.)"""
    return bool(_NAME_RE.match(name or ""))


def parse_profile_args(rest):
    """argv after `profile` -> {verb, name, source}. Raises ValueError (with
    usage text) on an unknown/missing verb, wrong arity, or an unknown flag."""
    if not rest or rest[0] not in PROFILE_VERBS:
        raise ValueError(_USAGE)
    verb, args = rest[0], rest[1:]
    out = {"verb": verb, "name": None, "source": "example"}
    if verb == "list":
        if args:
            raise ValueError(_USAGE)
    elif verb == "show":
        if len(args) > 1:
            raise ValueError(_USAGE)
        if args:
            out["name"] = args[0]
    elif verb == "use":
        if len(args) != 1:
            raise ValueError(_USAGE)
        out["name"] = args[0]
    elif verb == "new":
        if not args:
            raise ValueError(_USAGE)
        out["name"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--from" and toks:
                out["source"] = toks.pop(0)
            elif t.startswith("--from="):
                out["source"] = t.split("=", 1)[1]
            else:
                raise ValueError(_USAGE)
    return out


def split_profile_flag(argv):
    """Pull a global `--profile <name>` / `--profile=<name>` out of anywhere in
    argv. Returns (cleaned_argv, name_or_None). Raises ValueError if --profile
    is given without a value."""
    out, name, i, toks = [], None, 0, list(argv)
    while i < len(toks):
        t = toks[i]
        if t == "--profile":
            if i + 1 >= len(toks):
                raise ValueError("--profile requires a profile name")
            name = toks[i + 1]
            i += 2
            continue
        if t.startswith("--profile="):
            name = t.split("=", 1)[1]
            i += 1
            continue
        out.append(t)
        i += 1
    return out, name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_profile.py`
Expected: `ok ...` line per test, then `ALL PASS`.

> Add the runner block now at the END of `tests/test_profile.py` so the file runs standalone:

```python
if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

Re-run `python3 tests/test_profile.py` → `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/profile_admin.py tests/test_profile.py
git commit -m "feat(cli): profile arg parsing + global --profile splitter"
```

---

### Task 2: `profile_admin` — create profile + set active

**Files:**
- Modify: `src/scripts/profile_admin.py`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile.py` (before the `if __name__` block):

```python
def _mkroot_with_example(td):
    """A fake project root with profiles/example/profile.env."""
    root = os.path.join(td, "proj")
    ex = os.path.join(root, "profiles", "example")
    os.makedirs(ex)
    with open(os.path.join(ex, "profile.env"), "w", encoding="utf-8") as fh:
        fh.write("NAME=Example League\nSHEET_ID=\n")
    open(os.path.join(root, ".env.example"), "w").close()   # project marker
    return root


def t_create_profile_copies_example():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        target = m.create_profile(root, "erf")
        assert target == os.path.join(root, "profiles", "erf")
        assert os.path.isfile(os.path.join(target, "profile.env"))
        # config now lists it (example stays excluded)
        assert m.cfg.list_profiles(root) == ["erf"]


def t_create_profile_from_other_profile():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        m.create_profile(root, "iro")
        with open(os.path.join(root, "profiles", "iro", "profile.env"),
                  "w", encoding="utf-8") as fh:
            fh.write("NAME=IRO\nSHEET_ID=abc\n")
        m.create_profile(root, "erf", source="iro")
        assert m.cfg.parse_profile(root, "erf")["SHEET_ID"] == "abc"


def t_create_profile_rejects_bad_name_existing_and_missing_source():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        _raises(lambda: m.create_profile(root, "BAD NAME"))
        _raises(lambda: m.create_profile(root, "example"))   # reserved
        m.create_profile(root, "erf")
        _raises(lambda: m.create_profile(root, "erf"))        # already exists
        _raises(lambda: m.create_profile(root, "x", source="ghost"))  # no source


def t_set_active_profile_writes_pointer():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        m.create_profile(root, "erf")
        runtime = os.path.join(td, "runtime")
        assert m.set_active_profile(root, runtime, "erf") == "erf"
        assert m.cfg.read_active_pointer(runtime) == "erf"


def t_set_active_profile_unknown_raises():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        runtime = os.path.join(td, "runtime")
        _raises(lambda: m.set_active_profile(root, runtime, "ghost"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_profile.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'create_profile'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/profile_admin.py`:

```python
def create_profile(root, name, source="example"):
    """Copy profiles/<source>/ -> profiles/<name>/ and return the new dir path.
    Raises ValueError on an invalid/reserved name, an existing target, or a
    missing source profile.env."""
    if not valid_profile_name(name):
        raise ValueError(f"invalid profile name {name!r} (use lowercase "
                         "letters, digits, '-' or '_')")
    if name == "example":
        raise ValueError("'example' is the reserved template name")
    pdir = cfg.profiles_dir(root)
    target = os.path.join(pdir, name)
    if os.path.exists(target):
        raise ValueError(f"profile {name!r} already exists ({target})")
    src = os.path.join(pdir, source)
    if not os.path.isfile(os.path.join(src, cfg.PROFILE_ENV_NAME)):
        raise ValueError(
            f"source profile {source!r} not found "
            f"({os.path.join(src, cfg.PROFILE_ENV_NAME)})")
    shutil.copytree(src, target)
    return target


def set_active_profile(root, runtime_root, name):
    """Write runtime/active-profile = name. Raises ValueError if `name` is not a
    known profile. Creates runtime_root if needed. Returns the name."""
    available = cfg.list_profiles(root)
    if name not in available:
        raise ValueError(f"unknown profile {name!r} "
                         f"(available: {', '.join(available) or 'none'})")
    os.makedirs(runtime_root, exist_ok=True)
    with open(os.path.join(runtime_root, cfg.ACTIVE_PROFILE_FILE),
              "w", encoding="utf-8") as fh:
        fh.write(name + "\n")
    return name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_profile.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/profile_admin.py tests/test_profile.py
git commit -m "feat(cli): create-profile (copy template) + set-active-profile"
```

---

### Task 3: `profile_admin` — output formatting (list + show, secret-masked)

**Files:**
- Modify: `src/scripts/profile_admin.py`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile.py`:

```python
def t_format_profile_list_marks_active():
    out = m.format_profile_list(["erf", "iro"], "iro")
    assert "  erf" in out
    assert "* iro" in out


def t_format_profile_list_empty():
    assert "no profiles" in m.format_profile_list([], None)


def t_mask_hides_secret_body():
    assert m.mask_secret("") == "(unset)"
    assert m.mask_secret("https://script.google.com/exec?key=SECRETVALUE") \
        .startswith("http")
    # the secret body is not shown in full
    assert "SECRETVALUE" not in m.mask_secret(
        "https://x/exec?key=SECRETVALUE")
    assert m.mask_secret("short") == "****"


def t_format_profile_show_masks_push_url():
    cfg_obj = m.cfg.ResolvedConfig(
        profile="iro", name="IRO Endurance", sheet_id="SHEETID123",
        sheet_push_url="https://x/exec?key=TOPSECRET",
        profile_dir="/p/profiles/iro", runtime_dir="/p/runtime/iro")
    out = m.format_profile_show(cfg_obj, active="iro")
    assert "IRO Endurance" in out
    assert "SHEETID123" in out          # sheet id shown (link-shared, not a secret)
    assert "TOPSECRET" not in out       # push-url secret masked
    assert "(active)" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_profile.py`
Expected: FAIL — `AttributeError: ... has no attribute 'format_profile_list'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/scripts/profile_admin.py`:

```python
def format_profile_list(names, active):
    """One profile per line, the active one marked with '* '. ASCII only."""
    if not names:
        return "no profiles — create one with `iro profile new <name>`"
    return "\n".join(("* " if n == active else "  ") + n for n in names)


def mask_secret(value):
    """Show enough of a secret URL to recognize it without revealing the key.
    Empty -> '(unset)'; short -> '****'; else first 8 chars + '...'. ASCII only."""
    if not value:
        return "(unset)"
    if len(value) <= 8:
        return "****"
    return value[:8] + "..."


def format_profile_show(rcfg, active):
    """Multi-line human view of a ResolvedConfig. The sheet-push-url (carries a
    ?key= secret) is masked; the sheet id is shown (it is link-shared, not a
    secret). ASCII only."""
    tag = "  (active)" if rcfg.profile == active else ""
    return "\n".join([
        f"profile:        {rcfg.profile}{tag}",
        f"name:           {rcfg.name}",
        f"sheet_id:       {rcfg.sheet_id or '(unset)'}",
        f"sheet_push_url: {mask_secret(rcfg.sheet_push_url)}",
        f"intro_url:      {rcfg.intro_url or '(unset)'}",
        f"outro_url:      {rcfg.outro_url or '(unset)'}",
        f"logo:           {rcfg.logo_path or '(none)'}",
        f"profile_dir:    {rcfg.profile_dir}",
        f"runtime_dir:    {rcfg.runtime_dir}",
    ])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_profile.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/profile_admin.py tests/test_profile.py
git commit -m "feat(cli): profile list/show formatting with push-url masking"
```

---

### Task 4: wire the `profile` command + global `--profile` into `src/iro.py`

**Files:**
- Modify: `src/iro.py` (imports, `route()`, `main()`, new `profile_cmd()`, `USAGE`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing routing test**

Append to `tests/test_iro.py` (before the `if __name__` runner block):

```python
def t_profile_routing():
    assert m.route(["profile", "list"]) == {"kind": "profile", "rest": ["list"]}
    assert m.route(["profile", "new", "erf", "--from", "example"]) == {
        "kind": "profile", "rest": ["new", "erf", "--from", "example"]}
    # an unknown profile verb is NOT validated at the route seam (parse_profile_args
    # does that) — route just hands the rest through:
    assert m.route(["profile", "bogus"]) == {"kind": "profile", "rest": ["bogus"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `route(["profile", "list"])` currently raises `ValueError("unknown command: profile")`, so the assert raises before matching.

- [ ] **Step 3a: Add the two module imports**

In `src/iro.py`, find this exact block (around line 30-31):

```python
import services as sv
import init_setup as ins
```

Replace it with:

```python
import services as sv
import init_setup as ins
import config as cfg
import profile_admin as pa
```

- [ ] **Step 3b: Add the `route()` branch**

In `src/iro.py`, find this exact block in `route()`:

```python
    if cmd in ONESHOTS:
        return {"kind": "oneshot", "command": cmd, "rest": rest}
```

Insert the profile branch immediately BEFORE it, so it reads:

```python
    if cmd == "profile":
        return {"kind": "profile", "rest": rest}
    if cmd in ONESHOTS:
        return {"kind": "oneshot", "command": cmd, "rest": rest}
```

- [ ] **Step 3c: Add the `profile_cmd()` handler**

In `src/iro.py`, find this exact line (the start of the init handler):

```python
def init_cmd(rest):
```

Insert this complete function immediately BEFORE it:

```python
def profile_cmd(rest):
    """`iro profile list|show|use|new` — manage league profiles. Resolves the
    project root + runtime dir the same way the rest of the CLI does, so it
    sees profiles/ and runtime/active-profile consistently with config.py."""
    try:
        opts = pa.parse_profile_args(rest)
    except ValueError as e:
        sys.exit(f"iro: {e}")
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    runtime_root = _runtime_dir()
    active = cfg.read_active_pointer(runtime_root)
    verb = opts["verb"]
    if verb == "list":
        print(pa.format_profile_list(cfg.list_profiles(root), active))
        return None
    if verb == "new":
        try:
            target = pa.create_profile(root, opts["name"], opts["source"])
        except ValueError as e:
            sys.exit(f"iro: {e}")
        env_path = os.path.join(target, cfg.PROFILE_ENV_NAME)
        print(f"created profile '{opts['name']}' at {target}")
        print(f"  edit {env_path} (fill in SHEET_ID), then: "
              f"iro profile use {opts['name']}")
        return None
    if verb == "use":
        try:
            pa.set_active_profile(root, runtime_root, opts["name"])
        except ValueError as e:
            sys.exit(f"iro: {e}")
        print(f"active profile: {opts['name']}")
        return None
    # verb == "show"
    try:
        rcfg = cfg.resolve_config(root, override=opts["name"],
                                  runtime_root=runtime_root)
    except cfg.ProfileError as e:
        sys.exit(f"iro: {e}")
    print(pa.format_profile_show(rcfg, active))
    return None
```

- [ ] **Step 3d: Strip the global `--profile` flag in `main()` and dispatch the profile kind**

In `src/iro.py` `main()`, find this exact line:

```python
    argv = sys.argv[1:] if argv is None else argv
```

Insert immediately AFTER it:

```python
    try:
        argv, _profile = pa.split_profile_flag(argv)
    except ValueError as e:
        sys.exit(f"iro: {e}")
    if _profile:
        os.environ["RACECAST_PROFILE"] = _profile   # M3 consumers read this
```

Then, still in `main()`, find this exact block:

```python
    if action["kind"] == "init":
        return init_cmd(action["rest"])
```

Insert immediately AFTER it:

```python
    if action["kind"] == "profile":
        return profile_cmd(action["rest"])
```

- [ ] **Step 3e: Document the commands in `USAGE`**

In `src/iro.py`, find this exact line in the module docstring:

```python
  iro status                            # aggregate health of all services
```

Insert these two lines immediately AFTER it:

```python
  iro profile   list | show [<name>] | use <name> | new <name> [--from <source>]
  iro --profile <name> <command>        # run one command against a non-active profile
```

- [ ] **Step 4: Run the routing test to verify it passes**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS` (includes `ok t_profile_routing`).

- [ ] **Step 5: End-to-end smoke test (manual, real CLI)**

Run this sequence from the repo root and check the output. `profiles/testleague/` is gitignored (`profiles/*`), but clean it up anyway:

```bash
python3 src/iro.py profile list
python3 src/iro.py profile new testleague
python3 src/iro.py profile use testleague
python3 src/iro.py profile show
python3 src/iro.py --profile testleague profile show
python3 src/iro.py profile bogus ; echo "exit=$?"
rm -rf profiles/testleague runtime/active-profile
```
Expected:
- `profile list` → either `no profiles ...` or a list (depends on local state).
- `profile new testleague` → `created profile 'testleague' at .../profiles/testleague` + the edit hint.
- `profile use testleague` → `active profile: testleague`.
- `profile show` and `--profile testleague profile show` → the multi-line view with `profile: testleague  (active)` (the `--profile` form also active because it equals the pointer).
- `profile bogus` → prints the `usage: iro profile {...}` line and `exit=1`.

- [ ] **Step 6: Run the full project gate**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected:
- `run-tests.py` → `ALL TEST FILES PASS` (incl. `== test_profile.py` and `== test_iro.py`).
- `lint.py` → clean.
- `build.py` → verify step passes (the new `profile_admin.py` ships under `src/scripts/`; no secrets, no shell scripts).

- [ ] **Step 7: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): wire profile command group + global --profile flag"
```

---

## Self-Review

**Spec coverage (M2):**
- `racecast profile list / show / use / new --from` → Tasks 1–4 (`parse_profile_args`, `create_profile`, `set_active_profile`, `format_*`, wired in `profile_cmd`). ✅
- Global `--profile` flag → Task 1 (`split_profile_flag`) + Task 4 (main() exports `RACECAST_PROFILE`). ✅
- "profiles/example/ template" → already shipped in M1; `create_profile` defaults `source="example"`. ✅
- "Extend tests (test_iro.py, test_init.py)" → test_iro.py extended (Task 4); **test_init.py untouched** because the init wizard change is deferred to M3 (see Scope Decision). The new `tests/test_profile.py` covers the profile logic.

**Deferred (intentionally NOT in M2):** the profile-aware init wizard step (M3, when `SHEET_ID` actually moves from `.env`/`IRO_SHEET_ID` to `profile.env`); any consumer rewiring; the `iro`→`racecast` string rename (M5).

**Placeholder scan:** none — every step has full code/commands/expected output.

**Type/name consistency:** `parse_profile_args`, `split_profile_flag`, `valid_profile_name`, `create_profile`, `set_active_profile`, `format_profile_list`, `mask_secret`, `format_profile_show` — names identical between `profile_admin.py` and `tests/test_profile.py` across Tasks 1–3, and used identically by `profile_cmd` in Task 4. `profile_cmd` only calls `config` symbols that exist in M1 (`cfg.profiles_dir`, `cfg.PROFILE_ENV_NAME`, `cfg.ACTIVE_PROFILE_FILE`, `cfg.list_profiles`, `cfg.read_active_pointer`, `cfg.resolve_config`, `cfg.ProfileError`) and iro.py helpers that exist (`_env_base`, `_real_executable`, `IS_FROZEN`, `HERE`, `_runtime_dir`). The route action `{"kind": "profile", "rest": rest}` matches the `main()` dispatch branch and the `t_profile_routing` test.

---

## CI Gate (must stay green at end of M2)

- `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- `python3 tools/lint.py` → clean
- `python3 tools/build.py` → verify passes
- No `IRO_*` var renamed; relay/setup/graphics/media + init wizard behavior unchanged (M2 is additive on the CLI surface).
