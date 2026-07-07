# Rebrand to "GT Racing Broadcast" Implementation Plan (#308)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product/umbrella from "GT Endurance Racing Broadcast" → "GT Racing Broadcast", with endurance and solo as two symmetric modes underneath, as a clean rename with no legacy aliases.

**Architecture:** A branding sweep across constants, committed OBS template files (renamed on disk), maintainer tools, docs/wiki, decks, and UI text. The endurance feed/relay behaviour is untouched — only strings and filenames change. Work on `feat/308-rebrand` (off `epic/300-solo-mode`); the PR targets the epic branch.

**Tech Stack:** Python 3 (stdlib only), plain HTML/JS, Markdown. Tests are stdlib runnable scripts (no pytest); run one file with `python3 tests/test_X.py`.

## Global Constraints

- **Canonical new strings (use verbatim):** umbrella = `GT Racing Broadcast`; endurance collection prefix + base = `GT Racing Endurance`; localized endurance = `GT Racing Endurance — <league>`; solo prefix = `GT Racing Solo` (already correct, do NOT change).
- **Clean rename — NO legacy aliases, fallbacks, or old-name auto-detection.** Do not add any code that recognises the old `GT Endurance Racing` collection.
- **Endurance feed/relay path stays byte-identical.** The renamed endurance template's scene graph must be identical to today's — only its top-level `name` field changes. No existing test is commented out or disabled.
- **Unchanged (do NOT touch):** repo name `gt-endurance-racing-broadcast`; CLI name `racecast`; the HTTP `User-Agent`.
- **Excluded from the text sweep:** `docs/superpowers/**` (historical design records — including THIS plan and the spec) and `CHANGELOG.md` (generated). Never rewrite those for branding.
- **Edit only under `src/`, plus the repo-root docs the issue names** (`README.md`, `CONTRIBUTING.md`, `CLAUDE.md`) and the maintainer tools (`tools/build.py`, `tools/tokenize-obs.py`, `tools/derive-solo-templates.py`). Never edit `dist/`/`runtime/`.
- **All scripts and docs are English only.**
- Run `python3 tools/lint.py` after any Python edit.

---

### Task 1: Collection-name constants + obs_ws logic

**Files:**
- Modify: `src/scripts/config.py` (module docstring line 2; `PRODUCT_COLLECTION_PREFIX` line 25; the two explanatory comments at lines 23-27)
- Modify: `src/scripts/obs_ws.py` (`EXPECTED_SCENE_COLLECTION` line 50; the docstring reference to `"GT Endurance Racing*"` around lines 57-58)
- Test: `tests/test_obsws.py`, `tests/test_config.py`, `tests/test_racecast.py`

**Interfaces:**
- Produces: `config.PRODUCT_COLLECTION_PREFIX == "GT Racing Endurance"`, `obs_ws.EXPECTED_SCENE_COLLECTION == "GT Racing Endurance"`. `config.SOLO_COLLECTION_PREFIX` stays `"GT Racing Solo"`. Later tasks rely on these exact strings.

- [ ] **Step 1: Update the failing test assertions (they will now fail against the old constants)**

In `tests/test_obsws.py`, replace every literal `GT Endurance Racing` with `GT Racing Endurance` (this includes the renamed-variant cases: `GT Endurance Racing 2` → `GT Racing Endurance 2`). Do NOT change the `ERF Endurance` string on line 662 — it is a deliberate non-matching example. Concretely the affected lines are: 649, 650, 654, 656, 682, 686, 691, 692, 714, 835, 836, 837, 842, 850, 853, 854, 860, 861, 869, 870, 873, 899, 900, 904, 905, 909, 921, 922, 924.

In `tests/test_config.py`, lines 302/311/319/388: `GT Endurance Racing — …` → `GT Racing Endurance — …`. Leave line 379 (`GT Racing Solo — My League`) unchanged.

In `tests/test_racecast.py`, lines 3580/3607/3635: `"GT Endurance Racing — demo"` → `"GT Racing Endurance — demo"`.

- [ ] **Step 2: Run the tests to verify they FAIL**

Run: `python3 tests/test_obsws.py && python3 tests/test_config.py`
Expected: FAIL — assertions expect `GT Racing Endurance` but the constants still say `GT Endurance Racing`.

