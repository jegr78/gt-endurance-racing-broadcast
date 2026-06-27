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
from urllib.parse import urlsplit

MAX_MESSAGES = 500      # ring-buffer / display cap (oldest dropped)
MAX_TEXT = 500          # per-message character cap
MAX_NAME = 60           # author-name character cap (YT names run long)
MAX_TOKENS = 80         # per-message token cap (#351); over it -> flat text only
DEFAULT_NAME = "Viewer"  # fallback when no/blank author name is supplied

# --- image-emote URL allowlist (#351) ---------------------------------------
# Inline emote <img> sources are validated against these hosts BEFORE they reach
# the front-end (defense in depth alongside the page CSP). The YouTube emote URL
# comes from Google's payload, so it must be checked; the Twitch URL is built
# from a validated id but is checked the same way. The check parses the URL and
# compares the host component structurally -- never a substring of the raw URL
# (which would match an attacker's `https://evil/yt3.ggpht.com/...`).
_EMOTE_HOST_EXACT = ("static-cdn.jtvnw.net",)   # Twitch CDN
_EMOTE_HOST_SUFFIX = (".ggpht.com",)            # YouTube emote CDN (yt3/yt4.…)


def emote_url_ok(url):
    """True iff `url` is an https URL whose host is an allowlisted emote CDN."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    if host in _EMOTE_HOST_EXACT:
        return True
    return any(host.endswith(sfx) for sfx in _EMOTE_HOST_SUFFIX)

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
    """Coerce one raw message into {ts, user, text, source[, tokens]} or None.
    ts must be numeric; text must be non-empty after cleaning; user falls back to
    DEFAULT_NAME. `source` tags which live stream the message came from (the
    videoId) so a handover overlap can be shown/merged. `tokens` (#351) is added
    only when the message carries at least one valid image emote -- otherwise the
    flat `text` is the whole display and no tokens are sent."""
    if not isinstance(raw, dict) or not _is_num(raw.get("ts")):
        return None
    text = _clean_text(raw.get("text")).strip()
    if not text:
        return None
    user = _clean_text(raw.get("user")).strip() or DEFAULT_NAME
    msg = {"ts": float(raw["ts"]), "user": user[:MAX_NAME],
           "text": text[:MAX_TEXT], "source": source}
    tokens = sanitize_tokens(raw.get("tokens"))
    if tokens is not None:
        msg["tokens"] = tokens
    return msg


def _append_text(tokens, value):
    """Append `value` as a text token, merging into a trailing text token."""
    if not value:
        return
    if tokens and tokens[-1].get("t") == "text":
        tokens[-1]["v"] += value
    else:
        tokens.append({"t": "text", "v": value})


def sanitize_tokens(raw_tokens):
    """A raw token list -> a cleaned [{t:text,v}|{t:emote,url,alt}] list, or None.

    Returns None unless the list contains at least one valid emote token (a flat
    `text` field then suffices). An emote whose URL fails `emote_url_ok` degrades
    to a text token of its `alt`; text tokens are control-stripped and merged.
    Over MAX_TOKENS tokens -> None (the absurd case falls back to flat text)."""
    if not isinstance(raw_tokens, list):
        return None
    out = []
    has_emote = False
    for tok in raw_tokens:
        if not isinstance(tok, dict):
            continue
        kind = tok.get("t")
        if kind == "emote":
            url = tok.get("url")
            alt = _clean_text(tok.get("alt")).strip()[:MAX_NAME]
            if isinstance(url, str) and emote_url_ok(url):
                out.append({"t": "emote", "url": url, "alt": alt})
                has_emote = True
            else:
                _append_text(out, alt)
        elif kind == "text":
            _append_text(out, _clean_text(tok.get("v")))
    if not has_emote or len(out) > MAX_TOKENS:
        return None
    return out


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


def _emoji_image_url(emoji):
    """The largest thumbnail URL of a YouTube emoji run, or "" if absent.
    YouTube lists thumbnails smallest-first, so the last entry is the largest."""
    image = emoji.get("image")
    thumbs = image.get("thumbnails") if isinstance(image, dict) else None
    if isinstance(thumbs, list) and thumbs and isinstance(thumbs[-1], dict):
        url = thumbs[-1].get("url")
        if isinstance(url, str) and url:
            return url
    return ""


def _emoji_to_token(emoji):
    """One YouTube emoji run -> a single token.

    A STANDARD emoji is its Unicode glyph (a text token, matching #345). A CUSTOM
    channel emote becomes an `emote` token from its image thumbnail when one
    exists; without an image it degrades to a `:shortcut:` text token. The URL is
    validated later (sanitize_tokens), so the host allowlist lives in one place."""
    emoji_id = emoji.get("emojiId")
    if (not emoji.get("isCustomEmoji")
            and isinstance(emoji_id, str)
            and any(ord(ch) > 0x7F for ch in emoji_id)):
        return {"t": "text", "v": emoji_id}
    url = _emoji_image_url(emoji)
    if url:
        return {"t": "emote", "url": url, "alt": _emoji_to_text(emoji)}
    return {"t": "text", "v": _emoji_to_text(emoji)}


def runs_to_tokens(message):
    """A YouTube chat `message` -> a token list [{t:text,v}|{t:emote,url,alt}],
    or None when the message has no image emote (the flat text is the whole
    display). Mirrors `runs_to_text` but preserves custom-emote image URLs."""
    if not isinstance(message, dict):
        return None
    runs = message.get("runs")
    if not isinstance(runs, list):
        return None        # simpleText / unexpected -> flat text suffices
    tokens = []
    has_emote = False
    for run in runs:
        if not isinstance(run, dict):
            continue
        if isinstance(run.get("text"), str):
            _append_text(tokens, run["text"])
        elif isinstance(run.get("emoji"), dict):
            tok = _emoji_to_token(run["emoji"])
            if tok["t"] == "emote":
                has_emote = True
                tokens.append(tok)
            else:
                _append_text(tokens, tok["v"])
    return tokens if has_emote else None


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
    message = renderer.get("message") or {}
    text = runs_to_text(message)
    tokens = runs_to_tokens(message)
    if paid:
        amount = ""
        amt = renderer.get("purchaseAmountText")
        if isinstance(amt, dict):
            amount = amt.get("simpleText") or ""
        if amount:
            text = f"[{amount}] {text}".strip()
            if tokens is not None:
                tokens = [{"t": "text", "v": f"[{amount}] "}] + tokens
        text = text.strip()
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
    out = {"id": renderer.get("id"), "user": user, "text": text, "ts": ts}
    if tokens is not None:
        out["tokens"] = tokens
    return out


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


def youtube_video_id(value):
    """A YouTube videoId validated to `[A-Za-z0-9_-]{11}`, else None.
    SECURITY: the id is interpolated into the popout URL handed to the browser."""
    return value if isinstance(value, str) and _YT_VIDEO_ID_RE.match(value) else None


def twitch_popout_chat_url(login):
    """A validated Twitch login -> its popout chat URL (carries a compose box for
    a signed-in user). `login` is constrained by twitch_login()."""
    return f"https://www.twitch.tv/popout/{login}/chat"


def primary_chat_target(keys):
    """The first compose target from an ordered list of supervisor reader keys
    (a YouTube videoId, or "twitch:<login>"), as {"platform", "url"}, or None.

    KISS: a broadcast stays on one channel/platform; during an A->B producer
    handover two YouTube videoIds are briefly live and the FIRST is used. Pure;
    mirrors the key convention of BroadcastChatSupervisor._desired()."""
    for key in keys or []:
        if not isinstance(key, str):
            continue
        if key.startswith("twitch:"):
            login = twitch_login(key[len("twitch:"):])
            if login:
                return {"platform": "twitch", "url": twitch_popout_chat_url(login)}
        else:
            vid = youtube_video_id(key)
            if vid:
                return {"platform": "youtube", "url": live_chat_page_url(vid)}
    return None


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
# A YouTube videoId is interpolated into the popout URL handed to the browser,
# so it is validated to YouTube's own 11-char id charset (defense vs. URL
# injection, mirroring _TWITCH_LOGIN_RE).
_YT_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# An emote id is interpolated into a CDN URL, so it is validated to Twitch's own
# id charset (digits, or the `emotesv2_<hex>` form) -- never a `/` or space.
_TWITCH_EMOTE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def twitch_emote_url(emote_id):
    """A validated Twitch emote id -> its 1.0 dark-theme CDN URL (#351)."""
    return (f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}"
            "/default/dark/1.0")


def splice_twitch_emotes(text, emotes_tag):
    """Twitch PRIVMSG text + its IRC `emotes` tag -> a token list, or None.

    The tag is `<id>:<s>-<e>[,<s>-<e>][/<id>:…]` with INCLUSIVE **codepoint**
    offsets into `text` (Python str indexing counts codepoints the same way). The
    spans are spliced in order; the gaps become text tokens and each span an
    `emote` token (alt = the matched word). A malformed/out-of-range span, an id
    outside `[A-Za-z0-9_]`, or an overlap is skipped. Returns None when no emote
    parsed, so the caller keeps the flat text."""
    if not isinstance(text, str) or not isinstance(emotes_tag, str) or not emotes_tag:
        return None
    chars = list(text)
    n = len(chars)
    spans = []                       # (start, end_inclusive, id)
    for group in emotes_tag.split("/"):
        eid, sep, ranges = group.partition(":")
        if not sep or not _TWITCH_EMOTE_ID_RE.match(eid):
            continue
        for rng in ranges.split(","):
            a, dash, b = rng.partition("-")
            if not dash:
                continue
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            if 0 <= start <= end < n:
                spans.append((start, end, eid))
    if not spans:
        return None
    spans.sort()
    tokens = []
    cursor = 0
    for start, end, eid in spans:
        if start < cursor:           # overlapping/duplicate span -> skip
            continue
        _append_text(tokens, "".join(chars[cursor:start]))
        tokens.append({"t": "emote", "url": twitch_emote_url(eid),
                       "alt": "".join(chars[start:end + 1])})
        cursor = end + 1
    _append_text(tokens, "".join(chars[cursor:]))
    return tokens


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
    out = {"id": tags.get("id") or None, "user": user, "text": text, "ts": ts}
    tokens = splice_twitch_emotes(text, tags.get("emotes", ""))
    if tokens is not None:
        out["tokens"] = tokens
    return out
