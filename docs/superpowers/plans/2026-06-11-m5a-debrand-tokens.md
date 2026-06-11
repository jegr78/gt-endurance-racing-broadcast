# M5a — De-brand: env vars + OBS tokens + collection name/file Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First slice of the de-brand sweep — rename the machine env-var prefix `IRO_` → `RACECAST_`, the OBS placeholder tokens `__IRO_*__` → `__RACECAST_*__`, the default OBS scene-collection name `"IRO Endurance"` → `"GT Endurance Racing"`, and the source collection file `src/obs/IRO_Endurance.json` → `src/obs/GT_Endurance.json` — each in lockstep across all producers/consumers, keeping the full suite and `tools/build.py` verify green.

**Architecture:** These are mechanical, lockstep renames across tightly-coupled files (the OBS collection JSON + its three consumers `setup-assets.py`/`tokenize-obs.py`/`build.py`, the `obs_ws`/`config` constants, and the machine `.env` plumbing). There is no behavior change — only identifiers/strings move. The integration safety net is `tools/build.py`'s verify step (it asserts the tokenized collection contains the literal token strings) plus the full test suite. This is the "data/token layer" of the de-brand; the `iro`→`racecast` binary/CLI rename is M5b, build/CI artifact names are M5c.

**Tech Stack:** Pure Python 3.11+ stdlib. Tests are stdlib runnable scripts (`python3 tests/test_X.py`). `tools/build.py` is the integration verifier.

**Locked decisions (with Jens, 2026-06-11):**
- Default collection name → **"GT Endurance Racing"**.
- Source collection file → **`src/obs/GT_Endurance.json`** (ships as `GT_Endurance.template.json`).
- **Clean break, no `IRO_*` compatibility shim** — drop the old names entirely.
- Machine vars to rename: `IRO_OBS_WS_PASSWORD`, `IRO_COMPANION_EXE`, `IRO_UI_PORT`, `IRO_UI_PASSWORD` → `RACECAST_*`. (League vars were already renamed to `RACECAST_*` in M3 — none should remain.)
- OBS tokens to rename: `__IRO_GRAPHICS__`, `__IRO_SHEET__`, `__IRO_MEDIA__`, `__IRO_ASSETS__`, `__IRO_TIMER__` → `__RACECAST_*__`.

**Out of scope (later milestones):** the `iro`→`racecast` command/binary/entrypoint-file renames (M5b); build/CI artifact + package names like `IRO_Broadcast_Package` (M5c); the wiki var/command de-brand and README/CLAUDE.md (M6) — EXCEPT doc lines that name the renamed JSON *path*, which this plan updates so no reference dangles.

**Migration note:** changing the default collection name means a producer who already imported the old "IRO Endurance" collection re-imports (setup-assets writes the new name); the per-profile `OBS_COLLECTION` override (M3c) still wins. Renaming the *source* template file does not touch any already-imported OBS collection.

---

### Task 1: Machine env-var prefix `IRO_` → `RACECAST_`

**Files (confirm via grep — do not trust this list as complete):**
- Modify: `src/scripts/obs_ws.py`, `src/ui/ui_server.py`, `src/iro.py`, `src/scripts/companion_common.py`, `tools/build-binary.py`, `.env.example`
- Tests: any of `tests/test_*.py` that reference these four vars
- Out of scope here: `src/docs/wiki/*` (M6)

**The four renames (clean break, no fallback):**
| old | new |
|---|---|
| `IRO_OBS_WS_PASSWORD` | `RACECAST_OBS_WS_PASSWORD` |
| `IRO_COMPANION_EXE` | `RACECAST_COMPANION_EXE` |
| `IRO_UI_PORT` | `RACECAST_UI_PORT` |
| `IRO_UI_PASSWORD` | `RACECAST_UI_PASSWORD` |

- [ ] **Step 1: Enumerate every occurrence**

```bash
grep -rInE "\bIRO_(OBS_WS_PASSWORD|COMPANION_EXE|UI_PORT|UI_PASSWORD)\b" src tools tests .env.example
```
This is the authoritative work-list. (Wiki under `src/docs/wiki/` is M6 — if grep shows hits there, LEAVE them.)

