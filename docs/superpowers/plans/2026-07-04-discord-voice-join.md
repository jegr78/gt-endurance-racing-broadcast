# Discord Voice-Channel Join (RPC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Discord desktop client join a league's voice channel from racecast (CLI + Control Center) so OBS's PipeWire capture picks up the audio — a fully hands-free cloud producer, and a one-click convenience for local producers.

**Architecture:** A pure stdlib module `src/scripts/discord_rpc.py` (socket-path resolution, RPC frame codec, message builders, channel-link parser, Sheet→env target resolver, token-cache logic) behind injected seams; a thin `DiscordVoiceClient` ties it to a real IPC socket + `http_util` OAuth token exchange + gviz Sheet fetch. `racecast discord join|leave|status` drives it; `event start` auto-joins (default on). A Control Center button rides the existing op→job machinery. Feasibility is proven live (see `docs/superpowers/specs/2026-07-04-discord-voice-join-design.md`).

**Tech Stack:** Python 3 stdlib only (`socket`, `struct`, `json`, `csv`, `urllib` via `http_util`). No new dependencies.

## Global Constraints

- **English only** for all shipped code, comments, docs.
- **Edit only under `src/`** for shipped code (plus `tests/`, `docs/superpowers/`).
- **The client_secret and tokens never get logged, printed, or returned** in any user-facing path. The token cache is gitignored runtime state.
- **All outbound HTTP goes through `src/scripts/http_util.py`** (UA guard) — the token exchange/refresh use `http_util.open_url(...)`; the gviz Sheet fetch uses `http_util.get_bytes(...)`. Never bare `urllib`.
- **Proven RPC recipe (do not change):** handshake `{v:1,client_id}` → AUTHORIZE `{client_id,scopes:["rpc"]}` → token exchange `POST https://discord.com/api/oauth2/token` with `redirect_uri=http://localhost` → AUTHENTICATE `{access_token}` → `SELECT_VOICE_CHANNEL {channel_id,force:true}` (leave = `channel_id:null`). Frame = `<int32-LE op><int32-LE len><json>`. Opcodes: handshake=0, frame=1.
- **rpc scope works because the account owns the app** — reuse the per-league `DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`; the app needs `http://localhost` registered as an OAuth redirect (one-time, documented).
- **Config:** voice target = Sheet `Configuration` tab header `Discord Voice` (override) → `profile.env` `DISCORD_VOICE_URL` (fallback). Value form: `https://discord.com/channels/<guild>/<channel>`.
- **Auto-join on `event start` is default ON**; kill-switch `RACECAST_DISCORD_AUTOJOIN=0` (machine `.env`). Best-effort, never fatal.
- **Tests: stdlib only, Windows-safe.** Test files are runnable scripts using `t_*` functions and the `for name, fn in sorted(globals().items())` runner. A fixed-OS absolute path (the Windows named pipe) is a literal string, never built with `os.path.join`. No real network / no real Discord — everything behind seams.
- **CodeQL:** never test host membership with `"discord.com" in url`; parse structurally (`.find("/channels/")` + digit checks).

---

### Task 1: Pure RPC core — socket candidates, frame codec, message builders, channel parser

**Files:**
- Create: `src/scripts/discord_rpc.py`
- Test: `tests/test_discord_rpc.py`

**Interfaces:**
- Produces: `ipc_candidates(os_name, env) -> list[str]`; `encode_frame(op:int, payload:dict) -> bytes`; `frame_header(buf8:bytes) -> (op:int, length:int)`; `msg_handshake(client_id) -> (0, dict)`; `msg_authorize(client_id) -> (1, dict)`; `msg_authenticate(token) -> (1, dict)`; `msg_select_voice(channel_id) -> (1, dict)`; `msg_leave() -> (1, dict)`; `parse_channel_link(link:str) -> (guild:str, channel:str) | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_discord_rpc.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_discord_rpc.py`
Expected: FAIL — `No module named 'discord_rpc'` / `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/discord_rpc.py`:

```python
#!/usr/bin/env python3
"""Discord voice-channel join via the local desktop-client RPC IPC socket.

Pure helpers (socket-path candidates, frame codec, message builders, the
channel-link parser, the Sheet->env target resolver, and token-cache logic) plus
a thin DiscordVoiceClient that ties them to a real socket + http_util OAuth token
exchange. The desktop client is driven so its audio plays on the machine's audio
device, where OBS's PipeWire plugin captures it. Feasibility proven live — see
docs/superpowers/specs/2026-07-04-discord-voice-join-design.md.

Secrets (client_secret, tokens) are never logged, printed, or returned."""
import csv
import io
import json
import os
import struct

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
TOKEN_URL = "https://discord.com/api/oauth2/token"
REDIRECT_URI = "http://localhost"
CONFIG_TAB = "Configuration"
VOICE_HEADER = "Discord Voice"


def ipc_candidates(os_name, env):
    """Ordered IPC endpoints where a running Discord client may listen.
    Windows uses a fixed named-pipe string (NOT os.path.join — that would inject
    backslashes wrongly and is meaningless for a pipe); POSIX joins the runtime
    bases with the socket name (incl. snap/flatpak subdirs)."""
    if os_name == "nt":
        return [r"\\?\pipe\discord-ipc-{}".format(n) for n in range(10)]
    bases = [env.get(k) for k in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")]
    bases = [b for b in bases if b] + ["/tmp"]
    out = []
    for base in bases:
        for sub in ("", "app/com.discordapp.Discord/", "snap.discord/"):
            for n in range(10):
                out.append(os.path.join(base, sub, "discord-ipc-{}".format(n)))
    return out


def encode_frame(op, payload):
    data = json.dumps(payload).encode("utf-8")
    return struct.pack("<II", op, len(data)) + data


def frame_header(buf8):
    """(opcode, payload_length) from a frame's first 8 bytes (little-endian)."""
    return struct.unpack("<II", buf8)


def msg_handshake(client_id):
    return OP_HANDSHAKE, {"v": 1, "client_id": str(client_id)}


def msg_authorize(client_id):
    return OP_FRAME, {"cmd": "AUTHORIZE",
                      "args": {"client_id": str(client_id), "scopes": ["rpc"]},
                      "nonce": "authorize"}


def msg_authenticate(access_token):
    return OP_FRAME, {"cmd": "AUTHENTICATE",
                      "args": {"access_token": access_token}, "nonce": "authenticate"}


def msg_select_voice(channel_id):
    return OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL",
                      "args": {"channel_id": str(channel_id), "force": True},
                      "nonce": "select-voice"}


def msg_leave():
    return OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL",
                      "args": {"channel_id": None, "force": True}, "nonce": "leave"}


def parse_channel_link(link):
    """'https://discord.com/channels/<guild>/<channel>' (or discord://) ->
    (guild, channel) of digit strings, else None. Structural parse — no host
    substring check (CodeQL py/incomplete-url-substring-sanitization)."""
    if not link:
        return None
    marker = "/channels/"
    i = str(link).find(marker)
    if i < 0:
        return None
    parts = str(link)[i + len(marker):].strip("/").split("/")
    if len(parts) < 2:
        return None
    guild, channel = parts[0], parts[1]
    if guild.isdigit() and channel.isdigit():
        return guild, channel
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_discord_rpc.py`
Expected: `ok t_...` for all five, then `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/discord_rpc.py tests/test_discord_rpc.py
git commit -m "feat(discord): pure RPC core — socket candidates, frame codec, message builders, link parser"
```

---

### Task 2: Pure target resolver, CSV extractor, token-cache logic

**Files:**
- Modify: `src/scripts/discord_rpc.py` (append functions)
- Test: `tests/test_discord_rpc.py` (append tests)

