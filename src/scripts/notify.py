#!/usr/bin/env python3
"""Pure Discord webhook payload builders for producer events (issue #317):
producer takeover and OBS stream start/stop. No I/O — the CLI (`_post_discord_webhook`)
and the relay (`Relay._discord_post`) send the returned dict.

Shape mirrors the relay's `discord_health_payload` so every racecast post reads
alike: it posts as "GT Racecast", an `@here` mention sits in top-level `content`
(Discord ignores mentions inside an embed), the message rides in one titled embed,
and the footer shows `<event_title> · <producer>` — which host/producer triggered
the event (#317). Important events (takeover, stream stopped = off air) ping
`@here`; an informational stream-start does not.
"""

USERNAME = "GT Racecast"

# Embed colors (hex ints), distinct per event so the crew reads severity at a glance.
COLOR_TAKEOVER = 0x8B5CF6      # violet — a producer handover
COLOR_STREAM_START = 0x16A34A  # green — stream is live
COLOR_STREAM_STOP = 0xDC2626   # red — off air


def _footer(event_title="", producer=""):
    """Footer text combining event title and producer: `<title> · <producer>`,
    one of them alone, or None when both are empty."""
    parts = [p for p in ((event_title or "").strip(), (producer or "").strip()) if p]
    return " · ".join(parts) or None


def _payload(title, desc, color, *, ping, event_title="", producer=""):
    embed = {"title": title, "description": desc, "color": color}
    footer = _footer(event_title, producer)
    if footer:
        embed["footer"] = {"text": footer}
    out = {"username": USERNAME, "embeds": [embed]}
    if ping:
        out["content"] = "@here"
        out["allowed_mentions"] = {"parse": ["everyone"]}
    return out


def takeover_discord_payload(producer, from_producer, stint, source, event_title=""):
    """Announce a producer takeover: `producer` took over (optionally from
    `from_producer`) at 1-based `stint`, with `source` the feed it landed on.
    @here ping — a handover is crew-relevant. Pure."""
    who = producer or "A producer"
    frm = (from_producer or "").strip()
    desc = f"**{who}** took over the broadcast at stint {stint}"
    if frm:
        desc += f", from **{frm}**"
    desc += f" ({source})."
    return _payload("🎬 Producer takeover", desc, COLOR_TAKEOVER,
                    ping=True, event_title=event_title, producer=producer)


def obs_stream_discord_payload(started, producer, event_title=""):
    """Announce OBS stream start (info, no ping) or stop (off air, @here ping). Pure."""
    if started:
        return _payload("▶️ OBS stream started",
                        "OBS has started streaming — the broadcast is live.",
                        COLOR_STREAM_START, ping=False,
                        event_title=event_title, producer=producer)
    return _payload("⏹️ OBS stream stopped",
                    "OBS has stopped streaming — the broadcast is off air.",
                    COLOR_STREAM_STOP, ping=True,
                    event_title=event_title, producer=producer)
