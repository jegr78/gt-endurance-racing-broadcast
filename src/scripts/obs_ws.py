#!/usr/bin/env python3
"""Minimal obs-websocket v5 client (stdlib only, all platforms).

Why this exists: OBS's media sources hold an HTTP connection to the relay
feeds (ports 53001-53003). When a feed source is not in the active scene OBS
stops draining the socket, so killing the relay leaves an orphaned kernel
socket stuck in FIN_WAIT_1 with the port still bound (preflight then warns
"port in use"). `release_feed_inputs()` makes OBS drop exactly those
connections AFTER the feeds were killed, so the ports tear down cleanly.

How: re-applying an input's own settings (`SetInputSettings`, unchanged) is
the one request that forces OBS to rebuild the ffmpeg source and close its
socket. Media actions (STOP/RESTART) are ignored for sources that are not in
the active scene — verified live against OBS 31. The rebuild must happen
after the feed is dead: against a live relay an active source would simply
reconnect. The sources keep `restart_on_activate`, so they come back on the
next scene activation after a relay restart.

Everything is best effort: the entry point never raises — a stop must never
hang or crash because OBS is closed, locked, or speaks a newer protocol.

The WebSocket password is auto-discovered from OBS's own obs-websocket
config.json (same machine, same user); `IRO_OBS_WS_PASSWORD` in the
environment / .env overrides it for non-standard setups.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import urllib.parse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # RFC 6455 magic
DEFAULT_PORT = 4455
RELAY_PORTS = (53001, 53002, 53003)

STINT_SCENE = "Stint"                       # single-cam scene holding both feeds
FEED_SOURCES = {"A": "Feed A", "B": "Feed B"}   # scene-item name == audio input name


def feed_state_intents(live, do_cut, feeds=("A", "B"),
                       scene=STINT_SCENE, sources=None):
    """Pure: the OBS intent list that makes `live` (A/B) the on-air feed in the
    Stint scene. Visibility first, then audio, then (do_cut) the program cut.
    reflect_feed_state() turns each (verb, target) into obs-websocket requests."""
    sources = sources or FEED_SOURCES
    others = [f for f in feeds if f != live]
    intents = [("show", sources[live])] + [("hide", sources[f]) for f in others]
    intents += [("unmute", sources[live])] + [("mute", sources[f]) for f in others]
    if do_cut:
        intents.append(("cut", scene))
    return intents


# --------------------------------------------------------------------------
# WebSocket plumbing (RFC 6455) — pure functions, unit-tested
# --------------------------------------------------------------------------
def accept_key(key):
    """Server's expected Sec-WebSocket-Accept for our Sec-WebSocket-Key."""
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def handshake_request(host, port, key):
    """The HTTP Upgrade request opening the WebSocket."""
    return (f"GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n").encode()


def parse_handshake(response, key):
    """Validate the 101 response; return any bytes past the headers (OBS sends
    its Hello immediately, so the first frame may ride in with the response)."""
    head, sep, rest = response.partition(b"\r\n\r\n")
    if not sep:
        raise ValueError("incomplete WebSocket handshake response")
    lines = head.decode("iso-8859-1").split("\r\n")
    if " 101 " not in lines[0] + " ":
        raise ValueError(f"WebSocket upgrade refused: {lines[0]}")
    accept = None
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "sec-websocket-accept":
            accept = value.strip()
    if accept != accept_key(key):
        raise ValueError("WebSocket handshake: Sec-WebSocket-Accept mismatch")
    return rest


def encode_frame(payload, mask=None, opcode=0x1):
    """One masked client->server frame (RFC 6455 requires clients to mask)."""
    if mask is None:
        mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        head = bytes([0x80 | opcode, 0x80 | length])
    elif length < 1 << 16:
        head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", length)
    else:
        head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + masked


def decode_frame(buf):
    """Parse one frame from buf. Returns (opcode, payload, rest) or None if
    buf does not yet hold a complete frame. Handles masked frames too."""
    if len(buf) < 2:
        return None
    opcode = buf[0] & 0x0F
    masked = bool(buf[1] & 0x80)
    length = buf[1] & 0x7F
    pos = 2
    if length == 126:
        if len(buf) < pos + 2:
            return None
        length = struct.unpack(">H", buf[pos:pos + 2])[0]
        pos += 2
    elif length == 127:
        if len(buf) < pos + 8:
            return None
        length = struct.unpack(">Q", buf[pos:pos + 8])[0]
        pos += 8
    mask = b""
    if masked:
        if len(buf) < pos + 4:
            return None
        mask = buf[pos:pos + 4]
        pos += 4
    if len(buf) < pos + length:
        return None
    payload = buf[pos:pos + length]
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload, buf[pos + length:]


