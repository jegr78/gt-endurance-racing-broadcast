"""Pure logic for the read-only broadcast-chat reader (issue #294).

No network, no argv parsing. The relay (`src/relay/racecast-feeds.py`) owns the
yt-dlp subprocess that resolves a channel to its currently-live videoId set and
the Innertube HTTP fetch; this module holds everything that can be unit-tested
without a live stream:

  * the message sanitizer + caps (mirrors `chat_admin.py`),
  * `runs_to_text` (YouTube's `message.runs[]` -> a single display string),
  * `parse_chat_action` / `parse_live_chat` (the Innertube `get_live_chat`
    continuation response -> messages + the next continuation + poll timeout),
  * `parse_bootstrap` (the `live_chat` page HTML -> api key, client version,
    first continuation) and `build_get_live_chat_body` (the POST body),
  * `parse_channel_tab` (the Sheet `Channel` tab CSV -> [(platform, channel)]),
  * `live_set_diff` (which readers to start/stop when the channel's live set
    changes — the producer-handover case where two streams overlap briefly),
  * the small URL builders.

The reader is READ-ONLY and EPHEMERAL: unlike the crew chat there is no on-disk
persistence and no send path. Broadcast chat is a situational-awareness panel,
not broadcast-critical, so every parser degrades to "empty" rather than raising.
"""
import csv
import io
import re

MAX_MESSAGES = 500      # ring-buffer / display cap (oldest dropped)
MAX_TEXT = 500          # per-message character cap
MAX_NAME = 60           # author-name character cap (YT names run long)
DEFAULT_NAME = "Viewer"  # fallback when no/blank author name is supplied

# Innertube WEB client used for the get_live_chat POST. The exact version is
# refreshed from the page bootstrap; this is only the fallback.
DEFAULT_CLIENT_VERSION = "2.20240101.00.00"


def _clean_text(value):
    """Strip control characters; fold every line/paragraph separator to a single
    space (chat is rendered in one row). Mirrors chat_admin._clean_text."""
    if not isinstance(value, str):
        return ""
    line_breaks = ("\t", "\n", "\r", "\x85", "\u2028", "\u2029")
    out = []
    for ch in value:
        if ch in line_breaks:
            out.append(" ")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            continue
        else:
            out.append(ch)
    return "".join(out)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sanitize_message(raw, source=None):
    """Coerce one raw message into {ts, user, text, source} or None if unusable.
    ts must be numeric; text must be non-empty after cleaning; user falls back to
    DEFAULT_NAME. `source` tags which live stream the message came from (the
    videoId) so a handover overlap can be shown/merged."""
    if not isinstance(raw, dict) or not _is_num(raw.get("ts")):
        return None
    text = _clean_text(raw.get("text")).strip()
    if not text:
        return None
    user = _clean_text(raw.get("user")).strip() or DEFAULT_NAME
    return {"ts": float(raw["ts"]), "user": user[:MAX_NAME],
            "text": text[:MAX_TEXT], "source": source}


# --- Innertube message rendering -------------------------------------------

def runs_to_text(message):
    """A YouTube chat `message` object -> a flat display string.

    Handles the `runs[]` form (text runs + emoji runs) and the `simpleText`
    form. A STANDARD emoji is rendered as its Unicode glyph (carried in
    `emojiId`); a CUSTOM channel emote (no Unicode equivalent) falls back to its
    first shortcut like `:pog:`. Anything unexpected yields ""."""
    if not isinstance(message, dict):
        return ""
    if isinstance(message.get("simpleText"), str):
        return message["simpleText"]
    runs = message.get("runs")
    if not isinstance(runs, list):
        return ""
    parts = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if isinstance(run.get("text"), str):
            parts.append(run["text"])
        elif isinstance(run.get("emoji"), dict):
            parts.append(_emoji_to_text(run["emoji"]))
    return "".join(parts)


def _emoji_to_text(emoji):
    """One YouTube emoji run -> its display string.

    Prefers the Unicode glyph from `emojiId` for a standard emoji (not
    `isCustomEmoji`, and the id is an actual glyph i.e. contains a non-ASCII
    character). Otherwise falls back to the first `:shortcut:`, then to a bare
    `emojiId` string. The non-ASCII guard keeps a custom emote's internal id
    (e.g. `UCabc/def`) from leaking through as text."""
    emoji_id = emoji.get("emojiId")
    if (not emoji.get("isCustomEmoji")
            and isinstance(emoji_id, str)
            and any(ord(ch) > 0x7F for ch in emoji_id)):
        return emoji_id
    shortcuts = emoji.get("shortcuts")
    if isinstance(shortcuts, list) and shortcuts:
        return str(shortcuts[0])
    if isinstance(emoji_id, str):
        return emoji_id
    return ""


_CHAT_RENDERERS = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer")


