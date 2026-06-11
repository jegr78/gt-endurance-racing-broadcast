# M3a — Profile-Scoped Runtime + Consumer Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all runtime state and league config profile-scoped — `iro <command>` and `iro event start` run entirely against the active profile's `runtime/<profile>/` dir and that profile's Google Sheet, so two leagues (IRO, ERF) never collide.

**Architecture:** `src/iro.py` is the profile authority. At startup `main()` resolves the active profile (via M1's `config.py`) and injects its league values (`RACECAST_SHEET_ID`/`_PUSH_URL`/`_INTRO_URL`/`_OUTRO_URL`) into `os.environ`; every child (relay daemon, one-shots, probes) inherits them. `_runtime_dir()` becomes `runtime/<profile>/`, so the relay, timer, caches, cookies, assets, PID/logs, and the OBS import JSON all land under the profile. The relay and the asset scripts stay self-contained — they just read the renamed `RACECAST_*` vars and the `--runtime-dir`/`--out` paths the CLI hands them. The only thing that stays at the un-scoped `runtime/` root is the `active-profile` pointer.

**Tech Stack:** Python 3.11+ stdlib only. Tests: no-pytest idiom (`t_`-prefixed, bare `assert`/`raise AssertionError`, `importlib` load, `if __name__=="__main__"` runner, auto-discovered by `tools/run-tests.py`).

---

## Scope Decisions (resolved during planning)

1. **Cookies are profile-scoped, not shared.** The spec said cookies shared, but cookie paths hang off `_runtime_dir()` in 5+ places; scoping them per-profile falls out for free, whereas "shared" would thread a base-vs-profile distinction through relay/preflight/init. Operationally fine (`iro cookies` is re-run per event anyway). The only un-scoped thing is the `active-profile` pointer. If shared cookies are wanted later, that's a small follow-up.
2. **OBS token rename `__IRO_*__` → `__RACECAST_*__` stays in M5.** The token is just a literal placeholder that `setup-assets.py` resolves; renaming it is cosmetic de-branding, not functional. M3a keeps the tokens and the committed `src/obs/IRO_Endurance.json` as-is; it only changes WHERE setup points the resolved paths (profile runtime) and WHICH sheet id it bakes in (active profile).
3. **The `iro` → `racecast` binary rename + machine-var renames (`IRO_OBS_WS_PASSWORD`, `IRO_COMPANION_EXE`, `IRO_UI_PORT`) stay in M5.** M3a renames ONLY the four league-config reads that move into the profile: `IRO_SHEET_ID`, `IRO_SHEET_PUSH_URL`, `IRO_INTRO_URL`, `IRO_OUTRO_URL` (+ the dynamic `IRO_{KEY}_URL`).
4. **The init wizard is M3b.** M3a leaves `init_setup.py`, `_init_env_run`, `REQUIRED_ENV`, and `.env.example` untouched (the env step still gates the legacy `IRO_SHEET_ID` — unused by events after M3a, reconciled in M3b). M3a is otherwise the full event path.

## File Structure

- **Modify:** `src/iro.py` — profile-scoped `_runtime_dir()` + `_runtime_base_dir()` + `_active_profile_name()`; `_apply_active_profile_env()` in `main()`; `_oneshot_extra()` always points asset output at the profile runtime; `_asset_dirs()` profile-scoped; `profile_cmd` pointer at the base; the 3 league-sheet env reads renamed.
- **Modify:** `src/relay/iro-feeds.py`, `src/setup-assets.py`, `src/relay/get-graphics.py`, `src/relay/get-media.py`, `src/scripts/preflight.py` — rename the league-config env reads + their user-facing strings to `RACECAST_*` (self-contained scripts; no imports added).
- **Modify:** `tests/test_iro.py` (+ the rename sweep across `tests/`) — new pure-helper tests + updated env-var names.

---

### Task 1: profile-scoped runtime dir + base-for-pointer

**Files:**
- Modify: `src/iro.py` (`_runtime_dir`, new helpers, `profile_cmd`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_iro.py` (before the `if __name__` runner):

```python
def t_profile_runtime_scoping():
    assert m._profile_runtime("/r", "iro") == os.path.join("/r", "iro")
    assert m._profile_runtime("/r", "erf") == os.path.join("/r", "erf")
    assert m._profile_runtime("/r", None) == "/r"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `AttributeError: module 'iro' has no attribute '_profile_runtime'`.

- [ ] **Step 3: Write minimal implementation**

In `src/iro.py`, find this exact block:

```python
def _runtime_dir():
    return _runtime_base(IS_FROZEN, _real_executable(), HERE)
```

Replace it with:

```python
def _runtime_base_dir():
    """The un-scoped machine runtime/ dir. Only the active-profile pointer lives
    here directly; per-league state lives under _runtime_dir()."""
    return _runtime_base(IS_FROZEN, _real_executable(), HERE)

def _profile_runtime(base_runtime, profile_name):
    """Profile-scoped runtime dir: <base>/<profile> when a profile is active,
    else the base (fresh machine / no profile yet)."""
    return os.path.join(base_runtime, profile_name) if profile_name else base_runtime

def _active_profile_name():
    """The active profile name (tolerant): RACECAST_PROFILE env / the active
    pointer / the sole profile -- or None if none can be resolved, so commands
    that do not need a profile still work."""
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    try:
        return pcfg.resolve_active_profile(
            pcfg.list_profiles(root),
            env_value=os.environ.get("RACECAST_PROFILE"),
            pointer=pcfg.read_active_pointer(_runtime_base_dir()))
    except pcfg.ProfileError:
        return None

def _runtime_dir():
    return _profile_runtime(_runtime_base_dir(), _active_profile_name())
```

- [ ] **Step 4: Point `profile_cmd`'s pointer at the base (not the profile-scoped dir)**

In `src/iro.py` `profile_cmd`, find this exact line:

```python
    runtime_root = _runtime_dir()
```

Replace it with:

```python
    runtime_root = _runtime_base_dir()   # the active-profile pointer is un-scoped
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS` (includes `ok t_profile_runtime_scoping`).

> Verify no regression in the existing profile commands:
> ```bash
> python3 src/iro.py profile new t1 && python3 src/iro.py profile use t1 && python3 src/iro.py profile list
> rm -rf profiles/t1 runtime/active-profile
> ```
> Expected: `t1` created, `active profile: t1`, list shows `* t1`. The pointer is written at `runtime/active-profile` (base), not under `runtime/t1/`.

- [ ] **Step 6: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): profile-scoped runtime dir (pointer stays at base)"
```

---

### Task 2: inject the active profile's league config into the child env

**Files:**
- Modify: `src/iro.py` (`_profile_env_vars`, `_apply_active_profile_env`, `main`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_iro.py`:

```python
def t_profile_env_vars_filters_empty():
    rc = m.pcfg.ResolvedConfig(
        profile="iro", name="IRO", sheet_id="abc",
        sheet_push_url="", intro_url="https://i", outro_url="")
    assert m._profile_env_vars(rc) == {
        "RACECAST_SHEET_ID": "abc", "RACECAST_INTRO_URL": "https://i"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `AttributeError: ... has no attribute '_profile_env_vars'`.

- [ ] **Step 3: Write minimal implementation**

In `src/iro.py`, find the `_runtime_dir()` function you created in Task 1 and insert these two functions immediately AFTER it:

```python
def _profile_env_vars(rc):
    """The league values from a ResolvedConfig to push into the child env, as a
    dict of the non-empty ones. These are exactly what the relay / one-shots /
    probes read (RACECAST_SHEET_ID etc.)."""
    pairs = (("RACECAST_SHEET_ID", rc.sheet_id),
             ("RACECAST_SHEET_PUSH_URL", rc.sheet_push_url),
             ("RACECAST_INTRO_URL", rc.intro_url),
             ("RACECAST_OUTRO_URL", rc.outro_url))
    return {k: v for k, v in pairs if v}

def _apply_active_profile_env():
    """Resolve the active profile and inject its league values into os.environ so
    every downstream consumer (relay daemon, one-shots, event probes) inherits
    them. Tolerant: no profile -> no-op. Returns the profile name or None."""
    name = _active_profile_name()
    if not name:
        return None
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    try:
        rc = pcfg.resolve_config(root, override=name,
                                 runtime_root=_runtime_base_dir())
    except pcfg.ProfileError:
        return None
    os.environ.update(_profile_env_vars(rc))
    return name
```

- [ ] **Step 4: Call it in `main()`**

In `src/iro.py` `main()`, find this exact block:

```python
    if _profile:
        os.environ["RACECAST_PROFILE"] = _profile   # M3 consumers read this
```

Insert immediately AFTER it:

```python
    _apply_active_profile_env()   # inject the active profile's sheet config for children
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): inject active profile's sheet config into child env"
```

---

### Task 3: rename the league-config env reads to RACECAST_* across the consumers

The CLI now injects `RACECAST_*`; the self-contained scripts must read those names (the four LEAGUE vars only — machine vars `IRO_OBS_WS_PASSWORD`/`IRO_COMPANION_EXE`/`IRO_UI_PORT` stay until M5).

**Files:**
- Modify: `src/relay/iro-feeds.py`, `src/setup-assets.py`, `src/relay/get-graphics.py`, `src/relay/get-media.py`, `src/scripts/preflight.py`, `src/iro.py`
- Test: the `tests/` rename sweep

- [ ] **Step 1: relay (`src/relay/iro-feeds.py`)**

Find:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID for the schedule/POV tabs. Default: env "
                         "IRO_SHEET_ID (or a .env at the repo/package root). See .env.example.")
```
Replace with:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID for the schedule/POV tabs. Default: env "
                         "RACECAST_SHEET_ID (injected by the CLI from the active profile).")
