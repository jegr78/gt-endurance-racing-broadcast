#!/usr/bin/env bash
# prepare-event.sh — on-box, per-event racecast preparation for the cloud GPU box.
# Runs the recurring event-prep sequence to "ready" (no go-live) and reports which
# one-time manual setup is still missing. Companion to tools/cloud/provision.sh.
# Run as the `racecast` user on the box:  ./prepare-event.sh <league> [flags]
set -uo pipefail

RACECAST_USER="${RACECAST_USER:-racecast}"

LEAGUE=""
# shellcheck disable=SC2034  # set here; read by a later task
NO_TWITCH=0
# shellcheck disable=SC2034  # set here; read by a later task
NO_SPEEDTEST=0
# shellcheck disable=SC2034  # set here; read by a later task
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
      --no-twitch)    # shellcheck disable=SC2034  # set here; read by a later task
                      NO_TWITCH=1 ;;
      --no-speedtest) # shellcheck disable=SC2034  # set here; read by a later task
                      NO_SPEEDTEST=1 ;;
      --no-update)    # shellcheck disable=SC2034  # set here; read by a later task
                      NO_UPDATE=1 ;;
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

resolve_root() {
  local bin; bin="$(command -v racecast)" || die "racecast not on PATH — is this the racecast user on a provisioned box?"
  ROOT="$(dirname "$(readlink -f "$bin")")"
  # shellcheck disable=SC2034  # set here; read by a later task
  RUNTIME="$ROOT/runtime"
  # shellcheck disable=SC2034  # set here; read by a later task
  PROFILES="$ROOT/profiles"
}

# shellcheck disable=SC2034
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
  racecast preflight
  # shellcheck disable=SC2034
  PREFLIGHT_RC=$?
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
  do_update
  run_prep_sequence
  # readiness report added in Task 4
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
