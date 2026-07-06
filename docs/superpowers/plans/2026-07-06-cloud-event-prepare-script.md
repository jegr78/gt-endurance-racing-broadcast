# Cloud event-preparation script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-box, per-event preparation script (`tools/cloud/prepare-event.sh`) that runs the recurring racecast event-prep sequence to "ready" and reports what one-time manual setup is still missing — and have `provision.sh` drop it onto the box.

**Architecture:** A standalone bash script under `tools/cloud/` (maintainer glue, not shipped, so bash is allowed and the "no `.sh` in dist" build check does not apply). It orchestrates existing `racecast` CLI commands only — no new product code, no change to the shipped CLI. It is source-friendly (functions + a guarded `main`) so decision helpers can be exercised directly. `provision.sh` gains one idempotent step that copies the script into `~racecast/`.

**Tech Stack:** bash (`set -uo pipefail`), the `racecast` CLI, `shellcheck` + `bash -n` as the verification gate (mirrors how `provision.sh` is validated — these cloud scripts have no Python unit tests in CI).

## Global Constraints

- **English-only** — all script text, comments, log lines, and docs (repo hard rule).
- **Edit only under `tools/cloud/` and `src/docs/`** for this change. No `src/scripts/` or `src/racecast.py` edits — the shipped CLI is unchanged (`relay stop` gains **no** `--force`).
- **bash, `set -uo pipefail`** (NOT `-e` — soft steps must fail without aborting the run).
- **Runs as the `racecast` user on the box**, never root.
- **Install root is binary-adjacent:** resolve it as `dirname "$(readlink -f "$(command -v racecast)")"` (→ `/home/racecast`); `runtime/` and `profiles/` live there.
- **Scope stops at "ready"** — the script never runs `racecast event start` or goes live.
- **Two independent scripts** — instance lifecycle (`gcloud create/start/stop`) stays a manual documented step, not scripted.
- **`racecast update` preview guard** — a build whose `racecast --version` contains `preview` must never be auto-downgraded to stable; prompt (default No) on a TTY, keep-preview when there is no TTY.
- Spec: `docs/superpowers/specs/2026-07-06-cloud-event-prepare-script-design.md`.

---

### Shared test harness (used by several tasks)

Several tasks verify branch logic by sourcing the script with a **stub `racecast`** on `PATH`. Create this helper once at the start and reuse it; it is throwaway (never committed):

```bash
# make a scratch dir with a fake `racecast` that prints canned output.
# $VER controls the version string; $PROFILES controls `profile list`.
mkstub() {
  local d; d="$(mktemp -d)"
  cat > "$d/racecast" <<'STUB'
#!/usr/bin/env bash
case "$1${2:+ $2}" in
  "--version")   echo "${STUB_VER:-1.4.0}" ;;
  "profile list") printf '%b' "${STUB_PROFILES:-* demo\n  gtec\n}" ;;
  "update")      echo "[stub] racecast update" ;;
  "profile use") echo "[stub] profile use ${3:-}" ;;
  "cookies")     echo "[stub] cookies ${2:-} ${3:-}" ;;
  "graphics"|"media"|"brands"|"speedtest"|"preflight") echo "[stub] $1" ;;
  "relay stop")  echo "[stub] relay stop" ;;
  "freeport")    echo "[stub] freeport $*" ;;
  "tailscale status") echo "stub tailnet up" ;;
  *)             echo "[stub] $*" ;;
esac
STUB
  chmod +x "$d/racecast"
  echo "$d"
}
```

Because the script guards `main` behind `[[ "${BASH_SOURCE[0]}" == "${0}" ]]`, a test can `source tools/cloud/prepare-event.sh` and call individual functions without running the whole flow.

---

### Task 1: Script skeleton — args, logging, sanity guard

**Files:**
- Create: `tools/cloud/prepare-event.sh`

**Interfaces:**
- Produces: `usage()`, `log MSG`, `warn MSG`, `die MSG`, `is_league_imported NAME` (exit 0 if the profile is in `racecast profile list`), the parsed globals `LEAGUE`, `NO_TWITCH`, `NO_SPEEDTEST`, `NO_UPDATE`, `ROOT`, `RUNTIME`, `PROFILES`, and a guarded `main`.

