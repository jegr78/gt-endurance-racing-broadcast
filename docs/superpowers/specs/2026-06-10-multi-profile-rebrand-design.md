# Multi-Profile + Rebrand Design

**Date:** 2026-06-10
**Status:** Approved (design), pending implementation plan
**Scope:** Turn the IRO-specific broadcast toolkit into a league-neutral, multi-profile
product ("GT Endurance Racing Broadcast"), so additional endurance leagues (next: ERF)
reuse the same base without forking.

---

## 1. Goal & Motivation

The toolkit is today hard-wired to one league (IRO). The mechanism — relay ping-pong,
HUD, OBS scenes, Companion buttons, flags, manufacturer logos — is already
league-neutral; league-specific graphics are downloaded per Google Sheet at runtime.
The actual per-league difference is therefore **small**: essentially the Google Sheet
config plus a display identity.

This effort:

1. Introduces a **profile** abstraction so one installation serves multiple leagues.
2. **De-brands** the product from "IRO" to the neutral "GT Endurance Racing Broadcast"
   (affects repo name, binaries, CLI command, env vars, docs). "GT" = Gran Turismo
   (the PlayStation sim the leagues race on).

Non-goal (deferred future seam): per-league OBS scene collections or Companion button
templates. Companion has no native profile/template mechanism, so divergent buttons are
handled by **extending the shared buttons/relay/panel actions generally**, not by
per-league templates. The profile directory layout is chosen so this can be added later
without rework.

---

## 2. Naming Decisions

| Thing | Value |
|---|---|
| Product / display name | **GT Endurance Racing Broadcast** |
| GitHub repo | **gt-endurance-racing-broadcast** (GitHub redirect from old `IRO_Broadcast_Setup`) |
| CLI command / binary | **racecast** (short, punchy) |
| UI binary | **racecast-ui** |
| Release archives | **racecast-windows.zip** / **racecast-macos.tar.gz** / **racecast-linux.tar.gz** |
| Build package dir | **GT_Racecast_Package** (+ `.zip`) |
| Machine env prefix | **RACECAST_** |
| OBS tokens | **`__RACECAST_GRAPHICS__`**, **`__RACECAST_SHEET__`**, **`__RACECAST_MEDIA__`** |

---

## 3. Profile Model & Config Split

Config is split into two clearly separated layers.

### 3.1 Machine-level `.env` (gitignored, repo root / next to binary)

Applies to **all leagues** on this machine:

```
RACECAST_PROFILE=iro            # default active profile (optional)
RACECAST_OBS_WS_PASSWORD=...    # OBS websocket password (override of auto-discovery)
RACECAST_COMPANION_EXE=...      # Windows Companion.exe path override
RACECAST_UI_PORT=8089           # Control Center port
```

### 3.2 Profile config `profiles/<league>/profile.env` (gitignored)

This *is* the league:

```
NAME=IRO Endurance              # display name (tool / Control Center / docs only)
SHEET_ID=...                    # Google Sheet driving schedule + HUD
SHEET_PUSH_URL=...              # Apps Script webhook (timer + panel writeback)
INTRO_URL=...                   # optional intro-clip override
OUTRO_URL=...                   # optional outro-clip override
LOGO=logo.png                   # optional, relative to the profile dir
```

Only `profiles/example/profile.env` ships as a template. Real profiles (`profiles/iro/`,
`profiles/erf/`) are created by the operator (clean break — no auto-migration of the old
IRO_* `.env`).

**Format:** simple `KEY=VALUE` parsed by the existing bounded dotenv parser (stdlib,
matches the current idiom, operator-editable, no new dependency).

### 3.3 Central resolver — `src/scripts/config.py` (working title)

One module becomes the single config authority:

- loads the machine `.env` **and** the active profile's `profile.env`
- returns a `ResolvedConfig` object: `sheet_id`, `push_url`, `name`, `intro_url`,
  `outro_url`, `logo_path`, `profile_name`, `profile_runtime_dir`
- **replaces the four duplicated `load_dotenv` copies** (`src/relay/iro-feeds.py`,
  `src/setup-assets.py`, `src/relay/get-media.py`, `src/relay/get-graphics.py`)

> **Verification point (plan phase):** the four copies may exist because of the frozen
> in-process execution model (self-contained standalone scripts avoiding cross-imports).
> If that is a hard constraint, the *logic* stays centralized but its delivery form
> (shared import vs. generated/duplicated-but-single-source) is decided during planning.
> This is an implementation detail, not an architecture risk.

