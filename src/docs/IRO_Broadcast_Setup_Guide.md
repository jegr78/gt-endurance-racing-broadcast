# IRO Endurance Broadcast — Setup Guide

A complete production setup. Game streams are pulled straight into OBS with a memory buffer, overlays are switched locally, and a remote Director controls everything from a browser. The Producer only starts and stops the main broadcast.

## How it works (read first)

**Source switching keeps full buffering.** Each channel gets **one Streamlink server** on its own fixed local port, fed by that channel's *permanent* live URL. OBS points at those fixed local ports and never changes. The Director only switches **scenes/sources** (which feed is on screen) — no URLs are ever typed, no processes restarted. This gives Streamlink's ring buffer **and** OBS's own network buffer **and** full remote switching at once. Because Streamlink keeps the session alive, channel links never expire mid-broadcast.

**Quality: 1080p target, never below 720p.**
- *Streamer side:* ingest at **1080p** so YouTube generates both a 1080p and a 720p rendition.
- *Pull side:* Streamlink quality selector `1080p60,1080p,720p60,720p` prefers 1080p and will not drop below 720p.
- *Note:* Streamlink's YouTube plugin occasionally exposes only a subset of qualities. If a channel won't give 1080p via Streamlink, use the per-source yt-dlp fallback (Section 7.4). Keep Streamlink + yt-dlp updated before each event.

---

## 1. Architecture

```
Each Streamer (game + commentary)
   └─ streams to THEIR OWN fixed YouTube channel (1080p, Low latency)
        │   permanent URL:  youtube.com/channel/<CHANNEL_ID>/live
        ▼
Producer PC
   ├─ Streamlink server per channel  → fixed local ports (53001, 53002, …)
   │      • memory ring buffer • prefers 1080p, floor 720p • auto-reconnect
   ├─ OBS Media Source per channel   → http://127.0.0.1:<port>  (never changes)
   ├─ Overlays / HUD                 → OBS Browser Sources (your Google-Sheet HUD)
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

## 2. Tools to install (all free)

| Tool | Installed on | Purpose |
|------|--------------|---------|
| OBS Studio (v30+) | Producer PC | Main broadcast + built-in WebSocket server |
| Streamlink | Producer PC | Pulls each channel's live stream with a buffer |
| yt-dlp + FFmpeg | Producer PC | 1080p fallback / link resolution |
| Bitfocus Companion | Producer PC | The Director's remote button board |
| Tailscale | Producer PC + every Director PC | Private network, no port forwarding |
| Discord | Producer PC + guests | Interview audio |

Downloads: OBS `obsproject.com` · Streamlink `streamlink.github.io` · yt-dlp `github.com/yt-dlp/yt-dlp` · Companion `bitfocus.io/download` · Tailscale `tailscale.com/download`.

---

## 3. PART A — Tailscale (idiot-proof)

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
7. On a Director PC, open a browser and go to `http://100.x.y.z:8000` (the Producer IP from step 3). You will see the Companion admin page once Companion is running (Part C). If it loads, Tailscale works.

> If it does not load later: make sure Tailscale shows "Connected" on both PCs, and that Companion is running on the Producer.

---

## 4. PART B — OBS WebSocket (idiot-proof)

This lets Companion send commands to OBS.

1. Open OBS on the Producer PC.
2. Top menu → **Tools → WebSocket Server Settings**.
3. Tick **Enable WebSocket server**.
4. Leave **Server Port** at `4455`.
5. Tick **Enable Authentication** and type a password you'll remember (e.g. `iro-broadcast`).
6. Click **Show Connect Info** and keep that window handy — you need the Port and Password in Part C.
7. Click **Apply**, then **OK**.

That's the entire WebSocket setup.

---

## 5. PART C — Bitfocus Companion (idiot-proof)

Companion runs on the Producer PC and turns into a web page of buttons the Directors open in a browser.

**Start Companion and open its admin page:**
1. Install and launch Companion. A small **launcher window** appears.
2. In the launcher, under **Network Interface / GUI Interface**, select your normal network (wired or Wi-Fi). Leave the admin port at `8000`.
3. Click **Launch GUI**. Your browser opens `http://localhost:8000` — this is the Companion admin.

**Connect Companion to OBS:**
4. In the admin, go to the **Connections** tab → **Add connection**.
5. Search for **OBS Studio**, select it.
6. Fill in: **Target IP** = `127.0.0.1` (Companion and OBS are on the same PC), **Port** = `4455`, **Password** = the one from Part B step 5.
7. Save. The connection should turn green/"OK". If not, re-check the password and that OBS is open with the WebSocket server enabled.