# --------------------------------------------------------------------------
# obs-websocket v5 protocol helpers — pure functions, unit-tested
# --------------------------------------------------------------------------
def auth_token(password, salt, challenge):
    """The documented v5 answer: base64(sha256(base64(sha256(pw+salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def identify_payload(hello, password):
    """Build the Identify (op 1) for a received Hello (op 0).
    Raises ValueError when OBS requires auth and we have no password."""
    d = {"rpcVersion": 1, "eventSubscriptions": 0}   # requests only, no events
    auth = hello.get("d", {}).get("authentication")
    if auth:
        if not password:
            raise ValueError("OBS WebSocket requires a password "
                             "(set IRO_OBS_WS_PASSWORD or enable auto-discovery)")
        d["authentication"] = auth_token(password, auth["salt"], auth["challenge"])
    return {"op": 1, "d": d}


def feed_input_names(inputs, get_settings, ports=RELAY_PORTS):
    """Which media inputs hold connections to the relay feed ports?
    Matches ffmpeg sources whose network URL points at localhost:<feed port>;
    local files and other URLs are left alone."""
    wanted = set()
    for port in ports:
        wanted.add(f"127.0.0.1:{port}")
        wanted.add(f"localhost:{port}")
    names = []
    for inp in inputs:
        if inp.get("inputKind") != "ffmpeg_source":
            continue
        name = inp.get("inputName")
        try:
            settings = get_settings(name) or {}
        except Exception:                            # one bad input must not stop the rest
            continue
        if settings.get("is_local_file"):
            continue
        url = settings.get("input")
        if isinstance(url, str) and urllib.parse.urlsplit(url.strip()).netloc in wanted:
            names.append(name)
    return names


def browser_input_names(inputs, get_settings, needle="127.0.0.1:8088"):
    """Which browser sources show relay-served pages (HUD, race timer)?
    Matches by URL substring so any future relay page is covered without a
    name list; local-file pages and other URLs are left alone."""
    names = []
    for inp in inputs:
        if inp.get("inputKind") != "browser_source":
            continue
        name = inp.get("inputName")
        try:
            settings = get_settings(name) or {}
        except Exception:                            # one bad input must not stop the rest
            continue
        url = settings.get("url")
        if isinstance(url, str) and needle in url:
            names.append(name)
    return names


# --------------------------------------------------------------------------
# Password / port discovery from OBS's own obs-websocket config
# --------------------------------------------------------------------------
def obs_config_path(platform, env, home):
    """Per-OS location of obs-websocket's config.json (explicit separators so
    the pure function gives identical answers on every host OS)."""
    if platform == "darwin":
        return home + "/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
    if platform.startswith("win"):
        base = env.get("APPDATA") or home + "\\AppData\\Roaming"
        return base + "\\obs-studio\\plugin_config\\obs-websocket\\config.json"
    return home + "/.config/obs-studio/plugin_config/obs-websocket/config.json"


def read_ws_config(path):
    """obs-websocket's config.json as a small dict, or None if unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return {"password": data.get("server_password"),
            "port": data.get("server_port", DEFAULT_PORT),
            "auth_required": data.get("auth_required", True),
            "enabled": data.get("server_enabled", True)}


def default_config_path():
    return obs_config_path(sys.platform, os.environ, os.path.expanduser("~"))


def find_password(env, config_path):
    """IRO_OBS_WS_PASSWORD wins; else OBS's own stored server password."""
    override = env.get("IRO_OBS_WS_PASSWORD")
    if override:
        return override
    cfg = read_ws_config(config_path)
    return cfg["password"] if cfg else None


