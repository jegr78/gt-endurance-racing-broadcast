#!/usr/bin/env python3
"""Stdlib unit checks for GT7 telemetry parsing + engine. Run: python3 tests/test_gt7_telemetry.py"""
import importlib.util, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


tm = _load("gt7_telemetry", ("src", "scripts", "gt7_telemetry.py"))


def _packet(**kw):
    """Build a decrypted packet-'A' buffer with the given field values."""
    b = bytearray(0x128)
    struct.pack_into("<I", b, tm.OFF_MAGIC, 0x47375330)
    struct.pack_into("<f", b, tm.OFF_FUEL_LEVEL, kw.get("fuel_level", 60.0))
    struct.pack_into("<f", b, tm.OFF_FUEL_CAP, kw.get("fuel_capacity", 60.0))
    struct.pack_into("<f", b, tm.OFF_SPEED, kw.get("speed_mps", 0.0))
    fl, fr, rl, rr = kw.get("tyre_temp", (80.0, 80.0, 80.0, 80.0))
    struct.pack_into("<f", b, tm.OFF_TYRE_FL, fl)
    struct.pack_into("<f", b, tm.OFF_TYRE_FR, fr)
    struct.pack_into("<f", b, tm.OFF_TYRE_RL, rl)
    struct.pack_into("<f", b, tm.OFF_TYRE_RR, rr)
    struct.pack_into("<h", b, tm.OFF_LAP, kw.get("lap", 1))
    struct.pack_into("<i", b, tm.OFF_BEST_MS, kw.get("best_ms", -1))
    struct.pack_into("<i", b, tm.OFF_LAST_MS, kw.get("last_ms", -1))
    struct.pack_into("<H", b, tm.OFF_FLAGS, kw.get("flags", tm.FLAG_ON_TRACK))
    b[tm.OFF_THROTTLE] = kw.get("throttle", 0)
    b[tm.OFF_BRAKE] = kw.get("brake", 0)
    return bytes(b)


def t_parse_fields():
    p = tm.parse_packet(_packet(speed_mps=50.0, throttle=255, brake=0,
                                tyre_temp=(70.0, 85.0, 60.0, 100.0), lap=3,
                                fuel_level=42.5, flags=tm.FLAG_ON_TRACK))
    assert abs(p.speed_mps - 50.0) < 1e-3
    assert p.throttle == 255 and p.brake == 0
    assert p.tyre_temp == (70.0, 85.0, 60.0, 100.0)
    assert p.lap == 3
    assert abs(p.fuel_level - 42.5) < 1e-3
    assert p.on_track is True and p.paused is False


def t_parse_flags():
    p = tm.parse_packet(_packet(flags=tm.FLAG_PAUSED | tm.FLAG_LOADING))
    assert p.on_track is False and p.paused is True and p.loading is True


def _feed_lap(eng, t0, lap, *, duration=10.0, dt=0.1, speed=50.0,
              flags=None, fuel_start=None):
    """Drive one synthetic lap of constant speed; returns the end timestamp.
    Emits packets across [t0, t0+duration) with the given lap number, then one
    packet at the end carrying lap+1 (the lap-change edge)."""
    flags = tm.FLAG_ON_TRACK if flags is None else flags
    t = t0
    n = int(duration / dt)
    for _ in range(n):
        kw = dict(speed_mps=speed, lap=lap, flags=flags)
        if fuel_start is not None:
            kw["fuel_level"] = fuel_start
        eng.update(tm.parse_packet(_packet(**kw)), t)
        t += dt
    # lap-change edge:
    eng.update(tm.parse_packet(_packet(speed_mps=speed, lap=lap + 1, flags=flags)), t)
    return t


def t_engine_no_reference_before_first_lap():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(speed_mps=40.0, lap=1)), 100.0)
    s = eng.snapshot()
    assert s["has_reference"] is False
    assert s["delta_s"] is None and s["predicted_s"] is None
    assert abs(s["speed_mps"] - 40.0) < 1e-3


def t_engine_reference_after_clean_lap():
    eng = tm.TelemetryEngine()
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)   # ~500 m in ~10 s
    s = eng.snapshot()
    assert s["has_reference"] is True
    assert s["best_s"] is not None and 9.0 < s["best_s"] < 11.0


def t_engine_delta_negative_when_faster():
    eng = tm.TelemetryEngine()
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)         # reference ~10 s / 500 m
    # Lap 2, faster (higher speed -> same distance reached earlier -> negative delta):
    t = 120.0
    for _ in range(30):                                          # 3 s in, well ahead on distance
        eng.update(tm.parse_packet(_packet(speed_mps=100.0, lap=2)), t)
        t += 0.1
    s = eng.snapshot()
    assert s["delta_s"] is not None and s["delta_s"] < 0
    assert s["predicted_s"] is not None


