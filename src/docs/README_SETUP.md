# IRO Endurance Broadcast — Setup Package (for new producers / colleagues)

This package sets up a complete producer station: OBS scenes + HUD,
Companion button board, director panel and the Streamlink feed scripts.
Follow the steps **in this order**.

> Background on every tool is in **`IRO_Broadcast_Setup_Guide.md`**
> (Parts A–F + runbook). This README is the short checklist for the package.

---

## System Requirements

Run `python3 scripts/preflight.py` on the producer machine before every event —
it checks all of the below plus your tool chain, ports, and YouTube cookies.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU       | 6-core modern (Intel 12th-gen i5 / AMD Ryzen 5) | 8-core+ (i7 / Ryzen 7) |
| RAM       | 16 GB | 32 GB |
| GPU       | hardware encoder (NVIDIA NVENC / Apple Silicon / Intel QSV) | dedicated NVIDIA GPU w/ NVENC |
| Disk      | SSD, ≥ 5 GB free | SSD |
| OS        | Windows 10/11 64-bit or macOS 13+ | — |
| Network   | wired; stable upload headroom for the YouTube push + up to 3 feed pulls | wired gigabit |

**Before each event:** reboot the machine (clears swap and frees RAM), then run
the pre-flight check and resolve any FAIL/WARN before going live. OBS runs 14 HUD
browser sources plus the live feeds, so RAM is the most common bottleneck.

---

## 0. Extract the package to a permanent location
Put the extracted folder where it will **stay** (e.g. `~/IRO_Broadcast` or
`C:\IRO_Broadcast`). **Do not move it after the OBS import** — OBS stores
absolute image paths. (Moved it? Just redo step 2 + the OBS import.)

## 1. Install the tools (once)
- **OBS Studio 30+** · **Streamlink + yt-dlp + FFmpeg** · **deno** · **Bitfocus Companion** ·
  **Tailscale** · **Discord**
- Per-OS install commands: see guide **Part A–D**.
  - macOS short: `brew install streamlink yt-dlp ffmpeg deno`, OBS/Companion/Tailscale/Discord as apps.
- **`deno`** is the JS runtime yt-dlp uses to solve YouTube's anti-bot JS challenges — **required for the relay** (otherwise pulls fail with "Sign in to confirm you're not a bot"). Windows: `winget install DenoLand.Deno` (or see deno.land).

## 2. Rewrite the image paths to this folder
This makes the Overlay + 5 graphics + thumbnail show up right after the OBS import,
and injects your Google-Sheet ID into the HUD browser source.
- **Set your Sheet ID first:** `cp .env.example .env`, then put the long ID from your
  HUD sheet URL (`.../spreadsheets/d/<THIS>/edit`) into `IRO_SHEET_ID`.
  (Or pass it inline: `python3 setup-assets.py --sheet-id <ID>`.)
- Open a terminal in this folder → `python3 setup-assets.py`
- Result: **`obs/IRO_Endurance.import.json`** (import this file — not the `.template.` one).

## 3. Set up OBS
1. **Import the scene collection:** OBS → `Scene Collection` → `Import` → `obs/IRO_Endurance.import.json` → then switch to `IRO Endurance`.
2. **Enable WebSocket:** `Tools` → `WebSocket Server Settings` → enable, **port 4455**, **authentication on**, **password = your team password** (the same one used in Companion — see step 5).
3. **Images there?** Overlay/Standings/… should be visible. If not: step 2 didn't run — run it again and re-import.
4. **Discord audio:**
   - The source **`Discord Audio Capture`** comes with the collection (macOS: `sck_audio_capture`, app = Discord).
   - **macOS:** grant OBS **screen & system audio recording** permission once (System Settings → Privacy). **Keep Discord in WINDOWED mode, NOT fullscreen** — otherwise it is not captured.
   - **Windows:** re-create the source as **Application Audio Capture** → pick Discord.
5. **Stream key** of the IRO YouTube channel in OBS (only at event time).

## 4. Streamlink feeds — static mode (per event)
- Put the streamers' channel IDs into the `FEEDS` list in `scripts/start-streams.py`: `(CHANNEL_ID, PORT)` (Feed A→53001, Feed B→53002, …).
- Ports must match the OBS media sources `Feed A`/`Feed B` (`http://127.0.0.1:<port>`).
- Start: `python3 scripts/start-streams.py`. Stop: `python3 scripts/stop-streams.py`.
- *Note:* this static mode is only for **public** channels / fixed feeds. For the typical endurance flow (one commentator per stint, unlisted) → **relay mode 4b**.