- [ ] **Step 3: Flip the constants + comments**

`src/scripts/config.py`:
- Line 2 docstring: `GT Endurance Racing Broadcast` → `GT Racing Broadcast`.
- Line 25: `PRODUCT_COLLECTION_PREFIX = "GT Racing Endurance"`.
- Update the comment block (lines 23-27) so it reads that endurance profiles group under `GT Racing Endurance` and solo under `GT Racing Solo` (both now unified under `GT Racing <MODE>`); drop the "#308 later unifies" future-tense note (it is now done).

`src/scripts/obs_ws.py`:
- Line 50: `EXPECTED_SCENE_COLLECTION = "GT Racing Endurance"`.
- In the `scene_collection_status` docstring, change the example family `"GT Endurance Racing*"` / `'GT Endurance Racing 2'` to `"GT Racing Endurance*"` / `'GT Racing Endurance 2'`.

- [ ] **Step 4: Run the tests to verify they PASS**

Run: `python3 tests/test_obsws.py && python3 tests/test_config.py && python3 tests/test_racecast.py`
Expected: PASS (all three).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/config.py src/scripts/obs_ws.py tests/test_obsws.py tests/test_config.py tests/test_racecast.py
git commit -m "refactor(brand): rename endurance collection constant to GT Racing Endurance (#308)"
```

---

### Task 2: Rename the committed OBS template files + all references

**Files:**
- Rename: `src/obs/GT_Endurance.json` → `src/obs/GT_Racing_Endurance.json` (top-level `name` field also changes)
- Rename: `src/obs/GT_Solo_Commentary.json` → `src/obs/GT_Racing_Solo_Commentary.json`
- Rename: `src/obs/GT_Solo_POV.json` → `src/obs/GT_Racing_Solo_POV.json`
- Modify: `tools/derive-solo-templates.py` (lines 3, 5 docstring; 59 `OUTPUTS`; 143 input path)
- Modify: `tools/build.py` (lines 131-138, 167, 254)
- Modify: `tools/tokenize-obs.py` (line 27 comment; the `CANONICAL_COLLECTION_NAME = "GT Endurance Racing"` constant at line 30)
- Modify: `src/setup-assets.py` (lines 26, 31, 35, 36, 283)
- Modify: `src/scripts/placeholders.py` (line 21)
- Modify: `src/racecast.py` (`_setup_import_name` lines 549-552; the STANDBY_SCENE comment line 866; any other `GT_Endurance` reference)
- Test: `tests/test_build.py`, `tests/test_solo_obs.py`, `tests/test_placeholders.py`, `tests/test_discord_audio.py`, `tests/test_intermission_scene.py`, `tests/test_overlay.py`, `tests/test_racecast.py`, `tests/test_event.py`, `tests/test_ui_server.py`, `tests/test_ui_ops.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly.
- Produces: the renamed template stems used by later readers: endurance stem `GT_Racing_Endurance`, solo stems `GT_Racing_Solo_Commentary` / `GT_Racing_Solo_POV`; runtime import names `GT_Racing_Endurance.import.json` / `GT_Racing_Solo.import.json`; dist template names `GT_Racing_Endurance.template.json` / `GT_Racing_Solo_*.template.json`.

- [ ] **Step 1: Git-move the three template files**

```bash
# from the repo root
git mv src/obs/GT_Endurance.json src/obs/GT_Racing_Endurance.json
git mv src/obs/GT_Solo_Commentary.json src/obs/GT_Racing_Solo_Commentary.json
git mv src/obs/GT_Solo_POV.json src/obs/GT_Racing_Solo_POV.json
```

- [ ] **Step 2: Change the endurance template's top-level `name` field**

In `src/obs/GT_Racing_Endurance.json`, the root-level `"name": "GT Endurance Racing"` → `"name": "GT Racing Endurance"`. This is the ONLY content change to this file. (Source-item `name`s such as `Feed A`, `Stint` are unrelated and must not change.)

- [ ] **Step 3: Verify the endurance rename is byte-identical except the name line**

Run:
```bash
diff <(git show HEAD:src/obs/GT_Endurance.json) src/obs/GT_Racing_Endurance.json
```
Expected: exactly one hunk — the single top-level `"name"` line changing from `GT Endurance Racing` to `GT Racing Endurance`. Any other diff line means the scene graph was altered — revert and redo Step 2.

