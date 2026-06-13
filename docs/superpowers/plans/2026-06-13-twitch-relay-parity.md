# Twitch Relay Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Twitch feed as reliable and operable as a YouTube feed end-to-end — correct per-platform resolve strategy, working low-latency, a concrete authentication path, platform-aware panel/UX, and complete docs — without regressing the YouTube path.

**Architecture:** A new pure `platform_of(url)` helper splits the `Feed` pull loop per platform: YouTube keeps `yt-dlp -g` → `streamlink <hls>`; Twitch hands the `twitch.tv` URL straight to Streamlink so its Twitch plugin does resolution, automatic ad-filtering and low-latency. The YouTube branch additionally probes the resolved manifest for server-side ad (SSAI/DAI) markers and warns via `/status`. The cookie jar is renamed `cookies.txt` → `yt-cookies.txt` (legacy fallback + one-time migration), and a parallel Twitch OAuth path (`twitch-cookies.txt` → `--twitch-api-header`) is added with its own CLI and Control Center row.

**Tech Stack:** Pure Python 3 + stdlib (no pytest — each `tests/test_*.py` is a runnable script). External runtime tools: `yt-dlp`, `streamlink`. Lint via `python3 tools/lint.py`; build-verify via `python3 tools/build.py`.

**Reference spec:** `docs/superpowers/specs/2026-06-13-twitch-relay-parity-design.md`

**Key existing locations (read before starting):**
- `src/relay/racecast-feeds.py`: `_is_stream_url` (:366), `is_channel` (:388), `channel_url` (:951), `ytdlp_resolve_cmd` (:958), `streamlink_serve_cmd` (:969), `resolve_hls` (:976), `Feed.__init__` (:1474), `Feed.run` (:1541), `Relay.__init__` (:1596), `Relay.status` (:1625), `cookie_health` (:1991), `export_cookies` (:2020), cookie auto-detect in `main` (:2155-2171), constants `YTDLP_FORMAT`/`STREAMLINK_SERVE` (:86-88).
- `src/racecast.py`: `_cookies_path` (:495), `_relay_runtime_args` (:515), `ONESHOTS` (:601), `COOKIE_SCRIPTS`/routing (:1738, :1750), init wizard cookie gates (:2808-2870).
- `src/relay/get-cookies.py` (whole file).
- `src/scripts/preflight.py`: `cookies_status` (:235).
- `src/ui/ui_ops.py`: op registry (:30, :42, :84). `src/ui/control-center.html`: cookie row (:697-710).

**Per-task loop:** run the touched test file with `python3 tests/test_X.py`, then `python3 tools/lint.py`. After Phase 5: `python3 tools/build.py`.

---

## Phase 1 — Per-platform resolve dispatch (relay core)

