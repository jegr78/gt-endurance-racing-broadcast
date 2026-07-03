# GPU box provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible one-shot provisioning script (plus its README and a runbook Appendix A rewrite) that brings a fresh GCP GPU VM to "ready to onboard a league" without hand-assembling each step.

**Architecture:** A single idempotent bash script `tools/cloud/provision.sh` installs only the machine layer racecast does not cover (NVIDIA driver, xfce, Firefox deb, RustDesk, passwordless sudo, Tailscale join) and delegates the toolchain + applications to the racecast binary (`install-tools` / `install-apps --yes`). It runs in two modes (manual `sudo ./provision.sh` or GCP startup-script) and ends with a green/red verification block. No machine images, no per-event re-provisioning — one persistent instance reused via racecast profiles.

**Tech Stack:** bash (POSIX-ish, `set -euo pipefail`), GCP `gcloud`, racecast CLI, apt, shellcheck for validation.

## Global Constraints

- **Maintainer glue, not shipped.** Lives under `tools/` — excluded from the `dist/` package, so the "no `.sh` shipped" build check (`os.walk(PKG)` in `tools/build.py:198`) does not apply. Do NOT place it under `src/`.
- **English only** for all scripts and docs (repo hard rule).
- **No secrets or machine paths in git.** `TS_AUTHKEY`, cookies, passwords are runtime-only; never commit them. The script reads `TS_AUTHKEY` from the environment.
- **Idempotent + root-safe.** Every step existence-/stamp-gated; safe to re-run after a failure; must run correctly both as `sudo ./provision.sh` and as a boot-time startup-script.
- **Repo slug:** `jegr78/gt-endurance-racing-broadcast`. **Linux amd64 asset:** `racecast-linux.tar.gz`; **arm64:** `racecast-linux-arm64.tar.gz`.
- **Do not re-implement racecast installers.** OBS/Tailscale/toolchain come from `racecast install-tools` / `racecast install-apps --yes`, never hand-rolled apt lines for those.
- **Commit only on the operator's go.** The commit steps below are part of the plan; actual commits happen at execution time under the operator's approval.

---

### Task 1: `tools/cloud/provision.sh`

**Files:**
- Create: `tools/cloud/provision.sh`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: an executable provisioning script invoked as `sudo ./provision.sh` or as `--metadata-from-file startup-script=tools/cloud/provision.sh`. Honors optional env `TS_AUTHKEY`, `RACECAST_TAG`, `RUSTDESK_VERSION`. Task 2 (README) and Task 3 (Appendix A) reference this exact path and invocation.

- [ ] **Step 1: Write the script**

Create `tools/cloud/provision.sh` with exactly this content:

```bash
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
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x tools/cloud/provision.sh`

- [ ] **Step 3: Syntax check (must pass before anything else)**

Run: `bash -n tools/cloud/provision.sh`
Expected: no output, exit 0 (a syntax error would print a line/column).

- [ ] **Step 4: Lint with shellcheck**

Run: `shellcheck tools/cloud/provision.sh` (install first if missing: `brew install shellcheck`)
Expected: no errors. Acceptable to leave low-severity style notes only if justified; fix anything SC2xxx that indicates a real bug (unquoted expansions, masked return values). The `warn ... ; rc=1` idempotency guards are intentional — do not "simplify" them away.