**Build the Director's buttons (Buttons tab):**
You're laying out a grid. Click any empty button cell to edit it. For each button: set **Button text**, then under **Add action** choose an OBS action.

Suggested layout for page 1:
- **Row 1 — Scenes:** one button each → action **Set Program Scene** → "Stint", "Splitscreen", "Interview", "Standby".
- **Row 2 — Camera/source select** (which Streamlink feed is shown): one button per channel → action **Set Source Visibility** (or a scene-per-feed if you prefer) for "Feed A", "Feed B", etc.
- **Row 3 — Graphics:** one button per overlay → action **Set Source Visibility** → toggle "HUD", "Standings", "Race Info", "Interview Lower-third".
- **Row 4 — Audio:** per feed → actions **Set Input Mute** (toggle) and **Set Input Volume** (+/- buttons).

Make buttons show their state with **feedback**:
- In a button's editor → **Add feedback** → e.g. **Source Visible** or **Scene Active** → pick a highlight color. Now the button lights up when that scene/source is live, so the Director always sees what's on air.

Tip: one button can hold **multiple stacked actions** — e.g. a single "Go to Interview" button that switches to the Interview scene *and* shows the lower-third *and* unmutes Discord.

**Give the Directors access (web buttons over Tailscale):**
8. In Companion admin, find the **web buttons / tablet** page link (served on port `8000`). The Directors open it in their browser using the **Producer's Tailscale IP**, e.g. `http://100.x.y.z:8000/tablet`.
9. Multiple Directors can open it at once. They need nothing else — no OBS, no Companion, no password.

> Same-machine case: if the Producer is also the Director on this PC, they can simply use OBS directly or the local Companion page (`http://localhost:8000/tablet`). Companion only matters for *remote* Directors.

---

## 6. PART D — Python, pip & FFmpeg (install before Streamlink)

Streamlink and yt-dlp are Python programs, and they need FFmpeg. Don't assume the Producer PC already has these. Do this **once** per machine. If `python --version`, `pip --version` and `ffmpeg -version` all already print a version, skip to Part E.

### Windows
1. Go to `python.org/downloads`, click the big **Download Python** button (3.11 or newer).
2. Run the installer. **CRITICAL:** on the first screen tick **“Add python.exe to PATH”** at the bottom, *then* click **Install Now**. (If you forget this, nothing below will work.)
3. When it finishes, close and re-open any open terminal windows.
4. Open **Command Prompt** (Start → type `cmd` → Enter) and check:
   ```
   python --version
   pip --version
   ```
   Both should print a version number.
5. Install the tools:
   ```
   pip install -U streamlink yt-dlp
   ```
6. Install **FFmpeg** (Streamlink/yt-dlp need it to remux):
   - Easiest: open **PowerShell** and run `winget install Gyan.FFmpeg`, then re-open the terminal.
   - Manual alternative: download a build from `gyan.dev/ffmpeg/builds` (the “release essentials” zip), unzip it, and add its `bin` folder to your PATH.
7. Confirm:
   ```
   streamlink --version
   ffmpeg -version
   ```

### macOS
1. Install **Homebrew** (a one-line package manager). Open **Terminal** (Cmd+Space → type `Terminal`) and paste:
   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Follow the prompts (it may ask for your password). When it finishes, it prints two `echo … >> ~/.zprofile` lines — run them so `brew` is on your PATH, then close and re-open Terminal.
2. Install everything in one go (this also pulls in Python):
   ```
   brew install streamlink yt-dlp ffmpeg
   ```
3. Confirm:
   ```
   streamlink --version
   yt-dlp --version
   ffmpeg -version
   ```

> **`pip` not found / “externally managed environment” error?** On some systems use `pip3` instead of `pip`, or `python -m pip install -U streamlink yt-dlp`. On macOS, prefer the `brew install` route above — it avoids this entirely.

> **Update before every event:** Windows `pip install -U streamlink yt-dlp` · macOS `brew upgrade streamlink yt-dlp`. YouTube changes often; outdated tools are the #1 cause of a feed failing to start.

---

## 7. PART E — Streamlink feeds (the buffering + 1080p engine)

### 7.1 Get each streamer's permanent channel URL
Every regular streamer/commentator uses **one fixed YouTube channel**. The permanent live URL is:

```
https://www.youtube.com/channel/<CHANNEL_ID>/live
```