### Task 1: `platform_of(url)` helper

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add after `is_channel`, ~:390)
- Test: `tests/test_platform.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_platform.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "relay"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "feeds", os.path.join(os.path.dirname(__file__), "..", "src", "relay", "racecast-feeds.py"))
feeds = importlib.util.module_from_spec(spec); spec.loader.exec_module(feeds)


def t_platform_of():
    assert feeds.platform_of("https://www.youtube.com/watch?v=abc") == "youtube"
    assert feeds.platform_of("https://youtu.be/abc") == "youtube"
    assert feeds.platform_of("https://www.twitch.tv/somechannel") == "twitch"
    assert feeds.platform_of("https://TWITCH.TV/Chan") == "twitch"      # case-insensitive
    assert feeds.platform_of("https://m.twitch.tv/chan") == "twitch"    # subdomain
    # bare UC id (channel_url turns it into a youtube URL) -> youtube
    assert feeds.platform_of("UC1234567890123456789012") == "youtube"
    # userinfo trick must NOT be seen as twitch
    assert feeds.platform_of("https://twitch.tv@evil.com/") == "youtube"


if __name__ == "__main__":
    t_platform_of(); print("ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL with `AttributeError: module 'feeds' has no attribute 'platform_of'`

- [ ] **Step 3: Write minimal implementation**

Add directly below `is_channel` (after :390) in `src/relay/racecast-feeds.py`:

```python
def platform_of(url):
    """Which streaming platform a (possibly bare-ID-wrapped) URL targets.
    Host-based, reusing the userinfo-safe parse from _is_stream_url. Anything
    that is not a Twitch host (including bare UC ids, which channel_url wraps
    into a youtube.com URL) is treated as YouTube — the default path."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return "twitch"
    return "youtube"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/racecast-feeds.py
git commit -m "feat(relay): platform_of() host-based platform detection (#105)"
```

---

### Task 2: Twitch-aware `streamlink_serve_cmd`

**Files:**
- Modify: `src/relay/racecast-feeds.py:88` (add `STREAMLINK_TWITCH`), `:969` (`streamlink_serve_cmd`)
- Test: `tests/test_platform.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_platform.py`:

```python
def t_serve_cmd_youtube():
    cmd = feeds.streamlink_serve_cmd("https://hls.example/x.m3u8", 53001)
    assert "--twitch-low-latency" not in cmd
    assert cmd[-2:] == ["https://hls.example/x.m3u8", "best"]
    assert "--" in cmd and cmd.index("--") < cmd.index("https://hls.example/x.m3u8")


def t_serve_cmd_twitch():
    cmd = feeds.streamlink_serve_cmd("https://www.twitch.tv/chan", 53002, platform="twitch")
    assert "--twitch-low-latency" in cmd
    assert "--twitch-disable-ads" not in cmd            # deprecated; ads filtered automatically
    assert cmd[cmd.index("--hls-live-edge") + 1] == "2"  # tighter than the default 4
    assert cmd[-2:] == ["https://www.twitch.tv/chan", "best"]


def t_serve_cmd_twitch_token():
    cmd = feeds.streamlink_serve_cmd("https://www.twitch.tv/chan", 53002,
                                     platform="twitch", twitch_token="abc123")
    i = cmd.index("--twitch-api-header")
    assert cmd[i + 1] == "Authorization=OAuth abc123"
    assert i < cmd.index("--")                          # header is an option, before the URL
```

Add these three to the `__main__` run line:
```python
    t_platform_of(); t_serve_cmd_youtube(); t_serve_cmd_twitch(); t_serve_cmd_twitch_token(); print("ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (`streamlink_serve_cmd` takes no `platform` kwarg)

- [ ] **Step 3: Write minimal implementation**

Add the Twitch flag set next to `STREAMLINK_SERVE` (:88):

```python
# Twitch is served DIRECTLY by Streamlink's twitch plugin (no yt-dlp hop), so its
# plugin options apply: low-latency prefetch + a tighter live edge. Ad filtering is
# automatic in current Streamlink (the old --twitch-disable-ads is deprecated).
STREAMLINK_TWITCH = ["--ringbuffer-size", "64M", "--hls-live-edge", "2", "--twitch-low-latency"]
```

Replace `streamlink_serve_cmd` (:969-973) with:

```python
def streamlink_serve_cmd(target, port, platform="youtube", twitch_token=None):
    """Argv for serving a stream to one OBS client. YouTube gets a resolved HLS
    URL (generic plugin); Twitch gets the twitch.tv URL itself so the Twitch
    plugin handles resolution, automatic ad-filtering and low-latency. `--`
    separates the positional URL/stream so neither can be parsed as a flag."""
    base = ["streamlink", "--player-external-http", "--player-external-http-port", str(port)]
    if platform == "twitch":
        base += STREAMLINK_TWITCH
        if twitch_token:
            base += ["--twitch-api-header", f"Authorization=OAuth {twitch_token}"]
    else:
        base += STREAMLINK_SERVE
    return base + ["--", target, "best"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/racecast-feeds.py
git commit -m "feat(relay): per-platform streamlink_serve_cmd with Twitch flags (#105)"
```

---

### Task 3: Branch the `Feed.run` pull loop per platform

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Feed.__init__` (:1474), `Feed.run` (:1541-1580), `Relay.__init__` (:1596-1603)
- Test: covered by the existing relay tests staying green + manual run note (the loop itself is I/O; the pure pieces are already tested in Tasks 1-2 and Phase 4).

> No new unit test for the loop wiring (it spawns subprocesses). The behavioral guarantee comes from Tasks 1-2 (argv) and Phase 3/4 (cookie resolution). Verify the existing suite stays green.

- [ ] **Step 1: Add `cookie_dir` to `Feed` and `Relay`**

In `Feed.__init__` (:1474) add a param and store it:

```python
    def __init__(self, name, port, idx, provider, logdir, cookies=None, fmt=YTDLP_FORMAT,
                 cookie_dir=None):
        ...
        self.cookies = cookies            # YouTube cookie jar path (bot-check) or None
        self.cookie_dir = cookie_dir      # dir holding yt-/twitch-cookies.txt (for per-pull resolve)
```

In `Relay.__init__` (:1597) add `cookie_dir=None` to the signature, store `self.cookie_dir = cookie_dir`, and pass it into both feeds:

```python
        self.A = Feed("A", ports[0], a_idx, source.get, logdir, cookies, cookie_dir=cookie_dir)
        self.B = Feed("B", ports[1], b_idx, source.get, logdir, cookies, cookie_dir=cookie_dir)
```

Also pass it to the POV feed where it is constructed (:1615 region): add `cookie_dir=cookie_dir` to that `Feed(...)` call.

- [ ] **Step 2: Branch the pull loop**

Replace the body of `Feed.run` from `url = channel_url(ch)` (:1548) through the serve block. New version:

```python
            self._set_phase("connecting")
            url = channel_url(ch)
            plat = platform_of(url)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f"\n>> [{self.name}:{self.port}] stint {i+1} ({plat}) -> {url}\n"); log.flush()

            if plat == "twitch":
                token = twitch_oauth_from_cookies(
                    cookies_for("twitch", self.cookie_dir))      # Phase 3/4 helpers
                target, serve_platform = url, "twitch"           # no yt-dlp hop
            else:
                hls, err = resolve_hls(url, self.cookies, self.logfile, self.fmt)
                if self.stop: break
                if self.advance.is_set():
                    self.advance.clear(); continue
                if not hls:
                    self.last_error = err
                    time.sleep(RESOLVE_RETRY); continue
                self.last_error = ssai_warning(hls, self.logfile)  # Phase 2 helper (warn, never block)
                token, target, serve_platform = None, hls, "youtube"

            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f">> [{self.name}:{self.port}] serving stint {i+1} ({serve_platform})\n"); log.flush()
                cmd = streamlink_serve_cmd(target, self.port, serve_platform, token)
                try:
                    self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                                 **_no_window_kwargs())
                    if serve_platform != "youtube":
                        self.last_error = None
                    self._set_phase("serving")
                    self.proc.wait()
                except FileNotFoundError:
                    log.write(f">> [{self.name}] streamlink not found on PATH — retrying\n"); log.flush()
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            self._set_phase("connecting")
            if self.stop: break
            if self.advance.is_set():
                self.advance.clear(); continue
            time.sleep(RETRY_SLEEP)
```

> Note: `ssai_warning`, `cookies_for`, and `twitch_oauth_from_cookies` are defined in Phases 2-3. To keep Phase 1 committable on its own, temporarily stub them (see Step 3) and replace the stubs in their phases.

- [ ] **Step 3: Add temporary stubs (removed in later phases)**

Until Phase 2/3 land, add near the top-level helpers so the module imports:

```python
def ssai_warning(hls_url, logfile):
    return None        # replaced in Phase 2

def cookies_for(platform, cookie_dir):
    return None        # replaced in Phase 3

def twitch_oauth_from_cookies(path):
    return None        # replaced in Phase 4
```

- [ ] **Step 4: Wire `cookie_dir` from `main`**

In `main` (after the cookies block ~:2160) compute and pass the dir. Where `Relay(...)` is constructed (:2241), add `cookie_dir=os.path.dirname(cookies) if cookies else runtime`:

```python
    relay = Relay(source, ports, logdir, cookies,
                  ... existing args ...,
                  cookie_dir=(os.path.dirname(cookies) if cookies else runtime))
```

- [ ] **Step 5: Run the full suite + lint**

Run: `python3 tools/run-tests.py` then `python3 tools/lint.py`
Expected: all pass (stubs make the module import; argv tests from Tasks 1-2 pass).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): per-platform pull dispatch (Twitch direct to streamlink) (#105)"
```

---

### Task 4: Surface platform + SSAI warning in `/status`

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Relay.status` per-feed dict (:1634-1638)
- Test: `tests/test_pov.py` is the relay status home, but status() needs a live Relay. Add a focused test that builds the per-feed dict shape via a small pure check instead — see Step 1.

- [ ] **Step 1: Extend the per-feed status dict**

In `Relay.status` (:1634) add `platform` to each feed entry, derived from the current channel:

```python
        for k, f in self.feeds.items():
            ch, i = f.current_channel()
            out["feeds"][k] = {"port": f.port, "index": i, "stint": i + 1,
                               "channel": ch,
                               "platform": platform_of(channel_url(ch)) if ch else None,
                               "state": "stopped" if f.paused else f.phase,
                               "state_age_s": round(now - f.phase_since, 1),
                               "last_error": f.last_error}
```

> `last_error` already carries the SSAI warning string for the YouTube branch (set by `ssai_warning`), so the panel renders it through the existing health line — no new field needed.

- [ ] **Step 2: Verify the suite stays green**

Run: `python3 tests/test_pov.py` then `python3 tools/run-tests.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(relay): expose feed platform in /status (#105)"
```

---

## Phase 2 — YouTube SSAI detection

### Task 5: `manifest_has_ssai_markers` + `ssai_warning`

**Files:**
- Modify: `src/relay/racecast-feeds.py` (replace the Phase-1 `ssai_warning` stub; add `manifest_has_ssai_markers` near `resolve_hls`, ~:1006)
- Test: `tests/test_platform.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_platform.py`:

```python
def t_ssai_markers():
    clean = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:2.0,\nseg0.ts\n#EXTINF:2.0,\nseg1.ts\n"
    assert feeds.manifest_has_ssai_markers(clean) is False
    cue = clean + "#EXT-X-CUE-OUT:30.0\n#EXTINF:2.0,\nad0.ts\n"
    assert feeds.manifest_has_ssai_markers(cue) is True
    daterange = clean + '#EXT-X-DATERANGE:ID="ad1",CLASS="twitch-stitched-ad",START-DATE="..."\n'
    assert feeds.manifest_has_ssai_markers(daterange) is True
    assert feeds.manifest_has_ssai_markers("") is False
    assert feeds.manifest_has_ssai_markers(None) is False
```

Add `t_ssai_markers();` to the `__main__` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (`manifest_has_ssai_markers` undefined)

- [ ] **Step 3: Write the implementation**

Add near `resolve_hls` (~:1006):

```python
# HLS tags that signal server-side ad insertion (SCTE-35 splice cues or an
# ad-classed date-range). Their PRESENCE in a YouTube manifest means the source
# is stitching ads we cannot reliably strip — we warn, never skip.
_SSAI_RE = re.compile(r"#EXT-X-(?:CUE-OUT|SCTE35|DATERANGE:[^\n]*(?:CLASS=\"[^\"]*ad|SCTE35-OUT))",
                      re.IGNORECASE)


def manifest_has_ssai_markers(text):
    """True iff an HLS playlist body carries server-side-ad-insertion markers.
    Pure + best-effort: empty/None -> False."""
    return bool(text) and bool(_SSAI_RE.search(text))


def ssai_warning(hls_url, logfile):
    """Fetch the resolved manifest once and, if it carries SSAI markers, return a
    short warning string for /status (else None). Best-effort: any network/parse
    failure returns None so the feed is never blocked by the probe."""
    try:
        import urllib.request
        with urllib.request.urlopen(hls_url, timeout=10) as r:   # noqa: S310 (https HLS only)
            body = r.read(65536).decode("utf-8", errors="replace")
    except Exception:
        return None   # probe is a bonus signal; never fail the resolve on it
    if manifest_has_ssai_markers(body):
        try:
            with open(logfile, "a", encoding="utf-8") as log:
                log.write("   WARN: source manifest carries server-side ads (cannot strip)\n")
        except Exception:
            pass  # logging best-effort
        return "source has server-side ads (not a clean broadcast feed)"
    return None
```

Remove the Phase-1 `ssai_warning` stub.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py` then `python3 tools/lint.py`
Expected: `ok`, lint clean

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/racecast-feeds.py
git commit -m "feat(relay): detect & warn on YouTube server-side ads (no skip) (#105)"
```

---

## Phase 3 — Cookie rename + `cookies_for`

### Task 6: `cookies_for(platform, cookie_dir)` resolver

**Files:**
- Modify: `src/relay/racecast-feeds.py` (replace the Phase-1 `cookies_for` stub, place near `cookie_health` ~:1991)
- Test: `tests/test_platform.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_platform.py`:

```python
import tempfile

def t_cookies_for(tmp=None):
    d = tempfile.mkdtemp()
    # nothing present -> None for both
    assert feeds.cookies_for("youtube", d) is None
    assert feeds.cookies_for("twitch", d) is None
    assert feeds.cookies_for("youtube", None) is None
    # legacy cookies.txt is still picked up for youtube
    legacy = os.path.join(d, "cookies.txt"); open(legacy, "w").write("x")
    assert feeds.cookies_for("youtube", d) == legacy
    # new yt-cookies.txt wins over legacy
    new = os.path.join(d, "yt-cookies.txt"); open(new, "w").write("x")
    assert feeds.cookies_for("youtube", d) == new
    # twitch file
    tw = os.path.join(d, "twitch-cookies.txt"); open(tw, "w").write("x")
    assert feeds.cookies_for("twitch", d) == tw
```

Add `t_cookies_for();` to the `__main__` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (stub returns None always; the legacy/new assertions fail)

- [ ] **Step 3: Replace the stub with the real resolver**

```python
def cookies_for(platform, cookie_dir):
    """Resolve the cookie file for a platform inside the shared cookie dir.
    YouTube prefers yt-cookies.txt and falls back to the legacy cookies.txt;
    Twitch uses twitch-cookies.txt. Returns an existing path or None (public).
    Pure (no migration side effects — see migrate_legacy_cookie)."""
    if not cookie_dir:
        return None
    if platform == "twitch":
        p = os.path.join(cookie_dir, "twitch-cookies.txt")
        return p if os.path.isfile(p) else None
    p = os.path.join(cookie_dir, "yt-cookies.txt")
    if os.path.isfile(p):
        return p
    legacy = os.path.join(cookie_dir, "cookies.txt")
    return legacy if os.path.isfile(legacy) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/racecast-feeds.py
git commit -m "feat(relay): cookies_for() per-platform resolver with legacy fallback (#105)"
```

---

### Task 7: One-time legacy-name migration + rename canonical writers

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `migrate_legacy_cookie`, call it in `main`; change `export_cookies` out default discussion (caller passes path); cookie auto-detect block (:2155-2160).
- Modify: `src/relay/get-cookies.py` — out filename `cookies.txt` → `yt-cookies.txt`, add `--platform`.
- Modify: `src/racecast.py` — `_cookies_path` (:495).
- Test: `tests/test_platform.py`

- [ ] **Step 1: Write the failing test** for the pure migration helper — append:

```python
def t_migrate_legacy():
    d = tempfile.mkdtemp()
    # no files: no-op, returns the canonical path
    assert feeds.migrate_legacy_cookie(d).endswith("yt-cookies.txt")
    # legacy present, new absent: renamed
    legacy = os.path.join(d, "cookies.txt"); open(legacy, "w").write("x")
    p = feeds.migrate_legacy_cookie(d)
    assert p.endswith("yt-cookies.txt") and os.path.isfile(p) and not os.path.isfile(legacy)
    # both present: legacy left as-is, new wins
    open(legacy, "w").write("y")
    p2 = feeds.migrate_legacy_cookie(d)
    assert os.path.isfile(p2) and os.path.isfile(legacy)
```

Add `t_migrate_legacy();` to the `__main__` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (`migrate_legacy_cookie` undefined)

- [ ] **Step 3: Implement the migration helper** (near `cookies_for`):

```python
def migrate_legacy_cookie(cookie_dir):
    """Rename a legacy cookies.txt to yt-cookies.txt once, if the new name does
    not yet exist. Returns the canonical yt-cookies.txt path. Best-effort."""
    new = os.path.join(cookie_dir, "yt-cookies.txt")
    legacy = os.path.join(cookie_dir, "cookies.txt")
    if not os.path.isfile(new) and os.path.isfile(legacy):
        try:
            os.replace(legacy, new)
        except OSError:
            return legacy   # migration failed -> keep using legacy this run
    return new
```

- [ ] **Step 4: Wire the canonical name through the writers**

In `src/racecast.py` `_cookies_path` (:495) — inline the legacy→new rename (do **not** import the relay from the hot CLI path; the relay's `migrate_legacy_cookie` test already covers the logic):

```python
def _cookies_path():
    """The YouTube cookie jar -- SHARED across leagues, at the un-scoped runtime/
    root. Canonical name is yt-cookies.txt; a legacy cookies.txt is migrated once."""
    base = _runtime_base_dir()
    new = os.path.join(base, "yt-cookies.txt")
    legacy = os.path.join(base, "cookies.txt")
    if not os.path.isfile(new) and os.path.isfile(legacy):
        try:
            os.replace(legacy, new)
        except OSError:
            return legacy   # migration failed -> keep using legacy this run
    return new
```

In `src/relay/get-cookies.py`:
- Change `out = os.path.join(a.runtime_dir, "cookies.txt")` → branch on platform (next step adds `--platform`). For YouTube: `yt-cookies.txt`.
- Update the module docstring (`<runtime>/cookies.txt` → `yt-cookies.txt`).

In `src/relay/racecast-feeds.py` cookie auto-detect (:2157-2159) — prefer the migrated name:

```python
    if cookies is None:
        auto = migrate_legacy_cookie(runtime)   # yt-cookies.txt (+ one-time rename)
        cookies = auto if os.path.exists(auto) else None
```

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_platform.py`, `python3 tests/test_config.py`, `python3 tools/lint.py`
Expected: PASS

- [ ] **Step 6: Grep sweep for stragglers** (CLAUDE.md hard rule)

Run: `grep -rn "cookies\.txt" src/ tools/ tests/ .github/ README.md CLAUDE.md`
Action: update each remaining doc/string reference to `yt-cookies.txt` (keep the *legacy fallback* mentions explicit). Code that only reads a passed-in path needs no change.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py src/relay/get-cookies.py src/racecast.py
git commit -m "feat(cookies): rename cookies.txt -> yt-cookies.txt with one-time migration (#105)"
```

---

## Phase 4 — Twitch auth (CLI + Control Center)

### Task 8: `twitch_oauth_from_cookies` extractor

**Files:**
- Modify: `src/relay/racecast-feeds.py` (replace the Phase-1 `twitch_oauth_from_cookies` stub, near `cookies_for`)
- Test: `tests/test_platform.py`

- [ ] **Step 1: Write the failing test** — append:

```python
def t_twitch_oauth():
    assert feeds.twitch_oauth_from_cookies(None) is None
    assert feeds.twitch_oauth_from_cookies("/no/such/file") is None
    d = tempfile.mkdtemp(); p = os.path.join(d, "twitch-cookies.txt")
    # Netscape format: domain \t flag \t path \t secure \t expiry \t name \t value
    open(p, "w").write(
        "# Netscape HTTP Cookie File\n"
        ".twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\tdeadbeefcafe0123\n"
        ".twitch.tv\tTRUE\t/\tTRUE\t0\tother\tnope\n")
    assert feeds.twitch_oauth_from_cookies(p) == "deadbeefcafe0123"
    # file without auth-token -> None
    open(p, "w").write(".twitch.tv\tTRUE\t/\tTRUE\t0\tother\tnope\n")
    assert feeds.twitch_oauth_from_cookies(p) is None
```

Add `t_twitch_oauth();` to the `__main__` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (stub returns None for the valid-token case)

- [ ] **Step 3: Replace the stub**

```python
def twitch_oauth_from_cookies(path):
    """Extract the Twitch `auth-token` value from a Netscape cookies file, for
    Streamlink's --twitch-api-header. Returns the token or None (public/no auth).
    Pure-ish (reads a file); any error -> None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#") or "\t" not in line:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and parts[5] == "auth-token" and parts[6]:
                    return parts[6]
    except OSError:
        return None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/racecast-feeds.py
