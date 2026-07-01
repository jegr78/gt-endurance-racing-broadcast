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
config.json (same machine, same user); `RACECAST_OBS_WS_PASSWORD` in the
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
CLOSE_DRAIN_TIMEOUT_S = 1.0   # max seconds to wait for OBS's close echo before closing the socket

STINT_SCENE = "Stint"                       # single-cam scene holding both feeds
INTERMISSION_SCENE = "Intermission"          # the safe holding scene (#371); auto-failover target (#378)
POV_SOURCE = "Feed POV"                      # the Stint-scene driver-POV PiP scene item
FEED_SOURCES = {"A": "Feed A", "B": "Feed B"}   # scene-item name == audio input name

# The scene collection the broadcast assumes. Mirrors the "name" field of
# src/obs/GT_Endurance.json (the name OBS shows after importing the localized
# collection). Keep the two in sync. Not a secret, so the no-hardcoding rule
# does not apply; not parsed at runtime because the file is renamed + tokenized
# in the shipped package and bundled differently when frozen.
EXPECTED_SCENE_COLLECTION = "GT Endurance Racing"


def scene_collection_status(current, available, expected=EXPECTED_SCENE_COLLECTION):
    """Pure: classify the active OBS scene collection. `current` is OBS's
    currentSceneCollectionName; `available` is the full list it reported.
    Returns a dict (see keys below). The only "correct" state is match=True;
    renamed_variant flags a non-exact "GT Endurance Racing*" (e.g. an import-renamed
    'GT Endurance Racing 2'), which we never switch to automatically."""
    available = list(available)
    # A correct collection wins: never flag a renamed variant when we already match.
    renamed = None if current == expected else next(
        (n for n in available
         if n != expected and isinstance(n, str) and n.startswith(expected)), None)
    return {"current": current, "expected": expected, "available": available,
            "match": current == expected,
            "expected_present": expected in available,
            "renamed_variant": renamed}


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


def pov_scene_item_transform(box):
    """Map a full POV box {left,top,width,height} to an obs-websocket
    sceneItemTransform. The Feed POV item is top-left anchored (alignment 5) with
    SCALE_INNER bounds (boundsType 2); all fields are sent explicitly so the
    result is idempotent regardless of the item's current bounds settings."""
    return {"positionX": box["left"], "positionY": box["top"],
            "boundsType": 2, "boundsAlignment": 0, "alignment": 5,
            "boundsWidth": box["width"], "boundsHeight": box["height"]}


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
                             "(set RACECAST_OBS_WS_PASSWORD or enable auto-discovery)")
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
# Source screenshots (GetSourceScreenshot) — pure helpers, unit-tested
# --------------------------------------------------------------------------
def screenshot_request_data(source_name, width=640, fmt="jpg", quality=60):
    """requestData for GetSourceScreenshot: a scaled still of a source/scene."""
    return {"sourceName": source_name, "imageFormat": fmt,
            "imageWidth": int(width), "imageCompressionQuality": int(quality)}


def parse_screenshot_data_uri(data_uri):
    """Decode a GetSourceScreenshot 'imageData' value
    (data:image/<fmt>;base64,<payload>) to raw bytes; None on a malformed URI."""
    if not isinstance(data_uri, str):
        return None
    head, sep, payload = data_uri.partition(",")
    if not sep or not head.startswith("data:") or "base64" not in head:
        return None
    try:
        return base64.b64decode(payload, validate=True)   # binascii.Error subclasses ValueError
    except ValueError:
        return None


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
    """RACECAST_OBS_WS_PASSWORD wins; else OBS's own stored server password."""
    override = env.get("RACECAST_OBS_WS_PASSWORD")
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
        rid = f"racecast-{self.counter}"
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
        """Best-effort RFC 6455 closing handshake so OBS logs a clean 1000 close
        instead of an abnormal 1006/EOF: send a status-1000 close frame, then briefly
        read OBS's close echo / EOF (bounded by CLOSE_DRAIN_TIMEOUT_S) so OBS can
        finish its side of the close before the socket goes away, then close it.

        We deliberately do NOT shutdown(SHUT_WR): sending a TCP FIN right after the
        close frame makes OBS's WebSocket server log the disconnect as 1006/"End of
        File" instead of 1000 — verified empirically against a live OBS. Letting the
        server send its close echo and close the TCP first (we read to EOF) yields a
        clean 1000. Never raises; never blocks past the drain timeout."""
        try:
            self.sock.sendall(encode_frame(struct.pack(">H", 1000), opcode=0x8))
        except OSError:
            pass  # OBS may have dropped the socket first — the rest is courtesy only
        try:
            self.sock.settimeout(CLOSE_DRAIN_TIMEOUT_S)
            while self.sock.recv(65536):   # drain OBS's close echo until EOF / timeout
                pass
        except OSError:
            pass  # timeout or reset — stop draining and close
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


