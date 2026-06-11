# M3b — Profile-Aware Init Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `iro init` profile-aware — replace its `IRO_SHEET_ID`-in-machine-`.env` gate with a **profile step** that ensures an active league profile whose `SHEET_ID` is filled — so first-time setup drives the multi-profile model M3a put in place.

**Architecture:** Add a `profile` step (first) to the init wizard that creates/selects a league profile (via the M2 `profile_admin` helpers) and gates until its `SHEET_ID` is set, then re-injects the profile config. Demote the existing `env` step to a no-gate machine-`.env` creator (league config no longer lives there). Drop the league vars from `.env.example`. The OBS scene-collection tie-in is a separate plan (M3c).

**Tech Stack:** Python 3.11+ stdlib only. Tests: no-pytest idiom (`t_`-prefixed, bare `assert`/`raise AssertionError`, `importlib` load, runner, auto-discovered by `tools/run-tests.py`).

---

## Scope Decisions

1. **OBS scene-collection tie-in is M3c, not M3b.** (origin/main was merged in 2026-06-11, so the OBS switch feature now exists; making it per-league is its own focused plan.)
2. **Machine vars stay `IRO_*`** in `.env.example` (`IRO_OBS_WS_PASSWORD`/`IRO_COMPANION_EXE`/`IRO_UI_PORT`) — renamed in M5. M3b only REMOVES the four league vars (now in `profile.env`) and the product-name de-brand stays M5.
3. **Control Center init rendering is M4.** M3b adds the `profile` step to the shared `STEP_ORDER`/`STEP_KINDS` contract (so M4 inherits it) and wires the CLI wizard's done/run. The UI's `init_plan_data` already iterates the step list generically, so it stays green.

## File Structure

- **Modify:** `src/scripts/init_setup.py` — add pure `profile_done` + `prompt_value`; restructure `STEP_ORDER`/`STEP_LABELS`/`STEP_KINDS` (add `profile`, demote `env`); remove `REQUIRED_ENV` + `env_done`.
- **Modify:** `src/iro.py` — add `_active_sheet_id`, `_active_profile_env_path`, `_init_profile_done`, `_init_profile_run`; de-gate `_init_env_run`; update `_init_steps` (`profile` entry, `env` done-probe, `setup` freshness dep).
- **Modify:** `.env.example` — drop the four league-var blocks, keep machine vars + `RACECAST_PROFILE`.
- **Modify:** `tests/test_init.py` — `t_profile_done`, `t_prompt_value`; remove `t_env_done`.

Reused (M1/M2/M3a, unchanged): `pa.create_profile`, `pa.set_active_profile`, `pcfg.list_profiles`, `pcfg.resolve_config`, `pcfg.profiles_dir`, `pcfg.PROFILE_ENV_NAME`, `_active_profile_name`, `_runtime_base_dir`, `_env_base`, `_apply_active_profile_env`, `_env_file`, `_init_pause`.

---

### Task 1: pure init helpers — `profile_done` + `prompt_value`

**Files:**
- Modify: `src/scripts/init_setup.py`
- Test: `tests/test_init.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py` (before the `if __name__` runner):

```python
def t_profile_done():
    assert m.profile_done("iro", "SHEET123") is not None
    assert m.profile_done("iro", "") is None
    assert m.profile_done(None, "SHEET123") is None
    assert m.profile_done(None, "") is None


def t_prompt_value_returns_stripped_answer_when_tty():
    assert m.prompt_value("Name", True, ask=lambda _p: "  erf  ") == "erf"


def t_prompt_value_checkpoints_when_not_tty():
    try:
        m.prompt_value("Name", False, ask=lambda _p: "x")
        raise AssertionError("expected SystemExit")
    except SystemExit:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_init.py`
Expected: FAIL — `AttributeError: module 'init_setup' has no attribute 'profile_done'`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/init_setup.py`, find this exact function:

```python
def env_done(env):
    """`env` is the merged os.environ + .env mapping."""
    if all(env.get(k) for k in REQUIRED_ENV):
        return "IRO_SHEET_ID set"
    return None