git commit -m "feat(relay): twitch_oauth_from_cookies() auth-token extractor (#105)"
```

---

### Task 9: `--platform twitch` export in get-cookies.py

**Files:**
- Modify: `src/relay/get-cookies.py`
- Test: `tests/test_init.py` or a small new check — the export itself shells out to yt-dlp, so test only the **pure** out-path/url selection. Add a helper `cookie_target(platform, runtime_dir)` and test it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_platform.py` (it already imports nothing from get-cookies; add a dedicated loader):

```python
def _load_getcookies():
    p = os.path.join(os.path.dirname(__file__), "..", "src", "relay", "get-cookies.py")
    spec = importlib.util.spec_from_file_location("getck", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def t_cookie_target():
    gc = _load_getcookies()
    out_yt, url_yt = gc.cookie_target("youtube", "/run")
    assert out_yt.endswith("yt-cookies.txt") and "youtube.com" in url_yt
    out_tw, url_tw = gc.cookie_target("twitch", "/run")
    assert out_tw.endswith("twitch-cookies.txt") and "twitch.tv" in url_tw
```

Add `t_cookie_target();` to the `__main__` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_platform.py`
Expected: FAIL (`cookie_target` undefined)

- [ ] **Step 3: Implement in get-cookies.py**

Add the pure helper and use it in `main`:

```python
def cookie_target(platform, runtime_dir):
    """(out_path, probe_url) for a cookie export. Pure."""
    if platform == "twitch":
        return os.path.join(runtime_dir, "twitch-cookies.txt"), "https://www.twitch.tv"
    return os.path.join(runtime_dir, "yt-cookies.txt"), "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

