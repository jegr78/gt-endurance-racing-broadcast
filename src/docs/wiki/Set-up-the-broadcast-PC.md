# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

This page leads with the **[Control Center](Control-Center)** — the web app that
runs setup from your browser, no terminal needed. Every step also shows its
**CLI alternative** (`iro …` in a terminal) for Linux, scripting, or remote
sessions; the two are interchangeable.

> Tip: the Control Center's **Preflight** view (CLI: `iro preflight`) checks your
> machine and tells you what's still missing. Open it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A wired internet connection.
- A **YouTube login** (for cookies) and the **shared Google Sheet** link from the team.

## 1 — Get the tool & open the Control Center

Download the archive for your OS from the
[latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest):

| OS | File |
|---|---|
| Windows | `iro-windows.zip` |
| macOS | `iro-macos.tar.gz` |
| Linux | `iro-linux.tar.gz` |

Extract it into a folder of its own (e.g. `Documents/IRO/`) — the tools keep their
working files (`.env`, `runtime/`) next to them. The archive contains two binaries
that sit side by side: **`iro`** (the CLI) and **`iro-ui`** (the Control Center).

**Open the Control Center:**

| Platform | How |
|---|---|
| Windows | Double-click **`iro-ui.exe`** |
| macOS | Double-click **`iro-ui.app`** |
| Linux | Run `./iro-ui` (or `./iro ui`) in a terminal |

It opens your browser at `http://127.0.0.1:8089/`. The first launch also creates a
`.env` file next to the binaries (you fill it in at step 4).

