#!/usr/bin/env python3
"""Stdlib unit checks for the minimal obs-websocket v5 client (src/scripts/obs_ws.py):
feed-port release on `racecast relay|streams|event stop` and browser-source refresh on
`racecast relay|event start`. Run: python3 tests/test_obsws.py"""
import base64
import hashlib
import importlib.util
import json
import os
import socket
import struct
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "src", "scripts")
sys.path.insert(0, SCRIPTS)
spec = importlib.util.spec_from_file_location("obs_ws", os.path.join(SCRIPTS, "obs_ws.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --------------------------------------------------------------------------
# WebSocket plumbing (RFC 6455)
# --------------------------------------------------------------------------
def t_accept_key_rfc6455_vector():
    # Known vector straight from RFC 6455 section 1.3.
    assert m.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def t_handshake_request_format():
    req = m.handshake_request("127.0.0.1", 4455, "AAAAAAAAAAAAAAAAAAAAAA==")
    assert isinstance(req, bytes)
    text = req.decode()
    assert text.startswith("GET / HTTP/1.1\r\n")
    assert "Host: 127.0.0.1:4455\r\n" in text
    assert "Upgrade: websocket\r\n" in text
    assert "Connection: Upgrade\r\n" in text
    assert "Sec-WebSocket-Key: AAAAAAAAAAAAAAAAAAAAAA==\r\n" in text
    assert "Sec-WebSocket-Version: 13\r\n" in text
    assert text.endswith("\r\n\r\n")


def t_parse_handshake_accepts_valid_response():
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    resp = (b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
    m.parse_handshake(resp, key)  # must not raise


def t_parse_handshake_rejects_bad_status_and_bad_accept():
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    _raises(lambda: m.parse_handshake(b"HTTP/1.1 403 Forbidden\r\n\r\n", key))
    _raises(lambda: m.parse_handshake(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Sec-WebSocket-Accept: bogus=\r\n\r\n", key))


def t_encode_frame_masks_text_payload():
    mask = b"\x01\x02\x03\x04"
    frame = m.encode_frame(b"hi", mask)
    assert frame[0] == 0x81                       # FIN + text opcode
    assert frame[1] == 0x80 | 2                   # mask bit + length 2
    assert frame[2:6] == mask
    assert bytes(b ^ mask[i % 4] for i, b in enumerate(frame[6:])) == b"hi"


def t_encode_frame_extended_lengths():
    mask = b"\x00\x00\x00\x00"                    # zero mask: payload stays readable
    f126 = m.encode_frame(b"a" * 200, mask)
    assert f126[1] == 0x80 | 126
    assert struct.unpack(">H", f126[2:4])[0] == 200
    f127 = m.encode_frame(b"a" * 70000, mask)
    assert f127[1] == 0x80 | 127
    assert struct.unpack(">Q", f127[2:10])[0] == 70000


def t_decode_frame_single_and_rest():
    op, payload, rest = m.decode_frame(b"\x81\x05hello" + b"\x81\x02hi")
    assert (op, payload, rest) == (0x1, b"hello", b"\x81\x02hi")
    op, payload, rest = m.decode_frame(rest)
    assert (op, payload, rest) == (0x1, b"hi", b"")


def t_decode_frame_incomplete_returns_none():
    assert m.decode_frame(b"") is None
    assert m.decode_frame(b"\x81") is None
    assert m.decode_frame(b"\x81\x05hel") is None         # short payload
    assert m.decode_frame(b"\x81\x7e\x00") is None        # short 16-bit length


def t_decode_frame_16bit_length():
    payload = b"x" * 300
    frame = b"\x81\x7e" + struct.pack(">H", 300) + payload
    op, got, rest = m.decode_frame(frame)
    assert (op, got, rest) == (0x1, payload, b"")


# --------------------------------------------------------------------------
# obs-websocket v5 protocol helpers
# --------------------------------------------------------------------------
AUTH_SALT = "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI="
AUTH_CHALLENGE = "ztTBnnuqrqaKDzRM3xcVdbYm"
# Independently computed from the documented formula:
# base64(sha256(base64(sha256(password + salt)) + challenge))
AUTH_EXPECTED = "1CHyRqIyanJT0eSP/mfMQR1AWZ9KgFl5l6/rPs76VDE="


def t_auth_token_matches_spec_vector():
    assert m.auth_token("supersecret", AUTH_SALT, AUTH_CHALLENGE) == AUTH_EXPECTED


def t_identify_payload_with_auth():
    hello = {"op": 0, "d": {"rpcVersion": 1, "authentication":
                            {"salt": AUTH_SALT, "challenge": AUTH_CHALLENGE}}}
    ident = m.identify_payload(hello, "supersecret")
    assert ident["op"] == 1
    assert ident["d"]["rpcVersion"] == 1
    assert ident["d"]["eventSubscriptions"] == 0   # we never want events
    assert ident["d"]["authentication"] == AUTH_EXPECTED


def t_identify_payload_without_auth():
    ident = m.identify_payload({"op": 0, "d": {"rpcVersion": 1}}, None)
    assert "authentication" not in ident["d"]


def t_identify_payload_auth_required_but_no_password():
    hello = {"op": 0, "d": {"rpcVersion": 1, "authentication":
                            {"salt": AUTH_SALT, "challenge": AUTH_CHALLENGE}}}
    _raises(lambda: m.identify_payload(hello, None))
    _raises(lambda: m.identify_payload(hello, ""))


# --------------------------------------------------------------------------
# Which OBS inputs hold relay-feed connections?
# --------------------------------------------------------------------------
def t_feed_input_names_picks_relay_fed_inputs():
    inputs = [{"inputName": "Feed A", "inputKind": "ffmpeg_source"},
              {"inputName": "Feed B", "inputKind": "ffmpeg_source"},
              {"inputName": "Intro Video", "inputKind": "ffmpeg_source"},
              {"inputName": "HUD", "inputKind": "browser_source"}]
    settings = {"Feed A": {"input": "http://127.0.0.1:53001", "is_local_file": False},
                "Feed B": {"input": "http://127.0.0.1:53002", "is_local_file": False},
                "Intro Video": {"local_file": "/x/intro.mp4", "is_local_file": True}}
    names = m.feed_input_names(inputs, lambda n: settings.get(n, {}),
                               ports=(53001, 53002, 53003))
    assert names == ["Feed A", "Feed B"]           # not the local file, not the browser


def t_feed_input_names_ignores_other_hosts_and_ports():
    inputs = [{"inputName": "X", "inputKind": "ffmpeg_source"},
              {"inputName": "Y", "inputKind": "ffmpeg_source"}]
    settings = {"X": {"input": "http://192.168.1.5:53001"},
                "Y": {"input": "http://127.0.0.1:9999"}}
    assert m.feed_input_names(inputs, lambda n: settings[n], ports=(53001,)) == []


def t_feed_input_names_tolerates_settings_failure():
    inputs = [{"inputName": "A", "inputKind": "ffmpeg_source"}]
    def boom(name):
        raise RuntimeError("no settings")
    assert m.feed_input_names(inputs, boom, ports=(53001,)) == []


# --------------------------------------------------------------------------
# Which OBS browser sources show relay-served pages?
# --------------------------------------------------------------------------
def t_browser_input_names_picks_relay_pages():
    inputs = [{"inputName": "HUD Lower Third", "inputKind": "browser_source"},
              {"inputName": "HUD Race Timer", "inputKind": "browser_source"},
              {"inputName": "Docs Panel", "inputKind": "browser_source"},
              {"inputName": "Feed A", "inputKind": "ffmpeg_source"}]
    settings = {"HUD Lower Third": {"url": "http://127.0.0.1:8088/hud"},
                "HUD Race Timer": {"url": "http://127.0.0.1:8088/timer"},
                "Docs Panel": {"url": "https://example.com/docs"},
                "Feed A": {"input": "http://127.0.0.1:53001"}}
    names = m.browser_input_names(inputs, lambda n: settings.get(n, {}),
                                  needle="127.0.0.1:8088")
    assert names == ["HUD Lower Third", "HUD Race Timer"]


def t_browser_input_names_tolerates_settings_failure():
    inputs = [{"inputName": "A", "inputKind": "browser_source"}]
    def boom(name):
        raise RuntimeError("no settings")
    assert m.browser_input_names(inputs, boom) == []


def t_browser_input_names_ignores_local_file_pages():
    # A browser source rendering a local HTML file has no "url" setting.
    inputs = [{"inputName": "Local HTML", "inputKind": "browser_source"}]
    assert m.browser_input_names(
        inputs, lambda n: {"local_file": "/x/p.html"}) == []


# --------------------------------------------------------------------------
# Password discovery (env override, else OBS's own websocket config)
# --------------------------------------------------------------------------
def t_obs_config_path_per_platform():
    env = {"APPDATA": r"C:\Users\x\AppData\Roaming"}
    assert m.obs_config_path("darwin", env, "/Users/x") == \
        "/Users/x/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
    assert m.obs_config_path("win32", env, r"C:\Users\x") == \
        r"C:\Users\x\AppData\Roaming" + "\\obs-studio\\plugin_config\\obs-websocket\\config.json"
    assert m.obs_config_path("linux", env, "/home/x") == \
        "/home/x/.config/obs-studio/plugin_config/obs-websocket/config.json"


def t_read_ws_config_roundtrip_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w") as fh:
            json.dump({"auth_required": True, "server_password": "pw",
                       "server_port": 4456, "server_enabled": True}, fh)
        cfg = m.read_ws_config(path)
        assert cfg == {"password": "pw", "port": 4456, "auth_required": True,
                       "enabled": True}
        assert m.read_ws_config(os.path.join(tmp, "nope.json")) is None
        broken = os.path.join(tmp, "broken.json")
        with open(broken, "w") as fh:
            fh.write("{not json")
        assert m.read_ws_config(broken) is None


def t_find_password_env_overrides_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w") as fh:
            json.dump({"auth_required": True, "server_password": "from-config"}, fh)
        assert m.find_password({"RACECAST_OBS_WS_PASSWORD": "from-env"}, path) == "from-env"
        assert m.find_password({}, path) == "from-config"
        assert m.find_password({}, os.path.join(tmp, "nope.json")) is None


# --------------------------------------------------------------------------
# release_feed_inputs — the best-effort entry point used by `racecast ... stop`
# --------------------------------------------------------------------------
def t_release_feed_inputs_unreachable_is_quiet():
    # Nothing listens on this port: must return a note, never raise.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    names, note = m.release_feed_inputs(port=free_port, password="x", timeout=0.5)
    assert names == []
    assert note                                    # human-readable reason


# --------------------------------------------------------------------------
# Screenshot request shape + data-URI decode (pure)
# --------------------------------------------------------------------------
def t_screenshot_request_data_shape():
    d = m.screenshot_request_data("Feed A", width=480, fmt="jpg", quality=55)
    assert d == {"sourceName": "Feed A", "imageFormat": "jpg",
                 "imageWidth": 480, "imageCompressionQuality": 55}


def t_parse_screenshot_data_uri_valid():
    raw = b"\xff\xd8\xff\xd9"
    uri = "data:image/jpg;base64," + base64.b64encode(raw).decode()
    assert m.parse_screenshot_data_uri(uri) == raw


def t_parse_screenshot_data_uri_rejects_garbage():
    assert m.parse_screenshot_data_uri("not a data uri") is None
    assert m.parse_screenshot_data_uri("data:image/jpg;base64,@@@@") is None
    assert m.parse_screenshot_data_uri(None) is None
    assert m.parse_screenshot_data_uri(12345) is None


# ---- fake obs-websocket v5 server (loopback, one connection) --------------
def _srv_recv_frame(conn):
    """Read one masked client frame; return (opcode, payload)."""
    head = _srv_read(conn, 2)
    opcode = head[0] & 0x0F
    length = head[1] & 0x7F
    assert head[1] & 0x80, "client frames must be masked"
    if length == 126:
        length = struct.unpack(">H", _srv_read(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _srv_read(conn, 8))[0]
    mask = _srv_read(conn, 4)
    data = _srv_read(conn, length)
    return opcode, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _srv_read(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        assert chunk, "client closed early"
        buf += chunk
    return buf


def _srv_send_json(conn, obj):
    payload = json.dumps(obj).encode()
    head = b"\x81" + (bytes([len(payload)]) if len(payload) < 126
                      else b"\x7e" + struct.pack(">H", len(payload)))
    conn.sendall(head + payload)


def _fake_obs_server(server_sock, password, state):
    conn, _ = server_sock.accept()
    conn.settimeout(5)
    # HTTP upgrade
    req = b""
    while b"\r\n\r\n" not in req:
        req += conn.recv(4096)
    key = [l.split(":", 1)[1].strip() for l in req.decode().split("\r\n")
           if l.lower().startswith("sec-websocket-key:")][0]
    accept = base64.b64encode(hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                  "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept +
                  "\r\n\r\n").encode())
    # Hello -> expect Identify with the documented auth answer
    _srv_send_json(conn, {"op": 0, "d": {"rpcVersion": 1, "authentication":
                                         {"salt": AUTH_SALT, "challenge": AUTH_CHALLENGE}}})
    op, payload = _srv_recv_frame(conn)
    ident = json.loads(payload)
    secret = base64.b64encode(hashlib.sha256(
        (password + AUTH_SALT).encode()).digest()).decode()
    expected = base64.b64encode(hashlib.sha256(
        (secret + AUTH_CHALLENGE).encode()).digest()).decode()
    if ident["d"].get("authentication") != expected:
        conn.close()
        return
    _srv_send_json(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
    # Serve requests until the client goes away
    inputs = [{"inputName": "Feed A", "inputKind": "ffmpeg_source"},
              {"inputName": "Feed B", "inputKind": "ffmpeg_source"},
              {"inputName": "Intro Video", "inputKind": "ffmpeg_source"},
              {"inputName": "HUD Lower Third", "inputKind": "browser_source"},
              {"inputName": "HUD Race Timer", "inputKind": "browser_source"},
              {"inputName": "Docs Panel", "inputKind": "browser_source"}]
    settings = {"Feed A": {"input": "http://127.0.0.1:53001"},
                "Feed B": {"input": "http://127.0.0.1:53002"},
                "Intro Video": {"local_file": "/x/i.mp4", "is_local_file": True},
                "HUD Lower Third": {"url": "http://127.0.0.1:8088/hud"},
                "HUD Race Timer": {"url": "http://127.0.0.1:8088/timer"},
                "Docs Panel": {"url": "https://example.com/docs"}}
    while True:
        try:
            op, payload = _srv_recv_frame(conn)
        except (AssertionError, OSError):
            return
        if op == 0x8:                              # close
            conn.close()
            return
        req = json.loads(payload)
        rtype, rid = req["d"]["requestType"], req["d"]["requestId"]
        rdata = req["d"].get("requestData", {})
        if rtype == "GetSceneCollectionList":
            resp = {"currentSceneCollectionName": state.get("current_collection", ""),
                    "sceneCollections": state.get("collections", [])}
        elif rtype == "SetCurrentSceneCollection":
            if state.get("output_active"):     # OBS refuses while streaming/recording
                _srv_send_json(conn, {"op": 7, "d": {
                    "requestType": rtype, "requestId": rid,
                    "requestStatus": {"result": False, "code": 501,
                                      "comment": "output active"},
                    "responseData": {}}})
                continue
            state["set_collection"] = rdata["sceneCollectionName"]
            state["current_collection"] = rdata["sceneCollectionName"]
            resp = {}
        elif rtype == "GetInputList":
            kind = rdata.get("inputKind")
            resp = {"inputs": [i for i in inputs
                               if not kind or i["inputKind"] == kind]}
        elif rtype == "GetCurrentProgramScene":
            resp = {"currentProgramSceneName": state.get("program_scene", "Stint"),
                    "sceneName": state.get("program_scene", "Stint")}
        elif rtype == "GetSourceScreenshot":
            state.setdefault("shot_requests", []).append(rdata)
            raw = state.get("shot_bytes", b"\xff\xd8\xff\xd9")
            resp = {"imageData": "data:image/jpg;base64," + base64.b64encode(raw).decode()}
        elif rtype == "PressInputPropertiesButton":
            # The refresh presses OBS's own 'Refresh cache of current page'
            # button — never anything else. Answer a wrong button with a
            # failed requestStatus (an assert would die silently in this
            # daemon thread and hang the client into its timeout).
            if rdata["propertyName"] != "refreshnocache":
                _srv_send_json(conn, {"op": 7, "d": {
                    "requestType": rtype, "requestId": rid,
                    "requestStatus": {"result": False, "code": 400},
                    "responseData": {}}})
                continue
            state.setdefault("refreshed", []).append(rdata["inputName"])
            resp = {}
        elif rtype == "GetInputSettings":
            resp = {"inputSettings": settings[rdata["inputName"]]}
        elif rtype == "SetInputSettings":
            # The release re-applies the input's OWN settings (a forced source
            # rebuild) — it must never change them.
            assert rdata["inputSettings"] == settings[rdata["inputName"]]
            assert rdata["overlay"] is True
            state["released"].append(rdata["inputName"])
            resp = {}
        elif rtype == "GetSceneItemId":
            state.setdefault("get_item_id", []).append(
                (rdata["sceneName"], rdata["sourceName"]))
            resp = {"sceneItemId": 7}
        elif rtype == "SetSceneItemEnabled":
            state.setdefault("set_enabled", []).append(
                (rdata["sceneName"], rdata["sceneItemId"], rdata["sceneItemEnabled"]))
            resp = {}
        elif rtype == "GetStreamStatus":
            resp = {"outputActive": state.get("stream_active", False),
                    "outputReconnecting": state.get("stream_reconnecting", False),
                    "outputTimecode": state.get("stream_timecode", "00:00:00.000"),
                    "outputBytes": state.get("output_bytes", 0)}
        elif rtype == "StartStream":
            state.setdefault("stream_calls", []).append("start")
            state["stream_active"] = True
            resp = {}
        elif rtype == "StopStream":
            state.setdefault("stream_calls", []).append("stop")
            state["stream_active"] = False
            resp = {}
        else:
            resp = {}
        _srv_send_json(conn, {"op": 7, "d": {
            "requestType": rtype, "requestId": rid,
            "requestStatus": {"result": True, "code": 100},
            "responseData": resp}})


def t_release_feed_inputs_end_to_end_against_fake_server():
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    state = {"released": []}
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, "supersecret", state), daemon=True)
    thread.start()
    names, note = m.release_feed_inputs(port=port, password="supersecret", timeout=5)
    assert note == "", note
    assert names == ["Feed A", "Feed B"]
    assert state["released"] == ["Feed A", "Feed B"]
    server_sock.close()


def t_release_feed_inputs_wrong_password_is_note_not_crash():
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, "supersecret", {"released": []}),
                              daemon=True)
    thread.start()
    names, note = m.release_feed_inputs(port=port, password="WRONG", timeout=2)
    assert names == []
    assert note
    server_sock.close()


# --------------------------------------------------------------------------
# set_stream — Director Panel broadcast start/stop (#295)
# (uses the shared _start_fake_obs helper defined further down)
# --------------------------------------------------------------------------
def t_set_stream_starts_when_offline():
    state = {"stream_active": False}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_stream(True, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert state["stream_calls"] == ["start"]
    assert state["stream_active"] is True
    srv.close()


def t_set_stream_stops_when_live():
    state = {"stream_active": True}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_stream(False, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert state["stream_calls"] == ["stop"]
    assert state["stream_active"] is False
    srv.close()


def t_set_stream_is_idempotent_noop_when_already_live():
    state = {"stream_active": True}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_stream(True, port=port, password="supersecret", timeout=5)
    assert ok and note == "", note
    assert "stream_calls" not in state          # no StartStream sent
    srv.close()


def t_set_stream_unreachable_is_note_not_crash():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    ok, note = m.set_stream(True, port=free_port, password="x", timeout=0.5)
    assert ok is False
    assert note                                 # human-readable reason


def t_parse_stream_status_includes_timecode():
    out = m.parse_stream_status({"outputActive": True,
                                 "outputReconnecting": False,
                                 "outputTimecode": "00:12:34.567"})
    assert out["stream_timecode"] == "00:12:34.567"
    assert out["stream_active"] is True


def t_read_obs_state_includes_stream():
    state = {"released": [], "stream_active": True,
             "stream_timecode": "01:02:03.000"}
    port, srv = _start_fake_obs(state)
    out, note = m.read_obs_state([("Stint", "Feed A")], ["Feed A"],
                                 port=port, password="supersecret", timeout=5)
    assert note == "", note
    assert out["stream"] == {"active": True, "reconnecting": False,
                             "timecode": "01:02:03.000"}
    srv.close()


# --------------------------------------------------------------------------
# refresh_browser_inputs — the auto-refresh used by `racecast relay|event start`
# --------------------------------------------------------------------------
def t_refresh_browser_inputs_end_to_end_against_fake_server():
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    state = {"released": [], "refreshed": []}
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, "supersecret", state), daemon=True)
    thread.start()
    names, note = m.refresh_browser_inputs(port=port, password="supersecret",
                                           timeout=5)
    assert note == "", note
    assert names == ["HUD Lower Third", "HUD Race Timer"]
    assert state["refreshed"] == ["HUD Lower Third", "HUD Race Timer"]
    assert state["released"] == []                 # refresh must not touch feeds
    server_sock.close()


def t_refresh_browser_inputs_unreachable_is_quiet():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    names, note = m.refresh_browser_inputs(port=free_port, password="x",
                                           timeout=0.5)
    assert names == []
    assert note                                    # human-readable reason


# --------------------------------------------------------------------------
# probe — the side-effect-free reachability check behind /status's obs.reachable
# --------------------------------------------------------------------------
def t_probe_unreachable_is_quiet():
    # Nothing listens here: (False, note), never an exception.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    reachable, note = m.probe(port=free_port, password="x", timeout=0.5)
    assert reachable is False
    assert note                                    # human-readable reason


def t_probe_end_to_end_against_fake_server():
    # A full handshake + auth -> reachable, no note, and the probe touches
    # nothing in OBS (no released feeds, no refreshed sources).
    state = {"released": [], "refreshed": []}
    port, srv = _start_fake_obs(state)
    reachable, note = m.probe(port=port, password="supersecret", timeout=5)
    assert reachable is True
    assert note == "", note
    assert state["released"] == [] and state["refreshed"] == []
    srv.close()


def t_probe_wrong_password_is_not_reachable():
    state = {"released": []}
    port, srv = _start_fake_obs(state)
    reachable, note = m.probe(port=port, password="WRONG", timeout=2)
    assert reachable is False
    assert note
    srv.close()


# --------------------------------------------------------------------------
# set_scene_item_enabled — relay-driven POV PiP show/hide (#130)
# --------------------------------------------------------------------------
def t_set_scene_item_enabled_end_to_end_against_fake_server():
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    state = {"released": [], "set_enabled": []}
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, "supersecret", state), daemon=True)
    thread.start()
    ok, note = m.set_scene_item_enabled("Stint", "Feed POV", True,
                                        port=port, password="supersecret", timeout=5)
    assert ok is True, note
    assert note == ""
    assert state["set_enabled"] == [("Stint", 7, True)]
    server_sock.close()


def t_set_scene_item_enabled_unreachable_is_quiet():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    ok, note = m.set_scene_item_enabled("Stint", "Feed POV", False,
                                        port=free_port, password="x", timeout=0.5)
    assert ok is False
    assert note


# --------------------------------------------------------------------------
# get_scene_collection / set_scene_collection — best-effort, like the others
# --------------------------------------------------------------------------
def _start_fake_obs(state, password="supersecret"):
    """Spin up the loopback fake OBS server; return its port (daemon thread)."""
    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    thread = threading.Thread(target=_fake_obs_server,
                              args=(server_sock, password, state), daemon=True)
    thread.start()
    return port, server_sock


def t_get_scene_collection_reads_current_and_list():
    state = {"released": [], "current_collection": "GT Endurance Racing",
             "collections": ["GT Endurance Racing", "Other"]}
    port, srv = _start_fake_obs(state)
    status, note = m.get_scene_collection(port=port, password="supersecret", timeout=5)
    assert note == "", note
    assert status["current"] == "GT Endurance Racing"
    assert status["match"] is True
    assert status["available"] == ["GT Endurance Racing", "Other"]
    srv.close()


def t_get_scene_collection_honors_custom_expected():
    state = {"released": [], "current_collection": "ERF Endurance",
             "collections": ["ERF Endurance", "GT Endurance Racing"]}
    port, srv = _start_fake_obs(state)
    status, note = m.get_scene_collection(port=port, password="supersecret",
                                          timeout=5, expected="ERF Endurance")
    assert note == "", note
    assert status["expected"] == "ERF Endurance"
    assert status["match"] is True          # would be False against the default
    srv.close()


def t_get_scene_collection_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    status, note = m.get_scene_collection(port=free_port, password="x", timeout=0.5)
    assert status is None
    assert note


def t_set_scene_collection_switches_when_present_and_different():
    state = {"released": [], "current_collection": "Other",
             "collections": ["GT Endurance Racing", "Other"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is True, note
    assert state["set_collection"] == "GT Endurance Racing"
    srv.close()


def t_set_scene_collection_noop_when_already_correct():
    state = {"released": [], "current_collection": "GT Endurance Racing",
             "collections": ["GT Endurance Racing"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is True
    assert "already" in note
    assert "set_collection" not in state          # no switch request issued
    srv.close()


def t_set_scene_collection_refuses_when_absent():
    state = {"released": [], "current_collection": "Other",
             "collections": ["Other", "Spare"]}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is False
    assert "not found" in note
    assert "set_collection" not in state
    srv.close()


def t_set_scene_collection_output_active_is_note_not_crash():
    state = {"released": [], "current_collection": "Other",
             "collections": ["GT Endurance Racing", "Other"], "output_active": True}
    port, srv = _start_fake_obs(state)
    ok, note = m.set_scene_collection(port=port, password="supersecret", timeout=5)
    assert ok is False
    assert note                                    # carries OBS's rejection
    srv.close()


def t_set_scene_collection_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]; sock.close()
    ok, note = m.set_scene_collection(port=free_port, password="x", timeout=0.5)
    assert ok is False
    assert note


# --------------------------------------------------------------------------
# get_source_screenshot / get_program_screenshot — best-effort fetchers
# --------------------------------------------------------------------------
def t_get_source_screenshot_returns_bytes():
    state = {"shot_bytes": b"\xff\xd8hello\xff\xd9"}
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=_fake_obs_server, args=(srv, "pw", state), daemon=True).start()
    data, note = m.get_source_screenshot("Feed A", width=320, host="127.0.0.1",
                                         port=port, password="pw", timeout=5)
    srv.close()
    assert note == "" and data == b"\xff\xd8hello\xff\xd9"
    assert state["shot_requests"][0]["sourceName"] == "Feed A"
    assert state["shot_requests"][0]["imageWidth"] == 320


def t_get_program_screenshot_uses_current_scene():
    state = {"program_scene": "Stint", "shot_bytes": b"\xff\xd8PGM\xff\xd9"}
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=_fake_obs_server, args=(srv, "pw", state), daemon=True).start()
    data, note = m.get_program_screenshot(width=640, host="127.0.0.1",
                                          port=port, password="pw", timeout=5)
    srv.close()
    assert note == "" and data == b"\xff\xd8PGM\xff\xd9"
    assert state["shot_requests"][0]["sourceName"] == "Stint"


def t_get_source_screenshot_unreachable_is_quiet():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]; sock.close()
    data, note = m.get_source_screenshot("Feed A", port=free, password="x", timeout=0.5)
    assert data is None and note


# --------------------------------------------------------------------------
# Pure scene-collection classifier — scene_collection_status
# --------------------------------------------------------------------------
def t_scene_collection_status_match():
    s = m.scene_collection_status("GT Endurance Racing", ["GT Endurance Racing", "Other"])
    assert s == {"current": "GT Endurance Racing", "expected": "GT Endurance Racing",
                 "available": ["GT Endurance Racing", "Other"], "match": True,
                 "expected_present": True, "renamed_variant": None}


def t_scene_collection_status_wrong_but_present():
    s = m.scene_collection_status("Other", ["GT Endurance Racing", "Other"])
    assert s["match"] is False
    assert s["expected_present"] is True
    assert s["renamed_variant"] is None
    assert s["current"] == "Other"


def t_scene_collection_status_renamed_variant():
    s = m.scene_collection_status("GT Endurance Racing 2", ["GT Endurance Racing 2", "Scene"])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] == "GT Endurance Racing 2"
    assert s["current"] == "GT Endurance Racing 2"