- [ ] **Step 4: Update `tools/derive-solo-templates.py` and regenerate the solo files**

- Line 3 docstring: `src/obs/GT_Endurance.json` → `src/obs/GT_Racing_Endurance.json`.
- Line 5 docstring: `src/obs/GT_Solo_*.json` → `src/obs/GT_Racing_Solo_*.json`.
- Line 59: `OUTPUTS = ("GT_Racing_Solo_Commentary.json", "GT_Racing_Solo_POV.json")`.
- Line 143: open `os.path.join(OBS, "GT_Racing_Endurance.json")`.

Then regenerate and confirm the git-moved solo files are unchanged by the derivation:
```bash
python3 tools/derive-solo-templates.py
git diff --stat src/obs/GT_Racing_Solo_Commentary.json src/obs/GT_Racing_Solo_POV.json
```
Expected: no diff (the deterministic derivation reproduces the git-moved files byte-for-byte; the solo `name` field was already `GT Racing Solo`).

- [ ] **Step 5: Update `tools/build.py`**

- Line 131-132: copy `src/obs/GT_Racing_Endurance.json` → `PKG/obs/GT_Racing_Endurance.template.json`.
- Line 135 loop: `for solo in ("GT_Racing_Solo_Commentary.json", "GT_Racing_Solo_POV.json"):`.
- Line 167: open `PKG/obs/GT_Racing_Endurance.template.json`.
- Line 254 loop: `for solo in ("GT_Racing_Solo_Commentary.template.json", "GT_Racing_Solo_POV.template.json"):`.

- [ ] **Step 6: Update `tools/tokenize-obs.py`**

- Line 27 comment: `src/obs/GT_Endurance.json` → `src/obs/GT_Racing_Endurance.json`.
- Line 30: `CANONICAL_COLLECTION_NAME = "GT Racing Endurance"` (this is the collection `name`
  that `tokenize-obs` stamps when folding an exported OBS collection back into the source
  template — it MUST match the new top-level `name` set in Step 2, or a re-tokenize would
  silently revert the rename).

- [ ] **Step 7: Update `src/setup-assets.py`**

- Line 26: `SOLO_TEMPLATE_FILES = {"commentary": "GT_Racing_Solo_Commentary", "pov": "GT_Racing_Solo_POV"}`.
- Lines 31/35 docstring + default: `resolve_template_base` returns `"GT_Racing_Solo_Commentary"` for the solo-default branch and `"GT_Racing_Endurance"` at line 36.
- Line 283: `--out` default → `os.path.join(base, "obs", "GT_Racing_Endurance.import.json")`.

- [ ] **Step 8: Update `src/scripts/placeholders.py`**

Line 21: `_OBS_TEMPLATE_NAMES = ("GT_Racing_Endurance.template.json", "GT_Racing_Endurance.json")`.

- [ ] **Step 9: Update `src/racecast.py`**

- `_setup_import_name` (lines 549-552): docstring mentions and the returns become `"GT_Racing_Solo.import.json"` (solo) / `"GT_Racing_Endurance.import.json"` (endurance/unknown).
- Line 866 comment (STANDBY_SCENE): `src/obs/GT_Endurance.json` → `src/obs/GT_Racing_Endurance.json`.
- Line 3787 comment: `GT_Solo_Commentary/GT_Solo_POV` → `GT_Racing_Solo_Commentary/GT_Racing_Solo_POV`.
- Grep `src/racecast.py` for any remaining `GT_Endurance`/`GT_Solo` and update.

- [ ] **Step 10: Update the tests to the new filenames**