def t_engine_replay_makes_no_phantom_lap():
    eng = tm.TelemetryEngine()
    # A "lap change" while paused/loading (menu/replay) must NOT set a reference.
    eng.update(tm.parse_packet(_packet(lap=1, flags=tm.FLAG_PAUSED)), 100.0)
    eng.update(tm.parse_packet(_packet(lap=2, flags=tm.FLAG_PAUSED)), 101.0)
    assert eng.snapshot()["has_reference"] is False


def t_engine_pause_midlap_marks_unclean():
    # A mid-lap pause (nonzero dt, paused flag) must prevent the lap becoming a reference.
    eng = tm.TelemetryEngine()
    t = 100.0
    for _ in range(50):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    t += 0.5
    eng.update(tm.parse_packet(_packet(speed_mps=0.0, lap=1, flags=tm.FLAG_PAUSED)), t)
    t += 0.1
    for _ in range(50):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)
    assert eng.snapshot()["has_reference"] is False


def t_engine_long_gap_midlap_marks_unclean():
    # A >2s stall WITHOUT a pause flag (network hiccup) also invalidates the lap.
    eng = tm.TelemetryEngine()
    t = 100.0
    for _ in range(50):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    t += 5.0
    for _ in range(50):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)
    assert eng.snapshot()["has_reference"] is False


def t_engine_fuel_after_two_laps():
    eng = tm.TelemetryEngine()
    # Lap 1: start 60 L. Lap 2: start 57 L (3 L/lap). Lap 3: start 54 L.
    t = _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0, fuel_start=60.0)
    t = _feed_lap(eng, t, 2, duration=10.0, speed=50.0, fuel_start=57.0)
    _feed_lap(eng, t, 3, duration=10.0, speed=50.0, fuel_start=54.0)
    f = eng.snapshot()["fuel"]
    assert f["per_lap"] is not None and abs(f["per_lap"] - 3.0) < 0.5
    # 54 L left / 3 L per lap ~ 18 laps; each lap ~10 s -> ~180 s.
    assert 15 < f["laps_remaining"] < 21
    assert 150 < f["time_remaining_s"] < 210


def t_engine_fuel_none_before_two_laps():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(fuel_level=60.0, lap=1)), 100.0)
    f = eng.snapshot()["fuel"]
    assert f["per_lap"] is None and f["laps_remaining"] is None


def t_engine_stall_at_lap_start_marks_unclean():
    # A >2s stall right at the start of a lap (before any elapsed accumulates) must
    # still invalidate the lap — it must NOT silently become the reference.
    eng = tm.TelemetryEngine()
    t = 100.0
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t)   # opens the accumulator
    t += 3.0                                                          # stall, elapsed still 0
    for _ in range(80):
        eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=1)), t); t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=2)), t)   # finalise lap 1
    assert eng.snapshot()["has_reference"] is False


def t_engine_fuel_continuous_decay():
    # Realistic: fuel drains continuously within each lap (~2 L/lap), not stepwise.
    eng = tm.TelemetryEngine()
    t = 100.0
    fuel = 50.0
    for lap in (1, 2, 3):
        for _ in range(100):
            eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=lap, fuel_level=fuel)), t)
            fuel -= 2.0 / 100
            t += 0.1
    eng.update(tm.parse_packet(_packet(speed_mps=50.0, lap=4, fuel_level=fuel)), t)
    f = eng.snapshot()["fuel"]
    assert f["per_lap"] is not None and abs(f["per_lap"] - 2.0) < 0.3


def t_engine_trace_decimates_and_windows():
    eng = tm.TelemetryEngine()
    t = 100.0
    # 60 Hz for 20 s: raw 1200 samples, decimated to ~30 Hz, windowed to 15 s.
    for i in range(1200):
        thr = 255 if i % 2 == 0 else 0
        eng.update(tm.parse_packet(_packet(throttle=thr, brake=0, lap=1)), t)
        t += 1.0 / 60
    tr = eng.trace_batch(limit=10_000)
    assert tr, "trace should not be empty"
    # decimated to ~30 Hz over 15 s window -> ~450 samples, well under raw 1200:
    assert len(tr) < 700
    # window bound: oldest sample within ~15 s of the newest:
    assert tr[-1]["t"] - tr[0]["t"] <= tm.TRACE_WINDOW_S + 0.5
    # normalised 0-1:
    assert all(0.0 <= s["throttle"] <= 1.0 for s in tr)


def t_engine_trace_batch_limit():
    eng = tm.TelemetryEngine()
    t = 100.0
    for _ in range(300):
        eng.update(tm.parse_packet(_packet(throttle=128, lap=1)), t)
        t += 1.0 / 30
    assert len(eng.trace_batch(limit=50)) == 50


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