This URL always points to whatever that channel is currently streaming, so it never changes between events. To find a channel's ID: open the channel → it's the `UC…` string in `youtube.com/channel/UC…`, or the channel owner can read it in YouTube Studio → Settings → Channel → Advanced. Collect all channel IDs once into your shared Google Sheet.

### 7.2 Update before every event
Tools must be current (see Part D for first-time install):
- Windows: `pip install -U streamlink yt-dlp`
- macOS: `brew upgrade streamlink yt-dlp`

### 7.3 Launch one Streamlink server per channel (primary method)
Each channel gets its own fixed local port and a loop so it auto-recovers and waits for the channel to go live. Put this in a single `.bat` file (Windows) and run it at the start of the broadcast:

```bat
@echo off
REM ---- Feed A : Channel 1 on port 53001 ----
start "FeedA" cmd /k loopstream.bat UCxxxxxxxxxxxxxxxxxxxxxx 53001
REM ---- Feed B : Channel 2 on port 53002 ----
start "FeedB" cmd /k loopstream.bat UCyyyyyyyyyyyyyyyyyyyyyy 53002
REM add one line per channel, incrementing the port
```

`loopstream.bat`:
```bat
@echo off
:loop
streamlink "https://www.youtube.com/channel/%1/live" 1080p60,1080p,720p60,720p ^
  --player-external-http --player-external-http-port %2 ^
  --ringbuffer-size 64M --hls-live-edge 6 ^
  --retry-streams 15 --retry-open 5
echo Stream ended or not live, retrying in 10s...
timeout /t 10 >nul
goto loop
```

What the flags do:
- `1080p60,1080p,720p60,720p` — prefer 1080p, fall back no lower than 720p.
- `--player-external-http --player-external-http-port` — serves the feed at `http://127.0.0.1:<port>` for OBS.
- `--ringbuffer-size 64M` — the **memory buffer** that absorbs network hiccups.
- `--hls-live-edge 6` — stay several segments behind live = more buffer, fewer stalls. With streamers on Low latency the segments are small, so 6 keeps a healthy cushion.
- `--retry-streams 15 --retry-open 5` — if the channel isn't live yet (driver hasn't started), keep polling cheaply until they go live, then connect automatically.

Idle channels (streamer not live yet) use almost no bandwidth — they just poll. Only channels that are actually broadcasting consume their full bitrate, so running several servers at once is fine.

For **Twitch** channels add `--twitch-disable-ads` and use the Twitch URL; everything else is identical.

### 7.4 yt-dlp fallback (only if Streamlink can't deliver 1080p for a channel)
```bash
yt-dlp -g "https://www.youtube.com/channel/<CHANNEL_ID>/live"
```
This prints a direct HLS URL. Put it in that feed's OBS Media Source instead of the local port. Downside: the link expires after a few hours, so re-resolve it at the 2-hour stint change. Use this only for the rare channel where Streamlink caps below 1080p.

---

## 8. PART F — OBS scenes & sources

**Create one Media Source per channel:**
1. In OBS, add a **Media Source** (uncheck "Local File").
2. **Input:** `http://127.0.0.1:53001` (the port for that channel).
3. Tick **Use hardware decoding**.
4. Set **Network Buffering** high — `8`–`16` MB (this is OBS's buffer, stacked on top of Streamlink's).
5. Set **Reconnect Delay** to `10` s.
6. Repeat for each channel (53002, 53003, …).

**Create your scenes:**
- **Stint** — the active feed full-screen + HUD overlay.
- **Splitscreen** — two feeds side by side (for the ~10-minute handover).
- **Interview** — interview graphic + Discord audio.
- **Standby / BRB** — for breaks.

**Overlays / HUD as Browser Sources:**
- Add your Google-Sheet-driven HUD as a Browser Source (your spreadsheet keeps updating it live — unchanged).
- Add each info-graphic (standings, schedule, race info, lower-third) as its own Browser Source, left in the scene and toggled by the Director via Companion. No screen-share, no extra latency.

**Discord audio for interviews (Windows):**
- Add source → **Application Audio Capture (BETA)** → select **Discord**. This isolates Discord audio only. (macOS: route Discord through BlackHole and capture that as an audio input.) Don't also capture Discord via desktop audio, or you'll double it.

---

## 9. Streamer requirements (hand this to every streamer)

