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
