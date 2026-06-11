# M5b — De-brand part 2: `iro` → `racecast` binary, CLI command & entrypoint files

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product's executable identity from `iro` to `racecast` — the entrypoint files, the two binaries (`racecast` + `racecast-ui`), every CLI command-name string operators see, and the internal product identifiers — leaving league/domain names, build/CI artifact names, and docs untouched.

**Architecture:** Mechanical, grep-driven rename across `src/` + `tools/` + `tests/`, in four lockstep slices that each keep the test suite + lint green, then a gate. This is the third slice of the de-brand (M5a did env vars / OBS tokens / collection name; M5c does build/CI artifact names; M6 does docs + repo rename).

**Tech Stack:** Pure Python 3.11+ stdlib. Tests are runnable scripts (`python3 tests/test_X.py`); gate is `python3 tools/run-tests.py` + `python3 tools/lint.py` + `python3 tools/build.py`.

---

## Scope boundaries (read before starting)

**IN scope (rename `iro` → `racecast`):**
- Entrypoint/config FILES: `src/iro.py`, `src/iro_ui.py`, `src/relay/iro-feeds.py`, `src/companion/iro-buttons.companionconfig`.
- Binary names: `iro` → `racecast`, `iro-ui` → `racecast-ui`.
- CLI command-name strings in `src/**/*.py`: usage blocks, module docstrings, and operator-PRINTED messages (e.g. `not running — \`iro relay start\``).
- Internal product identifiers: `APP_ID = "iro-control-center"`, User-Agent `"iro-feeds/1.0"`, the runtime default companionconfig basename `iro-buttons.companionconfig`.

