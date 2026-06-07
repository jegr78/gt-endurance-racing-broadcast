# Sheet-Webhook — the write path back into the Google Sheet

The relay reads the Sheet via CSV export (no key needed). Writing back —
race-timer sync and the director panel's HUD/Schedule/POV controls — goes
through **one** Google Apps Script web app deployed inside the broadcast
Sheet. One URL + key in `.env` powers all of it:

```
IRO_SHEET_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
```

Without it everything still works read-only: the timer stays local to one
machine and the panel's HUD row + URLs section are display-only.

## What it writes

| Action (sent by the relay) | Sheet target |
|---|---|
| `timer` | Timer tab (race-timer state — see [Race-Timer](Race-Timer)) |
| `setup` | Setup tab: the cell **below** a header (`Stint`, `Streamer`, `Session`, `Race Control`) — found by text, so the tab layout may move |
| `schedule` | Schedule tab **physical row N** (the panel sends the CSV line number automatically): URL (col A) + name (col B); row `last+1` appends. **The Schedule tab must not have leading blank rows** — the gviz CSV export maps physical sheet rows to CSV lines 1:1 when the tab starts at row 1. A header row is silently skipped when reading but its physical line number is still used when writing. |
| `pov` | POV tab cell `A2` |

The relay only sends Setup values that exist in the Configuration tab's
vocabulary columns — the same lists the sheet's own dropdowns use.

## One-time setup (per sheet)

1. Open the broadcast Google Sheet → **Extensions → Apps Script**.
2. Replace the editor contents with this script (set `KEY` to a random secret):

   ```javascript
   const KEY = 'change-me';            // must match the key=... in the URL below
   const TABS = {setup: 'Setup', schedule: 'Schedule', pov: 'POV', timer: 'Timer'};
   const SETUP_FIELDS = ['Stint', 'Streamer', 'Session', 'Race Control'];
   const TIMER_ROWS = {'Race End (UTC)': 1, 'Duration': 2, 'Visible': 3,
                       'Updated (UTC)': 4, 'Remaining': 5};

   function doPost(e) {
     const out = (o) => ContentService.createTextOutput(JSON.stringify(o))
         .setMimeType(ContentService.MimeType.JSON);
     if (((e.parameter && e.parameter.key) || '') !== KEY) return out({error: 'bad key'});
     try {
       const p = JSON.parse(e.postData.contents);
       const ss = SpreadsheetApp.getActiveSpreadsheet();
       const action = p.action || 'timer';
       if (action === 'timer') writeTimer(ss, p);
       else if (action === 'setup') writeSetup(ss, p.fields || {});
       else if (action === 'schedule') writeSchedule(ss, p);
       else if (action === 'pov') writePov(ss, p);
       else return out({error: 'unknown action: ' + action});
       return out({ok: true, action: action, v: 2});
     } catch (err) { return out({error: String(err)}); }
   }

   function tab(ss, name) {
     const sheet = ss.getSheetByName(name);
     if (!sheet) throw 'tab not found: ' + name;
     return sheet;
   }

   function writeTimer(ss, p) {
     const sheet = ss.getSheetByName(TABS.timer) || ss.insertSheet(TABS.timer);
     const write = (label, value) => {
       sheet.getRange(TIMER_ROWS[label], 1).setValue(label);
       sheet.getRange(TIMER_ROWS[label], 2).setNumberFormat('@').setValue(value);
     };
     if ('end' in p) write('Race End (UTC)', p.end);
     if ('duration' in p) write('Duration', p.duration);
     if ('visible' in p) write('Visible', p.visible);
     if ('remaining' in p) write('Remaining', p.remaining);
     write('Updated (UTC)', new Date().toISOString());
   }

   function writeSetup(ss, fields) {
     // Locate every header first, then write — an unknown/renamed header
     // aborts the whole write with a clear error.
     const sheet = tab(ss, TABS.setup);
     const grid = sheet.getDataRange().getValues();
     const targets = {};
     Object.keys(fields).forEach((name) => {
       if (SETUP_FIELDS.indexOf(name) === -1) throw 'unknown setup field: ' + name;
       let hit = null;
       for (let r = 0; r < grid.length && !hit; r++)
         for (let c = 0; c < grid[r].length && !hit; c++)
           if (String(grid[r][c]).trim().toLowerCase() === name.toLowerCase())
             hit = [r + 2, c + 1];          // the value cell sits BELOW the header
       if (!hit) throw 'header not found in Setup tab: ' + name;
       targets[name] = hit;
     });
     Object.keys(targets).forEach((name) => {
       sheet.getRange(targets[name][0], targets[name][1])
            .setNumberFormat('@').setValue(fields[name]);
     });
   }

   function writeSchedule(ss, p) {
     const sheet = tab(ss, TABS.schedule);
     const row = Number(p.row);
     const last = sheet.getLastRow();
     if (!row || row < 1 || row > last + 1) throw 'row out of range: ' + p.row;
     if ('url' in p) sheet.getRange(row, 1).setNumberFormat('@').setValue(p.url);
     if ('name' in p) sheet.getRange(row, 2).setNumberFormat('@').setValue(p.name);
   }

   function writePov(ss, p) {
     tab(ss, TABS.pov).getRange(2, 1).setNumberFormat('@').setValue(p.url || '');
   }
   ```

3. **Deploy → New deployment → Web app**, execute as **Me**, access:
   **Anyone**. Copy the `/exec` URL.
4. In `.env` on every producer machine:

   ```
   IRO_SHEET_PUSH_URL=https://script.google.com/macros/s/…/exec?key=<your secret>
   ```

5. Restart the relay. `iro event status` shows the `.env` check as PASS; the
   panel's HUD line reports `sheet sync OK` after the first action.

## Updating the script later

**Manage deployments → ✎ Edit → Version: New version → Deploy.** This keeps
the `/exec` URL — no `.env` change on any machine. (A *New deployment*
instead creates a NEW URL and every `.env` must be updated.)

The relay detects an outdated (v1, timer-only) script: panel writes then
report *"webhook script outdated — redeploy"* instead of failing silently.

## Security

The URL+key is a write credential for the Sheet — treat it like the other
`.env` secrets (never commit it). The endpoints the panel uses sit on the
relay's unauthenticated control server: the tailnet is the trust boundary,
same as all other `/panel` controls.
