# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

> Tip: `racecast preflight` checks your machine and tells you what's still missing.
> Run it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A **wired** internet connection of at least
  **25 Mbps down / 10 Mbps up** (50 / 20 recommended), measured under load — see
  [Internet — bandwidth and wiring](#internet--bandwidth-and-wiring) below for why the
  download side matters as much as the upload.
- A **YouTube login** (for cookies — always required) and, if any stint uses a gated
  Twitch feed, a **Twitch login** too. Plus the **shared Google Sheet** link from the team.

## Internet — bandwidth and wiring

Unlike a typical single-source stream, this station pulls **down** as much as it pushes
**up**, on the same line at the same time: the relay pulls 2–3 live commentator feeds in
while OBS sends one clean program out. **Download matters as much as upload.**

**Download — the relay pulling feeds in**

- **Feed A** (on-air commentator pull, 1080p): ~5–6 Mbps
- **Feed B** (pre-rolled during a handover): ~5–6 Mbps — both feeds run together around
  each driver change, which is the worst case
- **POV** (optional driver picture-in-picture pull): ~3–6 Mbps
- Discord interview audio in + Sheet / Tailscale control: < 0.5 Mbps (negligible)
- **Buffer-ahead bursts:** a fresh pull (e.g. Feed B just before **NEXT**) can momentarily
  spike to ~1.5–2× its steady rate for a few seconds

**Upload — one clean broadcast out to the league channel**

- **Program → YouTube:** 1080p30 ≈ 6 Mbps, 1080p60 ≈ 9 Mbps (CBR, 2 s keyframe). YouTube's
  recommended range for 1080p60 is 4,500–9,000 Kbps (up to ~12,000 if the line allows).
- Discord audio out + director panel / Companion / Tailscale: < 0.5 Mbps — the panel is
  state JSON, not video.

### Minimum vs. recommended (sustained, measured under load)

|                          | Minimum                                              | Recommended                              |
| ------------------------ | ---------------------------------------------------- | ---------------------------------------- |
| **Download**             | **25 Mbps**                                          | **50 Mbps**                              |
| **Upload**               | **10 Mbps**                                          | **20 Mbps**                              |
| Program target supported | 1080p30 @ ~6 Mbps                                    | 1080p60 @ 9 Mbps                         |
| Feeds carried cleanly    | Feed A + Feed B @ 1080p; POV may need 720p / capping | A + B + POV @ 1080p, with burst headroom |
| Headroom                 | program ≈ 60–70% of upload                           | program ≈ ~45% of upload                 |

These are sized for the **handover** worst case: pulling a fresh (bursting) Feed B
alongside Feed A and an optional POV *down* while pushing the program *up*, all in the
same few seconds.

### Levers if your line is tight

- **Cap the relay pull quality** (streamlink / yt-dlp format) to 720p to fit the Minimum
  tier, or to absorb a commentator running heavy 1080p60.
- **Wired only.** A Wi-Fi jitter spike at a driver change — pulling a new stream *and*
  pushing the program at once — is the classic failure. Ethernet removes it.
- **Measure under combined load**, not an idle speedtest: with all feeds + the program
  running, sustained upload should stay ≤ ~70% of the line's real capacity.
- **The director's line is separate and light** — a browser panel over Tailscale plus
  watching the public broadcast — and is not part of these numbers.

## The easy way — the Control Center

The release archive contains two binaries: **`racecast`** (the CLI used throughout this
page) and **`racecast-ui`** (the **[Control Center](Control-Center)**, the recommended
way to set up the station). Download it (step 1), then **double-click `racecast-ui`**
(`racecast-ui.exe` / `racecast-ui.app`; Linux `./racecast-ui`) — it opens at
`http://127.0.0.1:8089/` and its **Setup** view walks you through the install and
asset steps with a progress checklist, no terminal needed.

![The Setup wizard in the Control Center](images/cc-setup.png)

The step-by-step terminal instructions below remain the **full reference** — use
them to repeat or debug a single step, on headless Linux, or if you prefer the
command line. Every step notes its `racecast …` command.

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
  on the `racecast` folder.

## 1 — Get the `racecast` tool

*Takes ~5 minutes.*

Download the archive for your OS from the
[latest release](https://github.com/jegr78/gt-endurance-racing-broadcast/releases/latest):

| OS | File |
|---|---|
| Windows | `racecast-windows.zip` |
| macOS | `racecast-macos.tar.gz` |
| Linux | `racecast-linux.tar.gz` |

Extract it into a folder of its own (e.g. `Documents/Racecast/`) — the tool keeps its
working files (`.env`, `profiles/`, `runtime/`) next to the binary. Open a terminal **in
that folder** (first time? [Never used a terminal?](#never-used-a-terminal)) and
check it runs:

```bash
./racecast --version     # Windows: racecast --version   (PowerShell: .\racecast)
```

The first run also creates a `.env` file next to the binary (you fill it in at
step 4).

**You should now see:** the version number printed in the terminal, and a new
`.env` file next to the binary.

> **One-time OS warning** (the binaries are unsigned — there is no Apple/Windows
> code-signing certificate, so the OS flags the download):
>
> - **Windows:** SmartScreen → "More info" → "Run anyway".
> - **macOS:** right-click → **Open** once (or System Settings → Privacy &
>   Security → "Open Anyway"). **Better**, clear the download quarantine from both
>   binaries in one go — run this in the folder where they live:
>
>   ```bash
>   xattr -dr com.apple.quarantine racecast racecast-ui.app
>   ```
>
>   This removes the prompt **and** stops macOS **App Translocation**: a
>   quarantined `.app` double-clicked from Finder is run from a throwaway,
>   read-only copy under `/private/var/.../AppTranslocation/` instead of your
>   folder, which can make the Control Center misbehave (e.g. the asset previews
>   failing to load). If the prompt ever returns after a manual re-download,
>   run it again.

All commands in this wiki are written as `racecast …` — type them in a terminal in
this folder (macOS/Linux: `./racecast …` unless you add the folder to your PATH).
Updating later is one command: `racecast update`.

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/racecast.py …` wherever the docs say `racecast …`, and copy
`.env.example` to `.env` in the repo root yourself.
</details>

### The short way: the Setup wizard (or `racecast init`)

The Control Center's **Setup** view, and the `racecast init` command, both walk through
the automatable steps on this page in order — they create or select your league
profile, install the tools and apps, export YouTube cookies (and optionally Twitch
cookies), download graphics and media, build the OBS import collection, and write the
Companion button config:

```
racecast init      # the CLI equivalent of the Control Center's Setup view
```

It skips whatever is already done, so re-running it is always safe. It pauses
for the things only you can do: creating/selecting a league profile and filling in
its `SHEET_ID`, and — when cookies are
missing or stale — logging into YouTube in Firefox (cookie details and the
before-each-event refresh:
[Relay — how the feeds work](Relay-Mode#2-producer-accounts-and-cookies-before-each-event)).
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
racecast install-apps
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
racecast install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg` and `deno` — they pull each
commentator's stream (YouTube or Twitch) into OBS and pass YouTube's bot check.
Afterwards **open a new terminal** ([how?](#never-used-a-terminal)) — installers
update the PATH for new shells only (`racecast preflight` confirms everything is
found).

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

## 4 — Create your league profile (secrets)

*Takes ~2 minutes.*

Each league's config lives in its own **profile** (`profiles/<name>/profile.env`), so
one machine can serve several leagues. Create one from the bundled template and make it
active:

```bash
racecast profile new myleague --from example   # copies profiles/example/ -> profiles/myleague/
racecast profile use myleague                  # make it the active league
```

Open `profiles/myleague/profile.env` in any text editor and fill in the values from the team:

- `SHEET_ID` — the ID in the shared Google Sheet link.
- *(optional)* `SHEET_PUSH_URL` — the Apps Script write webhook for the relay-hosted
  race timer. Enables Director timer actions to sync to the Sheet so a second producer
  machine takes over with the same countdown. See [Sheet-Webhook](Sheet-Webhook) to set it up.

Keep the profile private; never share it. The machine-only `.env` (created on first
run) holds just optional switches and needs nothing here. Full detail:
[Configuration & secrets](Configuration).

> **In the Control Center:** the **Profile** view switches leagues, copies a new profile,
> and edits `profile.env` with masked values; **General Settings** edits the machine `.env`.

**You should now see:** `profiles/myleague/profile.env` containing a filled `SHEET_ID=…` line,
and `racecast profile show` listing it as the active league.

## 5 — Import the OBS scenes

*Takes ~5 minutes.*

Download the broadcast assets first (they come from the shared Sheet), then
localize and import the collection:

```bash
racecast media       # Intro/Outro clips   -> runtime/<profile>/media/
racecast graphics    # broadcast graphics  -> runtime/<profile>/graphics/
racecast setup --out runtime/GT_Endurance.import.json
```

> **In the Control Center:** **Assets → Download** fetches the graphics and media;
> the **Setup** view's `setup` step builds the import collection.

Then in OBS: **Scene Collection → Import →** pick that file, and switch to it. The
collection is named after your profile's `OBS_COLLECTION` (the convention is
`GT Endurance Racing — <league>`), so several leagues can co-exist in OBS — switch the
active league's collection later with `racecast obs collection set`. Don't move
the folder afterwards. (Running `racecast setup` before the downloads also works — it only
warns and OBS shows those sources black until the files exist.) The collection already
includes the **Discord Audio Capture** source for the interviews, set up for your OS —
on macOS just grant OBS the *Screen & System Audio Recording* permission and keep
Discord windowed. Step-by-step (incl. Discord audio):
[OBS & scenes](OBS-Setup#5-discord-audio-interviews).

**You should now see:** OBS switched to the imported collection — the scene
list includes Standby / BRB, Stint, Splitscreen, Interview, Intro and Outro.

## 6 — Import the Companion buttons

*Takes ~5 minutes.*

```bash
racecast companion start
```

The first run just launches Companion (it creates its config on startup). In the
launcher press **Launch GUI**, then import the provided button config in the admin
(**Import/Export → Import** — `racecast export companion` writes it to
`runtime/<profile>/racecast-buttons.companionconfig`). In the import dialog: a **first import**
on a fresh machine → confirm **"Replace current configuration"**; **updating an
existing board** later → choose **"Import, Resetting only Selected Components"**
with the default checkboxes — that keeps Companion's settings, including the
stored OBS WebSocket password (details: [Companion](Companion#import-the-button-board)).
Finally bind the board to the tailnet:

```bash
racecast companion restart    # binds Companion to this machine's Tailscale IP
```

(Linux: start and bind Companion manually — automated control is Windows/macOS
only.) Details: [Companion](Companion).

**You should now see:** the broadcast buttons in Companion's admin **Buttons** tab.

## 7 — Let Companion control OBS

*Takes ~2 minutes.*

In OBS: **Tools → WebSocket Server Settings →** enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's OBS
connection. (OBS's own walkthrough: the
[Remote Control Guide](https://obsproject.com/kb/remote-control-guide).)

**You should now see:** the OBS connection **green** under Companion →
**Connections**.

## 8 — Connect remote directors (Tailscale)

*Takes ~5 minutes.*

Open Tailscale, sign in (free account — this owns your private network), then note this
machine's IP (`100.x.y.z`) from the Tailscale menu
([how Tailscale assigns IPs](https://tailscale.com/kb/1033/ip-and-dns-addresses)). Invite
each director (free, up to 6
people) at [login.tailscale.com](https://login.tailscale.com/admin/users); they install
Tailscale and sign in too. A director can then open `http://100.x.y.z:8000/tablet` to drive
the show. More: [Director setup](Director-Setup) (the page to send your directors) and the [Director guide](Director).

**You should now see:** this machine's `100.x.y.z` address in the Tailscale
menu, and your invitation(s) showing in the Tailscale admin console
(directors appear once they accept).

## 9 — Pre-flight check

*Takes ~1 minute.*

```bash
racecast preflight
```

> **In the Control Center:** the **Preflight** view runs the same check — press **Run**.

Fix anything it flags. Then you're ready → [Run an event](Run-an-event).

**You should now see:** every check green — or only warnings you understand
(e.g. Companion not running yet).
