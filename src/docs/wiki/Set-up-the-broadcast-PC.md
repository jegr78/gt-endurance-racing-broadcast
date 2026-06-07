# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

> Tip: `iro preflight` checks your machine and tells you what's still missing.
> Run it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A wired internet connection.
- A **YouTube login** (for cookies) and the **shared Google Sheet** link from the team.

## Never used a terminal?

Sixty seconds of background, and every command on this page makes sense:

- **Open a terminal in a folder.** Windows: open the folder in Explorer,
  right-click an empty spot → **Open in Terminal**. macOS: right-click the
  folder in Finder → **Services → New Terminal at Folder** (or open
  **Terminal** via Spotlight, type `cd `, drag the folder into the window,
  press Enter). Linux: most file managers — right-click → **Open Terminal
  Here**.
- **You get a prompt** — a line ending in `$`, `%`, or `>`. Type or paste a
  command (paste: `Ctrl+V`, macOS `Cmd+V`), press **Enter**, and read what
  comes back.
- Nothing runs until you press Enter, and the commands in this wiki only act
  on the `iro` folder.

## 1 — Get the `iro` tool

*Takes ~5 minutes.*

Download the archive for your OS from the
[latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest):

| OS | File |
|---|---|
| Windows | `iro-windows.zip` |
| macOS | `iro-macos.tar.gz` |
| Linux | `iro-linux.tar.gz` |