def t_scene_collection_status_match_suppresses_renamed_variant():
    # A correct collection plus an old import-renamed duplicate must NOT report
    # a renamed_variant — match wins, no false "looks renamed" warning.
    s = m.scene_collection_status("GT Endurance Racing",
                                  ["GT Endurance Racing", "GT Endurance Racing 2"])
    assert s["match"] is True
    assert s["renamed_variant"] is None


def t_scene_collection_status_overlap_present_and_renamed():
    # A renamed duplicate is active while the real collection ALSO exists:
    # both flags are truthy — consumers must prefer the switchable case.
    s = m.scene_collection_status("GT Endurance Racing 2",
                                  ["GT Endurance Racing", "GT Endurance Racing 2"])
    assert s["match"] is False
    assert s["expected_present"] is True
    assert s["renamed_variant"] == "GT Endurance Racing 2"


def t_scene_collection_status_expected_absent():
    s = m.scene_collection_status("Scene", ["Scene", "Foo"])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] is None


def t_scene_collection_status_empty_current():
    s = m.scene_collection_status(None, [])
    assert s["match"] is False
    assert s["expected_present"] is False
    assert s["renamed_variant"] is None
    assert s["current"] is None


class _FakeSock:
    """Records sendall/recv/shutdown/settimeout/close for _Session.close() tests.
    recv_chunks is a list of bytes (b"" means EOF) or exceptions to raise in order."""
    def __init__(self, recv_chunks=None, raise_on_send=None):
        self.sent = b""
        self.calls = []                 # ordered method names
        self.timeout = None
        self._recv = list(recv_chunks or [b""])
        self._raise_on_send = raise_on_send
    def sendall(self, data):
        self.calls.append("sendall")
        if self._raise_on_send:
            raise self._raise_on_send
        self.sent += data
    def recv(self, n):
        self.calls.append("recv")
        if not self._recv:
            return b""
        item = self._recv.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    def shutdown(self, how):
        self.calls.append("shutdown")
    def settimeout(self, t):
        self.calls.append("settimeout")
        self.timeout = t
    def close(self):
        self.calls.append("close")


