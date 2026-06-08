# The Control Center

The **Control Center** is a local web app that runs the whole producer station —
first-time setup, event-day bring-up, service control, logs — from your browser,
no terminal needed. It is the recommended way to drive the station. Everything it
does is also available as an `iro …` command (shown as a *CLI alternative*
throughout the operator guides), so the terminal stays a first-class option for
Linux, scripting, and remote sessions.

It is shipped in the same release archive as the CLI: alongside the `iro` binary
you get **`iro-ui`**, the Control Center launcher.

## Launch it

| Platform | How |
|---|---|
| **Windows** | Double-click **`iro-ui.exe`**. |
| **macOS** | Double-click **`iro-ui.app`**. |
| **Linux** | Run `./iro-ui` (or `./iro ui`) — most Linux desktops don't launch a plain binary on double-click. |

It opens your default browser at `http://127.0.0.1:8089/`. Keep `iro-ui` in the
same folder as `iro` and your `.env` — the two binaries sit side by side and
share the `runtime/` folder next to them.

- **Already running?** Launching again just reopens the browser — there is only
  ever one Control Center per machine.
- **Closing the tab** leaves it running in the background. Use the **Quit**
  button (bottom-left) to stop the server. Stopping the Control Center does *not*
  stop the relay, Companion, or streams — those are independent and keep running.
- **Port busy?** Set `IRO_UI_PORT` in `.env` to a free port and relaunch.

> **CLI alternative:** `iro ui` runs the same server in a terminal (add
> `--no-browser` to skip opening a tab). `iro ui` and `iro-ui` are interchangeable.

## Security — keep it local

The Control Center listens on `127.0.0.1` only (this machine). Its API is
unauthenticated and can start installs and stop services, so it is deliberately
**not** reachable from the LAN or the tailnet. Don't put it behind a proxy or
forward its port. (The director's panel and Companion tablet *are* reached over
Tailscale — those are separate, see [Director setup](Director-Setup).)

## A tour of the views

The left sidebar holds every view. The docked **Console** at the bottom streams
the live output of any action you run.

### Home

![Control Center — Home dashboard](images/cc-home.png)

The dashboard. At a glance: how many core services are up, the state of Tailscale,
Discord, OBS, the relay, Companion and the static streams, the race-timer state,
and tiles for Preflight / Assets / Cookies readiness. **Start event** brings the
station up (optional stint number for a mid-event takeover); **Stop event** winds
the `iro` services down. From here you also open the Director panel and copy the
director/tablet links.

> **CLI alternative:** `iro status`, `iro event start [--stint N]`, `iro event stop`.

### Setup

![Control Center — Setup wizard](images/cc-setup.png)

The first-time-setup **wizard**. It detects what is already done and marks each
step `done` or `pending`, with a running "*X of N complete*" summary. Run the
pending steps in order — installs, YouTube cookies, broadcast graphics, intro/
outro media, the OBS scene collection, the Companion config — each streams its
output in the Console. **Re-check all** re-reads the state (e.g. after you fill in
`.env`). The closing **Manual next steps** list covers the imports no script can
do (importing the OBS collection and Companion config, signing in to Tailscale).

> **CLI alternative:** `iro init` runs the same steps in the terminal.

### Preflight

![Control Center — Preflight checks](images/cc-preflight.png)

A read-only hardware and tooling check: RAM, CPU, disk, swap; the four command-
line tools (`yt-dlp`, `streamlink`, `ffmpeg`, `deno`) with versions; and the four
apps (OBS, Companion, Tailscale, Discord). Each line is `PASS` / `WARN` / `INFO` /
`FAIL`. **Run** re-checks.

> **CLI alternative:** `iro preflight`.

### Apps & Tools

![Control Center — Apps](images/cc-apps.png)

**Apps** installs, launches, quits and shows the status of OBS, Companion,
Tailscale and Discord. **Tools** does the same for the command-line tools
(`yt-dlp`, `streamlink`, `ffmpeg`, `deno`), with **Install all** / **Update all**.

![Control Center — Tools](images/cc-tools.png)

> **CLI alternative:** `iro install-apps`, `iro install-tools` (add `--update` to
> upgrade), `iro app launch|quit obs|discord|tailscale`.

### Relay & Static Streams

![Control Center — Relay](images/cc-relay.png)

**Relay** starts / stops / restarts the commentator-feed relay (the normal mode)
and shows its live status. It reads its schedule and HUD data from the Google
Sheet; there are no local relay knobs — ports and bind mode use safe defaults.

![Control Center — Static Streams](images/cc-streams.png)

**Static Streams** is the **fallback** for plain public channels when the relay
mode can't be used. Edit the channel/port list here and start/stop the set.

> **CLI alternative:** `iro relay start|stop|restart|status|logs`,
> `iro streams start|stop`.

### Assets

![Control Center — Assets](images/cc-assets.png)

The broadcast graphics, intro/outro media and YouTube cookies. Thumbnails show
which graphics are present; **Download** fetches them from the Sheet's Assets tab;
**Check vs sheet** compares what's on disk against what the Sheet lists. The
cookies row shows freshness and re-exports with **Refresh**.

> **CLI alternative:** `iro graphics`, `iro media`, `iro cookies <browser>`.

### Settings

![Control Center — Settings (.env)](images/cc-settings.png)

A safe editor for the local `.env` (this machine only). Secret values are
**masked** — click the eye to reveal one. Comments in the file are preserved.
Changes apply the next time you (re)start the affected service.

> **CLI alternative:** edit `.env` in any text editor.

### Logs

![Control Center — Logs](images/cc-logs.png)

Live tail of the relay, Companion and static-stream logs — pick a source from the
dropdown. The example above shows the relay reporting it couldn't reach its Google
Sheet (a misconfigured-sheet state).

> **CLI alternative:** `iro relay logs -f` (and `companion` / `streams`).

### Help & Docs

![Control Center — Help & Docs](images/cc-help.png)

The bundled cheat sheet and setup guides (rendered offline, on this machine) plus
links to the always-current pages on this wiki.

## Where to go next

- **Setting up a machine?** → [Set up the broadcast PC](Set-up-the-broadcast-PC)
- **Running a show today?** → [Run an event](Run-an-event)
- **The remote director?** → [Director setup](Director-Setup), then the
  [Director guide](Director)

---

> This page is generated from `src/docs/wiki/` in the
> [main repository](https://github.com/jegr78/IRO_Broadcast_Setup) — don't edit it
> here by hand. See [Build & maintenance](Build-and-maintenance).