Extract it into a folder of its own (e.g. `Documents/IRO/`) — the tool keeps its
working files (`.env`, `runtime/`) next to the binary. Open a terminal **in that
folder** (first time? [Never used a terminal?](#never-used-a-terminal)) and
check it runs:

```bash
./iro --version          # Windows: iro --version   (PowerShell: .\iro)
```

The first run also creates a `.env` file next to the binary (you fill it in at
step 4).

**You should now see:** the version number printed in the terminal, and a new
`.env` file next to the binary.
<!-- screenshot: terminal open in the iro folder with ./iro --version output -->

> **One-time OS warning** (the binary is unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

All commands in this wiki are written as `iro …` — type them in a terminal in
this folder (macOS/Linux: `./iro …` unless you add the folder to your PATH).
Updating later is one command: `iro update`.

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/iro.py …` wherever the docs say `iro …`, and copy
`.env.example` to `.env` in the repo root yourself.
</details>

### The short way: `iro init`

One command walks through the automatable steps on this page in order — it
installs the tools and apps, exports YouTube cookies, downloads graphics and
media, builds the OBS import collection, writes the Companion button config,
and finishes with the preflight report:

```
iro init
```

It skips whatever is already done, so re-running it is always safe. It pauses
for the things only you can do: filling in `.env` and — when cookies are
missing or stale — logging into YouTube in Firefox (cookie details and the
before-each-event refresh:
[Relay — how the feeds work](Relay-Mode#2-get-youtube-cookies-before-each-event)).
At the end it prints the remaining manual steps (importing the OBS collection
and the Companion config, signing in to Tailscale) — those are described in
detail in the sections below, and letting Companion control OBS (section 7)
still needs its one-time manual setup too.

Flags: `--browser NAME` (cookie export browser, default `firefox`),
`--skip-installs` (no admin rights), `--force` (re-run every step).

The sections below remain the full reference — use them when a single step
needs repeating or debugging.

## 2 — Install the apps

*Takes ~5–10 minutes (downloads).*

```bash
iro install-apps
```

Installs whichever of these are missing — **OBS Studio** (the broadcast itself),
**Bitfocus Companion** (the director's button board), **Tailscale** (private
network so remote directors can connect), **Discord** (interview audio) — via
winget on Windows, Homebrew on macOS, apt + the official vendor installers on
Linux (it lists the steps and asks before running them).

> **Windows:** Companion installs through its interactive wizard — approve the
> **UAC prompt** and click through it (its silent install reports success without
> installing anything). The other apps install silently.

<details>
<summary>Alternative: install them manually</summary>

| App | What it's for | Download |
|---|---|---|
| **OBS Studio** (v30+) | The broadcast itself | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | The director's button board | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | Private network so remote directors can connect | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | Interview audio | [discord.com/download](https://discord.com/download) |
</details>

**You should now see:** OBS Studio, Companion, Tailscale and Discord in your
applications / Start menu.

## 3 — Install the command-line tools

*Takes ~5 minutes.*

```bash
iro install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg` and `deno` — they pull each
commentator's stream into OBS and pass YouTube's bot check. Afterwards **open a
new terminal** ([how?](#never-used-a-terminal)) — installers update the PATH for
new shells only (`iro preflight`
confirms everything is found).

> `deno` is required — without it feeds fail with *"Sign in to confirm you're not a bot."*
> Details: [Relay — how the feeds work](Relay-Mode).

<details>
<summary>Alternative: install them manually</summary>

- **macOS:** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows:** `winget install yt-dlp.yt-dlp Streamlink.Streamlink Gyan.FFmpeg DenoLand.Deno`
- **Linux:** `brew install streamlink yt-dlp ffmpeg deno`, or your distro's packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

**You should now see:** in a **new** terminal, `streamlink --version`,
`yt-dlp --version`, `ffmpeg -version` and `deno --version` each print a version.

## 4 — Add your secrets (`.env`)

*Takes ~2 minutes.*

The first `iro` run created a `.env` file next to the binary. Open it in any
text editor and fill in the required value from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- *(optional)* `IRO_SHEET_PUSH_URL` — the Apps Script write webhook for the relay-hosted
  race timer. Enables Director timer actions to sync to the Sheet so a second producer
  machine takes over with the same countdown. See [Sheet-Webhook](Sheet-Webhook) to set it up.

Keep `.env` private; never share it. Full detail: [Configuration & secrets](Configuration).

**You should now see:** your `.env` containing a filled `IRO_SHEET_ID=…` line.
<!-- screenshot: .env open in an editor with IRO_SHEET_ID filled (value blurred) -->

## 5 — Import the OBS scenes

*Takes ~5 minutes.*

Download the broadcast assets first (they come from the shared Sheet), then
localize and import the collection:

```bash
iro media       # Intro/Outro clips   -> runtime/media/
iro graphics    # broadcast graphics  -> runtime/graphics/
iro setup --out runtime/IRO_Endurance.import.json
```

Then in OBS: **Scene Collection → Import →** pick that file, and switch to it. Don't move
the folder afterwards. (Running `iro setup` before the downloads also works — it only
warns and OBS shows those sources black until the files exist.) The collection already
includes the **Discord Audio Capture** source for the interviews, set up for your OS —
on macOS just grant OBS the *Screen & System Audio Recording* permission and keep
Discord windowed. Step-by-step (incl. Discord audio):
[OBS & scenes](OBS-Setup#5-discord-audio-interviews).

**You should now see:** OBS switched to the imported collection — the scene
list includes Standby / BRB, Stint, Splitscreen, Interview, Intro and Outro.
<!-- screenshot: OBS Scene Collection -> Import dialog with runtime/IRO_Endurance.import.json selected -->
<!-- screenshot: OBS after the import - scene list visible, Standby scene active -->

## 6 — Import the Companion buttons

*Takes ~5 minutes.*

```bash
iro companion start
```

The first run just launches Companion (it creates its config on startup). In the
launcher press **Launch GUI**, then import the provided button config in the admin
(**Import/Export → Import** — `iro export companion` writes it to
`runtime/iro-buttons.companionconfig`). In the import dialog: a **first import**
on a fresh machine → confirm **"Replace current configuration"**; **updating an
existing board** later → choose **"Import, Resetting only Selected Components"**
with the default checkboxes — that keeps Companion's settings, including the
stored OBS WebSocket password (details: [Companion](Companion#import-the-button-board)).
Finally bind the board to the tailnet:

```bash
iro companion restart    # binds Companion to this machine's Tailscale IP
```

(Linux: start and bind Companion manually — automated control is Windows/macOS
only.) Details: [Companion](Companion).

**You should now see:** the IRO buttons in Companion's admin **Buttons** tab.
<!-- screenshot: Companion launcher with the Launch GUI button -->
<!-- screenshot: Companion Import/Export -> Import dialog showing the Reset/Replace choices -->

## 7 — Let Companion control OBS

*Takes ~2 minutes.*

In OBS: **Tools → WebSocket Server Settings →** enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's OBS
connection.

**You should now see:** the OBS connection **green** under Companion →
**Connections**.
<!-- screenshot: Companion Connections tab with the OBS connection green -->
<!-- screenshot: OBS WebSocket Server Settings dialog (enabled, port 4455, authentication on) -->

## 8 — Connect remote directors (Tailscale)

*Takes ~5 minutes.*

Open Tailscale, sign in (free account — this owns your private network), then note this
machine's IP (`100.x.y.z`) from the Tailscale menu. Invite each director (free, up to 6
people) at [login.tailscale.com](https://login.tailscale.com/admin/users); they install
Tailscale and sign in too. A director can then open `http://100.x.y.z:8000/tablet` to drive
the show. More: [Director setup](Director-Setup) (the page to send your directors) and the [Director guide](Director).

**You should now see:** this machine's `100.x.y.z` address in the Tailscale
menu, and your invitation(s) showing in the Tailscale admin console
(directors appear once they accept).
<!-- screenshot: Tailscale menu showing this machine's 100.x.y.z IP -->

## 9 — Pre-flight check

*Takes ~1 minute.*

```bash
iro preflight
```

Fix anything it flags. Then you're ready → [Run an event](Run-an-event).

**You should now see:** every check green — or only warnings you understand
(e.g. Companion not running yet).
<!-- screenshot: iro preflight output with everything green -->