In `main`, add `ap.add_argument("--platform", default="youtube", choices=["youtube", "twitch"])`, replace the hardcoded `out`/`url` with `out, url = cookie_target(a.platform, a.runtime_dir)`, and adjust the login-detection regex: for twitch, success = `auth-token` present (`re.search(r"auth-token", txt)`), else the YouTube regex. Update the docstring + print strings to name the platform.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_platform.py`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add tests/test_platform.py src/relay/get-cookies.py
git commit -m "feat(cookies): get-cookies.py --platform twitch export (#105)"
```

---

### Task 10: `racecast cookies twitch <browser>` CLI routing

**Files:**
- Modify: `src/racecast.py` — the `cookies` one-shot arg assembly (around ONESHOTS dispatch / where browser arg is read).
- Test: `tests/test_racecast.py` (CLI routing home)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_racecast.py` a check that a leading `twitch` token is translated to `--platform twitch` and the remaining token is the browser. (Mirror the existing cookies-routing test in that file; assert the argv passed to the cookies script contains `--platform twitch` and the browser.)

```python
def t_cookies_twitch_routing():
    # however that file invokes the router; assert the translated args:
    args = rc._cookies_oneshot_args(["twitch", "firefox"])     # new pure helper
    assert "--platform" in args and args[args.index("--platform") + 1] == "twitch"
    assert "firefox" in args
    args2 = rc._cookies_oneshot_args(["firefox"])
    assert "--platform" not in args2 and "firefox" in args2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL (`_cookies_oneshot_args` undefined)

