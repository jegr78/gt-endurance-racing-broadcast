# obs-websocket Clean Close Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `obs_ws._Session.close()` perform a proper RFC 6455 closing handshake so OBS records clean code-1000 closes instead of the ~40k abnormal code-1006 "End of File" disconnects racecast currently causes.

**Architecture:** Replace the empty-payload close frame + immediate `sock.close()` with: send a status-1000 close frame, `shutdown(SHUT_WR)`, drain inbound briefly (bounded by a 1 s timeout) until OBS's close echo / EOF, then close the socket. Best-effort throughout — never raises, never hangs.

**Tech Stack:** Pure Python 3 + stdlib (`socket`, `struct`). Tests are runnable scripts (`t_*` functions, no pytest); `tests/test_obsws.py` loads the module via importlib as `m`.

## Global Constraints

- Edit only under `src/` and `tests/`. Stdlib only; no new dependencies; `obs_ws.py` is stdlib-only by design.
- All code and comments in English.
- `_Session.close()` MUST remain best-effort: it never raises (callers rely on the `(names, note)` best-effort contract) and never blocks indefinitely (a dead/slow OBS must hit the timeout, not hang).
- `close()` must stay safe to call after OBS already dropped the socket (current contract): a `sendall`/`shutdown` that raises `OSError` is swallowed and the socket is still closed.
- Exact new constant: `CLOSE_DRAIN_TIMEOUT_S = 1.0` (max seconds to wait for OBS's close echo).
- The close frame must carry status code 1000 as a 2-byte big-endian payload: `struct.pack(">H", 1000)`.
- Do NOT change connection COUNT or any caller — only `_Session.close()` and the new constant.
- Run `python3 tools/lint.py` and `python3 tests/test_obsws.py` after changes.

---

### Task 1: Clean closing handshake in `_Session.close()`

**Files:**
- Modify: `src/scripts/obs_ws.py` — add `CLOSE_DRAIN_TIMEOUT_S` near the module constants (after `RELAY_PORTS`, line ~37); rewrite `_Session.close()` (lines 342-347)
- Test: `tests/test_obsws.py` — add a minimal fake socket + `t_*` close tests

**Interfaces:**
- Consumes: `encode_frame(payload, mask=None, opcode=0x1)` (existing), `struct`, `socket` (both already imported in `obs_ws.py`).
- Produces:
  - module constant `CLOSE_DRAIN_TIMEOUT_S = 1.0`
  - reworked `_Session.close(self)` — same name/signature, no return value; sends a status-1000 close frame, half-closes write, drains (≤1 s), closes the socket; never raises.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsws.py` (near the other `_Session`/close tests). The module is loaded as `m`; `socket` and `struct` are already imported at the top of the test file.

```python
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


def t_close_sends_status_1000_then_shutdown_then_close():
    sock = _FakeSock(recv_chunks=[b""])          # immediate EOF
    sess = m._Session(sock, b"")
    sess.close()
    opcode, payload = _unmask_client_frame(sock.sent)
    assert opcode == 0x8, opcode                  # close frame
    assert payload == struct.pack(">H", 1000), payload   # status 1000
    # write half-closed before the socket is closed
    assert "shutdown" in sock.calls and "close" in sock.calls
    assert sock.calls.index("shutdown") < sock.calls.index("close")
    assert sock.timeout == m.CLOSE_DRAIN_TIMEOUT_S


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_obsws.py`
Expected: FAIL — `t_close_sends_status_1000_then_shutdown_then_close` fails because the current `close()` sends an empty payload (assert on `struct.pack(">H", 1000)` fails) and never calls `shutdown`/`settimeout` (`AttributeError`/assertion on `sock.timeout`).

- [ ] **Step 3: Add the `CLOSE_DRAIN_TIMEOUT_S` constant**

In `src/scripts/obs_ws.py`, after `RELAY_PORTS = (53001, 53002, 53003)` (line ~37):

```python
RELAY_PORTS = (53001, 53002, 53003)
CLOSE_DRAIN_TIMEOUT_S = 1.0   # max seconds to wait for OBS's close echo before closing the socket
```

- [ ] **Step 4: Rewrite `_Session.close()`**

Replace the current body (lines 342-347):

```python
    def close(self):
        try:
            self.sock.sendall(encode_frame(b"", opcode=0x8))   # polite close
        except OSError:
            pass  # OBS may have dropped the socket first — close is courtesy only
        self.sock.close()
```

with the closing-handshake version:

```python
    def close(self):
        """Best-effort RFC 6455 closing handshake so OBS logs a clean 1000 close
        instead of an abnormal 1006/EOF: send a status-1000 close frame, half-close
        the write side, briefly drain OBS's echo (bounded by CLOSE_DRAIN_TIMEOUT_S),
        then close the socket. Never raises; never blocks past the drain timeout."""
        try:
            self.sock.sendall(encode_frame(struct.pack(">H", 1000), opcode=0x8))
        except OSError:
            pass  # OBS may have dropped the socket first — the rest is courtesy only
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            self.sock.settimeout(CLOSE_DRAIN_TIMEOUT_S)
            while True:
                if not self.sock.recv(65536):   # OBS's close echo / EOF
                    break
        except OSError:
            pass  # timeout or reset — stop draining and close
        self.sock.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_obsws.py`
Expected: PASS — all `t_*` print `ok`, including the four new close tests.

- [ ] **Step 6: Lint**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/obs_ws.py tests/test_obsws.py
git commit -m "fix(obs): clean obs-websocket closing handshake (1000, not 1006)"
```

---

## Self-Review

**Spec coverage:**
- Send status-1000 close frame → Task 1 Step 4 + test `t_close_sends_status_1000_*`. ✅
- `shutdown(SHUT_WR)` before close → Step 4 + same test asserts order. ✅
- Bounded drain via `CLOSE_DRAIN_TIMEOUT_S` → Step 3 + Step 4 + tests `t_close_returns_on_echo_then_eof` / `t_close_does_not_hang_on_silent_socket`. ✅
- Never raises / safe after OBS dropped socket → Step 4 try/except + test `t_close_safe_when_obs_already_dropped_socket`. ✅
- Connection count / callers unchanged → only `close()` + constant touched. ✅
- Manual live-OBS verification → documented in the PR (not a code task). ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type/name consistency:** `CLOSE_DRAIN_TIMEOUT_S`, `_Session.close`, `encode_frame(..., opcode=0x8)`, `struct.pack(">H", 1000)`, `socket.SHUT_WR` used consistently across the rewrite and the tests. The test helper `_unmask_client_frame` mirrors the masking in `encode_frame`. ✅