**Interfaces:**
- Consumes: `parse_channel_link` (Task 1).
- Produces: `resolve_voice_target(sheet_value, env_value) -> (guild, channel) | None`; `discord_voice_from_csv(csv_text) -> str`; `token_valid(cache, now, skew=60) -> bool`; `needs_refresh(cache, now, skew=60) -> bool`; `store_token(resp, now) -> dict`; `token_exchange_body(cid, secret, code) -> dict`; `token_refresh_body(cid, secret, refresh_token) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discord_rpc.py` (before the `if __name__` block):

```python
def t_discord_voice_from_csv():
    csv_text = ('"Stints","Cue Preset","Discord Voice"\r\n'
                '"Stint 1","Formation Lap",""\r\n'
                '"Stint 2","","https://discord.com/channels/1/2"\r\n')
    assert m.discord_voice_from_csv(csv_text) == "https://discord.com/channels/1/2"
    assert m.discord_voice_from_csv('"A","B"\r\n"x","y"\r\n') == ""   # header absent
    assert m.discord_voice_from_csv("") == ""


def t_resolve_voice_target_override_then_fallback():
    sheet = "https://discord.com/channels/11/22"
    env = "https://discord.com/channels/33/44"
    assert m.resolve_voice_target(sheet, env) == ("11", "22")   # sheet wins
    assert m.resolve_voice_target("", env) == ("33", "44")      # fall back to env
    assert m.resolve_voice_target("garbage", env) == ("33", "44")   # bad sheet -> env
    assert m.resolve_voice_target("", "") is None


def t_token_cache_logic():
    fresh = {"access_token": "a", "expires_at": 1000, "refresh_token": "r"}
    assert m.token_valid(fresh, now=900) is True
    assert m.token_valid(fresh, now=999) is False          # inside the 60s skew
    assert m.token_valid({}, now=0) is False
    expired = {"access_token": "a", "expires_at": 100, "refresh_token": "r"}
    assert m.needs_refresh(expired, now=900) is True
    assert m.needs_refresh({"access_token": "a", "expires_at": 100}, now=900) is False  # no refresh token


def t_store_token_absolute_expiry():
    resp = {"access_token": "a", "refresh_token": "r", "expires_in": 604800, "scope": "rpc identify"}
    cache = m.store_token(resp, now=1000)
    assert cache["access_token"] == "a" and cache["refresh_token"] == "r"
    assert cache["expires_at"] == 1000 + 604800


def t_oauth_bodies():
    ex = m.token_exchange_body("cid", "sec", "code")
    assert ex["grant_type"] == "authorization_code" and ex["redirect_uri"] == "http://localhost"
    assert ex["code"] == "code" and ex["client_secret"] == "sec"
    rf = m.token_refresh_body("cid", "sec", "rtok")
    assert rf["grant_type"] == "refresh_token" and rf["refresh_token"] == "rtok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_discord_rpc.py`
Expected: FAIL — `AttributeError: module 'discord_rpc' has no attribute 'discord_voice_from_csv'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/discord_rpc.py`:

```python
def discord_voice_from_csv(csv_text):
    """First non-empty `Discord Voice` cell from the Configuration-tab CSV, or ''."""
    rows = list(csv.reader(io.StringIO(csv_text or "")))
    if not rows:
        return ""
    try:
        idx = rows[0].index(VOICE_HEADER)
    except ValueError:
        return ""
    for row in rows[1:]:
        if idx < len(row) and row[idx].strip():
            return row[idx].strip()
    return ""


def resolve_voice_target(sheet_value, env_value):
    """Sheet override wins; else the profile.env fallback. (guild, channel) | None."""
    for value in (sheet_value, env_value):
        target = parse_channel_link(value)
        if target:
            return target
    return None


def token_valid(cache, now, skew=60):
    tok, exp = cache.get("access_token"), cache.get("expires_at")
    return bool(tok) and isinstance(exp, (int, float)) and now < exp - skew


def needs_refresh(cache, now, skew=60):
    return (not token_valid(cache, now, skew)) and bool(cache.get("refresh_token"))


def store_token(resp, now):
    """OAuth token response -> cache dict with an ABSOLUTE expiry."""
    return {"access_token": resp.get("access_token"),
            "refresh_token": resp.get("refresh_token"),
            "expires_at": now + int(resp.get("expires_in", 0)),
            "scope": resp.get("scope", "")}


def token_exchange_body(client_id, client_secret, code):
    return {"client_id": client_id, "client_secret": client_secret,
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI}


def token_refresh_body(client_id, client_secret, refresh_token):
    return {"client_id": client_id, "client_secret": client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_discord_rpc.py`