def parse_chat_action(action):
    """One Innertube action -> a message dict {id, user, text, ts} or None.

    Only addChatItemAction with a text or paid-message renderer yields a message;
    system/engagement items, banners, deletions, etc. -> None. A paid
    (Super Chat) message is prefixed with its amount. ts is seconds (from the
    microsecond `timestampUsec`)."""
    if not isinstance(action, dict):
        return None
    item = (action.get("addChatItemAction") or {}).get("item")
    if not isinstance(item, dict):
        return None
    renderer = None
    for key in _CHAT_RENDERERS:
        if isinstance(item.get(key), dict):
            renderer = item[key]
            paid = key == "liveChatPaidMessageRenderer"
            break
    else:
        return None
    text = runs_to_text(renderer.get("message") or {})
    if paid:
        amount = ""
        amt = renderer.get("purchaseAmountText")
        if isinstance(amt, dict):
            amount = amt.get("simpleText") or ""
        text = (f"[{amount}] {text}".strip() if amount else text).strip()
    if not text:
        return None
    author = renderer.get("authorName")
    user = author.get("simpleText") if isinstance(author, dict) else None
    ts = None
    usec = renderer.get("timestampUsec")
    try:
        ts = int(usec) / 1_000_000
    except (TypeError, ValueError):
        ts = None
    return {"id": renderer.get("id"), "user": user, "text": text, "ts": ts}


_CONTINUATION_KEYS = (
    "invalidationContinuationData",
    "timedContinuationData",
    "reloadContinuationData",
    "liveChatReplayContinuationData",
)


def _read_continuation(continuations):
    """First (continuation, timeout_ms) from a `continuations` list, across the
    several continuation-data variants YouTube uses. (None, None) if absent."""
    if not isinstance(continuations, list):
        return None, None
    for cont in continuations:
        if not isinstance(cont, dict):
            continue
        for key in _CONTINUATION_KEYS:
            data = cont.get(key)
            if isinstance(data, dict) and data.get("continuation"):
                return data["continuation"], data.get("timeoutMs")
    return None, None


def parse_live_chat(payload):
    """An Innertube get_live_chat response -> {messages, continuation, timeout_ms}.

    messages is a list of {id, user, text, ts} (unsanitised — the store applies
    `sanitize_message` with the source tag). Garbage/None -> empty result with
    continuation None (the reader then backs off / re-bootstraps)."""
    out = {"messages": [], "continuation": None, "timeout_ms": None}
    if not isinstance(payload, dict):
        return out
    cc = payload.get("continuationContents")
    live = cc.get("liveChatContinuation") if isinstance(cc, dict) else None
    if not isinstance(live, dict):
        return out
    cont, timeout = _read_continuation(live.get("continuations"))
    out["continuation"] = cont
    out["timeout_ms"] = timeout
    actions = live.get("actions")
    if isinstance(actions, list):
        for action in actions:
            msg = parse_chat_action(action)
            if msg is not None:
                out["messages"].append(msg)
    return out


# --- page bootstrap + POST body --------------------------------------------