```

Find:
```python
    push_url = os.environ.get("IRO_SHEET_PUSH_URL")
    # Race timer: local file always; sheet sync derived from sheet-id/tab
    # (custom --sheet-csv-url -> local-only); push via IRO_SHEET_PUSH_URL.
```
Replace with:
```python
    push_url = os.environ.get("RACECAST_SHEET_PUSH_URL")
    # Race timer: local file always; sheet sync derived from sheet-id/tab
    # (custom --sheet-csv-url -> local-only); push via RACECAST_SHEET_PUSH_URL.
```

Find:
```python
        mode = "writes ON" if push_url else "read-only (set IRO_SHEET_PUSH_URL)"
```
Replace with:
```python
        mode = "writes ON" if push_url else "read-only (set RACECAST_SHEET_PUSH_URL)"
```

Find:
```python
            "sheet read-only (set IRO_SHEET_PUSH_URL for handover sync)"
```
Replace with:
```python
            "sheet read-only (set RACECAST_SHEET_PUSH_URL for handover sync)"
```

- [ ] **Step 2: setup-assets (`src/setup-assets.py`)**

Find:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID injected into the HUD browser source. "
                         "Default: env IRO_SHEET_ID (or .env). See .env.example.")
```
Replace with:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID injected into the HUD browser source. "
                         "Default: env RACECAST_SHEET_ID (from the active profile).")