def _unmask_client_frame(buf):
    """Decode one masked client->server frame; return (opcode, unmasked_payload)."""
    opcode = buf[0] & 0x0F
    length = buf[1] & 0x7F
    mask = buf[2:6]
    masked = buf[6:6 + length]
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(masked))
    return opcode, payload


def t_close_sends_status_1000_then_drains_then_close():
    sock = _FakeSock(recv_chunks=[b""])          # immediate EOF
    sess = m._Session(sock, b"")
    sess.close()
    opcode, payload = _unmask_client_frame(sock.sent)
    assert opcode == 0x8, opcode                  # close frame
    assert payload == struct.pack(">H", 1000), payload   # status 1000
    assert "close" in sock.calls
    # Regression guard: close() must NOT shutdown(SHUT_WR). An early TCP FIN makes
    # OBS log the disconnect as 1006/"End of File" instead of 1000 (verified live).
    assert "shutdown" not in sock.calls, sock.calls
    assert sock.timeout == m.CLOSE_DRAIN_TIMEOUT_S
    # settimeout must precede the draining recv (no-hang guarantee)
    if "recv" in sock.calls:
        assert sock.calls.index("settimeout") < sock.calls.index("recv")


def t_close_returns_on_echo_then_eof():
    # OBS echoes a close frame (server->client, unmasked), then EOF.
    echo = m.encode_frame(struct.pack(">H", 1000), mask=b"\x00\x00\x00\x00", opcode=0x8)
    sock = _FakeSock(recv_chunks=[echo, b""])
    sess = m._Session(sock, b"")
    sess.close()                                  # must not raise
    assert sock.calls.count("close") == 1