- [ ] **Step 1: Write the script skeleton**

Create `tools/cloud/prepare-event.sh`:

```bash
#!/usr/bin/env bash
# prepare-event.sh — on-box, per-event racecast preparation for the cloud GPU box.
# Runs the recurring event-prep sequence to "ready" (no go-live) and reports which
# one-time manual setup is still missing. Companion to tools/cloud/provision.sh.
# Run as the `racecast` user on the box:  ./prepare-event.sh <league> [flags]
set -uo pipefail

RACECAST_USER="${RACECAST_USER:-racecast}"

LEAGUE=""
NO_TWITCH=0
NO_SPEEDTEST=0
NO_UPDATE=0

usage() {
  cat <<'EOF'
Usage: ./prepare-event.sh <league> [--no-twitch] [--no-speedtest] [--no-update]

  <league>        racecast profile name for this event (required; must be imported)
  --no-twitch     skip the Twitch cookie/auth refresh (default: run it alongside YouTube)
  --no-speedtest  skip the bandwidth test (default: run it)
  --no-update     skip the racecast binary self-update (default: run it, with preview guard)

Prepares the box to "ready"; it never goes live (no `racecast event start`).
EOF
}

log()  { printf '\033[1;34m[prepare]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; SOFT_WARNINGS=$((SOFT_WARNINGS + 1)); }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

SOFT_WARNINGS=0

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --no-twitch)    NO_TWITCH=1 ;;
      --no-speedtest) NO_SPEEDTEST=1 ;;
      --no-update)    NO_UPDATE=1 ;;
      -h|--help)      usage; exit 0 ;;
      -*)             usage; die "unknown flag: $1" ;;
      *)              if [ -z "$LEAGUE" ]; then LEAGUE="$1"; else die "unexpected argument: $1"; fi ;;
    esac
    shift
  done
}

is_league_imported() {  # $1 = profile name
  racecast profile list 2>/dev/null | awk '{print $NF}' | grep -qxF "$1"
}

resolve_root() {
  local bin; bin="$(command -v racecast)" || die "racecast not on PATH — is this the racecast user on a provisioned box?"
  ROOT="$(dirname "$(readlink -f "$bin")")"
  RUNTIME="$ROOT/runtime"
  PROFILES="$ROOT/profiles"
}

sanity_guard() {
  [ "$(id -un)" = "$RACECAST_USER" ] || die "run as the '$RACECAST_USER' user (current: '$(id -un)'). Try: sudo -iu $RACECAST_USER ./prepare-event.sh $*"
  command -v racecast >/dev/null 2>&1 || die "racecast not on PATH"
  [ -n "$LEAGUE" ] || { usage; die "missing <league>"; }
  is_league_imported "$LEAGUE" || die "profile '$LEAGUE' is not imported. Onboard it first (see tools/cloud/README.md §4): racecast profile import <bundle>.zip"
}

main() {
  parse_args "$@"
  resolve_root
  sanity_guard "$@"
  log "profile '$LEAGUE' found; install root $ROOT"
  # (further steps added in later tasks)
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
```

- [ ] **Step 2: Lint — must be clean**

Run: `shellcheck tools/cloud/prepare-event.sh && bash -n tools/cloud/prepare-event.sh && echo OK`
Expected: `OK` (no shellcheck findings).

- [ ] **Step 3: Verify the missing-league abort**

Run (uses the harness above):
```bash
chmod +x tools/cloud/prepare-event.sh
d="$(mkstub)"; PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh nope; echo "exit=$?"
```
Expected: prints `profile 'nope' is not imported…` and `exit=1`.

- [ ] **Step 4: Verify a good league + flag parsing passes the guard**

Run:
```bash
d="$(mkstub)"; PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec --no-twitch; echo "exit=$?"
```
Expected: prints `profile 'gtec' found…` and `exit=0` (STUB_PROFILES lists `gtec`).

