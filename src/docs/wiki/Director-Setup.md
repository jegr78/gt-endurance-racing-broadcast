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
| Linux | your distribution's package, or <https://tailscale.com/download/linux> (see the Linux note below) |

**Linux has no Tailscale app** — it runs as a background service you control from a
terminal. Sign in once with `sudo tailscale up`, which prints a
`https://login.tailscale.com/…` URL to **open in a browser** and sign in. Then run
`sudo tailscale set --operator=$USER` once so you can connect/disconnect later without
`sudo`. Check the connection with `tailscale status` (there's no app window to show
"Connected").

## Step 2 — Accept the invite

Open the invite link from your producer and sign in (your own account). You
are done when the Tailscale app shows **Connected** (on Linux: `tailscale status`
reports your `100.x.y.z` address).

## Step 3 — Bookmark your two pages

The producer gives you their address — it looks like `100.x.y.z` (`racecast event
start` prints both URLs ready to forward, see
[Run an event](Run-an-event#before-you-go-live)):

| Bookmark | What it is |
|---|---|
| `http://<producer-tailscale-ip>:8088/panel` | the **director panel** — the whole show in one browser tab |
| `http://<producer-tailscale-ip>:8000/tablet` | the **Companion Web Buttons** — the big-button board |

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
| Page loads, but a red **RELAY UNREACHABLE** banner shows | You ARE connected — the problem is on the producer's side. Tell the producer; `racecast status` shows them what's down. |
| Panel loads, but scene/audio buttons stay grey or ON AIR says **OBS OFFLINE** | Check the three fields at the top of the panel — producer IP, port `4455`, the OBS WebSocket password — and press **Connect**. |
| Still stuck | Ask the producer to run `racecast tailscale status` and `racecast status` — those name the problem. |

---

Connected? → the [Director guide](Director) shows what the buttons do.