def t_close_does_not_hang_on_silent_socket():
    # recv raising timeout simulates the drain deadline; close() must still finish.
    sock = _FakeSock(recv_chunks=[socket.timeout()])
    sess = m._Session(sock, b"")
    sess.close()                                  # must not raise, must not loop
    assert "close" in sock.calls


def t_close_safe_when_obs_already_dropped_socket():
    # sendall raising OSError (OBS gone) must be swallowed; socket still closed.
    sock = _FakeSock(raise_on_send=OSError("broken pipe"))
    sess = m._Session(sock, b"")
    sess.close()                                  # must not raise
    assert "close" in sock.calls


def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


# --------------------------------------------------------------------------
# Pure intent planner — feed_state_intents
# --------------------------------------------------------------------------
def t_feed_state_intents_live_a_with_cut():
    assert m.feed_state_intents("A", True) == [
        ("show", "Feed A"), ("hide", "Feed B"),
        ("unmute", "Feed A"), ("mute", "Feed B"),
        ("cut", "Stint"),
    ]


def t_feed_state_intents_live_b_no_cut():
    assert m.feed_state_intents("B", False) == [
        ("show", "Feed B"), ("hide", "Feed A"),
        ("unmute", "Feed B"), ("mute", "Feed A"),
    ]


# --------------------------------------------------------------------------
# set_current_program_scene / set_input_volume / set_input_mute /
# read_obs_state — relay-mediated OBS control helpers
# --------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, responses=None):
        self.sent = []
        self._responses = responses or {}

    def request(self, request_type, request_data=None):
        self.sent.append((request_type, request_data or {}))
        return self._responses.get(request_type, {})

    def close(self):
        self.sent.append(("close", {}))


