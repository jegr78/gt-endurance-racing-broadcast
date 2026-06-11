# IRO Endurance Broadcast — Setup Package

This package sets up a complete producer station for the IRO Endurance
broadcast: OBS scenes + HUD, the Companion button board, the director panel,
and the relay that pulls each commentator's stream into OBS.

**Quickest start:** double-click **`iro-ui`** to open the **Control Center** — a
local web dashboard that runs setup and event day from your browser, no terminal
needed. The `iro …` commands below are the CLI alternative.

**The documentation lives in the project wiki** — always current, written for
first-time producers:

- **The Control Center:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Control-Center>
- **First-time setup** (one time, ~30 min):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Set-up-the-broadcast-PC>
- **Event day:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Run-an-event>
- **Start page** (all roles):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki>

## Quickstart

First-time setup — one guided command (it skips whatever is already done):

    iro init

On event day:

    iro cookies firefox    # refresh YouTube cookies (log into YouTube in Firefox first)
    iro event start        # bring everything up; prints the director URLs
    iro event stop         # after the broadcast

`iro preflight` checks this machine any time and names the exact fix for
anything missing.

The printable role cheat sheets are in `cheat_sheets.html` (open it in a
browser, print).
