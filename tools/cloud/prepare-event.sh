#!/usr/bin/env bash
# prepare-event.sh — on-box, per-event racecast preparation for the cloud GPU box.
# Runs the recurring event-prep sequence to "ready" (no go-live) and reports which
# one-time manual setup is still missing. Companion to tools/cloud/provision.sh.
# Run as the `racecast` user on the box:  ./prepare-event.sh <league> [flags]
# shellcheck disable=SC2034  # globals for later tasks
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
