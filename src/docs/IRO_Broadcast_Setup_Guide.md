# IRO Endurance Broadcast — Setup Guide

A complete production setup. Game streams are pulled straight into OBS with a memory buffer, overlays are switched locally, and a remote Director controls everything from a browser. The Producer only starts and stops the main broadcast.

## How it works (read first)

**Source switching keeps full buffering.** Each channel gets **one Streamlink server** on its own fixed local port, fed by that channel's *permanent* live URL. OBS points at those fixed local ports and never changes. The Director only switches **scenes/sources** (which feed is on screen) — no URLs are ever typed, no processes restarted. This gives Streamlink's ring buffer **and** OBS's own network buffer **and** full remote switching at once. Because Streamlink keeps the session alive, channel links never expire mid-broadcast.

**Quality: 1080p target, never below 720p.**
- *Streamer side:* ingest at **1080p** so YouTube generates both a 1080p and a 720p rendition.
- *Pull side:* Streamlink quality selector `1080p60,1080p,720p60,720p` prefers 1080p and will not drop below 720p.
- *Note:* Streamlink's YouTube plugin occasionally exposes only a subset of qualities. If a channel won't give 1080p via Streamlink, see the "Feed stuck at 720p" row in the Troubleshooting section (§12). Keep Streamlink + yt-dlp updated before each event.

---

## 1. Architecture

```
Each Streamer (game + commentary)
   └─ streams to THEIR OWN fixed YouTube channel (1080p, Low latency)
        │   permanent URL:  youtube.com/channel/<CHANNEL_ID>/live
        ▼
Producer PC
   ├─ Relay (iro relay start) → fixed local ports (53001, 53002, 53003)
   │      • resolves HLS URLs via yt-dlp • serves via streamlink • auto-reconnect
   ├─ OBS Media Source per channel   → http://127.0.0.1:<port>  (never changes)
   ├─ Overlays / HUD                 → relay-served Browser Source (http://127.0.0.1:8088/hud)
   ├─ Interviews                     → Discord Voice → OBS audio source
   ├─ OBS WebSocket server (on)      → lets Companion control OBS
   ├─ Bitfocus Companion             → button board, served as web buttons
   └─ OBS  ─────────────────────────► YouTube (IRO channel)

Director(s), remote
   └─ Browser over Tailscale → Companion web buttons
         switch scenes / sources, volume, mute, show/hide graphics
```

The Producer's only live job: start and stop the IRO broadcast. Everything else is the Director's, done remotely.

---

## 2. Tools needed (all free)

| Tool | Installed on | Purpose |
|------|--------------|---------|
| OBS Studio (v30+) | Producer PC | Main broadcast + built-in WebSocket server |
| Streamlink | Producer PC | Pulls each channel's live stream with a buffer |
| yt-dlp + FFmpeg | Producer PC | HLS URL resolution / remux |
| deno | Producer PC | JS runtime for YouTube bot-check bypass (**required**) |
| Bitfocus Companion | Producer PC | The Director's remote button board |
| Tailscale | Producer PC + every Director PC | Private network, no port forwarding |
| Discord | Producer PC + guests | Interview audio |

---

## 3. PART A — Get the `iro` tool

Download the archive for your OS from the
[latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest):

| OS | File |
|---|---|
| Windows | `iro-windows.zip` |
| macOS | `iro-macos.tar.gz` |
| Linux | `iro-linux.tar.gz` |

Extract into a folder of its own (e.g. `~/IRO_Broadcast` or `C:\IRO_Broadcast`) —
the tool keeps its working files (`.env`, `runtime/`) next to the binary. Open a
terminal **in that folder** and check it runs:

```bash
./iro --version          # Windows: iro --version  (PowerShell: .\iro)
```

The first run creates a `.env` file next to the binary (you fill it in at Part E).