def t_set_current_program_scene_sends_request():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_current_program_scene("Stint")
    finally:
        m._connect = orig
    assert ok is True and note == ""
    assert ("SetCurrentProgramScene", {"sceneName": "Stint"}) in sess.sent


def t_set_input_volume_and_mute():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        assert m.set_input_volume("Mic", -6.0)[0] is True
        assert m.set_input_mute("Mic", True)[0] is True
    finally:
        m._connect = orig
    assert ("SetInputVolume", {"inputName": "Mic", "inputVolumeDb": -6.0}) in sess.sent
    assert ("SetInputMute", {"inputName": "Mic", "inputMuted": True}) in sess.sent


def t_read_obs_state_batches_one_session():
    sess = _FakeSession({
        "GetCurrentProgramScene": {"currentProgramSceneName": "Stint"},
        "GetSceneItemId": {"sceneItemId": 7},
        "GetSceneItemEnabled": {"sceneItemEnabled": True},
        "GetInputMute": {"inputMuted": False},
        "GetInputVolume": {"inputVolumeDb": -3.0},
    })
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        state, note = m.read_obs_state([("Stint", "HUD")], ["Mic"])
    finally:
        m._connect = orig
    assert note == "" and state["scene"] == "Stint"
    assert state["sources"] == [{"scene": "Stint", "source": "HUD", "enabled": True}]
    assert state["audio"] == [{"input": "Mic", "muted": False, "volumeDb": -3.0}]