- [ ] **Step 5: Commit**

```bash
git add tools/cloud/prepare-event.sh
git commit -m "feat(cloud): prepare-event.sh skeleton — args, logging, sanity guard"
```

---

### Task 2: `racecast update` with the preview guard

**Files:**
- Modify: `tools/cloud/prepare-event.sh`

**Interfaces:**
- Consumes: `log`, `die`, `NO_UPDATE`.
- Produces: `is_preview_version STR` (exit 0 iff `STR` contains `preview`), `have_tty` (exit 0 iff stdin is a terminal), `do_update` (runs the guarded update).

- [ ] **Step 1: Add the helpers and `do_update`**

Insert after `is_league_imported` (before `resolve_root`):

```bash
is_preview_version() {  # $1 = version string
  case "$1" in *preview*) return 0 ;; *) return 1 ;; esac
}

have_tty() { [ -t 0 ]; }

do_update() {
  if [ "$NO_UPDATE" = 1 ]; then log "update: skipped (--no-update)"; return 0; fi
  local cur; cur="$(racecast --version 2>/dev/null)"
  if is_preview_version "$cur"; then
    if have_tty; then
      printf '\033[1;33m[prepare]\033[0m Preview build '\''%s'\'' installed (kept for the Linux fixes).\n' "$cur"
      read -r -p "         Update to latest STABLE (loses the preview fixes)? [y/N] " ans
      case "$ans" in
        [yY]|[yY][eE][sS]) racecast update || die "racecast update failed" ;;
        *) log "update: keeping preview build '$cur'" ;;
      esac
    else
      log "update: preview build '$cur' kept (no TTY to confirm). Run interactively, or 'racecast update' to move to stable."
    fi
  else
    log "update: stable build '$cur' — checking for a newer stable"
    racecast update || die "racecast update failed"
  fi
}
```

- [ ] **Step 2: Call it from `main`**

Change `main`'s body from the `log "profile '$LEAGUE' found…"` line onward to:

```bash
  log "profile '$LEAGUE' found; install root $ROOT"
  do_update
  # (further steps added in later tasks)
```

- [ ] **Step 3: Lint**

Run: `shellcheck tools/cloud/prepare-event.sh && bash -n tools/cloud/prepare-event.sh && echo OK`
Expected: `OK`.

- [ ] **Step 4: Unit-check the pure helper by sourcing**

Run:
```bash
source tools/cloud/prepare-event.sh
is_preview_version "1.1.0-preview.main.abc" && echo "preview:OK"
is_preview_version "preview-main-abc"       && echo "preview2:OK"
is_preview_version "1.4.0" || echo "stable:OK"
```
Expected: `preview:OK`, `preview2:OK`, `stable:OK`.

- [ ] **Step 5: Verify the stable path auto-updates (stub)**

Run:
```bash
d="$(mkstub)"; STUB_VER="1.4.0" PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec </dev/null; echo "exit=$?"
```
Expected: shows `update: stable build '1.4.0' — checking…` then `[stub] racecast update`, `exit=0`.

- [ ] **Step 6: Verify the preview path keeps preview when there is no TTY**

Run:
```bash
d="$(mkstub)"; STUB_VER="1.4.0-preview.main.abc" PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec </dev/null; echo "exit=$?"
```
Expected: shows `update: preview build '…' kept (no TTY…)`, **no** `[stub] racecast update` line, `exit=0`.

- [ ] **Step 7: Commit**

```bash
git add tools/cloud/prepare-event.sh
git commit -m "feat(cloud): racecast update with preview-build guard"
```

---

### Task 3: The prep sequence (profile → cookies → assets → speedtest → fresh relay → preflight)

**Files:**
- Modify: `tools/cloud/prepare-event.sh`

**Interfaces:**
- Consumes: `log`, `warn`, `die`, `LEAGUE`, `NO_TWITCH`, `NO_SPEEDTEST`.
- Produces: `run_prep_sequence` (steps 2–9 of the spec), setting `PREFLIGHT_RC` (the exit code of `racecast preflight`).