- [ ] **Step 3: Implement the pure translator + use it in dispatch**

Add to `src/racecast.py`:

```python
def _cookies_oneshot_args(rest):
    """Translate `cookies` subcommand args. A leading 'twitch' selects the Twitch
    export (--platform twitch); anything else is the YouTube browser as before."""
    rest = list(rest)
    if rest and rest[0] == "twitch":
        return ["--platform", "twitch"] + rest[1:]
    return rest
```

Call it where the `cookies` one-shot forwards its trailing args to `get-cookies.py` (the ONESHOTS dispatch / `RUNTIME_DIR_ONESHOTS` path). Update the usage string (:22) to include `cookies [twitch] [browser]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_racecast.py src/racecast.py
git commit -m "feat(cli): racecast cookies twitch <browser> (#105)"
```

---

### Task 11: Control Center "Twitch login (optional)" row

**Files:**
- Modify: `src/ui/ui_ops.py` (op registry :30, :84), `src/ui/control-center.html` (cookie view :697-710)
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing test** — add to `tests/test_ui_ops.py` (the module exposes `OPS`, `PARAMS`, `build_argv`):

```python
def t_cookies_twitch_op():
    assert "cookies-twitch" in ui_ops.OPS
    argv = ui_ops.build_argv("cookies-twitch", {"browser": "firefox"})
    assert argv == ["cookies", "twitch", "firefox"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_ops.py`
