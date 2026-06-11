# M5c — De-brand part 3: build/CI artifact & package names

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the build/release ARTIFACT identity from `iro` to `racecast` — the producer package (`IRO_Broadcast_Package`→`GT_Racecast_Package`), the release/preview archive + binary names (`iro-windows.zip`→`racecast-windows.zip`, `dist/bin/iro`→`dist/bin/racecast`, etc.), and the self-update download logic in lockstep — so the release pipeline produces and the binary self-updates against `racecast-*` artifacts.

**Architecture:** Two slices: (1) the standalone producer-package name in `tools/build.py` (independent), and (2) the release-archive lockstep chain `release.yml`/`preview.yml` matrix ↔ `src/scripts/update.py` (asset/ui-asset/member/old-binary names + User-Agent) ↔ `tests/test_update.py` — which MUST move atomically because `update.py` downloads exactly what the workflows upload. Then a gate. This is the final de-brand code/CI slice; M6 does docs/wiki/README + the GitHub repo rename.

**Tech Stack:** Pure Python 3.11+ stdlib + GitHub Actions YAML. Gate: `python3 tools/run-tests.py` + `python3 tools/lint.py` + `python3 tools/build.py`. The release/preview workflows only run on `v*`/`preview-*` refs (NOT PRs), so the suite + a manual matrix↔update.py correspondence check are the gate for the YAML.

---

## Scope boundaries (read before starting)

