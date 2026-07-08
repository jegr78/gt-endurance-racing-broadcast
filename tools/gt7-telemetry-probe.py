#!/usr/bin/env python3
"""Standalone GT7 telemetry probe (maintainer; not shipped). Heartbeat + decrypt +
field dump against a live PS4/PS5, the way to validate the real packet path and the
struct offsets. Mirrors tools/broadcast-chat-probe.py.

    python3 tools/gt7-telemetry-probe.py --ps-ip 192.168.1.42
    python3 tools/gt7-telemetry-probe.py               # subnet-broadcast discovery
"""
import argparse
import importlib.util
import os
import socket
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


crypto = _load("gt7_crypto", ("src", "scripts", "gt7_crypto.py"))
tm = _load("gt7_telemetry", ("src", "scripts", "gt7_telemetry.py"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps-ip", default=None)
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 33740)); sock.settimeout(2.0)
    dest = args.ps_ip
    last = 0.0
    print("listening on 33740; Ctrl-C to stop")
    while True:
        now = time.monotonic()
        if now - last >= 10:
            sock.sendto(b"A", (dest or "255.255.255.255", 33739)); last = now
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            print("… no packet (is GT7 in a session? heartbeat sent)"); continue
        if dest is None:
            dest = addr[0]; print("console:", dest)
        plain = crypto.decrypt_packet(data)
        if plain is None:
            print("undecryptable/foreign packet"); continue
        p = tm.parse_packet(plain)
        print(f"lap {p.lap} spd {p.speed_mps*3.6:5.1f} km/h "
              f"tyres {tuple(round(t) for t in p.tyre_temp)} "
              f"thr {p.throttle} brk {p.brake} fuel {p.fuel_level:.1f} "
              f"on_track={p.on_track} paused={p.paused}")


if __name__ == "__main__":
    main()