```

Find:
```python
            sys.exit(f"ERROR: the collection references the HUD sheet ({SHEET_TOKEN}) but no "
                     "Sheet ID is set. Add IRO_SHEET_ID to .env at the repo/package root "
                     "(see .env.example) or pass --sheet-id.")
```
Replace with:
```python
            sys.exit(f"ERROR: the collection references the HUD sheet ({SHEET_TOKEN}) but no "
                     "Sheet ID is set. Set SHEET_ID in the active profile "
                     "(profiles/<name>/profile.env) or pass --sheet-id.")
```

- [ ] **Step 3: get-graphics (`src/relay/get-graphics.py`)**

Find:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env IRO_SHEET_ID.")
```
Replace with:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env RACECAST_SHEET_ID.")
```

- [ ] **Step 4: get-media (`src/relay/get-media.py`)**

Find:
```python
    """Resolve a URL per key in `which` (a set of 'intro'/'outro').
    Priority: cli[key]  >  env['IRO_<KEY>_URL']  >  sheet label lookup.
    `csv_text` may be None (sheet not fetched)."""
```
Replace with:
```python
    """Resolve a URL per key in `which` (a set of 'intro'/'outro').
    Priority: cli[key]  >  env['RACECAST_<KEY>_URL']  >  sheet label lookup.
    `csv_text` may be None (sheet not fetched)."""
```

Find:
```python
        out[key] = (cli.get(key) or env.get(f"IRO_{key.upper()}_URL") or sheet.get(key))
```
Replace with:
```python
        out[key] = (cli.get(key) or env.get(f"RACECAST_{key.upper()}_URL") or sheet.get(key))
```

Find:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env IRO_SHEET_ID.")
```
Replace with:
```python
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env RACECAST_SHEET_ID.")
```

Find:
```python
    need_sheet = any(not (cli.get(k) or os.environ.get(f"IRO_{k.upper()}_URL")) for k in which)
```
Replace with:
```python
    need_sheet = any(not (cli.get(k) or os.environ.get(f"RACECAST_{k.upper()}_URL")) for k in which)
```

- [ ] **Step 5: preflight (`src/scripts/preflight.py`)**