Expected: FAIL (`cookies-twitch` not registered)

- [ ] **Step 3: Register the op** in `src/ui/ui_ops.py`:

```python
    "cookies": ["cookies"],
    "cookies-twitch": ["cookies", "twitch"],
    ...
    "cookies": {"browser": _browser_arg},
    "cookies-twitch": {"browser": _browser_arg},
```

- [ ] **Step 4: Add the HTML row** in `src/ui/control-center.html` after the YouTube cookie row (:709), mirroring it:

```html
          <div class="row"><span class="name">Twitch login (optional)</span>
            <span class="badge" id="b-cookies-tw"><span class="dot"></span><span>…</span></span>
            <span class="dim grow">only needed for sub-/follower-only Twitch feeds</span>
            <select id="browser-tw" aria-label="Browser to export Twitch cookies from">
              <!-- same options as #browser -->
            </select>
            <button onclick="op('cookies-twitch', false, {browser: $('browser-tw').value})">
              Refresh Twitch login</button>
          </div>
```

Update the cookie view subtitle (:697) to "YouTube login (required) + Twitch login (optional) — shared across all leagues".

- [ ] **Step 5: Run test + lint**

Run: `python3 tests/test_ui_ops.py` then `python3 tools/lint.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_ui_ops.py src/ui/ui_ops.py src/ui/control-center.html
git commit -m "feat(ui): Control Center Twitch login row (#105)"
```