Expected: all `ok t_...`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/discord_rpc.py tests/test_discord_rpc.py
git commit -m "feat(discord): pure target resolver, CSV extractor, token-cache logic"
```

---

### Task 3: DiscordVoiceClient (IPC + OAuth flow) with seams

**Files:**
- Modify: `src/scripts/discord_rpc.py` (append the client + token-cache file I/O)
- Test: `tests/test_discord_rpc.py` (append seam-based tests)

**Interfaces:**
- Consumes: all Task 1/2 pure helpers, `http_util.open_url`, `http_util.get_bytes`.
- Produces: `load_cache(path) -> dict`; `save_cache(path, cache) -> None`; `class DiscordVoiceClient(client_id, client_secret, cache_path, *, connect=None, http_post_form=None, now=None)` with `.join(guild, channel) -> (ok:bool, note:str)`, `.leave() -> (ok, note)`. `connect(endpoint) -> conn` where `conn` has `.sendall(bytes)`, `.recv(n)->bytes`, `.close()`. `http_post_form(url, form:dict) -> dict` (parsed JSON). `now() -> float`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discord_rpc.py`:

```python
def _fake_conn(script):
    """A conn whose recv() replays pre-encoded frames; records sent payloads."""
    class C:
        def __init__(self):
            self.sent = []
            self._buf = b"".join(m.encode_frame(op, p) for op, p in script)
        def sendall(self, data):
            # decode what the client sent so the test can assert on it
            op, length = m.frame_header(data[:8])
            self.sent.append((op, json.loads(data[8:8 + length])))
        def recv(self, n):
            chunk, self._buf = self._buf[:n], self._buf[n:]
            return chunk
        def close(self):
            pass
    return C()


def t_client_join_with_cached_token(tmp=None):
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "tok.json")
    m.save_cache(path, {"access_token": "a", "expires_at": 10_000, "refresh_token": "r"})
    # server frames: READY, AUTHENTICATE ok, SELECT_VOICE_CHANNEL ok
    script = [(m.OP_FRAME, {"evt": "READY", "data": {"user": {"username": "box"}}}),
              (m.OP_FRAME, {"cmd": "AUTHENTICATE", "data": {"user": {"username": "box"}}}),
              (m.OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL", "data": {"name": "General"}})]
    conn = _fake_conn(script)
    posted = []
    cli = m.DiscordVoiceClient(
        "cid", "sec", path,
        connect=lambda ep: conn, endpoints=["fake-ep"],
        http_post_form=lambda url, form: posted.append((url, form)) or {},
        now=lambda: 5000)
    ok, note = cli.join("11", "22")
    assert ok is True and "General" in note
    assert posted == []                                   # cached token -> no token endpoint call
    cmds = [p.get("cmd") for _, p in conn.sent if p.get("cmd")]
    assert cmds == ["AUTHENTICATE", "SELECT_VOICE_CHANNEL"]   # no AUTHORIZE when cached


def t_client_refreshes_expired_token():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "tok.json")
    m.save_cache(path, {"access_token": "old", "expires_at": 100, "refresh_token": "r"})
    script = [(m.OP_FRAME, {"evt": "READY", "data": {}}),
              (m.OP_FRAME, {"cmd": "AUTHENTICATE", "data": {"user": {}}}),
              (m.OP_FRAME, {"cmd": "SELECT_VOICE_CHANNEL", "data": {"name": "GT"}})]
    def post(url, form):
        assert form["grant_type"] == "refresh_token"       # refresh, not authorize
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 604800}
    cli = m.DiscordVoiceClient("cid", "sec", path,
                               connect=lambda ep: _fake_conn(script), endpoints=["fake-ep"],
                               http_post_form=post, now=lambda: 9000)
    ok, _ = cli.join("11", "22")
    assert ok is True
    assert m.load_cache(path)["access_token"] == "new"     # cache updated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_discord_rpc.py`
