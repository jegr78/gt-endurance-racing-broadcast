"""Commentator-cockpit auth core (issue #191) — pure, stdlib-only, importable by
both the relay (src/relay/racecast-feeds.py) and the CLI (src/racecast.py) WITHOUT
importing the hyphenated relay module.

Token model (per the approved design):
    token = "<streamer_key>.<version>.<sig>"
    streamer_key = streamer_key(name)                 # URL-safe [a-z0-9-]
    sig = HMAC_SHA256(secret, "<streamer_key>:<version>") hex, truncated to 128 bits.
A valid signature IS proof the request is that streamer — no token->name map is stored.
Revocation is a per-streamer integer version (see cockpit_admin.py): a token whose
version is below the streamer's current version is rejected.
"""
import hashlib
import hmac
import re
import time
from http.cookies import SimpleCookie

COOKIE_NAME = "rc_cockpit"
_KEY_RE = re.compile(r"[a-z0-9-]+")


def streamer_key(s):
    """Normalize a streamer name to a URL-safe key. DUPLICATE of
    racecast-feeds.asset_key() — pinned byte-identical by a cross-check test in
    tests/test_cockpit.py (same idiom as STREAMLINK_TWITCH). Keep them in sync."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9-]", "", s)


def _sign(secret, key, version):
    msg = f"{key}:{version}".encode("utf-8")
    full = hmac.new((secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return full[:32]                       # 128-bit truncation -> shorter link


def mint_token(secret, key, version=1):
    """Build a signed token for an already-normalized streamer_key."""
    return f"{key}.{int(version)}.{_sign(secret, key, int(version))}"


def verify_token(secret, token, versions=None):
    """Return the streamer_key iff the token's signature is valid (constant-time)
    AND, when *versions* is given, its version is current. None on any failure.
    *versions* is the {streamer_key: current_version} dict (default 1 when absent)."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    key, ver_s, sig = parts
    if not key or not _KEY_RE.fullmatch(key):
        return None
    try:
        version = int(ver_s)
    except ValueError:
        return None
    expected = _sign(secret, key, version)
    if not hmac.compare_digest(sig, expected):
        return None
    if versions is not None and version < int(versions.get(key, 1)):
        return None
    return key


def parse_cookie_token(cookie_header):
    """Extract the rc_cockpit token from a raw Cookie header, or None. Pure."""
    if not cookie_header:
        return None
    try:
        jar = SimpleCookie()
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


class RateLimiter:
    """Fixed-window per-key counter (auth failures, chat sends). Time-injectable
    so tests are deterministic. Best-effort, in-process only."""

    def __init__(self, limit, window_s):
        self.limit = limit
        self.window_s = window_s
        self._hits = {}                    # key -> [window_start, count]

    def allow(self, key, now=None):
        now = time.time() if now is None else now
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window_s:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        return count <= self.limit
