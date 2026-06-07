# Director Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new director goes from "I got a link" to "I see the panel" via a new wiki setup page, a panel-first director guide (incl. the Feature-1 panel surfaces), and a "Share with your directors" URL block in `iro event start`.

**Architecture:** Docs-heavy feature per `docs/superpowers/specs/2026-06-07-director-onboarding-design.md`. One pure helper (`director_urls`) in `src/scripts/event.py` (unit-tested, no network), thin wiring in `src/iro.py:event_start`, one new wiki page, one restructured wiki page, and cross-reference fixes in five wiki files.

**Tech Stack:** Python 3 stdlib only (no pytest — tests are runnable scripts with `t_*` functions). Wiki pages are GitHub-flavored Markdown in `src/docs/wiki/` (English only), published later via `tools/sync-wiki.py` (NOT part of this plan).

**Conventions that bite:**
- Tests must use `100.64.0.0/10` Tailscale test constants — never a real IP.
- All shipped text is English. No shell scripts.
- After changing any Python file run `python3 tools/lint.py`.
- The wiki is generated from `src/docs/wiki/` — never edit anything under `dist/` or `runtime/`.

---

### Task 1: `director_urls()` helper in event.py (TDD)

**Files:**
- Modify: `src/scripts/event.py` (append after `classify_env`, ~line 235)
- Test: `tests/test_event.py` (append before the `_raises` helper at the bottom)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_event.py` (directly above the `def _raises(...)` helper near the end of the file):

```python
def t_director_urls():
    lines = m.director_urls("100.64.1.2", companion_port=8000)
    assert lines[0] == "Share with your directors:"
    assert "http://100.64.1.2:8088/panel" in lines[1]
    assert "http://100.64.1.2:8000/tablet" in lines[2]
    assert "OBS WebSocket password" in lines[3]
    # custom companion port flows through to the tablet URL
    assert "8123/tablet" in m.director_urls("100.64.1.2", companion_port=8123)[2]
    # custom relay port flows through to the panel URL
    assert "9001/panel" in m.director_urls("100.64.1.2", relay_port=9001)[1]


def t_director_urls_no_tailscale():
    # No tailnet IP -> a notice instead of URLs (directors cannot connect)
    lines = m.director_urls(None)
    assert len(lines) == 2
    assert lines[0] == "Share with your directors:"
    assert "Tailscale not connected" in lines[1]
    assert "iro tailscale up" in lines[1]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_event.py`
Expected: `AttributeError: module 'event' has no attribute 'director_urls'` (the runner executes `t_*` alphabetically; earlier tests print `ok …` first).

- [ ] **Step 3: Write the implementation**

Append to `src/scripts/event.py` (after `classify_env`):

```python
def director_urls(ts_ip, companion_port=8000, relay_port=8088):
    """Printable 'Share with your directors' block for `iro event start`.
    Pure: the caller supplies the detected Tailscale IP (or None) and
    Companion's web port (config.json `http_port`, default 8000)."""
    lines = ["Share with your directors:"]
    if not ts_ip:
        lines.append("  Tailscale not connected — directors cannot connect "
                     "remotely (iro tailscale up).")
        return lines
    lines += [
        f"  Director panel:     http://{ts_ip}:{relay_port}/panel",
        f"  Companion buttons:  http://{ts_ip}:{companion_port}/tablet",
        "  (panel scene/audio control also needs the OBS WebSocket password "
        "— OBS → Tools → WebSocket Server Settings)",
    ]
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_event.py`
Expected: `ok t_director_urls`, `ok t_director_urls_no_tailscale`, ends `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (exit 0).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/event.py tests/test_event.py
git commit -m "feat(event): director_urls helper for the share-with-directors block"
```

---

### Task 2: Wire the block into `iro event start`

**Files:**
- Modify: `src/iro.py` — new `_companion_tablet_port()` helper next to `_relay_extra()` (~line 401), and `event_start` (~line 979, before `print("\nEvent readiness:")`)
- Test: existing suites only (the wiring is thin by design; the logic lives in Task 1's pure helper)

- [ ] **Step 1: Add the Companion-port helper**

In `src/iro.py`, directly after the `_relay_extra()` function (ends ~line 401), add:

```python
def _companion_tablet_port():
    """Companion's web/tablet port from its config.json (best effort, 8000)."""
    try:
        cc = _companion()
        with open(cc.companion_config_path(sys.platform), encoding="utf-8") as fh:
            return int(json.load(fh).get("http_port", 8000))
    except Exception:
        return 8000