### 3.4 Active-profile resolution order

1. `--profile <name>` global flag (per-command override)
2. `RACECAST_PROFILE` env var
3. persistent pointer `runtime/active-profile` (one line: the profile name)
4. if exactly **one** profile directory exists → use it
5. otherwise → error listing available profiles

`racecast profile use <name>` writes the persistent pointer.

---

## 4. Runtime Scoping & OBS Localization

### 4.1 Profile-scoped `runtime/`

```
runtime/
  active-profile              # pointer, one line ("iro")
  cookies.txt                 # SHARED (YouTube cookies are account/machine-wide)
  wiki/                       # SHARED (maintainer)
  iro/                        # profile-scoped
    graphics/                 # from IRO sheet Assets tab
    media/                    # intro/outro from IRO sheet
    timer.json                # IRO event state
    obs-pages.hash            # HUD/timer refresh gate
    <name>.import.json        # localized OBS collection for IRO
    relay.pid / relay.log     # daemon state
  erf/
    graphics/ media/ timer.json obs-pages.hash ... 
```

`default_runtime_dir()` / `state_dir()` gain the active-profile dimension. **Shared**
only for genuinely cross-league state (cookies, wiki clone, the active-profile pointer).

Because the relay binds fixed ports (53001–53003, 8088), only **one** profile can be
live at a time. **Rule (documented): no profile switch mid-event.**

### 4.2 OBS collection localization per league

OBS stores **absolute** paths, so each league needs its own imported scene collection:

- `racecast setup --profile erf` writes `runtime/erf/<name>.import.json` with tokens
  resolved to the ERF sheet + `runtime/erf/graphics` + `runtime/erf/media`
