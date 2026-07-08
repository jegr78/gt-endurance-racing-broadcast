#!/usr/bin/env python3
"""Real-packet CI fixture: a genuine GT7 "A" packet captured live (2026-07-08) via
`tools/gt7-telemetry-probe.py --capture` against an actual PS5 session. Decrypting and
parsing it validates the field OFFSETS against reality, not just internal wiring. Run:
python3 tests/test_gt7_fixture.py

Provenance: game telemetry only (the car's own physics state) — no PII, no secrets; the
Salsa20 key is a public constant. If GT7 ever changes the packet layout, this fails loudly.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


gc = _load("gt7_crypto", ("src", "scripts", "gt7_crypto.py"))
tm = _load("gt7_telemetry", ("src", "scripts", "gt7_telemetry.py"))

# A real encrypted GT7 packet-"A" (296 bytes), captured from a live session.
REAL_PACKET_HEX = (
    "26ac820369a6f362f5b0c1ed7fb5afce411fb9f3666dc88f2a6392586944842398639ed362"
    "0c295a13d7da0b7891f47ad69f85bc8331185f9b4c156c3aaf0df5714b28abb63f9d1c1197"
    "0513fcb5f10d1cd2a91d41773d01e7dfdec4ca68379acdf0bcda48effafe33e18891342778"
    "bcef3cc8a40011de1bc4ff0a49393ee2ba2e1dde03529ede7253d72c9b1fdd00f51c4dd3bd"
    "3c624c4f3176214c044515a58b8a7bda37566e9ae0e2e89f7bf9bef1791c4e9abdb3be4e8b"
    "d823996e67af0ff91bc7e8df23b19d2eb63b849a78f2d07d96399b8582a926e130ff370a64"
    "12f39a48f539d708c478d7043f30999fb901192b251558d2a612203cba8283627f907a2a71"
    "1ef870b387617256ced231440f5b292407b918d3b2a5c5bd53f3fb13c57792552b17988fd1"
)


def t_real_packet_decrypts():
    data = bytes.fromhex(REAL_PACKET_HEX)
    assert len(data) == 296
    assert gc.decrypt_packet(data) is not None   # magic matches on a REAL packet


def t_real_packet_fields_plausible():
    # Exact values for THIS captured packet -> a wrong OFF_* constant fails here.
    p = tm.parse_packet(gc.decrypt_packet(bytes.fromhex(REAL_PACKET_HEX)))
    assert abs(p.speed_mps - 71.25) < 0.1        # 256.5 km/h at full throttle
    assert p.throttle == 255 and p.brake == 0
    assert abs(p.fuel_level - 98.68) < 0.1 and abs(p.fuel_capacity - 100.0) < 0.1
    assert p.lap == 1
    assert p.best_ms == -1 and p.last_ms == -1   # no lap set yet -> -1 sentinel
    assert p.on_track is True and p.paused is False
    assert all(60.0 < t < 75.0 for t in p.tyre_temp)   # captured 65.8-69.6 C


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
