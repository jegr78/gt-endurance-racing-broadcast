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


class _LapAccumulator:
    """Accumulates time + distance samples within one lap."""
    __slots__ = ("t0", "elapsed", "distance", "samples", "clean", "last_t")

    def __init__(self, now):
        self.t0 = now
        self.elapsed = 0.0
        self.distance = 0.0
        self.samples = [(0.0, 0.0)]   # (distance, time) pairs, monotonic in distance
        self.clean = True
        self.last_t = now

    def add(self, pkt, now):
        dt = now - self.last_t
        self.last_t = now
        if dt <= 0:
            return
        if dt > 2.0:                  # a long gap (stall/menu) makes the lap time unreliable
            self.clean = False
            return
        if pkt.paused or pkt.loading or not pkt.on_track:
            self.clean = False
            return
        self.elapsed += dt
        self.distance += max(0.0, pkt.speed_mps) * dt
        if self.distance > self.samples[-1][0]:
            self.samples.append((self.distance, self.elapsed))


class TelemetryEngine:
    """Consumes GT7Packets (timestamp injected) and derives lap/delta/predicted.

    Fuel + input trace are added in Task 4/6. Lap detection uses the packet lap
    counter; menu/replay/paused activity never finalises a lap. The reference is
    the fastest clean completed lap, stored as time-vs-distance samples.
    """

    def __init__(self):
        self._last = None                 # last GT7Packet
        self._lap_num = None
        self._acc = None                  # current _LapAccumulator
        self._ref = None                  # reference (best) lap: {"time": s, "samples": [...]}

    def update(self, pkt, now):
        if self._lap_num is None:         # first packet: open a lap
            self._lap_num = pkt.lap
            self._acc = _LapAccumulator(now)
        elif pkt.lap != self._lap_num:    # lap-change edge
            self._finalise_lap()
            self._lap_num = pkt.lap
            self._acc = _LapAccumulator(now)
        if self._acc is not None:
            self._acc.add(pkt, now)
        self._last = pkt

    def _finalise_lap(self):
        acc = self._acc
        if acc is None or not acc.clean or acc.elapsed <= 0 or len(acc.samples) < 2:
            return
        if self._ref is None or acc.elapsed < self._ref["time"]:
            self._ref = {"time": acc.elapsed, "samples": acc.samples}

    def _ref_time_at(self, distance):
        """Interpolate the reference lap's elapsed time at a given distance."""
        s = self._ref["samples"]
        if distance <= s[0][0]:
            return s[0][1]
        if distance >= s[-1][0]:
            return s[-1][1]
        lo, hi = 0, len(s) - 1
        while lo + 1 < hi:                # binary search on distance
            mid = (lo + hi) // 2
            if s[mid][0] <= distance:
                lo = mid
            else:
                hi = mid
        (d0, t0), (d1, t1) = s[lo], s[hi]
        if d1 == d0:
            return t0
        return t0 + (t1 - t0) * (distance - d0) / (d1 - d0)

    def snapshot(self):
        pkt = self._last
        acc = self._acc
        has_ref = self._ref is not None
        delta = predicted = best = None
        if has_ref:
            best = self._ref["time"]
            if acc is not None and acc.elapsed > 0:
                delta = acc.elapsed - self._ref_time_at(acc.distance)
                predicted = best + delta
        return {
            "speed_mps": pkt.speed_mps if pkt else 0.0,
            "tyre_temp": pkt.tyre_temp if pkt else (0.0, 0.0, 0.0, 0.0),
            "lap": pkt.lap if pkt else 0,
            "current_lap_s": acc.elapsed if acc else 0.0,
            "best_s": best,
            "delta_s": delta,
            "predicted_s": predicted,
            "has_reference": has_ref,
        }
