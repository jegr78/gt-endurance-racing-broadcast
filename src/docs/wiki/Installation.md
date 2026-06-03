# Installation

Everything below is installed **once** on the producer station (Windows or macOS). After this, go to
[Configuration](Configuration) and [OBS Setup](OBS-Setup).

> Run `python3 src/scripts/preflight.py` (or `scripts/preflight.py` in the package)
> before every event — it checks the tool chain, ports, and YouTube cookies and tells
> you what is missing.

## System requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 6-core modern (Intel 12th-gen i5 / AMD Ryzen 5) | 8-core+ (i7 / Ryzen 7) |
| RAM | 16 GB | 32 GB |
| GPU | hardware encoder (NVIDIA NVENC / Apple Silicon / Intel QSV) | dedicated NVIDIA GPU w/ NVENC |
| Disk | SSD, ≥ 5 GB free | SSD |
| OS | Windows 10/11 64-bit or macOS 13+ | — |
| Network | wired; stable upload headroom for the YouTube push + up to 3 feed pulls | wired gigabit |

**Before each event:** reboot the machine (clears swap and frees RAM), then run the
pre-flight check and resolve any FAIL/WARN before going live. OBS runs many HUD browser
sources plus the live feeds, so **RAM is the most common bottleneck**.

## Tools to install (all free)

| Tool | Installed on | Purpose |
|------|--------------|---------|
| OBS Studio (v30+) | Producer | Main broadcast + built-in WebSocket server |
| Streamlink | Producer | Serves each pulled stream to OBS with a buffer |
| yt-dlp + FFmpeg | Producer | Resolves the live HLS URL (passes YouTube's bot-check) |
| deno | Producer | JS runtime yt-dlp uses to solve YouTube's anti-bot challenge — **required for the relay** |
| Bitfocus Companion | Producer | The director's remote button board |
| Tailscale | Producer + every director | Private network, no port forwarding |
| Discord | Producer + guests | Interview audio |

### macOS (short version)

```bash
# Homebrew first if you don't have it: https://brew.sh
brew install streamlink yt-dlp ffmpeg deno
```

Install **OBS Studio**, **Bitfocus Companion**, **Tailscale** and **Discord** as normal
apps from their websites.

### Windows

```text
python.org/downloads   ->  tick "Add python.exe to PATH", Install Now
pip install -U streamlink yt-dlp
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Then install OBS, Companion, Tailscale and Discord as apps. Confirm with
`streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.

> **Why deno matters:** without it the relay's pulls fail with *"Sign in to confirm
> you're not a bot"*. yt-dlp uses deno to solve YouTube's JS challenge. Streamlink
> alone — even with cookies — is blocked.

> **Update before every event:** macOS `brew upgrade streamlink yt-dlp` ·
> Windows `pip install -U streamlink yt-dlp`. YouTube changes often; outdated tools are
> the #1 cause of a feed failing to start.

---

## Tailscale (private network for remote directors)

This puts the producer and all directors on one private network so directors can reach
Companion — no router settings, no port forwarding.

**On the producer:**
1. Install Tailscale, run it, sign in (Google/GitHub/email — free account). This
   account owns your network ("tailnet").
2. Click the Tailscale icon → note this machine's IP (`100.x.y.z`). **This is the
   producer IP directors will use.**

**Invite directors** (free Personal plan allows up to 6 users):
3. `login.tailscale.com/admin/users` → **Invite users** → each director's email.
4. Each director clicks the invite, makes a free account, installs Tailscale, signs in.

**Test:** on a director machine open `http://100.x.y.z:8000` — once Companion is running
it shows the admin page. If it loads, Tailscale works.

---

## OBS WebSocket (lets Companion control OBS)

1. OBS → **Tools → WebSocket Server Settings**.
2. Tick **Enable WebSocket server**, leave **Port = 4455**.
3. Tick **Enable Authentication** and set a password you'll remember — **use the same
   password in Companion** (see [Companion](Companion)).
4. **Apply** → **OK**.

---

## Companion (install only — buttons come from the config)

1. Install and launch Companion → the launcher window appears.
2. **GUI Interface = All Interfaces (0.0.0.0)** (important for Tailscale access), admin
   port `8000` → **Launch GUI** → your browser opens `http://localhost:8000`.
3. Importing the ready-made button board and connecting it to OBS is covered in
   [Companion](Companion).

Next: [Configuration](Configuration).
