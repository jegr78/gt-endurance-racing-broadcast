# Run an event

The producer's checklist from go-live to wrap. Assumes the machine is already set up —
if not, do [Set up the broadcast PC](Set-up-the-broadcast-PC) first.

## The shape of an event

```mermaid
flowchart LR
  A["Prepare<br/>reboot, update, cookies"] --> B["Go live<br/>start on Standby, cut to Intro"]
  B --> C["Race<br/>stints and driver changes"]
  C --> D["Interviews<br/>at the end"]
  D --> E["Outro<br/>cut to the Outro clip"]
  E --> F["Wrap up<br/>stop stream and relay"]
```

## One-command bring-up

On the event day, start everything with:

    iro event start

This launches Tailscale, Discord, the relay, OBS and Companion (in that
order) and ends with a readiness report. Re-check any time with
`iro event status` — it verifies the apps and services are running and that
cookies, graphics and the intro/outro clips are present, and names the exact
fix command for anything missing.

> **Before going LIVE:** refresh the HUD overlay browser source in OBS once
> (right-click the source → Refresh) — its auto-refresh is not fully
> reliable.

After the broadcast, `iro event stop` stops the relay and Companion; OBS,
Discord and Tailscale stay running. If OBS is still open, the stop also asks
it (via the OBS WebSocket, port 4455) to drop its connections to the dead
feeds — otherwise OBS would pin the feed ports until it restarts and the next
preflight would warn "port in use". The feed sources reconnect automatically
the next time their scene goes active.

## Before you go live

1. **Update the tool:** `iro update` — picks up the latest release (skip if the team froze the version for the event).
2. **Reboot** the PC (frees memory) and close heavy apps.
3. **Update the tools:** macOS/Linux `brew upgrade streamlink yt-dlp` · Windows
   `winget upgrade yt-dlp.yt-dlp Streamlink.Streamlink`. Outdated tools are the #1
   cause of a feed not starting.
4. **Refresh cookies:** `iro cookies firefox` (log into YouTube in Firefox first).
5. **Refresh the intro/outro clips** (only if their URLs changed):
   `iro media` — pulls the URLs from the Sheet **Assets** tab and
   downloads `runtime/media/intro.mp4` / `outro.mp4`.
6. **Refresh the graphics:** `iro graphics` — pulls every graphic from
   the Sheet **Assets** tab into `runtime/graphics/` (Standings, Schedule, Race/Quali
   Results, the three weather overlays, Standby, …). Run it whenever the sheet graphics
   changed. The **weather** graphics are then available as full-screen toggles during the
   race (see [Director guide](Director)).
7. **Pre-flight check:** `iro preflight` — fix anything it flags.
8. **Start the feeds and apps:** `iro event start` brings up Tailscale, Discord,
   the relay, OBS and Companion in one go. Alternatively, start them individually:
   `iro relay start` then `iro companion start`. Confirm each live feed shows up in
   OBS.
9. Make sure **Companion** is connected (green) and a director can reach
   `http://<producer-tailscale-ip>:8000/tablet`.
10. **Enter the IRO stream key** in OBS (**Settings → Stream**).

## Go live

Start OBS on the **Standby** scene, then click **Start Streaming**. From here the
**director runs the show** — you just keep an eye on the machine. The director opens with
the **Intro**: pressing **INTRO** (Companion) plays the looping intro clip with its own
audio. When the field is ready they cut into the race look (**STINT A** / **Splitscreen**).

## During the race: driver changes

About every two hours the driver/commentator changes. Two feeds take turns so the picture
on air never drops:

```mermaid
flowchart LR
  subgraph nowair["On air"]
    F1["Feed A<br/>current commentator"]
  end
  subgraph ready["Getting ready"]
    F2["Feed B<br/>next commentator"]
  end
  F1 -->|"driver change: press Feeds Next"| F2
  F2 -.->|"next change, roles swap"| F1
```

At each change the director: cuts to **Splitscreen**, sets **Race Control** to *Driver
Swaps* in the sheet, presses **Feeds Next**, updates the **Stint** and **Streamer** cells,
cuts back with **STINT A** / **STINT B** (the incoming feed), then clears **Race Control**.
Full step-by-step: [Director guide](Director#at-a-driver-change). (Why two feeds:
[Relay — how the feeds work](Relay-Mode).)

## During the race: driver POV (optional)

The director can show a driver's stream as a small PiP in the Stint scene. It needs a
**few minutes of lead time** — the driver goes live, the URL goes into the sheet, the
director presses **POV Reload**, and only once the relay reports the pull as `serving`
is there a picture to show. The director drives all of it; on the producer side nothing
is needed beyond the relay already running. Steps and timing:
[Director guide](Director#showing-a-driver-pov-plan-ahead).

## Producer handover (12h/24h multi-part events)

Long events are split into broadcast parts run by different producers, each on
their own machine with their own stream key. Viewers follow via the channel's
end-of-stream redirect; plan a few minutes of deliberate overlap.

The relay does **not** need the previous producer's Feed A/B order — the
ping-pong works from any starting point. `--stint <N>` simply puts stint N on
Feed A and preloads stint N+1 on Feed B; from there `/next` works as usual.
Which feed carries which stint may therefore differ between the parts — that
is fine.

1. Incoming producer: `iro event start --stint <N>` — N is the stint **on air
   right now** (1-based, from the schedule sheet / Discord). Taking over right
   at a stint change (e.g. a part boundary like "end of stint 3"): pass the
   stint that is starting.
2. Verify Feed A shows the expected commentator (`/status` or the OBS
   preview).
3. Start your OBS stream with this part's stream key — the overlap begins.
4. Share your panel/tablet URLs with the directors (`iro event start` prints
   them — just forward).
5. Outgoing producer: stop the stream (the YouTube redirect takes over), then
   `iro event stop`.

Typo, or forgot `--stint`? Fix it **before going live**:
`http://127.0.0.1:8088/set/stint/<N>` repositions both feeds. Like the other
`/set` endpoints it tears a running feed off its stream — not for mid-program
use.

**Same producer runs the next part:** just stop the OBS stream and start it
again with the next part's stream key — the relay keeps running, no `--stint`
needed.

## Interviews (at the end)

Interviews run at the very end over Discord voice. The producer who is on air for the last
part must **join the Discord "Interviews" voice channel personally, before race end** — the
OBS audio is captured from your local Discord, so the director can't join for you. You stay
muted until the director cuts to the Interview scene, so joining early is harmless. (On
12 h / 24 h events only the final-part producer does this.)

## Outro &amp; wrap up

When the interviews and the on-air wrap-up are done, the director presses **OUTRO** — the
looping outro clip plays (with its own audio) and stays on air. After that you can **Stop
Streaming** in OBS at any time, then stop the feeds (Ctrl+C the relay).

---

Something looks wrong? → [If something goes wrong](If-something-goes-wrong).