Expected: FAIL — `AttributeError: ... 'DiscordVoiceClient'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/discord_rpc.py` (top: add `import time`, `import socket`, `import http_util` to the import block):

```python
def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, cache):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)


class _PipeConn:
    """Windows named-pipe wrapper exposing the same sendall/recv/close as a socket."""
    def __init__(self, path):
        self._f = open(path, "r+b", buffering=0)
    def sendall(self, data):
        self._f.write(data); self._f.flush()
    def recv(self, n):
        return self._f.read(n)
    def close(self):
        try:
            self._f.close()
        except OSError:
            pass


def _default_connect(endpoint):
    if os.name == "nt":
        return _PipeConn(endpoint)              # \\?\pipe\discord-ipc-N
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(endpoint)
    return sock


def _default_post_form(url, form):
    import urllib.parse
    body = urllib.parse.urlencode(form).encode("utf-8")
    raw = http_util.open_url(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"}).read()
    return json.loads(raw.decode("utf-8"))


class DiscordVoiceClient:
    """Drives the local Discord desktop client into/out of a voice channel.
    Every failure path returns (False, note) — never raises to the caller."""

    def __init__(self, client_id, client_secret, cache_path,
                 *, connect=None, http_post_form=None, now=None, endpoints=None):
        self.cid, self.sec, self.cache_path = client_id, client_secret, cache_path
        self._connect = connect or _default_connect
        self._post = http_post_form or _default_post_form
        self._now = now or time.time
        self._endpoints_override = endpoints        # tests inject a fake list

    def _endpoints(self):
        """Candidate IPC endpoints to try. POSIX filters to existing sockets;
        Windows keeps every pipe path (existence isn't reliably checkable) and
        the connect attempt in _open picks the one that opens."""
        if self._endpoints_override is not None:
            return self._endpoints_override
        cands = ipc_candidates(os.name, os.environ)
        if os.name == "nt":
            return cands
        return [c for c in cands if os.path.exists(c)]

    def _open(self):
        """First endpoint that actually connects, or (None, None)."""
        for ep in self._endpoints():
            try:
                return self._connect(ep), ep
            except OSError:
                continue
        return None, None

    def _read_frame(self, conn):
        head = b""
        while len(head) < 8:
            head += conn.recv(8 - len(head))
        op, length = frame_header(head)
        body = b""
        while len(body) < length:
            body += conn.recv(length - len(body))
        return op, (json.loads(body) if body else {})

    def _send(self, conn, msg):
        conn.sendall(encode_frame(*msg))

    def _access_token(self, conn):
        """Return a usable access token, doing the cheapest of: cached / refresh /
        full AUTHORIZE. Raises RuntimeError with a friendly message on failure."""
        cache = load_cache(self.cache_path)
        now = self._now()
        if token_valid(cache, now):
            return cache["access_token"]
        if needs_refresh(cache, now):
            resp = self._post(TOKEN_URL, token_refresh_body(self.cid, self.sec, cache["refresh_token"]))
            if resp.get("access_token"):
                save_cache(self.cache_path, store_token(resp, self._now()))
                return resp["access_token"]
        # Full consent flow (first run / refresh failed): AUTHORIZE over the socket.
        self._send(conn, msg_authorize(self.cid))
        _op, msg = self._read_frame(conn)
        code = (msg.get("data") or {}).get("code")
        if not code:
            raise RuntimeError("Discord authorization was declined or timed out")
        resp = self._post(TOKEN_URL, token_exchange_body(self.cid, self.sec, code))
        if not resp.get("access_token"):
            raise RuntimeError("token exchange failed (check the app's http://localhost redirect)")
        save_cache(self.cache_path, store_token(resp, self._now()))
        return resp["access_token"]

    def _run(self, action_msg, ok_note):
        conn, endpoint = self._open()
        if conn is None:
            return False, "Discord desktop app is not running (no IPC socket)"
        try:
            self._send(conn, msg_handshake(self.cid))
            _op, ready = self._read_frame(conn)
            if ready.get("evt") != "READY":
                return False, "Discord did not accept the client id"
            token = self._access_token(conn)
            self._send(conn, msg_authenticate(token))
            self._read_frame(conn)
            self._send(conn, action_msg)
            _op, res = self._read_frame(conn)
            if res.get("evt") == "ERROR":
                return False, str((res.get("data") or {}).get("message", "voice command failed"))
            name = (res.get("data") or {}).get("name")
            return True, ok_note(name)
        except (OSError, RuntimeError, ValueError) as exc:
            return False, str(exc)
        finally:
            if conn is not None:
                conn.close()

    def join(self, guild, channel):
        return self._run(msg_select_voice(channel),
                         lambda name: "joined voice channel " + (name or channel))

    def leave(self):
        return self._run(msg_leave(), lambda name: "left the voice channel")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_discord_rpc.py`
