#!/usr/bin/env bash
# provision.sh — one-shot machine-layer provisioning for a GCP GPU box (Ubuntu 24.04)
# for the racecast cloud-producer spike (#395).
#
# Installs everything racecast does NOT cover — NVIDIA driver, xfce desktop,
# Firefox (deb, not snap), RustDesk, passwordless sudo, Tailscale join — then delegates
# the toolchain + applications to the racecast binary (install-tools / install-apps).
#
# Idempotent: every step is existence-/stamp-gated; safe to re-run after a failure.
# Runs as root: `sudo ./provision.sh`, or as a GCP startup-script (instance metadata).
#
# Optional environment:
#   TS_AUTHKEY        Tailscale reusable/ephemeral pre-auth key for unattended join.
#                     NEVER commit this. When unset, the browser-auth command is printed.
#   RACECAST_TAG      racecast release tag to install (default: latest = latest STABLE
#                     release). Set to `preview-main` to install the current main
#                     preview build — needed until the install-tools/install-apps
#                     apt-update-first fixes (#408/#412) land in a stable release.
#                     `latest` never selects a pre-release, so this is opt-in.
#   RUSTDESK_VERSION  RustDesk release to install (default: pinned below; check for newer).
#
# NOT handled here — per-league onboarding the operator does once per league:
#   racecast profiles, cookies, `racecast setup`, OBS scene import, RustDesk password.

set -euo pipefail

RUSTDESK_VERSION="${RUSTDESK_VERSION:-1.3.8}"
RACECAST_REPO="jegr78/gt-endurance-racing-broadcast"

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m  %s\n' "$*"; }
warn() { printf '  \033[1;33m!!\033[0m  %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
has_nvidia_gpu() { lspci 2>/dev/null | grep -qi 'nvidia'; }   # false on a CPU-only dry-run box

if [ "$(id -u)" -ne 0 ]; then
  echo "provision.sh must run as root (use: sudo ./provision.sh)" >&2
  exit 1
fi

# The human login user (for sudoers + desktop autologin). Under `sudo` that is
# $SUDO_USER; as a boot-time startup-script no human exists yet — fall back to the
# first real (uid>=1000) account, else defer (the GCP guest agent's google-sudoers
# already grants NOPASSWD until a re-run under `sudo` sets the explicit rule).
target_user() {
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    printf '%s' "$SUDO_USER"; return 0
  fi
  getent passwd | awk -F: '$3>=1000 && $3<65534 {print $1; exit}'
}
USER_NAME="$(target_user || true)"

# ---------------------------------------------------------------------------
log "1/10  APT base + upgrade"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y curl python3 ca-certificates wget gnupg pciutils mesa-utils
ok "base packages present"

# ---------------------------------------------------------------------------
log "2/10  NVIDIA driver + headless X config"
if ! has_nvidia_gpu; then
  warn "no NVIDIA GPU on this host — skipping driver + xorg (CPU dry-run mode)"
elif nvidia-smi >/dev/null 2>&1; then
  ok "driver already loaded ($(nvidia-smi --query-gpu=name --format=csv,noheader | head -1))"
else
  curl -fsSL https://raw.githubusercontent.com/GoogleCloudPlatform/compute-gpu-installation/main/linux/install_gpu_driver.py -o /tmp/install_gpu_driver.py
  python3 /tmp/install_gpu_driver.py || warn "driver install returned non-zero; a reboot may be required, then re-run provision.sh"
  if nvidia-smi >/dev/null 2>&1; then ok "driver loaded"; else warn "nvidia-smi not yet available — reboot and re-run provision.sh"; fi
fi
# Headless virtual display: let X start on the GPU with NO monitor attached, so OBS's
# OpenGL compositor + browser source get GPU acceleration (NVENC itself is via
# libnvidia-encode and independent of the X display). Recipe for Ubuntu 24.04 + NVIDIA.
if has_nvidia_gpu && nvidia-smi >/dev/null 2>&1 && have nvidia-xconfig; then
  nvidia-xconfig --allow-empty-initial-configuration --use-display-device=None --virtual=1920x1080 >/dev/null 2>&1 \
    && ok "xorg.conf written (virtual 1080p display)" \
    || warn "nvidia-xconfig failed — headless X may need manual xorg/EDID tuning"
fi

# ---------------------------------------------------------------------------
log "3/10  xfce desktop + autologin (OBS needs a real X11 session)"
apt-get install -y xfce4 xfce4-goodies lightdm
# xfce as the lightdm session + autologin for the login user, so an X session comes up
# on boot for RustDesk to attach to.
if [ -n "$USER_NAME" ]; then
  install -d -m 0755 /etc/lightdm/lightdm.conf.d
  cat > /etc/lightdm/lightdm.conf.d/50-racecast-autologin.conf <<EOF
[Seat:*]
autologin-user=$USER_NAME
autologin-user-timeout=0
user-session=xfce
EOF
  ok "autologin configured for $USER_NAME"
else
  warn "no login user detected — set autologin manually after first SSH"
fi

# ---------------------------------------------------------------------------
log "4/10  Firefox (deb from Mozilla APT, not snap — snap confinement breaks cookie export)"
ff="$(command -v firefox || true)"
if [ -n "$ff" ] && ! readlink -f "$ff" | grep -q '/snap/'; then
  ok "non-snap Firefox already present"
else
  install -d -m 0755 /etc/apt/keyrings
  wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O /etc/apt/keyrings/packages.mozilla.org.asc
  echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
    > /etc/apt/sources.list.d/mozilla.list
  printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
    > /etc/apt/preferences.d/mozilla
  apt-get update
  apt-get install -y firefox
  ok "Firefox (deb) installed"
fi

# ---------------------------------------------------------------------------
log "5/10  RustDesk (remote desktop over the tailnet)"
if have rustdesk; then
  ok "RustDesk already present"
else
  deb="/tmp/rustdesk-${RUSTDESK_VERSION}.deb"
  curl -fsSL "https://github.com/rustdesk/rustdesk/releases/download/${RUSTDESK_VERSION}/rustdesk-${RUSTDESK_VERSION}-x86_64.deb" -o "$deb"
  apt-get install -y "$deb"
  ok "RustDesk ${RUSTDESK_VERSION} installed (set the password + 'direct IP access' in the GUI)"
fi

# ---------------------------------------------------------------------------
log "6/10  passwordless sudo"
if [ -n "$USER_NAME" ]; then
  f="/etc/sudoers.d/90-racecast"
  echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > "$f"
  chmod 0440 "$f"
  if visudo -cf "$f" >/dev/null 2>&1; then
    ok "passwordless sudo for $USER_NAME"
  else
    rm -f "$f"; warn "sudoers validation failed — drop-in removed"
  fi
else
  warn "no login user detected — passwordless sudo deferred (re-run under sudo after first SSH)"
fi

# ---------------------------------------------------------------------------
log "7/10  racecast binary"
if have racecast; then
  ok "racecast already on PATH ($(racecast --version 2>/dev/null | head -1))"
else
  case "$(uname -m)" in
    aarch64|arm64) asset="racecast-linux-arm64.tar.gz" ;;
    *)             asset="racecast-linux.tar.gz" ;;
  esac
  tag="${RACECAST_TAG:-latest}"
  if [ "$tag" = "latest" ]; then
    url="https://github.com/${RACECAST_REPO}/releases/latest/download/${asset}"
  else
    url="https://github.com/${RACECAST_REPO}/releases/download/${tag}/${asset}"
  fi
  curl -fsSL "$url" -o /tmp/racecast.tar.gz
  install -d -m 0755 /opt/racecast
  tar -xzf /tmp/racecast.tar.gz -C /opt/racecast
  ln -sf /opt/racecast/racecast /usr/local/bin/racecast
  ok "racecast installed ($(racecast --version 2>/dev/null | head -1))"