```

Replace it with:

```python
def profile_done(active, sheet_id):
    """The profile step is done when a league profile is active and its SHEET_ID
    is filled in. `active` is the active profile name (or None); `sheet_id` its
    SHEET_ID value (or '')."""
    if active and sheet_id:
        return f"profile '{active}' ready"
    return None


def prompt_value(message, isatty, ask=input):
    """Collect one line at a manual step. Interactive: return the stripped
    answer. Non-TTY (CI/pipe): degrade to checkpoint-and-exit (same contract as
    gate_pause)."""
    if not isatty:
        raise SystemExit(f"{message}\nThen run `iro init` again.")
    return ask(f"{message}: ").strip()
```

(This removes `env_done`. `REQUIRED_ENV` is removed in Task 2 together with its last reference.)

- [ ] **Step 4: Update the obsolete `env_done` test**

In `tests/test_init.py`, find this exact function:

```python
def t_env_done():
    assert m.env_done({"IRO_SHEET_ID": "x"}) is not None
    assert m.env_done({"IRO_SHEET_ID": ""}) is None
    assert m.env_done({}) is None
```

Delete it entirely (its three lines + the `def` line + the trailing blank line). `profile_done` replaces its coverage.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_init.py`
Expected: `ALL PASS` (includes `ok t_profile_done`, `ok t_prompt_value_returns_stripped_answer_when_tty`, `ok t_prompt_value_checkpoints_when_not_tty`; no `t_env_done`).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/init_setup.py tests/test_init.py
git commit -m "feat(init): profile_done + prompt_value helpers (replace env_done)"
```

---

### Task 2: switch the wizard to a profile gate (atomic)

This task changes the step contract AND the CLI wiring together so the wizard is never half-broken.

**Files:**
- Modify: `src/scripts/init_setup.py` (constants), `src/iro.py` (init glue)

- [ ] **Step 1: init_setup.py — restructure the step constants**

In `src/scripts/init_setup.py`, find this exact block:

```python
REQUIRED_ENV = ("IRO_SHEET_ID",)

STEP_ORDER = ("env", "install-tools", "install-apps", "cookies", "graphics",
              "media", "setup", "export-companion", "preflight")
INSTALL_STEPS = ("install-tools", "install-apps")
STEP_LABELS = {
    "env": ".env",
    "install-tools": "install-tools",
    "install-apps": "install-apps",
    "cookies": "cookies",
    "graphics": "graphics",
    "media": "media",
    "setup": "setup (OBS collection)",
    "export-companion": "export companion",
    "preflight": "preflight",
}
```

Replace it with:

```python
STEP_ORDER = ("profile", "env", "install-tools", "install-apps", "cookies",
              "graphics", "media", "setup", "export-companion", "preflight")