Find:
```python
    sheet_id = os.environ.get("IRO_SHEET_ID")
```
Replace with:
```python
    sheet_id = os.environ.get("RACECAST_SHEET_ID")
```

- [ ] **Step 6: iro.py event + asset probes**

Find:
```python
    rows = ev.fetch_assets_rows(gg, os.environ.get("IRO_SHEET_ID"))
```
Replace with:
```python
    rows = ev.fetch_assets_rows(gg, os.environ.get("RACECAST_SHEET_ID"))
```

Find:
```python
    config = [ev.classify_env(os.environ.get("IRO_SHEET_ID"),
                              os.environ.get("IRO_SHEET_PUSH_URL"))]
```
Replace with:
```python
    config = [ev.classify_env(os.environ.get("RACECAST_SHEET_ID"),
                              os.environ.get("RACECAST_SHEET_PUSH_URL"))]
```

Also, in the `_asset_state` docstring, find:
```python
    Note: get-graphics' load_dotenv also fills IRO_* env vars for repo/package
    modes (frozen already loaded .env next to the binary at startup)."""
```
Replace with:
```python
    Note: the CLI injects RACECAST_SHEET_ID from the active profile before this
    runs (get-graphics' load_dotenv still fills machine vars from .env)."""
```

- [ ] **Step 7: rename sweep across the tests**

Run this to find every remaining LEAGUE-var reference in the tests:
```bash
grep -rn "IRO_SHEET_ID\|IRO_SHEET_PUSH_URL\|IRO_INTRO_URL\|IRO_OUTRO_URL\|IRO_{.*}_URL\|IRO_INTRO\|IRO_OUTRO" tests/
```
For EACH hit in the test files, rename the token to its `RACECAST_` equivalent (`IRO_SHEET_ID`→`RACECAST_SHEET_ID`, `IRO_SHEET_PUSH_URL`→`RACECAST_SHEET_PUSH_URL`, `IRO_INTRO_URL`→`RACECAST_INTRO_URL`, `IRO_OUTRO_URL`→`RACECAST_OUTRO_URL`, and any `IRO_{key}_URL` f-string →`RACECAST_{key}_URL`). Do NOT touch `IRO_OBS_WS_PASSWORD`, `IRO_COMPANION_EXE`, or `IRO_UI_PORT` (machine vars, renamed in M5).

Then confirm nothing league-related is left in src/ either:
```bash
grep -rn "IRO_SHEET_ID\|IRO_SHEET_PUSH_URL\|IRO_INTRO_URL\|IRO_OUTRO_URL" src/
```
Expected: no hits (only the machine vars + the `__IRO_*__` OBS tokens, which are NOT these names, remain).

- [ ] **Step 8: Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS`. If a test fails because it set `IRO_SHEET_ID` in its own environment to drive a probe, that is exactly a Step-7 hit — rename it and re-run.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: read league sheet config from RACECAST_* (CLI-injected from profile)"
```

---

### Task 4: point the asset one-shots at the profile runtime in every run mode

The asset writers (`graphics`/`media`/`setup`) previously got profile-redirected `--out` only when frozen; in repo mode they used their own `runtime/` defaults. Now the CLI always points them at `runtime/<profile>/`, and the asset-dir probe matches.

