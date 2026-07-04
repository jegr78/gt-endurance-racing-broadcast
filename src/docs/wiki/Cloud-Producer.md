# Remote producer (cloud GPU box)

Run the **producer station** — the relay, OBS, and the broadcast encode/upload — on an
on-demand **GCP GPU instance** instead of your home machine. You keep only your own
commentator stream and the browser [director panel](Run-an-event#the-director-panel-remote-control)
at home. This page is the **event-day operator guide**: start the box, get in, run the show,
send the report, stop the box.

> **One-time build** (create the VM, install the driver/desktop/toolchain) is a separate
> maintainer step — see `tools/cloud/README.md` and the spike runbook in the repo. This page
> assumes the box already exists and was provisioned.

## The model

- **One long-lived instance**, reused for every event by switching
  [league profiles](Profiles) (`racecast profile use <name>`). **Stop it between events**
  — you pay for the GPU only while it runs; the **Tailscale IP stays stable** across
  stop/start.
- **Event day is SSH-only.** The box boots into an autologin desktop and launches OBS +
  Discord automatically; `racecast event start` drives them over SSH. You do **not** need a
  remote-desktop connection for a normal event.
- **RustDesk is the fallback**, only for GUI work: the one-time per-league OBS
  scene-collection import, or hands-on troubleshooting.

The running example below uses the instance name **`spike-gpu`** in zone
**`europe-west4-c`** — substitute your own.

## 1. Start / stop the box

**gcloud (Terminal):**

```bash
gcloud compute instances start spike-gpu --zone=europe-west4-c   # before the event
gcloud compute instances stop  spike-gpu --zone=europe-west4-c   # after — stops GPU billing
```

**Web Console:** Google Cloud Console → **Compute Engine → VM instances** → tick
`spike-gpu` → **Start / Resume** or **Stop** (also in the row's **⋮** menu).

Give the box ~1–2 minutes after start to reach the desktop before you SSH in. The tailnet IP
is unchanged, so all your saved `http://100.x…` bookmarks keep working.

## 2. SSH into the box

**gcloud (Terminal) — simplest, keys handled for you:**

```bash
gcloud compute ssh spike-gpu --zone=europe-west4-c
```

**Web Console:** on the VM instances list, click the **SSH** button — a browser terminal
opens, no local key setup.

**Plain Terminal (direct IP or over Tailscale):** find the external IP once —

```bash
gcloud compute instances describe spike-gpu --zone=europe-west4-c \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

then `ssh <user>@<EXTERNAL_IP>` (or `ssh <user>@100.x.y.z` over the tailnet once the box has
joined — see §5).

> **First connection — go passwordless.** Install your public key once so `ssh` **and**
> `scp` never prompt again:
> ```bash
> ssh-copy-id <user>@<EXTERNAL_IP>
> ```
> After this every later `ssh`/`scp` to the box is key-based and silent. The **gcloud**
> method already manages keys for you, so `ssh-copy-id` is only for the plain-Terminal path.

## 3. Send files to the box

You mainly copy in a **league profile** the first time you onboard it (cookies are handled
on the box — see §6, no upload). The frozen binary looks for `profiles/` and `runtime/`
**next to itself** at `~/racecast/`, so copy straight into that tree.

**gcloud (Terminal):**

```bash
gcloud compute scp --recurse profiles/<league> spike-gpu:~/racecast/profiles/ --zone=europe-west4-c
```

**Plain Terminal (after `ssh-copy-id`, no password):**

```bash
scp -r profiles/<league> <user>@<EXTERNAL_IP>:~/racecast/profiles/
```

**Web Console:** in the browser **SSH** window, use the **⚙ gear → Upload file** (and
**Download file**) menu.

Then on the box: `racecast profile use <league>`.

## 4. Run the event (SSH-only)

From your laptop, once the box is up and you are SSHed in:

```bash
racecast profile use <league>     # pick the league for this event
racecast cookies firefox          # refresh feed cookies on the box (see §6)
racecast preflight                # hardware + tool check — fix anything red
racecast event start              # brings up relay + OBS + Discord in the box's desktop
#   racecast event start --part 2 # mid-event recovery: resume at a later broadcast Part
```

`event start` (re)launches OBS and Discord **into the running desktop session** over SSH
(it sets `DISPLAY=:0`; override with `RACECAST_DISPLAY`). From there you drive everything from
the browser **[Director Panel](Run-an-event#the-director-panel-remote-control)** — including
starting and stopping each **[broadcast Part](Run-an-event#broadcast-parts-director-panel)**.
No RustDesk needed.

When the event is over:

```bash
racecast event stop               # stops the racecast services (GUI apps keep running)
gcloud compute instances stop spike-gpu --zone=europe-west4-c   # then stop the box (§1)
```

## 5. Join the tailnet

The box must be on your Tailscale network so your laptop reaches the
[Control Center](Control-Center) and `/console/panel` privately (the tailnet is the trust
boundary — the relay's control port is never exposed publicly).

- **Unattended:** provisioning with a `TS_AUTHKEY` (a reusable/ephemeral **tagged**
  pre-auth key) joins the box automatically at build time.
- **Interactive (single persistent box):** on the box, run `sudo tailscale up` — it prints a
  login URL; open it in your **laptop** browser and approve the box into your tailnet.

Verify and use it:

```bash
racecast tailscale status         # confirms the 100.x address
```

Then open the Control Center at **`http://100.x.y.z:8089`** and hand out `/console` links as
usual. To let directors/commentators help **without a Tailscale account**, publish only the
role-gated `/console` page over the Funnel — see
[Remote access & the Funnel](Remote-access).

## 6. Feed cookies — on the box, not uploaded

YouTube (and gated Twitch) feeds need a signed-in browser session. Because **Firefox runs on
the box**, you sign in there once and export locally — nothing is copied from your laptop:

1. Connect once over **RustDesk** (§7) and, in the box's Firefox, sign in to **YouTube** (and
   **Twitch** if the league uses gated Twitch feeds) with your **dedicated racecast Google
   account** — one account covers both.
2. Whenever cookies need refreshing (before an event, or after they expire), export them
   **on the box** over SSH:
   ```bash
   racecast cookies firefox          # YouTube
   racecast cookies twitch firefox   # only for gated Twitch feeds
   ```

Because the cookies are both created **and** used on the box's datacenter IP, there is no
"home-IP session used from a datacenter IP" mismatch to trip the bot-check — an improvement
over the old export-locally-and-upload flow.

## 7. RustDesk — the fallback (GUI work only)

You only need a remote **desktop** for two things: the **one-time OBS scene-collection
import** per league, and hands-on **troubleshooting**. Everything else is SSH.

- One-time (during provisioning): set a **permanent password** and enable
  **RustDesk → Settings → Security → "Enable direct IP access"**.
- Connect from your laptop's RustDesk to the box's **`100.x` Tailscale IP** (direct IP over
  the tailnet — no public relay).
- If the desktop is black / `nvidia-smi` wasn't ready, reboot the box once so the autologin X
  session (which RustDesk shows) starts.

Then, per league, import the localized scene collection into OBS once:

```bash
racecast setup                    # writes runtime/<profile>/GT_Endurance.import.json
# in the OBS GUI over RustDesk: Scene Collection → Import → that file
```

## 8. Post-event report → Discord

After the event, generate the report and send it to the league Discord:

```bash
racecast report                   # build the HTML report into runtime/<profile>/reports/
racecast report send              # attach the newest report to the league Discord
#   racecast report send <FILE>   # or send a specific report file
```

`report send` needs **`DISCORD_WEBHOOK_URL`** in the active league's `profile.env`. You can
also generate and send it from the **Control Center → Post-Event Report** card. Full details:
[Health Monitor → Post-Event Report](Health-Monitor#post-event-report).

## Quick reference

| Task | gcloud | Web Console | Plain Terminal |
|---|---|---|---|
| Start / stop | `gcloud compute instances start\|stop …` | Compute Engine → Start/Stop | — |
| SSH | `gcloud compute ssh …` | **SSH** button (browser) | `ssh <user>@<IP>` (after `ssh-copy-id`) |
| Send files | `gcloud compute scp --recurse …` | SSH window → **⚙ Upload file** | `scp -r … <user>@<IP>:…` |
| Remote desktop | — | — | RustDesk → `100.x` IP (fallback) |

See also: [Run an event](Run-an-event) · [Remote access & the Funnel](Remote-access) ·
[Set up the broadcast PC](Set-up-the-broadcast-PC) · [League profiles](Profiles).
