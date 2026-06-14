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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