- [ ] **Step 1: Add `run_prep_sequence`**

Insert before `main`:

```bash
PREFLIGHT_RC=0

run_prep_sequence() {
  log "activating profile '$LEAGUE'"
  racecast profile use "$LEAGUE" || die "racecast profile use '$LEAGUE' failed"

  log "refreshing YouTube cookies"
  racecast cookies firefox || warn "YouTube cookie refresh failed — check the box's Firefox is signed in to YouTube"
  if [ "$NO_TWITCH" = 1 ]; then
    log "Twitch cookies: skipped (--no-twitch)"
  else
    log "refreshing Twitch cookies"
    racecast cookies twitch firefox || warn "Twitch cookie refresh failed — sign in to Twitch in the box's Firefox, or pass --no-twitch"
  fi

  log "refreshing broadcast graphics"; racecast graphics || warn "graphics refresh failed (OBS shows black for missing files)"
  log "refreshing intro/outro media"; racecast media || warn "media refresh failed"
  log "refreshing brand logos";       racecast brands || warn "brands refresh failed"

  if [ "$NO_SPEEDTEST" = 1 ]; then
    log "speedtest: skipped (--no-speedtest)"
  else
    log "running bandwidth speedtest"; racecast speedtest || warn "speedtest failed (network); preflight bandwidth check may be stale"
  fi

  log "forcing a clean relay state (stop + free feed ports)"
  racecast relay stop >/dev/null 2>&1 || true
  racecast freeport --force >/dev/null 2>&1 || true

  log "running preflight"
  racecast preflight; PREFLIGHT_RC=$?
}
```

Note: `relay stop` has no `--force` flag — the fresh-state guarantee is `relay stop` (graceful) **plus** `freeport --force` (per-process kill of any orphaned holder of feed ports 53001–53003, overriding the "relay/streams running" refusal). Both are best-effort: nothing running == success.

- [ ] **Step 2: Call it from `main`**

Update `main` to:

```bash
  log "profile '$LEAGUE' found; install root $ROOT"
  do_update
  run_prep_sequence
  # readiness report added in Task 4
```

- [ ] **Step 3: Lint**

Run: `shellcheck tools/cloud/prepare-event.sh && bash -n tools/cloud/prepare-event.sh && echo OK`
Expected: `OK`.

- [ ] **Step 4: Verify the full sequence runs in order (stub)**

Run:
```bash
d="$(mkstub)"; STUB_VER="1.4.0" PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec </dev/null 2>&1 | grep -E 'profile use|cookies|graphics|media|brands|speedtest|relay stop|freeport|preflight'
```
Expected (order): `profile use gtec`, `cookies firefox`, `cookies twitch firefox`, `graphics`, `media`, `brands`, `speedtest`, `relay stop`, `freeport --force`, `preflight`.

- [ ] **Step 5: Verify `--no-twitch` and `--no-speedtest` skip**

Run:
```bash
d="$(mkstub)"; STUB_VER="1.4.0" PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec --no-twitch --no-speedtest </dev/null 2>&1 | grep -E 'twitch|speedtest'
```
Expected: `Twitch cookies: skipped (--no-twitch)` and `speedtest: skipped (--no-speedtest)`; **no** `[stub] cookies twitch` / `[stub] speedtest` lines.

- [ ] **Step 6: Commit**

```bash
git add tools/cloud/prepare-event.sh
git commit -m "feat(cloud): event-prep sequence (profile, cookies, assets, speedtest, fresh relay, preflight)"
```

---

### Task 4: Readiness report + exit code

**Files:**
- Modify: `tools/cloud/prepare-event.sh`

**Interfaces:**
- Consumes: `log`, `LEAGUE`, `RUNTIME`, `PROFILES`, `PREFLIGHT_RC`, `SOFT_WARNINGS`.
- Produces: `readiness_report` (prints green/red per one-time item and exits the script with the right code).

- [ ] **Step 1: Add `readiness_report`**

Insert before `main`:

```bash
# green/red readiness markers
_ok()   { printf '  \033[1;32mOK\033[0m   %s\n' "$*"; }
_bad()  { printf '  \033[1;31mMISS\033[0m %s\n' "$*"; }
_note() { printf '  \033[1;33m--\033[0m   %s\n' "$*"; }

tailnet_joined() { tailscale ip -4 2>/dev/null | grep -qE '^100\.'; }

league_uses_discord() { grep -q '^DISCORD_CLIENT_ID=' "$PROFILES/$LEAGUE/profile.env" 2>/dev/null; }

readiness_report() {
  local fail=0
  log "readiness — one-time setup that neither provision.sh nor this script can do:"

  # go-live prerequisites (block the exit code)
  if tailnet_joined; then _ok "tailnet joined ($(tailscale ip -4 2>/dev/null | grep -E '^100\.' | head -1))"
  else _bad "tailnet NOT joined — run:  sudo tailscale up --ssh --hostname racecast-box"; fail=1; fi

  if [ -s "$RUNTIME/$LEAGUE/GT_Endurance.import.json" ]; then _ok "OBS scene collection localized for '$LEAGUE'"
  else _bad "OBS collection not localized — run 'racecast setup', then import it into OBS over RustDesk (once per league)"; fail=1; fi

  # advisory (surfaced, do NOT block the exit code)
  if [ -s "$RUNTIME/yt-cookies.txt" ]; then _ok "YouTube cookies present"
  else _note "no YouTube cookies yet — sign in to YouTube in the box's Firefox, then re-run"; fi

  if league_uses_discord; then
    if [ -s "$RUNTIME/discord-rpc-token.json" ] || find "$RUNTIME" -name discord-rpc-token.json -type f 2>/dev/null | grep -q .; then
      _ok "Discord voice token cached"
    else
      _note "league uses Discord but no voice token — run 'racecast discord join' once over RustDesk"
    fi
  fi

  if [ "$PREFLIGHT_RC" -eq 0 ]; then _ok "preflight passed"
  else _bad "preflight reported issues (exit $PREFLIGHT_RC) — see the preflight output above"; fail=1; fi

  echo
  if [ "$fail" -eq 0 ]; then
    log "READY — go live via Control Center 'Start event' or:  racecast event start"
    [ "$SOFT_WARNINGS" -gt 0 ] && warn "$SOFT_WARNINGS soft warning(s) above — review before going live"
    exit 0
  else
    die "NOT ready — fix the MISS lines above, then re-run:  ./prepare-event.sh $LEAGUE"
  fi
}
```

- [ ] **Step 2: Call it as the last line of `main`**

```bash
  do_update
  run_prep_sequence
  readiness_report
```

- [ ] **Step 3: Lint**

Run: `shellcheck tools/cloud/prepare-event.sh && bash -n tools/cloud/prepare-event.sh && echo OK`
Expected: `OK`.

- [ ] **Step 4: Verify a missing go-live prereq fails the exit code**

Run (no tailnet, no localized collection on this dev box):
```bash
d="$(mkstub)"; STUB_VER="1.4.0" PATH="$d:$PATH" RACECAST_USER="$(id -un)" bash tools/cloud/prepare-event.sh gtec </dev/null 2>&1 | tail -8; echo "exit=$?"
```
Expected: `MISS tailnet NOT joined…`, `MISS OBS collection not localized…`, ends with `NOT ready…` and a non-zero exit.

- [ ] **Step 5: Verify the report is source-testable in isolation**

Run:
```bash
source tools/cloud/prepare-event.sh
LEAGUE=demo; RUNTIME="$(mktemp -d)"; PROFILES="$(mktemp -d)"; PREFLIGHT_RC=0; SOFT_WARNINGS=0
mkdir -p "$RUNTIME/demo"; : > "$RUNTIME/demo/GT_Endurance.import.json"; echo x > "$RUNTIME/demo/GT_Endurance.import.json"
( readiness_report ); echo "exit=$?"
```
Expected: `OK   OBS scene collection localized for 'demo'`, a `MISS tailnet…` (unless this machine is on a tailnet), exit reflects the tailnet state. (This confirms the function is independently exercisable.)

