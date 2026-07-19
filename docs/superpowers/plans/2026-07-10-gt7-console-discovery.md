# GT7 console auto-discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit operator action — `racecast gt7-discover` (CLI) and a "Discover PlayStation" button in the Control Center — that finds the PS4/PS5 running GT7 on the LAN and persists its IP into `RACECAST_GT7_PS_IP` in the machine `.env`.

**Architecture:** A new pure-ish scanner module (`src/scripts/gt7_discovery.py`) reuses the proven GT7 heartbeat mechanism (bind `0.0.0.0:33740`, broadcast `b"A"` to `255.255.255.255:33739`, latch only responders whose reply *decrypts*). A two-tier caller helper in `src/racecast.py` (`resolve_console`) prefers a running relay's already-latched console IP (read over `GET /telemetry/data`, avoiding a `33740` port conflict) and otherwise runs a fresh scan. Both the CLI verb and two Control Center data endpoints persist the chosen IP via the existing `env_upsert_data` write path — mirroring the `device-scan` feature end-to-end.

**Tech Stack:** Python 3 stdlib only (no deps). Tests are runnable scripts (`python3 tests/test_*.py`), not pytest. UDP `socket`, existing `gt7_crypto`/`gt7_telemetry`, `http_util`, the Control Center `ui_server` + `control-center.html`.

## Global Constraints