---

## Phase 5 — Panel UX + docs/wiki

### Task 12: Panel stream-entry help + platform badge

**Files:**
- Modify: `src/obs/hud.html`? No — the **panel** is served from the relay; find the panel template (search `Schedule`/`POV` stream-entry markup and the `/status` feed renderer).
- Test: none (static HTML/JS); verify by `racecast relay run` + open `/panel`.

- [ ] **Step 1: Locate the panel markup**

Run: `grep -rn "watch?v=\|Schedule\|/status\|feeds\[" src/relay/*.html src/obs/*.html 2>/dev/null`
Edit the schedule/POV stream-entry help text to: "YouTube or Twitch — full watch URL (e.g. `https://www.youtube.com/watch?v=…` or `https://www.twitch.tv/<channel>`)".

- [ ] **Step 2: Render the platform badge**

In the JS that builds each feed row from `/status` `feeds[k]`, when `f.platform` is set, render a small `YT`/`TW` chip next to the feed letter. Keep `f.last_error` rendering as-is (it now also carries the SSAI warning).

- [ ] **Step 3: Manual verify**

Run: `python3 src/racecast.py relay run` (foreground), open `http://127.0.0.1:8088/panel`, confirm help text + that a running feed shows a platform chip.

- [ ] **Step 4: Commit**

