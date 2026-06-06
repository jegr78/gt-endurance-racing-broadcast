# Race Timer

The remaining-race-time overlay is served by the relay itself at
`http://127.0.0.1:8088/timer` (the OBS `HUD Race Timer` browser source points
there). No external service is involved.

## How it works

The timer is **one absolute end timestamp** plus a duration, a visibility
flag, and — while paused — a frozen remainder. The browser source computes
`end − now` locally and ticks smoothly; the state lives in three places:

| Layer | Purpose |
|---|---|
| Relay memory + `runtime/timer.json` | survives a relay/OBS restart on this machine |
| Sheet tab **Timer** | survives a producer-machine handover — every relay reads the same anchor |
| Apps Script webhook | lets Director buttons write that Sheet tab |

Newest write wins (both sides carry an `Updated (UTC)` stamp), so a stale
Sheet never reverts a fresh local action. Machines must have normal NTP clock
sync (macOS/Windows default).

## Director controls

Available on the **director panel** (`http://<producer-tailscale-ip>:8088/panel`,
Race Timer section) and as **Companion buttons** (page 2, top row):

The buttons follow **stopwatch semantics**:

| Action | Endpoint | Effect |
|---|---|---|
| Start | `/timer/start` | starts (end = now + duration) — or **resumes** a paused timer |
| Stop (pause) | `/timer/stop` | pauses: freezes the remaining time on screen |
| Reset | `/timer/reset` | back to "not started" (shows the full duration) |
| Show / Hide | `/timer/show`, `/timer/hide` | blanks/unblanks the overlay on every producer machine |
| Set duration | `/timer/set/6:00:00` | race length for the next start |
| Correct | `/timer/adjust/-60` | ± seconds on whatever is relevant: the running countdown, a paused remainder, or — before start — the duration |

Display behaviour: before start → static full duration; running → countdown;
paused → frozen remaining time; at zero → blank (no `0:00:00` left standing);
hidden → blank.

## One-time setup: the write webhook (optional but recommended)

Without it the timer still works on the producer machine, but Director actions
cannot sync to the Sheet — a takeover machine would not pick up the running
countdown. Set it up once per sheet:

1. Open the broadcast Google Sheet → **Extensions → Apps Script**.
2. Paste this script (replace `change-me` with a random secret):

   ```javascript
   const KEY = 'change-me';            // must match the key=... in the URL below
   const TAB = 'Timer';
   const ROWS = {'Race End (UTC)': 1, 'Duration': 2, 'Visible': 3,
                 'Updated (UTC)': 4, 'Remaining': 5};

   function doPost(e) {
     const out = (o) => ContentService.createTextOutput(JSON.stringify(o))
         .setMimeType(ContentService.MimeType.JSON);
     if (((e.parameter && e.parameter.key) || '') !== KEY) return out({error: 'bad key'});
     const p = JSON.parse(e.postData.contents);
     const ss = SpreadsheetApp.getActiveSpreadsheet();
     const sheet = ss.getSheetByName(TAB) || ss.insertSheet(TAB);
     const write = (label, value) => {
       sheet.getRange(ROWS[label], 1).setValue(label);
       sheet.getRange(ROWS[label], 2).setNumberFormat('@').setValue(value);
     };
     if ('end' in p) write('Race End (UTC)', p.end);
     if ('duration' in p) write('Duration', p.duration);
     if ('visible' in p) write('Visible', p.visible);
     if ('remaining' in p) write('Remaining', p.remaining);
     write('Updated (UTC)', new Date().toISOString());
     return out({ok: true});
   }
   ```

3. **Deploy → New deployment → Web app**, execute as **Me**, access:
   **Anyone**. Copy the `/exec` URL.
4. In `.env` on every producer machine:

   ```
   IRO_TIMER_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
   ```

5. Restart the relay. `iro event status` shows the `.env` check as PASS, and
   the panel's timer line reports `sheet sync OK` after the first action.

The URL+key is a write credential for the Timer tab — treat it like the other
`.env` secrets (never commit it).

## Producer handover

Nothing to do: the new machine's relay reads the Sheet anchor on startup and
shows the identical countdown. If the webhook was never set up, set the
remaining time manually after takeover: `/timer/set/<H:MM:SS>` + `/timer/start`
won't match mid-race — instead start, then `/timer/adjust/±seconds` until it
matches the official clock.