Expected: all `ok`, `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/discord_rpc.py tests/test_discord_rpc.py
git commit -m "feat(discord): DiscordVoiceClient — IPC handshake/authorize/authenticate/select-voice with token cache"
```

---

### Task 4: config field, env injection, and `racecast discord join|leave|status`

**Files:**
- Modify: `src/scripts/config.py` (add `discord_voice_url`)
- Modify: `src/racecast.py` (env injection + `discord` command)
- Test: `tests/test_config.py` (assert the new field parses), `tests/test_racecast.py` (assert the command routes)

**Interfaces:**
- Consumes: `discord_rpc.DiscordVoiceClient`, `discord_rpc.resolve_voice_target`, `discord_rpc.discord_voice_from_csv`, `http_util.get_bytes`.
- Produces: CLI `racecast discord join|leave|status`; `ResolvedConfig.discord_voice_url`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` a check that `DISCORD_VOICE_URL` is parsed (follow that file's existing profile-fixture pattern — locate an existing test that builds a temp `profile.env`, copy its structure, add the line `DISCORD_VOICE_URL=https://discord.com/channels/1/2` and assert `rc.discord_voice_url == "https://discord.com/channels/1/2"`).

Append to `tests/test_racecast.py` (follow its existing command-routing pattern):

```python
def t_discord_command_routes_join(monkeypatch=None):
    import types
    calls = {}
    R.dc_join = lambda: calls.setdefault("join", True) or 0   # see impl for the seam name
    # The real assertion mirrors how other commands are tested in this file: call
    # R.main(["discord", "join"]) with the client stubbed and assert it dispatched.
```

> Implementer note: match the *actual* routing-test idiom already in `tests/test_racecast.py` (it stubs at a seam and calls `main`). Assert that `main(["discord","join"])`, `["discord","leave"]`, and `["discord","status"]` each reach the right branch, and that an unknown verb prints the usage string.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_config.py` then `python3 tests/test_racecast.py`
Expected: FAIL — missing `discord_voice_url` / unknown command `discord`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/config.py`, next to the other Discord fields (the `@dataclass` field list near `discord_client_secret` and the constructor near `discord_client_id=prof.get(...)`):

```python
    discord_voice_url: str = ""      # league voice channel (fallback; Sheet override wins)
```
```python
        discord_voice_url=prof.get("DISCORD_VOICE_URL", ""),
```

In `src/racecast.py` `_profile_env_vars`, add to the `pairs` tuple:

```python
             ("RACECAST_DISCORD_VOICE_URL", rc.discord_voice_url),
```

