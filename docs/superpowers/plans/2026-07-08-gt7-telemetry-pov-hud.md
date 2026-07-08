# GT7 UDP telemetry-driven POV HUD — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a POV/solo-only live telemetry HUD that ingests GT7's undocumented Salsa20-encrypted UDP stream on the driver's machine and renders tyres, throttle/brake trace, delta-to-best, predicted lap, and fuel through the existing OBS Browser Source (`hud.html`).

**Architecture:** Pure, stdlib-only, unit-testable modules (`gt7_crypto.py` decrypt, `gt7_telemetry.py` parse + engine) feed a thread-safe store persisted to `runtime/<profile>/telemetry.json`. A solo-only UDP listener thread in the relay (bind `0.0.0.0:33740`, heartbeat to `PS_IP:33739`) drives the store. Two solo-gated GET endpoints (`/telemetry/data`, `/telemetry/trace`) are polled by a self-gating block in `hud.html` (404 in endurance ⇒ block hidden). No new transport, no pip dependency; endurance path stays byte-identical.

**Tech Stack:** Python 3 stdlib (`socket`, `struct`, `threading`, `json`), vendored pure-Python Salsa20, existing relay `ThreadingHTTPServer` + `HudSource`/`TimerStore` patterns, `hud.html` polling + `<canvas>`.

**Spec:** `docs/superpowers/specs/2026-07-08-gt7-telemetry-pov-hud-design.md`

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `docs/`, `.env.example`). Never touch `dist/`/`runtime/`.
- **Stdlib only — no pip dependency.** Salsa20 is vendored pure-Python.
- **English only** in all code, comments, docs.
- **Endurance path byte-identical**; `python3 tools/run-tests.py` stays green with **no test disabled**. All new behaviour is gated on `--solo` / the presence of a telemetry store.
- **Tests run on any machine / CI** — no real console, no real IPs, no hardware. UDP sockets/heartbeat are thin glue kept out of the pure-tested core; live validation is manual (`tools/gt7-telemetry-probe.py`).
- **No secrets / machine paths** in code or tests.
- **Tyre-temp thresholds (°C, native):** cold `<70`, optimal `70–85`, hot `>85`, critical `>95`. `.env`-overridable. Comparison always in °C; only display converts to °F.
- **Units:** `RACECAST_TELEMETRY_UNITS=metric` (default: km/h, °C, L) | `imperial` (mph, °F, gal).
- **Run `python3 tools/lint.py` after changing any Python file.**
- Field offsets are from community docs (MacManley/gt7-udp, Nenkai/PDTools MIT); pinned as module constants so a live correction is a one-line edit. gt7dashboard is GPL-3.0 — **no code copied**.

---

### Task 1: Salsa20 decryption module (`gt7_crypto.py`)

**Files:**
- Create: `src/scripts/gt7_crypto.py`
- Test: `tests/test_gt7_crypto.py`

**Interfaces:**
- Produces:
  - `KEY: bytes` (32 bytes)
  - `salsa20_xor(key: bytes, nonce8: bytes, data: bytes) -> bytes` (stream XOR; encrypt == decrypt)
  - `decrypt_packet(data: bytes) -> bytes | None` (returns plaintext on magic match, else `None`; never raises)

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Stdlib unit checks for GT7 Salsa20 decryption. Run: python3 tests/test_gt7_crypto.py"""
import importlib.util, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


gt7 = _load("gt7_crypto", ("src", "scripts", "gt7_crypto.py"))


def t_salsa20_test_vector():
    # ECRYPT Salsa20/20 test vector (256-bit key, set 1 vector 0):
    # key = 0x80 followed by 31 zero bytes, IV = 8 zero bytes -> first 8 bytes of keystream.
    key = bytes([0x80] + [0] * 31)
    nonce = bytes(8)
    ks = gt7.salsa20_xor(key, nonce, bytes(64))   # XOR against zeros = raw keystream
    assert ks[:8] == bytes.fromhex("E3BE8FDD8BECA2E3"), ks[:8].hex()


def t_salsa20_is_symmetric():
    key = bytes(range(32)); nonce = bytes(range(8)); msg = b"hello gt7 telemetry" * 5
    ct = gt7.salsa20_xor(key, nonce, msg)
    assert ct != msg
    assert gt7.salsa20_xor(key, nonce, ct) == msg


def _encrypted(iv1, plaintext):
    """Craft a GT7-style encrypted packet: the IV travels in clear at 0x40."""
    nonce = struct.pack("<II", iv1 ^ 0xDEADBEAF, iv1)
    ct = bytearray(gt7.salsa20_xor(gt7.KEY, nonce, plaintext))
    ct[0x40:0x44] = struct.pack("<I", iv1)
    return bytes(ct)


def t_decrypt_packet_ok():
    plain = bytearray(0x128)
    struct.pack_into("<I", plain, 0x00, 0x47375330)   # magic
    struct.pack_into("<f", plain, 0x4C, 55.0)         # speed m/s marker
    ct = _encrypted(0x12345678, bytes(plain))
    out = gt7.decrypt_packet(ct)
    assert out is not None
    assert struct.unpack_from("<I", out, 0x00)[0] == 0x47375330
    assert abs(struct.unpack_from("<f", out, 0x4C)[0] - 55.0) < 1e-3


def t_decrypt_packet_rejects_garbage():
    assert gt7.decrypt_packet(bytes(0x128)) is None        # wrong magic
    assert gt7.decrypt_packet(b"short") is None            # too short


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_crypto.py`
Expected: FAIL — `No module named` / `AttributeError: module ... has no attribute 'salsa20_xor'`.

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Pure-Python Salsa20 decryption for the GT7 "Simulator Interface" UDP telemetry.

Vendored (no pip dependency): the toolkit ships as a single frozen binary and the
model is stdlib + external binaries only. Salsa20 is a stream cipher, so the same
XOR routine encrypts and decrypts. Reference: Nenkai/PDTools (MIT), the GT7
community field docs. See docs/superpowers/specs/2026-07-08-gt7-telemetry-pov-hud-design.md
"""
import struct

# Key = first 32 bytes of the fixed interface string.
KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
# Per-packet-version XOR constant for packet type 'A'.
IV_XOR_A = 0xDEADBEAF
# Decrypted magic (little-endian uint32 at offset 0) — "0S7G" bytes.
MAGIC = 0x47375330

_SIGMA = struct.unpack("<4I", b"expand 32-byte k")
_MASK = 0xFFFFFFFF


def _rotl(v, n):
    v &= _MASK
    return ((v << n) | (v >> (32 - n))) & _MASK