INSTALL_STEPS = ("install-tools", "install-apps")
STEP_LABELS = {
    "profile": "profile (league)",
    "env": ".env (machine)",
    "install-tools": "install-tools",
    "install-apps": "install-apps",
    "cookies": "cookies",
    "graphics": "graphics",
    "media": "media",
    "setup": "setup (OBS collection)",
    "export-companion": "export companion",
    "preflight": "preflight",
}
```

Then find this exact block:

```python
STEP_KINDS = {
    "env": {"kind": "gate", "op": None,
            "instruction": "Open Settings and set IRO_SHEET_ID in .env "
                           "(IRO_SHEET_PUSH_URL is optional). Then re-check."},
    "install-tools": {"kind": "job", "op": "install-tools"},
```

Replace it with:

```python
STEP_KINDS = {
    "profile": {"kind": "gate", "op": None,
                "instruction": "Create or select a league profile and set its "
                               "SHEET_ID (profiles/<name>/profile.env). Then re-check."},
    "env": {"kind": "action", "op": None},
    "install-tools": {"kind": "job", "op": "install-tools"},
```

- [ ] **Step 2: iro.py — add the profile-step helpers**

In `src/iro.py`, find this exact function:

```python
def _init_env_run():
    """The .env step has no script to run — its work IS the gate: make sure
    the file exists (copy the template once, any run mode), then pause until
    the operator filled in the required values."""
    path = _env_file()
    example = os.path.join(os.path.dirname(path), ".env.example")
    if not os.path.exists(path) and os.path.exists(example):
        shutil.copyfile(example, path)
        print(f"  created {path} from .env.example")
    while ins.env_done(_init_env_state()) is None:
        _init_pause(f"Fill in IRO_SHEET_ID in {path} (IRO_SHEET_PUSH_URL is "
                    "optional — see the Sheet-Webhook wiki page)")
    for key, val in _read_env_file().items():
        os.environ.setdefault(key, val)   # downstream probes + children see them
    return 0
```

Replace it with:

```python
def _active_sheet_id(root, base, active):
    """The active profile's SHEET_ID, or '' if no profile / unresolvable."""
    if not active:
        return ""
    try:
        return pcfg.resolve_config(root, override=active,
                                   runtime_root=base).sheet_id
    except pcfg.ProfileError:
        return ""


def _active_profile_env_path():
    """profiles/<active>/profile.env for the active profile (falls back to the
    machine .env when no profile is active)."""
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    active = _active_profile_name()
    if not active:
        return _env_file()
    return os.path.join(pcfg.profiles_dir(root), active, pcfg.PROFILE_ENV_NAME)


def _init_profile_done():
    """Wizard done-probe for the profile step."""
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    base = _runtime_base_dir()
    active = _active_profile_name()
    return ins.profile_done(active, _active_sheet_id(root, base, active))


def _init_profile_run():
    """Ensure a league profile is active with its SHEET_ID filled. Creates one
    from the example template (prompting for a name) when none exists, pauses
    until SHEET_ID is set, then re-injects the profile's config for the steps
    that follow (graphics/media/setup)."""
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    base = _runtime_base_dir()
    if not pcfg.list_profiles(root):
        name = ins.prompt_value(
            "Name your league profile (e.g. iro, erf)", sys.stdin.isatty())
        try:
            pa.create_profile(root, name)
            pa.set_active_profile(root, base, name)
        except ValueError as e:
            sys.exit(f"iro: {e}")
        print(f"  created profile '{name}' (profiles/{name}/profile.env)")
    while True:
        active = _active_profile_name()
        if active is None:
            _init_pause("Select a league profile: run `iro profile use <name>`")
            continue
        if _active_sheet_id(root, base, active):
            break
        path = os.path.join(pcfg.profiles_dir(root), active, pcfg.PROFILE_ENV_NAME)
        _init_pause(f"Fill in SHEET_ID in {path} (SHEET_PUSH_URL is optional)")
    _apply_active_profile_env()
    return 0


def _init_env_run():
    """Machine .env: create it from the template if missing (optional machine
    vars + the default profile). No gate -- league config lives in the profile."""
    path = _env_file()
    example = os.path.join(os.path.dirname(path), ".env.example")
    if not os.path.exists(path) and os.path.exists(example):
        shutil.copyfile(example, path)
        print(f"  created {path} from .env.example")
    for key, val in _read_env_file().items():
        os.environ.setdefault(key, val)
    return 0
```

- [ ] **Step 3: iro.py — wire the steps in `_init_steps`**

In `src/iro.py` `_init_steps`, find this exact block:

```python
    by_key = {
        "env": {"done": lambda: ins.env_done(_init_env_state()),
                "run": _init_env_run},
```

Replace it with:

```python
    by_key = {
        "profile": {"done": _init_profile_done,
                    "run": _init_profile_run},
        "env": {"done": lambda: ".env present"
                if os.path.exists(_env_file()) else None,
                "run": _init_env_run},
```

Then, still in `_init_steps`, find the `setup` step's freshness dependency:

```python
        "setup": {"done": lambda: ins.setup_done(
                      _mtime(_init_import_json()),
                      [_mtime(_env_file())] if IS_FROZEN else
                      [_mtime(resource_path("obs/IRO_Endurance.json")),
                       _mtime(_env_file())]),
```

Replace it with:

```python
        "setup": {"done": lambda: ins.setup_done(
                      _mtime(_init_import_json()),
                      [_mtime(_active_profile_env_path())] if IS_FROZEN else
                      [_mtime(resource_path("obs/IRO_Endurance.json")),
                       _mtime(_active_profile_env_path())]),
```

- [ ] **Step 4: Remove the now-dead `_init_env_state`**

`_init_env_state` was only used by the old `env_done` gate. In `src/iro.py`, find this exact function and DELETE it entirely:

```python
def _init_env_state():
    """os.environ merged over the .env file (real environment wins) — the
    mapping env_done() judges."""
    env = dict(_read_env_file())
    env.update(os.environ)
    return env
```

> Verify it has no other callers first: `grep -n "_init_env_state" src/iro.py` must show only the definition. If anything else references it, leave it and note it instead.

- [ ] **Step 5: Verify the suite + the wizard wiring**

Run:
```bash
grep -n "env_done\|REQUIRED_ENV\|_init_env_state" src/iro.py src/scripts/init_setup.py
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected:
- the grep shows NO hits (all three removed).
- `run-tests.py` → `ALL TEST FILES PASS` (the UI `init_plan_data` tests pass — they iterate the step list generically and the new `profile` gate has `op=None`, so `t_wizard_job_ops_all_exist_in_registry` is unaffected).
- `lint.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/init_setup.py src/iro.py
git commit -m "feat(init): profile step gates on the active league's SHEET_ID"
```

---

### Task 3: drop the league vars from `.env.example`

League config now lives in `profiles/<name>/profile.env`; the machine `.env` keeps only optional machine vars + the default-profile selector.

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Rewrite `.env.example`**

Replace the ENTIRE contents of `.env.example` with:

```
# IRO broadcast -- machine-local config. Copy to ".env" (gitignored) and fill in.
#   cp .env.example .env
# Real environment variables take precedence over values in this file.
#
# League config (Google Sheet ID + push URL + intro/outro) is NOT here -- it
# lives per league in profiles/<name>/profile.env (see `iro profile new`).

# OPTIONAL: OBS WebSocket password for the feed-port release on `iro ... stop`
# (OBS is asked to stop the relay-fed media inputs so the feed ports tear down
# cleanly). Normally NOT needed -- the password is auto-read from OBS's own
# obs-websocket config on this machine. Set it only for portable/non-standard
# OBS installs where that config is not in the default location.
IRO_OBS_WS_PASSWORD=

# OPTIONAL (Windows): full path to Companion.exe for `iro companion start/stop`.
# Only needed when Companion sits in a NON-standard location -- the standard
# install paths are found automatically, e.g. the winget / install-apps default:
#   IRO_COMPANION_EXE=C:\Program Files\Companion\Companion.exe
IRO_COMPANION_EXE=

# OPTIONAL: port of the local Control Center web app (`iro ui`). Set this only
# when another application on this machine already occupies the default 8089.
IRO_UI_PORT=

# RESERVED for the future remote-support feature (Control Center over
# Tailscale): not read by any current version -- leave commented out.
# IRO_UI_PASSWORD=

# Default active profile (league) when neither --profile nor an explicit
# RACECAST_PROFILE env var is given. Each league lives in profiles/<name>/.
# Leave unset if you keep exactly one profile (it is then selected implicitly).
RACECAST_PROFILE=
```

- [ ] **Step 2: Verify no consumer still needs the removed vars**

Run:
```bash
grep -rn "IRO_SHEET_ID\|IRO_SHEET_PUSH_URL\|IRO_INTRO_URL\|IRO_OUTRO_URL" src/iro.py src/scripts/init_setup.py src/relay/ src/setup-assets.py
python3 tools/build.py
```
Expected:
- the grep shows NO hits in those code paths (the relay/setup/graphics/media read `RACECAST_*` since M3a; init no longer gates on `IRO_SHEET_ID` after Task 2). Doc/HTML hits elsewhere are expected (M4/M5).
- `build.py` → verify passes (no secrets, the blanked-password + tokenization checks still hold; `.env.example` carries no secret).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "feat(init): drop league vars from .env.example (they live in profile.env)"
```

---

### Task 4: end-to-end init-gate smoke test

**Files:** none modified — verifies the profile gate behaves.

- [ ] **Step 1: With no profile, the gate is not done**

Run from the repo root (ensure a clean slate first):
```bash
rm -rf runtime/active-profile
python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('iro','src/iro.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('no-profile done:', m._init_profile_done())"
```
Expected: `no-profile done: None` (the gate fires; with zero or multiple profiles and no SHEET_ID, it is not done).

- [ ] **Step 2: With an active profile lacking SHEET_ID → still not done; with SHEET_ID → done**

Run:
```bash
python3 src/iro.py profile new smoke >/dev/null
python3 src/iro.py profile use smoke >/dev/null
python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('iro','src/iro.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('empty-sheet done:', m._init_profile_done())"
printf 'NAME=Smoke\nSHEET_ID=SMOKESHEET\n' > profiles/smoke/profile.env
python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('iro','src/iro.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('filled-sheet done:', m._init_profile_done())"
```
Expected: `empty-sheet done: None`, then `filled-sheet done: profile 'smoke' ready`.

- [ ] **Step 3: Clean up + final gate**

Run:
```bash
rm -rf profiles/smoke runtime/smoke runtime/active-profile
git status --short
python3 tools/run-tests.py
```
Expected: working tree clean; `ALL TEST FILES PASS`. (Verification only — no commit. Fix any surfaced bug under the relevant earlier task and commit there.)

---

## Self-Review

**Spec coverage (M3b):**
- "profile-aware init wizard (profile step replaces the IRO_SHEET_ID .env gate)" → Tasks 1+2 (`profile_done`/`prompt_value`, the `profile` step, de-gated `env`). ✅
- ".env.example loses league vars" → Task 3. ✅
- "init's import-json/companion/cookie paths already profile-scoped/shared" → inherited from M3a (`_init_import_json` uses `_runtime_dir()`; cookies use `_cookies_path()`), no change needed. ✅
- "OBS collection switch tie-in" → **M3c** (separate plan; the feature now exists on the merged main).

**Placeholder scan:** none — every step has full code/commands/expected output. The two grep verification steps (Task 2 Step 5, Task 3 Step 2) check an explicit, enumerated token set.

**Type/name consistency:** `profile_done`, `prompt_value` (init_setup); `_active_sheet_id`, `_active_profile_env_path`, `_init_profile_done`, `_init_profile_run`, `_init_env_run` (iro.py) — names used identically across tasks and at call sites (`_init_steps` `by_key`). `_init_profile_done`/`_init_profile_run` are referenced by the `profile` `by_key` entry added in Task 2 Step 3. `env_done`, `REQUIRED_ENV`, `_init_env_state` are removed and have no remaining references (verified in Task 2 Step 5).

---

## CI Gate (must stay green at end of M3b)

- `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- `python3 tools/lint.py` → clean
- `python3 tools/build.py` → verify passes
- Smoke (Task 4): the profile gate is not-done without an active profile + SHEET_ID, and done once both are set.
- Untouched: the OBS scene-collection feature, the machine vars (`IRO_OBS_WS_PASSWORD`/`IRO_COMPANION_EXE`/`IRO_UI_PORT`), the `iro` binary name, the `__IRO_*__` OBS tokens, the Control Center init rendering (M4).