def resolve_obs_target(host, port, env, cfg):
    """Where to reach OBS. RACECAST_OBS_WS_HOST / RACECAST_OBS_WS_PORT override
    everything — a test/proxy seam (point the relay at a simulated OBS for
    reproducible screenshots, or at OBS on another host) — otherwise the host the
    caller passed plus OBS's own config port (then the 4455 default)."""
    host = env.get("RACECAST_OBS_WS_HOST") or host
    if port is None:
        p = (env.get("RACECAST_OBS_WS_PORT") or "").strip()
        port = int(p) if p.isdigit() else ((cfg or {}).get("port") or DEFAULT_PORT)
    return host, port


def _connect(host, port, password, timeout):
    """(session, "") or (None, reason). Host/port/password fall back to the
    RACECAST_OBS_WS_* overrides, then OBS's own obs-websocket config; never raises."""
    cfg = read_ws_config(default_config_path())
    host, port = resolve_obs_target(host, port, os.environ, cfg)
    if password is None:
        password = find_password(os.environ, default_config_path())
    try:
        return _open_session(host, port, password, timeout), ""
    except OSError:
        return None, f"OBS WebSocket not reachable on {host}:{port} (OBS not running?)"
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__


def _pct(part, total):
    """skipped/total as a rounded percentage, or None when either is missing or
    total is zero (avoid a div-by-zero and a meaningless 0/0)."""
    if part is None or not total:
        return None
    return round(part / total * 100.0, 2)


def stream_kbps(prev_bytes, prev_ts, bytes_, ts, active):
    """Upstream kbps from successive outputBytes samples. None resets the line on
    stream stop/restart so no ghost spike appears."""
    if not active or bytes_ is None or prev_bytes is None or prev_ts is None:
        return None
    dt = ts - prev_ts
    if dt <= 0 or bytes_ < prev_bytes:
        return None
    return round((bytes_ - prev_bytes) * 8 / 1000.0 / dt, 1)


def parse_obs_stats(payload):
    """Flatten a GetStats response into the health field names. Missing keys -> None."""
    p = payload or {}
    return {
        "obs_cpu_pct": p.get("cpuUsage"),
        "obs_mem_mb": p.get("memoryUsage"),
        "obs_disk_free_mb": p.get("availableDiskSpace"),
        "obs_fps": p.get("activeFps"),
        "obs_render_skipped_pct": _pct(p.get("renderSkippedFrames"),
                                       p.get("renderTotalFrames")),
    }


def parse_stream_status(payload):
    """Flatten a GetStreamStatus response. outputBytes is returned raw (the caller
    derives kbps from successive samples); missing keys -> None."""
    p = payload or {}
    active = p.get("outputActive")
    recon = p.get("outputReconnecting")
    return {
        "stream_active": None if active is None else bool(active),
        "stream_reconnecting": None if recon is None else bool(recon),
        "stream_timecode": p.get("outputTimecode"),
        "stream_congestion": p.get("outputCongestion"),
        "stream_dropped_pct": _pct(p.get("outputSkippedFrames"),
                                   p.get("outputTotalFrames")),
        "output_bytes": p.get("outputBytes"),
    }