- [ ] **Step 2: Rename each occurrence (code + tests + .env.example)**

Replace each `IRO_<NAME>` with `RACECAST_<NAME>` in every non-wiki file from Step 1. Includes: the `os.environ.get(...)`/`getenv` reads, the `.env.example` keys + the commented example lines (`# IRO_COMPANION_EXE=…`, `# IRO_UI_PASSWORD=…`), docstrings/comments that name the var, and any test that sets/asserts the var. Do NOT add a compatibility fallback (locked: clean break).

- [ ] **Step 3: Verify no stray machine-var references remain (outside wiki)**

```bash
grep -rInE "\bIRO_(OBS_WS_PASSWORD|COMPANION_EXE|UI_PORT|UI_PASSWORD)\b" src tools tests .env.example
```
Expected: ZERO hits (everything moved). Also confirm no league straggler:
```bash
grep -rInE "\bIRO_(SHEET_ID|SHEET_PUSH_URL|INTRO_URL|OUTRO_URL)\b" src tools tests
```
Expected: ZERO (M3 already moved these; if any appear, rename them to `RACECAST_*` too and note it).

- [ ] **Step 4: Run suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: ALL TEST FILES PASS · lint clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(debrand): rename machine env vars IRO_* -> RACECAST_*"
```

---

### Task 2: OBS placeholder tokens `__IRO_*__` → `__RACECAST_*__`

**Files (lockstep — all must change together):**
- `src/obs/IRO_Endurance.json` (the token strings inside sources/settings — NOTE the file itself is renamed in Task 3; here only edit its *contents*)
- `src/setup-assets.py` (constants `ASSETS_TOKEN`/`SHEET_TOKEN`/`MEDIA_TOKEN`/`GRAPHICS_TOKEN` lines ~11-14; the regex line ~192 `__IRO_GRAPHICS__/...`; docstrings/help lines ~3, ~142, ~145)
- `tools/tokenize-obs.py` (constants `TOKEN`/`SHEET_TOKEN` lines ~12-13; the `f.startswith("__IRO_")` guard line ~83; docstrings lines ~2, ~5, ~56)
- `tools/build.py` (token assertions lines ~128, ~131, ~135, ~137; regex line ~164)
- Tests: `tests/test_standby.py`, `tests/test_discord_audio.py`, and any other token-referencing test
- CONFIRM there are no other consumers: `grep -rIn "__IRO_" src tools tests` must, after this task, return ZERO.

**The five token renames:**
| old | new |
|---|---|
| `__IRO_GRAPHICS__` | `__RACECAST_GRAPHICS__` |
| `__IRO_SHEET__` | `__RACECAST_SHEET__` |
| `__IRO_MEDIA__` | `__RACECAST_MEDIA__` |
| `__IRO_ASSETS__` | `__RACECAST_ASSETS__` |
| `__IRO_TIMER__` | `__RACECAST_TIMER__` |

**CRITICAL lockstep:** `tools/build.py`'s verify asserts the *served* template still contains the literal token strings (`"obs graphics tokenized": "__IRO_GRAPHICS__/" in tpl`, the `__IRO_TIMER__ not in tpl` check, `"obs media tokenized": "__IRO_MEDIA__/"`, and the graphics-ref regex at ~164). If the JSON tokens change but `build.py` still checks `__IRO_*__`, the build verify FAILS. They MUST change together.

- [ ] **Step 1: Enumerate**

```bash
grep -rIn "__IRO_" src tools tests
```
This is the work-list (the `prefix.startswith("__IRO_")` guard in tokenize-obs.py becomes `"__RACECAST_"`).

- [ ] **Step 2: Rename all five tokens everywhere**

Replace each `__IRO_X__` → `__RACECAST_X__` across all files from Step 1: the JSON token strings, the Python constants, the two regexes (`setup-assets.py:192`, `build.py:164`), the `startswith` guard, the `build.py` assertion literals, the docstrings/help text, and the tests. Keep the regex structure identical — only the literal token prefix changes (e.g. `r"__IRO_GRAPHICS__/([^\"\\]+\.png)"` → `r"__RACECAST_GRAPHICS__/([^\"\\]+\.png)"`).

- [ ] **Step 3: Verify zero stragglers**

```bash
grep -rIn "__IRO_" src tools tests          # expect 0
grep -rIn "__RACECAST_" src tools tests | wc -l   # sanity: should match the old count
```

- [ ] **Step 4: Suite + lint + BUILD VERIFY (the real integration gate)**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: ALL TEST FILES PASS · lint clean · build verify passes with the token checks now green (`[OK] obs graphics tokenized`, `[OK] obs media tokenized`, `[OK] obs no raw sheet url`). Graphics/media "missing file" warnings are expected, not failures. If build verify reports a token check `[FAIL]`, a `__IRO_*__`/`__RACECAST_*__` mismatch remains between the JSON and `build.py` — fix the lockstep.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(debrand): rename OBS tokens __IRO_*__ -> __RACECAST_*__"
```

