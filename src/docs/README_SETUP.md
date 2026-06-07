# IRO Endurance Broadcast — Setup Package (for new producers / colleagues)

This package sets up a complete producer station: OBS scenes + HUD,
Companion button board, director panel and the Streamlink feed scripts.
Follow the steps **in this order**.

> Background on every tool is in **`IRO_Broadcast_Setup_Guide.md`**
> (Parts A–G + runbook). This README is the short checklist for the package.

---

## System Requirements

Run `iro preflight` on the producer machine before every event —
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
the pre-flight check and resolve any FAIL/WARN before going live. The lower-third
HUD is a **single** relay-served Browser Source (`http://127.0.0.1:8088/hud`) —
the relay must be running for the HUD to show. Live HUD values are
edited in the sheet's **Overlay** tab; team→manufacturer logos come from a
**`Brand Name`** text column in the **Configuration** tab, resolved against bundled
assets in `src/assets/flags/` and `src/assets/brands/`.

---

## 0. Get the `iro` tool

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

The first run also creates a `.env` file next to the binary (you fill it in at
step 2). **Do not move the folder after the OBS import** — OBS stores absolute
image paths. Moved it? Redo step 2 + the OBS import.

> **One-time OS warning** (the binary is unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

All commands below are written as `iro …` — type them in a terminal in this
folder (macOS/Linux: `./iro …` unless you add the folder to your PATH).

## 1. Install the apps and tools (once)

```bash
iro install-apps
```

Installs whichever of these are missing — **OBS Studio**, **Bitfocus Companion**,
**Tailscale**, **Discord** — via winget (Windows), Homebrew (macOS), or apt +
official vendor installers (Linux). It lists the steps and asks before running.

```bash
iro install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg`, and `deno` — they pull each
commentator's stream into OBS and pass YouTube's bot check. **`deno` is required**
for the relay (otherwise pulls fail with "Sign in to confirm you're not a bot").

<details>
<summary>Alternative: install apps and tools manually</summary>

| App | What it's for | Download |
|---|---|---|
| **OBS Studio** (v30+) | The broadcast itself | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | The director's button board | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | Private network so remote directors can connect | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | Interview audio | [discord.com/download](https://discord.com/download) |

- **macOS (tools):** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows (tools):** `winget install yt-dlp.yt-dlp Streamlink.Streamlink Gyan.FFmpeg DenoLand.Deno`
- **Linux (tools):** `brew install streamlink yt-dlp ffmpeg deno`, or distro packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

## 2. Add your secrets (`.env`)

The first `iro` run created a `.env` file next to the binary. Open it in any text
editor and fill in the required value from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- *(optional)* `IRO_SHEET_PUSH_URL` — Apps Script write webhook for the relay-hosted
  race timer (enables cross-machine countdown sync). See the Sheet-Webhook wiki page.

Keep `.env` private; never share it.

## 3. Set up OBS

### 3a. Import the scene collection

Download the broadcast assets from the sheet first, then localize the collection:

```bash
iro media       # Intro/Outro clips   -> runtime/media/
iro graphics    # broadcast graphics  -> runtime/graphics/
iro setup --out runtime/IRO_Endurance.import.json
```

Then in OBS: **Scene Collection → Import** → pick that file, and switch to it.
(Downloading after the import also works — `iro setup` only warns, and OBS shows
those sources black until the files exist.)

### 3b. OBS WebSocket

**Tools → WebSocket Server Settings** → enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's
OBS connection.

### 3c. Discord audio

The collection ships one **`Discord Audio Capture`** source; `iro setup` realizes it
for the importing OS — no manual source-switching needed.

- **macOS:** `App Audio Capture` (ScreenCaptureKit). Grant OBS **Screen & System Audio
  Recording** permission once (System Settings → Privacy). Keep Discord **windowed**
  (not fullscreen).
- **Windows:** `Application Audio Capture`, bound to `Discord.exe` (any window — window
  titles don't matter). Don't also capture Discord via desktop audio, or you'll double it.
- **Linux:** requires the
  [PipeWire Audio Capture plugin](https://obsproject.com/forum/resources/pipewire-audio-capture.1458/)
  (untested). Install the plugin before importing the collection.
- **Switched production machine / OS?** Re-run `iro setup` and re-import the collection.

## 4. Streamlink feeds — relay mode (recommended for endurance)

Two fixed feeds (A/B) "walk" along a **stint schedule** — Feed A serves stints
1,3,5…, Feed B 2,4,6…. At each handover the off-air feed advances to the next
commentator. OBS stays unchanged (53001/53002).

*How it pulls:* the relay uses **yt-dlp** to resolve each live HLS URL (passing
YouTube's bot-check via cookies + deno JS-challenge solving) and **streamlink** to
serve that direct URL to OBS. So `cookies.txt` (step 4c below) + `deno` (step 1)
are both required for reliable pulls.

### 4a. Fill the schedule

Fill the sheet tab `Schedule` with watch URLs (unlisted format:
`https://www.youtube.com/watch?v=VIDEOID`) per stint. The director or streamer
enters their watch URL shortly before their stint.

### 4b. Start / stop the relay

```bash
iro relay start       # start in background
iro relay stop        # stop it
iro relay logs -f     # tail the log
iro relay run         # foreground / debug mode
```

### 4c. Get YouTube cookies (important — refresh before each event)

```bash
iro cookies firefox   # recommended on every OS (macOS alternatives: safari, chrome, edge)
```

This lets the feeds bypass YouTube's bot check. **Firefox is the recommended
source on every OS** — no prompts, and it works even while Firefox is running.
On **Windows**, Chrome/Edge/Brave cannot be exported (their cookies are
app-bound encrypted since Chrome 127). macOS Chrome/Edge show a Keychain
prompt; Safari needs Full Disk Access. Cookies rotate — refresh before each event.

### 4d. Companion control

Companion's **Generic HTTP Requests** connections drive the relay:

- `Feeds Next` → `http://127.0.0.1:8088/next` *(handover — press once per stint
  change, right after cutting to the new feed)*
- `Feeds Reload` → `http://127.0.0.1:8088/reload` *(edited a cell in the sheet →
  reload the current feed immediately)*
- `Feeds Status` → `http://127.0.0.1:8088/status`

## 4c. Driver-POV PiP (optional)

Show an ad-hoc driver-POV as a small picture-in-picture (bottom-right) over the
active feed in the **Stint** scene. Pulled by a third relay feed on port **53003**
(capped at 720p), independent of the A/B ping-pong.

1. **Schedule it:** put the driver's live watch URL into the Google-Sheet tab
   **`POV`**, cell **A2** (A1 = header `url`). Empty cell = POV off.
2. **Pull it:** press **POV Reload** in Companion → relay resolves + serves it on
   53003 (still hidden). `/status` shows the `pov` block (`state: serving`).
3. **Show it:** press **POV Toggle** → PiP appears bottom-right in Stint.
4. **Audio:** muted by default; **MUTE POV** toggles the mute, **VOL POV UP /
   VOL POV DOWN** adjust its volume.
5. **Done:** **POV Toggle** to hide, then **POV Stop** (frees the pull/bandwidth).

Two rules: **Reload before Toggle (show)**, and **hide + POV Stop when done**.

> **Lead time:** not instant — after **POV Reload** the relay needs ~10–30 s to
> resolve a live stream, and while the driver is not live yet it keeps retrying
> every 15 s (`/status` shows `state: connecting`). Only press **POV Toggle** once
> `/status` reports `state: serving`; OBS takes a few more seconds to connect on
> first show. Plan roughly **5 minutes** from "driver starts streaming" to
> "PiP on air".

## 4d. Intro/Outro clips

```bash
iro media    # -> runtime/media/  (downloads from the Sheet Assets tab)
```

The clip URLs live in the sheet's **Assets** tab as `Intro Video` / `Outro Video`.
You can also override them per-machine via `IRO_INTRO_URL` / `IRO_OUTRO_URL` in
`.env`.

## 4e. Broadcast graphics

```bash
iro graphics    # -> runtime/graphics/<Label>.png
```

Downloads the still-graphics (Overlay, Standings, Schedule, Race/Quali Results,
the three weather overlays, Standby, …) from the sheet **Assets** tab. The sheet
label *is* the filename. Run before `iro setup` and again before each event if
the graphics changed. Missing files: OBS shows that source black until you fetch.

---

## 5. Set up Companion (director button board)

1. Start Companion → launcher → **GUI Interface = All Interfaces**, port `8000` →
   **Launch GUI**.
2. Import the button config:

   ```bash
   iro export companion    # writes runtime/iro-buttons.companionconfig
   ```

   Then in Companion admin: `Import/Export` → **Import** → pick that file.
   Confirm "**Replace** current configuration". ⚠️ This replaces the entire
   Companion config on this station — back up first if it has other content.

3. **OBS connection** (`127.0.0.1:4455`) comes with the import — **without the
   password** (removed for security). → `Connections` → open the OBS entry →
   **enter your OBS WebSocket password (step 3b)** → connection turns green.

4. Buttons (two pages):
   - **Page 1 — show control:**
     - *row 0 — combos:* `SPLIT`, `STINT A`, `STINT B`, `INTERVIEW`, `STANDBY`,
       `INTRO`, `OUTRO` (one-press scene+source presets)
     - *row 1 — scene switches + relay control:* `Stint Scene`, `Split Scene`,
       `Interview Scene`, `Standby Scene`, `Feeds Next`, `Feeds Reload`,
       `Feeds Status`
     - *row 2 — feeds & reloads:* `Feed A Toggle`, `Feed B Toggle`, `POV Toggle`,
       `Feed A Reload`, `Feed B Reload`, `POV Reload`, `POV Stop`
     - *row 3 — graphics & weather:* `Standings`, `Schedule`, `Race Results`,
       `Quali Results`, `Standby Toggle`, `Weather Race (1) Toggle`,
       `Weather Race (2) Toggle`, `Weather Quali Toggle`
   - **Page 2 — audio:**
     - *row 1 — mute:* `MUTE A`, `MUTE B`, `MUTE POV`, `MUTE DISC`
     - *row 2 — volume A/B:* `VOL A DOWN`/`VOL A UP`/`VOL A RESET`,
       `VOL B DOWN`/`VOL B UP`/`VOL B RESET`
     - *row 3 — volume POV/Discord:* `VOL POV DOWN`/`VOL POV UP`/`VOL POV RESET`,
       `VOL DISC DOWN`/`VOL DISC UP`/`VOL DISC RESET`

5. Test: `iro companion open-tablet` (opens the board on Companion's bound
   address), press a button → OBS reacts.

## 6. Remote directors (Tailscale)

Start Companion first (step 5), then:

```bash
iro companion start    # binds Companion to this machine's Tailscale IP
```

- Start/sign in to Tailscale; invite directors at
  `login.tailscale.com/admin/users`.
- Director URL: **`http://<PRODUCER-TAILSCALE-IP>:8000/tablet`** (producer IP via
  `iro tailscale status` — it also confirms Tailscale is actually connected;
  `tailscale ip -4` prints the assigned IP even while disconnected).
- Directors only need a browser — no OBS, no password.

## 7. Director panel (optional backup console)

Companion (steps 5–6) is the primary control surface. The director panel talks to
OBS directly — use it only if Companion is unavailable.

- **Served by the relay (recommended):** `http://<producer-ip>:8088/panel`.
- **As a file:** open `director-panel.html` directly (via `file://` or `http://`,
  **not** `https://`).

Either way it connects straight to OBS — the director must enter the OBS IP +
port `4455` + WebSocket password. That password requirement is exactly why
Companion is preferred for directors.

---

## Important notes / pitfalls

- **Do not move the folder after the OBS import** (absolute image paths). Moved it
  → redo `iro setup` + re-import.
- **OBS WebSocket password:** NOT included in the Companion export — enter it once
  after import (`Connections` → OBS). Set the same password in OBS (step 3b).
- **HUD & graphics** pull live data from the shared Google Sheet — a shared production
  resource. The sheet must stay shared.
- **Discord** must run in **windowed mode** (macOS audio capture).
- Before every event update the tools: `iro install-tools --update` (manual
  alternative: `brew upgrade …` on macOS / `winget upgrade …` on Windows).

## Relay-mode quickstart (short version)

1. Fill the sheet tab `Schedule` with watch URLs (unlisted) per stint.
2. Get YouTube cookies: `iro cookies firefox` (log into YouTube in Firefox first).
3. Start the relay: `iro relay start`.
4. Companion buttons `Feeds Next` (`/next`) & `Feeds Reload` (`/reload`) drive
   handovers.

> **Public channels only?** The simpler static mode (`iro streams start`) skips the stint schedule and cookies — it is described in the Setup Guide (§9.5).