> **One-time OS warning** (the binaries are unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

> **CLI alternative:** open a terminal in that folder and run `./iro --version`
> (Windows: `iro --version`; PowerShell: `.\iro`). Use `./iro …` wherever this
> wiki says `iro …`. Update later with `iro update`. — Full Control Center tour:
> [The Control Center](Control-Center).

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/iro.py …` wherever the docs say `iro …` (the Control Center
is `python3 src/iro.py ui`), and copy `.env.example` to `.env` in the repo root
yourself.
</details>

### The short way: the Setup wizard

![The Setup wizard in the Control Center](images/cc-setup.png)

In the Control Center, open **Setup**. The wizard walks the automatable steps on
this page in order — installs the tools and apps, exports YouTube cookies,
downloads graphics and media, builds the OBS import collection, and writes the
Companion button config. Each step shows `done` or `pending`; run the pending ones
and watch the output in the Console. It detects what's already done, so re-running
is always safe.

It pauses for the things only you can do: filling in `.env` (step 4) and — when
cookies are missing or stale — logging into YouTube first (cookie details and the
before-each-event refresh:
[Relay — how the feeds work](Relay-Mode#2-get-youtube-cookies-before-each-event)).
The closing **Manual next steps** list covers what no script can do: importing the
OBS collection (step 5) and the Companion config (step 6), and signing in to
Tailscale (step 8). Letting Companion control OBS (step 7) is a one-time manual
setup too.

> **CLI alternative:** `iro init` runs the same wizard in the terminal. Flags:
> `--browser NAME` (cookie export browser, default `firefox`), `--skip-installs`
> (no admin rights), `--force` (re-run every step).

The sections below remain the full reference — use them when a single step needs
repeating or debugging.

## 2 — Install the apps

In the Control Center, open **Apps** and use **Install all** (or run the
`install-apps` step in the Setup wizard).

![The Apps view in the Control Center](images/cc-apps.png)

This installs whichever of these are missing — **OBS Studio** (the broadcast
itself), **Bitfocus Companion** (the director's button board), **Tailscale**
(private network so remote directors can connect), **Discord** (interview audio) —
via winget on Windows, Homebrew on macOS, apt + the official vendor installers on
Linux.

> **Windows:** Companion installs through its interactive wizard — approve the
> **UAC prompt** and click through it (its silent install reports success without
> installing anything). The other apps install silently.

> **CLI alternative:** `iro install-apps`.

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

In the Control Center, open **Tools** and use **Install all** (or run the
`install-tools` step in the Setup wizard).

![The Tools view in the Control Center](images/cc-tools.png)

This installs `streamlink`, `yt-dlp`, `ffmpeg` and `deno` — they pull each
commentator's stream into OBS and pass YouTube's bot check. The Tools view then
shows each one as installed with its version.

> `deno` is required — without it feeds fail with *"Sign in to confirm you're not a bot."*
> Details: [Relay — how the feeds work](Relay-Mode).

> **CLI alternative:** `iro install-tools`. Afterwards **open a new terminal** —
> installers update the PATH for new shells only.

<details>
<summary>Alternative: install them manually</summary>

- **macOS:** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows:** `winget install yt-dlp.yt-dlp Streamlink.Streamlink Gyan.FFmpeg DenoLand.Deno`
- **Linux:** `brew install streamlink yt-dlp ffmpeg deno`, or your distro's packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

## 4 — Add your secrets (`.env`)

In the Control Center, open **Settings** and fill in the required value from the
team. Secret values are masked; comments in the file are preserved.

![The Settings (.env) editor in the Control Center](images/cc-settings.png)

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- *(optional)* `IRO_SHEET_PUSH_URL` — the Apps Script write webhook for the relay-hosted
  race timer. Enables Director timer actions to sync to the Sheet so a second producer
  machine takes over with the same countdown. See [Sheet-Webhook](Sheet-Webhook) to set it up.

Changes apply the next time you (re)start the affected service. Keep `.env`
private; never share it. Full detail: [Configuration & secrets](Configuration).

> **CLI alternative:** the first `iro` run created `.env` next to the binary —
> open it in any text editor.

## 5 — Import the OBS scenes

In the Control Center, open **Assets** and **Download** the graphics and media
(they come from the shared Sheet), then run the `setup` step in the **Setup**
wizard to build the OBS import collection.

![The Assets view in the Control Center](images/cc-assets.png)

Then in OBS: **Scene Collection → Import →** pick `runtime/IRO_Endurance.import.json`,
and switch to it. Don't move the folder afterwards. (Building the collection before
the downloads also works — it only warns, and OBS shows those sources black until
the files exist.) The collection already includes the **Discord Audio Capture**
source for the interviews, set up for your OS — on macOS just grant OBS the
*Screen & System Audio Recording* permission and keep Discord windowed.
Step-by-step (incl. Discord audio): [OBS & scenes](OBS-Setup#5-discord-audio-interviews).

> **CLI alternative:**
> ```
> iro media       # Intro/Outro clips   -> runtime/media/
> iro graphics    # broadcast graphics  -> runtime/graphics/
> iro setup --out runtime/IRO_Endurance.import.json
> ```

## 6 — Import the Companion buttons

In the Control Center, open **Apps** and **Launch** Companion (the Setup wizard's
`export-companion` step writes the button config first). The first launch just
starts Companion — it creates its config on startup.

In Companion's launcher press **Launch GUI**, then import the provided button
config in the admin (**Import/Export → Import** — the config is at
`runtime/iro-buttons.companionconfig`). Finally **Restart** Companion from the
Apps view to bind the board to the tailnet.

(Linux: start and bind Companion manually — automated control is Windows/macOS
only.) Details: [Companion](Companion).

> **CLI alternative:** `iro export companion` (writes the config), then
> `iro companion start` (first launch) and `iro companion restart` (binds
> Companion to this machine's Tailscale IP).

## 7 — Let Companion control OBS

In OBS: **Tools → WebSocket Server Settings →** enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's OBS
connection.

(This one is OBS-side and has no Control Center step. When you open the Director
panel from the Control Center's **Home**, it pre-fills this OBS connection for the
director automatically — see [The Control Center](Control-Center) and the
[Director guide](Director).)

## 8 — Connect remote directors (Tailscale)

Open the Control Center's **Apps** view and **Launch** Tailscale, then sign in
(free account — this owns your private network). Note this machine's IP
(`100.x.y.z`) from the Tailscale menu. Invite each director (free, up to 6 people)
at [login.tailscale.com](https://login.tailscale.com/admin/users); they install
Tailscale and sign in too. A director can then open `http://100.x.y.z:8000/tablet`
to drive the show. More: [Director guide](Director).

> **CLI alternative:** `iro app launch tailscale` (start the app),
> `iro tailscale up` (connect).

## 9 — Pre-flight check

In the Control Center, open **Preflight** and press **Run**. Fix anything it flags.

![The Preflight view in the Control Center](images/cc-preflight.png)

Then you're ready → [Run an event](Run-an-event).

> **CLI alternative:** `iro preflight`.