# --------------------------------------------------------------------------
# Tiny request/response client
# --------------------------------------------------------------------------
class _Session:
    """One identified obs-websocket connection; request() is synchronous."""

    def __init__(self, sock, buf):
        self.sock = sock
        self.buf = buf
        self.counter = 0

    def next_json(self):
        """Next text message as JSON; answers pings, raises on close/EOF."""
        while True:
            frame = decode_frame(self.buf)
            if frame is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("OBS closed the connection")
                self.buf += chunk
                continue
            opcode, payload, self.buf = frame
            if opcode == 0x9:                       # ping -> pong
                self.sock.sendall(encode_frame(payload, opcode=0xA))
            elif opcode == 0x8:
                raise ConnectionError("OBS closed the connection")
            elif opcode == 0x1:
                return json.loads(payload)

    def send_json(self, obj):
        self.sock.sendall(encode_frame(json.dumps(obj).encode()))

    def request(self, request_type, request_data):
        self.counter += 1
        rid = f"iro-{self.counter}"
        self.send_json({"op": 6, "d": {"requestType": request_type,
                                       "requestId": rid,
                                       "requestData": request_data}})
        while True:
            msg = self.next_json()
            if msg.get("op") == 7 and msg["d"].get("requestId") == rid:
                if not msg["d"].get("requestStatus", {}).get("result"):
                    raise ValueError(f"{request_type} failed: "
                                     f"{msg['d'].get('requestStatus')}")
                return msg["d"].get("responseData", {})

    def close(self):
        try:
            self.sock.sendall(encode_frame(b"", opcode=0x8))   # polite close
        except OSError:
            pass  # OBS may have dropped the socket first — close is courtesy only
        self.sock.close()


def _open_session(host, port, password, timeout):
    """Connect + WebSocket upgrade + obs-websocket identify. Returns an
    identified _Session; raises on any failure (callers translate that into
    their best-effort (names, note) contract)."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(handshake_request(host, port, key))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("OBS closed during the handshake")
            response += chunk
        session = _Session(sock, parse_handshake(response, key))
        hello = session.next_json()
        session.send_json(identify_payload(hello, password))
        identified = session.next_json()
        if identified.get("op") != 2:
            raise ValueError("OBS WebSocket identify failed")
        return session
    except Exception:
        sock.close()
        raise


def _connect(host, port, password, timeout):
    """(session, "") or (None, reason). Port + password fall back to OBS's own
    obs-websocket config / IRO_OBS_WS_PASSWORD; never raises."""
    cfg = read_ws_config(default_config_path())
    if port is None:
        port = (cfg or {}).get("port") or DEFAULT_PORT
    if password is None:
        password = find_password(os.environ, default_config_path())
    try:
        return _open_session(host, port, password, timeout), ""
    except OSError:
        return None, f"OBS WebSocket not reachable on {host}:{port} (OBS not running?)"
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__


def release_feed_inputs(ports=RELAY_PORTS, host="127.0.0.1", port=None,
                        password=None, timeout=2.0):
    """Make OBS drop its connections to the (just killed) relay feed ports by
    re-applying each feed input's own settings — a forced source rebuild that
    closes the socket without changing anything (see module docstring).

    Returns (released_input_names, note). Best effort by design: any failure —
    OBS not running, wrong password, protocol surprise — yields ([], reason)
    and NEVER an exception; stopping the relay must always go through.
    """
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    try:
        inputs = session.request("GetInputList",
                                 {"inputKind": "ffmpeg_source"}).get("inputs", [])
        settings = {}                                # filled by the name filter

        def get_settings(name):
            settings[name] = session.request(
                "GetInputSettings", {"inputName": name}).get("inputSettings", {})
            return settings[name]

        names = feed_input_names(inputs, get_settings, ports)
        for name in names:
            session.request("SetInputSettings",      # unchanged -> rebuild only
                            {"inputName": name, "inputSettings": settings[name],
                             "overlay": True})
        return names, ""
    except Exception as exc:                         # noqa: BLE001 — see docstring
        return [], str(exc) or exc.__class__.__name__
    finally:
        session.close()


def refresh_browser_inputs(needle="127.0.0.1:8088", host="127.0.0.1", port=None,
                           password=None, timeout=2.0):
    """Press 'Refresh cache of current page' (refreshnocache) on every browser
    source whose URL points at the relay — the programmatic right-click →
    Refresh, used after the shipped HUD/timer pages changed (OBS's CEF caches
    the page JS until then).

    Returns (refreshed_input_names, note). Best effort like
    release_feed_inputs(): any failure yields ([], reason), never an exception.
    """
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    try:
        inputs = session.request("GetInputList",
                                 {"inputKind": "browser_source"}).get("inputs", [])

        def get_settings(name):
            return session.request("GetInputSettings",
                                   {"inputName": name}).get("inputSettings", {})

        names = browser_input_names(inputs, get_settings, needle)
        for name in names:
            session.request("PressInputPropertiesButton",
                            {"inputName": name, "propertyName": "refreshnocache"})
        return names, ""
    except Exception as exc:                         # noqa: BLE001 — see docstring
        return [], str(exc) or exc.__class__.__name__
    finally:
        session.close()
