# obs-websocket Clean Close — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming)
**Component:** `src/scripts/obs_ws.py` (`_Session.close`)

## Problem

A real ~10-day OBS Studio session logged **40 443** abnormal obs-websocket
disconnects (`disconnected with code 1006 and reason: End of File`) against only
4 557 clean ones (code 1000). One abnormal disconnect roughly every ~20 s.

Root cause is a racecast action. `_Session.close()`
(`src/scripts/obs_ws.py:342`) sends a close frame with an **empty payload** (no
status code) and then **immediately** calls `sock.close()` without waiting for
OBS's close-frame echo:

```python
def close(self):
    try:
        self.sock.sendall(encode_frame(b"", opcode=0x8))   # polite close
    except OSError:
        pass
    self.sock.close()
```

Because the TCP socket is closed before OBS reads the close frame, OBS sees an
EOF instead of a completed close handshake and records code 1006 ("End of
File"). Since racecast never sends a status code, essentially all 40 443 1006
disconnects are racecast's. The cadence is driven mainly by the **program
monitor** `get_program_screenshot` (`racecast-feeds.py:4831`), which opens a
fresh obs-websocket session on every cockpit/director-panel/race-control poll and
tears it down via this dirty close (plus `reflect_feed_state`, scene-item
toggles, and `get_health_stats`).

The disconnects are not functionally harmful — OBS handles the reconnects — but
they flood OBS's log and the Control Center's OBS log source, where they can mask
a genuine obs-websocket problem.

## Goal

`_Session.close()` performs a proper RFC 6455 closing handshake so OBS records a
clean code-1000 close. The change stays **best-effort**: `close()` never raises
and never blocks indefinitely, exactly like today.

## Non-goals (out of scope)

- The **number** of connections is unchanged: the program monitor keeps
  connecting per poll. OBS handles that volume fine; only the dirty close is the
  defect. (Reusing a persistent connection was considered and explicitly
  deferred — larger change to the stateless best-effort obs_ws, more risk.)
- No change to `_open_session`, the request paths, or any caller's best-effort
  `(names, note)` contract.

## Design

Rewrite `_Session.close()` to:

1. **Send a close frame with status code 1000:**
   `self.sock.sendall(encode_frame(struct.pack(">H", 1000), opcode=0x8))`
   (a 2-byte big-endian status payload instead of the empty body).
2. **Drain briefly:** set a short socket timeout (`CLOSE_DRAIN_TIMEOUT_S = 1.0`)
   and `recv()` in a loop, discarding bytes, until OBS's close echo / EOF /
   timeout. This lets OBS send its close echo and close the TCP first, which is
   what turns 1006 into 1000. The drain reads raw bytes (it does NOT go through
   `next_json`, which would raise on the close frame).
3. **Close the socket:** `self.sock.close()`.

**Do NOT `shutdown(SHUT_WR)`.** An earlier design half-closed the write side after
the close frame; this was **verified to FAIL against a live OBS** — sending a TCP
FIN right after the close frame makes OBS's WebSocket server (websocketpp) log the
disconnect as **1006 / "End of File"** instead of 1000. Empirically, the close
frame followed by a plain drain-to-EOF (no FIN) yields a clean 1000; the FIN
variant yields 1006 every time. So we send the close frame and let the server
finish the handshake (send its echo, close the TCP) while we read to EOF, then
close. This is exactly the kind of behavior the unit tests (a fake socket) cannot
see and only the manual live-OBS check catches — see Manual verification.

Every step is wrapped so any `OSError`/`socket.timeout` is swallowed — a slow or
dead OBS hits the 1 s timeout and we still close. `close()` must remain safe to
call after OBS already dropped the socket (the current contract).

New module constant near the other timing/config constants:

```python
CLOSE_DRAIN_TIMEOUT_S = 1.0   # max seconds to wait for OBS's close echo before closing the socket
```

### Why this removes the 1006s

OBS now receives a complete close frame carrying code 1000 and gets a brief
window (the drain) to finish its half of the handshake before the TCP socket
closes, so it logs a normal 1000 close instead of an abnormal 1006 / EOF.

## Error handling

- `sendall`, the drain loop, and `close` each tolerate `OSError`
  (OBS may have closed first). The method never propagates an exception.
- The drain loop is bounded by `CLOSE_DRAIN_TIMEOUT_S` via `settimeout`, so
  `close()` cannot hang on an unresponsive OBS. A single bounded read loop, not a
  retry storm.

## Testing

`tests/test_obsws.py`. The existing tests fake at the **session** level
(`_FakeSession`); `close()` operates on `self.sock`, so the tests introduce a
minimal **fake socket** and build a real `m._Session(fake_sock, b"")`:

- **Close frame carries status 1000:** a fake socket records `sendall` bytes; after
  `close()`, decode the recorded client frame — opcode `0x8`, and the unmasked
  2-byte payload equals `struct.pack(">H", 1000)`.
- **No `shutdown(SHUT_WR)` (regression guard):** assert `"shutdown"` is NOT in the
  fake's recorded calls — the early FIN is the exact bug that produced 1006, so a
  test pins it out. Also assert `settimeout` precedes the first `recv` (the no-hang
  guarantee).
- **Clean return on echo + EOF:** a fake whose `recv` returns a close-frame echo
  then `b""` — `close()` returns without raising and calls `sock.close()`.
- **No hang on a silent socket:** a fake whose `recv` raises `socket.timeout`
  (simulating the drain timeout) — `close()` still returns and closes; it does not
  loop forever or raise.
- **Safe after OBS already dropped the socket:** a fake whose `sendall`
  raises `OSError` — `close()` swallows it and still calls `sock.close()`.

The fake socket implements only `sendall`, `recv`, `shutdown`, `settimeout`, and
`close`, each recording its invocation. (`shutdown` is recorded so the regression
guard can assert it is never called.)

**Important — why the live check is mandatory:** the unit tests use a fake socket
that cannot model OBS's websocketpp FIN-handling, so they pass for BOTH the
correct (no-FIN) and the broken (FIN) variants. The 1006→1000 difference is only
observable against a real OBS. The first implementation shipped the FIN variant
and passed all unit tests + code review; the manual live-OBS run caught it. The
live verification is therefore a required gate, not a courtesy.

## Manual verification (PR note)

CI has no OBS, so the 1006→1000 change can only be confirmed against a live OBS:
drive `get_program_screenshot` in a loop (or open a cockpit/panel), then grep the
OBS log for `disconnected with code` and confirm new disconnects are `1000`, not
`1006`.

**Result (2026-06-24, live OBS):** 15 real `get_program_screenshot` cycles produced
**16× code 1000 and 0× 1006**. The same harness on the FIN variant produced
**8× 1006**; dropping the `shutdown(SHUT_WR)` is what fixed it. Confirmed.

## Files

- Modify: `src/scripts/obs_ws.py` — `CLOSE_DRAIN_TIMEOUT_S` constant + `_Session.close()` rewrite.
- Test: `tests/test_obsws.py` — fake-socket close tests.