---

### Task 3: Collection name → "GT Endurance Racing" + rename `IRO_Endurance.json` → `GT_Endurance.json`

**Files (lockstep — collection identity):**
- `src/obs/IRO_Endurance.json` → **rename to** `src/obs/GT_Endurance.json`, AND change its top-level `"name": "IRO Endurance"` → `"name": "GT Endurance Racing"`.
- `src/scripts/obs_ws.py`: `EXPECTED_SCENE_COLLECTION = "IRO Endurance"` → `"GT Endurance Racing"`; update the comment (line ~43) that names `src/obs/IRO_Endurance.json` → `src/obs/GT_Endurance.json`.
- `tools/tokenize-obs.py`: `CANONICAL_COLLECTION_NAME = "IRO Endurance"` → `"GT Endurance Racing"`; update the comment (line ~26) naming the JSON path.
- `src/setup-assets.py`: the template-discovery tuple (line ~156) `("IRO_Endurance.template.json", "IRO_Endurance.json")` → `("GT_Endurance.template.json", "GT_Endurance.json")`.
- `src/iro.py`: `resource_path("obs/IRO_Endurance.json")` (line ~2360) → `resource_path("obs/GT_Endurance.json")`.
- `tools/build.py`: lines ~89-90 copy `IRO_Endurance.json` → `IRO_Endurance.template.json`; change source to `GT_Endurance.json` and dest to `GT_Endurance.template.json`; line ~116 verify-read of `IRO_Endurance.template.json` → `GT_Endurance.template.json`.
- `src/director/director-panel.html`: comment (line ~272) naming `src/obs/IRO_Endurance.json` → `src/obs/GT_Endurance.json`.
- `src/docs/wiki/Build-and-maintenance.md` (line ~78) and `src/docs/wiki/OBS-Setup.md` (line ~29): update the `src/obs/IRO_Endurance.json` *path* in those commands so the rename leaves no dangling path. (This is the ONLY wiki edit in M5a — the broader wiki de-brand is M6.)
- Tests: `tests/test_discord_audio.py` (line ~92 builds the path `src/obs/IRO_Endurance.json`), and every test asserting the collection name `"IRO Endurance"` — `tests/test_obsws.py`, `tests/test_event.py`, `tests/test_ui_server.py`, `tests/test_iro.py`, `tests/test_discord_audio.py` (grep to find all).

- [ ] **Step 1: Enumerate both the name and the path**

```bash
grep -rIn "IRO Endurance" src tools tests          # the collection display name
grep -rIn "IRO_Endurance" src tools tests           # the file path (json/template)
```
These two lists are the work-list.

- [ ] **Step 2: Rename the file with git (preserve history)**

```bash
git mv src/obs/IRO_Endurance.json src/obs/GT_Endurance.json
```

- [ ] **Step 3: Change the collection name + every path reference**

- In `src/obs/GT_Endurance.json`: top-level `"name"` → `"GT Endurance Racing"`.
- Replace `"IRO Endurance"` → `"GT Endurance Racing"` in the two constants (`obs_ws.EXPECTED_SCENE_COLLECTION`, `tokenize-obs.CANONICAL_COLLECTION_NAME`) and in every test that asserts the name (fake-OBS `current_collection`/`collections` lists, expected-name asserts, event-classifier fixtures, etc. — use the Step 1 `"IRO Endurance"` list).
- Replace the file path `IRO_Endurance.json`/`IRO_Endurance.template.json` → `GT_Endurance.json`/`GT_Endurance.template.json` everywhere from the Step 1 `IRO_Endurance` list (setup-assets discovery tuple, iro.py resource_path, build.py copy+verify, director-panel comment, the two wiki path mentions, test_discord_audio path, obs_ws/tokenize comments).