```bash
git add src/relay  # the panel template/JS
git commit -m "feat(panel): YouTube/Twitch help text + per-feed platform badge (#105)"
```

---

### Task 13: Docs + wiki (YouTube → YouTube/Twitch; Producer accounts)

**Files:**
- Modify: relay header comment (`src/relay/racecast-feeds.py:32-36`), CLI help (`src/racecast.py:22`, `--cookies` help :2098-2105), `README.md`, `CLAUDE.md`, `src/docs/README_SETUP.md` / `src/docs/Broadcast_Setup_Guide.md`, `src/docs/wiki/*` onboarding pages.
- Test: none (docs). Wiki publish is a separate maintainer step (`tools/sync-wiki.py`), not in this PR.

- [ ] **Step 1: English-only, mechanism-only edits** (CLAUDE.md hard rules)

- Replace "commentator YouTube stream" / "enter UNLISTED streams as a watch URL" with platform-neutral wording naming both YouTube and Twitch and the full-URL norm.
- `--cookies` help: note `yt-cookies.txt` (canonical) + legacy `cookies.txt` fallback; mention `racecast cookies twitch <browser>` for the optional Twitch login.

- [ ] **Step 2: Add a "Producer accounts" wiki section + pre-event checklist**

Create/extend the relevant `src/docs/wiki/` onboarding page with: *recommended that the producer keeps a logged-in YouTube browser session (mandatory — bot-check / `yt-cookies.txt`) and, if any Twitch feed may be gated, a logged-in Twitch session (`racecast cookies twitch firefox` → `twitch-cookies.txt`)*. State it as mechanism (what the logins enable), not a crew rule. Mirror a short note into `src/docs/Broadcast_Setup_Guide.md` and the cookie-refresh section.

- [ ] **Step 3: Document the known limits** (from the spec) where cookies/feeds are described: YouTube DAI/SSAI ads are detected & warned, not removed; Twitch ad-filtering relies on current Streamlink.

- [ ] **Step 4: Commit**

```bash
git add src/relay/racecast-feeds.py src/racecast.py README.md CLAUDE.md src/docs
git commit -m "docs: YouTube/Twitch parity + Producer accounts guidance (#105)"
```

---

### Task 14: Build-verify + final sweep

- [ ] **Step 1: Full suite**

Run: `python3 tools/run-tests.py`
Expected: all green

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: clean

- [ ] **Step 3: Build verify** (closest thing to CI)

Run: `python3 tools/build.py`
Expected: assembles `dist/` and passes the verify step (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 4: Grep for residual `cookies.txt` / YouTube-only wording**

Run: `grep -rn "cookies\.txt" src/ tools/ tests/ .github/ README.md CLAUDE.md`
Confirm every remaining hit is an intentional *legacy-fallback* mention.

- [ ] **Step 5: Commit any cleanup, then open the PR**

```bash
git push -u origin feat/twitch-relay-parity
gh pr create --fill --base main
```

---

## Self-review (spec coverage)

| Spec requirement | Task |
|---|---|
| Per-platform resolve dispatch (`platform_of`, branch) | 1, 3 |
| Twitch direct-to-streamlink + `--twitch-low-latency`/`--hls-live-edge 2`, no `--twitch-disable-ads` | 2, 3 |
| YouTube CSAI bypass unchanged | 3 (YouTube branch identical) |
| YouTube SSAI/DAI detection → `/status` warning, non-fatal | 4, 5 |
| `channel_url` unchanged (full-URL norm) | (no code change — Task 13 docs) |
| Rename `cookies.txt` → `yt-cookies.txt` + legacy fallback + one-time migration | 6, 7 |
| `cookies_for(platform, dir)` resolver | 6 |
| Twitch OAuth token model (`twitch_oauth_from_cookies`, `--twitch-api-header`) | 2, 8 |
| `racecast cookies twitch <browser>` CLI | 9, 10 |
| Control Center Twitch login row | 11 |
| Panel help text + platform badge | 12 |
| Docs/wiki + Producer accounts recommendation | 13 |
| Tests for all pure helpers | 1, 2, 5, 6, 7, 8, 9, 10, 11 |
| Build-verify | 14 |

**Known-limit / out-of-scope items** (documented, not built): YouTube server-side ad *removal*; Twitch token rotation warning. Covered by Task 13 docs.