- **Platform:** your own YouTube channel (or Twitch), stream set to **Unlisted**, always the **same channel** each event.
- **Latency setting:** **Low** — *not* "Ultra-low" unless your connection is rock-solid. Buffering protection lives on the Producer side, so Low gives a responsive feed while staying stable.
- **Resolution:** **1080p target.** If your upload can't reliably sustain ~6 Mbps, drop to **720p — but never below 720p.**
- **Bitrate (CBR), keyframe interval 2 s:** 1080p60 ≈ 8000 kbps · 1080p30 ≈ 6000 kbps · 720p60 ≈ 4500 kbps · 720p30 ≈ 3000 kbps.
- **Audio:** 128–160 kbps AAC, 48 kHz, stereo.
- **Encoder:** hardware (NVENC / QuickSync / AMF) to spare your CPU.
- **No personal overlays/graphics** — those are added centrally by the Producer.
- Provide your **channel ID once** for the shared sheet; you never need to send a per-stream link again.

---

## 10. Runbook

**Before the event (Producer):**
1. Update tools: Windows `pip install -U streamlink yt-dlp` · macOS `brew upgrade streamlink yt-dlp`; confirm FFmpeg (see Part D).
2. Update GPU driver (hardware-encoding the broadcast and decoding the feeds leans on the GPU).
3. Tailscale running; a Director confirms they can open `http://<producer-tailscale-ip>:8000/tablet`.
4. OBS WebSocket on; Companion connected (green); scenes/sources loaded.
5. Run the Streamlink launcher; confirm each live feed appears in its Media Source.
6. Test the Discord audio source.
7. Enter the IRO stream key in OBS.

**Start:** Producer clicks **Start Streaming** in OBS. From here the Director runs the show.

**During a stint:** Director keeps the **Stint** scene on the active feed, toggles HUD/graphics via Companion, adjusts volumes.

**Driver/lobby change (every 2 h):** The incoming streamer goes live on their channel; their Streamlink server connects automatically. Director switches to **Splitscreen** for the ~10-minute handover, then to **Stint** on the new feed. Nothing to type.

**Interviews (post-race):** Interviews run at the **end** over Discord voice. The
**producer of the last/only part must join the Discord "Interviews" voice channel
themselves, before race end** — the OBS capture taps the producer's *local* Discord app,
so the Director cannot join remotely. (8 h event = 1 part = always the last part → that
producer always joins; on 12 h / 24 h only the final-part producer joins, earlier
producers skip Discord entirely.) The producer stays muted in OBS until the cut, so
joining early is harmless; keep Discord **windowed, not fullscreen**. Guests join the same
voice channel; the Director confirms the producer is joined, switches to **Interview**,
shows the lower-third, and manages mutes.

**End:** Producer clicks **Stop Streaming**; close the Streamlink windows.

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Buffering / stalls | Raise OBS Network Buffering and/or `--ringbuffer-size`; raise `--hls-live-edge`; confirm the streamer is on **Low** latency (not Ultra-low); check total upload stays under ~70–80 % of real capacity. |
| A feed won't appear | Confirm the streamer is actually live; check that channel's Streamlink window for errors; update streamlink/yt-dlp. |
| Feed stuck at 720p but should be 1080p | Streamlink's YouTube plugin capped it — use the yt-dlp fallback (Section 7.4) for that feed; confirm the streamer is ingesting 1080p. |
| Quality dropped below 720p | Streamer's upload can't sustain it — they should lower fps (720p30) but hold 720p; check their encoder settings. |
| Director can't reach Companion | Tailscale "Connected" on both PCs? Companion running? Using the **Tailscale** IP (100.x.y.z), not a local IP? |
| Companion shows OBS disconnected | OBS open with WebSocket enabled? Port 4455 + correct password in the OBS connection? |
| Picture artifacts | Enable hardware decoding on the Media Source; check the streamer's source bitrate. |
| Interview audio doubled/echo | Capture Discord only via Application Audio Capture, not also via desktop audio. |
| One machine overloaded (Producer = Director) | Hardware-encode the broadcast; current GPU driver; hardware-decode every Media Source; lower a streamer to 720p30 if upload is tight. |

---

## 12. Roles at a glance

- **Streamer:** streams their stint to their fixed channel per Section 9. Provides channel ID once.
- **Producer:** runs OBS + Streamlink + Companion + Discord + Tailscale on one PC; only starts/stops the IRO broadcast live.
- **Director (remote):** controls scenes, feeds, volume, mute and graphics from a browser via Companion over Tailscale — no software beyond a browser. Multiple Directors supported; the Producer can also take this role locally.