- [ ] **Step 4: Verify zero stragglers**

```bash
grep -rIn "IRO Endurance" src tools tests     # expect 0
grep -rIn "IRO_Endurance" src tools tests      # expect 0
ls src/obs/                                     # GT_Endurance.json present, IRO_Endurance.json gone
```

- [ ] **Step 5: Suite + lint + build verify**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: ALL TEST FILES PASS · lint clean · build verify passes. The build copies `GT_Endurance.json` → `GT_Endurance.template.json` and its verify-read + token checks pass. Confirm the build log shows the obs checks `[OK]` (not skipped/failed) and that `dist/IRO_Broadcast_Package/obs/GT_Endurance.template.json` exists (the package dir name is still `IRO_Broadcast_Package` until M5c — that's expected here).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(debrand): rename collection to 'GT Endurance Racing' + GT_Endurance.json"
```

---

### Task 4: Milestone gate

**Files:** none (verification only)

- [ ] **Step 1: Full suite + lint + build**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # clean
python3 tools/build.py         # verify passes (graphics/media warnings expected)
```

- [ ] **Step 2: Global straggler sweep for this milestone's scope**

```bash
grep -rInE "\bIRO_(OBS_WS_PASSWORD|COMPANION_EXE|UI_PORT|UI_PASSWORD)\b" src tools tests .env.example   # 0
grep -rIn "__IRO_" src tools tests                                                                       # 0
grep -rIn "IRO Endurance" src tools tests                                                                # 0
grep -rIn "IRO_Endurance" src tools tests                                                                # 0
```
All four must be ZERO. (Remaining `iro`/`IRO` hits elsewhere — the binary name, `IRO_Broadcast_Package`, wiki branding — are M5b/M5c/M6 scope, not failures here.)

- [ ] **Step 3: Commit any gate fix (only if needed)**

```bash
git add -A && git commit -m "test(m5a): de-brand token/var/collection gate green"
```

---

## Self-Review

**Spec coverage:**
- Machine env vars `IRO_*`→`RACECAST_*` → Task 1 (the 4 machine vars; league vars already done in M3, re-checked).
- OBS tokens `__IRO_*__`→`__RACECAST_*__` → Task 2 (5 tokens across JSON + setup-assets + tokenize-obs + build.py + tests; the build.py assertion literals are called out as the lockstep trap).
- Collection name → "GT Endurance Racing" + file rename → Task 3 (constants + JSON name + `git mv` + every path ref incl. the two wiki path mentions so nothing dangles).

**Placeholder scan:** These are renames, so the plan specifies exact old→new mappings + exhaustive `grep` work-lists + zero-straggler assertions rather than reproducing every line — appropriate for a mechanical lockstep rename. Every grep that must return 0 is stated.

**Lockstep risks flagged:** (1) `build.py` token assertions/regex must move with the JSON tokens (Task 2 — else build verify fails). (2) The collection-name constants in `obs_ws.py` AND `tokenize-obs.py` must match the JSON `name` (Task 3 — a mismatch breaks `iro obs collection` checks and `t_canonicalize_name`). (3) The file rename must update setup-assets discovery, iro.py resource_path, build.py copy+verify, and the test path-builder together (Task 3). The full suite + `tools/build.py` verify after each task is the integration net.

**Consistency:** new names used identically — `RACECAST_OBS_WS_PASSWORD`/`_COMPANION_EXE`/`_UI_PORT`/`_UI_PASSWORD`; `__RACECAST_GRAPHICS__`/`_SHEET__`/`_MEDIA__`/`_ASSETS__`/`_TIMER__`; `"GT Endurance Racing"`; `src/obs/GT_Endurance.json` → `GT_Endurance.template.json`. The package dir `IRO_Broadcast_Package` and the `iro` binary/command are deliberately untouched here (M5c/M5b).