```

(`_companion()` and the `json` import already exist in iro.py — see `companion_status` ~line 630.)

- [ ] **Step 2: Print the block in `event_start`**

In `src/iro.py`'s `event_start`, the current tail reads:

```python
    # OBS may not have been running when relay_start's refresh hook fired
    # (event start launches OBS AFTER the relay) — retry now that both sides
    # are up. Hash-gated: a no-op when the first hook already delivered.
    _refresh_obs_pages()
    print("\nEvent readiness:")
    event_status(rest)  # exit code: 0 = ready, 1 = FAILs remain
```

Insert the share block between `_refresh_obs_pages()` and the readiness print (it must come BEFORE `event_status`, which exits via `SystemExit`):

```python
    _refresh_obs_pages()
    print()
    for line in ev.director_urls(_tailscale_ip(), _companion_tablet_port(),
                                 relay_port=RELAY_PORT):
        print(line)
    print("\nEvent readiness:")
    event_status(rest)  # exit code: 0 = ready, 1 = FAILs remain
```

- [ ] **Step 3: Verify the helper output by hand (no event start needed)**

Run:

```bash
python3 - <<'EOF'
import importlib.util, os, sys
sys.path.insert(0, os.path.join("src", "scripts"))
spec = importlib.util.spec_from_file_location("event", os.path.join("src", "scripts", "event.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("\n".join(m.director_urls("100.64.1.2", 8000)))
print("\n".join(m.director_urls(None)))
EOF
```

Expected output:

```
Share with your directors:
  Director panel:     http://100.64.1.2:8088/panel
  Companion buttons:  http://100.64.1.2:8000/tablet
  (panel scene/audio control also needs the OBS WebSocket password — OBS → Tools → WebSocket Server Settings)
Share with your directors:
  Tailscale not connected — directors cannot connect remotely (iro tailscale up).
```

- [ ] **Step 4: Run the affected suites + lint**

Run: `python3 tests/test_iro.py && python3 tests/test_event.py && python3 tools/lint.py`
Expected: both suites end `ALL PASS`; lint exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py
git commit -m "feat(iro): event start prints share-with-directors URL block"
```

---

### Task 3: New wiki page `Director-Setup.md`

**Files:**
- Create: `src/docs/wiki/Director-Setup.md`

- [ ] **Step 1: Create the page with exactly this content**

```markdown
# Director setup

Get your device ready to direct — about **5 minutes, once per device**. You
direct from a normal browser; the only thing to install is the Tailscale app.

## What you need

- A device with a browser — tablet, laptop, or phone.
- The producer's **Tailscale invite** (a link they send you).
- The **two URLs** from the producer (step 3 below).

> **What is Tailscale?** A private-network app: it makes the producer's
> machine reachable from your device — and nothing else. Without it the URLs
> below simply won't load.

## Step 1 — Install Tailscale

| Your device | Where to get it |
|---|---|
| iPad / iPhone | App Store → "Tailscale" |
| Android | Play Store → "Tailscale" |
| Windows / macOS | <https://tailscale.com/download> |
| Linux | your distribution's package, or <https://tailscale.com/download/linux> — connecting may need `sudo tailscale up` in a terminal |

## Step 2 — Accept the invite

Open the invite link from your producer and sign in (your own account). You
are done when the Tailscale app shows **Connected**.

## Step 3 — Bookmark your two pages

The producer gives you their address — it looks like `100.x.y.z` (`iro event
start` prints both URLs ready to forward, see
[Run an event](Run-an-event#before-you-go-live)):

| Bookmark | What it is |
|---|---|
| `http://<producer-ip>:8088/panel` | the **director panel** — the whole show in one browser tab |
| `http://<producer-ip>:8000/tablet` | the **Companion buttons** — the big-button board |

Add both as bookmarks (or **Add to Home Screen** on a tablet).

> Using the panel for scene/audio control? Ask your producer for the **OBS
> WebSocket password** too — you enter it once at the top of the panel
> ([which controls need it](Director#panel-or-companion-buttons)).

## If you cannot connect

Things you can check yourself, in order:

| Check | Fix |
|---|---|
| Tailscale app open and **Connected**? | Open the app and switch the connection on, then reload the page. |
| Right address? | Both URLs use the producer's `100.x.y.z` address — not `localhost`, not a `192.168.…` one. Compare with what the producer sent you. |
| Signed into the right account? | Your device must be signed into the Tailscale account that was invited. Unsure? Ask the producer to check their Tailscale admin for your device. |
| Page loads, but a red **RELAY UNREACHABLE** banner shows | You ARE connected — the problem is on the producer's side. Tell the producer; `iro status` shows them what's down. |
| Panel loads, but scene/audio buttons stay grey or ON AIR says **OBS OFFLINE** | Check the three fields at the top of the panel — producer IP, port `4455`, the OBS WebSocket password — and press **Connect**. |
| Still stuck | Ask the producer to run `iro tailscale status` and `iro status` — those name the problem. |

---

Connected? → the [Director guide](Director) shows what the buttons do.
```

- [ ] **Step 2: Verify the page**

Run: `grep -c "^#" src/docs/wiki/Director-Setup.md`
Expected: `6` (one H1 + five H2). Also confirm every wiki link target exists:
`Run-an-event.md`, `Director.md` are present in `src/docs/wiki/`.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/Director-Setup.md
git commit -m "docs(wiki): Director-Setup — connect a director device in 5 minutes"
```

---

### Task 4: Restructure `Director.md` panel-first (incl. Feature-1 panel docs)

**Files:**
- Rewrite: `src/docs/wiki/Director.md`

The workflow sections (Through the broadcast / At a driver change / POV /
Interviews) keep their existing substance — the page is re-ordered around the
panel, the Feature-1 surfaces (banners, pills, health line, guards) are
documented, the stale `SET STINT` blockquote becomes `FEEDS → STINT…`, and the
POV "verify" step uses the panel health line first.

- [ ] **Step 1: Replace the ENTIRE file content with exactly this**

```markdown
# Director guide

You direct the show **from a browser** — no OBS, no software on your machine.
You never touch the producer's PC. Several directors can take turns, and the
producer can also direct locally.

First time? [Director setup](Director-Setup) gets your device connected in
about 5 minutes. From there you have two ways to drive the show:

## Panel or Companion buttons?

Both control the same broadcast — which one your crew uses is a team call,
not a rule. The practical differences:

| | Director panel (`…:8088/panel`) | Companion buttons (`…:8000/tablet`) |
|---|---|---|
| What it is | one page with everything — program switches, feeds, HUD, graphics, timer, audio — plus live status and health warnings | the big-button board (same layout as a Stream Deck) |
| Needs | the **OBS WebSocket password** from the producer for scene/audio control: enter the producer's IP, port `4455` and the password once at the top of the panel — the browser remembers them. **FEEDS, TIMER, HUD and URLs work without it** | nothing — the OBS connection lives on the producer's machine |
| Strengths | one-tab overview; shows problems early (banners, feed health) | muscle memory; very large touch targets |

## The director panel

Open `http://<producer-tailscale-ip>:8088/panel`. The page is organized as
horizontal busses; the Stream Deck pages and the panel share one muscle
memory:

| Bus | What's on it |
|---|---|
| **PGM** | one-press program looks — `STINT A/B`, `SPLIT`, `INTERVIEW`, `STANDBY`, `INTRO`, `OUTRO`, `RED FLAG` (same behavior as the Companion combos below) |
| **FEEDS** | `NEXT` (the handover), per-feed reloads, POV reload/stop, `FEEDS → STINT…` |
| **HUD** | the sheet's Setup-tab dropdowns — Stint label, Streamer, Session, Race Control |
| **SCN·VIS** | raw scene switches and feed visibility toggles |
| **GFX** | graphics toggles (HUD, standings, schedule, results, weather, covers) |
| **TIMER** | the race timer ([Race Timer](Race-Timer)) |
| **AUDIO** | per-source dB sliders, 0 dB reset and mutes |
| **URLs** | collapsible editor for the schedule and POV URLs |

**FEEDS, TIMER, HUD and URLs work relay-only** — no OBS connection needed
(HUD and URLs additionally need the sheet-write webhook, see
[Sheet-Webhook](Sheet-Webhook); without it they are display-only). Everything
else needs the OBS WebSocket connection from the panel header (see the table
above).

### Status strip and feed health

The strip at the top shows what is on air, the race timer, and one pill per
feed with its stint and state: `A S3 · LIVE` (green — serving), `B S4 · CONN`
(amber — still connecting), `IDLE`, or `STOPPED`. The FEEDS bus adds a health
line per feed, e.g. `A · serving stint 3 (since 1:32:08)`. When a feed has
been connecting for more than ~30 seconds the line turns amber and warns
`stream may not be live yet` — usually the streamer simply hasn't started;
the exact error from the producer's machine is appended when there is one.
The POV feed joins the line whenever it isn't stopped.

### Warning banners

Ongoing problems show as banners directly under the header — they appear
while the condition holds and disappear on their own when it is resolved:

| Banner | Meaning | Who acts |
|---|---|---|
| **RELAY UNREACHABLE** (red) | the panel cannot reach the producer's relay — buttons in FEEDS/TIMER will not work | tell the producer (`iro status` on their side names the problem) |
| **SHEET SYNC FAILED** (red) | a write to the shared sheet did not go through | tell the producer; re-try the change once the banner clears |
| **COOKIES N H OLD** (amber) | the producer's YouTube cookies are stale — the **next handover may fail** | tell the producer: `iro cookies firefox` on the producer machine |

One-off action failures (a button press that didn't take) show as short
toasts in the top-right corner and are also logged in the log box at the
bottom.

### Guarded buttons

- `RELOAD A` / `RELOAD B` / `RELOAD ALL` ask for confirmation — a reload
  tears the feed's pull and means a brief interruption if that feed is on
  air.
- `NEXT` locks for 3 seconds after a press, so a double-tap cannot advance
  two stints.

> **Two things are called "stint".** `FEEDS → STINT…` (FEEDS bus) re-targets
> the actual feeds to a stint number — it interrupts running pulls and is for
> corrections/takeovers. **STINT LABEL** (HUD bus) only changes the text
> viewers see on the overlay — harmless. Advancing to the next commentator
> stream is `NEXT`.

## Director panel — HUD row

The **HUD bus** has four dropdowns: **Stint label**, **Streamer**,
**Session**, and **Race Control** (plus a **CLEAR RC** button). The options
come from the Configuration tab of the sheet — any new streamers or messages
added there are picked up automatically without changing the panel.

Each change takes effect on the HUD immediately and is written to the sheet's
Setup tab in the background. An amber outline on the dropdown means the write
is pending; the HUD status line shows the sync state. Editing the sheet
dropdowns directly works exactly as before — the two methods are equivalent.

The panel HUD row needs the sheet-write webhook (`IRO_SHEET_PUSH_URL`);
without it the panel dropdowns are read-only. (The sheet's own dropdowns work
either way — they never need the webhook.) See [Sheet-Webhook](Sheet-Webhook).

## Director panel — URLs section

Below the main rows the panel has a collapsible **URLs** section. It shows the
Schedule tab entries (one per stint: name + stream URL; rows currently
assigned to a live feed are marked A or B) and the POV URL field.

Saving a change writes it to the sheet only — **no feed reconnects
automatically**. A new stream URL takes effect at the next **RELOAD A/B** /
**NEXT** for that feed (POV: **POV RELOAD**), exactly as if the sheet had been
edited directly.

Each row also has a **CLEAR** button: it empties the row's name + URL in the
sheet (after a confirmation). The row itself stays and can be refilled later —
rows are never deleted, because removing a row would shift the stint numbering
of everything after it.

The URLs section also needs `IRO_SHEET_PUSH_URL` — without it the fields are
read-only.

## The Companion button board

The same show as big buttons: open
`http://<producer-tailscale-ip>:8000/tablet`. Two pages — **show control**
and **race timer & audio**. The left column on each page (`UP` / `DOWN`)
flips between them. Everything below is a single tap.

### Page 1 — show control

| Row | Buttons |
|-----|---------|
| **Combos** | `SPLIT`, `STINT A`, `STINT B`, `INTERVIEW`, `STANDBY`, `INTRO`, `OUTRO` — one press sets a whole look (the scene **and** the right feeds and audio). `SPLIT` also sets **Race Control → *Driver Swaps***; `STINT A` / `STINT B` **clear Race Control** on the way back — unconditionally, whatever it currently shows. `INTRO` / `OUTRO` cut to the looping intro/outro clip (with its own audio) and mute the live feeds; they light while on air. `RED FLAG` is a toggle: first press shows the Standby Cover in the Stint scene **and** sets Race Control to *Red Flag - Race Suspended*; second press hides the cover and clears Race Control. It lights red while the cover is up |
| **Scenes + relay** | `Stint Scene`, `Split Scene`, `Interview Scene`, `Standby Scene`, `Feeds Next` (the handover), `Feeds Reload`, `Feeds Status` |
| **Feeds & reloads** | `Feed A Toggle`, `Feed B Toggle`, `POV Toggle`, `Feed A Reload` (reconnect only Feed A → `/reload/A`), `Feed B Reload` (→ `/reload/B`), `POV Reload`, `POV Stop` |
| **Graphics & weather** | `Standings`, `Schedule`, `Race Results`, `Quali Results`, `Standby Toggle` (incident cover — see [The race](#through-the-broadcast-scene--sheet-cues)), `Weather Race (1) Toggle`, `Weather Race (2) Toggle`, `Weather Quali Toggle` — the three weather buttons are full-screen Stint overlays, each an independent toggle like Standings/Results |

![Companion page 1 — show control: combos, scene switches, feeds & reloads, graphics & weather](images/companion-page1-show-control.png)

### Page 2 — race timer & audio

| Row | Buttons |
|-----|---------|
| **Race timer** | `TIMER START` (starts — or resumes a paused timer), `TIMER PAUSE` (freezes the remaining time on screen), `TIMER SHOW` / `TIMER HIDE` (overlay visibility), `TIMER +1 MIN` / `TIMER -1 MIN` (correction: shifts the running countdown, a paused remainder, or — before start — the race duration), `TIMER RESET` (back to the full duration). Stopwatch logic; details in [Race-Timer](Race-Timer) |
| **Mute** | `MUTE A`, `MUTE B`, `MUTE POV`, `MUTE DISC` |
| **Volume A / B** | `VOL A DOWN` / `VOL A UP` / `VOL A RESET`, `VOL B DOWN` / `VOL B UP` / `VOL B RESET` |
| **Volume POV / Discord** | `VOL POV DOWN` / `VOL POV UP` / `VOL POV RESET`, `VOL DISC DOWN` / `VOL DISC UP` / `VOL DISC RESET` |

> `VOL … UP` / `DOWN` nudge a source by ±3 dB (relative — they drift over a
> session); `VOL … RESET` snaps that source back to **0 dB** (its original
> level). Reset only touches the level, not the mute state — use the `MUTE …`
> buttons for that.

![Companion page 2 — race timer (start/pause/show/hide/correct/reset), mute and per-source volume for the feeds, POV and Discord](images/companion-page2-timer-audio.png)

> Tip: for the everyday moves, use the **combo** buttons on page 1 (`STINT A`,
> `SPLIT`, `INTERVIEW`, …) — they set the scene and the audio in one tap.

How the board is imported and built: [Companion](Companion).

## Through the broadcast (scene + sheet cues)

The steps below name the Companion buttons; the panel has the same controls —
the combos sit on the **PGM** bus and **Feeds Next** is **NEXT** in the FEEDS
bus.

As director you drive two things: the **scenes** (Companion or panel) and
three **HUD fields in the shared sheet** — **Stint**, **Session**, and **Race
Control**. Each is a dropdown: pick the listed value, or clear the cell to
show nothing. The whole run, in order:

**At go-live (intro)**
- The producer starts streaming on **Standby**. Press **INTRO** to play the looping intro
  clip full-screen (with its own audio). Leave it running until the field is ready, then cut
  into the show (**STINT A** / **Splitscreen** for the formation lap). This is the **Intro
  video scene** — separate from the **Stint → Intro** HUD label below.

**Before the start**
- Sheet: **Stint → Intro**, **Session → Warmup**.

**Formation lap** — the race always begins with a manual formation lap.
- Sheet: **Race Control → Formation Lap**. Set it **after** the cut: the combos write
  Race Control too (**SPLIT** stamps *Driver Swaps*, **STINT A/B** clear it), so a combo
  pressed afterwards would wipe the *Formation Lap* message.
- As the formation lap starts: **Stint → Stint 1**, **Session → Race**.
- Just before the green flag: **clear Race Control**.

**The race**
- Keep the **Stint** scene on the active feed.
- Need to show a weather graphic? Press **Weather Race (1) Toggle**, **Weather Race (2) Toggle** or **Weather Quali Toggle** — each
  drops a full-screen weather overlay onto the Stint scene and is an independent toggle
  (press again to hide), exactly like the Standings/Results graphics.
- At each commentator change, run the [driver-change steps](#at-a-driver-change) below.
- Want a driver's onboard as a small PiP? It needs a **few minutes of lead time** — see
  [Showing a driver POV](#showing-a-driver-pov-plan-ahead) below.
- Incident? Set **Race Control → Red Flag** or **Technical Difficulties** and press
  **Standby Toggle** to hold the picture — it hides the feeds and the POV but keeps the
  Race Control banner and timer visible (the button lights while it's active). When it's
  resolved, press **Standby Toggle** again and **clear Race Control**.
  For a red flag specifically, **RED FLAG** does both in one press (cover + Race
  Control *Red Flag - Race Suspended*); pressing it again ends the phase (cover
  hidden, Race Control cleared). The Race Control write needs the sheet-write
  webhook ([Sheet-Webhook](Sheet-Webhook)) — without it only the cover toggles.

**Final lap** — once you're in the last stint and the leader starts the final lap:
- Sheet: **Race Control → Final Lap**. **Clear it** as soon as the race finishes.

**After the race — interviews**
- Sheet: **Stint → Moderator**, **Session → Interviews** — set these **before** you cut.
- Confirm the producer has joined Discord (see [Interviews](#interviews) below), then cut to
  the **Interview** scene.

**Wrap up**
- When the interviews end, cut back to **Stint** and set **Stint → Outro**,
  **Session → Wrapup**.
- For the close, press **OUTRO** — the looping outro clip plays full-screen (with its own
  audio) and stays on air. The producer can then stop streaming at any time. (**OUTRO** is
  the **video scene**; **Stint → Outro** above is the HUD label.)

## At a driver change

Every ~2 hours the commentator changes. You do this from your browser — the
buttons (Companion or panel) **and** the shared Google Sheet. Each time:

1. Cut to **Splitscreen** with the **SPLIT** combo (covers the handover window) — it also
   sets **Race Control → Driver Swaps** for you, so viewers see it on the overlay.
2. Press **Feeds Next** (panel: **NEXT**) — the off-air feed advances to the next
   commentator.
3. **Just before cutting back, update the sheet** for the new commentator: set the **Stint**
   and **Streamer** entries (panel: the HUD bus dropdowns do the same).
4. **Make sure the incoming feed is active.** Cut back with the matching combo — **STINT A**
   or **STINT B** — which selects the right feed (A or B alternate each stint), shows the
   **Stint** scene and **clears Race Control**, all in one press. (Cutting manually? Toggle
   the incoming **Feed A** / **Feed B** on first — and clear Race Control yourself.)
   On the panel, the feed pill shows when the incoming feed is `LIVE`.

## Showing a driver POV (plan ahead)

You can show a driver's own stream as a small picture-in-picture (bottom-right) over the
active feed in the **Stint** scene ([how it works](Relay-Mode#driver-pov-pip-optional)).
The one thing to know: **it is not instant.** Between "driver goes live" and "PiP ready
on the producer's machine" the relay still has to resolve and pull the stream — so start
the chain **a few minutes before** you want it on air:

1. **Order it early:** ask the driver to start their (unlisted) live stream and send you
   the watch URL — roughly **5 minutes ahead** is comfortable.
2. **Schedule it:** paste the watch URL into the shared sheet, tab **POV**, cell **A2**
   (panel: the POV field in the **URLs** section does the same).
3. **Pull it:** press **POV Reload**. The relay re-reads the cell and starts pulling.
   Resolving a live stream takes ~10–30 seconds; if the driver is **not live yet**, the
   relay simply keeps retrying every 15 seconds until they are — no harm, but nothing to
   show either.
4. **Verify it's ready:** the panel's FEEDS health line shows the POV state —
   wait until it says **serving**. (`CONN` means it's still resolving or the
   driver isn't live yet — don't show it; the PiP would be black.) No panel
   open? `http://<producer-tailscale-ip>:8088/status` shows the same: the
   `pov` block must say `"state": "serving"`.
5. **Show it:** press **POV Toggle** — allow a couple of seconds for OBS to connect the
   first time. Audio is muted by default; **MUTE POV** / **VOL POV …** (page 2) if you
   want it audible.
6. **Done:** **POV Toggle** to hide, then **POV Stop** (frees the pull / bandwidth).

Two rules: **Reload before Toggle**, and **hide + POV Stop when done**. The PiP lives only
in the Stint scene — switching to Splitscreen/Interview/Standby auto-hides and
auto-silences it.

## Interviews

Interviews are over Discord voice. **Before** you cut to the Interview scene, confirm the
**producer has joined the Discord "Interviews" voice channel** — the audio comes from the
producer's local machine, so you can't join for them. Then switch to **Interview**, show
the lower-third, and manage mutes as guests speak. The conversation itself is moderated
from inside the voice channel by one of its participants — usually the final-stint
streamer. You can take that role, but it isn't yours by default: your job is the scene
and the broadcast audio.

---

New to the team? → [Who does what](Who-does-what). Something off? →
[If something goes wrong](If-something-goes-wrong).
```

- [ ] **Step 2: Verify no stale terminology remains**

Run: `grep -n "SET STINT" src/docs/wiki/Director.md`
Expected: no output (exit 1).

Run: `grep -c "FEEDS → STINT" src/docs/wiki/Director.md`
Expected: `2` (bus table + the "two stints" blockquote).

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/Director.md
git commit -m "docs(wiki): restructure Director guide panel-first, document panel health surfaces"
```

---

### Task 5: Cross-reference fixes in five wiki pages

**Files:**
- Modify: `src/docs/wiki/Run-an-event.md`
- Modify: `src/docs/wiki/Who-does-what.md`
- Modify: `src/docs/wiki/_Sidebar.md`
- Modify: `src/docs/wiki/Home.md`
- Modify: `src/docs/wiki/If-something-goes-wrong.md`

- [ ] **Step 1: `Run-an-event.md` — three exact replacements**

(a) The FEEDS bus row (~line 88). Old:

```
| **FEEDS** | relay control: NEXT (driver change), feed reloads, POV reload/stop, SET STINT… |
```

New:

```
| **FEEDS** | relay control: NEXT (driver change), feed reloads, POV reload/stop, FEEDS → STINT… |
```

(b) Step 9 of "Before you go live" (~line 62). Old:

```
9. Make sure **Companion** is connected (green) and a director can reach
   `http://<producer-tailscale-ip>:8000/tablet`.
```

New:

```
9. Make sure **Companion** is connected (green) and a director can reach
   `http://<producer-tailscale-ip>:8000/tablet` (first-time directors:
   [Director setup](Director-Setup)).
```

(c) The panel intro (~line 75). Old:

```
show from the **director panel** the relay serves at
`http://<producer-tailscale-ip>:8088/panel` (`iro event start` prints the
URL — just forward it).
```

New:

```
show from the **director panel** the relay serves at
`http://<producer-tailscale-ip>:8088/panel` (`iro event start` prints both
director URLs ready to forward; first-time directors:
[Director setup](Director-Setup)).
```

- [ ] **Step 2: `Who-does-what.md` — one exact replacement**

Old (~line 30):

```
- Drives the whole show from a browser via Companion — no machine access. See
  [Director guide](Director).
```

New:

```
- Drives the whole show from a browser (panel or Companion buttons) — no
  machine access. First time: [Director setup](Director-Setup); then the
  [Director guide](Director).
```

- [ ] **Step 3: `_Sidebar.md` — insert the new page**

Old:

```
- [Run an event](Run-an-event)
- [Director guide](Director)
```

New:

```
- [Run an event](Run-an-event)
- [Director setup](Director-Setup)
- [Director guide](Director)
```

- [ ] **Step 4: `Home.md` — update the director path**

Old (~line 30):

```
- **You're the remote director?** → [Director guide](Director)
```

New:

```
- **You're the remote director?** → [Director setup](Director-Setup) (first
  time), then the [Director guide](Director)
```

- [ ] **Step 5: `If-something-goes-wrong.md` — add a director-side pointer**

In the "## The director can't connect" section, add a new FIRST row to the
table. Old:

```
| Problem | Fix |
|---------|-----|
| Director can't reach the buttons | Run `iro tailscale status` — the process icon alone says nothing about being connected; the backend must be `Running`. If it shows `Stopped`, run `iro tailscale up` first. Then check: Tailscale connected on both machines? Companion running with **GUI Interface = All Interfaces**? Using the **Tailscale** address (`100.x.y.z`), not a local one? |
```

New:

```
| Problem | Fix |
|---------|-----|
| First triage | Director-side checks (Tailscale app, right URL, panel password) are on [Director setup → If you cannot connect](Director-Setup#if-you-cannot-connect) — have the director run through those while you check below. |
| Director can't reach the buttons | Run `iro tailscale status` — the process icon alone says nothing about being connected; the backend must be `Running`. If it shows `Stopped`, run `iro tailscale up` first. Then check: Tailscale connected on both machines? Companion running with **GUI Interface = All Interfaces**? Using the **Tailscale** address (`100.x.y.z`), not a local one? |
```

- [ ] **Step 6: Verify**

Run: `grep -rn "SET STINT" src/docs/wiki/`
Expected: no output (exit 1) — no stale references anywhere.

Run: `grep -rln "Director-Setup" src/docs/wiki/ | sort`
Expected: `Director.md`, `Home.md`, `If-something-goes-wrong.md`, `Run-an-event.md`, `Who-does-what.md`, `_Sidebar.md` (6 files; `Director-Setup.md` itself doesn't self-reference).

- [ ] **Step 7: Commit**

```bash
git add src/docs/wiki/Run-an-event.md src/docs/wiki/Who-does-what.md src/docs/wiki/_Sidebar.md src/docs/wiki/Home.md src/docs/wiki/If-something-goes-wrong.md
git commit -m "docs(wiki): cross-link Director-Setup, rename stale SET STINT references"
```

---

### Task 6: Full gates

**Files:** none (verification only; fix fallout if any).

- [ ] **Step 1: Whole test suite**

Run: `python3 tools/run-tests.py`
Expected: every file ends `ALL PASS`, summary `ALL TEST FILES PASS`.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: exit 0, no findings.

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: all `[OK]` verify lines, exit 0 (confirms the new wiki page ships and no shell scripts / secrets crept in).

- [ ] **Step 4: Commit (only if fixes were needed)**

If steps 1–3 required changes, commit them with a `fix:` message describing the fallout; otherwise nothing to commit.

---

## Spec coverage map

| Spec section | Task |
|---|---|
| 1. New page `Director-Setup.md` (3 steps + troubleshooting, Linux incl.) | 3 |
| 2. Restructured `Director.md` (panel-first, F1 docs, password difference, POV step) | 4 |
| 3. CLI share block (`director_urls` helper + event_start wiring + no-Tailscale notice) | 1, 2 |
| 4. Cross-reference fixes (5 pages incl. `SET STINT` renames) | 4 (Director.md), 5 (rest) |
| Testing (helper unit tests, suite/lint/build green) | 1, 6 |
| Out of scope: sync-wiki publication, screenshots, F3 items | not in plan (post-merge / F3) |