> **One-time OS warning** (the binary is unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

All commands in this guide are written as `iro …` — type them in a terminal in
this folder (macOS/Linux: `./iro …` unless you add the folder to your PATH).

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/iro.py …` wherever the docs say `iro …`, and copy
`.env.example` to `.env` in the repo root yourself.
</details>

---

## 4. PART B — Tailscale (idiot-proof)

This puts the Producer and all Directors on one private network so the Directors can reach Companion. No router settings, no port forwarding.

**On the Producer PC:**
1. Go to `tailscale.com/download`, download for your OS, run the installer, accept defaults.
2. A browser window opens. Sign in (Google/GitHub/email — create a free account if needed). This account is the "owner" of your network (your "tailnet").
3. After sign-in, Tailscale runs in the system tray/menu bar. Click its icon → you'll see this PC listed with an IP like `100.x.y.z`. **Write that IP down — this is the Producer IP the Directors will use.**

**Invite the Directors (free Personal plan allows up to 6 users):**
4. Go to `login.tailscale.com/admin/users` → **Invite users** → enter each Director's email → send.
5. Each Director clicks the invite link, makes a free account, and installs Tailscale on their PC the same way (steps 1–2).

**On each Director PC:**
6. Install Tailscale, sign in with the invited account, leave it running. Done — they are now on the same private network as the Producer.

**Test it:**
7. On a Director PC, open a browser and go to `http://100.x.y.z:8000` (the Producer IP from step 3). You will see the Companion admin page once Companion is running (Part D). If it loads, Tailscale works.

> If it does not load later: make sure Tailscale shows "Connected" on both PCs, and that Companion is running on the Producer.

---

## 5. PART C — OBS WebSocket

This lets Companion send commands to OBS.

1. Open OBS on the Producer PC.
2. Top menu → **Tools → WebSocket Server Settings**.
3. Tick **Enable WebSocket server**.
4. Leave **Server Port** at `4455`.
5. Tick **Enable Authentication** and type a password you'll remember (e.g. `iro-broadcast`).
6. Click **Show Connect Info** and keep that window handy — you need the Port and Password in Part D.
7. Click **Apply**, then **OK**.

That's the entire WebSocket setup.

---

## 6. PART D — Bitfocus Companion (idiot-proof)

Companion runs on the Producer PC and turns into a web page of buttons the Directors open in a browser.

**Start Companion and open its admin page:**
1. Install and launch Companion. A small **launcher window** appears.
2. In the launcher, under **Network Interface / GUI Interface**, select **All Interfaces**, admin port `8000`.
3. Click **Launch GUI**. Your browser opens `http://localhost:8000` — this is the Companion admin.

**Connect Companion to OBS:**
4. In the admin, go to the **Connections** tab → **Add connection**.
5. Search for **OBS Studio**, select it.
6. Fill in: **Target IP** = `127.0.0.1`, **Port** = `4455`, **Password** = the one from Part C step 5.
7. Save. The connection should turn green/"OK". If not, re-check the password and that OBS is open with the WebSocket server enabled.

**Import the button config:**

```bash
iro export companion    # writes the .companionconfig file
```

In the admin: `Import/Export` → **Import** → pick that file. Confirm "**Replace**
current configuration". ⚠️ This replaces the entire Companion config on this
station — back up first if it has other content.

> The OBS connection (`127.0.0.1:4455`) comes with the import — without the
> password (removed for security). Open `Connections` → OBS entry → enter your
> WebSocket password (Part C) → the connection turns green.

**Give the Directors access (web buttons over Tailscale):**

```bash
iro companion start    # binds Companion to this machine's Tailscale IP
```

Directors open `http://<PRODUCER-TAILSCALE-IP>:8000/tablet` in their browser.
Multiple Directors can open it at once. They need nothing else — no OBS, no
Companion, no password.

---

## 7. PART E — Install apps and tools, add secrets

### 7.1 Install apps and tools

```bash
iro install-apps
```

Installs whichever of these are missing — **OBS Studio**, **Bitfocus Companion**,
**Tailscale**, **Discord** — via winget (Windows), Homebrew (macOS), or apt +
official vendor installers (Linux).

```bash
iro install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg`, and `deno`. **`deno` is required** —
without it feeds fail with "Sign in to confirm you're not a bot."

<details>
<summary>Alternative: install apps and tools manually</summary>

| App | Download |
|---|---|
| **OBS Studio** (v30+) | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | [discord.com/download](https://discord.com/download) |

**macOS (tools):** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))

**Windows (tools):**
```
pip install -U streamlink yt-dlp
winget install Gyan.FFmpeg DenoLand.Deno
```

**Linux (tools):** `brew install streamlink yt-dlp ffmpeg deno`, or distro packages
plus `pip install -U streamlink yt-dlp`.

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

### 7.2 Add your secrets (`.env`)

The first `iro` run created a `.env` file next to the binary. Open it in any text
editor and fill in two values from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- `IRO_TIMER_URL` — the stagetimer output link.

Keep `.env` private; never share it.

---

## 8. PART F — OBS scenes & sources

### 8.1 Import the scene collection

Download the broadcast graphics first (OBS shows a source black until they are present):

```bash
iro graphics    # -> runtime/graphics/<Label>.png
```

Then generate the localized OBS collection:

```bash
iro setup --out runtime/IRO_Endurance.import.json
```

In OBS: **Scene Collection → Import** → pick that file, and switch to it. **Do
not move the folder afterwards** (absolute image paths). Moved it? Redo `iro setup`
+ re-import.

### 8.2 Scene layout

**Create your scenes:**
- **Stint** — the active feed full-screen + HUD overlay.
- **Splitscreen** — two feeds side by side (for the ~10-minute handover).
- **Interview** — interview graphic + Discord audio.
- **Standby / BRB** — for breaks.
- **Intro** / **Outro** — local clip (looping, with audio); download clips with
  `iro media`.

**Overlays / HUD:**
- The lower-third HUD is a relay-served Browser Source at
  `http://127.0.0.1:8088/hud` — it polls the sheet's **Overlay** tab live.
- Each info-graphic (standings, schedule, race info) is toggled by the Director
  via Companion.

**Discord audio:**
- **macOS:** the `Discord Audio Capture` source (type `sck_audio_capture`, app =
  Discord) comes with the collection. Grant OBS **screen & system audio recording**
  once (System Settings → Privacy). Keep Discord in **windowed mode, NOT
  fullscreen**.
- **Windows:** add source → **Application Audio Capture (BETA)** → select Discord.
- Don't also capture Discord via desktop audio — you'll hear it twice.

### 8.3 Media sources (feeds)

Each feed port (53001, 53002, 53003) is already configured in the imported
collection as an OBS Media Source pointing at `http://127.0.0.1:<port>`:

- Tick **Use hardware decoding**.
- Set **Network Buffering** to `8`–`16` MB.
- Set **Reconnect Delay** to `10` s.

---

## 9. PART G — Relay mode (recommended for endurance)

Two fixed feeds (A/B) "walk" along a stint schedule — Feed A serves stints 1,3,5…,
Feed B 2,4,6…. At each handover the off-air feed advances to the next commentator.
OBS stays unchanged (53001/53002).