## 4b. Relay mode (recommended for endurance)
Two fixed feeds (A/B) "walk" along a **stint schedule** — Feed A serves stints 1,3,5…, Feed B 2,4,6…. At each handover the off-air feed advances to the next commentator. OBS stays unchanged (53001/53002).

*How it pulls (important):* the relay uses **yt-dlp to resolve** each live HLS URL (this is what passes YouTube's bot-check, via cookies + deno JS-challenge solving) and **streamlink to serve** that direct URL to OBS. So `cookies.txt` (step 3 below) + `deno` (step 1) are both required for reliable pulls. Streamlink alone — even with cookies — is blocked by the bot-check.

1. **Schedule = Google Sheet tab `Schedule`** (editable remotely by anyone). One column = entries in stint order; other columns (stint number / name) are ignored.
   - **Unlisted streams → watch URL** `https://www.youtube.com/watch?v=VIDEOID` (the channel `/live` URL only works for PUBLIC streams!). The streamer/director enters their watch URL shortly before their stint.
   - Default sheet = the shared HUD sheet. Other sheet/tab: `--sheet-id …` / `--sheet-tab …`.
2. **Start:** `python3 relay/iro-feeds.py`  (replaces `start-streams`). **Stop:** Ctrl+C.
3. **Cookie hardening (important for the event)** against YouTube's "Sign in to confirm you're not a bot". Easiest — auto-export from your **logged-in** browser via yt-dlp:
   - One-off: `python3 relay/get-cookies.py chrome`  (or `firefox`/`safari`/`edge`/`brave`) → writes `relay/cookies.txt`.
   - Or let the relay do it on start: `python3 relay/iro-feeds.py --cookies-from-browser chrome`.
   - You must be **logged into YouTube** in that browser. macOS **Chrome/Edge**: approve the Keychain prompt; **Safari**: grant your terminal **Full Disk Access**. (Firefox needs neither.)
   - Manual alternative: drop any Netscape `cookies.txt` next to `relay/iro-feeds.py`.
   - It is auto-detected and passed to Streamlink (`--http-cookies-file`). `/status` shows `"cookies": true`. Re-run before each event (cookies rotate).
4. **Companion control** (connection **"Generic HTTP Requests"**, action *GET*):
   - `Feeds Next` → `http://127.0.0.1:8088/next`  *(press once per handover, right after cutting to the new feed)*
   - `Feeds Reload` → `http://127.0.0.1:8088/reload`  *(edited a cell in the sheet → reload the current feed immediately)*
   - `Feeds Status` → `http://127.0.0.1:8088/status`
   - Works for remote directors too (Companion makes the request locally on the producer station).

## 4c. Driver-POV PiP (optional goodie)
Show an ad-hoc driver-POV as a small picture-in-picture (bottom-right) over the active
feed in the **Stint** scene. Pulled by a third relay feed on port **53003** (capped at
720p), independent of the A/B ping-pong.

1. **Schedule it:** put the driver's live **watch URL** into the Google-Sheet tab
   **`POV`**, cell **A2** (A1 = header `url`). Empty cell = POV off.
2. **Pull it:** press **POV Reload** in Companion → the relay resolves + serves it on
   53003 (still hidden). `/status` shows the `pov` block (`state: serving`).
3. **Show it:** press **POV Toggle** → the PiP appears bottom-right in Stint.
4. **Audio:** muted by default; **MUTE POV** toggles the mute, **POV UP / POV DOWN**
   adjust its volume (use briefly).
5. **Done:** **POV Toggle** to hide, then **POV Stop** (frees the pull / bandwidth).

Two rules: **Reload before Toggle (show)**, and **hide + POV Stop when done**. The PiP
lives only in the Stint scene, so switching to Splitscreen/Interview/Standby auto-hides
and auto-silences it — no combo changes needed.

## 5. Set up Companion (director button board)
1. Start Companion → launcher → **GUI Interface = All Interfaces (0.0.0.0)** (important for Tailscale access), admin port `8000` → **Launch GUI**.
2. In the admin: `Import/Export` → **Import** → `companion/iro-buttons.companionconfig`. This is a **full config** → confirm "**Replace** current configuration". ⚠️ This **replaces the entire Companion configuration** on this station (fine for a fresh/dedicated producer station; back up first on a Companion instance with other content!).
3. The **OBS connection** (`127.0.0.1:4455`) comes with it — **but without the password** (removed for security). → `Connections` → open the OBS entry → **enter your OBS WebSocket password (step 3.2)** → the connection turns green.
4. Buttons (two pages):
   - **Page 1 — show control:**
     - *row 0 — combos:* `SPLIT`, `STINT A`, `STINT B`, `INTERVIEW`, `STANDBY` (one-press scene+source presets)
     - *row 1 — scene switches + relay control:* `Stint Scene`, `Split Scene`, `Interview Scene`, `Standby Scene`, `Feeds Reload` (→ `/reload`), `Feeds Next` (→ `/next`, the handover), `Feeds Status` (→ `/status`)
     - *row 2 — feeds & POV:* `Feed A Toggle`, `Feed B Toggle`, `POV Toggle`, `Split Left`, `Split Right`, `POV Reload`, `POV Stop`
     - *row 3 — graphics:* `Standings`, `Schedule`, `Race Results`, `Quali Results`, `HUD Stint Toggle`, `HUD Split Toggle`
   - **Page 2 — audio:**
     - *row 1 — mute:* `MUTE A`, `MUTE B`, `MUTE POV`, `MUTE DISC`
     - *row 2 — volume A/B:* `A DOWN`/`A UP`, `B DOWN`/`B UP`
     - *row 3 — volume POV/Discord:* `POV DOWN`/`POV UP`, `DISC DOWN`/`DISC UP`
5. Test: open `http://localhost:8000/tablet`, press a button → OBS reacts.

## 6. Remote directors (Tailscale)
- Start/sign in to Tailscale; invite the director(s) into the tailnet (`login.tailscale.com/admin/users`).
- Director URL: **`http://<PRODUCER-TAILSCALE-IP>:8000/tablet`** (producer IP via the Tailscale menu / `tailscale ip -4`).
- Directors only need a browser — no OBS, no password.

## 7. Director panel (optional backup console)
Companion (steps 5–6) is the primary control surface and is strictly more capable
(combo buttons, feedback colors, relay `HANDOVER`/`RELOAD`). The director panel is a
**backup** that talks to OBS directly — use it only if Companion is unavailable.

Two ways to open it:
- **Served by the relay (recommended):** the relay (step 4b) serves it at
  **`http://<producer-ip>:8088/panel`**. For remote directors start the relay with
  `--bind 0.0.0.0` (otherwise it is local-only). `--no-panel` disables it.
- **As a file:** open `director-panel.html` directly (via `file://` or `http://`, **not** `https://`).

Either way it then connects **straight to OBS** — so the director must enter the OBS IP
(`127.0.0.1` locally / producer Tailscale IP) + port `4455` + **OBS WebSocket password**.
(That password requirement is exactly why Companion is preferred for directors.)

---

## Important notes / pitfalls
- **Do not move the folder after the OBS import** (absolute image paths). Moved it → redo step 2 + import.
- **OBS WebSocket password:** NOT included in the Companion export — everyone enters it once after import (`Connections` → OBS). Set the same password in OBS (step 3.2).
- **HUD & graphics** pull live data from the **shared Google Sheet** and **stagetimer.io** — these are shared production resources (changes affect everyone). The sheet must stay shared.
- **Discord** must run in **windowed mode** (macOS audio capture).
- Before every event update the tools: `brew upgrade streamlink yt-dlp` (macOS) / `pip install -U streamlink yt-dlp` (Windows).

## Package contents
```
README_SETUP.md              <- this document
IRO_Broadcast_Setup_Guide.md <- full guide (Parts A–F, runbook, troubleshooting)
.env.example                 <- copy to .env, set IRO_SHEET_ID (your HUD/schedule Sheet ID)
setup-assets.py              <- localize OBS asset paths + inject Sheet ID (writes obs/IRO_Endurance.import.json)
assets/                      <- Overlay + graphics + thumbnail (7 PNG)
obs/IRO_Endurance.template.json <- template (placeholder paths) — do NOT import directly
obs/IRO_Endurance.import.json <- produced by step 2 — import THIS one
companion/iro-buttons.companionconfig <- Companion full config (Page 1: combos+scenes+feeds/POV+graphics, Page 2: audio mute/volume, incl. OBS connection, no password)
director-panel.html          <- backup director console (also served by the relay at /panel)
IRO_cheat_sheets.html        <- printable role cards (Streamer/Producer/Director)
scripts/                     <- static-mode launchers (start/stop/loopstream, Python)
relay/iro-feeds.py           <- relay mode (stint schedule from Google Sheet, 2-feed ping-pong)
relay/get-cookies.py         <- export YouTube cookies from your logged-in browser (yt-dlp)
relay/cookies.txt            <- (generated by get-cookies) YouTube cookies vs. bot-check — auto-detected
```

## Relay-mode quickstart (short version)
1. Fill the sheet tab `Schedule` with watch URLs (unlisted) per stint.
2. Get YouTube cookies: `python3 relay/get-cookies.py chrome` (your logged-in browser).
3. Start `python3 relay/iro-feeds.py`.
4. Create Companion buttons `HANDOVER ▶` (`/next`) & `RELOAD ⟳` (`/reload`).
