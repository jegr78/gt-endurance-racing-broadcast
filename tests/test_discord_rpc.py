#!/usr/bin/env python3
"""Stdlib unit checks for src/scripts/discord_rpc.py. Run: python3 tests/test_discord_rpc.py"""
import importlib.util, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
spec = importlib.util.spec_from_file_location(
    "discord_rpc", os.path.join(ROOT, "src", "scripts", "discord_rpc.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_ipc_candidates_windows_named_pipe():
    cands = m.ipc_candidates("nt", {})
    assert cands[0] == r"\\?\pipe\discord-ipc-0"
    assert r"\\?\pipe\discord-ipc-9" in cands
    assert all("\\" in c for c in cands)          # never os.path.join'd on the runner


def t_ipc_candidates_posix_order_and_subdirs():
    cands = m.ipc_candidates("posix", {"XDG_RUNTIME_DIR": "/run/user/1000"})
    assert cands[0] == "/run/user/1000/discord-ipc-0"
    assert "/run/user/1000/app/com.discordapp.Discord/discord-ipc-0" in cands
    assert "/tmp/discord-ipc-0" in cands           # always a fallback base


def t_frame_round_trip():
    raw = m.encode_frame(1, {"cmd": "PING"})
    op, length = m.frame_header(raw[:8])
    assert op == 1 and length == len(raw) - 8
    assert json.loads(raw[8:]) == {"cmd": "PING"}
    assert struct.unpack("<II", raw[:8]) == (1, length)   # little-endian, as Discord expects


def t_message_builders():
    assert m.msg_handshake(123) == (0, {"v": 1, "client_id": "123"})
    op, p = m.msg_authorize(123)
    assert op == 1 and p["cmd"] == "AUTHORIZE" and p["args"]["scopes"] == ["rpc"]
    assert m.msg_authenticate("tok")[1]["args"]["access_token"] == "tok"
    op, p = m.msg_select_voice(456)
    assert p["cmd"] == "SELECT_VOICE_CHANNEL" and p["args"] == {"channel_id": "456", "force": True}
    assert m.msg_leave()[1]["args"]["channel_id"] is None


def t_parse_channel_link():
    assert m.parse_channel_link(
        "https://discord.com/channels/111/222") == ("111", "222")
    assert m.parse_channel_link("discord://-/channels/111/222/") == ("111", "222")
    assert m.parse_channel_link("https://discord.com/channels/111") is None   # no channel
    assert m.parse_channel_link("not a link") is None
    assert m.parse_channel_link("") is None
    assert m.parse_channel_link(None) is None
    assert m.parse_channel_link(
        "https://discord.com/channels/@me/222") is None                       # non-numeric guild


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