*How it pulls:* the relay uses **yt-dlp** to resolve each live HLS URL (passing
YouTube's bot-check via cookies + deno JS-challenge solving) and **streamlink** to
serve that direct URL to OBS. Both `cookies.txt` and `deno` are required for
reliable pulls.

### 9.1 Fill the schedule

Sheet tab `Schedule`: one column of entries per stint in order. Use the unlisted
watch URL (`https://www.youtube.com/watch?v=VIDEOID`) — the `/live` URL only works
for public channels. The streamer/director enters their URL shortly before their
stint.

### 9.2 Start / stop

```bash
iro relay start       # start in background
iro relay stop        # stop it
iro relay logs -f     # tail the log
iro relay run         # foreground / debug mode
```

### 9.3 YouTube cookies (refresh before each event)

```bash
iro cookies firefox   # recommended on every OS (macOS alternatives: safari, chrome, edge)
```

You must be **logged into YouTube** in that browser. **Firefox is the recommended
source on every OS** — no prompts, works even while Firefox is running. On
**Windows**, Chrome/Edge/Brave cannot be exported (app-bound encryption since
Chrome 127). macOS Chrome/Edge: approve the Keychain prompt; Safari: grant your
terminal **Full Disk Access**. Cookies rotate — re-run before each event.
`/status` shows `"cookies": true`.

### 9.4 Companion control

Companion's **Generic HTTP Requests** connections drive the relay:

- `Feeds Next` → `http://127.0.0.1:8088/next` *(handover)*
- `Feeds Reload` → `http://127.0.0.1:8088/reload` *(sheet edit → reload current feed)*
- `Feeds Status` → `http://127.0.0.1:8088/status`

### 9.5 Static mode (fallback — public channels only)

For public channels / fixed feeds without a stint schedule:

```bash
iro streams start
iro streams stop
```

---

## 10. Streamer requirements (hand this to every streamer)

- **Platform:** your own YouTube channel (or Twitch), stream set to **Unlisted**, always the **same channel** each event.
- **Latency setting:** **Low** — *not* "Ultra-low" unless your connection is rock-solid. Buffering protection lives on the Producer side, so Low gives a responsive feed while staying stable.
- **Resolution:** **1080p target.** If your upload can't reliably sustain ~6 Mbps, drop to **720p — but never below 720p.**
- **Bitrate (CBR), keyframe interval 2 s:** 1080p60 ≈ 8000 kbps · 1080p30 ≈ 6000 kbps · 720p60 ≈ 4500 kbps · 720p30 ≈ 3000 kbps.
- **Audio:** 128–160 kbps AAC, 48 kHz, stereo.
- **Encoder:** hardware (NVENC / QuickSync / AMF) to spare your CPU.
- **No personal overlays/graphics** — those are added centrally by the Producer.
- Provide your **channel ID once** for the shared sheet; you never need to send a per-stream link again.

---

## 11. Runbook

**Before the event (Producer):**
1. Update tools: `iro install-tools` (or `brew upgrade streamlink yt-dlp` on macOS
   / `pip install -U streamlink yt-dlp` on Windows). YouTube changes often —
   outdated tools are the #1 cause of feeds failing to start.
2. Update GPU driver (hardware-encoding the broadcast and decoding the feeds leans on the GPU).
3. Tailscale running; a Director confirms they can open
   `http://<producer-tailscale-ip>:8000/tablet`.
4. Get cookies: `iro cookies firefox`.
5. Download graphics + media: `iro graphics` and `iro media`.
6. Run `iro setup --out runtime/IRO_Endurance.import.json` and (re-)import into OBS
   if the collection has not been imported yet on this machine.
7. OBS WebSocket on; Companion connected (green); scenes/sources loaded.
8. Start the relay: `iro relay start`.
9. Run the preflight check: `iro preflight`. Fix anything flagged.
10. Enter the IRO stream key in OBS.

**Start:** Producer clicks **Start Streaming** in OBS. From here the Director runs the show.

**During a stint:** Director keeps the **Stint** scene on the active feed, toggles HUD/graphics via Companion, adjusts volumes.

**Handover (every stint change):** The incoming streamer goes live on their channel;
their relay feed connects automatically. Director presses **Feeds Next** in Companion
(right after cutting to the new feed), switches to **Splitscreen** for the ~10-minute
handover, then to **Stint** on the new feed. Nothing to type.

**Interviews (post-race):** Interviews run at the **end** over Discord voice. The
**producer of the last/only part must join the Discord "Interviews" voice channel
themselves, before race end** — the OBS capture taps the producer's *local* Discord
app, so the Director cannot join remotely. (8 h event = 1 part = always the last part
→ that producer always joins; on 12 h / 24 h only the final-part producer joins,
earlier producers skip Discord entirely.) The producer stays muted in OBS until the
cut, so joining early is harmless; keep Discord **windowed, not fullscreen**. Guests
join the same voice channel; the Director confirms the producer is joined, switches to
**Interview**, shows the lower-third, and manages mutes.

**End:** Producer clicks **Stop Streaming**; run `iro relay stop`.

---

## 12. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Feeds fail with "Sign in to confirm you're not a bot" | Re-run `iro cookies firefox`; confirm `deno` is installed (`deno --version`). |
| Buffering / stalls | Raise OBS Network Buffering to 16 MB; confirm the streamer is on **Low** latency (not Ultra-low); check total upload stays under ~70–80 % of real capacity. |
| A feed won't appear | Confirm the streamer is actually live; check `iro relay logs -f` for errors; update streamlink/yt-dlp (`iro install-tools`). |
| Feed stuck at 720p | Streamlink's YouTube plugin capped it — confirm the streamer is ingesting 1080p. If a source channel genuinely streams below 1080p, resolve its direct URL with `yt-dlp -g <channel-url>` and use that URL in a dedicated OBS media source for that stint. |
| Quality dropped below 720p | Streamer's upload can't sustain it — they should lower fps (720p30) but hold 720p. |
| Director can't reach Companion | Tailscale "Connected" on both PCs? `iro companion start` run? Using the Tailscale IP (100.x.y.z), not a local IP? |
| Companion shows OBS disconnected | OBS open with WebSocket enabled? Port 4455 + correct password in the OBS connection? |
| Picture artifacts | Enable hardware decoding on the Media Source; check the streamer's source bitrate. |
| Interview audio doubled/echo | Capture Discord only via Application Audio Capture, not also via desktop audio. |
| One machine overloaded (Producer = Director) | Hardware-encode the broadcast; current GPU driver; hardware-decode every Media Source; lower a streamer to 720p30 if upload is tight. |

---

## 13. Roles at a glance

- **Streamer:** streams their stint to their fixed channel per Section 10. Provides channel ID once.
- **Producer:** runs OBS + relay + Companion + Discord + Tailscale on one PC; starts/stops the IRO broadcast live; runs `iro relay start/stop` and `iro status` to monitor.
- **Director (remote):** controls scenes, feeds, volume, mute and graphics from a browser via Companion over Tailscale — no software beyond a browser. Multiple Directors supported; the Producer can also take this role locally.
