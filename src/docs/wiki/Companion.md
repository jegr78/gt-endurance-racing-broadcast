# Companion

> Technical reference. What the buttons do for a director: [Director guide](Director).

Bitfocus Companion is the director's button board: a grid of buttons served as a web
page that directors open in a browser. It is the **primary** control surface and is
strictly more capable than the [backup director panel](Director). Install it first per
[Set up the broadcast PC](Set-up-the-broadcast-PC).

## Import the button board

1. Start Companion → launcher → **GUI Interface = All Interfaces (0.0.0.0)** (important
   for Tailscale), admin port `8000` → **Launch GUI**.
2. In the admin: **Import/Export → Import** → `companion/iro-buttons.companionconfig`.
   This is a **full config** → confirm **"Replace current configuration"**.

> ⚠️ This **replaces the entire Companion configuration** on this station. Fine for a
> fresh/dedicated producer station; **back up first** if this Companion holds other
> content.

## Connect to OBS

The **OBS connection** (`127.0.0.1:4455`) comes with the config — **but without the
password** (removed for security). → **Connections** → open the OBS entry → **enter your
OBS WebSocket password** (the one you set in [Set up the broadcast PC](Set-up-the-broadcast-PC)) → the
connection turns green.

## The button board

The board has two pages — **show control** and **audio**. The full layout, what each
button does, and the screenshots live in the [Director guide](Director#the-button-board) —
that's the operator's reference for actually using the board.

This page covers only how the board is wired up. The relay buttons (`Feeds Next`,
`Feeds Reload`, `Feeds Status`, `Feed A Reload`, `Feed B Reload`, `POV Reload`, `POV Stop`)
use the **Generic HTTP Requests**
connection — see [Relay Mode §4](Relay-Mode#4-control-it-companion--relay). Everything else
uses the OBS connection.

## Test

Open `http://localhost:8000/tablet`, press a button → OBS reacts. For remote directors,
see [Director (Remote)](Director).

## State feedback (optional)

A button can light up when its scene/source is live: in the button editor → **Add
feedback** → **Source Visible** / **Scene Active** → pick a highlight color. Now the
director always sees what's on air. A button can also hold **multiple stacked actions** —
e.g. one "Go to Interview" that switches scene *and* shows the lower-third *and* unmutes
Discord (this is how the row-0 combos work).