fi

# ---------------------------------------------------------------------------
log "8/10  racecast install-tools (yt-dlp / streamlink / ffmpeg / deno)"
racecast install-tools
ok "toolchain installed"

# ---------------------------------------------------------------------------
log "9/10  racecast install-apps (OBS + Browser Source, Tailscale, Companion, Discord)"
racecast install-apps --yes
ok "applications installed"

# ---------------------------------------------------------------------------
log "10/10  Tailscale join"
if tailscale status >/dev/null 2>&1; then
  ok "already joined the tailnet ($(tailscale ip -4 2>/dev/null | head -1))"
elif [ -n "${TS_AUTHKEY:-}" ]; then
  tailscale up --ssh --authkey "$TS_AUTHKEY" --hostname spike-gpu
  ok "joined the tailnet unattended"
else
  warn "no TS_AUTHKEY set — run this once to join:"
  echo "      sudo tailscale up --ssh --hostname spike-gpu"
fi

# ---------------------------------------------------------------------------
log "verification"
rc=0
if nvidia-smi >/dev/null 2>&1; then ok "nvidia-smi: GPU present"; else warn "nvidia-smi: FAIL (reboot + re-run)"; rc=1; fi
if have ffmpeg && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q nvenc; then ok "ffmpeg: NVENC encoders present"; else warn "ffmpeg NVENC: FAIL"; rc=1; fi
if ldconfig -p | grep -q nvidia-encode; then ok "libnvidia-encode present"; else warn "libnvidia-encode: not found (NVENC needs it)"; fi
ff2="$(command -v firefox || true)"
if [ -n "$ff2" ] && ! readlink -f "$ff2" | grep -q '/snap/'; then ok "firefox: deb build"; else warn "firefox: missing or snap"; rc=1; fi
if have racecast; then ok "racecast: $(racecast --version 2>/dev/null | head -1)"; else warn "racecast: FAIL"; rc=1; fi
if have obs; then ok "obs: installed"; else warn "obs: not on PATH (check install-apps output)"; fi
if tailscale status >/dev/null 2>&1; then ok "tailscale: up"; else warn "tailscale: not joined (run tailscale up)"; fi
if pgrep -x Xorg >/dev/null 2>&1; then ok "X server: running"; else warn "X server: not running yet (reboot to start the autologin session; RustDesk needs it)"; fi
if has_nvidia_gpu; then
  if DISPLAY=:0 glxinfo 2>/dev/null | grep -qi nvidia; then ok "OpenGL renderer: NVIDIA (X is on the GPU)"; else warn "OpenGL renderer not NVIDIA yet — reboot so the X session starts, then re-check: DISPLAY=:0 glxinfo -B"; fi
fi

echo
if [ "$rc" -eq 0 ]; then
  log "provision.sh complete — machine layer ready. Next: per-league onboarding (profile + cookies + racecast setup + OBS import)."
else
  warn "provision.sh finished with issues above — fix and re-run (idempotent)."
fi
exit "$rc"