- `tests/test_build.py`: line 14 `GT_Endurance.json` → `GT_Racing_Endurance.json`; line 199 loop → `("GT_Racing_Solo_Commentary.json", "GT_Racing_Solo_POV.json")`.
- `tests/test_solo_obs.py`: lines 21-26 `resolve_template_base` expectations → `GT_Racing_Endurance` / `GT_Racing_Solo_Commentary` / `GT_Racing_Solo_POV`; line 96 `SOLO_FILES` → `("GT_Racing_Solo_Commentary.json", "GT_Racing_Solo_POV.json")`; line 167 `_load_solo("GT_Racing_Solo_Commentary.json")`.
- `tests/test_placeholders.py`: lines 53-56 → `GT_Racing_Endurance.json` / `GT_Racing_Endurance.template.json`.
- `tests/test_discord_audio.py`: line 117 path → `GT_Racing_Endurance.json`; line 147 comment; the collection-`name` fixtures + assertions on lines 125/131/133/135 (`"GT Endurance Racing"` → `"GT Racing Endurance"`) and line 142 (`tk.CANONICAL_COLLECTION_NAME == "GT Racing Endurance"`).
- `tests/test_intermission_scene.py`: line 20 path → `GT_Racing_Endurance.json`; line 50 message text.
- `tests/test_overlay.py`: lines 535/547/587 path → `GT_Racing_Endurance.json`.
- `tests/test_racecast.py`: lines 446/450/461/467/875/890/902 `GT_Endurance.import.json` → `GT_Racing_Endurance.import.json`; lines 894/907 `GT_Solo.import.json` → `GT_Racing_Solo.import.json`; lines 924-941 `_setup_import_name`/`_init_import_json` expectations → the new names; line 3787 comment.
- `tests/test_event.py`: the scene-collection fixtures on lines 289-330 — replace every `"GT Endurance Racing"` with `"GT Racing Endurance"` and every `"GT Endurance Racing 2"` with `"GT Racing Endurance 2"` (these are the classifier `current`/`expected`/`available`/`renamed_variant` fixture values).
- `tests/test_ui_server.py`: lines 110 and 380 — `"GT Endurance Racing"` → `"GT Racing Endurance"`.
- `tests/test_ui_ops.py`: lines 992-993 — `"GT Endurance Racing"` → `"GT Racing Endurance"`.

- [ ] **Step 11: Run the affected tests**

Run:
```bash
python3 tests/test_solo_obs.py && python3 tests/test_placeholders.py && \
python3 tests/test_discord_audio.py && python3 tests/test_intermission_scene.py && \
python3 tests/test_overlay.py && python3 tests/test_racecast.py && python3 tests/test_build.py && \
python3 tests/test_event.py && python3 tests/test_ui_server.py && python3 tests/test_ui_ops.py
```
Expected: PASS (all).

- [ ] **Step 12: Build to verify the dist path end-to-end**

Run: `python3 tools/build.py`
Expected: exit 0 (its verify step reads `GT_Racing_Endurance.template.json` and asserts the tokenized/secret-free artifact).

- [ ] **Step 13: Lint + commit**

```bash
python3 tools/lint.py
git add -A
git commit -m "refactor(brand): rename OBS template files to GT_Racing_* (#308)"
```

---

### Task 3: Docs + wiki text sweep

**Files:**
- Modify: `README.md`, `CONTRIBUTING.md`, `CLAUDE.md` (descriptive product-name text only)
- Modify: `src/docs/README_SETUP.md`, `src/docs/Broadcast_Setup_Guide.md`
- Modify: `src/docs/wiki/*.md` (the pages found: `Home.md`, `_Sidebar.md`, `Configuration.md`, `Set-up-the-broadcast-PC.md`, `HUD-Overlays.md`, `OBS-Setup.md`, `Profiles.md`, `Build-and-maintenance.md`, `Cloud-Producer.md`)
- Test: `tests/test_wiki.py`

**Interfaces:**
- Consumes: the canonical strings from Global Constraints.
- Produces: docs that name the umbrella `GT Racing Broadcast` and the endurance collection `GT Racing Endurance`.

- [ ] **Step 1: Sweep each file, choosing the replacement per occurrence**

This is NOT a blind find/replace — read each occurrence and pick:
- `GT Endurance Racing Broadcast` (the umbrella/product) → `GT Racing Broadcast`.
- `GT Endurance Racing` that names the **OBS scene collection** (e.g. "switch OBS to the GT Endurance Racing collection", "GT Endurance Racing — <league>") → `GT Racing Endurance`.
- `GT Endurance Racing` used **generically for the product** in prose → `GT Racing Broadcast` (or `GT Racing` where the sentence reads better as the short brand).
- Filenames in docs: `GT_Endurance.json` → `GT_Racing_Endurance.json`; `GT_Solo_*.json` → `GT_Racing_Solo_*.json`; `.import.json` names likewise.
- README line 1 heading `# GT Endurance Racing Broadcast — Repository` → `# GT Racing Broadcast — Repository`; line 3 → `GT Racing broadcast producer station`.
- CLAUDE.md line 7 `**GT Endurance Racing Broadcast**` → `**GT Racing Broadcast**`. Do NOT alter CLAUDE.md hard-rule *mechanics* — only the product-name phrase.

