# Repo Structure & Build — Design

**Date:** 2026-06-03
**Status:** Approved (design), ready for implementation planning
**Scope:** Restructure the IRO_Broadcast_Setup folder into a clean, self-contained,
single-source repository with a build step that generates the distributable. Unify all
scripts to Python. Separate config (versioned) from runtime data and build output
(gitignored).

---

## 1. Goal

Turn the current flat, partly-duplicated folder (working files **plus** a hand-maintained
`IRO_Broadcast_Package/` near-duplicate) into a single-source repo where:

- **`src/`** is the only place anything is edited (the source of truth).
- **`tools/build.py`** generates the distributable into **`dist/`** (gitignored).
- **`runtime/`** holds all runtime data (cookies, logs, caches) and is gitignored.
- Everything is **self-contained** — no references outside the repo (no Google-Drive
  asset paths, no `~/Downloads` companion export).
- All scripts are **Python** (one file per task, cross-platform) — no `.sh`/`.bat` pairs.

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| Core model | **Single-source + build** — `src/` is truth, `build.py` produces `dist/` |
| OBS assets | **In the repo** (`src/assets/`) — fully self-contained; a `sync-assets.py` refreshes them from Drive |
| Runtime data | **Dedicated `runtime/`** (gitignored); relay gets `--runtime-dir` |
| Scripts | **All Python** — replace every `.sh`/`.bat` |
| Build output | **`dist/`** (gitignored), incl. the ZIP |
| Companion password | **Stripped in `src/`** (and dist); never committed with a password |
| Schedule fallback | Sheet → `runtime/schedule.cache.txt`; **no shipped `schedule.txt`** — the relay auto-writes a commented template to `runtime/schedule.txt` on cold-start failure |

## 3. Target folder layout

```
IRO_Broadcast_Setup/                  (repo root, git)
├── README.md                         (repo overview: how to run + how to build)
├── .gitignore
│
├── src/                              ← SINGLE SOURCE OF TRUTH (versioned)
│   ├── relay/
│   │   ├── iro-feeds.py
│   │   └── get-cookies.py            (YouTube cookies -> runtime/cookies.txt)
│   │                                 (no schedule.txt shipped — see 4.1)
│   │                                 (run-relay.py lives in tools/ — repo launcher)
│   ├── obs/
│   │   └── IRO_Endurance.json        (tokenized: __IRO_ASSETS__ instead of Drive paths)
│   ├── companion/
│   │   └── iro-buttons.companionconfig   (password stripped)
│   ├── director/
│   │   └── director-panel.html
│   ├── assets/                       (the 7 PNGs — self-contained)
│   ├── scripts/                      (static-mode, public-only feeds)
│   │   ├── start-streams.py
│   │   ├── stop-streams.py
│   │   └── loopstream.py
│   ├── setup-assets.py               (token -> local abs path; shipped, run by producer/colleagues)
│   └── docs/
│       ├── IRO_Broadcast_Setup_Guide.md
│       ├── README_SETUP.md
│       └── IRO_cheat_sheets.html
│
├── tools/                            ← maintainer-only (NOT shipped)
│   ├── build.py                      (src -> dist/IRO_Broadcast_Package + .zip)
│   ├── tokenize-obs.py               (local abs path -> token, after an OBS re-export)
│   ├── sync-assets.py                (Google Drive -> src/assets/)
│   ├── add_pov_source.py             (inject an ffmpeg source into a collection)
│   └── strip_companion_pass.py       (blank pass/password fields)
│
├── tests/
│   └── test_pov.py
│
├── docs/superpowers/                 (specs + plans — versioned)
│
├── runtime/                          ← GITIGNORED (runtime data)
│   ├── cookies.txt
│   ├── logs/
│   ├── schedule.cache.txt            (last-good sheet cache, written by the relay)
│   ├── schedule.txt                  (optional: auto-generated commented template on cold-start failure)
│   ├── pov.cache.txt
│   └── IRO_Endurance.import.json     (setup-assets output: local-path collection to import)
│
└── dist/                             ← GITIGNORED (build output)
    ├── IRO_Broadcast_Package/
    └── IRO_Broadcast_Package.zip
```

Three clear layers: **config/source** (`src/`, edited once), **runtime** (`runtime/`,
never committed), **distributable** (`dist/`, a build artifact).

## 4. Component changes

### 4.1 Relay — `--runtime-dir` (`src/relay/iro-feeds.py`)

- New arg `--runtime-dir DIR`. Under it: `cookies.txt`, `logs/`, `*.cache.txt`.
- **Default stays "next to the script"** → the distributed package keeps its current
  self-locating behaviour (backward compatible). The repo passes `--runtime-dir runtime`
  via the launcher.
- Affected paths: `logdir`, the cookies auto-detect path, `schedule.cache.txt`,
  `pov.cache.txt` → all under `runtime/`.
- **Schedule fallback (changed):** `schedule.txt` is **no longer shipped**. The schedule
  source order becomes: live Sheet → `runtime/schedule.cache.txt` (last-good) →
  `runtime/schedule.txt` (only if the user has filled one). If **all** fail on a cold
  start, the relay writes a **commented template** (an embedded `SCHEDULE_TEMPLATE`
  string) to `runtime/schedule.txt` if absent, then exits with a clear message ("check
  the Sheet/tab/sharing, or fill runtime/schedule.txt"). The template documents the
  format; real data always comes from the Sheet.
- The `/panel` lookup (director-panel.html) stays as-is (searches next to / one level up);
  in `src/relay/` it resolves `../director/director-panel.html` — add that candidate path.

### 4.2 Launchers / shipped scripts (Python)

- **`tools/run-relay.py`** — repo launcher: runs
  `src/relay/iro-feeds.py --runtime-dir <root>/runtime` passing through extra args. The
  producer's one command to start the relay. (In `tools/`, not `src/relay/`, because its
  runtime resolution is repo-specific; dist colleagues run `python3 relay/iro-feeds.py`.)