- [ ] **Step 5: Manual idempotency review (read, don't run — no GPU box here)**

Confirm by reading each step: (a) every install is guarded so a second run is a no-op (`have`, `nvidia-smi` gate, `command -v firefox` non-snap gate, `tailscale status` gate); (b) the script never re-implements OBS/Tailscale installation (those come only from `racecast install-apps`); (c) no secret is hard-coded (`TS_AUTHKEY` is read from env only); (d) the verification block exits non-zero when a hard requirement fails. Note in the commit message that full end-to-end validation happens on the real GPU box (Appendix A/B).

- [ ] **Step 6: Commit**

```bash
git add tools/cloud/provision.sh
git commit -m "feat(cloud): one-shot GPU-box provisioning script (#395)"
```

---

### Task 2: `tools/cloud/README.md`

**Files:**
- Create: `tools/cloud/README.md`

**Interfaces:**
- Consumes: `tools/cloud/provision.sh` (Task 1) — references its exact path, env vars, and both execution modes.
- Produces: operator documentation for standing up and reusing the box. Task 3 (Appendix A) links here for the full detail.

- [ ] **Step 1: Write the README**

Create `tools/cloud/README.md` with exactly this content:

````markdown
# GPU box provisioning (cloud-producer spike, #395)

`provision.sh` brings a fresh GCP GPU VM (Ubuntu 24.04, amd64) to "ready to onboard a
league": NVIDIA driver, xfce desktop, Firefox (deb), RustDesk, passwordless sudo,
Tailscale join, plus the racecast toolchain and applications (`install-tools` /
`install-apps`). It installs only what racecast does not cover and delegates the rest to
the racecast binary — it never re-implements the OBS/Tailscale installers.

**Model:** one long-lived instance, reused for all events by switching racecast
**profiles** (`racecast profile use <name>`). Stop the VM between events for cost; the
tailnet IP is stable across stop/start. No machine images/snapshots — this script is the
reproducibility mechanism instead (any league can stand up its own box the same way).

## 1. Create the instance (once)

Requires GPU quota (free; request first — see the runbook Appendix A, Step 0) and a
`gcloud` authed to your project. T4 example:

```bash
gcloud compute instances create spike-gpu \
  --zone=us-central1-a \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --maintenance-policy=TERMINATE \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-type=pd-standard \
  --boot-disk-size=50GB
```

## 2. Provision (once)

**Default — manual, with output on screen (recommended for the first setup):**

```bash
gcloud compute scp tools/cloud/provision.sh spike-gpu:~/ --zone=us-central1-a
gcloud compute ssh spike-gpu --zone=us-central1-a
  $ sudo ./provision.sh        # idempotent — re-run after any red line
```

**Reproduction one-liner — unattended startup-script (any league, from scratch):**

```bash
gcloud compute instances create spike-gpu ... \
  --metadata-from-file startup-script=tools/cloud/provision.sh
# watch the log:
gcloud compute instances get-serial-port-output spike-gpu --zone=us-central1-a
```

Optional env (never commit these):

- `TS_AUTHKEY` — a reusable/ephemeral **tagged** Tailscale pre-auth key for unattended
  join. When unset, the script prints the one-time `tailscale up` command for you to run
  once (fine for the single persistent box).
- `RACECAST_TAG` — racecast release to install (default `latest` = latest **stable**).
  Set `RACECAST_TAG=preview-main` to install the current `main` preview build. Needed
  until the `install-tools`/`install-apps` apt-update-first fixes (#408/#412) reach a
  stable release; `latest` never picks a pre-release, so the preview is strictly opt-in.
  Cut the preview first with `gh workflow run preview.yml --ref main` (rolling tag
  `preview-main`, re-pointed on each run).
- `RUSTDESK_VERSION` — pin a RustDesk release (default in the script; bump if outdated).

The script ends with a green/red verification block. A red line names the step to re-run.

## 3. Finish (once, in the GUI over RustDesk)

These cannot be scripted safely:

- RustDesk: set a permanent password + enable **Settings → Security → "Enable direct IP
  access"**, then connect from your laptop to the box's **`100.x` Tailscale IP**.
- If `nvidia-smi` was not yet ready, reboot once so the autologin X session starts
  (RustDesk needs a running X server).

## 4. Onboard a league (once per league, then reuse)

Not part of `provision.sh` — this is the profile layer:

```bash
# from your laptop, copy the profile + fresh cookies up:
gcloud compute scp --recurse profiles/<league> runtime/yt-cookies.txt \
  spike-gpu:~/racecast-data/ --zone=us-central1-a
# on the box:
racecast profile use <league>
racecast setup            # localize the OBS scene collection for this profile
# then import the localized collection into OBS (GUI, once per league)
```

Switch between already-onboarded leagues with `racecast profile use <name>`.

## 5. Cost control — stop between events

```bash
gcloud compute instances stop  spike-gpu --zone=us-central1-a   # idle ≈ boot disk only
gcloud compute instances start spike-gpu --zone=us-central1-a   # tailnet IP stays stable
```

## Confidence-building before GPU hours

The one genuinely GPU-specific unknown is "does X start on the T4 with no monitor". Everything
else is validatable without a GPU. De-risk in three tiers:

1. **CPU dry-run (pennies).** Run `provision.sh` on a cheap non-GPU VM (the Stage 0/1
   e2-micro). `has_nvidia_gpu()` auto-skips the driver + xorg steps, so the rest —
   lightdm/autologin config, RustDesk + direct-IP over Tailscale, Firefox deb, `racecast
   install-tools`/`install-apps`, the verification block — runs identically and catches
   the non-GPU bugs. Use `RACECAST_TAG=preview-main` so the *fixed* install code is what
   you test.
2. **Isolated GPU smoke test (~15 min on the GPU box).** Before any OBS/onboarding:
   `provision.sh` → reboot → check only the display lines of the verification block
   (`nvidia-smi` lists Xorg as a GPU process, `pgrep Xorg`, `DISPLAY=:0 glxinfo` renderer
   is the T4 not `llvmpipe`, RustDesk shows the xfce desktop). Green = the risky part is
   proven; only then invest in OBS setup + NVENC (#421).
3. **Fallback.** If `--allow-empty-initial-configuration` misbehaves, feed a CustomEDID
   (fake a 1080p monitor). NVENC encoding is independent of the X display, so it is not at
   risk even while the desktop display is being tuned.

## Notes

- `provision.sh` runs as root, so the racecast toolchain lands under `/opt/racecast/runtime`
  (world-readable; racecast adds it to its own PATH). A later `racecast install-tools --update`
  therefore needs `sudo`.
- NVENC proof (that OBS uses the T4 encoder, not a silent x264 fallback) is the runbook's
  Appendix B checklist (#421).
````

- [ ] **Step 2: Commit**

```bash
git add tools/cloud/README.md
git commit -m "docs(cloud): README for the GPU-box provisioning script (#395)"
```

---

### Task 3: Rewrite runbook Appendix A

**Files:**
- Modify: `docs/superpowers/specs/2026-07-02-cloud-producer-spike-runbook.md` (Appendix A, currently lines 239–311)

**Interfaces:**
- Consumes: `tools/cloud/provision.sh` (Task 1) + `tools/cloud/README.md` (Task 2).
- Produces: an Appendix A that points at the script instead of listing the manual machine-layer steps. Appendix B (NVENC) is untouched.

- [ ] **Step 1: Read the current Appendix A to anchor the edit**

Run: `sed -n '239,312p' docs/superpowers/specs/2026-07-02-cloud-producer-spike-runbook.md`
Expected: the current "Appendix A — GCP T4 provisioning commands" block through the `---` before Appendix B.

- [ ] **Step 2: Replace the Appendix A body**

Replace everything from the line `## Appendix A — GCP T4 provisioning commands (copy-paste)` up to (but NOT including) the `---` separator that precedes `## Appendix B` with:

```markdown
## Appendix A — GCP T4 provisioning (persistent instance + provision.sh)

Model: **one long-lived instance**, provisioned once with `tools/cloud/provision.sh`,
reused for all events by switching racecast **profiles**. Stop it between events for cost;
the tailnet IP is stable across stop/start. **No machine images/snapshots** — the script
is the reproducibility mechanism (full detail + the per-league onboarding and cost-control
commands live in `tools/cloud/README.md`). Assumes `gcloud` is authed
(`gcloud auth login`; `gcloud config set project <PROJECT_ID>`).

**Step 0 — GPU quota (do FIRST; the only real lead time; quota is free).** New accounts
have GPU quota 0. Request in the console (**IAM & Admin → Quotas & System Limits**), filter
`us-central1`, request **≥ 1** for `NVIDIA_T4_GPUS` (region us-central1) and
`GPUS_ALL_REGIONS` (global). Inspect from the CLI:
```bash
gcloud compute regions describe us-central1 \
  --format="table(quotas.metric,quotas.limit,quotas.usage)" | grep -i gpu
```
Approval: hours to ~2 business days. The VM cannot be created until it lands. Quota is an
allocation *ceiling*, not a reservation or a charge — you pay only for resources actually
running (distinct from Reservations / Committed-Use, which do cost and are not needed here).

**Step 1 — create the VM (only after quota granted).** GPU VMs cannot live-migrate →
`--maintenance-policy=TERMINATE` is required. T4 zones in us-central1: a, b, c, f.
```bash
gcloud compute instances create spike-gpu \
  --zone=us-central1-a \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --maintenance-policy=TERMINATE \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-type=pd-standard \
  --boot-disk-size=50GB
```
`pd-standard` (not the "Balanced" default) → ~$2/mo idle disk. Ephemeral IP (Stage 1 showed
GCP IPs pass generally — no reserved static IP). `STANDARD`, never spot, for a live run.

**Step 2 — provision the machine layer (once).** Copy up and run the script; it installs
the NVIDIA driver, xfce, Firefox (deb), RustDesk, passwordless sudo, joins Tailscale, and
runs `racecast install-tools` + `racecast install-apps --yes`. Idempotent — re-run after
any red line.
```bash
gcloud compute scp tools/cloud/provision.sh spike-gpu:~/ --zone=us-central1-a
gcloud compute ssh spike-gpu --zone=us-central1-a
  $ sudo ./provision.sh
```
Until the `install-tools`/`install-apps` apt fixes (#408/#412) ship in a stable release,
install the current main preview instead: `gh workflow run preview.yml --ref main` once,
then `sudo RACECAST_TAG=preview-main ./provision.sh`. Reproduction alternative
(unattended, any league): pass the script as a startup-script at create time —
`--metadata-from-file startup-script=tools/cloud/provision.sh` — and read the serial-port
output. Both modes are documented in `tools/cloud/README.md`.

**Step 3 — finish in the GUI (once, over RustDesk on the `100.x` Tailscale IP).** Set the
RustDesk permanent password + "Enable direct IP access". If `nvidia-smi` was not ready
during provisioning, reboot once so the autologin X session starts (RustDesk needs it).

**Step 4 — onboard a league (once per league, then reuse via `racecast profile use`).**
Copy the profile + fresh cookies up, `racecast setup` to localize the OBS scene collection,
import it into OBS. See `tools/cloud/README.md` §4.

**Step 5 — validate with eyes on the screen (Stage 2 / NVENC #421).** HUD browser source
renders; **NVENC encodes 1080p60** (Appendix B checklist); short test encode →
private/unlisted RTMP arrives. Then continue Stage 3 (panel drives cloud OBS) and Stage 4.

**Cost control — stop between events (idle ≈ $2/mo boot disk).**
```bash
gcloud compute instances stop  spike-gpu --zone=us-central1-a
gcloud compute instances start spike-gpu --zone=us-central1-a   # ephemeral public IP may change; tailnet IP stays
```
```

- [ ] **Step 3: Verify the edit is consistent**

Run: `grep -n "provision.sh\|Appendix A\|Appendix B" docs/superpowers/specs/2026-07-02-cloud-producer-spike-runbook.md`
Expected: Appendix A now references `provision.sh` (Steps 2 + 4), the `---` before Appendix B is intact, and Appendix B is unchanged. Confirm no orphaned manual driver/toolchain lines remain in Appendix A.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-02-cloud-producer-spike-runbook.md
git commit -m "docs(runbook): point Appendix A at provision.sh; persistent-instance model (#395)"
```

---

## Self-Review

**Spec coverage:**
- Lifecycle (single persistent instance, profiles, stop/start, no images) → README §Model + Appendix A intro + non-goals. ✓
- Two layers (machine vs. per-league onboarding) → provision.sh scope + README §4. ✓
- provision.sh steps 1–10 + verification block → Task 1 script verbatim. ✓
- Both execution modes → README §2 + Appendix A Step 2. ✓
- SSH (gcloud → tailscale ssh) + passwordless sudo drop-in → script step 6, `tailscale up --ssh` step 10, README. ✓
- Firefox deb-not-snap rationale → script step 4 + verification. ✓
- Delegation to install-tools/install-apps, no re-implementation → script steps 8–9 + Global Constraints. ✓
- Deliverables: provision.sh, README, Appendix A rewrite → Tasks 1–3. ✓
- Validation before GPU hours (shellcheck, bash -n, read-review) → Task 1 steps 3–5. ✓
- Headless X recipe (nvidia-xconfig virtual display) + `glxinfo` renderer check → script step 2 + verification block. ✓
- CPU-dry-run safety (`has_nvidia_gpu` guard skips driver+xorg) → script helper + step 2 + README §Confidence-building. ✓
- Preview-binary path (`RACECAST_TAG=preview-main` until #408/#412 ship stable) → script header env doc + README env note + Appendix A Step 2. ✓
- Risks (driver reboot idempotency, snap-vs-deb, manual GUI steps) → script gates + README §3 + verification block. ✓

**Placeholder scan:** No TBD/TODO; all code shown in full; RUSTDESK_VERSION is a real pinned default with a "bump if outdated" note (not a placeholder). ✓

**Type/name consistency:** Path `tools/cloud/provision.sh`, env vars `TS_AUTHKEY`/`RACECAST_TAG`/`RUSTDESK_VERSION`, and the `--yes` flag are identical across Task 1, Task 2, and Task 3. ✓
```

---

## Post-review amendments (2026-07-03, after task reviews)

The task reviews surfaced two changes to the committed deliverables. **The committed
`tools/cloud/provision.sh` and `tools/cloud/README.md` supersede the verbatim code blocks
in Task 1 / Task 2 above** — a re-execution should use the committed files, not re-transcribe
those blocks:

1. **Install racecast as the login user (user-owned tree)** — the frozen binary resolves
   `profiles/` + `runtime/` next to itself and the relay writes runtime state, so a
   root-owned `/opt/racecast` would force `sudo` on every event op and break the onboarding
   path. provision.sh now installs the binary into `~USER/racecast` and runs
   `install-tools`/`install-apps` via `sudo -u "$USER_NAME" -H …` (the passwordless sudo
   from step 6 keeps `install-apps`' internal `sudo apt-get` working). README §4 onboarding
   now scps directly into `~/racecast/profiles/` + `~/racecast/runtime/` with no sudo. (User
   decision: user-home install.)
2. **SIGPIPE-safe GPU probe** — `has_nvidia_gpu()` and the ffmpeg/ldconfig/glxinfo checks
   changed `grep -q X` → `grep X >/dev/null`: under `set -o pipefail`, `grep -q` closes
   stdin on first match, SIGPIPE-ing the upstream (`lspci`/`ldconfig -p`) and making a
   matched pipeline report failure — which could make `has_nvidia_gpu` spuriously skip the
   driver install on a real GPU box. `grep` without `-q` consumes the whole stream, so no
   early close.