def t_obs_helpers_unreachable_return_failure_not_raise():
    orig, m._connect = m._connect, lambda *a, **k: (None, "OBS not running")
    try:
        assert m.set_current_program_scene("Stint") == (False, "OBS not running")
        assert m.read_obs_state([], []) == (None, "OBS not running")
    finally:
        m._connect = orig


def t_resolve_obs_target_env_overrides_then_config():
    # RACECAST_OBS_WS_HOST/PORT override the discovered target (proxy/remote seam).
    env = {"RACECAST_OBS_WS_HOST": "100.64.0.5", "RACECAST_OBS_WS_PORT": "4466"}
    assert m.resolve_obs_target("127.0.0.1", None, env, {"port": 4455}) == ("100.64.0.5", 4466)
    # no overrides -> caller host + OBS's own config port
    assert m.resolve_obs_target("127.0.0.1", None, {}, {"port": 4455}) == ("127.0.0.1", 4455)
    # no overrides, no config -> the 4455 default
    assert m.resolve_obs_target("127.0.0.1", None, {}, None) == ("127.0.0.1", m.DEFAULT_PORT)
    # a non-numeric port override is ignored (falls back to config/default)
    assert m.resolve_obs_target(
        "127.0.0.1", None, {"RACECAST_OBS_WS_PORT": "x"}, {"port": 4455}) == ("127.0.0.1", 4455)
    # host override alone still resolves the port via config/default
    assert m.resolve_obs_target("127.0.0.1", None, {"RACECAST_OBS_WS_HOST": "100.64.0.9"},
                                {"port": 4455}) == ("100.64.0.9", 4455)