Add the command implementation (near `report_cmd`, and register it in `main`'s dispatch exactly like the other verbs are registered):

```python
def _discord_voice_client():
    """Build a DiscordVoiceClient from the active profile's env, or exit with a hint."""
    import discord_rpc
    cid = os.environ.get("RACECAST_DISCORD_CLIENT_ID", "")
    sec = os.environ.get("RACECAST_DISCORD_CLIENT_SECRET", "")
    if not cid or not sec:
        sys.exit("racecast: this league has no DISCORD_CLIENT_ID/SECRET in profile.env")
    cache = os.path.join(_runtime_dir(), "discord-rpc-token.json")
    return discord_rpc.DiscordVoiceClient(cid, sec, cache)


def _discord_voice_target():
    """(guild, channel) from the Sheet `Discord Voice` override then the env fallback."""
    import discord_rpc
    sheet_val = ""
    sid = os.environ.get("RACECAST_SHEET_ID", "")
    if sid:
        from urllib.parse import quote
        url = ("https://docs.google.com/spreadsheets/d/{}/gviz/tq?tqx=out:csv&sheet={}"
               .format(sid, quote(discord_rpc.CONFIG_TAB)))
        try:
            sheet_val = discord_rpc.discord_voice_from_csv(
                http_util.get_bytes(url, timeout=15).decode("utf-8"))
        except Exception:  # noqa: BLE001 — Sheet unreachable -> fall back to env
            sheet_val = ""
    return discord_rpc.resolve_voice_target(
        sheet_val, os.environ.get("RACECAST_DISCORD_VOICE_URL", ""))


def discord_cmd(rest):
    """`racecast discord join|leave|status` — drive the desktop client's voice channel."""
    verb = rest[0] if rest else "status"
    if verb not in ("join", "leave", "status"):
        sys.exit("usage: racecast discord {join|leave|status}")
    client = _discord_voice_client()
    if verb == "leave":
        ok, note = client.leave()
        print("discord: " + note)
        return 0 if ok else 1
    target = _discord_voice_target()
    if verb == "status":
        print("discord voice target: " + ("#".join(target) if target else "none configured"))
        return 0
    if not target:
        sys.exit("racecast: no voice channel configured (Sheet `Discord Voice` or DISCORD_VOICE_URL)")
    ok, note = client.join(*target)
    print("discord: " + note)
    return 0 if ok else 1
```

Register `discord` in `main`'s command table alongside the existing verbs (mirror how `report` / `app` are wired), routing to `discord_cmd(rest)`. Add a `racecast discord …` usage line to the top-of-file help banner near the existing `racecast app …` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_config.py && python3 tests/test_racecast.py && python3 tests/test_discord_rpc.py`
Expected: `ALL PASS` for each.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/config.py src/racecast.py tests/test_config.py tests/test_racecast.py
git commit -m "feat(discord): config discord_voice_url + racecast discord join|leave|status"
```

---

### Task 5: Auto-join on `event start` (default on, kill-switch)

**Files:**
- Modify: `src/racecast.py` (call the join best-effort at the end of `event start`)
- Test: `tests/test_racecast.py` (auto-join gate helper)

**Interfaces:**
- Consumes: `discord_cmd` internals (`_discord_voice_client`, `_discord_voice_target`).
- Produces: `_discord_autojoin_enabled(env) -> bool`; a best-effort call in `event_start`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py`:

```python
def t_discord_autojoin_gate():
    assert R._discord_autojoin_enabled({}) is True                       # default on
    assert R._discord_autojoin_enabled({"RACECAST_DISCORD_AUTOJOIN": "0"}) is False
    assert R._discord_autojoin_enabled({"RACECAST_DISCORD_AUTOJOIN": "1"}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — no `_discord_autojoin_enabled`.

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py`:

```python
def _discord_autojoin_enabled(env):
    """Auto-join is default-on; RACECAST_DISCORD_AUTOJOIN=0 disables it."""
    return env.get("RACECAST_DISCORD_AUTOJOIN", "1") != "0"


def _discord_autojoin():
    """Best-effort voice join during event start — never fatal, secrets stay quiet."""
    if not _discord_autojoin_enabled(os.environ):
        return
    if not (os.environ.get("RACECAST_DISCORD_CLIENT_ID") and
            os.environ.get("RACECAST_DISCORD_CLIENT_SECRET")):
        return
    try:
        target = _discord_voice_target()
        if not target:
            return
        client = _discord_voice_client()
        ok, note = client.join(*target)
        print("discord: " + note if ok
              else "discord: voice auto-join skipped — " + note
              + " (run `racecast discord join` once to consent)")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — auto-join must never break event start
        print("discord: voice auto-join skipped ({})".format(type(exc).__name__))
```

Call `_discord_autojoin()` at the end of the `event start` success path (after the relay/OBS/Companion bring-up, before the final status print). Guard it so it runs only for `event start`, not `event takeover`/`stop`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(discord): auto-join voice on event start (default on, RACECAST_DISCORD_AUTOJOIN=0 kills it)"
```

---

### Task 6: Control Center Join/Leave-voice buttons

**Files:**
- Modify: `src/ui/ui_ops.py` (two OPS entries)
- Modify: `src/ui/control-center.html` (two buttons next to the Discord launch/quit controls)
- Modify: `src/docs/wiki/images/cc-*.png` (refresh the affected Control Center view screenshot)
- Test: `tests/test_ui_ops.py` (assert the new ops resolve to the right argv)

**Interfaces:**
- Consumes: `racecast discord join|leave` (Task 4).
- Produces: OPS `discord-voice-join` / `discord-voice-leave`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_ops.py` (match its existing OPS assertion idiom):

```python
def t_discord_voice_ops():
    assert m.OPS["discord-voice-join"] == ["discord", "join"]
    assert m.OPS["discord-voice-leave"] == ["discord", "leave"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL — `KeyError: 'discord-voice-join'`.

- [ ] **Step 3: Write minimal implementation**

In `src/ui/ui_ops.py` `OPS`, next to `discord-start`/`discord-stop`:

```python
    "discord-voice-join": ["discord", "join"],
    "discord-voice-leave": ["discord", "leave"],
```

In `src/ui/control-center.html`, add two buttons beside the existing Discord launch/quit buttons that trigger these ops (copy the exact markup/JS of an adjacent op button — e.g. the `discord-start` button — changing only the op id to `discord-voice-join` / `discord-voice-leave` and the label to `Join voice` / `Leave voice`). The op→job machinery already streams the command output; no new route is needed.

- [ ] **Step 4: Run test + visually verify**

Run: `python3 tests/test_ui_ops.py` → PASS.

Then follow the **ui-visual-verification** skill: serve the Control Center from a local dev build (`RACECAST_UI_PORT=<free> racecast ui --no-browser` from `src/`), screenshot the view with the new buttons, and confirm they match the sibling Discord buttons (theme, spacing, disabled/hover states). Record the marker:
`python3 .claude/hooks/record_ui_verified.py src/ui/control-center.html`

- [ ] **Step 5: Refresh the wiki screenshot + commit**

Regenerate the affected `src/docs/wiki/images/cc-*.png` (the Control Center view that now shows the buttons) per the **wiki-screenshots** skill, from the local dev build (no `VERSION` badge). Then:

```bash
python3 tools/lint.py
git add src/ui/ui_ops.py src/ui/control-center.html tests/test_ui_ops.py src/docs/wiki/images/
git commit -m "feat(discord): Control Center Join/Leave-voice buttons"
```

---

## Final verification (whole feature)

- [ ] `python3 tools/run-tests.py` — the whole suite green.
- [ ] `python3 tools/lint.py` — clean.
- [ ] `python3 tools/build.py` — the verify step passes (no secrets, tokenization intact).
- [ ] Update `docs/superpowers/specs/2026-07-04-discord-voice-join-design.md` status note if anything changed during implementation.
- [ ] Consider a short **Cloud-Producer** wiki addition (voice-join setup: register `http://localhost`, set the `Discord Voice` cell / `DISCORD_VOICE_URL`, first-run consent). Optional follow-up, not blocking.
