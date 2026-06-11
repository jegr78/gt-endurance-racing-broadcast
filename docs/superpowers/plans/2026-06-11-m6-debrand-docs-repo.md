# M6 — Docs/Wiki De-Brand + Multi-Profile Overhaul + Repo Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the rebrand: de-brand all remaining prose (docs/wiki/README/CLAUDE.md/.env.example + a few code strings) from IRO → racecast / GT Endurance Racing, rewrite the docs to reflect the **multi-profile** reality (they still describe the old single-`.env` model) and the new **overlay** feature, add dedicated **Profiles** and **HUD-Overlays** wiki pages, rename the IRO-named doc/spec files, point the self-updater + wiki links at the renamed repo, then hand off the irreversible **GitHub repo rename** as a user-gated cutover.

**Architecture:** This is the final milestone of the single rolling PR #43. It is mostly careful prose work, not code. The risk is (a) using a WRONG replacement name (always derive from the real code), (b) leaving the old single-`.env` narrative in place (factually wrong post-refactor), and (c) breaking the self-updater by mangling the repo owner. Tests cover fixtures (`run-tests`) and internal wiki links (`tests/test_wiki.py`); docs prose is gated by a residual-`iro` grep + a build verify + a wiki link-check + a sync dry-run.

**Tech Stack:** Markdown + one HTML cheat-sheet; Python stdlib for the few code-string + fixture + constant edits; `tools/sync-wiki.py` (wiki publish), `tools/build.py` (package verify), `tests/test_wiki.py` (link checker).

**Decisions locked with the user (2026-06-11):**
- Doc-file names: **brand-neutral** → `IRO_Broadcast_Setup_Guide.md` → `Broadcast_Setup_Guide.md`, `IRO_cheat_sheets.html` → `cheat_sheets.html`.
- `profiles/example/profile.env` stays **generic** (`NAME=Example League`) — do NOT change it.
- Channel/stream-key references become **league-neutral** ("the league's YouTube channel", "your stream key"), not a specific league.
- Example league identifier in **test fixtures**: "IRO Endurance" → **"IRO GTEC"**.
- Doc depth: **full overhaul** — de-brand + correct to the multi-profile model + new dedicated wiki pages.
- Repo rename target: **`jegr78/gt-endurance-racing-broadcast`** (owner `jegr78/` stays).

---

## Section 0 — Shared reference (every task uses this; do not diverge)

### 0.1 Canonical rename dictionary (product de-brand)

Apply these EXACT mappings. Always confirm the target against the real repo (`git ls-files`, `grep`) — never invent a name.

| Old | New |
|---|---|
| `iro` (CLI/binary) | `racecast` |
| `iro-ui` (windowed app) | `racecast-ui` |
| `python3 src/iro.py` | `python3 src/racecast.py` |
| product name "IRO Endurance Broadcast" / "IRO Broadcast" | **GT Endurance Racing Broadcast** |
| package `IRO_Broadcast_Package` (+`.zip`) | `GT_Racecast_Package` (+`.zip`) |
| archives `iro-windows.zip` / `iro-macos.tar.gz` / `iro-linux.tar.gz` | `racecast-windows.zip` / `racecast-macos.tar.gz` / `racecast-linux.tar.gz` |
| OBS source `src/obs/IRO_Endurance.json` | `src/obs/GT_Endurance.json` |
| OBS template `IRO_Endurance.template.json` | `GT_Endurance.template.json` |
| localized import `IRO_Endurance.import.json` | `GT_Endurance.import.json` |
| scene-collection name "IRO Endurance" (the OBS collection) | `GT Endurance Racing` (canonical) / `GT Endurance Racing — <league>` (per-profile default) |
| `iro-buttons.companionconfig` | `racecast-buttons.companionconfig` |
| relay `src/relay/iro-feeds.py` | `src/relay/racecast-feeds.py` |
| Companion backup `.iro-bak` | `.racecast-bak` |
| OBS tokens `__IRO_GRAPHICS__`/`__IRO_SHEET__`/`__IRO_MEDIA__`/`__IRO_ASSETS__`/`__IRO_TIMER__` | `__RACECAST_GRAPHICS__`/`__RACECAST_SHEET__`/`__RACECAST_MEDIA__`/`__RACECAST_ASSETS__`/`__RACECAST_TIMER__` |
| machine vars `IRO_OBS_WS_PASSWORD`/`IRO_COMPANION_EXE`/`IRO_UI_PORT`/`IRO_UI_PASSWORD` | `RACECAST_OBS_WS_PASSWORD`/`RACECAST_COMPANION_EXE`/`RACECAST_UI_PORT`/`RACECAST_UI_PASSWORD` |
| doc file `IRO_Broadcast_Setup_Guide.md` | `Broadcast_Setup_Guide.md` |
| doc file `IRO_cheat_sheets.html` | `cheat_sheets.html` |
| repo `jegr78/IRO_Broadcast_Setup` | `jegr78/gt-endurance-racing-broadcast` |
| spec `docs/superpowers/specs/2026-06-06-iro-init-design.md` | `2026-06-06-racecast-init-design.md` |