Do not touch `docs/superpowers/**` or `CHANGELOG.md`.

- [ ] **Step 2: Add the one-time migration note to the OBS-Setup wiki page**

In `src/docs/wiki/OBS-Setup.md`, add a short note near the collection-import section:

```markdown
> **Renamed in the rebrand (#308):** the endurance scene collection is now
> **"GT Racing Endurance — <league>"** (was "GT Endurance Racing — <league>").
> Existing installs: run `racecast setup` once to regenerate the import file,
> import it into OBS, then delete the old "GT Endurance Racing — <league>"
> collection. There is no automatic rename.
```

- [ ] **Step 3: Run the wiki link/anchor test**

Run: `python3 tests/test_wiki.py`
Expected: PASS. If a renamed heading broke an inbound anchor, fix the link (or restore the heading text) until green.

- [ ] **Step 4: Confirm no unintended endurance-brand leaks remain in the swept docs**

Run:
```bash
grep -rn "GT Endurance Racing" README.md CONTRIBUTING.md CLAUDE.md src/docs/*.md src/docs/wiki/*.md
```
Expected: the ONLY remaining hits are the intentional old-name mention inside the migration note (Step 2). Everything else must be gone.

- [ ] **Step 5: Commit**

```bash
git add README.md CONTRIBUTING.md CLAUDE.md src/docs/README_SETUP.md src/docs/Broadcast_Setup_Guide.md src/docs/wiki
git commit -m "docs(brand): rebrand docs + wiki to GT Racing Broadcast, add OBS-collection migration note (#308)"
```

---

### Task 4: UI text (Control Center + Director Panel)

> **Controller note (subagent-driven):** the implementer for this task edits the HTML text ONLY. Rendering, the `ui-visual-verify` gate marker, and any wiki-screenshot refresh are performed by the controller after this task (the subagent cannot drive Playwright or the Stop gate). See the controller checklist below the task.

**Files:**
- Modify: `src/ui/control-center.html` (line 1875 confirm string; line 2220 comment; sweep for any other brand strings)
- Modify: `src/director/director-panel.html` (line 30 `<title>`; line 1471 dynamic-title ternary; lines 796/861 comments; sweep for any other brand strings)

**Interfaces:**
- Consumes: the canonical strings.
- Produces: no code interface; user-facing strings only.

- [ ] **Step 1: Control Center**

- Line 1875: `'obs-collection-set': 'Switch OBS to the GT Racing Endurance scene collection? …'` (replace `GT Endurance Racing` → `GT Racing Endurance`).
- Line 2220 comment: `GT Racing Endurance collection is present to switch to.`
- Grep `src/ui/control-center.html` for `GT Endurance Racing` and `GT Endurance Racing Broadcast`; replace remaining collection refs with `GT Racing Endurance` and umbrella refs with `GT Racing Broadcast`.

- [ ] **Step 2: Director Panel**

- Line 30 `<title>`: `GT Racing · Director Console` (was `GT Endurance Racing · Director Console`).
- Line 1471 ternary: the endurance-branch title string → `"GT Racing · Director Console"`. Read the surrounding ternary; if a solo-branch title already exists, leave it; only the endurance branch changes.
- Lines 796/861 comments: update the `src/obs/GT_Endurance.json` filename reference → `src/obs/GT_Racing_Endurance.json`; the `GT Racing Solo` mention on 861 is already correct.
- Grep the file for any remaining `GT Endurance Racing` and replace per the same rules.

- [ ] **Step 3: Run the UI/route tests (no functional change expected)**

