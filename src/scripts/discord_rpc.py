#!/usr/bin/env python3
"""Discord voice-channel join via the local desktop-client RPC IPC socket.

Pure helpers (socket-path candidates, frame codec, message builders, the
channel-link parser, the Sheet->env target resolver, and token-cache logic) plus
a thin DiscordVoiceClient that ties them to a real socket + http_util OAuth token
exchange. The desktop client is driven so its audio plays on the machine's audio
device, where OBS's PipeWire plugin captures it. Feasibility proven live — see
docs/superpowers/specs/2026-07-04-discord-voice-join-design.md.

Secrets (client_secret, tokens) are never logged, printed, or returned."""
import csv
import io
import json
import os
import struct

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
TOKEN_URL = "https://discord.com/api/oauth2/token"
REDIRECT_URI = "http://localhost"
CONFIG_TAB = "Configuration"
VOICE_HEADER = "Discord Voice"


def ipc_candidates(os_name, env):
    """Ordered IPC endpoints where a running Discord client may listen.
    Windows uses a fixed named-pipe string (NOT os.path.join — that would inject
    backslashes wrongly and is meaningless for a pipe); POSIX joins the runtime
    bases with the socket name (incl. snap/flatpak subdirs)."""
    if os_name == "nt":
        return [r"\\?\pipe\discord-ipc-{}".format(n) for n in range(10)]
    bases = [env.get(k) for k in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")]
    bases = [b for b in bases if b] + ["/tmp"]
    out = []
    for base in bases:
        for sub in ("", "app/com.discordapp.Discord/", "snap.discord/"):
            for n in range(10):
                out.append(os.path.join(base, sub, "discord-ipc-{}".format(n)))
    return out


def encode_frame(op, payload):
    data = json.dumps(payload).encode("utf-8")
    return struct.pack("<II", op, len(data)) + data


def frame_header(buf8):
    """(opcode, payload_length) from a frame's first 8 bytes (little-endian)."""
    return struct.unpack("<II", buf8)


def msg_handshake(client_id):
    return OP_HANDSHAKE, {"v": 1, "client_id": str(client_id)}


def msg_authorize(client_id):
    return OP_FRAME, {"cmd": "AUTHORIZE",
                      "args": {"client_id": str(client_id), "scopes": ["rpc"]},
                      "nonce": "authorize"}


def msg_authenticate(access_token):
    return OP_FRAME, {"cmd": "AUTHENTICATE",
                      "args": {"access_token": access_token}, "nonce": "authenticate"}


def msg_select_voice(channel_id):
    return OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL",
                      "args": {"channel_id": str(channel_id), "force": True},
                      "nonce": "select-voice"}


def msg_leave():
    return OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL",
                      "args": {"channel_id": None, "force": True}, "nonce": "leave"}


def parse_channel_link(link):
    """'https://discord.com/channels/<guild>/<channel>' (or discord://) ->
    (guild, channel) of digit strings, else None. Structural parse — no host
    substring check (CodeQL py/incomplete-url-substring-sanitization)."""
    if not link:
        return None
    marker = "/channels/"
    i = str(link).find(marker)
    if i < 0:
        return None
    parts = str(link)[i + len(marker):].strip("/").split("/")
    if len(parts) < 2:
        return None
    guild, channel = parts[0], parts[1]
    if guild.isdigit() and channel.isdigit():
        return guild, channel
    return None


def discord_voice_from_csv(csv_text):
    """First non-empty `Discord Voice` cell from the Configuration-tab CSV, or ''."""
    rows = list(csv.reader(io.StringIO(csv_text or "")))
    if not rows:
        return ""
    try:
        idx = rows[0].index(VOICE_HEADER)
    except ValueError:
        return ""
    for row in rows[1:]:
        if idx < len(row) and row[idx].strip():
            return row[idx].strip()
    return ""


def resolve_voice_target(sheet_value, env_value):
    """Sheet override wins; else the profile.env fallback. (guild, channel) | None."""
    for value in (sheet_value, env_value):
        target = parse_channel_link(value)
        if target:
            return target
    return None


def token_valid(cache, now, skew=60):
    tok, exp = cache.get("access_token"), cache.get("expires_at")
    return bool(tok) and isinstance(exp, (int, float)) and now < exp - skew


def needs_refresh(cache, now, skew=60):
    return (not token_valid(cache, now, skew)) and bool(cache.get("refresh_token"))


def store_token(resp, now):
    """OAuth token response -> cache dict with an ABSOLUTE expiry."""
    return {"access_token": resp.get("access_token"),
            "refresh_token": resp.get("refresh_token"),
            "expires_at": now + int(resp.get("expires_in", 0)),
            "scope": resp.get("scope", "")}


def token_exchange_body(client_id, client_secret, code):
    return {"client_id": client_id, "client_secret": client_secret,
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI}


def token_refresh_body(client_id, client_secret, refresh_token):
    return {"client_id": client_id, "client_secret": client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token}