**IN scope (rename `iro` → `racecast`):**
- Producer package: `IRO_Broadcast_Package` → `GT_Racecast_Package` (`tools/build.py` + two test fixtures).
- Release/preview archive assets: `iro-{windows.zip,macos.tar.gz,linux.tar.gz}` → `racecast-*`.
- Release/preview binary members + source paths: `dist/bin/iro`→`dist/bin/racecast`, `iro.exe`→`racecast.exe`, `iro-ui.app`→`racecast-ui.app`, `iro-ui`→`racecast-ui`, etc.
- `src/scripts/update.py`: `asset_name`, `ui_asset_name`, `extract_binary` member search, the Windows `iro-old.exe` rename-trick, the `iro-update` User-Agent, and operator-printed prose mentioning the `iro`/`iro-ui` binary/archive.
- `src/racecast.py` `cleanup_old_binary`: the `iro-old.exe` filename (lockstep with `update.py`'s `swap_plan`).
- `tests/test_update.py`: all asset/ui-asset/member/swap-plan/old-binary assertions.
- `.github/workflows/ci.yml`: the one stale comment naming "the iro binary" (cosmetic).

**OUT of scope — do NOT touch:**
- `README.md` (`iro-windows.zip`, `IRO_Broadcast_Package` mentions) → **M6**.
- All `src/docs/**`, wiki, `CLAUDE.md`, the `src/racecast.py:2` "IRO operator CLI" title, the `2026-06-06-iro-init-design.md` spec filename → **M6**.
- `release-please-config.json` / `.release-please-manifest.json` / `release-please.yml` — **no change needed**: `release-type: simple`, no package-name/component, bare `vX.Y.Z` tags.
- The league name `IRO Endurance`, internal symbol `_iro_job_executable`, importlib nicknames, env-var examples (already `RACECAST_*`).
- The `--current` CLI command-name comment `# injected by iro` in update.py — that names the program (already could be `racecast`), low value; **leave it** unless trivially in a line you're already editing (avoid scope creep).

## The lockstep correspondence (Task 2 MUST keep these three columns identical)

| platform | `release.yml`/`preview.yml` `asset:` | `update.py` `asset_name()` | `test_update.py` assertion |
|---|---|---|---|
| win32 | `racecast-windows.zip` | `racecast-windows.zip` | `m.asset_name("win32") == "racecast-windows.zip"` |
| darwin | `racecast-macos.tar.gz` | `racecast-macos.tar.gz` | `... "racecast-macos.tar.gz"` |
| linux | `racecast-linux.tar.gz` | `racecast-linux.tar.gz` | `... "racecast-linux.tar.gz"` |

| platform | `release.yml` `binary:` (in-archive) | `update.py` `extract_binary` search | — |
|---|---|---|---|
| win | `racecast.exe` | `("racecast.exe", "racecast")` | — |
| mac/linux | `racecast` | `("racecast.exe", "racecast")` | — |

| platform | `release.yml` `binary_ui:` | `update.py` `ui_asset_name()` | `test_update.py` |
|---|---|---|---|
| win | `racecast-ui.exe` | `racecast-ui.exe` | `ui_asset_name("win32") == "racecast-ui.exe"` |
| mac | `racecast-ui.app` | `racecast-ui.app` | `... "racecast-ui.app"` |
| linux | `racecast-ui` | `racecast-ui` | `... "racecast-ui"` |

And `release.yml` `built:`/`built_ui:` (the source paths from `build-binary.py` output) → `dist/bin/racecast(.exe)` and `dist/bin/racecast-ui(.exe|.app)`.

---

## File Structure

| File | Change |
|---|---|
| `tools/build.py` | PKG name `IRO_Broadcast_Package`→`GT_Racecast_Package` (3 sites: docstring, `PKG`, zip path) |
| `tests/test_graphics.py`, `tests/test_media.py` | fixture path `/x/IRO_Broadcast_Package`→`/x/GT_Racecast_Package` |
| `.github/workflows/release.yml` | matrix: asset/built/binary/built_ui/binary_ui (3 OS) |
| `.github/workflows/preview.yml` | matrix (3 OS) + release-notes prose (3 archive lines + `iro --version`) |
| `src/scripts/update.py` | asset_name, ui_asset_name, extract_binary member, `iro-old.exe`, `iro-update` UA, prose |
| `src/racecast.py` | `cleanup_old_binary` `iro-old.exe`→`racecast-old.exe` |
| `tests/test_update.py` | asset/ui-asset/member/swap-plan/old-binary assertions |
| `.github/workflows/ci.yml` | one stale comment (cosmetic) |

---

## Task 1: Rename the producer package `IRO_Broadcast_Package` → `GT_Racecast_Package`

**Goal:** `tools/build.py` produces `dist/GT_Racecast_Package/` + `.zip`; the two test fixtures that name the package match. Independent of the archive lockstep.

**Files:**
- Modify: `tools/build.py`, `tests/test_graphics.py`, `tests/test_media.py`

- [ ] **Step 1: Rename the package in `tools/build.py`**

Three sites (verify by grep `grep -n IRO_Broadcast_Package tools/build.py`):
- docstring (≈line 3): `Produces dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip.` → `GT_Racecast_Package`.
- `PKG = os.path.join(DIST, "IRO_Broadcast_Package")` (≈line 11) → `"GT_Racecast_Package"`.
- `zip_path = os.path.join(DIST, "IRO_Broadcast_Package.zip")` (≈line 99) → `"GT_Racecast_Package.zip"`.

- [ ] **Step 2: Update the two test fixtures**

`tests/test_graphics.py` (≈lines 65–66) and `tests/test_media.py` (≈lines 47–48): the fixture path component `/x/IRO_Broadcast_Package` → `/x/GT_Racecast_Package` (these tests assert `graphics_dir`/`media_dir` derive the sibling dir from the `relay` dir — the package name is arbitrary, but keep it consistent).

- [ ] **Step 3: Run suite + lint + build**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # All checks passed
python3 tools/build.py 2>&1 | tail -3   # builds dist/GT_Racecast_Package/, verify passes (exit 0)
ls -d dist/GT_Racecast_Package dist/GT_Racecast_Package.zip   # both exist
```
Expected: green; the new package dir + zip exist; no `dist/IRO_Broadcast_Package*` is newly created.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(m5c): rename producer package IRO_Broadcast_Package -> GT_Racecast_Package"
```

---

## Task 2: Rename release-archive artifact names in lockstep (workflows ↔ update.py ↔ tests)

**Goal:** The release + preview pipelines build/package/upload `racecast-*` archives containing `racecast`/`racecast-ui` binaries, and `racecast update` downloads + extracts exactly those. ALL three columns of the correspondence table above move together in ONE commit so the download path can never look for an asset the upload path didn't produce.

**Files:**
- Modify: `.github/workflows/release.yml`, `.github/workflows/preview.yml`, `src/scripts/update.py`, `src/racecast.py`, `tests/test_update.py`, `.github/workflows/ci.yml`

- [ ] **Step 1: `release.yml` matrix (3 OS)**

For each of the windows/macos/linux matrix entries (≈lines 27–43), rename:
- `asset: iro-windows.zip` → `racecast-windows.zip` (and `iro-macos.tar.gz`→`racecast-macos.tar.gz`, `iro-linux.tar.gz`→`racecast-linux.tar.gz`).
- `built: dist/bin/iro.exe` → `dist/bin/racecast.exe`; `built: dist/bin/iro` → `dist/bin/racecast` (mac + linux).
- `binary: iro.exe` → `racecast.exe`; `binary: iro` → `racecast`.
- `built_ui: dist/bin/iro-ui.exe` → `dist/bin/racecast-ui.exe`; `dist/bin/iro-ui.app` → `dist/bin/racecast-ui.app`; `dist/bin/iro-ui` → `dist/bin/racecast-ui`.
- `binary_ui: iro-ui.exe` → `racecast-ui.exe`; `iro-ui.app` → `racecast-ui.app`; `iro-ui` → `racecast-ui`.
(The packaging steps that reference `${{ matrix.* }}` need no change — they're variable-driven.)

- [ ] **Step 2: `preview.yml` matrix (3 OS) + release-notes prose**

- Matrix (≈lines 114–130): identical renames to Step 1.
- Release-notes body (≈lines 183–185): `$BASE/iro-windows.zip` → `racecast-windows.zip`, `iro-macos.tar.gz` → `racecast-macos.tar.gz`, `iro-linux.tar.gz` → `racecast-linux.tar.gz`.
- ≈line 187: `\`iro --version\` prints` → `\`racecast --version\` prints`.

- [ ] **Step 3: `src/scripts/update.py` — asset/ui-asset/member/old-binary/UA**

- `asset_name` (≈lines 26/28/29): `"iro-windows.zip"`/`"iro-macos.tar.gz"`/`"iro-linux.tar.gz"` → `"racecast-*"`.
- `ui_asset_name` (≈lines 209/211/212): `"iro-ui.exe"`/`"iro-ui.app"`/`"iro-ui"` → `"racecast-ui.*"`/`"racecast-ui"`.
- `extract_binary` member search (≈line 198): `for name in ("iro.exe", "iro"):` → `("racecast.exe", "racecast")`.
- Windows rename-trick `iro-old.exe` (≈line 154, in `swap_plan`): `"iro-old.exe"` → `"racecast-old.exe"`.
- User-Agent (≈lines 51, 175): `"iro-update"` → `"racecast-update"`.
- Operator-printed prose + docstrings mentioning the binary/archive (≈lines 189, 206, 216–220, 253, 264, 271, 275, 282 (`installed ... next to iro` ≈286, `kept as iro-old.exe` ≈288), 284 `restart iro`): rename `iro`/`iro-ui`/`iro-old.exe` → `racecast`/`racecast-ui`/`racecast-old.exe`. **Leave** `# injected by iro` (≈line 295) and the `racecast update`/`racecast ui` strings already renamed in M5b.

- [ ] **Step 4: `src/racecast.py` `cleanup_old_binary` — lockstep with `swap_plan`**

≈lines 249 & 256: the docstring "the iro-old.exe that `racecast update` leaves behind" and `old = os.path.join(exe_dir, "iro-old.exe")` → `"racecast-old.exe"`. This filename MUST equal `update.py`'s `swap_plan` rename target from Step 3 (cleanup removes what swap creates).

- [ ] **Step 5: `tests/test_update.py` — update every artifact assertion**

- `t_asset_name_per_platform` (≈25–27): `iro-windows.zip`/`iro-macos.tar.gz`/`iro-linux.tar.gz` → `racecast-*`.
- `t_ui_asset_name_per_platform` (≈109–111): `iro-ui.exe`/`iro-ui.app`/`iro-ui` → `racecast-ui.*`/`racecast-ui`.
- `swap_plan` tests (≈77–85): the binary paths `/app/iro` → `/app/racecast`, `C:\IRO\iro.exe` → `C:\IRO\racecast.exe`, and the rename target `iro-old.exe` → `racecast-old.exe`. (Keep the `C:\IRO\` dir component — arbitrary fixture dir; only the binary filename changes. The `IRO` here is a path component, not the league; renaming the dir is optional — but the FILE `iro.exe`→`racecast.exe` and `iro-old.exe`→`racecast-old.exe` MUST change.)
- `safe_member` tests (≈90–93): `m.safe_member("iro")` → `m.safe_member("racecast")`, `m.safe_member("sub/iro")` → `"sub/racecast"`, `not m.safe_member("..\\iro.exe")` → `"..\\racecast.exe"` (path-traversal name is arbitrary; rename for consistency).
- `install_ui` tests (≈124–158): every `iro-ui` / `iro-ui.app` / inner `Contents/MacOS/iro-ui` → `racecast-ui` / `racecast-ui.app`.
- All the `_find_asset_url`/`classify*` fixture asset names (≈32–33, 164–165, 192, 196, 255–256): `iro-macos.tar.gz`/`iro-windows.zip` → `racecast-*`.
- **Keep** the `preview-pr-42`/`preview-main`/SHA-tail fixtures and the league-agnostic logic untouched.

- [ ] **Step 6: `ci.yml` stale comment (cosmetic)**

≈line 3: comment "the iro binary ships for Windows/macOS/Linux" → "the racecast binary ships ...".

- [ ] **Step 7: Run suite + lint + the lockstep correspondence check**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS (test_update covers update.py)
python3 tools/lint.py          # All checks passed
```
Then VERIFY the three-way correspondence by hand (the workflows aren't suite-tested):
```bash
# asset names must be identical across release.yml, preview.yml, update.py
grep -o "racecast-\(windows.zip\|macos.tar.gz\|linux.tar.gz\)" .github/workflows/release.yml .github/workflows/preview.yml src/scripts/update.py | sort | uniq -c
# in-archive binary members in release.yml must equal update.py's extract search + binary_ui must equal ui_asset_name
grep -n "binary:\|binary_ui:" .github/workflows/release.yml
grep -n "racecast.exe\|racecast-ui\|racecast-old.exe" src/scripts/update.py src/racecast.py
# zero stale artifact names remain (outside README/docs)
grep -RIn -e "iro-windows\|iro-macos\|iro-linux\|dist/bin/iro\b\|iro-ui\.\|iro-old\|iro-update\|\"iro\.exe\"\|(\"iro.exe\", \"iro\")" \
  .github src/scripts/update.py src/racecast.py tests/test_update.py
```
Expected: each asset name appears in all three files; `release.yml` `binary:`/`binary_ui:` match `update.py`; the final grep returns NO output (all renamed).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(m5c): rename release-archive artifacts iro->racecast (workflows + update.py lockstep)"
```

---

## Task 3: Gate — full suite, lint, build, artifact audit

**Goal:** Prove the whole M5c slice is coherent: suite + lint + producer build all green, the producer package is `GT_Racecast_Package`, and no in-scope `iro` artifact/package name leaks outside README/docs (M6).

**Files:** none (verification only).

- [ ] **Step 1: Full gate**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS
python3 tools/lint.py          # All checks passed
python3 tools/build.py 2>&1 | tail -3   # exit 0
ls -d dist/GT_Racecast_Package dist/GT_Racecast_Package.zip   # exist
```

- [ ] **Step 2: Artifact-name audit (in-scope leakage only)**

```bash
grep -RIn -e "IRO_Broadcast_Package" -e "iro-windows" -e "iro-macos" -e "iro-linux" \
  -e "dist/bin/iro\b" -e "iro-ui\." -e "iro-old" -e "iro-update" \
  tools .github src/scripts/update.py src/racecast.py tests \
  | grep -v "/docs/"
```
Expected: NO output. Any hit is a real miss (fix it). Note: README.md `iro-windows.zip` + `IRO_Broadcast_Package` are **expected** to remain (M6) — they're excluded by scoping the grep to `tools`/`.github`/`src/scripts/update.py`/`src/racecast.py`/`tests`.

- [ ] **Step 3: Report** the gate results + audit output to the controller. No commit.