def _quarter(x, a, b, c, d):
    x[b] ^= _rotl(x[a] + x[d], 7)
    x[c] ^= _rotl(x[b] + x[a], 9)
    x[d] ^= _rotl(x[c] + x[b], 13)
    x[a] ^= _rotl(x[d] + x[c], 18)


def _block(key, nonce8, counter8):
    k = struct.unpack("<8I", key)
    n = struct.unpack("<2I", nonce8)
    b = struct.unpack("<2I", counter8)
    state = [
        _SIGMA[0], k[0], k[1], k[2],
        k[3], _SIGMA[1], n[0], n[1],
        b[0], b[1], _SIGMA[2], k[4],
        k[5], k[6], k[7], _SIGMA[3],
    ]
    x = list(state)
    for _ in range(10):                      # 20 rounds = 10 double-rounds
        _quarter(x, 0, 4, 8, 12)             # columns
        _quarter(x, 5, 9, 13, 1)
        _quarter(x, 10, 14, 2, 6)
        _quarter(x, 15, 3, 7, 11)
        _quarter(x, 0, 1, 2, 3)              # rows
        _quarter(x, 5, 6, 7, 4)
        _quarter(x, 10, 11, 8, 9)
        _quarter(x, 15, 12, 13, 14)
    out = [(x[i] + state[i]) & _MASK for i in range(16)]
    return struct.pack("<16I", *out)