- **`src/relay/get-cookies.py`** — replaces `get-cookies.sh/.bat`. Runs
  `yt-dlp --cookies-from-browser <browser> --cookies <runtime>/cookies.txt …`, detects a
  logged-in session, prints OK/WARN. Browser arg defaults to `firefox`.
- **`src/setup-assets.py`** — replaces `setup-assets.sh/.bat`. Rewrites the
  `__IRO_ASSETS__` token in `obs/IRO_Endurance.json` to the **absolute local** assets path
  on this machine, writing the importable collection (repo: `runtime/IRO_Endurance.import.json`;
  dist: alongside the package). OBS needs absolute paths; the stored source stays tokenized.
- **`src/scripts/{start-streams,stop-streams,loopstream}.py`** — replace the `.sh/.bat`
  static-mode launchers (public-only fixed feeds). `loopstream.py` runs the streamlink
  serve-loop; `start/stop` manage the set.

### 4.3 Maintainer tools (Python, not shipped)

- **`tools/build.py`** — the build:
  1. `rm -rf dist/IRO_Broadcast_Package`
  2. copy `src/{relay,obs,companion,director,assets,scripts,setup-assets.py,docs}` into
     `dist/IRO_Broadcast_Package/` in the documented package layout
     (`obs/`, `companion/`, `relay/`, `assets/`, `scripts/`, top-level docs).
  3. run `strip_companion_pass.py` on the dist companion config (defense in depth — the
     `src/` copy is already stripped).
  4. keep the OBS collection tokenized; ship `setup-assets.py` so colleagues localize it.
  5. `zip` → `dist/IRO_Broadcast_Package.zip`.
  6. print size + verification (POV endpoints present, `pass=''`, paths tokenized).
- **`tools/tokenize-obs.py`** — local abs path → `__IRO_ASSETS__`; run after an OBS
  re-export to update `src/obs/IRO_Endurance.json`.
- **`tools/sync-assets.py`** — copy the production PNGs from the Google-Drive folder into
  `src/assets/` when graphics change. Drive path is a config constant / arg.
- **`tools/add_pov_source.py`**, **`tools/strip_companion_pass.py`** — keep as-is (already
  Python); `add_pov_source` stays a dev helper for future source injections.

### 4.4 OBS collection — self-contained

- The 7 PNGs (`Overlay`, 5 graphics, `Thumbnail`) move into `src/assets/` (sourced from
  the existing `IRO_Broadcast_Package/assets/`, which already holds local copies).
- `src/obs/IRO_Endurance.json` stores the asset `file` paths as the `__IRO_ASSETS__/<name>.png`
  token (no Google-Drive paths). `setup-assets.py` localizes it per machine.

### 4.5 `.gitignore`

```
runtime/
dist/
__pycache__/
*.pyc
.DS_Store
*.bak
cookies.txt
*.cache.txt
```

## 5. Migration steps (high level — detailed in the plan)

1. Create `src/`, `tools/`, `runtime/`; move/sort existing files in.
2. Port all `.sh`/`.bat` to Python; delete the shell/batch versions.
3. Make OBS self-contained: copy the 7 PNGs into `src/assets/`; tokenize the Drive paths
   in `src/obs/IRO_Endurance.json` to `__IRO_ASSETS__`.
4. Put the current full Companion config (password stripped) into `src/companion/`.
5. Relay: add `--runtime-dir`; route cookies/caches/logs into `runtime/`. Drop the shipped
   `schedule.txt`; add the embedded `SCHEDULE_TEMPLATE` + cold-start auto-write to
   `runtime/schedule.txt`.
6. Write `tools/build.py`; generate `dist/` and confirm it equals the prior package
   (same files, tokenized OBS, stripped password, working relay).
7. Add `.gitignore`; delete the old `IRO_Broadcast_Package/` + `.zip` + root duplicates
   (now generated by the build).
8. Verify: `build.py` output matches the documented package; relay runs from `src/` with
   `runtime/`; `python3 tests/test_pov.py` passes; an end-to-end relay smoke test works.

## 6. Self-containment checklist (post-migration)

- OBS collection tokenized — **no Google-Drive paths**.
- Assets live in `src/assets/`.
- Companion config in `src/`, **password stripped** — no `~/Downloads` dependency.
- Cookies in `runtime/` — gitignored, never committed.
- **No reference points outside the repo.**

## 7. Out of scope (YAGNI)

- No packaging into a Python wheel / installer (plain repo + `python3 …` is enough).
- No CI build automation (manual `python3 tools/build.py` for now).
- No double-click `.command`/`.bat` wrappers (run via `python3`).
- No change to the relay's runtime behaviour for the **distributed** package (it keeps the
  self-locating default; only the repo uses `--runtime-dir runtime`).
- The missing schedule-relay Companion buttons (HANDOVER/RELOAD/STATUS) — tracked
  separately ("ergänzen wir später"), not part of this restructure.

## 8. Risks / notes

- **OBS re-import after migration:** localizing assets changes the collection's image
  paths; the producer re-imports `runtime/IRO_Endurance.import.json` once. (Same one-time
  import as today.)
- **OBS round-trip:** editing in OBS and re-exporting yields absolute paths — must run
  `tools/tokenize-obs.py` to fold changes back into `src/` (documented in README).
- **Static-mode scripts** are legacy (public-only); ported for completeness but the relay
  is the real path.
- Working dir is **not yet a git repo** — `git init` + `.gitignore` happen as part of /
  right after this migration (user owns the init).
