#!/usr/bin/env python3
"""GT7 telemetry: pure packet parsing + the derived-metrics engine.

No sockets — the relay owns the UDP thread and feeds decrypted packets here. All
functions are deterministic (timestamps are injected) so the engine is unit-tested
without a console. Offsets: community packet-'A' layout, validated live via
tools/gt7-telemetry-probe.py. See the design spec.
"""
import struct
from collections import namedtuple

# --- Packet 'A' field offsets (little-endian) ---
OFF_MAGIC = 0x00
OFF_SPEED = 0x4C        # metres/second (float)
OFF_FUEL_LEVEL = 0x44   # litres in tank (float)
OFF_FUEL_CAP = 0x48     # tank capacity (float)
OFF_TYRE_FL = 0x60      # tyre surface temp, °C (float x4)
OFF_TYRE_FR = 0x64
OFF_TYRE_RL = 0x68
OFF_TYRE_RR = 0x6C
OFF_LAP = 0x74          # current lap (int16)
OFF_BEST_MS = 0x78      # best lap time, ms (int32; -1 = none)
OFF_LAST_MS = 0x7C      # last lap time, ms (int32; -1 = none)
OFF_FLAGS = 0x8E        # simulator flags (uint16 bitfield)
OFF_THROTTLE = 0x91     # 0-255 (uint8)
OFF_BRAKE = 0x92        # 0-255 (uint8)

# --- Simulator flag bits (subset we use) ---
FLAG_ON_TRACK = 1 << 0
FLAG_PAUSED = 1 << 1
FLAG_LOADING = 1 << 2   # loading / processing (menu / replay transitions)

GT7Packet = namedtuple("GT7Packet", [
    "speed_mps", "fuel_level", "fuel_capacity", "tyre_temp",
    "throttle", "brake", "lap", "best_ms", "last_ms",
    "flags", "on_track", "paused", "loading",
])


def parse_packet(plain):
    """Parse a decrypted packet-'A' buffer into a GT7Packet."""
    flags = struct.unpack_from("<H", plain, OFF_FLAGS)[0]
    return GT7Packet(
        speed_mps=struct.unpack_from("<f", plain, OFF_SPEED)[0],
        fuel_level=struct.unpack_from("<f", plain, OFF_FUEL_LEVEL)[0],
        fuel_capacity=struct.unpack_from("<f", plain, OFF_FUEL_CAP)[0],
        tyre_temp=(
            struct.unpack_from("<f", plain, OFF_TYRE_FL)[0],
            struct.unpack_from("<f", plain, OFF_TYRE_FR)[0],
            struct.unpack_from("<f", plain, OFF_TYRE_RL)[0],
            struct.unpack_from("<f", plain, OFF_TYRE_RR)[0],
        ),
        throttle=plain[OFF_THROTTLE],
        brake=plain[OFF_BRAKE],
        lap=struct.unpack_from("<h", plain, OFF_LAP)[0],
        best_ms=struct.unpack_from("<i", plain, OFF_BEST_MS)[0],
        last_ms=struct.unpack_from("<i", plain, OFF_LAST_MS)[0],
        flags=flags,
        on_track=bool(flags & FLAG_ON_TRACK),
        paused=bool(flags & FLAG_PAUSED),
        loading=bool(flags & FLAG_LOADING),
    )