- operator imports it as a separate OBS collection (e.g. "GT Racecast – ERF")
- the already-merged **OBS scene-collection switch** (issue #36) switches between league
  collections during an event — fits in natively
- tokens are de-branded: `__IRO_GRAPHICS__` → `__RACECAST_GRAPHICS__`,
  `__IRO_SHEET__` → `__RACECAST_SHEET__`, `__IRO_MEDIA__` → `__RACECAST_MEDIA__`
  (touches `src/setup-assets.py` + `tools/tokenize-obs.py`)

---

## 5. CLI & Control Center UX

### 5.1 New CLI group `racecast profile`

```
racecast profile list                    # all profiles, active one marked
racecast profile show [<name>]           # resolved config (secrets masked)
racecast profile use <name>              # set persistent active profile
racecast profile new <name> [--from <src>]   # copy from <src> or from profiles/example/
racecast profile edit <name>             # open profile.env in $EDITOR (optional, later)
```

Plus a **global `--profile <name>` flag** on every command (one-shot override).

### 5.2 `racecast init` (wizard)

Profile-aware: detects "no profile present" → offers to create one by copying
`profiles/example/`, prompts NAME + SHEET_ID + SHEET_PUSH_URL, sets it active. No
auto-import of an old IRO_* `.env` (clean break).

### 5.3 Control Center (`racecast ui`)

- **Profile switcher** (dropdown, top): shows active profile; switching =
  `profile use` + reload of profile-dependent status panels
- **"New profile" flow:** dialog with "copy from: [example | iro | erf]" + name +
  required fields → creates `profiles/<name>/` (no filesystem handwork)
- **Settings editor split in two:**
  - **Machine** (all leagues): `RACECAST_OBS_WS_PASSWORD`, `RACECAST_COMPANION_EXE`,
    `RACECAST_UI_PORT`, default profile
  - **Profile "\<active\>"**: NAME, SHEET_ID, SHEET_PUSH_URL, INTRO/OUTRO_URL, LOGO →
    writes `profiles/<active>/profile.env`
  - clearly labeled which block writes where; secrets masked
- status / health panels show the active profile and use its `runtime/<profile>/`

---

## 6. De-Branding / Rename Sweep (no behavior change)

### 6.1 Code & file names

| today | new |
|---|---|
| `src/iro.py` | `src/racecast.py` (entrypoint module) |
| `src/relay/iro-feeds.py` | `src/relay/feeds.py` |
| `src/companion/iro-buttons.companionconfig` | `src/companion/buttons.companionconfig` |
| `src/obs/IRO_Endurance.json` | `src/obs/scene-collection.json` |
| env `IRO_*` (machine) | `RACECAST_*` |
| OBS tokens `__IRO_*__` | `__RACECAST_*__` |
| CLI command `iro …` | `racecast …` |

Companion button **labels** (operator-visible) reviewed for IRO text. Internal button
IDs (`iro-timer-start`) are not visible — renamed only if risk-free, otherwise kept as
opaque internal IDs.

### 6.2 Build & release artifacts

| today | new |
|---|---|
| `dist/IRO_Broadcast_Package/` + `.zip` | `dist/GT_Racecast_Package/` + `.zip` |
| binaries `iro` / `iro-ui` | `racecast` / `racecast-ui` |
| `iro-windows.zip` / `-macos.tar.gz` / `-linux.tar.gz` | `racecast-windows.zip` / `-macos.tar.gz` / `-linux.tar.gz` |
| workflow / job names containing "IRO" | neutral |

### 6.3 Repo & docs (last; partly GitHub-side)

- GitHub repo `IRO_Broadcast_Setup` → `gt-endurance-racing-broadcast` (GitHub creates an
  old→new redirect; the `<origin>.wiki.git` remote follows)
- `README.md`, `CHANGELOG.md`, `src/docs/**`, `src/docs/wiki/**`: IRO branding removed,
  product name "GT Endurance Racing Broadcast", new commands/URLs
- release-please config (package name), preview workflow, CodeQL/ruff stay functionally
  identical
- `CLAUDE.md` updated to the new architecture and names

### 6.4 Deliberately NOT renamed (pure neutral mechanism)

Flags, manufacturer logos, `hud.html`, `timer.html`, relay ping-pong logic, Tailscale
helpers.

---

## 7. Implementation Milestones

Sequenced to avoid double-touch (config is built with the **new** names directly, not
IRO_* first then renamed).

- **M1 — Profile core (behavior, TDD).** `src/scripts/config.py`: resolver, machine
  `.env` + `profile.env`, resolution order, `ResolvedConfig`, profile-scoped
  `runtime/<name>/`. New `tests/test_config.py`. Switch the four `load_dotenv` copies to
  the module. The `RACECAST_*` names + `profiles/` are born here.
- **M2 — Profile CLI + init.** `racecast profile list/show/use/new --from`, global
  `--profile`, profile-aware `init` wizard, `profiles/example/` template. Extend tests
  (`test_iro.py` → `test_racecast.py`, `test_init.py`).
- **M3 — Runtime/OBS per profile.** `setup-assets.py` writes to `runtime/<profile>/`,
  token rename `__RACECAST_*__`, `tokenize-obs.py` updated. graphics/media/timer/PID
  profile-scoped. Tie-in with the OBS collection switch.
- **M4 — Control Center.** Profile switcher, "new profile" dialog (copy), two-part
  settings editor (machine vs. profile). UI tests (`test_ui_*`).
- **M5 — De-branding sweep (no behavior).** File renames (`iro.py` → `racecast.py`,
  etc.), remaining strings, Companion labels, build/CI artifact names, binary smoke test.
- **M6 — Docs + repo rename (irreversible GitHub step, last).** README/wiki/CHANGELOG
  de-branded, then rename the GitHub repo, wiki sync, release-please package name.

---

## 8. Risks & Open Verification Points

- **`load_dotenv` duplication** may be a frozen-binary constraint → verify in M1 (keep
  logic central; delivery form resolved during planning).
- **CLAUDE.md rule "removing/renaming a CLI flag → grep the whole repo incl. `tools/` +
  `.github/`"** — the `iro` → `racecast` rename hits exactly those silent callers
  (binary-smoke). M5 greps exhaustively.
- **Repo rename** breaks old release/wiki links; GitHub redirect mitigates; CHANGELOG
  old links stay pinned to old tags.
- **Migration of the real IRO config:** clean break → operator creates `profiles/iro/`
  once (wizard assists). Verify before the first live event.
- **CLAUDE.md** itself must be updated to the new architecture/names at the end.

---

## 9. Testing / CI Gate (every milestone)

- stdlib test suite green (`python3 tools/run-tests.py`)
- `python3 tools/lint.py` clean
- `python3 tools/build.py` verify passes (tokenization, blanked passwords, no secrets,
  preflight present, no shell scripts)
- binary smoke test switched to the new `racecast` command
