# Director guide

You direct the show **from a browser** — no OBS, no software, just the Companion buttons.
You never touch the producer's PC. Several directors can take turns, and the producer can
also direct locally.

## Getting connected

1. Make sure Tailscale is running and you've accepted the producer's invite (they set this
   up — see [Set up the broadcast PC](Set-up-the-broadcast-PC)).
2. Open **`http://<producer-tailscale-ip>:8000/tablet`** in your browser. The producer
   gives you that address.
3. The buttons now drive the show. (When a button sends a relay command, Companion runs it
   on the producer's PC for you — so it works from anywhere.)

## The button board

Two pages — **show control** and **audio**. The left column on each page (`UP` / `DOWN`)
flips between them. Everything below is a single tap.

### Page 1 — show control

| Row | Buttons |
|-----|---------|
| **Combos** | `SPLIT`, `STINT A`, `STINT B`, `INTERVIEW`, `STANDBY` — one press sets a whole look (the scene **and** the right feeds and audio) |
| **Scenes + feeds** | `Stint Scene`, `Split Scene`, `Interview Scene`, `Standby Scene`, `Feeds Reload`, `Feeds Next` (the handover), `Feeds Status` |
| **Feeds & POV** | `Feed A Toggle`, `Feed B Toggle`, `POV Toggle`, `Split Left`, `Split Right`, `POV Reload`, `POV Stop` |
| **Graphics** | `Standings`, `Schedule`, `Race Results`, `Quali Results`, `Standby Toggle` (incident cover — see [The race](#through-the-broadcast-scene--sheet-cues)), `HUD Stint Toggle`, `HUD Split Toggle` |

![Companion page 1 — show control: combos, scene switches, feeds & POV, graphics](images/companion-page1-show-control.png)

### Page 2 — audio

| Row | Buttons |
|-----|---------|
| **Mute** | `MUTE A`, `MUTE B`, `MUTE POV`, `MUTE DISC` |
| **Volume A / B** | `A DOWN` / `A UP`, `B DOWN` / `B UP` |
| **Volume POV / Discord** | `POV DOWN` / `POV UP`, `DISC DOWN` / `DISC UP` |

![Companion page 2 — audio: mute and per-source volume for the feeds, POV and Discord](images/companion-page2-audio.png)

> Tip: for the everyday moves, use the **combo** buttons on page 1 (`STINT A`, `SPLIT`,
> `INTERVIEW`, …) — they set the scene and the audio in one tap.

How the board is imported and built: [Companion](Companion).

## Through the broadcast (scene + sheet cues)

As director you drive two things: the **scenes** (Companion) and three **HUD fields in the
shared sheet** — **Stint**, **Session**, and **Race Control**. Each is a dropdown: pick the
listed value, or clear the cell to show nothing. The whole run, in order:

**Before the start**
- Sheet: **Stint → Intro**, **Session → Warmup**.

**Formation lap** — the race always begins with a manual formation lap.
- Sheet: **Race Control → Formation Lap**.
- As the formation lap starts: **Stint → Stint 1**, **Session → Race**.
- Just before the green flag: **clear Race Control**.

**The race**
- Keep the **Stint** scene on the active feed.
- At each commentator change, run the [driver-change steps](#at-a-driver-change) below.
- Incident? Set **Race Control → Red Flag** or **Technical Difficulties** and press
  **Standby Toggle** to hold the picture — it hides the feeds and the POV but keeps the
  Race Control banner and timer visible (the button lights while it's active). When it's
  resolved, press **Standby Toggle** again and **clear Race Control**.

**Final lap** — once you're in the last stint and the leader starts the final lap:
- Sheet: **Race Control → Final Lap**. **Clear it** as soon as the race finishes.

**After the race — interviews**
- Sheet: **Stint → Moderator**, **Session → Interviews** — set these **before** you cut.
- Confirm the producer has joined Discord (see [Interviews](#interviews) below), then cut to
  the **Interview** scene.

**Wrap up**
- When the interviews end, cut back to **Stint** and set **Stint → Outro**,
  **Session → Wrapup**.

## At a driver change

Every ~2 hours the commentator changes. You do this from your browser — both the Companion
buttons **and** the shared Google Sheet. Each time:

1. Cut to **Splitscreen** (covers the handover window).
2. In the sheet, set **Race Control** to **Driver Swaps** — viewers see it on the overlay.
3. Press **Feeds Next** — the off-air feed advances to the next commentator.
4. **Just before cutting back, update the sheet** for the new commentator: set the **Stint**
   and **Streamer** entries.
5. **Make sure the incoming feed is active.** Cut back with the matching combo — **STINT A**
   or **STINT B** — which selects the right feed (A or B alternate each stint) and shows the
   **Stint** scene in one press. (Cutting manually? Toggle the incoming **Feed A** / **Feed B**
   on first.)
6. Back in **Stint**, **clear the Race Control entry** in the sheet (leave it empty).

## Interviews

Interviews are over Discord voice. **Before** you cut to the Interview scene, confirm the
**producer has joined the Discord "Interviews" voice channel** — the audio comes from the
producer's local machine, so you can't join for them. Then switch to **Interview**, show
the lower-third, and manage mutes as guests speak.

---

New to the team? → [Who does what](Who-does-what). Something off? →
[If something goes wrong](If-something-goes-wrong).