**Files:**
- Modify: `src/iro.py` (`_oneshot_extra`, `_oneshot_code`, `_asset_dirs`, `_asset_state`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_iro.py`:

```python
def t_oneshot_extra_points_assets_at_profile_runtime():
    rd = os.path.join("R", "iro")
    assert m._oneshot_extra("graphics", [], rd) == [
        "--out", os.path.join(rd, "graphics")]
    assert m._oneshot_extra("media", [], rd) == [
        "--out", os.path.join(rd, "media")]
    assert m._oneshot_extra("setup", [], rd) == [
        "--out", os.path.join(rd, "IRO_Endurance.import.json"),
        "--media", os.path.join(rd, "media"),
        "--graphics", os.path.join(rd, "graphics")]
    assert m._oneshot_extra("cookies", [], rd) == ["--runtime-dir", rd]
    assert m._oneshot_extra("graphics", ["--out", "X"], rd) == []   # user override respected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: FAIL — the current `_oneshot_extra` takes 4 args `(command, rest, frozen, runtime_dir)`, so the 3-arg call raises `TypeError`.

- [ ] **Step 3: Rewrite `_oneshot_extra`**

In `src/iro.py`, find the entire current function:

```python
def _oneshot_extra(command, rest, frozen, runtime_dir):
    """Extra argv for a one-shot. --runtime-dir where the script supports it (see
    RUNTIME_DIR_ONESHOTS); when frozen, also redirect default locations away from
    the throwaway _MEIPASS unpack dir (unless the user passed the flag himself):
    --out for the writers, and setup's --media/--graphics — those are INJECTED
    into the OBS collection as absolute paths and must outlive the process."""
    extra = []
    if command in RUNTIME_DIR_ONESHOTS:
        extra += ["--runtime-dir", runtime_dir]
    if frozen and "--out" not in rest:
        out = {"graphics": os.path.join(runtime_dir, "graphics"),
               "media": os.path.join(runtime_dir, "media"),
               "setup": os.path.join(runtime_dir, "IRO_Endurance.import.json")}.get(command)
        if out:
            extra += ["--out", out]
    if frozen and command == "setup":
        for flag, sub in (("--media", "media"), ("--graphics", "graphics")):
            if flag not in rest:
                extra += [flag, os.path.join(runtime_dir, sub)]
    return extra
```

Replace it with:

```python
def _oneshot_extra(command, rest, runtime_dir):
    """Extra argv for a one-shot: --runtime-dir where the script supports it (see
    RUNTIME_DIR_ONESHOTS), and the profile-scoped output locations for the asset
    writers (--out, plus setup's --media/--graphics — those are baked into the
    OBS collection as absolute paths, so they must point at THIS profile's
    runtime dir in every run mode, not just frozen). The user's own --out wins."""
    extra = []
    if command in RUNTIME_DIR_ONESHOTS:
        extra += ["--runtime-dir", runtime_dir]
    if "--out" not in rest:
        out = {"graphics": os.path.join(runtime_dir, "graphics"),
               "media": os.path.join(runtime_dir, "media"),
               "setup": os.path.join(runtime_dir, "IRO_Endurance.import.json")}.get(command)
        if out:
            extra += ["--out", out]
    if command == "setup":
        for flag, sub in (("--media", "media"), ("--graphics", "graphics")):
            if flag not in rest:
                extra += [flag, os.path.join(runtime_dir, sub)]
    return extra
```

- [ ] **Step 4: Update the caller**

In `src/iro.py` `_oneshot_code`, find:

```python
    extra = _oneshot_extra(command, rest, IS_FROZEN, _runtime_dir())
```

Replace with:

```python
    extra = _oneshot_extra(command, rest, _runtime_dir())
```

- [ ] **Step 5: Make `_asset_dirs` profile-scoped in every mode**

In `src/iro.py`, find the entire current function:

```python
def _asset_dirs(gg, gm):
    """Where `iro graphics`/`iro media` put files in THIS run mode. Frozen:
    the oneshot injection redirects to runtime/ (see _oneshot_extra); repo and
    package follow the scripts' own defaults (runtime/ vs. package root)."""
    if IS_FROZEN:
        return (os.path.join(_runtime_dir(), "graphics"),
                os.path.join(_runtime_dir(), "media"))
    return (gg.graphics_dir(os.path.dirname(os.path.abspath(gg.__file__))),
            gm.media_dir(os.path.dirname(os.path.abspath(gm.__file__))))
```

Replace it with:

```python
def _asset_dirs():
    """Where `iro graphics`/`iro media` write: always the active profile's
    runtime dir (the one-shot injection points --out there in every run mode --
    see _oneshot_extra)."""
    return (os.path.join(_runtime_dir(), "graphics"),
            os.path.join(_runtime_dir(), "media"))
```

Then update its caller in `_asset_state`. Find:

```python
    g_dir, m_dir = _asset_dirs(gg, gm)
```

Replace with:

```python
    g_dir, m_dir = _asset_dirs()
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`.

> If `tests/test_iro.py` had a pre-existing `_oneshot_extra(...)` test using the old 4-arg signature, update that call to drop the `frozen`/`IS_FROZEN` argument (now 3 args) and re-run.

- [ ] **Step 7: Run the full gate**

Run:
```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: `ALL TEST FILES PASS`, lint clean, build verify passes.

- [ ] **Step 8: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(cli): point asset one-shots + asset probe at the profile runtime"
```

---

### Task 5: end-to-end profile-separation smoke test

**Files:** none modified — this verifies the whole M3a chain.

- [ ] **Step 1: Create two throwaway profiles with distinct sheet ids**

Run from the repo root:
```bash
python3 src/iro.py profile new alpha
python3 src/iro.py profile new beta
printf 'NAME=Alpha\nSHEET_ID=ALPHASHEET\n' > profiles/alpha/profile.env
printf 'NAME=Beta\nSHEET_ID=BETASHEET\n'  > profiles/beta/profile.env
```

- [ ] **Step 2: Build the OBS import for each profile and verify isolation**

Run:
```bash
python3 src/iro.py --profile alpha setup
python3 src/iro.py --profile beta  setup
echo "--- alpha import contains ALPHASHEET:" ; grep -c ALPHASHEET runtime/alpha/IRO_Endurance.import.json
echo "--- alpha import contains BETASHEET (should be 0):" ; grep -c BETASHEET runtime/alpha/IRO_Endurance.import.json
echo "--- beta import contains BETASHEET:" ; grep -c BETASHEET runtime/beta/IRO_Endurance.import.json
ls -d runtime/alpha runtime/beta
```
Expected:
- `runtime/alpha/IRO_Endurance.import.json` and `runtime/beta/IRO_Endurance.import.json` both exist (proves profile-scoped `--out` in repo mode).
- alpha's import contains `ALPHASHEET` (count > 0) and NOT `BETASHEET` (count 0); beta's contains `BETASHEET` — proving the active profile's sheet id flowed end-to-end (profile.env -> RACECAST_SHEET_ID -> setup-assets) and the two leagues are isolated.

- [ ] **Step 3: Confirm the active-profile pointer stayed at the base**

Run:
```bash
python3 src/iro.py profile use alpha
test -f runtime/active-profile && echo "pointer at base: OK"
test ! -e runtime/alpha/active-profile && echo "no pointer under profile dir: OK"
```
Expected: both `OK` lines.

- [ ] **Step 4: Clean up**

Run:
```bash
rm -rf profiles/alpha profiles/beta runtime/alpha runtime/beta runtime/active-profile
git status --short
```
Expected: working tree clean (all created files were gitignored under `profiles/*` and `runtime/`).

- [ ] **Step 5: Final gate + commit (docs only, if anything)**

Run `python3 tools/run-tests.py` once more → `ALL TEST FILES PASS`. No code commit needed for this task (verification only); if the smoke test surfaced a bug, fix it under the relevant earlier task's files and commit there.

---

## Self-Review

**Spec coverage (M3, the M3a slice):**
- "runtime/<profile>/ scoping (graphics/media/timer/PID/obs-pages.hash/import json)" → Task 1 (`_runtime_dir` profile-scoped; everything derived from it follows) + Task 4 (asset `--out`). ✅
- "consumers read SHEET_ID from the active profile" → Task 2 (inject) + Task 3 (rename reads). ✅
- "setup-assets writes to runtime/<profile>/" → Task 4 (`--out` always profile). ✅
- "cookies shared" → **deviated** to profile-scoped (Scope Decision 1; flagged to the user). 
- "token rename __RACECAST_*__" → **deferred to M5** (Scope Decision 2).
- "profile-aware init wizard" + "OBS collection switch tie-in" → **M3b** (Scope Decision 4).

**Placeholder scan:** the only non-literal step is Task 3 Step 7 (a `grep` rename sweep across tests) — this is a precise, enumerated token list with an explicit exclusion set, not a vague "handle the rest", so it complies.

**Type/name consistency:** `_runtime_base_dir`, `_profile_runtime`, `_active_profile_name`, `_runtime_dir`, `_profile_env_vars`, `_apply_active_profile_env`, `_oneshot_extra` (now 3-arg), `_asset_dirs` (now 0-arg) — names used identically across tasks and at their call sites (`profile_cmd`, `main`, `_oneshot_code`, `_asset_state`). `pcfg` is the iro.py alias for `config` (from M2); `m.pcfg.ResolvedConfig` in the test resolves it. The injected var names (`RACECAST_SHEET_ID`/`_PUSH_URL`/`_INTRO_URL`/`_OUTRO_URL`) match exactly between `_profile_env_vars` (Task 2) and every read renamed in Task 3.

---

## CI Gate (must stay green at end of M3a)

- `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- `python3 tools/lint.py` → clean
- `python3 tools/build.py` → verify passes
- Smoke test (Task 5) proves two profiles produce isolated, correctly-keyed OBS imports under their own `runtime/<profile>/`.
- Untouched in M3a: `init_setup.py`, `_init_env_run`, `REQUIRED_ENV`, `.env.example`, the `__IRO_*__` OBS tokens, the machine vars (`IRO_OBS_WS_PASSWORD`/`IRO_COMPANION_EXE`/`IRO_UI_PORT`), the `iro` binary name.