def salsa20_xor(key, nonce8, data):
    """XOR `data` with the Salsa20/20 keystream (256-bit key, 64-bit nonce, counter 0)."""
    out = bytearray(len(data))
    for off in range(0, len(data), 64):
        ks = _block(key, nonce8, struct.pack("<Q", off // 64))
        chunk = data[off:off + 64]
        for j, byte in enumerate(chunk):
            out[off + j] = byte ^ ks[j]
    return bytes(out)


def decrypt_packet(data):
    """Decrypt a received GT7 packet. Returns the plaintext, or None if the packet
    is too short or the magic does not match (foreign/corrupt datagram)."""
    if len(data) < 0x44:
        return None
    iv1 = struct.unpack_from("<I", data, 0x40)[0]
    nonce = struct.pack("<II", iv1 ^ IV_XOR_A, iv1)
    plain = salsa20_xor(KEY, nonce, data)
    if struct.unpack_from("<I", plain, 0x00)[0] != MAGIC:
        return None
    return plain
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_crypto.py`
Expected: `ok t_decrypt_packet_ok` … `ALL PASS`. If `t_salsa20_test_vector` fails, the round/rotation order is wrong — recheck `_quarter` and the column/row order.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_crypto.py src/scripts/gt7_crypto.py
git commit -m "feat(solo): vendored pure-Python Salsa20 for GT7 telemetry (#324)"
```

---

### Task 2: Packet parser (`gt7_telemetry.py` — `parse_packet`)

**Files:**
- Create: `src/scripts/gt7_telemetry.py`
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: `gt7_crypto.decrypt_packet` (Task 1) in the relay glue, not here.
- Produces:
  - `GT7Packet` (a `dataclass` / `namedtuple` with: `speed_mps: float`, `fuel_level: float`, `fuel_capacity: float`, `tyre_temp: tuple[float,float,float,float]` (FL,FR,RL,RR), `throttle: int` (0-255), `brake: int` (0-255), `lap: int`, `best_ms: int`, `last_ms: int`, `flags: int`, `on_track: bool`, `paused: bool`, `loading: bool`)
  - `parse_packet(plain: bytes) -> GT7Packet`
  - Offset constants (module-level `OFF_*`) and flag-bit constants (`FLAG_ON_TRACK=1`, `FLAG_PAUSED=2`, `FLAG_LOADING=4`).

> **Offsets** are the community-documented packet-'A' layout. They are pinned here and validated **live** via `tools/gt7-telemetry-probe.py` (Task 9); the unit test proves the parser *wiring*, not real-world offset truth.

- [ ] **Step 1: Add the failing test (append to `tests/test_gt7_telemetry.py`)**

```python
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — module/attribute not found.

- [ ] **Step 3: Write minimal implementation (create `src/scripts/gt7_telemetry.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: `ok t_parse_fields`, `ok t_parse_flags`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_telemetry.py src/scripts/gt7_telemetry.py
git commit -m "feat(solo): GT7 packet parser (#324)"
```

---

### Task 3: Engine — lap detection, distance, delta, predicted

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (add `TelemetryEngine`)
- Test: `tests/test_gt7_telemetry.py` (add engine tests)

**Interfaces:**
- Consumes: `GT7Packet`, `parse_packet` (Task 2)
- Produces:
  - `class TelemetryEngine` with:
    - `update(pkt: GT7Packet, now: float) -> None` — feed one packet at wall-clock `now` (seconds).
    - `snapshot() -> dict` — see keys below.
  - `snapshot()` returns (this task's subset): `{"speed_mps", "tyre_temp": (fl,fr,rl,rr), "lap", "current_lap_s", "best_s"|None, "delta_s"|None, "predicted_s"|None, "has_reference": bool}`. `delta_s`/`predicted_s`/`best_s` are `None` until a reference lap exists.

- [ ] **Step 1: Add the failing test**

```python
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
    end = _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0)   # ~500 m in ~10 s
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `TelemetryEngine` not defined.

- [ ] **Step 3: Write minimal implementation (append to `gt7_telemetry.py`)**

```python
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
        if dt <= 0 or dt > 2.0:       # ignore backwards / long gaps (pause/menu)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: all `t_engine_*` `ok`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_telemetry.py src/scripts/gt7_telemetry.py
git commit -m "feat(solo): GT7 engine lap detection + delta/predicted (#324)"
```

---

### Task 4: Engine — fuel consumption + remaining laps/time

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (extend `TelemetryEngine`)
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Produces: `snapshot()` gains `"fuel": {"level": float, "per_lap": float|None, "laps_remaining": float|None, "time_remaining_s": float|None}`. `per_lap`/`laps_remaining`/`time_remaining_s` are `None` until ≥2 completed laps give a consumption figure. Consumption is smoothed over the last 3 completed laps; lap-time average over the last 3 completed lap times.

- [ ] **Step 1: Add the failing test**

```python
def t_engine_fuel_after_two_laps():
    eng = tm.TelemetryEngine()
    # Lap 1: start 60 L. Lap 2: start 57 L (3 L/lap). Lap 3: start 54 L.
    _feed_lap(eng, 100.0, 1, duration=10.0, speed=50.0, fuel_start=60.0)
    _feed_lap(eng, 200.0, 2, duration=10.0, speed=50.0, fuel_start=57.0)
    _feed_lap(eng, 300.0, 3, duration=10.0, speed=50.0, fuel_start=54.0)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `KeyError: 'fuel'`.

- [ ] **Step 3: Write minimal implementation**

In `_LapAccumulator.__init__` add fuel tracking:

```python
        self.fuel_start = None
        self.fuel_end = None
```

In `_LapAccumulator.add`, after the clean/gap guards (once we know the sample counts), record fuel:

```python
        if self.fuel_start is None:
            self.fuel_start = pkt.fuel_level
        self.fuel_end = pkt.fuel_level
```

In `TelemetryEngine.__init__` add:

```python
        self._lap_times = []      # last completed clean lap durations (s)
        self._lap_fuel = []       # last completed clean lap fuel burns (L)
```

In `_finalise_lap`, after the reference update, append history:

```python
        self._lap_times.append(acc.elapsed)
        self._lap_times = self._lap_times[-3:]
        if acc.fuel_start is not None and acc.fuel_end is not None:
            burn = acc.fuel_start - acc.fuel_end
            if burn > 0:
                self._lap_fuel.append(burn)
                self._lap_fuel = self._lap_fuel[-3:]
```

Add a helper and extend `snapshot`:

```python
    def _fuel(self):
        pkt = self._last
        level = pkt.fuel_level if pkt else 0.0
        per_lap = laps = time_rem = None
        if self._lap_fuel:
            per_lap = sum(self._lap_fuel) / len(self._lap_fuel)
            if per_lap > 0:
                laps = level / per_lap
                if self._lap_times:
                    avg = sum(self._lap_times) / len(self._lap_times)
                    time_rem = laps * avg
        return {"level": level, "per_lap": per_lap,
                "laps_remaining": laps, "time_remaining_s": time_rem}
```

In `snapshot()`'s returned dict add:

```python
            "fuel": self._fuel(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: `ok t_engine_fuel_after_two_laps`, `ok t_engine_fuel_none_before_two_laps`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_telemetry.py src/scripts/gt7_telemetry.py
git commit -m "feat(solo): GT7 engine fuel estimate (#324)"
```

---

### Task 5: Engine — throttle/brake trace ring buffer

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (extend `TelemetryEngine`)
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Produces:
  - `TelemetryEngine.trace_batch(limit: int = 150) -> list[dict]` — last N `{"t": float, "throttle": float(0-1), "brake": float(0-1)}`, oldest→newest. 60 Hz decimated to ≥ `TRACE_MIN_DT` (≈ 1/30 s) spacing, window `TRACE_WINDOW_S` (15 s).
  - Module constants `TRACE_WINDOW_S = 15.0`, `TRACE_MIN_DT = 1.0 / 30`.

- [ ] **Step 1: Add the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `trace_batch` not defined.

- [ ] **Step 3: Write minimal implementation**

Add constants near the top of `gt7_telemetry.py`:

```python
TRACE_WINDOW_S = 15.0
TRACE_MIN_DT = 1.0 / 30      # decimate 60 Hz -> ~30 Hz
```

Add to `TelemetryEngine.__init__`:

```python
        from collections import deque
        self._trace = deque()     # (t, throttle01, brake01), decimated + windowed
        self._trace_last_t = None
```

At the **end** of `TelemetryEngine.update` (after `self._last = pkt`):

```python
        if self._trace_last_t is None or (now - self._trace_last_t) >= TRACE_MIN_DT:
            self._trace_last_t = now
            self._trace.append((now, pkt.throttle / 255.0, pkt.brake / 255.0))
            cutoff = now - TRACE_WINDOW_S
            while self._trace and self._trace[0][0] < cutoff:
                self._trace.popleft()
```

Add the accessor:

```python
    def trace_batch(self, limit=150):
        items = list(self._trace)[-limit:]
        return [{"t": t, "throttle": thr, "brake": brk} for (t, thr, brk) in items]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: `ok t_engine_trace_decimates_and_windows`, `ok t_engine_trace_batch_limit`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_telemetry.py src/scripts/gt7_telemetry.py
git commit -m "feat(solo): GT7 engine throttle/brake trace buffer (#324)"
```

---

### Task 6: Thread-safe telemetry store + display formatting

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (add `TelemetryStore` + `format_snapshot`)
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Consumes: `TelemetryEngine` (Tasks 3-5)
- Produces:
  - `class TelemetryStore(path: str|None, units: str = "metric", thresholds: tuple = (70,85,95))`
    - `update(pkt, now)` — thread-safe engine feed; periodically persists the reference lap to `path` (JSON).
    - `data() -> dict` — the `/telemetry/data` payload: display-formatted numbers + `units` + `thresholds` + `has_reference`.
    - `trace(limit=150) -> list[dict]` — the `/telemetry/trace` payload.
  - `format_snapshot(snap: dict, units: str, thresholds: tuple) -> dict` — pure display formatter (speed→km/h|mph, tyre °C→°C|°F + band label, fuel L→L|gal, times→`m:ss.mmm`).
  - Band labels: `"cold" | "optimal" | "hot" | "critical"`.

- [ ] **Step 1: Add the failing test**

```python
def t_format_metric_and_bands():
    snap = {"speed_mps": 50.0, "tyre_temp": (65.0, 78.0, 90.0, 99.0),
            "lap": 4, "current_lap_s": 12.3, "best_s": 95.4,
            "delta_s": -0.42, "predicted_s": 94.98, "has_reference": True,
            "fuel": {"level": 40.0, "per_lap": 2.5, "laps_remaining": 16.0,
                     "time_remaining_s": 1600.0}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["speed"] == 180          # 50 m/s = 180 km/h
    assert out["units"]["speed"] == "km/h"
    assert [t["band"] for t in out["tyres"]] == ["cold", "optimal", "hot", "critical"]
    assert out["tyres"][0]["value"] == 65    # °C
    assert out["delta"] == -0.42
    assert out["has_reference"] is True


def t_format_imperial_converts_tyres():
    snap = {"speed_mps": 50.0, "tyre_temp": (70.0, 70.0, 70.0, 70.0),
            "lap": 1, "current_lap_s": 0.0, "best_s": None,
            "delta_s": None, "predicted_s": None, "has_reference": False,
            "fuel": {"level": 10.0, "per_lap": None,
                     "laps_remaining": None, "time_remaining_s": None}}
    out = tm.format_snapshot(snap, "imperial", (70, 85, 95))
    assert out["units"]["speed"] == "mph" and out["units"]["temp"] == "°F"
    assert out["tyres"][0]["value"] == 158     # 70°C -> 158°F
    assert out["tyres"][0]["band"] == "optimal"  # band still computed in °C
    assert out["speed"] == 112                 # 50 m/s -> 111.8 mph -> 112


def t_store_roundtrips_reference(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "telemetry.json")
    st = tm.TelemetryStore(path, units="metric")
    _feed_lap_store(st, 100.0, 1, duration=10.0, speed=50.0)
    assert st.data()["has_reference"] is True
    # A new store on the same path recovers the reference lap:
    st2 = tm.TelemetryStore(path, units="metric")
    assert st2.data()["has_reference"] is True


def _feed_lap_store(st, t0, lap, *, duration, speed, dt=0.1):
    t = t0
    for _ in range(int(duration / dt)):
        st.update(tm.parse_packet(_packet(speed_mps=speed, lap=lap)), t)
        t += dt
    st.update(tm.parse_packet(_packet(speed_mps=speed, lap=lap + 1)), t)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `format_snapshot` / `TelemetryStore` not defined.

- [ ] **Step 3: Write minimal implementation (append to `gt7_telemetry.py`)**

```python
import json
import os
import threading


def _fmt_time(seconds):
    if seconds is None:
        return None
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.3f}"


def _band(temp_c, thresholds):
    cold, opt_hi, crit = thresholds
    if temp_c < cold:
        return "cold"
    if temp_c <= opt_hi:
        return "optimal"
    if temp_c < crit:
        return "hot"
    return "critical"


def format_snapshot(snap, units, thresholds):
    imperial = units == "imperial"
    spd = snap["speed_mps"] * (2.2369363 if imperial else 3.6)
    tyres = []
    for c in snap["tyre_temp"]:
        val = c * 9 / 5 + 32 if imperial else c
        tyres.append({"value": round(val), "band": _band(c, thresholds)})
    fuel = snap["fuel"]
    lvl = fuel["level"] * (0.2641720 if imperial else 1.0)   # L -> gal
    return {
        "speed": round(spd),
        "tyres": tyres,
        "lap": snap["lap"],
        "current_lap": _fmt_time(snap["current_lap_s"]),
        "best_lap": _fmt_time(snap["best_s"]),
        "delta": None if snap["delta_s"] is None else round(snap["delta_s"], 2),
        "predicted": _fmt_time(snap["predicted_s"]),
        "has_reference": snap["has_reference"],
        "fuel": {
            "level": round(lvl, 1),
            "laps_remaining": (None if fuel["laps_remaining"] is None
                               else round(fuel["laps_remaining"], 1)),
            "time_remaining": _fmt_time(fuel["time_remaining_s"]),
        },
        "units": {
            "speed": "mph" if imperial else "km/h",
            "temp": "°F" if imperial else "°C",
            "fuel": "gal" if imperial else "L",
        },
    }


class TelemetryStore:
    """Thread-safe wrapper around TelemetryEngine. Persists ONLY the reference lap
    to `path` (survives an OBS Browser Source reload; resets on relay restart).
    """

    def __init__(self, path=None, units="metric", thresholds=(70, 85, 95)):
        self._eng = TelemetryEngine()
        self._lock = threading.Lock()
        self._path = path
        self._units = units
        self._thresholds = thresholds
        self._dirty_ref = None
        self._load()

    def update(self, pkt, now):
        with self._lock:
            had = self._eng._ref
            self._eng.update(pkt, now)
            if self._eng._ref is not had:      # a new reference lap was set
                self._save()

    def data(self):
        with self._lock:
            snap = self._eng.snapshot()
        return format_snapshot(snap, self._units, self._thresholds)

    def trace(self, limit=150):
        with self._lock:
            return self._eng.trace_batch(limit)

    def _save(self):
        if not self._path or self._eng._ref is None:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._eng._ref, fh)
            os.replace(tmp, self._path)
        except OSError:
            pass                               # best-effort, never crash the relay

    def _load(self):
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                ref = json.load(fh)
            if (isinstance(ref, dict) and isinstance(ref.get("time"), (int, float))
                    and isinstance(ref.get("samples"), list) and len(ref["samples"]) >= 2):
                ref["samples"] = [(float(d), float(t)) for d, t in ref["samples"]]
                self._eng._ref = ref
        except (OSError, ValueError, TypeError):
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: all format/store tests `ok`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add tests/test_gt7_telemetry.py src/scripts/gt7_telemetry.py
git commit -m "feat(solo): GT7 telemetry store + display formatting (#324)"
```

---

### Task 7: Relay UDP listener + heartbeat thread + config knobs

**Files:**
- Modify: `src/relay/racecast-feeds.py` (argparse flags; UDP thread; construct store in `main`)
- Modify: `.env.example` (document the new keys)

**Interfaces:**
- Consumes: `gt7_crypto.decrypt_packet`, `gt7_telemetry.parse_packet`, `gt7_telemetry.TelemetryStore`.
- Produces: a `telemetry_store` object (or `None`) available in `main()` for Task 8's `make_handler` call.

> The relay already imports sibling `src/scripts` modules. Follow the existing import style at the top of `racecast-feeds.py` (it uses a `sys.path`/importlib helper — mirror how `logsetup` / `console_auth` are imported there). No new third-party imports.

- [ ] **Step 1: Add argparse flags** (near the other flags, ~line 7755 by `--solo`)

```python
    ap.add_argument("--gt7-ps-ip", default=os.environ.get("RACECAST_GT7_PS_IP"),
                    help="PS4/PS5 IP for GT7 UDP telemetry (solo/POV). "
                         "Empty -> subnet-broadcast discovery.")
    ap.add_argument("--no-telemetry", action="store_true",
                    default=_env_flag("RACECAST_GT7_TELEMETRY", default=True) is False,
                    help="Disable the GT7 telemetry listener (solo only).")
```

Use the existing env-flag helper if one exists (grep for how `RACECAST_FEED_FANOUT` is parsed); otherwise add a tiny local helper near the top of `main`:

```python
    def _env_flag(name, default):
        v = os.environ.get(name)
        if v is None:
            return default
        return v.strip().lower() not in {"0", "false", "no", "off"}
```

- [ ] **Step 2: Construct the store + thread in `main()`** (after `relay.start()` at ~8097, inside the existing flow; guard on solo)

```python
    telemetry_store = None
    if args.solo and not args.no_telemetry:
        units = os.environ.get("RACECAST_TELEMETRY_UNITS", "metric")
        thr = (
            float(os.environ.get("RACECAST_TELEMETRY_TYRE_COLD", 70)),
            float(os.environ.get("RACECAST_TELEMETRY_TYRE_OPTIMAL_HI", 85)),
            float(os.environ.get("RACECAST_TELEMETRY_TYRE_HOT_HI", 95)),
        )
        telemetry_store = gt7_telemetry.TelemetryStore(
            os.path.join(runtime, "telemetry.json"), units=units, thresholds=thr)
        threading.Thread(
            target=_telemetry_loop,
            args=(telemetry_store, args.gt7_ps_ip, stop_evt),
            daemon=True).start()
        log.info("GT7 telemetry listener started (bind 0.0.0.0:33740, ps_ip=%s)",
                 args.gt7_ps_ip or "<discovery>")
```

> `stop_evt` and `log` already exist in `main()` (used by the schedule poller). If the telemetry block runs before `stop_evt` is defined, move it just after that definition. Confirm by grepping `stop_evt =` in `main()`.

- [ ] **Step 3: Add the listener loop** (module-level function, near the other daemon loops)

```python
GT7_RECV_PORT = 33740
GT7_SEND_PORT = 33739
GT7_HEARTBEAT_S = 10.0


def _telemetry_loop(store, ps_ip, stop_evt):
    """Bind 33740, send a heartbeat every ~10 s, decrypt+parse+feed each packet.
    Best-effort: any error logs and the loop keeps running; no console -> idle."""
    import socket as _socket
    tlog = logging.getLogger("racecast.relay.telemetry")
    sock = None
    last_hb = 0.0
    dest = ps_ip
    while not stop_evt.is_set():
        try:
            if sock is None:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
                sock.bind(("0.0.0.0", GT7_RECV_PORT))
                sock.settimeout(1.0)
            now = time.monotonic()
            if now - last_hb >= GT7_HEARTBEAT_S:
                target = dest or "255.255.255.255"
                try:
                    sock.sendto(b"A", (target, GT7_SEND_PORT))
                except OSError as e:
                    tlog.warning("heartbeat send failed: %s", e)
                last_hb = now
            try:
                data, addr = sock.recvfrom(4096)
            except _socket.timeout:
                continue
            if dest is None:                 # discovery: latch the responder
                dest = addr[0]
                tlog.info("GT7 console discovered at %s", dest)
            plain = gt7_crypto.decrypt_packet(data)
            if plain is None:
                continue
            store.update(gt7_telemetry.parse_packet(plain), time.time())
        except OSError as e:
            tlog.warning("telemetry socket error: %s — reopening", e)
            try:
                if sock:
                    sock.close()
            except OSError:
                pass
            sock = None
            stop_evt.wait(1.0)
        except Exception as e:                 # never let the thread die silently
            tlog.error("telemetry loop error: %s", e)
            stop_evt.wait(1.0)
```

> Add the `gt7_crypto` / `gt7_telemetry` imports at the top of `racecast-feeds.py` using the same importlib/sys.path pattern the file already uses for `logsetup`. `time`, `logging`, `threading` are already imported (grep to confirm; add only what's missing).

- [ ] **Step 4: Document the keys in `.env.example`**

```bash
# --- GT7 telemetry (solo / POV only; ignored in endurance) ---
# PS4/PS5 IP that runs GT7. Empty -> subnet-broadcast discovery.
RACECAST_GT7_PS_IP=
# Master switch for the telemetry listener (1/0). Default on in solo.
RACECAST_GT7_TELEMETRY=1
# Display units: metric (km/h, °C, L) or imperial (mph, °F, gal).
RACECAST_TELEMETRY_UNITS=metric
# Tyre-temp colour band edges in °C (comparison always in °C; display converts).
RACECAST_TELEMETRY_TYRE_COLD=70
RACECAST_TELEMETRY_TYRE_OPTIMAL_HI=85
RACECAST_TELEMETRY_TYRE_HOT_HI=95
```

- [ ] **Step 5: Smoke-check import + run the suite**

Run:
```bash
python3 -c "import importlib.util,os; s=importlib.util.spec_from_file_location('r','src/relay/racecast-feeds.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('import ok', hasattr(m,'_telemetry_loop'))"
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: `import ok True`; lint clean; full suite green (nothing disabled).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py .env.example
git commit -m "feat(solo): GT7 UDP telemetry listener + heartbeat + config (#324)"
```

---

### Task 8: Relay endpoints `/telemetry/data` + `/telemetry/trace`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`make_handler` param; `do_GET` routes; `main()` `make_handler` call)
- Test: `tests/test_telemetry_endpoints.py`

**Interfaces:**
- Consumes: `telemetry_store` (Task 7).
- Produces: `GET /telemetry/data` → `store.data()`; `GET /telemetry/trace` → `{"samples": store.trace(150)}`. Both return `404 {"error": "telemetry disabled"}` when `telemetry_store is None` (endurance / disabled).

- [ ] **Step 1: Write the failing endpoint test**

```python
#!/usr/bin/env python3
"""Endpoint checks for the GT7 telemetry routes. Run: python3 tests/test_telemetry_endpoints.py

Exercises the do_GET routing for /telemetry/* by driving a handler instance with a
fake request, mirroring the style of the other endpoint tests in this repo (grep
tests/ for how make_handler is exercised without a live socket; reuse that harness
helper). Asserts: solo store -> shaped JSON; None store -> 404."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_telemetry_data_shape():
    store = m.gt7_telemetry.TelemetryStore(None, units="metric")
    payload = store.data()
    assert set(payload) >= {"speed", "tyres", "fuel", "units", "has_reference"}
    assert len(payload["tyres"]) == 4


def t_telemetry_trace_shape():
    store = m.gt7_telemetry.TelemetryStore(None)
    assert store.trace(10) == []          # empty before any packet


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

> If the repo has an existing handler-invocation harness (e.g. `test_ui_server.py` / a relay endpoint test drives `H` with a fake `rfile`/`wfile`), add a route-level test there asserting `/telemetry/data` returns 200 with a store and 404 without. Keep this file for the store-shape checks regardless.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_telemetry_endpoints.py`
Expected: FAIL — `module ... has no attribute 'gt7_telemetry'` until Task 7's import is in place; if Task 7 landed, the store-shape assertions define the contract.

- [ ] **Step 3: Add the `make_handler` parameter**

In `make_handler(...)` signature (line ~5926), add to the keyword params:

```python
                 telemetry_store=None,
```

- [ ] **Step 4: Add the routes in `do_GET`** (next to the other `/hud` routes, before the fallthrough)

```python
                if p == ["telemetry", "data"]:
                    if telemetry_store is None:
                        return self._send({"error": "telemetry disabled"}, 404)
                    return self._send(telemetry_store.data())
                if p == ["telemetry", "trace"]:
                    if telemetry_store is None:
                        return self._send({"error": "telemetry disabled"}, 404)
                    return self._send({"samples": telemetry_store.trace(150)})
```

- [ ] **Step 5: Pass the store at the `make_handler` call site** (~line 8155)

Add the keyword argument to the existing call:

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           # ... existing args unchanged ...
                           telemetry_store=telemetry_store)
```

- [ ] **Step 6: Run tests + lint**

Run:
```bash
python3 tests/test_telemetry_endpoints.py
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: `ALL PASS`; lint clean; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_telemetry_endpoints.py
git commit -m "feat(solo): /telemetry/data + /telemetry/trace endpoints (#324)"
```

---

### Task 9: HUD telemetry block in `hud.html` + Visual Overlay Builder slots

**Files:**
- Modify: `src/obs/hud.html` (self-gating telemetry block + polling + canvas)
- Modify: `src/scripts/overlay_build.py` (register the new slots so the builder can position them)
- Test: `tests/test_overlay.py` (assert the new slots are extracted)

**Interfaces:**
- Consumes: `GET /telemetry/data`, `GET /telemetry/trace` (Task 8).
- Produces: rendered tyres (with band colours), throttle/brake canvas, delta, predicted, fuel — hidden until `/telemetry/data` returns 200 (endurance 404 ⇒ hidden). Delta/predicted hidden until `has_reference`.

- [ ] **Step 1: Add a failing slot-extraction test** (mirror the existing slot test in `test_overlay.py`)

```python
def t_telemetry_slots_present():
    # The builder must see the telemetry slots so a POV profile can position them.
    slots = ov.extract_slots(_read("src", "obs", "hud.html"))   # reuse the file's helper
    keys = {s["key"] for s in slots}
    assert {"tyres", "inputTrace", "delta", "predicted", "fuel"} <= keys
```

> Match the exact helper names already in `test_overlay.py` (`extract_slots` / `_read` may differ — grep the file and reuse its real API). If slots are keyed differently (e.g. `data-edit="tele-tyres"`), align the assertion to the chosen marker names.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — the telemetry slot keys are missing.

- [ ] **Step 3: Add the telemetry block to `hud.html`**

Add the markup (inside the overlay root, after the existing HUD elements). Use `data-edit` markers consistent with the existing slots:

```html
<div id="tele" style="display:none">
  <div class="el" data-edit="tyres" id="tele-tyres">
    <span class="tw" data-w="fl">--</span><span class="tw" data-w="fr">--</span>
    <span class="tw" data-w="rl">--</span><span class="tw" data-w="rr">--</span>
  </div>
  <canvas class="el" data-edit="inputTrace" id="tele-trace" width="240" height="60"></canvas>
  <div class="el" data-edit="delta" id="tele-delta" style="display:none">--</div>
  <div class="el" data-edit="predicted" id="tele-pred" style="display:none">--</div>
  <div class="el" data-edit="fuel" id="tele-fuel">--</div>
</div>
```

Add band colours to the page CSS (respect any per-league override):

```css
.tw{display:inline-block;min-width:2.4em;text-align:center}
.tw[data-band="cold"]{color:#4ea3ff}
.tw[data-band="optimal"]{color:#37d67a}
.tw[data-band="hot"]{color:#f5a623}
.tw[data-band="critical"]{color:#ff4d4f}
```

- [ ] **Step 4: Add the polling + render JS** (near the existing `/hud/data` poller in `hud.html`)

```javascript
(function () {
  const tele = document.getElementById("tele");
  const ctx = document.getElementById("tele-trace").getContext("2d");
  let alive = false;

  async function pollData() {
    try {
      const r = await fetch("/telemetry/data", { cache: "no-store" });
      if (r.status === 404) { tele.style.display = "none"; alive = false; return; }
      if (!r.ok) return;
      const d = await r.json();
      alive = true; tele.style.display = "";
      const wheels = ["fl", "fr", "rl", "rr"];
      d.tyres.forEach((t, i) => {
        const el = tele.querySelector('[data-w="' + wheels[i] + '"]');
        el.textContent = t.value + d.units.temp;
        el.setAttribute("data-band", t.band);
      });
      const delta = document.getElementById("tele-delta");
      const pred = document.getElementById("tele-pred");
      if (d.has_reference && d.delta !== null) {
        delta.style.display = ""; pred.style.display = "";
        delta.textContent = (d.delta >= 0 ? "+" : "") + d.delta.toFixed(2) + "s";
        pred.textContent = d.predicted || "--";
      } else {
        delta.style.display = "none"; pred.style.display = "none";
      }
      const f = d.fuel;
      document.getElementById("tele-fuel").textContent =
        f.level + d.units.fuel +
        (f.laps_remaining !== null ? " · " + f.laps_remaining + " laps" : "") +
        (f.time_remaining ? " · " + f.time_remaining : "");
    } catch (e) { /* transient; keep polling */ }
  }

  async function pollTrace() {
    if (!alive) return;
    try {
      const r = await fetch("/telemetry/trace", { cache: "no-store" });
      if (!r.ok) return;
      const { samples } = await r.json();
      const w = ctx.canvas.width, h = ctx.canvas.height;
      ctx.clearRect(0, 0, w, h);
      if (!samples.length) return;
      const t0 = samples[0].t, span = (samples[samples.length - 1].t - t0) || 1;
      const draw = (key, color) => {
        ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2;
        samples.forEach((s, i) => {
          const x = ((s.t - t0) / span) * w;
          const y = h - s[key] * h;
          i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        });
        ctx.stroke();
      };
      draw("throttle", "#37d67a"); draw("brake", "#ff4d4f");
    } catch (e) { /* transient */ }
  }

  setInterval(pollData, 100);
  setInterval(pollTrace, 100);
  pollData();
})();
```

- [ ] **Step 5: Register the slots in `overlay_build.py`**

Add the five telemetry slot keys to the slot registry / default layout so the Visual Overlay Builder lists and positions them (follow the exact structure `overlay_build.py` already uses for HUD slots — the `data-edit` markers are the source, so extraction may be automatic; if there is an explicit slot allow-list or default-position map, add `tyres`, `inputTrace`, `delta`, `predicted`, `fuel` with sensible default boxes).

- [ ] **Step 6: Run tests + lint**

Run:
```bash
python3 tests/test_overlay.py
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: `ALL PASS`; full suite green.

- [ ] **Step 7: Visual verification (REQUIRED before commit)**

Use the **ui-visual-verification** skill: run the relay in a solo profile with a **fake-telemetry feeder** (Task 10 provides `tools/gt7-telemetry-probe.py --replay`, or feed the store directly), open `/hud`, and confirm tyres colour-band correctly, the throttle/brake trace scrolls, delta/predicted appear only after a reference lap, and fuel renders. Fix any styling/alignment issues before proceeding.

- [ ] **Step 8: Commit**

```bash
git add src/obs/hud.html src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(solo): telemetry HUD block + builder slots (#324)"
```

---

### Task 10: Maintainer probe tool + wiki screenshot + spec risk note

**Files:**
- Create: `tools/gt7-telemetry-probe.py`
- Modify: `src/docs/wiki/images/` (new/updated HUD screenshot) + the wiki page that shows the solo HUD
- Modify: `CLAUDE.md` Commands section (one line documenting the probe tool, matching the `broadcast-chat-probe.py` entry)

**Interfaces:**
- Produces: a standalone diagnostic — `python3 tools/gt7-telemetry-probe.py [--ps-ip IP]` sends the heartbeat, decrypts, and prints parsed fields from a live console; `--replay FILE` feeds captured/synthetic packets for offline HUD testing. Not shipped (lives in `tools/`).

- [ ] **Step 1: Write the probe tool**

```python
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
```

- [ ] **Step 2: Verify it imports and runs (no console needed)**

Run: `python3 tools/gt7-telemetry-probe.py --ps-ip 127.0.0.1` (Ctrl-C after it prints the "no packet" line — proves the loop + imports work without hardware).
Expected: prints `listening on 33740` then `… no packet …`.

- [ ] **Step 3: Capture the wiki screenshot**

Use the **wiki-screenshots** skill. Because the telemetry block only renders with live data, drive `/hud` with a **fake-telemetry feeder** (a short script that constructs a `TelemetryStore`, feeds a synthetic lap so `has_reference` is true, and serves it — or point the running solo relay at `tools/gt7-telemetry-probe.py` extended with a `--replay` synthetic emitter). Take an **element** screenshot of `#tele` from a local dev build (no `VERSION` stamp). Commit the image under `src/docs/wiki/images/` with the naming the wiki page expects, and add a short "Solo POV telemetry HUD" section to the relevant wiki page.

- [ ] **Step 4: Document the probe in `CLAUDE.md`**

Add one line under the Commands section, next to the `broadcast-chat-probe.py` entry:

```
# Probe GT7 UDP telemetry (#324) against a LIVE PS4/PS5 — standalone, no relay/Sheet.
python3 tools/gt7-telemetry-probe.py --ps-ip 192.168.1.42   # heartbeat + decrypt + field dump
```

- [ ] **Step 5: Full suite + lint + commit**

Run:
```bash
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: green.

```bash
git add tools/gt7-telemetry-probe.py src/docs/wiki/ CLAUDE.md
git commit -m "feat(solo): GT7 telemetry probe tool + wiki HUD shot + docs (#324)"
```

---

### Task 11: Engine + format — session top speed + tyre 30 s average

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (extend `TelemetryEngine` + `format_snapshot`)
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Produces: `snapshot()` gains `"top_speed_mps": float` and `"tyre_temp_avg": (fl,fr,rl,rr)`. `format_snapshot` output gains `"top_speed"` (display unit, rounded int) and each `tyres[i]` gains `"avg"` (display unit, rounded int). The colour band stays driven by the current °C.

- [ ] **Step 1: Add the failing tests**

```python
def t_engine_top_speed_tracks_onair_max():
    eng = tm.TelemetryEngine()
    eng.update(tm.parse_packet(_packet(speed_mps=40.0, lap=1)), 100.0)
    eng.update(tm.parse_packet(_packet(speed_mps=80.0, lap=1)), 100.1)
    eng.update(tm.parse_packet(_packet(speed_mps=55.0, lap=1)), 100.2)
    # a higher speed while paused/off-track must NOT count (menu/replay artefact):
    eng.update(tm.parse_packet(_packet(speed_mps=200.0, lap=1, flags=tm.FLAG_PAUSED)), 100.3)
    assert abs(eng.snapshot()["top_speed_mps"] - 80.0) < 1e-6


def t_engine_tyre_avg_windowed():
    eng = tm.TelemetryEngine()
    t = 100.0
    # 40 s of FL=60, then 10 s of FL=100 -> the 30 s average should be pulled
    # toward 100 (the >30 s-old 60s samples fall out of the window).
    for _ in range(400):
        eng.update(tm.parse_packet(_packet(tyre_temp=(60.0, 60.0, 60.0, 60.0), lap=1)), t); t += 0.1
    for _ in range(100):
        eng.update(tm.parse_packet(_packet(tyre_temp=(100.0, 100.0, 100.0, 100.0), lap=1)), t); t += 0.1
    avg_fl = eng.snapshot()["tyre_temp_avg"][0]
    assert avg_fl > 80.0, avg_fl          # window no longer contains the old 60s block fully


def t_format_includes_top_speed_and_tyre_avg():
    snap = {"speed_mps": 50.0, "tyre_temp": (70.0, 70.0, 70.0, 70.0),
            "tyre_temp_avg": (68.0, 69.0, 71.0, 72.0), "top_speed_mps": 90.0,
            "lap": 1, "current_lap_s": 0.0, "best_s": None, "delta_s": None,
            "predicted_s": None, "has_reference": False,
            "fuel": {"level": 10.0, "per_lap": None, "laps_remaining": None,
                     "time_remaining_s": None}}
    out = tm.format_snapshot(snap, "metric", (70, 85, 95))
    assert out["top_speed"] == 324             # 90 m/s -> 324 km/h
    assert out["tyres"][0]["avg"] == 68 and out["tyres"][0]["value"] == 70
    imp = tm.format_snapshot(snap, "imperial", (70, 85, 95))
    assert imp["top_speed"] == 201             # 90 m/s -> 201 mph
    assert imp["tyres"][0]["avg"] == 154       # 68 C -> 154 F
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: FAIL — `KeyError: 'top_speed_mps'` / `'tyre_temp_avg'`.

- [ ] **Step 3: Implement**

Add a constant near `TRACE_WINDOW_S`:

```python
TYRE_AVG_WINDOW_S = 30.0
```

In `TelemetryEngine.__init__` add:

```python
        self._tyre_hist = deque()     # (t, (fl,fr,rl,rr)) over TYRE_AVG_WINDOW_S
        self._top_speed = 0.0
```

At the **end** of `TelemetryEngine.update` (after the trace-append block):

```python
        if pkt.on_track and not pkt.paused and pkt.speed_mps > self._top_speed:
            self._top_speed = pkt.speed_mps
        self._tyre_hist.append((now, pkt.tyre_temp))
        tcut = now - TYRE_AVG_WINDOW_S
        while self._tyre_hist and self._tyre_hist[0][0] < tcut:
            self._tyre_hist.popleft()
```

Add a helper:

```python
    def _tyre_avg(self):
        if not self._tyre_hist:
            return self._last.tyre_temp if self._last else (0.0, 0.0, 0.0, 0.0)
        sums = [0.0, 0.0, 0.0, 0.0]
        for _, temps in self._tyre_hist:
            for i in range(4):
                sums[i] += temps[i]
        n = len(self._tyre_hist)
        return tuple(s / n for s in sums)
```

In `snapshot()`'s returned dict add:

```python
            "tyre_temp_avg": self._tyre_avg(),
            "top_speed_mps": self._top_speed,
```

In `format_snapshot`, replace the tyre loop so each entry carries `avg`, and add `top_speed`:

```python
    avgs = snap["tyre_temp_avg"]
    tyres = []
    for i, c in enumerate(snap["tyre_temp"]):
        val = c * 9 / 5 + 32 if imperial else c
        a = avgs[i] * 9 / 5 + 32 if imperial else avgs[i]
        tyres.append({"value": round(val), "avg": round(a), "band": _band(c, thresholds)})
```

and in the returned dict add:

```python
        "top_speed": round(snap["top_speed_mps"] * (2.2369363 if imperial else 3.6)),
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: `ALL PASS` (incl. the 3 new tests + all prior).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/gt7_telemetry.py tests/test_gt7_telemetry.py
git commit -m "feat(solo): session top speed + tyre 30s average (#324)"
```

---

### Task 12: HUD — top-speed element + tyre average display

**Files:**
- Modify: `src/obs/hud.html` (top-speed slot + tyre avg render)
- Modify: `src/scripts/overlay_build.py` (SAMPLE preview for the new `tele-top` text slot, if the guard test requires it)
- Test: `tests/test_overlay.py`
- Controller: ui-visual-verification pass after.

**Interfaces:**
- Consumes: `/telemetry/data` now returns `top_speed` + `tyres[i].avg`.
- Produces: a `#tele-top` element (builder slot) showing top speed; each tyre shows current (band colour) with a small dimmed `ø<avg>`.

- [ ] **Step 1: Add the failing slot test** (to `tests/test_overlay.py`)

```python
def t_ob_hud_has_top_speed_slot():
    with open(os.path.join(ROOT, "src", "obs", "hud.html")) as f:
        ids = {s["id"] for s in ob.extract_slots(f.read())}
    assert "tele-top" in ids
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `tele-top` missing.

- [ ] **Step 3: Markup** — add a top-speed element inside `#tele` (after `#tele-fuel`), and give each tyre span an avg child:

```html
    <div id="tele-top" class="el white" data-edit="Top speed" data-edit-kind="text">--</div>
```

Change each tyre span to carry a small avg child, e.g.:

```html
      <span class="tw" data-w="fl">--<small class="ta" data-a="fl"></small></span>
```
(do this for fl/fr/rl/rr).

- [ ] **Step 4: CSS** — add near the other `#tele-*` rules:

```css
  #tele-top{left:1400px;top:460px}
  .ta{font-size:.6em;opacity:.75;margin-left:.15em}
```

- [ ] **Step 5: JS** — in the `pollData` tyre loop, set the current value and the avg child; and set the top-speed element. Replace the tyre-render lines with:

```javascript
          d.tyres.forEach((t, i) => {
            const el = tele.querySelector('[data-w="' + wheels[i] + '"]');
            el.setAttribute("data-band", t.band);
            const av = el.querySelector('[data-a="' + wheels[i] + '"]');
            el.childNodes[0].nodeValue = t.value + d.units.temp;
            if (av) av.textContent = (t.avg != null ? " ø" + t.avg : "");
          });
          document.getElementById("tele-top").textContent =
            "TOP " + d.top_speed + " " + d.units.speed;
```

(`el.childNodes[0]` is the leading text node before the `<small>` child — set its value so the avg `<small>` is preserved.)

- [ ] **Step 6: Overlay-build sample** — if `python3 tests/test_overlay.py` fails on `t_ob_sample_covers_every_text_slot`, add a preview string for `tele-top` to `SAMPLE["hud"]` in `src/scripts/overlay_build.py` (e.g. `"tele-top": "TOP 291 km/h"`), pure data like the Task 9 entries.

- [ ] **Step 7: Run tests + lint**

Run:
```bash
python3 tests/test_overlay.py
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: ALL PASS; full suite green.

- [ ] **Step 8: Controller visual verification (REQUIRED)**

The controller re-runs the fake-telemetry render (`scratchpad/tele_shot.py` — extend the feeder so top speed and a spread of tyre history populate), confirms the top-speed line and the `ø<avg>` render legibly over a dark backdrop, re-records the marker for `src/obs/hud.html`, and commits.

- [ ] **Step 9: Commit**

```bash
git add src/obs/hud.html src/scripts/overlay_build.py tests/test_overlay.py
git commit -m "feat(solo): HUD top-speed + tyre 30s average display (#324)"
```

---

## Final verification (before opening the PR)

- [ ] `python3 tools/run-tests.py` — full suite green, **no test disabled**.
- [ ] `python3 tools/lint.py` — clean.
- [ ] `python3 tools/build.py` — verify step passes (no shell scripts, no secrets, tokenization intact).
- [ ] Endurance unaffected: a non-solo relay start binds no telemetry socket and `/telemetry/data` 404s (grep-confirm the `args.solo` guard on the store + thread).
- [ ] Spec risks are documented in the design spec (undocumented API, no field data, fuel-map re-convergence, GPL boundary) — no code change needed, just confirm the spec section is present.
- [ ] **Manual/live (user, real PS5 + GT7):** heartbeat received & decrypted on 33740; tyres + trace live; reference lap → delta/predicted appear; fuel after ≥2 laps; no phantom laps from menu/replay; HUD survives a Browser Source reload; no feed ports bound; relay 8088 unaffected.

## Self-review notes (author)

- **Spec coverage:** crypto §A→T1; parser §B→T2; lap/delta/predicted §B→T3; fuel §B→T4; trace §B→T5; store+units §D/§G→T6; UDP+heartbeat+config §C/§G→T7; endpoints §E→T8; HUD §F→T9; probe+wiki+risks §Testing/§Wiki/§Risks→T10. All spec sections mapped.
- **Offset honesty:** T2 note states unit tests prove parser *wiring*; real offsets are live-validated via T9/T10 — the one place a live correction lands (`OFF_*` constants).
- **Type consistency:** `TelemetryStore.data()`/`.trace()` shapes in T6 match the endpoint payloads in T8 and the JS field names in T9 (`tyres[].value/.band`, `units.temp/.speed/.fuel`, `has_reference`, `delta`, `predicted`, `fuel.level/.laps_remaining/.time_remaining`).
- **Grep-confirm items flagged inline** (env-flag helper, `stop_evt`/`log` availability, the import pattern for sibling modules, the `make_handler` call-site arg list, `test_overlay.py` helper names, any existing handler test harness) — the executor verifies these against the real file rather than assuming.