- [ ] **Step 6: Commit**

```bash
git add tools/cloud/prepare-event.sh
git commit -m "feat(cloud): readiness report + go-live-prereq exit code"
```

---

### Task 5: `provision.sh` drops `prepare-event.sh` onto the box

**Files:**
- Modify: `tools/cloud/provision.sh`

**Interfaces:**
- Consumes: the `provision.sh` conventions — `$RACECAST_USER`, its `log`/`warn` helpers, and the sibling-file location `"$(dirname "$0")"`.

- [ ] **Step 1: Read the tail of `provision.sh` to place the step**

Run: `grep -nE 'verification|verify|install-apps|^main|reboot|SCRIPT_DIR|dirname' tools/cloud/provision.sh | tail -30`
Purpose: find where the racecast install finishes and the verification block begins, plus the helper names (`log`, `warn`) and how the script refers to its own directory. Place the copy **after** the racecast binary install (step 7) and **before** the verification block, so a later red line does not skip it.

- [ ] **Step 2: Add the copy step**

Add a function near the other step functions and call it in sequence (match the file's existing `log`/`warn` style and `N/10` logging convention — read the neighbours first). Example body:

```bash
copy_prepare_script() {
  log "copying prepare-event.sh into ~$RACECAST_USER"
  local src; src="$(dirname "$0")/prepare-event.sh"
  if [ -f "$src" ]; then
    install -m 0755 -o "$RACECAST_USER" -g "$RACECAST_USER" "$src" "/home/$RACECAST_USER/prepare-event.sh" \
      && log "  -> /home/$RACECAST_USER/prepare-event.sh" \
      || warn "  could not copy prepare-event.sh (continuing)"
  else
    warn "  prepare-event.sh not beside provision.sh (startup-script mode?) — scp it up manually later"
  fi
}
```

Call it in the same place the other steps are invoked (after the racecast-binary step). It is idempotent (overwrite) and best-effort (a startup-script run where the sibling file is absent just warns).

- [ ] **Step 3: Lint**

Run: `shellcheck tools/cloud/provision.sh && bash -n tools/cloud/provision.sh && echo OK`
Expected: `OK` (fix any new finding; leave pre-existing ones untouched — compare against `git stash` if unsure).

- [ ] **Step 4: Verify the copy step in isolation**

Run (simulate the copy with a fake HOME + user = current user):
```bash
tmp="$(mktemp -d)"; cp tools/cloud/prepare-event.sh "$tmp/"; cp tools/cloud/provision.sh "$tmp/"
( cd "$tmp"; RACECAST_USER="$(id -un)"; src="./prepare-event.sh"; dest="$tmp/home/prepare-event.sh"; mkdir -p "$tmp/home"; install -m 0755 "$src" "$dest" && test -x "$dest" && echo "COPY:OK" )
```
Expected: `COPY:OK` (confirms the `install` invocation and executable bit; the real step targets `/home/$RACECAST_USER`).

- [ ] **Step 5: Commit**

```bash
git add tools/cloud/provision.sh
git commit -m "feat(cloud): provision.sh drops prepare-event.sh onto the box"
```

---

### Task 6: Documentation

**Files:**
- Modify: `tools/cloud/README.md`
- Modify: `src/docs/wiki/Cloud-Producer.md`

**Interfaces:** none (docs).

- [ ] **Step 1: Add the README section**

In `tools/cloud/README.md`, after §4 "Onboard a league", add a new section:

````markdown
## 4b. Prepare for an event (`prepare-event.sh`)

`provision.sh` drops `prepare-event.sh` into `~racecast/`. Before each event, SSH in as
`racecast` and run it with the league profile:

```bash
gcloud compute ssh racecast@racecast-box --zone=europe-west4-c
  $ ./prepare-event.sh <league>            # + --no-twitch / --no-speedtest / --no-update
```

It runs, in order: `racecast update` (with a **preview guard** — a deliberate
`preview-main` build is kept unless you confirm the downgrade to stable), `profile use`,
YouTube **and** Twitch cookie refresh, `graphics` / `media` / `brands`, `speedtest`, a
forced-clean relay (`relay stop` + `freeport --force`), and `preflight`. It stops at
**ready** — it never goes live. A closing readiness report lists any one-time manual
setup still missing (tailnet join, OBS scene-collection import, cookies, Discord token)
with the exact fix, and exits non-zero if a go-live prerequisite (tailnet / OBS
collection) is absent.

Go live afterwards from the browser Director Panel or `racecast event start`.
````

- [ ] **Step 2: Add the copy note to §2**

In `tools/cloud/README.md` §2, add one line noting that provision now also copies
`prepare-event.sh` into `~racecast/` (so it is present for §4b without a second upload;
in startup-script mode where the sibling file is absent, `scp` it up manually).

- [ ] **Step 3: Rewrite `Cloud-Producer.md` §4**

In `src/docs/wiki/Cloud-Producer.md` §4 "Run the event (SSH-only)", replace the hand-typed
command block with:

````markdown
```bash
racecast profile use <league>     # (or let prepare-event.sh do the whole prep — below)
./prepare-event.sh <league>       # update (preview-guarded) · cookies (YouTube+Twitch) ·
                                  # graphics · media · brands · speedtest · fresh relay · preflight
racecast event start              # go live (relay + OBS + Discord)  — prepare-event.sh does NOT
```
````

Keep the existing per-command explanations underneath as "what `prepare-event.sh` does",
and add a one-line note that `racecast update` on the box is preview-guarded (a
`preview-main` build is kept unless you confirm the stable downgrade). Do **not** remove the
existing §6 cookies / §7 RustDesk detail.

- [ ] **Step 4: Verify the wiki link/anchor check still passes**

Run: `python3 tests/test_wiki.py`
Expected: PASS (no broken links/anchors introduced — per the "run test_wiki after wiki edits" repo rule).

- [ ] **Step 5: Commit**

```bash
git add tools/cloud/README.md src/docs/wiki/Cloud-Producer.md
git commit -m "docs(cloud): document prepare-event.sh (README §4b + Cloud-Producer §4)"
```

---

## Self-Review

**1. Spec coverage:**
- CLI surface (`<league>` + `--no-twitch/--no-speedtest/--no-update`, TTY intent) → Task 1 (args) + Task 2 (TTY) + Task 3 (flag skips). ✓
- Form & error philosophy (`set -uo pipefail`, run-as-racecast, hard vs soft) → Task 1 (guard) + Task 3 (`die` vs `warn`). ✓
- Step sequence 0–9 incl. `profile use` before assets and `relay stop` + `freeport --force` → Task 3. ✓
- Preview guard (detect, prompt default-No, no-TTY keep, `--no-update`) → Task 2. ✓
- Readiness report + exit code (tailnet/OBS block; cookies/Discord advisory; preflight) → Task 4. ✓
- `provision.sh` copy step (idempotent, best-effort in startup-script mode) → Task 5. ✓
- Docs (README §4b + copy note; Cloud-Producer §4 rewrite) → Task 6. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete bash. Task 5 Step 1 is a *read-first* step (locating the insertion point in an unread file) with a concrete example body in Step 2 — intentional, not a placeholder.

**3. Type/name consistency:** `LEAGUE`, `NO_TWITCH`, `NO_SPEEDTEST`, `NO_UPDATE`, `ROOT`, `RUNTIME`, `PROFILES`, `PREFLIGHT_RC`, `SOFT_WARNINGS` are defined in Task 1/3 and consumed consistently. `is_preview_version`/`have_tty`/`do_update` (Task 2), `run_prep_sequence` (Task 3), `readiness_report`/`tailnet_joined`/`league_uses_discord` (Task 4) are each defined once and called by name. `mkstub`/`STUB_VER`/`STUB_PROFILES` are consistent across tasks.

**Note on TDD form:** these cloud scripts have no Python CI tests (like `provision.sh`); the verification gate is `shellcheck` + `bash -n` + stubbed dry-runs / sourced-function checks. Each task still follows write → verify-it-behaves → commit.
