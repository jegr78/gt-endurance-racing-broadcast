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
`gcloud` authed to your project. **L4 in `europe-west4-c`** is the validated EU default
(T4 was capacity-exhausted across the zones tried; RTT ~20 ms vs ~110 ms to us-central1).
The L4 is bundled into the `g2` machine type — **no `--accelerator` flag**. `g2-standard-4`
(4 vCPU) already passes preflight green: the L4's NVENC offloads OBS's encode, so preflight
detects the GPU and relaxes the CPU-core floor. `g2-standard-8` below is the roomier default —
extra core headroom for a busy multi-feed event, not a preflight requirement:

```bash
gcloud compute instances create spike-gpu \
  --zone=europe-west4-c \
  --machine-type=g2-standard-8 \
  --maintenance-policy=TERMINATE \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-type=pd-standard \
  --boot-disk-size=50GB
```

T4 fallback (needs the flag): `--machine-type=n1-standard-8
--accelerator=type=nvidia-tesla-t4,count=1` (e.g. `us-central1-a`). A create/start can hit
`ZONE_RESOURCE_POOL_EXHAUSTED` — retry across zones.

## 2. Provision (once)

**Default — manual, with output on screen (recommended for the first setup):**

```bash
gcloud compute scp tools/cloud/provision.sh spike-gpu:~/ --zone=europe-west4-c
gcloud compute ssh spike-gpu --zone=europe-west4-c
  $ sudo ./provision.sh        # idempotent — re-run after any red line
```

**Reproduction one-liner — unattended startup-script (any league, from scratch):**

```bash
gcloud compute instances create spike-gpu ... \
  --metadata-from-file startup-script=tools/cloud/provision.sh
# watch the log:
gcloud compute instances get-serial-port-output spike-gpu --zone=europe-west4-c
```

Optional env (never commit these):

- `TS_AUTHKEY` — a reusable/ephemeral **tagged** Tailscale pre-auth key for unattended
  join. When unset, the script prints the one-time `tailscale up` command for you to run
  once (fine for the single persistent box).
- `RACECAST_TAG` — racecast release to install (default `latest` = latest **stable**).
  Set `RACECAST_TAG=preview-main` to install the current `main` preview build. Needed
  until the Linux `install-tools`/`install-apps` fixes reach a stable release —
  apt-update-first (#408/#412) **and** the streamlink-venv (≥ 8.2.0) + obs-pipewire-audio
  plugin installs (#395). Without them a fresh box gets a too-old streamlink (every
  cookie'd YouTube feed aborts) and no Discord audio plugin. `latest` never picks a
  pre-release, so the preview is strictly opt-in. Cut it with `gh workflow run preview.yml
  --ref main` (rolling tag `preview-main`, re-pointed on each run).
- `RUSTDESK_VERSION` — pin a RustDesk release (default in the script; bump if outdated).

The script ends with a green/red verification block. A red line names the step to re-run.

## 3. Finish (once, in the GUI over RustDesk)

These cannot be scripted safely:

- RustDesk: set a permanent password + enable **Settings → Security → "Enable direct IP
  access"**, then connect from your laptop to the box's **`100.x` Tailscale IP**.
- If `nvidia-smi` was not yet ready, reboot once so the autologin X session starts
  (RustDesk needs a running X server).

- **Event day is SSH-only — no RustDesk needed.** The autologin xfce session
  comes up at boot, and `provision.sh` installs autostart entries so OBS +
  Discord launch with it. From your laptop: `gcloud compute ssh spike-gpu … ` then
  `racecast preflight` and `racecast event start` — `event start` also (re)launches
  OBS/Discord into the running session over SSH (it sets `DISPLAY=:0`; override
  with `RACECAST_DISPLAY`). RustDesk stays only for the one-time per-league OBS
  scene-collection import.

## 4. Onboard a league (once per league, then reuse)

Not part of `provision.sh` — this is the profile layer:

The racecast binary lives at `~/racecast/` (user-owned), and the frozen binary looks for
profiles + runtime **next to itself** — so copy straight into that tree:

```bash
# from your laptop, copy the profile into the user-owned tree:
gcloud compute scp --recurse profiles/<league> spike-gpu:~/racecast/profiles/ --zone=europe-west4-c
# on the box (no sudo — the tree is user-owned):
racecast profile use <league>
racecast setup            # localize the OBS scene collection for this profile
# then import the localized collection into OBS (GUI, once per league)
```

**Cookies live on the box** (Firefox is installed here): over RustDesk, sign in to YouTube
(and gated Twitch) in the box's Firefox with the dedicated racecast Google account, then
export them on the box over SSH — `racecast cookies firefox` (+ `racecast cookies twitch
firefox`). No scp from the laptop, and the cookies are created and used on the same
datacenter IP (no session-origin mismatch). The operator-facing walkthrough is the
**Remote producer (cloud GPU box)** wiki page.

Switch between already-onboarded leagues with `racecast profile use <name>`.

## 5. Cost control — stop between events

```bash
gcloud compute instances stop  spike-gpu --zone=europe-west4-c   # idle ≈ boot disk only
gcloud compute instances start spike-gpu --zone=europe-west4-c   # tailnet IP stays stable
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
3. **Fallback.** The live run's headless-X recipe (`nvidia-open` has no `nvidia-xconfig`,
   so `provision.sh` writes `/etc/X11/xorg.conf` by hand — single 1920×1080, BusID from
   `lspci`) is proven. If X still won't start, feed a CustomEDID (fake a 1080p monitor).
   NVENC encoding is independent of the X display, so it is never at risk while the desktop
   display is being tuned.

## Notes

- `provision.sh` runs as root for the machine layer (driver, apt, sudoers) but installs
  racecast into the login user's home (`~/racecast/`, user-owned) and runs
  `install-tools`/`install-apps` **as that user**. So every event operation — profile
  switch, cookie refresh, relay runtime writes, `install-tools --update` — runs without
  `sudo`. The apt steps inside `install-apps` use the passwordless sudo the script set up.
- NVENC proof (that OBS uses the T4 encoder, not a silent x264 fallback) is the runbook's
  Appendix B checklist (#421).