# --------------------------------------------------------------------------
# parse_obs_stats / parse_stream_status / get_health_stats
# --------------------------------------------------------------------------
def t_parse_obs_stats():
    p = {"cpuUsage": 12.5, "memoryUsage": 910.0, "availableDiskSpace": 51200.0,
         "activeFps": 60.0, "renderSkippedFrames": 3, "renderTotalFrames": 1000}
    out = m.parse_obs_stats(p)
    assert out["obs_cpu_pct"] == 12.5
    assert out["obs_mem_mb"] == 910.0
    assert out["obs_disk_free_mb"] == 51200.0
    assert out["obs_fps"] == 60.0
    assert out["obs_render_skipped_pct"] == 0.3
    # Missing fields -> None, never KeyError; zero total -> None (no div by zero).
    out2 = m.parse_obs_stats({"renderSkippedFrames": 0, "renderTotalFrames": 0})
    assert out2["obs_cpu_pct"] is None and out2["obs_render_skipped_pct"] is None


def t_parse_stream_status():
    p = {"outputActive": True, "outputReconnecting": False, "outputCongestion": 0.2,
         "outputSkippedFrames": 5, "outputTotalFrames": 500, "outputBytes": 1234567}
    out = m.parse_stream_status(p)
    assert out["stream_active"] is True
    assert out["stream_reconnecting"] is False
    assert out["stream_congestion"] == 0.2
    assert out["stream_dropped_pct"] == 1.0
    assert out["output_bytes"] == 1234567
    out2 = m.parse_stream_status({})
    assert out2["stream_active"] is None and out2["stream_dropped_pct"] is None


