# GPU box provisioning (cloud-producer spike, #395)

`provision.sh` brings a fresh GCP GPU VM (Ubuntu 24.04, amd64) to "ready to onboard a
league": NVIDIA driver, xfce desktop (autologin), Firefox (deb), RustDesk, passwordless
sudo, Tailscale join, plus the racecast toolchain and applications (`install-tools` /
`install-apps`). It installs only what racecast does not cover and delegates the rest to
the racecast binary — it never re-implements the OBS/Tailscale installers.

**Log in as `racecast`.** You connect to the box **directly as the `racecast` user**
(`gcloud compute ssh racecast@racecast-box`); the GCP guest agent auto-creates that user on
first connect (OS Login is off → metadata SSH keys). `provision.sh` then installs the whole
event stack **directly into `/home/racecast`** (binary at `/home/racecast/racecast`, with
`profiles/` + `runtime/` alongside — the home IS the install root, no nesting). Because you
ARE `racecast`, every event command is plain `racecast <cmd>` — no `sudo`, no second user.

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
gcloud compute instances create racecast-box \
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

The `racecast@racecast-box` login (below) relies on **OS Login being off** so metadata SSH
keys create the `racecast` user. That is the GCP default. If your project/org **enforces**
OS Login (usernames are then derived from your Google identity, not `racecast`), either
turn it off for this box — add `--metadata enable-oslogin=FALSE` to the create above — or
keep OS Login and drive racecast through the service user with `sudo -iu racecast racecast
<cmd>` instead of the plain login.

## 2. Provision (once)

Connect **as `racecast`** (the `racecast@` prefix — first connect creates the user), then
run the script. **Manual, with output on screen (recommended for the first setup):**

```bash
gcloud compute scp tools/cloud/provision.sh racecast@racecast-box:~/ --zone=europe-west4-c
gcloud compute ssh racecast@racecast-box --zone=europe-west4-c
  $ sudo ./provision.sh        # idempotent — re-run after any red line
```

**Reproduction one-liner — unattended startup-script (any league, from scratch):**

```bash
gcloud compute instances create racecast-box ... \
  --metadata-from-file startup-script=tools/cloud/provision.sh
# watch the log:
gcloud compute instances get-serial-port-output racecast-box --zone=europe-west4-c
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
  access"**, then connect from your laptop to the box's **`100.x` Tailscale IP**. What you
  see is the **`racecast` autologin session** on `:0` (RustDesk mirrors that display) — the
  same session OBS autostarts into, so the desktop, OBS and the install tree all run as
  `racecast`.
- If `nvidia-smi` was not yet ready, reboot once so the autologin X session starts
  (RustDesk needs a running X server).

- **Event day is SSH-only — no RustDesk needed.** The autologin xfce session
  comes up at boot (as `racecast`), and `provision.sh` installs autostart entries so OBS +
  Discord launch with it. From your laptop, `gcloud compute ssh racecast@racecast-box …`
  then plain `racecast preflight` and `racecast event start` — `event start` also
  (re)launches OBS/Discord into the running session over SSH (it sets `DISPLAY=:0`;
  override with `RACECAST_DISPLAY`). RustDesk stays only for the one-time per-league OBS
  scene-collection import.

## 4. Onboard a league (once per league, then reuse)

Not part of `provision.sh` — this is the profile layer. The event tree lives directly in
`/home/racecast` (binary at `/home/racecast/racecast`, with `profiles/` + `runtime/`
alongside). Ship the league as a portable **profile bundle** and import it on the box —
because you SSH in as `racecast`, the whole flow is plain commands:

```bash
# from your laptop, export the league to a portable bundle, copy it to the box:
racecast profile export <league> --out /tmp/<league>.zip                       # (on your laptop)
gcloud compute scp /tmp/<league>.zip racecast@racecast-box:~/ --zone=europe-west4-c
# on the box (logged in as racecast), import + activate + localize:
racecast profile import ~/<league>.zip
racecast profile use <league>
racecast setup            # localize the OBS scene collection for this profile
# then import the localized collection into OBS (GUI over RustDesk, once per league)
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
gcloud compute instances stop  racecast-box --zone=europe-west4-c   # idle ≈ boot disk only
gcloud compute instances start racecast-box --zone=europe-west4-c   # tailnet IP stays stable
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
  racecast **straight into the `racecast` login user's home** (`/home/racecast`, user-owned
  — the binary at `/home/racecast/racecast`, no nested `racecast/` dir) and runs
  `install-tools`/`install-apps` **as that user**. So every event operation — profile
  switch, cookie refresh, relay runtime writes, `install-tools --update` — runs without
  `sudo`. The apt steps inside `install-apps` use the passwordless sudo the script set up.
  Because you SSH in **as `racecast`** (`gcloud compute ssh racecast@racecast-box`; OS Login
  is off so the guest agent creates that user from the metadata key), there is no second
  account and no `sudo -iu` — you simply are the owner of the tree.
- NVENC proof (that OBS uses the T4 encoder, not a silent x264 fallback) is the runbook's
  Appendix B checklist (#421).
