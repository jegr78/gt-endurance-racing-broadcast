# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

> Tip: `python3 src/iro.py preflight` checks your machine and tells you what's still
> missing. Run it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A wired internet connection.
- The **IRO package** (this repo, or the distributed package).
- A **YouTube login** (for cookies), the **shared Google Sheet** link, and the
  **stagetimer** link from the team.

You install everything below in steps 1–3.

## 1 — Install Python

The toolkit's scripts run on Python 3.

- **macOS:** usually preinstalled. If not, install from [python.org/downloads](https://www.python.org/downloads/)
  or `brew install python`.
- **Windows:** download from [python.org/downloads](https://www.python.org/downloads/) and
  **tick "Add python.exe to PATH"** in the installer.
- **Linux:** usually preinstalled. If not: `sudo apt install python3 python3-pip`
  (Debian/Ubuntu) or `sudo dnf install python3 python3-pip` (Fedora).

Check it works: `python3 --version` (on Windows, also try `py --version`).

## 2 — Install the apps

All four are free and run on **macOS, Windows, and Linux**. Install each like any normal
app:

| App | What it's for | Download |
|---|---|---|
| **OBS Studio** (v30+) | The broadcast itself | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | The director's button board | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | Private network so remote directors can connect | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | Interview audio | [discord.com/download](https://discord.com/download) |

## 3 — Install the command-line tools

These pull each commentator's stream into OBS and pass YouTube's bot check.

- **macOS:** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows:** `pip install -U streamlink yt-dlp` then `winget install Gyan.FFmpeg DenoLand.Deno`
- **Linux:** `brew install streamlink yt-dlp ffmpeg deno`, or your distro's packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.

> `deno` is required — without it feeds fail with *"Sign in to confirm you're not a bot."*
> Details: [Relay — how the feeds work](Relay-Mode).

## 4 — Add your secrets (`.env`)

Copy `.env.example` to `.env` in the project root and fill in two values from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- `IRO_TIMER_URL` — the stagetimer output link.

Keep `.env` private; never share it. Full detail: [Configuration & secrets](Configuration).

## 5 — Import the OBS scenes

```bash
python3 src/iro.py setup --out runtime/IRO_Endurance.import.json
```

Then in OBS: **Scene Collection → Import →** pick that file, and switch to it. Don't move
the folder afterwards. Step-by-step: [OBS & scenes](OBS-Setup).

## 6 — Import the Companion buttons

Open Companion (launcher → **GUI Interface = All Interfaces**, port `8000` → **Launch
GUI**), then import the provided button config. Details: [Companion](Companion).

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
python3 src/iro.py cookies chrome   # or firefox / safari / edge — any logged-in browser
```

This lets the feeds bypass YouTube's bot check. OS notes: on **macOS**, Chrome/Edge show a
Keychain prompt and Safari needs Full Disk Access; on **Windows** and **Linux** the browser
export usually runs without a prompt (Firefox needs none anywhere). Refresh before each
event — cookies expire.

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
python3 src/iro.py preflight
```

Fix anything it flags. Then you're ready → [Run an event](Run-an-event).