Run: `python3 tests/test_ui_server.py && python3 tests/test_racecast.py`
Expected: PASS (these don't assert the brand strings, but confirm nothing broke).

- [ ] **Step 4: Commit**

```bash
git add src/ui/control-center.html src/director/director-panel.html
git commit -m "refactor(brand): rebrand Control Center + Director Panel UI strings (#308)"
```

**Controller checklist AFTER Task 4 (not the implementer):**
- Render both surfaces from a local dev build per the `ui-visual-verification` skill (Control Center via `racecast ui` on a free port; Director Panel via the demo relay + obs-sim).
- Eyeball: the changed strings appear correctly; no layout regressions. The changed strings (confirm dialog, browser-tab title, comments) are NOT in the standing `cc-*.png`/`director-panel.png` element screenshots — so a wiki-screenshot refresh is expected to be UNNECESSARY. Confirm by comparing; only regenerate a committed image if its pixels actually changed.
- Record the gate marker: `python3 .claude/hooks/record_ui_verified.py src/ui/control-center.html src/director/director-panel.html`.

---

### Task 5: Slides / decks text sweep

**Files:**
- Modify: `src/docs/slides/*.html` (`index.html`, `director.html`, `league-admin-setup.html`, `race-control.html`, `commentator.html`, `overlay-designer.html`, `producer.html`, `walkthrough-thumb.html`, `producer-setup.html`, `walkthrough-intro.html`, `cheat_sheets.html`)
- Modify: `src/docs/slides/favicon.svg` (any brand-text label)

**Interfaces:**
- Consumes: the canonical strings.
- Produces: decks that read `GT Racing Broadcast` / `GT Racing`.

- [ ] **Step 1: Sweep each deck file**

- `GT Endurance Racing Broadcast` → `GT Racing Broadcast`.
- `GT Endurance Racing` used as the product brand → `GT Racing Broadcast` (or `GT Racing` for a short title/logo lockup where it reads better).
- Any `GT_Endurance.json` / `GT_Solo_*.json` filename references → the `GT_Racing_*` names.

- [ ] **Step 2: Verify no leaks + decks still render**

Run:
```bash
grep -rn "GT Endurance Racing" src/docs/slides/
python3 tools/check-slides.py
```
Expected: grep returns nothing; `check-slides.py` reports no overflow/render errors.

- [ ] **Step 3: Commit (note the stale walkthrough videos)**

```bash
git add src/docs/slides
git commit -m "docs(brand): rebrand slide decks to GT Racing Broadcast (#308)

Walkthrough MP4s rendered from these decks are now stale; re-rendering
via the TTS pipeline is a deferred follow-up, out of scope for #308."
```

---

### Task 6: Final verification sweep

**Files:** none modified (verification only; fix-forward if a leak is found).

- [ ] **Step 1: Repo-wide residual brand check**

Run:
```bash
grep -rn "GT Endurance Racing" --include="*.py" --include="*.html" --include="*.md" --include="*.json" --include="*.svg" . \
  | grep -v "docs/superpowers/" | grep -v "CHANGELOG.md" | grep -v "/dist/" | grep -v "/runtime/"
grep -rn "GT_Endurance\|GT_Solo_" --include="*.py" --include="*.json" --include="*.html" --include="*.md" . \
  | grep -v "docs/superpowers/" | grep -v "/dist/" | grep -v "/runtime/"
```
Expected: the ONLY remaining `GT Endurance Racing` hit is the intentional old-name mention in the OBS-Setup migration note (Task 3 Step 2). No `GT_Endurance`/`GT_Solo_` filename references remain. If anything else appears, fix it and re-run.

- [ ] **Step 2: Full suite + lint + build**

Run:
```bash
python3 tools/run-tests.py && python3 tools/lint.py && python3 tools/build.py
```
Expected: all green; `build.py` exits 0.

- [ ] **Step 3: Commit (only if Step 1 required a fix-forward; otherwise nothing to commit)**

```bash
git commit -am "chore(brand): sweep residual GT Endurance branding (#308)"
```

---

## Notes for the executor

- The endurance byte-identical guard (Task 2 Step 3) is the single most important correctness check — the renamed endurance template must differ from the old one only in the top-level `name` field.
- Tasks 3 and 5 are judgment sweeps (per-occurrence choice between the umbrella `GT Racing Broadcast` and the collection `GT Racing Endurance` / short `GT Racing`) — not `sed`. Read before replacing.
- Task 4's visual verification and marker recording belong to the controller, not the implementer subagent.
