# Broadcast chat: rendering custom/image emotes — evaluation

**Date:** 2026-06-27
**Status:** evaluation (go) — implementation is a follow-up
**Area:** broadcast-chat reader (#294), builds on #345
**Issue:** #347

## Question

PR #345 made the broadcast-chat mirror render **standard** YouTube emoji as their
Unicode glyph, using data already in the payload and changing exactly one pure
function — no pipeline or front-end change. This evaluation decides whether to go
further and render **custom / image-based** emotes (no Unicode equivalent) as small
inline `<img>` in the three broadcast-chat cards (cockpit, director panel,
race-control), and at what scope.

## Recommendation

**Go**, at scope **YouTube channel/membership emotes + Twitch first-party/sub
emotes**. **Defer** Twitch third-party emotes (BTTV / FFZ / 7TV).

### Rationale

The dominant cost is **not** the data source — it is the one-time pipeline change
from a flat `text` string to **structured tokens**, carried through
`BroadcastChatStore`, `/broadcast-chat/data` and `/console/broadcast-chat/data`,
plus a token renderer (no `innerHTML`) in all three cards. Once that is paid:

| Scope | Data source | Marginal cost beyond the pipeline |
|---|---|---|
| YouTube custom | `emoji.image.thumbnails[].url` is **already in the Innertube payload** (we discard it today) | ~none |
| Twitch first-party | the IRC `emotes` tag → build a deterministic CDN URL | keep the `emotes` tag + raw message in `parse_twitch_privmsg`; one CDN host |
| Twitch third-party | **separate per-channel BTTV/FFZ/7TV APIs** | new network dependency + caching + 3 more CDN hosts |

The first two share the decisive property: **the emote data is already in hand, no
new external call.** That fits the reader's design contract — a *non-critical
convenience panel* that degrades to empty/text instead of crashing and adds no
broadcast-time external dependency (#294). Third-party emotes are the only scope
that introduces per-channel API calls + caching for a read-only panel — poor
cost/benefit, so they are deferred (a `:shortcut:`/name fallback already covers
them gracefully).

The **UX payoff is concentrated on Twitch**, where emote-heavy chat is today a wall
of repeated words (`showl3Hype showl3Hype showl3Hype`); small images are far more
scannable. YouTube custom emotes are a marginal win on their own but come almost
free through the shared pipeline.

## Token pipeline (sketch)

**Wire format — additive, not replacing.** Keep the flat `text` field; add a
parallel `tokens` array. A message a card cannot tokenise (or whose image is
blocked) still renders `text` verbatim, and a stale cached front-end keeps working —
graceful degradation, and no breaking change to a released wire shape.

```json
{ "ts": 0, "user": "Showler89", "source": "<videoId or twitch:login>",
  "text": ":_pog: lets go Kappa",
  "tokens": [
    {"t": "emote", "url": "https://yt3.ggpht.com/…",                          "alt": ":_pog:"},
    {"t": "text",  "v": " lets go "},
    {"t": "emote", "url": "https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/1.0", "alt": "Kappa"}
  ] }
```

**YouTube** — a new pure function `runs_to_tokens(message)` alongside `runs_to_text`
(which stays as the flat `text` fallback). A custom-emoji run
(`isCustomEmoji` truthy) emits an `emote` token from `emoji.image.thumbnails[-1].url`
with `alt = :shortcut:`; a standard emoji and plain text collapse into `text`
tokens (the glyph already comes through from #345). No new request.

**Twitch** — `parse_twitch_privmsg` keeps the `emotes` tag and the raw message; a
new pure function `splice_twitch_emotes(message, emotes_tag)` returns the token
list. Tag format `25:0-4,12-16/1902:6-10` = emote-id : **codepoint** ranges into the
message (Python codepoint indexing matches Twitch's counting). URL is deterministic:
`https://static-cdn.jtvnw.net/emoticons/v2/<id>/default/dark/1.0`. Both new functions
are pure and unit-tested like the existing parsers in
`tests/test_broadcast_chat.py`.

## Safety

1. **XSS.** The token renderer uses only `createTextNode` + `createElement('img')`,
   never `innerHTML`. The `src` is never set from raw message text.
2. **`img-src` host allowlist *in the builder*, not only via CSP.** The Twitch URL
   is safe-by-construction (the emote id is strictly validated digits; the channel
   `login` is already validated by `twitch_login`). The **YouTube URL comes from
   Google's payload**, so the token builder validates its host against an allowlist
   (`yt3.ggpht.com` / `*.ggpht.com`) before emitting it — otherwise an odd payload
   could point an `<img src>` at an arbitrary tracking beacon. A token whose URL
   fails the allowlist degrades to a `text` token carrying its `:shortcut:`/name.
3. **CSP `img-src`** on the three card pages is belt-and-suspenders on top of (2)
   and can stay minimal: `Content-Security-Policy: img-src 'self' <hosts>` restricts
   only images — no `default-src`/`script-src` is set, so the cards' inline scripts
   are unaffected.

## Front-end

A small shared token renderer used by all three cards: walk `tokens`, append a text
node for `text` and an `<img>` for `emote` (`alt` set, `loading="lazy"`, fixed
height ~`1.2em`, `onerror` → replace with a text node of `alt`). The size cap +
lazy-load avoid layout thrash in the small chat card. If `tokens` is absent, render
`text` exactly as today.

## Funnel boundary

Unchanged: the data still flows only through the existing `/console` mount
(`/console/broadcast-chat/data`); no new public surface. The emote data is already
public on the source platform, so mirroring it leaks nothing.

## Out of scope (this issue and the follow-up)

- Twitch third-party emotes (BTTV / FFZ / 7TV) — deferred (per-channel API
  dependency for a convenience panel). They keep their plain-word fallback.
- Retina / higher-res emote variants (`2.0`/`3.0`); start with `1.0` at a fixed
  display height.
- Animated-emote handling beyond whatever the CDN serves at the chosen URL.

## Acceptance (met by this document)

A written go/no-go evaluation with the chosen scope, a token-pipeline sketch and the
CSP/safety changes. Implementation (the `tokens` field, `runs_to_tokens`,
`splice_twitch_emotes`, the renderer, the CSP header, and tests) is a follow-up
issue.
