# Broadcast-chat compose popup — design

**Date:** 2026-06-27
**Surfaces:** Commentator Cockpit (`src/cockpit/cockpit.html`), Director Panel
(`src/director/director-panel.html`), Race Control desk
(`src/racecontrol/race-control.html`) — the three pages that already host the
read-only broadcast-chat card (#294).

## Goal

Let the crew post into the **public** broadcast chat (YouTube or Twitch) from the
console pages, not only read it. A small **"Write in chat ↗"** button in the
broadcast-chat card opens the platform's **native** popout chat page in a small
dedicated window; the crew member posts under the account their browser is already
signed into on that platform.

## Approach — native popout, no relay write path

Reading is anonymous today (YouTube Innertube polling, Twitch anonymous IRC).
**Writing requires an authenticated account**, so it cannot reuse the read path.
Three options were weighed:

- **A — popout to the native chat UI (chosen).** A button opens the native
  YouTube/Twitch chat compose page; the crew member's own browser session sends.
  No credential storage, no API quota, no ToS risk, **no relay write path** — the
  relay's read-only/ephemeral broadcast-chat property is fully preserved.
- **B — one shared "official" broadcast identity, relay-mediated send.** Per-league
  OAuth (YouTube Data API + authenticated Twitch IRC). Far more work, and the
  YouTube Data API quota caps inserts at ~200/day by default. Rejected for this
  convenience feature.
- **C — per-crew-member OAuth send.** Maximum auth surface; overkill. Rejected.

The only server-side change is one **read-only field** (`target`) added to the
existing broadcast-chat data payload. No new endpoint, no new public surface.

## Decisions

- **Identity:** each crew member posts under their *own* personal account (whatever
  their browser is logged into on the platform). No shared/official identity.
- **One channel, one platform.** A broadcast stays on a single channel/platform;
  it does not switch platforms mid-event. The channel is the maintainable URL in
  the Sheet `Channel` tab (already read by `ChannelSource`). KISS.
- **Single primary target.** During an A→B producer handover a second live video
  appears on the same channel; both are live ~1–2 min. The button targets the
  **first** live chat in that window — a brief mis-aim is acceptable. No multi-target
  UI.
- **Target derived server-side from the supervisor's live set**, not from the last
  message's `source`, so the button is present even when the chat is momentarily
  quiet.
- **All three console pages** get the button: Cockpit, Director Panel, Race Control.
  (The Race Control "read-only" convention only covers internal broadcast setup —
  scenes, graphics, HUD — not posting to the public chat, which anyone can do
  natively anyway.)
- **Popup window, not a tab,** 400 × 560, named (reused on repeat clicks),
  resizable, with scrollbars.

## Backend — pure helpers in `src/scripts/broadcast_chat.py`

```python
def youtube_video_id(value):
    """A YouTube videoId validated to `[A-Za-z0-9_-]{11}`, else None.
    SECURITY: the id is interpolated into the popout URL handed to the browser,
    so it is validated the same way twitch_login() guards the Twitch login."""

def twitch_popout_chat_url(login):
    """A validated Twitch login -> its popout chat URL (compose box for a
    signed-in user). login is already constrained by twitch_login()."""
    return f"https://www.twitch.tv/popout/{login}/chat"

def primary_chat_target(candidates):
    """The first compose target from an ordered [(platform, key)] list, as
    {"platform","url"} (YouTube key = videoId -> live_chat_page_url;
    Twitch key = "twitch:<login>" -> twitch_popout_chat_url), or None when
    empty / nothing valid. Pure."""
```

- The YouTube target reuses the existing `live_chat_page_url(video_id)`
  (`…/live_chat?is_popout=1&v=<id>`) — that popout carries a compose box for a
  signed-in user. `youtube_video_id` guards the id first.
- `primary_chat_target` is fed the supervisor's desired set in Channel-tab order
  (YouTube videoIds first, then Twitch). "First" = first in that stable order.

## Backend — relay (`src/relay/racecast-feeds.py`)

- **`BroadcastChatStore`:** add a `target` slot + `set_target(target)`; `data()`
  returns `{"messages": [...], "target": {…}|None}` (default `None`).
- **`BroadcastChatSupervisor._cycle()`:** from the desired set it already builds
  (`_desired()` keys = videoId / `twitch:<login>`), compute the primary target via
  `primary_chat_target(...)` and call `store.set_target(...)`. When nothing is live,
  set `None`. Best-effort like the rest of the supervisor.
- **Endpoints:** none added. `target` flows automatically through both existing
  readers of `broadcast_chat_store.data()`:
  - `GET /broadcast-chat/data` (tailnet/loopback)
  - `GET /console/broadcast-chat/data` (Funnel, any authenticated `/console` subject)

## Front-end — the three broadcast-chat cards

In `cockpit.html`, `director/director-panel.html`, `racecontrol/race-control.html`:

- A small button in the card header. Label is platform-aware from `target.platform`:
  **"✍ Write in YouTube chat ↗"** / **"✍ Write in Twitch chat ↗"**. All UI text is
  English (project rule).
- **Visibility:** render the button only when the poll payload's `target` is non-null.
  No live chat / reader disabled → `target` is null → button hidden (the card already
  self-hides when the reader is disabled / the endpoint 404s).
- **Click handler:**

  ```js
  window.open(
    target.url,
    "rc_broadcast_chat",                                   // named -> reuse, not a swarm
    "popup=yes,width=400,height=560,scrollbars=yes,resizable=yes"
  );
  ```

  The features string forces a dedicated popup window (not a tab) in all major
  browsers; the button click is a user gesture, so popup blockers do not fire.
- Works identically over tailnet and Funnel (pure client navigation to
  youtube.com/twitch.tv; the `target` field arrives via the existing endpoints).
- The three cards already share the same poll/render pattern (`RC_API` shim); the
  button code stays consistent/duplicated alongside the rest of the card, matching
  the existing structure.

## Security

- **No new endpoint, no write path, no new public surface.** `target` rides the
  existing `/console/broadcast-chat/data` (Funnel) and `/broadcast-chat/data`
  (tailnet) payloads.
- `target.url` is built **server-side** from validated inputs (`youtube_video_id`
  regex, `twitch_login` regex) — no URL injection.
- No data leak: the live videoId / channel are already public (they ride the
  `source` field of every mirrored message).
- `window.open` intentionally omits `noopener` so the named window is reused; the
  target is a trusted first-party site (youtube.com / twitch.tv), so
  reverse-tabnabbing risk is negligible. Defensive `win.opener = null` where the
  browser permits it.

## Tests

- `tests/test_broadcast_chat.py`:
  - `youtube_video_id`: valid 11-char id passes; wrong length / illegal chars /
    non-str → None.
  - `twitch_popout_chat_url`: builds the expected URL from a login.
  - `primary_chat_target`: first candidate wins (YouTube vs Twitch); empty → None.
  - `BroadcastChatStore`: `data()["target"]` defaults to None; reflects
    `set_target(...)`.
- Endpoint test (existing pattern): `target` present in the payload of both
  `/broadcast-chat/data` and `/console/broadcast-chat/data`.
- Front-end: manual + optional Playwright (e2e follows the existing
  "skip when unavailable" pattern; no new required CI surface).

## Docs & wiki screenshots (same change — hard rule)

- **CLAUDE.md:** one sentence on the new `target` field + popout compose button,
  noting the relay's read-only/ephemeral broadcast-chat property is unchanged (the
  compose happens entirely in the crew member's own browser, never through the relay).
- **Wiki screenshots** (the card changes visibly): regenerate `director-panel.png`
  and the cockpit / console / race-control images that show the broadcast-chat card,
  via the `wiki-screenshots` skill, committed in this change.

## Out of scope

- A shared "official" broadcast identity (option B) and per-member OAuth (option C).
- Embedding a compose box inline (the native popout is the compose UI).
- Multi-target selection UI (one channel/platform, KISS).