**OUT of scope — do NOT touch:**
- `src/docs/**` (operator guides, cheat sheets, wiki) → **M6**.
- `README.md`, `CLAUDE.md` → **M6**.
- `.github/workflows/release.yml` + `preview.yml` archive/artifact names, `IRO_Broadcast_Package` (in `tools/build.py`) → **M5c**. (These never run on this PR's CI, so leaving them on `iro`/`IRO_Broadcast_Package` keeps the PR green.)
- The **league/domain** name `"IRO Endurance"` and profile-fixture `NAME=` values → intentionally kept (IRO is a real league; domain data, not product branding).
- The OBS scene-collection product name `"GT Endurance Racing"` → already done in M5a; do not re-touch.
- Internal **Python symbol names** (function names like `_iro_job_executable`, `_relay_script`; importlib module nicknames like `"irofeeds"`/`"iro_feeds"`). These are invisible to operators — renaming them is pure churn and diff noise. Change their STRING/PATH **values** only, not the identifiers.

**Exclusion grep guard** (used to verify a sweep didn't catch a forbidden token):
```
grep -RIn -e "iro" <files> | grep -iv \
  -e "IRO Endurance" -e "IRO_Broadcast" -e "IRO_Endurance" \
  -e "GT Endurance" -e "environ" -e "_iro_job_executable" -e "irofeeds" -e "iro_feeds"
```

---

## File Structure

| File | Change |
|---|---|
| `src/iro.py` → `src/racecast.py` | `git mv` + internal path/basename refs |
| `src/iro_ui.py` → `src/racecast_ui.py` | `git mv` + `import` of the main module |
| `src/relay/iro-feeds.py` → `src/relay/racecast-feeds.py` | `git mv` |
| `src/companion/iro-buttons.companionconfig` → `src/companion/racecast-buttons.companionconfig` | `git mv` |
| `tools/build.py`, `tools/build-binary.py`, `tools/strip_companion_pass.py`, `tools/fetch-flags.py` | path/basename/entry/name refs |
| `tests/test_*.py` (≈10 files) | importlib PATH args + string assertions |
| `src/ui/ui_server.py` | `APP_ID` value |
| `src/**/*.py` (≈21 files) | CLI command-name strings |

---

## Task 1: Rename the four entrypoint/config files + fix every path & basename reference

**Goal:** The four files move to their `racecast` names and every PATH / basename string that points at them is updated, so the suite + lint stay green. Binary `--name` stays `iro`/`iro-ui` (Task 2) and command-name help strings stay `iro` (Task 3) for now — this task is purely about file paths.

**Files:**
- Rename (git mv): `src/iro.py`→`src/racecast.py`, `src/iro_ui.py`→`src/racecast_ui.py`, `src/relay/iro-feeds.py`→`src/relay/racecast-feeds.py`, `src/companion/iro-buttons.companionconfig`→`src/companion/racecast-buttons.companionconfig`
- Modify: `src/racecast.py`, `src/racecast_ui.py`, `tools/build.py`, `tools/build-binary.py`, `tools/strip_companion_pass.py`, `tools/fetch-flags.py`
- Modify (tests): `tests/test_setup.py`, `tests/test_cookies.py`, `tests/test_pov.py`, `tests/test_bind.py`, `tests/test_health.py`, `tests/test_stint.py`, `tests/test_timer.py`, `tests/test_hud.py`, `tests/test_iro.py`, plus any other test loading these by path (grep to confirm)

- [ ] **Step 1: Move the files with git mv (preserves history)**

```bash
cd /Users/jegr/Downloads/IRO_Broadcast_Setup
git mv src/iro.py src/racecast.py
git mv src/iro_ui.py src/racecast_ui.py
git mv src/relay/iro-feeds.py src/relay/racecast-feeds.py
git mv src/companion/iro-buttons.companionconfig src/companion/racecast-buttons.companionconfig
```

- [ ] **Step 2: Find every test/tool that loads a renamed file by path (so none is missed)**

```bash
grep -RIn -e "iro-feeds.py" -e "iro_ui.py" -e "src/iro.py" -e "iro-buttons.companionconfig" \
  tests tools src | grep -v "/docs/"
```
Expected: the callsites listed in Steps 3–6. Treat anything extra as another edit.

- [ ] **Step 3: Update relay-script path references in `src/racecast.py`**

In `src/racecast.py`:
- `_relay_script()` (≈line 444): `os.path.join(HERE, "relay", "iro-feeds.py")` → `...,"relay","racecast-feeds.py"`.
- `_script_invocation` callsite (≈line 892): `_run_script("relay/iro-feeds.py", ...)` → `"relay/racecast-feeds.py"`.
- companionconfig source (≈line 1610): `resource_path("companion/iro-buttons.companionconfig")` → `"companion/racecast-buttons.companionconfig"`.
- runtime default OUTPUT basename (≈lines 1606, 1608, 2318): `"iro-buttons.companionconfig"` → `"racecast-buttons.companionconfig"`.

- [ ] **Step 4: Update `src/racecast_ui.py`'s import of the main module**

`src/racecast_ui.py` imports the main entrypoint (`import iro` / `from iro import ...` — grep it). Rename that import to the new module name `racecast` (e.g. `import racecast` / `racecast.run_ui(...)`). In frozen + dev both load by module name, so the import statement must match the new filename. Grep `src/racecast_ui.py` for `iro` and update the import + any `iro.<attr>` references; leave its prose/docstring command-name (`iro ui`) for Task 3.

- [ ] **Step 5: Update tool path references**

- `tools/build.py`:
  - relay copy comment (≈line 51): `# iro-feeds.py + get-cookies.py` → racecast-feeds.py (comment, cosmetic but update).
  - companionconfig read/write paths (≈lines 81, 84, 122): `"companion","iro-buttons.companionconfig"` → `"...racecast-buttons.companionconfig"`.
  - relay file read for token assert (≈line 118): `os.path.join(PKG,"relay","iro-feeds.py")` → `"...racecast-feeds.py"`.
- `tools/build-binary.py`:
  - `build_target(... entry="iro.py" ...)` (≈line 113): entry `"iro.py"` → `"racecast.py"`.
  - `build_target(... entry="iro_ui.py" ...)` (≈line 115): entry `"iro_ui.py"` → `"racecast_ui.py"`.
  - smoke temp basename (≈line 207): `dst = os.path.join(td, "iro-buttons.companionconfig")` → `"racecast-buttons.companionconfig"` (cosmetic temp path).
  - Leave the `name="iro"`/`"iro-ui"` args and `.app` paths for Task 2; leave `iro-control-center` ping checks for Task 4.
- `tools/strip_companion_pass.py`:
  - `DEFAULT_IN`/`DEFAULT_OUT` (≈lines 15, 16) basenames `iro-buttons.companionconfig` → `racecast-buttons.companionconfig`; update the docstring path lines (5, 6) to match (these are maintainer-tool comments, not shipped operator docs).
- `tools/fetch-flags.py`:
  - importlib load PATH (≈line 47): `os.path.join(ROOT,"src","relay","iro-feeds.py")` → `"...racecast-feeds.py"`. (Leave the `"irofeeds"` nickname and the `User-Agent` for Task 4.)

- [ ] **Step 6: Update every test that loads a renamed file by path**

In each of `tests/test_setup.py`, `tests/test_cookies.py`, `tests/test_pov.py`, `tests/test_bind.py`, `tests/test_health.py`, `tests/test_stint.py`, `tests/test_timer.py`, `tests/test_hud.py`: change the importlib PATH arg `os.path.join(ROOT,"src","relay","iro-feeds.py")` → `"...racecast-feeds.py"`. **Keep the module-nickname** first arg (`"irofeeds"`/`"iro_feeds"`) as-is.

In `tests/test_iro.py`:
- ≈line 262: `m._script_invocation("relay/iro-feeds.py", ...)` → `"relay/racecast-feeds.py"`.
- ≈line 265: assertion `path == os.path.join("MEI","src","relay","iro-feeds.py")` → `"...racecast-feeds.py"`.
- ≈line 272: `repo[1].endswith("iro-feeds.py")` → `endswith("racecast-feeds.py")`.
- ≈line 376: `out = os.path.join(td,"runtime","iro-buttons.companionconfig")` → `"racecast-buttons.companionconfig"`.
- Also confirm how `test_iro.py` loads the main module (grep for `iro.py`/`src/iro.py`/`"iro"`): update that load PATH to `src/racecast.py`. Keep the in-memory module nickname symbol as-is.

Also grep `tests` for any OTHER loader of `src/iro.py`/`src/iro_ui.py` (e.g. `test_ui_*`, `test_native_dialog`, `test_event`, `test_init`, `test_profile`) and update the PATH to the new filename:
```bash
grep -RIn -e "src.*iro\.py" -e "src.*iro_ui\.py" tests
```

- [ ] **Step 7: Run the suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: ALL TEST FILES PASS / All checks passed. If a test fails on a path it loads, that path was missed in Step 6 — fix and re-run.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(m5b): rename entrypoint/config files iro->racecast (paths only)"
```

---

## Task 2: Rename the two binaries `iro`→`racecast`, `iro-ui`→`racecast-ui`

**Goal:** PyInstaller produces `dist/bin/racecast` + `dist/bin/racecast-ui` (`.exe`/`.app` per OS), the Control-Center server's job spawner finds the sibling `racecast` binary, and the build-binary smoke (the only binary CI on PRs) stays green. `release.yml`/`preview.yml` archive names stay `iro-*` (M5c) — they don't run on this PR.

**Files:**
- Modify: `tools/build-binary.py`, `src/racecast.py`
- Test: `tests/test_iro.py` (the `_iro_job_executable` unit test, if it asserts the literal name)

- [ ] **Step 1: Update `_iro_job_executable` sibling-binary name in `src/racecast.py`**

≈line 2462: `return _app_home(executable) + sep + ("iro.exe" if win else "iro")` → `("racecast.exe" if win else "racecast")`. Update the function's docstring references to the sibling binary (`iro`/`iro-ui`) to `racecast`/`racecast-ui` (≈lines 2451–2454) — these are code comments, not operator docs. **Keep the function name `_iro_job_executable`** (internal symbol).

- [ ] **Step 2: Update the unit test if it asserts the literal binary name**

```bash
grep -n "iro\.exe\|\"iro\"\|'iro'\|job_executable" tests/test_iro.py
```
For any assertion on the produced name (e.g. `endswith("iro")`/`"iro.exe"`), change to `racecast`/`racecast.exe`. (The function-name symbol `_iro_job_executable` stays.)

- [ ] **Step 3: Update binary `--name` values + macOS `.app` paths in `tools/build-binary.py`**

- `build_target(... "iro.py", "iro", windowed=False)` (≈line 113): name `"iro"` → `"racecast"`.
- `build_target(... "iro_ui.py", "iro-ui", windowed=True)` (≈line 115): name `"iro-ui"` → `"racecast-ui"`. (Entry filenames were already updated in Task 1 to `racecast.py`/`racecast_ui.py`.)
- macOS `.app` smoke path (≈lines 122–124): `"iro-ui.app"` → `"racecast-ui.app"`, inner exe `"Contents","MacOS","iro-ui"` → `"...","racecast-ui"`.
- Docstring/usage (≈lines 2–7): update `iro`/`iro-ui` → `racecast`/`racecast-ui` (maintainer-tool comment).
- `tempfile.mkdtemp(prefix="iro-build-")` (≈line 107): cosmetic, may update to `"racecast-build-"`.
- Leave the `iro-control-center` ping checks (≈lines 161, 241) for Task 4.

- [ ] **Step 4: Run the suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: green. (The PyInstaller binary smoke runs in CI's `binary-smoke` job — driven entirely by `build-binary.py` internals just edited, which return the new binary paths, so it stays name-coherent. Do NOT attempt to run PyInstaller locally unless it is already installed.)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(m5b): rename binaries iro/iro-ui -> racecast/racecast-ui"
```

---

## Task 3: Rename CLI command-name strings `iro `→`racecast ` across `src/**/*.py`

**Goal:** Every place the code prints or documents the command name `iro` (usage blocks, docstrings, operator-facing printed hints like `not running — \`iro relay start\``) now says `racecast`, so the renamed binary's own output is self-consistent. No `src/docs/` (M6), no league/package names.

**Files (≈21, grep to confirm):** `src/racecast.py`, `src/racecast_ui.py`, `src/ui/ui_ops.py`, `src/ui/ui_jobs.py`, `src/scripts/update.py`, `src/scripts/event.py`, `src/scripts/companion_common.py`, `src/scripts/installer_common.py`, `src/scripts/install_tools.py`, `src/scripts/install_apps.py`, `src/scripts/stop-streams.py`, `src/scripts/profile_admin.py`, `src/scripts/native_dialog.py`, `src/scripts/start-streams.py`, `src/scripts/tailscale.py`, `src/scripts/preflight.py`, `src/relay/get-cookies.py`, `src/scripts/loopstream.py`, `src/relay/racecast-feeds.py`, `src/scripts/init_setup.py`, `src/scripts/obs_ws.py`
- Test: `tests/test_iro.py` (+ any test asserting usage/help substrings — grep)

- [ ] **Step 1: Survey the exact occurrences**

```bash
grep -RIn -e "\biro \b" -e "iro_ui" -e "python3 src/iro" src --include="*.py" \
  | grep -v "/docs/" | grep -iv "IRO Endurance\|IRO_Broadcast\|IRO_Endurance"
```
Read each hit and classify: command-name string (rename) vs. something inside an excluded token (skip). Most are `iro <subcommand>` in usage/docstrings/printed messages.

- [ ] **Step 2: Rewrite command-name strings to `racecast`**

Replace the command token `iro ` → `racecast ` in:
- `src/racecast.py` usage block (≈lines 4–23): `python3 src/iro.py` → `python3 src/racecast.py`; every `iro <subcommand>` → `racecast <subcommand>`.
- The `_USAGE`/`prog=`/printed-hint strings across the script modules (e.g. `init_setup.py` `_USAGE = "usage: iro init ..."` and its `\`iro init\`` retry hints; `event.py` `\`iro relay start\``/`\`iro obs collection set\``/`\`iro companion start\``/`\`iro event start\`` etc.; `install_apps.py`/`install_tools.py` `\`iro install-* --update\``; `update.py`, `profile_admin.py`, `obs_ws.py`, `tailscale.py`, `preflight.py`, `get-cookies.py`, `loopstream.py`, `companion_common.py`, `native_dialog.py`, `ui_ops.py`, `ui_jobs.py` docstrings/messages).
- `src/racecast_ui.py` docstring `iro ui` → `racecast ui`.

Do NOT touch: `IRO Endurance` (league), `IRO_Broadcast_Package` (M5c), env-var names (already `RACECAST_*`), `_iro_job_executable`, importlib nicknames.

- [ ] **Step 3: Update test assertions on usage/help text**

```bash
grep -RIn "iro " tests/test_iro.py tests/test_init.py tests/test_profile.py tests/test_ui_ops.py | grep -iv "IRO Endurance"
```
For any assertion checking a usage/help/printed substring (e.g. `"usage: iro init" in ...`, `"iro relay start" in out`), update to `racecast`. Keep importlib nicknames + league names.

- [ ] **Step 4: Run the suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: green. Fix any string-assertion mismatch surfaced.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(m5b): rename CLI command-name strings iro -> racecast (src code only)"
```

---

## Task 4: Rename internal product identifiers (ping signature, User-Agent, temp basename)

**Goal:** The internal "this is our product" magic strings become `racecast`, in lockstep across producer + consumer + smoke + tests, so nothing silently mismatches.

**Files:**
- Modify: `src/ui/ui_server.py`, `src/relay/racecast-feeds.py`, `tools/fetch-flags.py`, `tools/build-binary.py`
- Test: `tests/test_ui_server.py` (references `us.APP_ID` by symbol — value change is safe; confirm no literal `"iro-control-center"` is hardcoded)

- [ ] **Step 1: Rename the Control-Center ping signature `APP_ID`**

- `src/ui/ui_server.py` ≈line 11: `APP_ID = "iro-control-center"` → `APP_ID = "racecast-control-center"`.
- `tools/build-binary.py` ≈lines 161 & 241: both `if b"iro-control-center" not in body:` → `b"racecast-control-center"`. Update the adjacent failure-message strings (`"smoke iro-ui FAILED"` / `"smoke ui FAILED"` mention the signature) for consistency.
- Confirm `tests/test_ui_server.py` uses `us.APP_ID` (symbol) — no literal to change. The negative test `classify_ping(b'{"app": "something-else"}')` stays.

- [ ] **Step 2: Rename the relay User-Agent**

In `src/relay/racecast-feeds.py` (≈lines 487, 568, 830, 945): `"User-Agent": "iro-feeds/1.0"` → `"racecast-feeds/1.0"` (4 occurrences). In `tools/fetch-flags.py` (≈line 54): `"User-Agent": "iro-feeds/1.0"` → `"racecast-feeds/1.0"`.

- [ ] **Step 3: Verify no internal-identifier stragglers remain**

```bash
grep -RIn -e "iro-control-center" -e "iro-feeds/1.0" src tools tests
```
Expected: no output.

- [ ] **Step 4: Run the suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(m5b): rename internal identifiers (ping APP_ID, relay User-Agent)"
```

---

## Task 5: Gate — full suite, lint, build, straggler audit

**Goal:** Prove the whole M5b slice is coherent: suite + lint + producer build all green, and no in-scope `iro` executable/command leakage remains outside the deliberately-kept tokens.

**Files:** none (verification only).

- [ ] **Step 1: Full suite + lint + producer build**

```bash
python3 tools/run-tests.py     # expect: ALL TEST FILES PASS
python3 tools/lint.py          # expect: All checks passed
python3 tools/build.py         # expect: exit 0, verify passes
```

- [ ] **Step 2: Confirm the renamed files exist and the old names are gone**

```bash
ls src/racecast.py src/racecast_ui.py src/relay/racecast-feeds.py src/companion/racecast-buttons.companionconfig
! ls src/iro.py src/iro_ui.py src/relay/iro-feeds.py src/companion/iro-buttons.companionconfig 2>/dev/null
```
Expected: the four `racecast` files listed; the four `iro` files absent.

- [ ] **Step 3: Straggler audit (in-scope leakage only)**

```bash
# command-name / entrypoint / binary leakage in CODE (not docs, not the kept tokens)
grep -RIn -e "\biro " -e "iro-feeds" -e "iro_ui" -e "iro-buttons" -e "iro-control-center" \
  src tools tests --include="*.py" \
  | grep -v "/docs/" \
  | grep -iv "IRO Endurance\|IRO_Broadcast\|IRO_Endurance\|_iro_job_executable\|irofeeds\|iro_feeds"
```
Expected: no output. Any hit is either a real miss (fix it) or a deliberately-kept token (confirm it matches the OUT-of-scope list, otherwise fix). Note: `IRO_Broadcast_Package` (build.py) and `release.yml`/`preview.yml` `iro-*.zip` are **expected** to remain — they are M5c.

- [ ] **Step 4: Report** the gate results (suite/lint/build exit codes + straggler-audit output) to the controller. No commit (verification only).