- **Edit only under `src/`** (and `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- **All scripts and docs English only.**
- **Never hardcode secrets or machine paths.** No real IPs in tests — use RFC1918/test constants like `192.168.1.42`.
- **Machine `.env` keys must be `RACECAST_`-prefixed** (`env_write_data` enforces `MACHINE_ENV_PREFIX`). No new env key — reuse `RACECAST_GT7_PS_IP`.
- **The relay (`src/relay/racecast-feeds.py`) is deliberately import-free** — it must NOT import `src/scripts/gt7_discovery.py`. Constants duplicated there stay duplicated (add a cross-reference comment).
- **Tests must run offline / in CI** — no live OBS/PS/relay; use injected socket/`now`/`decrypt`/HTTP seams.
- **Cross-platform** — the test matrix includes Windows. UDP broadcast socket code must not assume POSIX-only behaviour.
- **Changed a UI surface? Refresh its wiki screenshot in the SAME change.** The General Settings view gains a button → `src/docs/wiki/images/cc-settings.png` MUST be regenerated (Task 8) via the `wiki-screenshots` skill against a local dev build (no `VERSION`).
- **After any Python change run** `python3 tools/lint.py` and the touched test files; before finishing run `python3 tools/run-tests.py`.
- **Run one test file:** `python3 tests/test_<name>.py` (prints `ALL PASS`). **Run one function:** `python3 -c "import sys; sys.path.insert(0,'tests'); import test_x as t; t.t_fn()"`.

---

### Task 1: Pure UDP scanner — `src/scripts/gt7_discovery.py`

**Files:**
- Create: `src/scripts/gt7_discovery.py`
- Test: `tests/test_gt7_discovery.py`

**Interfaces:**
- Consumes: `gt7_crypto.decrypt_packet(data) -> bytes|None` (default `decrypt` seam).
- Produces:
  - `discover_consoles(timeout=4.0, *, sock_factory=None, decrypt=None, now=None, heartbeat_interval=1.0) -> {"consoles": [ip:str, ...], "note": str}` — deduped, sorted IPs of GT7 consoles that replied with a decryptable packet; `note` is `""` on a hit and the "active session" hint when empty; never raises.
  - Module constants `GT7_RECV_PORT=33740`, `GT7_SEND_PORT=33739`, `GT7_HEARTBEAT=b"A"`, `BROADCAST_ADDR="255.255.255.255"`, `NO_CONSOLE_NOTE` (the exact hint string).

- [ ] **Step 1: Write the failing test**

Create `tests/test_gt7_discovery.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for GT7 console discovery. Run: python3 tests/test_gt7_discovery.py"""
import importlib.util, os, socket

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


disc = _load("gt7_discovery", ("src", "scripts", "gt7_discovery.py"))


class _FakeSock:
    """Records sendto; yields queued (data, addr) from recvfrom, then socket.timeout."""
    def __init__(self, packets):
        self._packets = list(packets)
        self.sent = []
        self.closed = False
    def sendto(self, data, addr):
        self.sent.append((data, addr))
    def recvfrom(self, _n):
        if self._packets:
            return self._packets.pop(0)
        raise socket.timeout()
    def close(self):
        self.closed = True


def _now_seq(values):
    it = iter(values)
    def _now():
        try:
            return next(it)
        except StopIteration:
            return 10_000.0
    return _now


def _ok_decrypt(data):
    return data if data.startswith(b"OK") else None


def t_latches_only_decryptable_and_dedupes():
    packets = [
        (b"OK1", ("192.168.1.42", 33740)),   # real console
        (b"NO",  ("192.168.1.99", 33740)),   # foreign host — must be ignored
        (b"OK2", ("192.168.1.42", 33740)),   # same console again — dedup
    ]
    fake = _FakeSock(packets)
    out = disc.discover_consoles(
        timeout=2.0, sock_factory=lambda: fake, decrypt=_ok_decrypt,
        now=_now_seq([0, 0, 0, 0, 0, 100]))
    assert out["consoles"] == ["192.168.1.42"], out
    assert out["note"] == ""
    assert fake.sent and fake.sent[0][1] == (disc.BROADCAST_ADDR, disc.GT7_SEND_PORT)
    assert fake.closed is True


def t_two_consoles_sorted():
    packets = [
        (b"OK3", ("192.168.1.50", 33740)),
        (b"OK1", ("192.168.1.42", 33740)),
    ]
    out = disc.discover_consoles(
        timeout=2.0, sock_factory=lambda: _FakeSock(packets), decrypt=_ok_decrypt,
        now=_now_seq([0, 0, 0, 0, 100]))
    assert out["consoles"] == ["192.168.1.42", "192.168.1.50"], out


def t_no_reply_returns_hint():
    out = disc.discover_consoles(
        timeout=2.0, sock_factory=lambda: _FakeSock([]), decrypt=_ok_decrypt,
        now=_now_seq([0, 0, 100]))
    assert out["consoles"] == []
    assert "active session" in out["note"]


def t_socket_error_never_raises():
    def _boom():
        raise OSError("no broadcast permission")
    out = disc.discover_consoles(timeout=2.0, sock_factory=_boom, decrypt=_ok_decrypt,
                                 now=_now_seq([0, 100]))
    assert out["consoles"] == []
    assert out["note"]  # a non-empty error note


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_gt7_discovery.py`
Expected: FAIL — `FileNotFoundError`/`ModuleNotFoundError` for `src/scripts/gt7_discovery.py` (module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/gt7_discovery.py`:

```python
"""GT7 console (PlayStation) discovery over the LAN — the explicit, operator-facing
scan behind `racecast gt7-discover` and the Control Center "Discover PlayStation"
button. Reuses the proven GT7 heartbeat: bind 0.0.0.0:33740, broadcast a heartbeat
byte to 255.255.255.255:33739, and latch a responder ONLY when its reply decrypts —
which proves it is a real GT7 console emitting valid telemetry, not any LAN host that
happens to sit on that port.

Pure-ish + best-effort: socket / clock / decrypt are injectable seams (unit-tested with
a fake socket) and the function NEVER raises. The relay (racecast-feeds.py) is
deliberately import-free, so the port constants below are DUPLICATED there
(GT7_RECV_PORT / GT7_SEND_PORT / GT7_HEARTBEAT_S) — keep the two copies in sync.
"""
import importlib.util
import os
import socket
import time

GT7_RECV_PORT = 33740          # local port we bind + the console replies to
GT7_SEND_PORT = 33739          # console's heartbeat port
GT7_HEARTBEAT = b"A"
BROADCAST_ADDR = "255.255.255.255"
NO_CONSOLE_NOTE = ("No PlayStation answered. Make sure GT7 is in an active session "
                   "(menus emit no telemetry) and the console is on this LAN.")


def _default_decrypt(data):
    """Lazily load gt7_crypto.decrypt_packet (sibling module, importlib to stay
    runnable both from src/ and the frozen bundle)."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "gt7_crypto", os.path.join(here, "gt7_crypto.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.decrypt_packet(data)


def _default_sock_factory():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", GT7_RECV_PORT))
    sock.settimeout(0.5)
    return sock


def discover_consoles(timeout=4.0, *, sock_factory=None, decrypt=None, now=None,
                      heartbeat_interval=1.0):
    """Scan the LAN for GT7 consoles for `timeout` seconds. Returns
    {"consoles": [ip, ...] sorted+deduped, "note": str}. Never raises."""
    sock_factory = sock_factory or _default_sock_factory
    decrypt = decrypt or _default_decrypt
    now = now or time.monotonic
    try:
        sock = sock_factory()
    except OSError as exc:
        return {"consoles": [], "note": f"discovery could not open a socket: {exc}"}
    found = set()
    try:
        start = now()
        last_hb = start - heartbeat_interval  # force an immediate first heartbeat
        while True:
            t = now()
            if t - start >= timeout:
                break
            if t - last_hb >= heartbeat_interval:
                try:
                    sock.sendto(GT7_HEARTBEAT, (BROADCAST_ADDR, GT7_SEND_PORT))
                except OSError:
                    pass  # a transient send failure: keep listening, retry next tick
                last_hb = t
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                continue
            try:
                if decrypt(data) is not None:
                    found.add(addr[0])
            except Exception:
                continue  # a malformed packet must never abort the scan
    finally:
        try:
            sock.close()
        except OSError:
            pass
    consoles = sorted(found)
    return {"consoles": consoles, "note": "" if consoles else NO_CONSOLE_NOTE}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_discovery.py`
Expected: `ok t_...` for all four, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/gt7_discovery.py tests/test_gt7_discovery.py
git commit -m "feat(gt7): LAN console discovery scanner (decrypt-gated, best-effort)"
```

---

### Task 2: Expose the relay's latched console IP on `/telemetry/data`

**Files:**
- Modify: `src/scripts/gt7_telemetry.py` (`TelemetryStore`, `__init__` ~line 385, `data()` ~line 414)
- Modify: `src/relay/racecast-feeds.py` (`_telemetry_loop`, latch point ~line 7694)
- Test: `tests/test_gt7_telemetry.py`

**Interfaces:**
- Produces: `TelemetryStore.set_source(ip: str|None) -> None` (thread-safe); `TelemetryStore.data()` return dict now carries a `"source"` key (the latched console IP, or `None`).
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gt7_telemetry.py` (before the `__main__` runner):

```python
def t_store_source_roundtrip():
    store = tm.TelemetryStore()
    assert store.data()["source"] is None      # unset by default
    store.set_source("192.168.1.42")
    assert store.data()["source"] == "192.168.1.42"
    store.set_source(None)                       # clearable (e.g. relaunch)
    assert store.data()["source"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_gt7_telemetry as t; t.t_store_source_roundtrip()"`
Expected: FAIL — `AttributeError: 'TelemetryStore' object has no attribute 'set_source'`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/gt7_telemetry.py`, in `TelemetryStore.__init__` add `self._source = None` after `self._lock = threading.Lock()`:

```python
        self._eng = TelemetryEngine()
        self._lock = threading.Lock()
        self._source = None            # latched console IP (discovery/UX), or None
```

Add a `set_source` method and extend `data()` in the same class:

```python
    def set_source(self, ip):
        """Record the console IP the listener latched (surfaced on /telemetry/data
        so `racecast gt7-discover` can read it without a second 33740 bind)."""
        with self._lock:
            self._source = ip

    def data(self):
        with self._lock:
            snap = self._eng.snapshot()
            source = self._source
        out = format_snapshot(snap, self._units, self._thresholds)
        out["source"] = source
        return out
```

(Replace the existing `data()` body — it currently does `with self._lock: snap = ...; return format_snapshot(...)`.)

In `src/relay/racecast-feeds.py`, at the latch point inside `_telemetry_loop`:

```python
            if dest is None:                 # discovery: latch the responder
                dest = addr[0]
                store.set_source(dest)
                tlog.info("GT7 console discovered at %s", dest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_gt7_telemetry.py`
Expected: all `ok t_...` incl. `t_store_source_roundtrip`, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/gt7_telemetry.py src/relay/racecast-feeds.py tests/test_gt7_telemetry.py
git commit -m "feat(gt7): surface latched console IP on /telemetry/data"
```

---

### Task 3: Two-tier `resolve_console` helper in `src/racecast.py`

**Files:**
- Modify: `src/racecast.py` (add helper + import near the other `import` lines / helper section; `RELAY_PORT`/`http_util` already exist)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `gt7_discovery.discover_consoles(...)` (Task 1); `http_util.get_json(url, timeout=...)`; module constant `RELAY_PORT` (=8088, already defined ~line 881).
- Produces: `resolve_console(timeout=4.0, *, discover=None, relay_get=None) -> {"consoles": [ip, ...], "note": str, "from_relay": bool}` — tier 1 returns the running relay's latched `source` IP (`from_relay=True`) if present; else falls through to a fresh scan (`from_relay=False`). Never raises. `discover`/`relay_get` are injected test seams.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py` (before the `__main__` runner):

```python
def t_resolve_console_prefers_relay():
    # A running relay that already latched a console short-circuits the scan.
    out = m.resolve_console(
        relay_get=lambda: {"source": "192.168.1.42"},
        discover=lambda **k: (_ for _ in ()).throw(AssertionError("must not scan")))
    assert out == {"consoles": ["192.168.1.42"], "note": "", "from_relay": True}


def t_resolve_console_scans_when_no_relay():
    # No relay (relay_get returns None) -> fall through to the scanner.
    out = m.resolve_console(
        relay_get=lambda: None,
        discover=lambda **k: {"consoles": ["192.168.1.50"], "note": ""})
    assert out == {"consoles": ["192.168.1.50"], "note": "", "from_relay": False}


def t_resolve_console_scans_when_relay_unlatched():
    # Relay up but telemetry not yet latched (source None) -> scan.
    out = m.resolve_console(
        relay_get=lambda: {"source": None},
        discover=lambda **k: {"consoles": [], "note": "nope"})
    assert out == {"consoles": [], "note": "nope", "from_relay": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_resolve_console_prefers_relay()"`
Expected: FAIL — `AttributeError: module 'racecast' has no attribute 'resolve_console'`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`, add near the relay-HTTP helpers (after `_relay_get`, ~line 893):

```python
def _relay_telemetry_source():
    """The console IP a running relay already latched, via GET /telemetry/data.
    None on any failure (no relay, telemetry disabled -> 404, timeout)."""
    try:
        data = http_util.get_json(
            f"http://127.0.0.1:{RELAY_PORT}/telemetry/data", timeout=2)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("source")


def resolve_console(timeout=4.0, *, discover=None, relay_get=None):
    """Resolve GT7 console IP(s) two ways: prefer a running relay's already-latched
    console (no second 33740 bind, instant); else broadcast-scan the LAN. Returns
    {consoles, note, from_relay}. Never raises."""
    relay_get = relay_get or _relay_telemetry_source
    src = relay_get()
    if src:
        return {"consoles": [src], "note": "", "from_relay": True}
    discover = discover or _discover_consoles
    res = discover(timeout=timeout)
    return {"consoles": res.get("consoles", []), "note": res.get("note", ""),
            "from_relay": False}
```

Add a small lazy loader for the scanner near the top-level helpers (the `src/scripts/` modules are loaded via importlib elsewhere in this file — follow the existing `import obs_ws` in-function style):

```python
def _discover_consoles(**kwargs):
    import gt7_discovery
    return gt7_discovery.discover_consoles(**kwargs)
```

(Note: `src/scripts/` is already on `sys.path` for `import obs_ws`/`import http_util`; `import gt7_discovery` resolves the same way.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: all `ok t_...` incl. the three `t_resolve_console_*`, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(gt7): resolve_console two-tier helper (relay-latched or LAN scan)"
```

---

### Task 4: CLI `racecast gt7-discover`

**Files:**
- Modify: `src/racecast.py` — help text (~line 33), `route()` (~line 1016, after the `device-scan` branch), `main()` dispatch (~line 6509, after the `device-scan` call), new `_parse_gt7_discover_args` + `gt7_discover_cmd`, and `ps_ip_write_data` (shared with Task 5).
- Test: `tests/test_racecast.py`

**Interfaces:**
- Consumes: `resolve_console(...)` (Task 3); `env_upsert_data(updates, path=None)` (~line 4590). Validation uses a local `_PS_HOST_RE` (charset identical to `ui_ops._HOST_RE`) to avoid a cross-package import into `src/racecast.py` (see Step 3).
- Produces:
  - `route(["gt7-discover", ...])` -> `{"kind": "gt7-discover", "rest": [...]}`.
  - `_parse_gt7_discover_args(rest) -> (save: bool, print_only: bool, timeout: float, pick: str|None)` — raises `ValueError` with a `usage:` string on an unknown flag.
  - `gt7_discover_cmd(rest) -> None`.
  - `ps_ip_write_data(ip: str, path=None) -> {"ok": bool, ...}` — validates `ip` then `env_upsert_data({"RACECAST_GT7_PS_IP": ip})`; `{"ok": False, "error": ...}` on a bad IP.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py`:

```python
def t_route_gt7_discover():
    assert m.route(["gt7-discover"]) == {"kind": "gt7-discover", "rest": []}
    assert m.route(["gt7-discover", "--save", "--timeout", "6"]) == \
        {"kind": "gt7-discover", "rest": ["--save", "--timeout", "6"]}


def t_parse_gt7_discover_args():
    assert m._parse_gt7_discover_args([]) == (False, False, 4.0, None)
    assert m._parse_gt7_discover_args(["--save"]) == (True, False, 4.0, None)
    assert m._parse_gt7_discover_args(["--print"]) == (False, True, 4.0, None)
    assert m._parse_gt7_discover_args(["--timeout", "6"]) == (False, False, 6.0, None)
    assert m._parse_gt7_discover_args(["--pick", "2"]) == (False, False, 4.0, "2")
    try:
        m._parse_gt7_discover_args(["--nope"]); assert False
    except ValueError as e:
        assert "usage:" in str(e)


def t_ps_ip_write_validates_and_upserts(tmp_path=None):
    import tempfile, os as _os
    fd, path = tempfile.mkstemp(suffix=".env"); _os.close(fd)
    try:
        bad = m.ps_ip_write_data("not a host!", path=path)
        assert bad["ok"] is False and "invalid" in bad["error"].lower()
        good = m.ps_ip_write_data("192.168.1.42", path=path)
        assert good["ok"] is True
        with open(path, encoding="utf-8") as f:
            assert "RACECAST_GT7_PS_IP=192.168.1.42" in f.read()
    finally:
        _os.remove(path)


def t_gt7_discover_cmd_single_save(capsys=None):
    # One console found + --save -> writes RACECAST_GT7_PS_IP via env_upsert_data.
    import tempfile, os as _os
    fd, path = tempfile.mkstemp(suffix=".env"); _os.close(fd)
    saved_resolve = m.resolve_console
    saved_write = m.ps_ip_write_data
    writes = {}
    m.resolve_console = lambda **k: {"consoles": ["192.168.1.42"], "note": "",
                                     "from_relay": True}
    m.ps_ip_write_data = lambda ip, path=None: writes.setdefault("ip", ip) or {"ok": True}
    try:
        m.gt7_discover_cmd(["--save"])
    finally:
        m.resolve_console = saved_resolve
        m.ps_ip_write_data = saved_write
        _os.remove(path)
    assert writes["ip"] == "192.168.1.42"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_route_gt7_discover()"`
Expected: FAIL — `route` returns `{"kind": "unknown", ...}` (or KeyError), no `gt7-discover` branch.

- [ ] **Step 3: Write minimal implementation**

In `route()`, after the `device-scan` branch (~line 1017):

```python
    if cmd == "gt7-discover":
        return {"kind": "gt7-discover", "rest": rest}
```

In `main()`, after the `device-scan` dispatch (~line 6510):

```python
    if action["kind"] == "gt7-discover":
        return gt7_discover_cmd(action["rest"])
```

Add the help line near line 33 (in the usage/help block, next to `device-scan`):

```
      gt7-discover [--save] [--print] [--timeout N] [--pick I]
                              find the PS4/PS5 running GT7 and save its IP
```

Add a module-level IP validator + the three functions (place near `device_scan_cmd`, ~line 2610):

```python
import re as _re
_PS_HOST_RE = _re.compile(r"^[A-Za-z0-9.\-]{1,253}\Z")   # mirrors ui_ops._HOST_RE


def ps_ip_write_data(ip, path=None):
    """Validate + upsert the PS4/PS5 IP into the machine .env as
    RACECAST_GT7_PS_IP. `path` is a test seam (mirrors env_upsert_data's)."""
    ip = (ip or "").strip()
    if not _PS_HOST_RE.match(ip):
        return {"ok": False, "error": f"invalid host/IP: {ip!r}"}
    return env_upsert_data({"RACECAST_GT7_PS_IP": ip}, path=path)


def _parse_gt7_discover_args(rest):
    """Return (save, print_only, timeout, pick). Raises ValueError on bad input."""
    usage = ("usage: racecast gt7-discover [--save] [--print] "
             "[--timeout N] [--pick INDEX]")
    save = print_only = False
    timeout = 4.0
    pick = None
    it = iter(rest)
    for tok in it:
        if tok == "--save":
            save = True
        elif tok == "--print":
            print_only = True
        elif tok == "--timeout":
            try:
                timeout = float(next(it))
            except (StopIteration, ValueError):
                raise ValueError(f"--timeout needs a number. {usage}")
        elif tok == "--pick":
            try:
                pick = next(it)
            except StopIteration:
                raise ValueError(f"--pick needs an index. {usage}")
        else:
            raise ValueError(f"unknown flag {tok!r}. {usage}")
    return save, print_only, timeout, pick


def gt7_discover_cmd(rest):
    """`racecast gt7-discover [--save] [--print] [--timeout N] [--pick I]` — find the
    PS4/PS5 running GT7 on the LAN (reuses a running relay's latched console when up,
    else a broadcast scan) and write its IP to RACECAST_GT7_PS_IP. --save skips the
    prompt (for non-TTY); --print never writes; --pick selects when several are found."""
    try:
        save, print_only, timeout, pick = _parse_gt7_discover_args(rest)
    except ValueError as exc:
        sys.exit(str(exc))
    res = resolve_console(timeout=timeout)
    consoles, note = res["consoles"], res["note"]
    if res["from_relay"]:
        print(f"Using console latched by the running relay: {consoles[0]}")
    if not consoles:
        print(f"gt7-discover: {note}")
        return None
    if len(consoles) == 1:
        chosen = consoles[0]
        print(f"Found PlayStation: {chosen}")
    else:
        print("Found PlayStations:")
        for i, ip in enumerate(consoles, start=1):
            print(f"  {i}. {ip}")
        if pick is None:
            if not sys.stdin.isatty():
                print("gt7-discover: pass --pick INDEX to choose one "
                      "(non-interactive session).")
                return None
            pick = input(f"Pick [1-{len(consoles)}, blank=cancel]: ").strip()
        if not pick:
            print("gt7-discover: cancelled.")
            return None
        try:
            chosen = consoles[int(pick) - 1]
        except (ValueError, IndexError):
            sys.exit(f"gt7-discover: invalid selection {pick!r}.")
    if print_only:
        return None
    if not save and sys.stdin.isatty():
        ans = input(f"Save {chosen} to RACECAST_GT7_PS_IP? [Y/n]: ").strip().lower()
        if ans in ("n", "no"):
            print("gt7-discover: not saved.")
            return None
    elif not save:
        print(f"gt7-discover: found {chosen} (pass --save to write it to .env).")
        return None
    out = ps_ip_write_data(chosen)
    if not out.get("ok"):
        sys.exit(f"gt7-discover: {out.get('error')}")
    print(f"gt7-discover: wrote RACECAST_GT7_PS_IP={chosen} to .env.")
    print("Restart the relay (`racecast relay restart`) to apply.")
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: all `ok t_...` incl. the new four, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(gt7): racecast gt7-discover CLI (find + save PS IP)"
```

---

### Task 5: Control Center data endpoints — `/api/ps/discover` + `/api/ps/save`

**Files:**
- Modify: `src/racecast.py` — add `ps_discover_data()`; register `ps_discover` + `ps_write` in the ctx registry (~line 6368, next to `devices_enumerate`/`devices_write`). (`ps_ip_write_data` already exists from Task 4.)
- Modify: `src/ui/ui_server.py` — GET/POST route for `/api/ps/discover` and POST `/api/ps/save` (mirror `/api/devices` ~line 449 and `/api/devices/select` ~line 627); update the ctx docstring ~line 115.
- Test: `tests/test_ui_server.py`

**Interfaces:**
- Consumes: `resolve_console(...)` (Task 3), `ps_ip_write_data(ip)` (Task 4).
- Produces:
  - `ps_discover_data() -> {"ok": bool, "consoles": [ip,...], "note": str, "from_relay": bool}` (`ok` = has at least one console).
  - ctx keys `"ps_discover": ps_discover_data`, `"ps_write": ps_ip_write_data`.
  - Routes: `POST /api/ps/discover` -> `ctx["ps_discover"]()`; `POST /api/ps/save` (body `{"ip": "..."}`) -> `ctx["ps_write"](ip)`.

- [ ] **Step 1: Write the failing test**

The harness in `tests/test_ui_server.py` is: `_ctx(**overrides)` builds the ctx dict, `_serve(ctx) -> (httpd, port)` runs a real server, `_get(port, path)` / `_post_json(port, path, obj)` return `(code, body_str)` (parse with `json.loads`). Mirror the `t_post_devices_select_*` tests. Append:

```python
def t_api_ps_discover_route():
    ctx = _ctx(ps_discover=lambda: {"ok": True, "consoles": ["192.168.1.42"],
                                    "note": "", "from_relay": False})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/ps/discover", {})
        data = json.loads(body)
        assert code == 200 and data["consoles"] == ["192.168.1.42"]
    finally:
        httpd.shutdown()


def t_api_ps_save_route():
    saved = {}
    ctx = _ctx(ps_write=lambda ip: saved.setdefault("ip", ip) or {"ok": True})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/ps/save", {"ip": "192.168.1.42"})
        assert code == 200 and json.loads(body)["ok"] is True
        assert saved["ip"] == "192.168.1.42"
    finally:
        httpd.shutdown()


def t_api_ps_save_rejects_bad_ip():
    ctx = _ctx(ps_write=lambda ip: {"ok": False, "error": f"invalid host/IP: {ip!r}"})
    httpd, port = _serve(ctx)
    try:
        code, body = _post_json(port, "/api/ps/save", {"ip": "bad host!"})
        assert code == 400 and json.loads(body)["ok"] is False
    finally:
        httpd.shutdown()
```

> `_ctx` passes unknown kwargs straight into the ctx dict (as the device tests rely on). If it does not, add `ps_discover`/`ps_write` to its default set the same way `devices_enumerate`/`devices_write` are provided.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the `/api/ps/discover` route 404s (unknown path) / `ps_discover` not in ctx.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py` add `ps_discover_data` (near `devices_enumerate_data`, ~line 4611):

```python
def ps_discover_data():
    """Control Center General-Settings data: discover the PS4/PS5 running GT7 on the
    LAN (a running relay's latched console, else a broadcast scan). Never raises."""
    res = resolve_console()
    return {"ok": bool(res["consoles"]), "consoles": res["consoles"],
            "note": res["note"], "from_relay": res["from_relay"]}
```

Register in the ctx dict (next to `"devices_write": devices_write_data,`):

```python
        "ps_discover": ps_discover_data,
        "ps_write": ps_ip_write_data,
```

In `src/ui/ui_server.py`, add the discover route next to the `/api/devices` GET handler is not ideal (discovery is an action) — put both under `do_POST` next to `/api/devices/select` (~line 627):

```python
            if path == "/api/ps/discover":
                try:
                    return self._json(ctx["ps_discover"]())
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not discover PlayStation: {exc}"},
                                      code=500)
            if path == "/api/ps/save":
                body = self._body_json()
                if body is None:
                    return self._json({"ok": False, "error": "malformed JSON body"},
                                      code=400)
                try:
                    result = ctx["ps_write"](body.get("ip"))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not save PS IP: {exc}"},
                                      code=500)
                return self._json(result, code=200 if result.get("ok") else 400)
```

Update the ctx docstring (~line 115) to mention `ps_discover()` / `ps_write(ip)` alongside `devices_enumerate`/`devices_write`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_ui_server.py`
Expected: all `ok t_...` incl. the new three, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(gt7): Control Center /api/ps/discover + /api/ps/save endpoints"
```

---

### Task 6: Control Center UI — "Discover PlayStation" in the Solo-devices card

**Files:**
- Modify: `src/ui/control-center.html` — extend the `#dev-section` / Solo-devices card (~line 1009–1033) with a PS-IP row + button + hint; add the JS (near the "Solo devices" JS ~line 2526).

**Interfaces:**
- Consumes: `POST /api/ps/discover`, `POST /api/ps/save` (Task 5).
- Produces: no exported symbols (in-page).

- [ ] **Step 1: Add the markup**

Inside the Solo-devices section (after the `#dev-tyres` select row, before the `#dev-hint` paragraph, ~line 1032), add:

```html
          <div class="devrow" style="margin-top:12px">
            <label for="ps-ip" style="min-width:150px">PlayStation IP (GT7)</label>
            <input id="ps-ip" type="text" style="flex:1" placeholder="e.g. 192.168.1.42"
                   aria-label="PlayStation IP">
            <button id="ps-discover" onclick="discoverPs()">Discover PlayStation</button>
            <button id="ps-save" onclick="savePsIp()">Save</button>
          </div>
          <select id="ps-list" style="width:100%;margin-top:6px" aria-label="Found consoles" hidden></select>
          <p class="envhint" id="ps-hint">Set the console IP by hand, or click Discover (GT7 must be in an active session).</p>
```

> Match the existing `devrow`/label/`select` classes used by the webcam/capture rows above (copy their class attributes verbatim so styling is consistent).

- [ ] **Step 2: Add the JS**

Near the Solo-devices JS block (~line 2526), add:

```javascript
// ----- PlayStation (GT7 console) discovery -----
async function discoverPs(){
  const hint = document.getElementById('ps-hint');
  const list = document.getElementById('ps-list');
  const btn = document.getElementById('ps-discover');
  btn.disabled = true; hint.textContent = 'Scanning the LAN for GT7…';
  try{
    const r = await fetch('/api/ps/discover', {method:'POST'});
    const d = await r.json();
    const consoles = d.consoles || [];
    if(!consoles.length){ list.hidden = true; hint.textContent = d.note || 'No PlayStation found.'; return; }
    if(consoles.length === 1){
      list.hidden = true;
      document.getElementById('ps-ip').value = consoles[0];
      hint.textContent = d.from_relay
        ? 'Using the console the running relay already latched. Click Save to pin it.'
        : 'Found one console. Click Save to write it to .env.';
    } else {
      list.hidden = false;
      list.innerHTML = consoles.map(ip => `<option value="${ip}">${ip}</option>`).join('');
      document.getElementById('ps-ip').value = consoles[0];
      list.onchange = () => { document.getElementById('ps-ip').value = list.value; };
      hint.textContent = 'Multiple consoles found — pick one, then Save.';
    }
  }catch(e){ hint.textContent = 'Discovery failed: ' + e; }
  finally{ btn.disabled = false; }
}
async function savePsIp(){
  const hint = document.getElementById('ps-hint');
  const ip = document.getElementById('ps-ip').value.trim();
  if(!ip){ hint.textContent = 'Enter or discover a PlayStation IP first.'; return; }
  try{
    const r = await fetch('/api/ps/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ip})});
    const d = await r.json();
    hint.textContent = d.ok
      ? 'Saved RACECAST_GT7_PS_IP — restart the relay to apply.'
      : ('Could not save: ' + (d.error || 'unknown error'));
    if(d.ok && typeof loadSettings === 'function'){ loadSettings(true); }  // refresh the .env editor
  }catch(e){ hint.textContent = 'Save failed: ' + e; }
}
```

(`loadSettings(force)` at ~line 2511 is the function that repopulates the `.env` editor from `/api/env` — calling it after a successful save shows the new `RACECAST_GT7_PS_IP` value.)

- [ ] **Step 3: Visually verify (ui-visual-verification skill)**

This edits a rendered surface (Control Center). Per the repo's blocking Stop-hook, run the **`ui-visual-verification`** skill: start a local dev build (`racecast ui` from `src/`, on a free `RACECAST_UI_PORT`), open General Settings, confirm the "Discover PlayStation" row renders aligned with the device rows, the button states work, and the hint updates. Capture the marker the skill requires.

- [ ] **Step 4: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(gt7): Discover PlayStation UI in Control Center Solo-devices"
```

---

### Task 7: Docs — `.env.example` + `CLAUDE.md`

**Files:**
- Modify: `.env.example` (~line 119–121, the GT7 section)
- Modify: `CLAUDE.md` (commands list, near the GT7/telemetry / `device-scan` entries)

**Interfaces:** none (documentation).

- [ ] **Step 1: Update `.env.example`**

Replace the `RACECAST_GT7_PS_IP` comment block:

```
# --- GT7 telemetry (solo / POV only; ignored in endurance) ---
# PS4/PS5 IP that runs GT7. Empty -> subnet-broadcast discovery at runtime. Set by
# hand, or use `racecast gt7-discover` / the Control Center's "Discover PlayStation"
# button (General Settings -> Solo devices) to find + save it automatically.
RACECAST_GT7_PS_IP=
```

- [ ] **Step 2: Update `CLAUDE.md`**

Add to the commands block, near the other one-shot verbs / the GT7 probe line:

```
python3 src/racecast.py gt7-discover      # find the PS4/PS5 running GT7 on the LAN and (with --save / the Control Center button) persist its IP to RACECAST_GT7_PS_IP; prefers a running relay's already-latched console, else a broadcast scan (GT7 must be in an active session)
```

- [ ] **Step 3: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(gt7): document racecast gt7-discover + Discover PlayStation"
```

---

### Task 8: Refresh `cc-settings.png` + full suite

**Files:**
- Modify: `src/docs/wiki/images/cc-settings.png` (and any mirrored `src/docs/slides/assets/img/` copy the `wiki-screenshots` skill produces).

**Interfaces:** none.

- [ ] **Step 1: Regenerate the screenshot**

Run the **`wiki-screenshots`** skill against a **local dev build** (run `racecast ui` from `src/`, no `VERSION` stamped, so the version badge stays uniform — per the "wiki screenshots use local dev build" rule). Populate the General Settings view (the demo profile recipe the skill documents), capture the Settings card so the "Discover PlayStation" row is visible, framed like the existing `cc-settings.png`.

- [ ] **Step 2: Full suite + lint**

Run:
```bash
python3 tools/lint.py
python3 tools/run-tests.py
```
Expected: lint clean; `run-tests.py` reports all suites pass (incl. `test_gt7_discovery`, `test_gt7_telemetry`, `test_racecast`, `test_ui_server`).

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/images/cc-settings.png src/docs/slides/assets/img/
git commit -m "docs(gt7): refresh cc-settings screenshot for Discover PlayStation"
```

---

## Final verification

- [ ] `python3 tools/run-tests.py` — whole suite green.
- [ ] `python3 tools/lint.py` — clean.
- [ ] Open a PR into `epic/300-solo-mode` referencing the new sub-issue under #300 (one PR per issue). Title e.g. `feat(gt7): PlayStation auto-discovery (CLI + Control Center)`. Let CI go green; the user makes the final defer-vs-fix call on any review minors.

## Spec-coverage self-check (from the design)

- Discovery via GT7 heartbeat, decrypt-gated → Task 1.
- Two-tier source resolution (relay-latched vs scan), 33740 conflict avoided → Tasks 2 + 3.
- CLI `racecast gt7-discover` (0/1/≥2 consoles, `--save`/`--print`/`--pick`, `env_upsert_data`) → Task 4.
- Control Center Discover + Save (endpoints + UI) → Tasks 5 + 6.
- `.env.example` + `CLAUDE.md` → Task 7.
- `cc-settings.png` refreshed; full suite → Task 8.
- New sub-issue under #300, PR into `epic/300-solo-mode` → Final verification.
