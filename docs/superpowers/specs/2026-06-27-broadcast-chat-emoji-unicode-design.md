# Broadcast chat: render standard emoji as Unicode

**Date:** 2026-06-27
**Status:** approved
**Area:** broadcast-chat reader (#294)

## Problem

Messages mirrored from the public YouTube broadcast chat show emoji as their
YouTube shortcut text instead of the glyph. Example as seen by the crew:

```
12:07:57 Showler89: The probability is low stigs :grinning_face_with_sweat:
```

The trailing `:grinning_face_with_sweat:` should read as 😅.

## Root cause

`runs_to_text` in `src/scripts/broadcast_chat.py` turns YouTube's
`message.runs[]` into a flat string. For an emoji run it deliberately emits the
first shortcut (`shortcuts[0]`, e.g. `:grinning_face_with_sweat:`) and only
falls back to `emojiId` when no shortcut is present. The front-end then renders
that text verbatim via `textContent` (XSS-safe), so the shortcut shows through
unchanged.

YouTube's emoji run carries both forms:
- `shortcuts` — the `:name:` text labels.
- `emojiId` — for a **standard** emoji this is the actual Unicode glyph; for a
  **custom** channel emote it is an internal id (`UC…/hash`) with no Unicode
  equivalent.
- `isCustomEmoji` — the discriminator (may be `False` or absent for standard).

## Change

One pure function only: `runs_to_text`. New per-emoji-run preference order:

1. If **not** `isCustomEmoji` **and** `emojiId` contains at least one non-ASCII
   character (i.e. it is a real glyph) → emit `emojiId` (the Unicode emoji).
2. Else if a `shortcuts[0]` exists → emit it (today's behaviour, `:name:`).
3. Else if `emojiId` is a string → emit it (today's final fallback).

The non-ASCII guard makes the change a strict superset of today's behaviour:
the glyph is only substituted when `emojiId` is genuinely an emoji character.
If the assumption ever fails (no glyph, or a custom emote), the function
degrades to exactly the current `:name:` output — never worse than today.

### Why no other change is needed

- **Front-end:** the cockpit, director panel and race-control desk all render
  `msg.text` through `textContent` / `createTextNode`, which passes Unicode
  emoji through correctly. No HTML/JS change.
- **Store / endpoints / pipeline:** unchanged — the text is still a plain
  string; only its content differs.
- **Twitch:** not affected — Twitch IRC already delivers the emote word in
  plain text; no shortcut form exists there.

## Out of scope (YAGNI)

- Rendering custom YouTube channel emotes or Twitch emotes as `<img>` (would
  require carrying image URLs through the pipeline and a front-end change).
- Any standalone shortcode→Unicode dictionary — YouTube already supplies the
  glyph in `emojiId`, so no table is maintained.

## Tests (`tests/test_broadcast_chat.py`)

- **Standard emoji uses the glyph:** a run with `emojiId: "😅"`,
  `shortcuts: [":grinning_face_with_sweat:"]`, `isCustomEmoji: False`
  → `runs_to_text` yields the text with `😅`.
- **Custom emote keeps the shortcut:** a run with `isCustomEmoji: True`,
  `emojiId: "UCxxxx/abcd"`, `shortcuts: [":pog:"]` → yields `:pog:`.
- **No glyph falls back to the shortcut:** the existing fixture (shortcut only,
  no `emojiId`) still yields `:smile:` (regression guard — stays green).

## Verification

Optional live check against a real channel:
`python3 tools/broadcast-chat-probe.py <youtube-channel>` to confirm a standard
emoji's `emojiId` carries the glyph in practice. The non-ASCII guard keeps the
change safe regardless of the outcome.
