# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

> Tip: `iro preflight` checks your machine and tells you what's still missing.
> Run it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A wired internet connection.
- A **YouTube login** (for cookies), the **shared Google Sheet** link, and the
  **stagetimer** link from the team.

## 1 — Get the `iro` tool

Download the archive for your OS from the
[latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest):

| OS | File |
|---|---|
| Windows | `iro-windows.zip` |
| macOS | `iro-macos.tar.gz` |
| Linux | `iro-linux.tar.gz` |

Extract it into a folder of its own (e.g. `Documents/IRO/`) — the tool keeps its
working files (`.env`, `runtime/`) next to the binary. Open a terminal **in that
folder** and check it runs:

```bash
./iro --version          # Windows: iro --version   (PowerShell: .\iro)
```

The first run also creates a `.env` file next to the binary (you fill it in at
step 4).

> **One-time OS warning** (the binary is unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

All commands in this wiki are written as `iro …` — type them in a terminal in
this folder (macOS/Linux: `./iro …` unless you add the folder to your PATH).

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/iro.py …` wherever the docs say `iro …`, and copy
`.env.example` to `.env` in the repo root yourself.
</details>

## 2 — Install the apps

```bash
iro install-apps
```

Installs whichever of these are missing — **OBS Studio** (the broadcast itself),
**Bitfocus Companion** (the director's button board), **Tailscale** (private
network so remote directors can connect), **Discord** (interview audio) — via
winget on Windows, Homebrew on macOS, apt + the official vendor installers on
Linux (it lists the steps and asks before running them).

<details>
<summary>Alternative: install them manually</summary>

| App | What it's for | Download |
|---|---|---|
| **OBS Studio** (v30+) | The broadcast itself | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | The director's button board | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | Private network so remote directors can connect | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | Interview audio | [discord.com/download](https://discord.com/download) |
</details>

## 3 — Install the command-line tools

```bash
iro install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg` and `deno` — they pull each
commentator's stream into OBS and pass YouTube's bot check.

> `deno` is required — without it feeds fail with *"Sign in to confirm you're not a bot."*
> Details: [Relay — how the feeds work](Relay-Mode).

<details>
<summary>Alternative: install them manually</summary>

- **macOS:** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows:** `pip install -U streamlink yt-dlp` then `winget install Gyan.FFmpeg DenoLand.Deno`
- **Linux:** `brew install streamlink yt-dlp ffmpeg deno`, or your distro's packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

## 4 — Add your secrets (`.env`)

The first `iro` run created a `.env` file next to the binary. Open it in any
text editor and fill in two values from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- `IRO_TIMER_URL` — the stagetimer output link.

Keep `.env` private; never share it. Full detail: [Configuration & secrets](Configuration).

## 5 — Import the OBS scenes

Download the broadcast assets first (they come from the shared Sheet), then
localize and import the collection:

```bash
iro media       # Intro/Outro clips   -> runtime/media/
iro graphics    # broadcast graphics  -> runtime/graphics/
iro setup --out runtime/IRO_Endurance.import.json
```

Then in OBS: **Scene Collection → Import →** pick that file, and switch to it. Don't move
the folder afterwards. (Running `iro setup` before the downloads also works — it only
warns and OBS shows those sources black until the files exist.) Step-by-step:
[OBS & scenes](OBS-Setup).

## 6 — Import the Companion buttons

Open Companion (launcher → **GUI Interface = All Interfaces**, port `8000` → **Launch
GUI**), then import the provided button config (`iro export companion` writes it to
`runtime/iro-buttons.companionconfig`). Details: [Companion](Companion).

## 7 — Let Companion control OBS

In OBS: **Tools → WebSocket Server Settings →** enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's OBS
connection.

## 8 — Connect remote directors (Tailscale)

Open Tailscale, sign in (free account — this owns your private network), then note this
machine's IP (`100.x.y.z`) from the Tailscale menu. Invite each director (free, up to 6
people) at [login.tailscale.com](https://login.tailscale.com/admin/users); they install
Tailscale and sign in too. A director can then open `http://100.x.y.z:8000/tablet` to drive
the show. More: [Director guide](Director).

## 9 — Get YouTube cookies

```bash
iro cookies firefox  # recommended on every OS (macOS alternatives: safari, chrome, edge)
```

This lets the feeds bypass YouTube's bot check. **Firefox is the recommended source on
every OS** — no prompts anywhere, and it works even while Firefox is running. OS notes: on
**Windows**, Chrome/Edge/Brave **cannot** be exported (their cookies are app-bound
encrypted since Chrome 127); on **macOS**, Chrome/Edge show a Keychain prompt and Safari
needs Full Disk Access. Refresh before each event — cookies expire.

## 10 — Discord audio (only the producer who runs interviews)

Interviews happen at the end over Discord voice. Add the Discord audio source in OBS:

- **macOS:** *App Audio Capture* bound to Discord — keep Discord **windowed** (not
  fullscreen) and grant OBS *Screen & System Audio Recording* permission.
- **Windows:** *Application Audio Capture (BETA)* → pick Discord.
- **Linux:** *Application Audio Capture* (PipeWire) or an *Audio Output Capture* monitor
  source — *should work, not yet tested on Linux.*

Don't also capture Discord via desktop audio, or you'll hear it twice.

## 11 — Pre-flight check

```bash
iro preflight
```

Fix anything it flags. Then you're ready → [Run an event](Run-an-event).