### 0.2 League-var prose CORRECTION (the multi-profile reality)

The biggest factual fix. The OLD docs say league config lives in the machine `.env` as `IRO_SHEET_ID` etc. That is now WRONG. The correct model:

- **League config lives in `profiles/<name>/profile.env`** with UN-prefixed keys: `NAME`, `SHEET_ID`, `SHEET_PUSH_URL`, `INTRO_URL`, `OUTRO_URL`, `LOGO`, `OBS_COLLECTION`. NOT `RACECAST_SHEET_ID`; NOT in `.env`. (When a relay/asset child process runs, the CLI injects these as `RACECAST_SHEET_ID` etc. into the child env — that is an internal implementation detail, not something an operator sets.)
- **The machine `.env`** (repo root, gitignored; template `.env.example`) holds ONLY machine-wide settings: `RACECAST_OBS_WS_PASSWORD`, `RACECAST_COMPANION_EXE`, `RACECAST_UI_PORT`, `RACECAST_UI_PASSWORD` (reserved/commented), and `RACECAST_PROFILE` (default active profile).
- **Profiles:** `racecast profile list | show | use | new [--from <src>]`; global `--profile <name>`; active pointer `runtime/active-profile`; precedence `--profile` > `RACECAST_PROFILE` > pointer > sole profile. Each league lives in `profiles/<name>/`; `profiles/example/` ships as the template.
- **Profile-scoped runtime:** `runtime/<profile>/` holds graphics/media/timer/PID-logs/OBS import; the `active-profile` pointer + `cookies.txt` are machine-shared (one YouTube login across leagues).
- **`racecast init`:** a profile step (create/select a profile, fill `SHEET_ID` into its `profile.env`) replaces the old `IRO_SHEET_ID`-in-`.env` gate; the env step is now a no-gate machine-`.env` creator.
- **Control Center:** a **Profile** view (profile switcher + "new profile" copy dialog + `profile.env` editor incl. `OBS_COLLECTION` + the **overlay-CSS editor** + profile-scoped graphics/media) and **General Settings** (machine `.env` + cookies).
- **Per-league OBS:** each profile gets its own localized collection `runtime/<profile>/GT_Endurance.import.json`, named `GT Endurance Racing — <league>` (or the profile's `OBS_COLLECTION`); several leagues coexist, switch with `racecast obs collection set`.
- **Overlay/HUD:** `profiles/<name>/overlay/{hud,timer}.css` (+ `overlay/fonts/`) restyle the relay-served HUD and race-timer pages (cascade-wins override CSS, served at `/hud/override.css`, `/timer/override.css`, `/overlay/fonts/<file>`); editable in the Control Center Profile view; first override on a profile whose `overlay/` didn't exist at relay start needs one `racecast relay restart`, later edits apply live via "Apply in OBS".

### 0.3 KEEP — do NOT change (these are correct or intentionally retained)

- **Test file names** `tests/test_iro.py`, `tests/test_init.py`, etc. — they still exist; docs that run `python3 tests/test_iro.py` are CORRECT. Do not rename them and do not change those doc commands.
- **Internal Python symbols:** `_iro_job_executable`; importlib module nicknames (`"irofeeds"`, `"iro_feeds"`). Pure churn — leave them.
- **`profiles/example/profile.env`** — already correct + generic; do not touch.
- **`CHANGELOG.md`** — auto-generated by release-please; do not hand-edit (its old URLs regenerate on the next release).
- **The example league name itself** is now "IRO GTEC" (fixtures) — "IRO" stays as the user's league brand. Do not de-brand "IRO GTEC".
- **Historical plan/spec docs** under `docs/superpowers/` (other than the init spec rename + live code refs in Task 3) — they are dated records; leave their old wording.

### 0.4 Gate definition (referenced by the final Gate section)

A task is doc-complete when, scoped to the files it touched: `python3 tools/run-tests.py` passes (incl. `tests/test_wiki.py` link checker + fixtures), `python3 tools/lint.py` is clean, and `python3 tools/build.py` verify passes. The milestone-level residual check is in the Gate section.

---

## Task 1: Residual product strings in code (non-doc)

**Files (verify each line first — line numbers drift):**
- `src/racecast.py` — module docstring/title line ~2 `IRO operator CLI` → `racecast operator CLI`.
- `src/scripts/update.py` — comment `# injected by iro` (~295) → `# injected by racecast`.
- `src/relay/racecast-feeds.py` — offline-fallback comment `# IRO relay offline fallback schedule` (~194) → `# racecast relay …`; print `IRO relay running.` (~1890) → `racecast relay running.`
- `src/scripts/native_dialog.py` — `TITLE = "IRO Control Center"` (~8) → `"racecast Control Center"`.
- `src/ui/ui_server.py` — docstring `'ours' when an IRO Control Center answered the ping` (~25) → `… racecast Control Center …`.
- `src/ui/control-center.html` — HTML comment line ~2 (`IRO Control Center … iro ui`) → `racecast Control Center … racecast ui`; `<title>IRO Control Center</title>` (~16) → `<title>racecast Control Center</title>`.
- Test: rely on the existing suite (no behavioural change). These are display/comment strings.

- [ ] **Step 1: Grep first to confirm no test asserts the old strings**

Run: `grep -rn "IRO Control Center\|IRO operator CLI\|IRO relay running\|injected by iro" src/ tests/`
Confirm the only matches are the source lines above (no test asserts them). If a test DOES assert one (e.g. a ping/title test), update that assertion in the same task and note it.

- [ ] **Step 2: Apply the string edits** exactly per the file list (use the dictionary in 0.1). Do NOT touch `_iro_job_executable`, importlib nicknames, or `tests/test_iro.py` references.

- [ ] **Step 3: Verify**

Run: `python3 tools/run-tests.py && python3 tools/lint.py`
Expected: ALL TEST FILES PASS / clean. (If a UI ping/title test existed and you updated it, it passes.)

- [ ] **Step 4: Commit**

```bash
git add src/racecast.py src/scripts/update.py src/relay/racecast-feeds.py src/scripts/native_dialog.py src/ui/ui_server.py src/ui/control-center.html
git commit -m "chore(m6): de-brand residual product strings in code (IRO -> racecast)"
```

---

## Task 2: Rename the two operator doc files + update references

**Files:**
- Rename: `src/docs/IRO_Broadcast_Setup_Guide.md` → `src/docs/Broadcast_Setup_Guide.md` (git mv)
- Rename: `src/docs/IRO_cheat_sheets.html` → `src/docs/cheat_sheets.html` (git mv)
- Modify: `src/racecast.py` `DOCS_FILES` (~2162-2163): values `docs/IRO_cheat_sheets.html` → `docs/cheat_sheets.html`, `docs/IRO_Broadcast_Setup_Guide.md` → `docs/Broadcast_Setup_Guide.md` (keep the dict KEYS `cheat-sheet`/`setup-guide` unchanged).
- Modify: `tools/build.py` — the shipped-doc file list referencing those two names.
- Modify: `tools/build-binary.py` — `DOC_FILES` list referencing `docs/IRO_cheat_sheets.html` / `docs/IRO_Broadcast_Setup_Guide.md`.

- [ ] **Step 1: Find every reference** `grep -rn "IRO_cheat_sheets\|IRO_Broadcast_Setup_Guide" src/ tools/ tests/` — note all (DOCS_FILES, build.py, build-binary.py, and any test). (Content de-brand of the files themselves is Task 7 — this task is the RENAME + refs only, but doing the git mv now is fine; content edits land in Task 7.)

- [ ] **Step 2: git mv both files** to the brand-neutral names.

- [ ] **Step 3: Update the three reference sites** (DOCS_FILES values, build.py, build-binary.py `DOC_FILES`) to the new paths. If a test references the old names, update it.

- [ ] **Step 4: Verify the build ships them under the new names**

Run: `python3 tools/build.py`
Expected: verify passes; confirm `dist/GT_Racecast_Package/docs/cheat_sheets.html` and `…/docs/Broadcast_Setup_Guide.md` exist (`ls dist/GT_Racecast_Package/docs/`). Run `python3 tools/build-binary.py` is NOT required here (slow); the doc-list edit is verified by reading. Run `python3 tools/run-tests.py && python3 tools/lint.py`.

- [ ] **Step 5: Commit**

```bash
git add -A src/docs/ src/racecast.py tools/build.py tools/build-binary.py
git commit -m "chore(m6): brand-neutral doc filenames (Broadcast_Setup_Guide.md, cheat_sheets.html) + refs"
```

---

## Task 3: Rename the init-design spec + update live references

**Files:**
- Rename: `docs/superpowers/specs/2026-06-06-iro-init-design.md` → `docs/superpowers/specs/2026-06-06-racecast-init-design.md` (git mv)
- Modify (live code refs): `src/racecast.py` (~2652) + `src/scripts/init_setup.py` (~8) — the docstring path reference.
- Modify (tracking docs, for cleanliness): `docs/superpowers/plans/2026-06-06-iro-init.md` (3 refs) and `docs/superpowers/plans/2026-06-11-m5c-debrand-artifacts.md` (1 ref) — update the spec filename mention. (These are historical; updating keeps cross-refs valid.)

- [ ] **Step 1: `grep -rn "2026-06-06-iro-init-design" .`** (exclude `.git`) — capture all references.
- [ ] **Step 2: git mv** the spec file.
- [ ] **Step 3:** update every reference found in Step 1 to the new filename.
- [ ] **Step 4:** `python3 tools/run-tests.py && python3 tools/lint.py` (no behavioural change; confirm nothing imports the old path). `grep -rn "2026-06-06-iro-init-design" . | grep -v .git` → expect zero.
- [ ] **Step 5: Commit**
```bash
git add -A docs/ src/racecast.py src/scripts/init_setup.py
git commit -m "chore(m6): rename init-design spec to racecast + update references"
```

---

## Task 4: League fixtures → "IRO GTEC"

**Files:**
- `tests/test_config.py` — every `NAME=IRO Endurance` fixture + derived assertions: `cfg.name == "IRO Endurance"` → `"IRO GTEC"`; `obs_collection == "GT Endurance Racing — IRO Endurance"` → `"GT Endurance Racing — IRO GTEC"`. Leave the explicit-`OBS_COLLECTION` test's asserted value unchanged (only its fixture NAME flips).
- `tests/test_profile.py` — fixture `name="IRO Endurance"` + display assertion → `"IRO GTEC"`.
- `tests/test_iro.py` — fixtures `name="IRO"/"IRO Endurance"` (incl. the `NAME=IRO Endurance` profile.env write and the `display == "IRO Endurance"` assertion) → `"IRO GTEC"`. Note: a ResolvedConfig fixture has `obs_collection="IRO Broadcast"` (an explicit value, unrelated) — leave that string as-is unless it reads as a product name; if it's just a test value, leaving it is fine, but prefer `"GT Endurance Racing — IRO GTEC"` only if the test asserts the default. Inspect before editing.

- [ ] **Step 1: Find every fixture** `grep -rn "IRO Endurance\|NAME=IRO\|name=\"IRO" tests/` — list each with its file:line and whether it's a fixture NAME, a derived `obs_collection` assertion, a `cfg.name`/display assertion, or an explicit `OBS_COLLECTION` value.
- [ ] **Step 2: Edit each fixture NAME to "IRO GTEC"** and update its DERIVED assertions in lockstep (the default `obs_collection` becomes `"GT Endurance Racing — IRO GTEC"`; `cfg.name`/display becomes `"IRO GTEC"`). Do NOT change explicit-`OBS_COLLECTION` asserted values. Keep profile DIR names (`"iro"`) and SHEET_IDs unchanged — only the human NAME changes.
- [ ] **Step 3: Run** `python3 tests/test_config.py && python3 tests/test_profile.py && python3 tests/test_iro.py && python3 tools/run-tests.py && python3 tools/lint.py` — expect ALL PASS.
- [ ] **Step 4: Commit**
```bash
git add tests/test_config.py tests/test_profile.py tests/test_iro.py
git commit -m "chore(m6): example-league fixtures IRO Endurance -> IRO GTEC"
```

---

## Task 5: Repo-reference + self-update constant → renamed repo

**Files:**
- `src/scripts/update.py` (~9): `REPO = "jegr78/IRO_Broadcast_Setup"` → `REPO = "jegr78/gt-endurance-racing-broadcast"`. **CRITICAL: keep the `jegr78/` owner.**
- `src/racecast.py` (~2178): `_wiki_repo()` fallback `return "jegr78/IRO_Broadcast_Setup"` → `return "jegr78/gt-endurance-racing-broadcast"`.
- Test: `tests/test_update.py` — if it asserts `REPO` / the API URL / `releases_url`, update those expectations.

- [ ] **Step 1: Grep** `grep -rn "jegr78/IRO_Broadcast_Setup" src/ tests/ tools/` — capture all (expect update.py + racecast.py + possibly a test).
- [ ] **Step 2:** edit the two code constants (owner preserved). Update any test assertion found.
- [ ] **Step 3:** add a one-line comment at the `update.py` REPO constant noting that already-released binaries embed the old slug and rely on GitHub's rename redirect; this constant governs future releases.
- [ ] **Step 4: Run** `python3 tests/test_update.py && python3 tools/run-tests.py && python3 tools/lint.py` — expect ALL PASS.
- [ ] **Step 5: Commit**
```bash
git add src/scripts/update.py src/racecast.py tests/test_update.py
git commit -m "chore(m6): point self-updater + wiki-repo fallback at jegr78/gt-endurance-racing-broadcast"
```

Note: `tools/sync-wiki.py` needs NO change (it derives the wiki URL from `git remote origin`). The local remote is updated in the final cutover (Gate), after the GitHub rename.

---

## Task 6: `.env.example` de-brand

**Files:** `.env.example` (repo root).

- [ ] **Step 1: Read it.** It already uses `RACECAST_*` var names but its COMMENTS still say `iro` (`iro profile new`, `iro companion start/stop`, `iro ui`, `iro ... stop`) and line 1 says "IRO broadcast".
- [ ] **Step 2: Edit** every `iro ` command in comments → `racecast `, and "IRO broadcast -- machine-local config" → "GT Endurance Racing Broadcast -- machine-local config". Keep the var names (already `RACECAST_*`) and the structure. Ensure the comment about league config pointing to `profiles/<name>/profile.env` and `racecast profile new` is correct.
- [ ] **Step 3: Verify** `python3 tools/build.py` still passes (it checks `.env.example` ships + is blanked); `python3 tools/run-tests.py`.
- [ ] **Step 4: Commit**
```bash
git add .env.example
git commit -m "docs(m6): de-brand .env.example comments (iro -> racecast)"
```

---

## Task 7: `README.md` + `src/docs/` operator docs (de-brand + multi-profile + overlay)

**Files:**
- `README.md`
- `src/docs/README_SETUP.md`
- `src/docs/Broadcast_Setup_Guide.md` (renamed in Task 2)
- `src/docs/cheat_sheets.html` (renamed in Task 2)

This is a content overhaul, not find-replace. Use the dictionary (0.1), the model corrections (0.2), the keep-list (0.3).

- [ ] **Step 1: README.md** — apply every CMD/PRODUCT/PATH/ARTIFACT/ENVVAR/REPO mapping. Then CORRECT the model: the "secrets/.env" section must describe the machine `.env` (machine vars only) vs `profiles/<name>/profile.env` (league config, un-prefixed keys) split; add the `racecast profile` commands and a one-paragraph multi-league note; add a short "Per-league HUD overlays" mention pointing at the wiki HUD-Overlays page; fix the `racecast setup --out runtime/GT_Endurance.import.json` example; repo URLs → `gt-endurance-racing-broadcast`. Do NOT change `python3 tests/test_*.py` commands.
- [ ] **Step 2: README_SETUP.md** — de-brand; reflect that `racecast init` now does a profile step; reference the renamed `cheat_sheets.html`; wiki URLs → new repo.
- [ ] **Step 3: Broadcast_Setup_Guide.md** — de-brand + wiki URLs → new repo; verify all internal references and the title ("GT Endurance Racing Broadcast — Setup Guide").
- [ ] **Step 4: cheat_sheets.html** — de-brand the `<title>`, `<h1>`, every `<code>iro …</code>`/`iro-ui`; make channel/stream-key references **league-neutral** ("your stream key", "the league's channel"); keep it a single self-contained file.
- [ ] **Step 5: Verify** `python3 tools/run-tests.py && python3 tools/lint.py && python3 tools/build.py` (docs ship). Then `grep -rin "\biro\b\|IRO_\|iro-\|iro\.py" README.md src/docs/README_SETUP.md src/docs/Broadcast_Setup_Guide.md src/docs/cheat_sheets.html | grep -vi "iro gtec"` → manually confirm every remaining hit is allowed (a `tests/test_iro.py` command, or "IRO GTEC"); zero product-IRO leftovers.
- [ ] **Step 6: Commit**
```bash
git add README.md src/docs/README_SETUP.md src/docs/Broadcast_Setup_Guide.md src/docs/cheat_sheets.html
git commit -m "docs(m6): overhaul README + operator docs (de-brand + multi-profile + overlay)"
```

---

## Task 8: `CLAUDE.md` (de-brand + multi-profile + overlay correctness)

**Files:** `CLAUDE.md` (the authoritative project guide — be careful, it is large and detailed).

- [ ] **Step 1:** Apply the full dictionary (0.1) across CLAUDE.md: every `python3 src/iro.py …` → `python3 src/racecast.py …`, `iro <subcmd>` → `racecast <subcmd>`, all PATH/ARTIFACT names (`IRO_Broadcast_Package`→`GT_Racecast_Package`, `iro-feeds.py`→`racecast-feeds.py`, `IRO_Endurance.json`→`GT_Endurance.json`, `iro-buttons.companionconfig`→`racecast-buttons.companionconfig`, `.iro-bak`→`.racecast-bak`, archive names, `IRO_Endurance.template.json`→`GT_Endurance.template.json`), OBS tokens `__IRO_*__`→`__RACECAST_*__`, machine vars `IRO_*`→`RACECAST_*`, the doc-file names (`Broadcast_Setup_Guide.md`/`cheat_sheets.html`). Keep `python3 tests/test_iro.py` and `_iro_job_executable`/importlib nicknames.
- [ ] **Step 2:** CORRECT the **Secrets via `.env`** section and any "league config" prose to the profile model (0.2): league vars live in `profiles/<name>/profile.env` (un-prefixed), machine `.env` holds only the machine `RACECAST_*` vars + `RACECAST_PROFILE`; the four `load_dotenv` copies note stays but referencing the correct files. Ensure the **Architecture** section mentions the profile resolver (`src/scripts/config.py`), profile-scoped `runtime/<profile>/`, the `racecast profile` CLI, the Control Center Profile view, and the **overlay** feature (`profiles/<name>/overlay/{hud,timer}.css` + fonts, the `/hud/override.css` etc. endpoints, the hash-gate inclusion, the collection-name prefix convention). Add the overlay endpoints to the relay endpoint list. Update the "Commands" block to include `racecast profile` if missing.
- [ ] **Step 3:** Verify internal consistency — CLAUDE.md must not still claim `IRO_SHEET_ID` in `.env`, must not reference `src/iro.py`, and must name the real files. `grep -n "\biro\b\|IRO_\|iro-\|src/iro\.py\|IRO Endurance" CLAUDE.md | grep -vi "test_iro\|_iro_job\|iro gtec"` → manually confirm zero product-IRO leftovers.
- [ ] **Step 4: Commit**
```bash
git add CLAUDE.md
git commit -m "docs(m6): overhaul CLAUDE.md (de-brand + multi-profile + overlay)"
```

---

## Task 9: Wiki overhaul — existing pages (de-brand + correctness)

**Files:** all 17 `src/docs/wiki/*.md` pages + `_Sidebar.md`. (Images unchanged. The Control-Center screenshots may show old branding — note but do not regenerate here; that needs the running UI. Flag in the report.)

Work page-by-page; apply 0.1 + 0.2 + 0.3. Per-page emphasis:
- **Home.md** — product title "GT Endurance Racing Broadcast"; league-neutral channel wording; `racecast-ui`; repo/release URLs → new repo; add a one-line pointer to the new **Profiles** and **HUD-Overlays** pages.
- **Configuration.md** — the heaviest correction: rewrite the env section to the **profile model** (machine `.env` = `RACECAST_OBS_WS_PASSWORD`/`_COMPANION_EXE`/`_UI_PORT`/`RACECAST_PROFILE`; league config = `profiles/<name>/profile.env` keys `SHEET_ID`/`SHEET_PUSH_URL`/`INTRO_URL`/`OUTRO_URL`/`LOGO`/`OBS_COLLECTION`/`NAME`). Replace every `IRO_SHEET_ID=`-in-`.env` example. Add the `racecast profile` workflow and a cross-link to the Profiles page. `racecast setup --out runtime/GT_Endurance.import.json`.
- **Set-up-the-broadcast-PC.md** & **Run-an-event.md** — de-brand commands; insert the profile step (create/select a league before first event); release URL → new repo.
- **Control-Center.md** — document the **Profile** view (switcher, new-profile dialog, profile.env editor, **overlay-CSS editor**, profile-scoped graphics/media) and **General Settings** (machine .env + cookies); de-brand.
- **Architecture.md** — `Relay (racecast-feeds.py)`; league-neutral channel labels in the Mermaid diagram; mention profile-scoping; de-brand the `start/stop the … broadcast` line.
- **Build-and-maintenance.md** — `GT_Racecast_Package`, `racecast-*` archives, `racecast --version`, `racecast binary`, `src/obs/GT_Endurance.json`, `racecast-buttons.companionconfig`.
- **Companion.md** — `racecast companion …`, `racecast-buttons.companionconfig`.
- **Sheet-Webhook.md**, **Race-Timer.md**, **Relay-Mode.md**, **Static-Mode.md**, **OBS-Setup.md**, **Director.md**, **Director-Setup.md**, **If-something-goes-wrong.md**, **Who-does-what.md** — apply the dictionary; check each for env-var prose / paths / channel wording; OBS-Setup must name `GT_Endurance.json` / the `GT Endurance Racing — <league>` collection and reference per-league collections + `racecast obs collection set`.
- **_Sidebar.md** — de-brand; (new Profiles/HUD-Overlays entries are added in Task 10 — leave a note or add placeholders only if Task 10 hasn't run; prefer adding them in Task 10 to avoid dangling links).

- [ ] **Step 1:** Edit each page per the above. Derive every replacement name from the real repo. Keep wiki internal links valid (page names with hyphens, e.g. `[[Set-up-the-broadcast-PC]]` or `(Set-up-the-broadcast-PC)` style — match the file's existing link syntax).
- [ ] **Step 2: Link-check** `python3 tests/test_wiki.py` (the internal-link/anchor checker) → ALL PASS. Fix any broken intra-wiki link your edits introduced.
- [ ] **Step 3: Residual grep** `grep -rin "\biro\b\|IRO_\|iro-\|src/iro\.py\|IRO Endurance\|IRO Broadcast" src/docs/wiki/ | grep -vi "iro gtec"` → manually confirm zero product-IRO leftovers (channel wording now league-neutral, not "IRO channel").
- [ ] **Step 4: Commit**
```bash
git add src/docs/wiki/
git commit -m "docs(m6): overhaul existing wiki pages (de-brand + multi-profile model)"
```

---

## Task 10: Wiki — new Profiles + HUD-Overlays pages + sidebar

**Files:**
- Create: `src/docs/wiki/Profiles.md`
- Create: `src/docs/wiki/HUD-Overlays.md`
- Modify: `src/docs/wiki/_Sidebar.md` (add both, in a sensible section)
- Modify: cross-links from `Home.md`, `Configuration.md`, `Control-Center.md` (add `[[Profiles]]` / `[[HUD-Overlays]]` pointers where natural — match the existing link syntax used in those pages).

- [ ] **Step 1: Profiles.md** — describe the multi-league profile model for operators: what a profile is (`profiles/<name>/profile.env` keys, what each does), `racecast profile list|show|use|new [--from <src>]`, the `--profile` flag + `RACECAST_PROFILE` + active pointer + precedence, profile-scoped `runtime/<profile>/` vs machine-shared cookies/active-pointer, how to add a second league (copy from `example`), and how the Control Center Profile view exposes all of this. Describe the MECHANISM, do not invent crew procedure. Cross-link Configuration + HUD-Overlays + Control-Center.
- [ ] **Step 2: HUD-Overlays.md** — describe per-league overlay overrides: the `profiles/<name>/overlay/{hud,timer}.css` + `overlay/fonts/` layout; that the base HUD/timer pages are shared and the override CSS wins the cascade (relay serves `/hud/override.css`, `/timer/override.css`, fonts at `/overlay/fonts/<file>`); the overridable element ids (from `src/obs/hud.html`: `#stint #session #streamer #round-top #round-flag #round-country #team0..2 #race-control`; timer `#clock`); a `@font-face` example; the Control Center overlay editor; the first-time `racecast relay restart` caveat then live edits via Apply-in-OBS; and the OBS collection-name prefix convention (`GT Endurance Racing — <league>`). Keep it operator-facing and accurate to the code.
- [ ] **Step 3: _Sidebar.md** — add `[[Profiles]]` and `[[HUD-Overlays]]` under an appropriate heading (e.g. near Configuration / Control-Center). Add the cross-links in Home/Configuration/Control-Center.
- [ ] **Step 4: Link-check** `python3 tests/test_wiki.py` → ALL PASS (the new pages must be reachable and their internal links valid). `python3 tools/lint.py`.
- [ ] **Step 5: Sync dry-run preview** `python3 tools/sync-wiki.py --dry-run` → confirm it would publish the two new pages + the edits with no error. (Dry-run only — do NOT publish; publishing happens after merge.)
- [ ] **Step 6: Commit**
```bash
git add src/docs/wiki/Profiles.md src/docs/wiki/HUD-Overlays.md src/docs/wiki/_Sidebar.md src/docs/wiki/Home.md src/docs/wiki/Configuration.md src/docs/wiki/Control-Center.md
git commit -m "docs(m6): new wiki pages Profiles + HUD-Overlays + sidebar/cross-links"
```

---

## Gate (after all tasks; before the repo-rename cutover)

- [ ] **Full suite:** `python3 tools/run-tests.py` → ALL TEST FILES PASS (incl. `tests/test_wiki.py`).
- [ ] **Lint:** `python3 tools/lint.py` → clean.
- [ ] **Build:** `python3 tools/build.py` → verify passes; confirm `dist/GT_Racecast_Package/docs/` has `cheat_sheets.html` + `Broadcast_Setup_Guide.md` + `README_SETUP.md`, and the package contains no `IRO_*` doc names.
- [ ] **Wiki sync dry-run:** `python3 tools/sync-wiki.py --dry-run` → no error; previews the new pages.
- [ ] **Milestone residual-IRO sweep** (the completion check). Run:
  ```bash
  grep -rin "iro" . \
    --exclude-dir=.git --exclude-dir=runtime --exclude-dir=dist --exclude-dir=node_modules \
    | grep -vi "iro gtec" \
    | grep -v "test_iro\|_iro_job_executable\|irofeeds\|iro_feeds" \
    | grep -v "CHANGELOG.md" \
    | grep -vi "docs/superpowers/"
  ```
  Inspect EVERY remaining line. Allowed survivors ONLY: the "IRO GTEC" league name, the kept test-file/symbol names, CHANGELOG, and historical `docs/superpowers/` records. ANY product-IRO in shipped code/docs/README/CLAUDE/.env.example is a miss — fix it. (Document the final allow-list in the gate report.)
- [ ] **Cross-cutting doc review:** dispatch a reviewer to read the overhauled README + CLAUDE.md + Configuration.md + the two new wiki pages against the model (0.2) — verify no doc still claims the single-`.env` league-var model, the `racecast profile`/overlay features are documented correctly, repo URLs point at the new slug, and no broken wiki links.

## After the gate — push, then the user-gated REPO RENAME cutover

This is the irreversible step. Do it WITH the user, not inside an implementer task.

- [ ] Push `feat/multi-profile-rebrand`; update the rolling **PR #43** title/body to mark M6 landed (the whole rebrand complete); update memory.
- [ ] **Confirm with the user**, then perform the GitHub repo rename: `gh repo rename gt-endurance-racing-broadcast -R jegr78/IRO_Broadcast_Setup` (or the user does it in the GitHub UI). GitHub auto-redirects old URLs/clones.
- [ ] Update the local remote: `git remote set-url origin https://github.com/jegr78/gt-endurance-racing-broadcast.git`; verify `git remote -v` + a `git fetch`.
- [ ] Re-run CI green on the renamed repo; confirm `gh pr checks 43`.
- [ ] **Merge PR #43** (the single cut-over) once everything is green — the rebrand is then complete.
- [ ] After merge: publish the wiki (`python3 tools/sync-wiki.py`) and cut the next release so the self-updater + CHANGELOG pick up the new slug.

## Self-Review (run before handing off the plan)

- Spec coverage: de-brand (1,6,7,8,9) + doc-file rename (2) + spec rename (3) + fixtures→IRO GTEC (4) + repo refs (5) + multi-profile correctness (7,8,9) + new pages (10) + repo rename (Gate) — all covered.
- No placeholders: each task names exact files + the dictionary + the verification command. Doc tasks are rewrite-briefs (the implementer reads + edits each file) rather than full embedded prose, which is appropriate for documentation.
- Consistency: the dictionary (0.1), model (0.2), and keep-list (0.3) are the single source every task references — no divergent mappings.