_API_KEY_RE = re.compile(r'"INNERTUBE_API_KEY":"([^"]+)"')
_CLIENT_VERSION_RE = re.compile(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"')
_CONTINUATION_RE = re.compile(r'"continuation":"([^"]+)"')


def parse_bootstrap(html):
    """The live_chat page HTML -> {api_key, client_version, continuation}.

    Extracts the Innertube API key + client version from ytcfg and the first
    chat continuation from ytInitialData (searched from `liveChatRenderer` so an
    unrelated earlier `"continuation"` token can't win). Missing pieces are None
    (the reader treats a missing key/continuation as "not live yet")."""
    if not isinstance(html, str):
        html = ""
    key_m = _API_KEY_RE.search(html)
    ver_m = _CLIENT_VERSION_RE.search(html)
    anchor = html.find("liveChatRenderer")
    cont_m = _CONTINUATION_RE.search(html, anchor if anchor >= 0 else 0)
    return {
        "api_key": key_m.group(1) if key_m else None,
        "client_version": ver_m.group(1) if ver_m else None,
        "continuation": cont_m.group(1) if cont_m else None,
    }


def build_get_live_chat_body(continuation, client_version=None):
    """The JSON body for a get_live_chat POST."""
    return {
        "context": {"client": {
            "clientName": "WEB",
            "clientVersion": client_version or DEFAULT_CLIENT_VERSION,
        }},
        "continuation": continuation,
    }


# --- URL builders -----------------------------------------------------------

def _is_url(entry):
    return entry.startswith("http://") or entry.startswith("https://")


def channel_live_url(entry):
    """Channel id / handle URL -> its `/live` URL (resolves the current public
    live stream via yt-dlp, exactly like the relay's feed path). A bare id
    becomes the canonical `/channel/<id>/live`."""
    e = (entry or "").strip()
    if _is_url(e):
        base = e.rstrip("/")
        return base if base.endswith("/live") else base + "/live"
    return f"https://www.youtube.com/channel/{e}/live"


def channel_streams_url(entry):
    """Channel -> its `/streams` tab URL (used to enumerate ALL currently-live
    videos, which `/live` cannot — needed for the handover overlap)."""
    e = (entry or "").strip()
    if _is_url(e):
        base = e.rstrip("/")
        for suffix in ("/live", "/streams"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base + "/streams"
    return f"https://www.youtube.com/channel/{e}/streams"


def live_chat_page_url(video_id):
    """The popout live-chat page for a videoId (carries the bootstrap)."""
    return f"https://www.youtube.com/live_chat?is_popout=1&v={video_id}"


def get_live_chat_api_url(api_key):
    """The Innertube get_live_chat endpoint for a given API key."""
    return ("https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
            f"?key={api_key}&prettyPrint=false")


# --- live-set diff (producer handover) --------------------------------------

def live_set_diff(prev_ids, cur_ids):
    """(to_start, to_stop): which per-stream readers to spawn/retire when the
    channel's currently-live videoId set changes. During an A->B producer
    handover both are live for a window, so B starts while A still runs; when A
    ends it is stopped — the merged buffer stays continuous throughout."""
    prev, cur = set(prev_ids), set(cur_ids)
    return cur - prev, prev - cur


# --- Channel tab CSV --------------------------------------------------------

CHANNEL_PLATFORM_HEADERS = ("platform",)
CHANNEL_CHANNEL_HEADERS = ("channel", "url")


def _infer_platform(channel):
    c = (channel or "").lower()
    if "twitch.tv" in c:
        return "twitch"
    return "youtube"


def parse_channel_tab(text):
    """The Sheet `Channel` tab CSV -> [(platform, channel)].

    Header-located: a `Channel` (or `URL`) column is required; a `Platform`
    column is optional and inferred from the URL when absent (twitch.tv ->
    twitch, else youtube). Blank-channel rows are skipped. No header / no
    Channel column -> [] (the reader simply has nothing to follow)."""
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    header = [(h or "").strip().lower() for h in rows[0]]
    chan_i = next((header.index(h) for h in CHANNEL_CHANNEL_HEADERS if h in header), None)
    if chan_i is None:
        return []
    plat_i = next((header.index(h) for h in CHANNEL_PLATFORM_HEADERS if h in header), None)
    out = []
    for r in rows[1:]:
        channel = r[chan_i].strip() if len(r) > chan_i else ""
        if not channel:
            continue
        platform = ""
        if plat_i is not None and len(r) > plat_i:
            platform = r[plat_i].strip().lower()
        if not platform:
            platform = _infer_platform(channel)
        out.append((platform, channel))
    return out


# --- Twitch (Phase 2) -------------------------------------------------------
# Anonymous read-only chat over Twitch IRC needs no API key / OAuth: the relay
# connects to irc.chat.twitch.tv as a `justinfan` nick and JOINs #<login>. These
# pure helpers extract the login and parse a PRIVMSG line; the socket lives in
# the relay (like the YouTube network).

_TWITCH_LOGIN_RE = re.compile(r"^[a-z0-9_]{1,25}$")


def twitch_login(channel):
    """A Twitch channel URL / @handle / name -> its lowercase login, or None.

    SECURITY: the login is JOINed into the raw IRC stream, so it is strictly
    validated to Twitch's own `[a-z0-9_]{1,25}` charset — a value containing
    spaces or CRLF (which could inject IRC commands) returns None."""
    s = (channel or "").strip()
    if "/" in s:
        s = s.rstrip("/").split("/")[-1]
    s = s.lstrip("@").lower()
    return s if _TWITCH_LOGIN_RE.match(s) else None


def parse_twitch_privmsg(line):
    """One Twitch IRC line -> a message dict {id, user, text, ts} for a chat
    PRIVMSG, else None (server notices, JOIN/PART, PING, …).

    With the `twitch.tv/tags` capability a line is
    `@k=v;…;display-name=Foo;id=…;tmi-sent-ts=<ms> :nick!… PRIVMSG #chan :text`;
    the display name + message id + server timestamp come from the tags, falling
    back to the prefix nick when untagged (ts is then None — the reader stamps
    the receive time)."""
    if not isinstance(line, str) or not line:
        return None
    tags = {}
    rest = line
    if rest.startswith("@"):
        tagpart, _, rest = rest[1:].partition(" ")
        for kv in tagpart.split(";"):
            k, _, v = kv.partition("=")
            tags[k] = v
    if not rest.startswith(":"):
        return None                       # PRIVMSG always has a :prefix
    prefix, _, rest = rest[1:].partition(" ")
    parts = rest.split(" ", 2)
    if len(parts) < 3 or parts[0] != "PRIVMSG":
        return None
    text = parts[2][1:] if parts[2].startswith(":") else parts[2]
    user = tags.get("display-name") or prefix.split("!", 1)[0]
    ts = None
    sent = tags.get("tmi-sent-ts")
    if sent:
        try:
            ts = int(sent) / 1000.0
        except (TypeError, ValueError):
            ts = None
    return {"id": tags.get("id") or None, "user": user, "text": text, "ts": ts}