def t_get_health_stats_unreachable_is_quiet():
    # Nothing listens here: (False, {}, note), never an exception.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    reachable, stats, note = m.get_health_stats(port=free_port, password="x", timeout=0.5)
    assert reachable is False
    assert stats == {}
    assert note                                    # human-readable reason


def t_get_health_stats_merges_stats_and_stream_status():
    # Use a fake session that returns canned GetStats + GetStreamStatus payloads.
    sess = _FakeSession({
        "GetStats": {"cpuUsage": 5.0, "memoryUsage": 800.0,
                     "availableDiskSpace": 20000.0, "activeFps": 60.0,
                     "renderSkippedFrames": 0, "renderTotalFrames": 500},
        "GetStreamStatus": {"outputActive": True, "outputReconnecting": False,
                            "outputCongestion": 0.0, "outputSkippedFrames": 0,
                            "outputTotalFrames": 200, "outputBytes": 999},
    })
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        reachable, stats, note = m.get_health_stats()
    finally:
        m._connect = orig
    assert reachable is True
    assert note == ""
    # parse_obs_stats keys present
    assert stats["obs_cpu_pct"] == 5.0
    assert stats["obs_mem_mb"] == 800.0
    assert stats["obs_render_skipped_pct"] == 0.0   # 0 skipped / 500 total -> 0%
    # parse_stream_status keys present
    assert stats["stream_active"] is True
    assert stats["output_bytes"] == 999
    # session was closed
    assert ("close", {}) in sess.sent


def t_stream_kbps():
    # 125000 bytes over 1 s = 1000 kbps.
    assert m.stream_kbps(0, 100.0, 125000, 101.0, True) == 1000.0
    assert m.stream_kbps(None, None, 125000, 101.0, True) is None   # first sample
    assert m.stream_kbps(0, 100.0, 125000, 101.0, False) is None    # not streaming
    assert m.stream_kbps(200000, 100.0, 1000, 101.0, True) is None  # counter reset
    assert m.stream_kbps(0, 101.0, 125000, 101.0, True) is None     # dt == 0


def t_pov_scene_item_transform_maps_box():
    assert m.pov_scene_item_transform(
        {"left": 1516, "top": 600, "width": 384, "height": 216}) == {
            "positionX": 1516, "positionY": 600,
            "boundsType": 2, "boundsAlignment": 0, "alignment": 5,
            "boundsWidth": 384, "boundsHeight": 216}


def t_set_scene_item_transform_sends_request():
    sess = _FakeSession({"GetSceneItemId": {"sceneItemId": 7}})
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        tf = m.pov_scene_item_transform(
            {"left": 1516, "top": 600, "width": 384, "height": 216})
        ok, note = m.set_scene_item_transform("Stint", "Feed POV", tf)
    finally:
        m._connect = orig
    assert ok is True and note == ""
    assert ("SetSceneItemTransform",
            {"sceneName": "Stint", "sceneItemId": 7,
             "sceneItemTransform": tf}) in sess.sent


def t_set_scene_item_transform_missing_item():
    sess = _FakeSession({"GetSceneItemId": {}})        # no sceneItemId
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        ok, note = m.set_scene_item_transform("Stint", "Feed POV", {})
    finally:
        m._connect = orig
    assert ok is False and "not found" in note


def t_set_scene_item_transform_unreachable():
    orig, m._connect = m._connect, lambda *a, **k: (None, "OBS not running")
    try:
        assert m.set_scene_item_transform("Stint", "Feed POV", {}) == \
            (False, "OBS not running")
    finally:
        m._connect = orig


# --------------------------------------------------------------------------
# set_feed_close_when_inactive — fan-out: tell OBS to drop off-air feeds
# --------------------------------------------------------------------------
def t_set_feed_close_when_inactive_builds_setinputsettings():
    sess = _FakeSession()
    orig, m._connect = m._connect, lambda *a, **k: (sess, "")
    try:
        note = m.set_feed_close_when_inactive(["Feed A", "Feed B"], True)
    finally:
        m._connect = orig
    assert note == "", note
    reqs = [{"requestType": rt, "requestData": rd}
            for rt, rd in sess.sent if rt == "SetInputSettings"]
    assert len(reqs) == 2
    for r in reqs:
        d = r["requestData"]
        assert d["inputSettings"]["close_when_inactive"] is True
        assert d.get("overlay", True) is True       # merge, not replace


def t_set_feed_close_when_inactive_unreachable_is_note_not_crash():
    orig, m._connect = m._connect, lambda *a, **k: (None, "OBS not running")
    try:
        note = m.set_feed_close_when_inactive(["Feed A"], True)
    finally:
        m._connect = orig
    assert note == "OBS not running"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