# Single-channel event -> OBS rtmp_common service name. Platform values come from
# the Sheet `Channel` tab (broadcast_chat.parse_channel_tab), lowercased.
OBS_STREAM_SERVICE_NAMES = {"youtube": "YouTube - RTMPS", "twitch": "Twitch"}


def stream_service_payload(platform, key):
    """Build SetStreamServiceSettings request data for a single-channel event.
    `platform` is the Channel-tab value ('youtube'/'twitch', case-insensitive);
    unknown -> ValueError (the caller turns it into a producer-facing note, never
    a crash). The key is passed through verbatim and never logged."""
    name = OBS_STREAM_SERVICE_NAMES.get((platform or "").strip().lower())
    if not name:
        raise ValueError(f"unknown stream platform: {platform!r}")
    return {"streamServiceType": "rtmp_common",
            "streamServiceSettings": {"service": name, "server": "auto", "key": key}}


def get_health_stats(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """One obs-websocket session -> (reachable, stats, note). `stats` is the merged
    parse_obs_stats + parse_stream_status dict (empty {} when the requests fail but
    the session opened). Best-effort: never raises (same contract as probe())."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, {}, note
    try:
        stats = parse_obs_stats(session.request("GetStats", {}))
        stats.update(parse_stream_status(session.request("GetStreamStatus", {})))
        return True, stats, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return True, {}, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def probe(host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Lightweight OBS reachability check used by the relay's /status: open an
    obs-websocket session (handshake + auth) and close it at once, touching
    nothing in OBS. Returns (reachable: bool, note: str) — (False, reason) when
    OBS is closed/locked/mis-keyed, (True, "") on a full identify. Never raises
    (same best-effort contract as the other entry points)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    session.close()
    return True, ""


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


def get_source_screenshot(source_name, width=640, fmt="jpg", quality=60,
                          host="127.0.0.1", port=None, password=None, timeout=2.0):
    """A scaled screenshot of an OBS source/scene as raw JPEG bytes.
    Returns (bytes, "") or (None, note). Best effort — never raises (same
    contract as release_feed_inputs/get_scene_collection)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        resp = session.request(
            "GetSourceScreenshot",
            screenshot_request_data(source_name, width, fmt, quality))
        data = parse_screenshot_data_uri(resp.get("imageData"))
        if data is None:
            return None, "OBS returned no image data"
        return data, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def get_program_screenshot(width=640, fmt="jpg", quality=60,
                           host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Screenshot the current OBS program scene (what viewers see) as raw JPEG
    bytes. Resolves the active scene name, then screenshots it on the same
    session. Returns (bytes, "") or (None, note). Best effort — never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        cur = session.request("GetCurrentProgramScene", {})
        scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        if not scene:
            return None, "OBS returned no program scene"
        resp = session.request(
            "GetSourceScreenshot",
            screenshot_request_data(scene, width, fmt, quality))
        data = parse_screenshot_data_uri(resp.get("imageData"))
        if data is None:
            return None, "OBS returned no image data"
        return data, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def get_current_program_scene(host="127.0.0.1", port=None,
                              password=None, timeout=2.0):
    """The name of the current OBS program scene (what viewers see), or None.
    Returns (scene_name, "") or (None, note). Best effort — never raises (same
    contract as get_program_screenshot). Used by the auto-failover guard (#378)
    to fire ONLY while OBS is still on the on-air feed scene."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        cur = session.request("GetCurrentProgramScene", {})
        scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        if not scene:
            return None, "OBS returned no program scene"
        return scene, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


_TRANSITION_KIND = {"cut": "cut_transition", "fade": "fade_transition",
                    "stinger": "stinger_transition"}
_TRANSITION_NAME_FALLBACK = {"cut": "cut", "fade": "fade"}


def resolve_transition(choice, transitions):
    """Resolve a director choice ('cut'|'fade'|'stinger') to a concrete OBS
    transition NAME, matched by kind against a GetSceneTransitionList payload
    (list of {transitionName, transitionKind}); falls back to a case-insensitive
    name match for cut/fade. Returns (name|None, note). Stinger with none
    configured -> (None, note). Pure; never raises."""
    kind = _TRANSITION_KIND.get(choice)
    for t in transitions or []:
        if kind and t.get("transitionKind") == kind:
            return (t.get("transitionName"), "")
    fb = _TRANSITION_NAME_FALLBACK.get(choice)
    if fb:
        for t in transitions or []:
            if (t.get("transitionName") or "").lower() == fb:
                return (t.get("transitionName"), "")
    if choice == "stinger":
        return (None, "no Stinger configured in OBS; used Cut")
    return (None, "")


def set_current_program_scene(scene, host="127.0.0.1", port=None,
                              password=None, timeout=2.0,
                              transition=None, duration_ms=None):
    """Switch the OBS program scene (best effort). When `transition`
    ('cut'|'fade'|'stinger') is given, set that transition (resolved by kind via
    GetSceneTransitionList) + duration first, then switch — so a director take
    uses the chosen transition. Stinger with none configured degrades to Cut and
    returns a note. (ok, note); never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    out_note = ""
    try:
        if transition:
            tlist = session.request("GetSceneTransitionList", {}).get("transitions", [])
            name, resolve_note = resolve_transition(transition, tlist)
            if name is None and transition == "stinger":
                name, _ = resolve_transition("cut", tlist)     # degrade to a cut
                out_note = resolve_note
            if name:
                session.request("SetCurrentSceneTransition", {"transitionName": name})
                if transition != "cut" and duration_ms is not None:
                    session.request("SetCurrentSceneTransitionDuration",
                                    {"transitionDuration": int(duration_ms)})
        session.request("SetCurrentProgramScene", {"sceneName": scene})
        return True, out_note
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_input_volume(input_name, volume_db, host="127.0.0.1", port=None,
                     password=None, timeout=2.0):
    """Set an OBS audio input volume in dB (best effort). (ok, note)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        session.request("SetInputVolume",
                        {"inputName": input_name, "inputVolumeDb": float(volume_db)})
        return True, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_input_mute(input_name, muted, host="127.0.0.1", port=None,
                   password=None, timeout=2.0):
    """Set an OBS audio input mute state (best effort). (ok, note)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        session.request("SetInputMute",
                        {"inputName": input_name, "inputMuted": bool(muted)})
        return True, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_stream(active, host="127.0.0.1", port=None,
               password=None, timeout=2.0):
    """Start or stop the OBS stream output (best effort). `active` True ->
    StartStream, False -> StopStream. Idempotent: if OBS is ALREADY in the
    requested state, returns (True, "") without sending a start/stop, so a
    double-click or retry never surfaces OBS's "output already active" error.
    (ok, note); never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active") == bool(active):
            return True, ""                       # already in the desired state
        session.request("StartStream" if active else "StopStream", {})
        return True, ""
    except Exception as exc:                       # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_stream_service(platform, key, host="127.0.0.1", port=None,
                       password=None, timeout=2.0):
    """Set OBS's stream service + key for a single-channel event (best effort).
    HARD GUARD: refuses while OBS is streaming — a live service/key change is
    unsafe — returning (False, "OBS is streaming — stop the broadcast before
    changing the stream target."). Unknown platform / unreachable OBS -> (False,
    note). The key is applied to OBS and NEVER logged. (ok, note); never raises."""
    try:
        data = stream_service_payload(platform, key)
    except ValueError as exc:
        return False, str(exc)
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        status = parse_stream_status(session.request("GetStreamStatus", {}))
        if status.get("stream_active"):
            return False, ("OBS is streaming — stop the broadcast before "
                           "changing the stream target.")
        session.request("SetStreamServiceSettings", data)
        return True, ""
    except Exception as exc:                       # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def read_obs_state(sources, inputs, host="127.0.0.1", port=None,
                   password=None, timeout=2.0):
    """One-session panel-refresh snapshot: current program scene + the enabled state
    of each (scene, source) + the mute/volume of each audio input. `sources` =
    [(scene, source), …]; `inputs` = [name, …]. Returns (state, "") or (None, note);
    a per-item OBS error leaves that item's fields None rather than failing the whole
    read. Best effort — never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        cur = session.request("GetCurrentProgramScene", {})
        scene = cur.get("currentProgramSceneName") or cur.get("sceneName")
        src_out = []
        for sc, src in sources:
            try:
                sid = session.request(
                    "GetSceneItemId",
                    {"sceneName": sc, "sourceName": src}).get("sceneItemId")
                enabled = session.request(
                    "GetSceneItemEnabled",
                    {"sceneName": sc, "sceneItemId": sid}).get("sceneItemEnabled")
            except Exception:                         # noqa: BLE001 — per-item best effort
                enabled = None
            src_out.append({"scene": sc, "source": src, "enabled": enabled})
        aud_out = []
        for name in inputs:
            try:
                muted = session.request(
                    "GetInputMute", {"inputName": name}).get("inputMuted")
                vol = session.request(
                    "GetInputVolume", {"inputName": name}).get("inputVolumeDb")
            except Exception:                         # noqa: BLE001 — per-item best effort
                muted, vol = None, None
            aud_out.append({"input": name, "muted": muted, "volumeDb": vol})
        try:
            st = parse_stream_status(session.request("GetStreamStatus", {}))
            stream = {"active": st.get("stream_active"),
                      "reconnecting": st.get("stream_reconnecting"),
                      "timecode": st.get("stream_timecode")}
        except Exception:                         # noqa: BLE001 — per-item best effort
            stream = None
        return {"scene": scene, "sources": src_out,
                "audio": aud_out, "stream": stream}, ""
    except Exception as exc:                          # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def reflect_feed_state(live, do_cut, scene=STINT_SCENE, sources=None,
                       host="127.0.0.1", port=None, password=None, timeout=2.0):
    """Reflect which feed (A/B) is on air into OBS: show/hide the Stint-scene
    sources, mute/unmute the feed audio inputs, and (do_cut) cut the program to
    Stint. Best effort by design: returns (applied_intents, note) and NEVER
    raises — a handover must go through even if OBS is closed/locked. On any
    failure the relay falls back to the manual panel/Companion controls."""
    intents = feed_state_intents(live, do_cut, scene=scene, sources=sources)
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return [], note
    applied = []
    try:
        for verb, target in intents:
            if verb in ("show", "hide"):
                sid = session.request("GetSceneItemId",
                                      {"sceneName": scene, "sourceName": target}).get("sceneItemId")
                if sid is None:
                    raise ValueError(f"scene item '{target}' not found in scene '{scene}'")
                session.request("SetSceneItemEnabled",
                                {"sceneName": scene, "sceneItemId": sid,
                                 "sceneItemEnabled": verb == "show"})
            elif verb in ("mute", "unmute"):
                session.request("SetInputMute",
                                {"inputName": target, "inputMuted": verb == "mute"})
            elif verb == "cut":
                session.request("SetCurrentProgramScene", {"sceneName": target})
            applied.append((verb, target))
        return applied, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return applied, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_feed_close_when_inactive(inputs, value=True, host="127.0.0.1", port=None,
                                  password=None, timeout=2.0):
    """Set close_when_inactive on each named feed media input (best effort).
    When fan-out is enabled, OBS disconnects off-air sources so no stale
    backlog forms and the ~2 s stale-on-activation glitch is eliminated.
    `inputs` is a list of OBS input names (e.g. FEED_SOURCES.values() +
    [POV_SOURCE]). Returns "" on success or a short note on any failure;
    never raises."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return note
    try:
        for name in inputs:
            session.request("SetInputSettings",
                            {"inputName": name,
                             "inputSettings": {"close_when_inactive": bool(value)},
                             "overlay": True})
        return ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_scene_item_enabled(scene, source, enabled, host="127.0.0.1", port=None,
                           password=None, timeout=2.0):
    """Enable/disable a scene item (best effort). Returns (ok, note); (False,
    reason) on any failure — OBS closed, wrong password, item missing — NEVER an
    exception (same contract as release_feed_inputs/get_scene_collection)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        sid = session.request("GetSceneItemId",
                              {"sceneName": scene, "sourceName": source}).get("sceneItemId")
        if sid is None:
            return False, f"scene item '{source}' not found in scene '{scene}'"
        session.request("SetSceneItemEnabled",
                        {"sceneName": scene, "sceneItemId": sid,
                         "sceneItemEnabled": bool(enabled)})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_scene_item_transform(scene, source, transform, host="127.0.0.1", port=None,
                             password=None, timeout=2.0):
    """Set a scene item's transform (best effort). `transform` is the
    obs-websocket sceneItemTransform dict (see pov_scene_item_transform).
    Mirrors set_scene_item_enabled: GetSceneItemId -> SetSceneItemTransform.
    Returns (ok, note); (False, reason) on any failure — OBS closed, wrong
    password, item missing — NEVER an exception."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        sid = session.request("GetSceneItemId",
                              {"sceneName": scene, "sourceName": source}).get("sceneItemId")
        if sid is None:
            return False, f"scene item '{source}' not found in scene '{scene}'"
        session.request("SetSceneItemTransform",
                        {"sceneName": scene, "sceneItemId": sid,
                         "sceneItemTransform": dict(transform)})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def get_scene_collection(host="127.0.0.1", port=None, password=None, timeout=2.0,
                         expected=EXPECTED_SCENE_COLLECTION):
    """Ask OBS which scene collection is active and classify it against
    `expected` (default EXPECTED_SCENE_COLLECTION). Returns (status_dict, note);
    (None, reason) on any failure — OBS closed, wrong password, protocol
    surprise — NEVER an exception (same best-effort contract as
    release_feed_inputs/refresh_browser_inputs)."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return None, note
    try:
        resp = session.request("GetSceneCollectionList", {})
        status = scene_collection_status(resp.get("currentSceneCollectionName"),
                                         resp.get("sceneCollections", []),
                                         expected=expected)
        return status, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return None, str(exc) or exc.__class__.__name__
    finally:
        session.close()


def set_scene_collection(name=EXPECTED_SCENE_COLLECTION, host="127.0.0.1",
                         port=None, password=None, timeout=2.0):
    """Switch OBS to scene collection `name`. Returns (ok, note). Best effort:
    - already on `name`            -> (True, "already on '<name>'"), no switch
    - `name` not in the live list  -> (False, "...not found...") — never creates
    - OBS rejects (output active)  -> (False, <obs error>) — _Session.request
      raises ValueError on a failed requestStatus; caught here, never re-raised
    - OBS unreachable              -> (False, reason)
    Heavyweight in OBS: the switch tears down and rebuilds ALL sources (incl. the
    relay feeds), so it is an explicit producer action, never automatic."""
    session, note = _connect(host, port, password, timeout)
    if session is None:
        return False, note
    try:
        resp = session.request("GetSceneCollectionList", {})
        current = resp.get("currentSceneCollectionName")
        available = resp.get("sceneCollections", [])
        if current == name:
            return True, f"already on '{name}'"
        if name not in available:
            return False, (f"scene collection '{name}' not found in OBS "
                           f"(import it with `racecast setup`)")
        session.request("SetCurrentSceneCollection", {"sceneCollectionName": name})
        return True, ""
    except Exception as exc:                         # noqa: BLE001 — best-effort contract
        return False, str(exc) or exc.__class__.__name__
    finally:
        session.close()
