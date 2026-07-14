# Robust Ingest — Quality Profiles (#493) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a relay feed three manual quality **profiles** (FULL / ROBUST / EMERGENCY) plus a single automatic FULL→ROBUST step-down, so an unstable low-bandwidth source stays watchable at a lower, sustainable rendition instead of stall→reconnect cycling.

**Architecture:** A per-`Feed` `quality_tier` (+ a `quality_pinned` flag) selects the yt-dlp format (YouTube) / streamlink quality positional (Twitch) **and** a bundled robust streamlink profile at resolve time. Auto-step-down (FULL→ROBUST only, 720p hard floor) fires off the existing `dead_serves` short-serve signal and raises an `@here` Discord ping + Director-Panel alert + health incident. Everything else — step-up, the emergency sub-720p profile — is a manual Director-Panel/Companion action via a new director-gated `POST /feed/<A|B>/quality`.

**Tech Stack:** Python 3 stdlib only (relay `src/relay/racecast-feeds.py`), `src/scripts/console_policy.py`, `src/scripts/health_store.py`, HTML/JS (`src/director/`), Companion config (`src/companion/`). Tests are stdlib runnable scripts under `tests/`.

**Spec:** `docs/superpowers/specs/2026-07-14-robust-ingest-quality-profile-design.md`.

## Global Constraints

- **Edit only under `src/`, `tests/`, `tools/`, `docs/`, `.env.example`.** Never touch `dist/`/`runtime/`.
- **English only** in all code, comments, docs, log lines, UI strings.
- **stdlib only**; every `tests/test_*.py` is a runnable script (no pytest). Run one file with `python3 tests/test_x.py`; the full suite with `python3 tools/run-tests.py`. Run `python3 tools/lint.py` after any Python change.
- **Backward compatible:** default behaviour unchanged unless a source degrades. New env `RACECAST_FEED_ROBUST_AUTO` **defaults ON**; `=0` disables only the automatic step-down. No CLI flag renames.
- **Quality invariants (from the spec, verbatim):** FULL = "best available up to 1080p" (`b[height<=1080]/b` / Twitch `best`) — never forces 1080p, always bounded by the source's current max. Auto-step-down goes **FULL → ROBUST only**; **720p is the hard automatic floor**; the sub-720p **EMERGENCY** tier is reachable **only** by an explicit operator action. **Step-up is manual only** (no auto-climb). A manual pin (`quality_pinned=True`) suppresses auto-step-down; **AUTO** releases it (`tier="full", pinned=False`). A **new distinct source** resets to the managed state (`tier="full", pinned=False`); a same-URL continuation keeps its profile.
- **Tier strings (exact):** YouTube — FULL `b[height<=1080]/b`, ROBUST `b[height<=720]/b`, EMERGENCY `b[height<=480]/w`. Twitch — FULL `best`, ROBUST `720p60,720p`, EMERGENCY `480p,360p,worst`. Robust streamlink profile — YouTube `--ringbuffer-size 128M --hls-live-edge 6`, Twitch `--ringbuffer-size 128M --hls-live-edge 2 --twitch-low-latency`.
- **POV is excluded from the operator control:** the POV feed is constructed pinned at ROBUST (`tier="robust", pinned=True`) — it replaces the old `YTDLP_FORMAT_POV` cap and is never auto-stepped or shown in the profile UI.
- **Director Panel / Companion are UI surfaces:** any visible change REQUIRES regenerating the committed wiki image in the SAME change (`src/docs/wiki/images/director-panel.png` via the `wiki-screenshots` skill; `companion-page*-*.png` via `companion-screenshots`) and passing the `ui-visual-verification` pre-flight look. This is a CLAUDE.md hard rule.
- **No new outbound HTTP path:** the Discord ping reuses the relay's existing `self._discord_post(...)`. The new endpoint accepts **no URL** (only a feed id + an enum tier) — no SSRF surface.

## File Structure

- `src/relay/racecast-feeds.py` — constants (robust streamlink profiles), pure tier helpers, `Feed` quality state + `set_quality`/`maybe_step_down`, run-loop resolve wiring + step-down firing, POV construction, `discord_step_down_payload`, `Relay._record_feed_step_down`, `Relay.set_feed_quality`, `/feed/<A|B>/quality` route, `status()` + `_health_current` profile/pinned fields.
- `src/scripts/console_policy.py` — extend the `feed` route rule with `"quality"`.
- `tests/test_pov.py` — pure helpers, `Feed` state, `discord_step_down_payload` (relay unit home).
- `tests/test_console.py` + `tests/test_console_gate.py` — `/feed/<A|B>/quality` director gating.
- `src/director/director-panel.html` (+ any panel JS/CSS in `src/director/`) — profile control, served-res, source-max hint, step-down alert.
- `src/companion/racecast-buttons.companionconfig` — per-feed profile buttons; `src/scripts/…` `export companion` generator if buttons are generated there.
- `.env.example` — `RACECAST_FEED_ROBUST_AUTO`.
- `tools/fanout-soak.py` — a `--switch-to` tier option to exercise a manual switch under a jittery source.
- `src/docs/wiki/images/director-panel.png`, `companion-page*-*.png` — regenerated screenshots.

---

### Task 1: Pure quality helpers + robust streamlink constants

**Files:**
- Modify: `src/relay/racecast-feeds.py` (near the format constants `:133`–`:186`)
- Test: `tests/test_pov.py`

**Interfaces:**
- Produces: `STREAMLINK_SERVE_ROBUST`, `STREAMLINK_TWITCH_ROBUST` (lists); `QUALITY_TIERS = ("full","robust","emergency")`; `ROBUST_STEP_DOWN_AFTER = 2`; and pure functions:
  - `quality_ytdlp_fmt(tier) -> str`
  - `quality_twitch_selector(tier) -> str`
  - `streamlink_serve_flags(tier) -> list[str]`
  - `streamlink_twitch_flags(tier) -> list[str]`
  - `parse_quality_tier(value) -> str | None`
  - `quality_height(token) -> int | None`
  - `quality_step_down_due(tier, pinned, dead_serves, source_state, *, threshold=ROBUST_STEP_DOWN_AFTER) -> bool`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`:

```python
def t_quality_ytdlp_fmt():
    assert fe.quality_ytdlp_fmt("full") == "b[height<=1080]/b"
    assert fe.quality_ytdlp_fmt("robust") == "b[height<=720]/b"
    assert fe.quality_ytdlp_fmt("emergency") == "b[height<=480]/w"

def t_quality_twitch_selector():
    assert fe.quality_twitch_selector("full") == "best"
    assert fe.quality_twitch_selector("robust") == "720p60,720p"
    assert fe.quality_twitch_selector("emergency") == "480p,360p,worst"

def t_streamlink_flags_per_tier():
    assert fe.streamlink_serve_flags("full") == fe.STREAMLINK_SERVE
    assert fe.streamlink_serve_flags("robust") == fe.STREAMLINK_SERVE_ROBUST
    assert fe.streamlink_serve_flags("emergency") == fe.STREAMLINK_SERVE_ROBUST
    assert fe.streamlink_twitch_flags("full") == fe.STREAMLINK_TWITCH
    assert fe.streamlink_twitch_flags("robust") == fe.STREAMLINK_TWITCH_ROBUST

def t_parse_quality_tier():
    for v in ("full", "robust", "emergency", "auto"):
        assert fe.parse_quality_tier(v) == v
    assert fe.parse_quality_tier("FULL") == "full"       # case-insensitive
    assert fe.parse_quality_tier("  robust ") == "robust"
    assert fe.parse_quality_tier("1080p") is None
    assert fe.parse_quality_tier("") is None
    assert fe.parse_quality_tier(None) is None

def t_quality_height():
    assert fe.quality_height("720p60") == 720
    assert fe.quality_height("1080p") == 1080
    assert fe.quality_height("480p") == 480
    assert fe.quality_height("best") is None
    assert fe.quality_height("audio_only") is None
    assert fe.quality_height(None) is None

def t_quality_step_down_due():
    # fires: unpinned, FULL, live-but-degraded, enough dead serves
    assert fe.quality_step_down_due("full", False, 2, None) is True
    assert fe.quality_step_down_due("full", False, 5, None) is True
    # not yet enough dead serves
    assert fe.quality_step_down_due("full", False, 1, None) is False
    # pinned suppresses auto
    assert fe.quality_step_down_due("full", True, 9, None) is False
    # already below full -> never auto-descend further
    assert fe.quality_step_down_due("robust", False, 9, None) is False
    assert fe.quality_step_down_due("emergency", False, 9, None) is False
    # offline / ended source -> stepping quality cannot help
    assert fe.quality_step_down_due("full", False, 9, "not_live_yet") is False
    assert fe.quality_step_down_due("full", False, 9, "ended") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL (AttributeError: module has no attribute `quality_ytdlp_fmt`).

- [ ] **Step 3: Implement** — add after `STREAMLINK_TWITCH` (`:186`) in `src/relay/racecast-feeds.py`:

```python
# --- Quality profiles (#493): each tier = a rendition cap + a streamlink profile ---
# FULL = best available up to 1080p (never forces 1080p; bounded by the source's max).
# ROBUST = 720p floor (the automatic step-down target). EMERGENCY = sub-720p, operator-only.
QUALITY_TIERS = ("full", "robust", "emergency")
ROBUST_STEP_DOWN_AFTER = 2       # consecutive dead (short) serves before an auto FULL->ROBUST

# Robust streamlink profile: more buffered segments at the live edge -> rides out short
# source jitter, trading latency for stability. Applied at ROBUST and EMERGENCY.
STREAMLINK_SERVE_ROBUST = ["--ringbuffer-size", "128M", "--hls-live-edge", "6"]
STREAMLINK_TWITCH_ROBUST = ["--ringbuffer-size", "128M", "--hls-live-edge", "2",
                            "--twitch-low-latency"]

_QUALITY_YTDLP = {"full": "b[height<=1080]/b",
                  "robust": "b[height<=720]/b",
                  "emergency": "b[height<=480]/w"}
_QUALITY_TWITCH = {"full": "best",
                   "robust": "720p60,720p",
                   "emergency": "480p,360p,worst"}
_QUALITY_HEIGHT_RE = re.compile(r"(\d{3,4})p")


def quality_ytdlp_fmt(tier):
    """yt-dlp -f string for a quality tier. Pure → unit-tested."""
    return _QUALITY_YTDLP.get(tier, _QUALITY_YTDLP["full"])


def quality_twitch_selector(tier):
    """Streamlink quality positional for a quality tier (Twitch). Pure → unit-tested."""
    return _QUALITY_TWITCH.get(tier, _QUALITY_TWITCH["full"])


def streamlink_serve_flags(tier):
    """YouTube streamlink buffer/live-edge flags for a tier (robust at <=ROBUST). Pure."""
    return STREAMLINK_SERVE_ROBUST if tier in ("robust", "emergency") else STREAMLINK_SERVE


def streamlink_twitch_flags(tier):
    """Twitch streamlink buffer/live-edge flags for a tier. Pure."""
    return STREAMLINK_TWITCH_ROBUST if tier in ("robust", "emergency") else STREAMLINK_TWITCH


def parse_quality_tier(value):
    """Normalise an operator-supplied tier to one of full|robust|emergency|auto, else
    None (so the endpoint can 400). `auto` = release a manual pin. Pure → unit-tested."""
    if not value:
        return None
    v = value.strip().lower()
    return v if v in ("full", "robust", "emergency", "auto") else None


def quality_height(token):
    """Numeric vertical resolution of a streamlink quality token ('720p60' -> 720),
    or None for non-heighted tokens ('best', 'audio_only', None). Pure → unit-tested."""
    if not token:
        return None
    m = _QUALITY_HEIGHT_RE.search(token)
    return int(m.group(1)) if m else None


def quality_step_down_due(tier, pinned, dead_serves, source_state,
                          *, threshold=ROBUST_STEP_DOWN_AFTER):
    """True when a feed should auto-step-down FULL->ROBUST: only while not manually
    pinned, only from FULL (720p is the hard floor), only for a live-but-degraded
    source (source_state None — an offline/not-live/ended source has no picture at any
    rendition, so a lower cap cannot help), once dead (short) serves reach `threshold`.
    Pure → unit-tested."""
    return (not pinned) and tier == "full" and source_state is None \
        and dead_serves >= threshold
```

Confirm `re` is imported at the top of the file (it is used elsewhere; if the import is missing, add `import re`).

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): quality-tier pure helpers + robust streamlink profile (#493)"
```

---

### Task 2: Thread the tier through the streamlink command builders

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `streamlink_serve_cmd` (`:2926`), `streamlink_fanout_cmd` (`:2952`)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `streamlink_serve_flags`, `streamlink_twitch_flags`, `quality_twitch_selector` (Task 1).
- Produces: both builders gain a keyword `tier="full"`; YouTube uses `streamlink_serve_flags(tier)`, Twitch uses `streamlink_twitch_flags(tier)` + `quality_twitch_selector(tier)` as the positional (instead of the hardcoded constants + `"best"`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`:

```python
def t_streamlink_serve_cmd_tier():
    # YouTube robust: robust flags, positional stays "best" (yt-dlp already capped the rendition)
    yt = fe.streamlink_serve_cmd("http://h/x.m3u8", 53001, "youtube", tier="robust")
    assert "128M" in yt and yt[-1] == "best"
    # Twitch robust: robust flags + the capped quality positional
    tw = fe.streamlink_serve_cmd("https://twitch.tv/x", 53001, "twitch", tier="robust")
    assert "128M" in tw and tw[-1] == "720p60,720p"
    # Twitch full: unchanged default
    tw_full = fe.streamlink_serve_cmd("https://twitch.tv/x", 53001, "twitch")
    assert tw_full[-1] == "best"

def t_streamlink_fanout_cmd_tier():
    tw = fe.streamlink_fanout_cmd("https://twitch.tv/x", "twitch", tier="emergency")
    assert "128M" in tw and tw[-1] == "480p,360p,worst"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL (unexpected keyword `tier`).

- [ ] **Step 3: Implement** — in both builders replace the platform branch. For `streamlink_serve_cmd`, change the signature to `def streamlink_serve_cmd(target, port, platform="youtube", twitch_token=None, cookies=None, user_agent=STREAMLINK_YT_UA, tier="full"):` and the body:

```python
    base = ["streamlink", "--player-external-http", "--player-external-http-port", str(port)]
    if platform == "twitch":
        base += streamlink_twitch_flags(tier)
        if twitch_token:
            base += ["--twitch-api-header", f"Authorization=OAuth {twitch_token}"]
        selector = quality_twitch_selector(tier)
    else:
        base += streamlink_serve_flags(tier)
        base += queue_deadline_args(_streamlink_help())
        if user_agent:
            base += ["--http-header", f"User-Agent={user_agent}"]
        if cookies:
            base += ["--http-cookies-file", cookies]
        selector = "best"     # yt-dlp already resolved the capped rendition
    return base + ["--", target, selector]
```

Apply the identical change to `streamlink_fanout_cmd` (signature gains `tier="full"`; body uses `streamlink_twitch_flags`/`streamlink_serve_flags` + the same `selector`, keeping its `--stdout` base).

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): thread quality tier through streamlink command builders (#493)"
```

---

### Task 3: Feed quality state, POV pinning, resolve wiring, new-source reset

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `Feed.__init__` (`:5119`), `set_index` (`:5215`), the resolve/serve calls in `run()` (`:5346`, `:5374`, `:5381`), POV construction (`:5526`)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `quality_ytdlp_fmt`, `quality_step_down_due`, `QUALITY_TIERS` (Task 1); the tier-aware builders (Task 2).
- Produces on `Feed`: `self.quality_tier` (default `"full"`), `self.quality_pinned` (default `False`), `self.on_step_down` (default `None`); methods `set_quality(tier, pinned)` and `maybe_step_down() -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`. Build a `Feed` with a no-op provider (mirror the existing Feed-construction pattern already used in this test file):

```python
def _mk_feed():
    return fe.Feed("A", 53001, 0, provider=lambda: [], logdir=tempfile.mkdtemp())

def t_feed_quality_defaults():
    f = _mk_feed()
    assert f.quality_tier == "full" and f.quality_pinned is False

def t_feed_set_quality_pins():
    f = _mk_feed()
    f.set_quality("robust", True)
    assert f.quality_tier == "robust" and f.quality_pinned is True

def t_feed_maybe_step_down_fires_once():
    f = _mk_feed()
    f.dead_serves = 2
    assert f.maybe_step_down() == ("full", "robust")
    assert f.quality_tier == "robust" and f.quality_pinned is False
    # already robust -> no further auto step
    f.dead_serves = 9
    assert f.maybe_step_down() is None

def t_feed_maybe_step_down_respects_pin_and_state():
    f = _mk_feed(); f.set_quality("full", True); f.dead_serves = 9
    assert f.maybe_step_down() is None            # pinned
    g = _mk_feed(); g.dead_serves = 9; g.source_state = "ended"
    assert g.maybe_step_down() is None            # offline/ended

def t_feed_new_source_resets_quality():
    f = _mk_feed(); f.set_quality("emergency", True)
    f.set_index(4)
    assert f.quality_tier == "full" and f.quality_pinned is False
```

(Ensure `import tempfile` is present in the test file.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_pov.py`
Expected: FAIL (no attribute `quality_tier` / `set_quality`).

- [ ] **Step 3: Implement**

In `Feed.__init__`, after `self.dead_serves = 0` (`:5161`) add:

```python
        self.quality_tier = "full"        # #493: full|robust|emergency (POV: pinned robust)
        self.quality_pinned = False       # True = operator pinned; suppresses auto-step-down
        self.on_step_down = None          # relay-set callback(feed, stint, from_tier, to_tier)
```

Add the two methods on `Feed` (near `set_index`/`reload`):

```python
    def set_quality(self, tier, pinned):
        """Set the quality tier and pin state, then trigger a re-resolve so the change
        takes effect immediately (brief reconnect — a deliberate director action)."""
        self.quality_tier = tier
        self.quality_pinned = pinned
        self.advance.set(); self._kill_proc()

    def maybe_step_down(self):
        """If an auto FULL->ROBUST step-down is due (see quality_step_down_due), apply it
        and return (from_tier, to_tier); else None. Leaves pinned False (still managed)."""
        if not feed_robust_auto_enabled(os.environ):
            return None
        if quality_step_down_due(self.quality_tier, self.quality_pinned,
                                 self.dead_serves, self.source_state):
            frm = self.quality_tier
            self.quality_tier = "robust"
            return (frm, "robust")
        return None
```

Add the env getter near the other `feed_*` env getters (mirroring `feed_autoresync_enabled` from #488):

```python
def feed_robust_auto_enabled(environ):
    """#493 auto FULL->ROBUST step-down. Default ON; RACECAST_FEED_ROBUST_AUTO=0 disables
    only the automatic step-down (manual switching always remains). Pure → unit-tested."""
    return (environ.get("RACECAST_FEED_ROBUST_AUTO") or "").strip().lower() not in _FANOUT_FALSEY
```

In `set_index` (`:5215`), alongside the existing `self.dead_serves = 0` reset, add the managed-state reset:

```python
        self.quality_tier = "full"        # #493: a new source starts fresh at full quality
        self.quality_pinned = False
```

In `run()`, change the YouTube resolve (`:5346`) from `self.fmt` to the tier mapping, and pass the tier to the serve/fanout builders:

```python
                hls, err = resolve_hls(url, self.cookies, self.log,
                                       quality_ytdlp_fmt(self.quality_tier))
```
```python
                    serve_elapsed, serve_rc = self._serve_fanout(
                        target, serve_platform, token, on_first_byte=_recover)   # _serve_fanout builds its cmd with tier below
```
`_serve_fanout` and the direct-serve `streamlink_serve_cmd` call (`:5381`) must pass `tier=self.quality_tier` into `streamlink_fanout_cmd` / `streamlink_serve_cmd`. Locate the `streamlink_fanout_cmd(` call inside `_serve_fanout` and the `streamlink_serve_cmd(` call at `:5381` and add `tier=self.quality_tier`.

POV construction (`:5526`): replace the `fmt=YTDLP_FORMAT_POV` argument with the pinned-robust state. Since `Feed.__init__` no longer needs `fmt`, set POV's tier after construction (keep the change minimal):

```python
        self.pov = Feed(..., cookie_dir=cookie_dir)   # drop fmt=YTDLP_FORMAT_POV
        self.pov.quality_tier = "robust"              # PiP: 720p + robust profile, never auto/exposed
        self.pov.quality_pinned = True
```
If `Feed.__init__` still declares a `fmt=` parameter, leave the parameter in place but stop reading `self.fmt` in `run()` (superseded by `quality_ytdlp_fmt(self.quality_tier)`); mark `YTDLP_FORMAT_POV` as retained-for-reference or remove it if now unused (grep first: `grep -n YTDLP_FORMAT_POV src/`). Removing it is preferred if the only reference was the POV construction.

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): per-feed quality tier, POV pinned-robust, new-source reset (#493)"
```

---

### Task 4: Auto-step-down firing → Discord @here + health incident

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `run()` after the `dead_serves += 1` (`:5435`); `Relay` wiring near `self.A.on_recovery = ...` (`:5494`); new `discord_step_down_payload` (near `discord_failover_payload` `:638`); new `Relay._record_feed_step_down` (near `_record_feed_recovery` `:6442`)
- Test: `tests/test_pov.py`

**Interfaces:**
- Consumes: `Feed.maybe_step_down` (Task 3), the existing `self._discord_post(payload, tag)` and `self.health_store.record_event(...)`.
- Produces: `discord_step_down_payload(feed, stint, from_tier, to_tier, event_title="", producer="") -> dict`; `Relay._record_feed_step_down(feed, stint, from_tier, to_tier)`; a `feed_step_down` health event.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_pov.py`:

```python
def t_discord_step_down_payload():
    p = fe.discord_step_down_payload("A", 3, "full", "robust",
                                     event_title="N24", producer="Box")
    assert p["content"] == "@here"                       # actionable
    assert p["allowed_mentions"]["parse"] == ["everyone"]
    body = json.dumps(p)
    assert "robust" in body.lower() and "Feed A" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_pov.py`
Expected: FAIL (no attribute `discord_step_down_payload`).

- [ ] **Step 3: Implement**

Add near `discord_failover_payload` (`:638`):

```python
def discord_step_down_payload(feed, stint, from_tier, to_tier, event_title="", producer=""):
    """Discord webhook JSON for an auto quality step-down (#493). @here in top-level
    content — actionable: the source is struggling and the director must decide the
    manual step-up. Pure → unit-tested."""
    desc = (f"Feed {feed} (stint {stint}) could not sustain **{from_tier}** — the relay "
            f"automatically reduced it to **{to_tier}** (720p) to keep a continuous "
            "picture. Step-up is manual: raise it again from the Director Panel once the "
            "source recovers.")
    embed = {"title": "📉 Quality step-down — source struggling",
             "description": desc, "color": HEALTH_COLORS["yellow"]}
    footer = notify._footer(event_title, producer)
    if footer:
        embed["footer"] = {"text": footer}
    return {"username": "GT Racecast",
            "content": "@here",
            "allowed_mentions": {"parse": ["everyone"]},
            "embeds": [embed]}
```

Add near `_record_feed_recovery` (`:6442`):

```python
    def _record_feed_step_down(self, feed, stint, from_tier, to_tier):
        """Feed.on_step_down callback: an auto quality step-down happened. Record a
        `feed_step_down` health incident (post-event report + health monitor) AND fire a
        Discord @here — it is actionable. Best-effort; never raises into the feed loop."""
        now = time.time()
        if self.health_store is not None:
            try:
                self.health_store.record_event(
                    now, "feed_step_down", producer=self.producer_name,
                    metadata={"feed": feed, "stint": stint,
                              "from": from_tier, "to": to_tier})
            except Exception:                # noqa: BLE001 — best-effort
                pass
        LOG.warning("feed step-down: Feed %s stint %d %s->%s — @here posted",
                    feed, stint, from_tier, to_tier)
        try:
            self._discord_post(
                discord_step_down_payload(feed, stint, from_tier, to_tier,
                                          self._event_title(), self.producer_name),
                "feed-step-down")
        except Exception:                    # noqa: BLE001 — best-effort
            pass
```

Wire it where `on_recovery` is wired (`:5494`):

```python
        self.A.on_step_down = self._record_feed_step_down
        self.B.on_step_down = self._record_feed_step_down
        # POV stays pinned-robust: no on_step_down.
```

In `run()`, right after the `self.dead_serves += 1` block (`:5435`), fire the step-down:

```python
                stepped = self.maybe_step_down()
                if stepped and self.on_step_down is not None:
                    try:
                        self.on_step_down(self.name, i + 1, stepped[0], stepped[1])
                    except Exception:        # noqa: BLE001 — best-effort telemetry
                        pass
```
(`i` is the stint index already in scope in `run()`; confirm the variable name at the `dead_serves += 1` site and use it.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_pov.py
git commit -m "feat(relay): auto step-down fires @here ping + health incident (#493)"
```

---

### Task 5: Manual switch endpoint, director gating, status exposure

**Files:**
- Modify: `src/scripts/console_policy.py` (`:83`); `src/relay/racecast-feeds.py` — `Relay.set_feed_quality`, the `do_POST` dispatch (near the `/obs/*` routes), `Relay.status()` feed dict, `_health_current` (`:7383`)
- Test: `tests/test_console.py`, `tests/test_console_gate.py`, `tests/test_pov.py`

**Interfaces:**
- Consumes: `parse_quality_tier` (Task 1), `Feed.set_quality` (Task 3).
- Produces: `Relay.set_feed_quality(which, tier) -> dict`; route `POST /feed/<A|B>/quality`; `feeds.<X>.profile` + `feeds.<X>.pinned` in `status()` and `_health_current`.

- [ ] **Step 1: Write the failing tests**

`tests/test_console.py` / `tests/test_console_gate.py` — assert `/feed/A/quality` (and `/feed/B/quality`) map to `Requirement(DIRECTOR, False)` (mirror the existing `feed activate/deactivate` assertions):

```python
def t_feed_quality_is_director():
    import console_policy as cp
    assert cp.min_capability(["feed", "A", "quality"], "POST") == cp.Requirement(cp.DIRECTOR, False)
    assert cp.min_capability(["feed", "B", "quality"], "POST") == cp.Requirement(cp.DIRECTOR, False)
```

`tests/test_pov.py` — `set_feed_quality` routes to the feed and applies `auto` as a release:

```python
def t_set_feed_quality_applies_and_releases(...):
    # construct a minimal Relay with feeds A/B (reuse this file's Relay test harness);
    # r.set_feed_quality("A", "emergency") -> A.quality_tier=="emergency", pinned True
    # r.set_feed_quality("A", "auto")      -> A.quality_tier=="full", pinned False
    # r.set_feed_quality("A", "bogus")     -> returns {"error": ...}, no state change
```
(Use the Relay construction already exercised in `tests/test_pov.py`; if none exists there, place this test in the relay-endpoint test file used for `/obs/*` and assert via `Relay.set_feed_quality` directly.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_console_gate.py` and `python3 tests/test_pov.py`
Expected: FAIL.

- [ ] **Step 3: Implement**

`src/scripts/console_policy.py` (`:83`) — extend the tuple:

```python
    if len(p) == 3 and p[0] == "feed" and p[2] in ("activate", "deactivate", "quality"):
        return Requirement(DIRECTOR, False)   # feed arm/disarm (#492) + quality profile (#493)
```

`Relay.set_feed_quality` (near the other feed-control relay methods):

```python
    def set_feed_quality(self, which, tier):
        """Director control: set a feed's quality profile. `tier` is one of
        full|robust|emergency (a manual pin) or `auto` (release to managed FULL).
        Returns the feed's resulting {profile, pinned}, or {"error": ...}."""
        feed = self.feeds.get(which)
        if feed is None:
            return {"error": f"unknown feed {which}"}
        if tier == "auto":
            feed.set_quality("full", False)
        else:
            feed.set_quality(tier, True)
        return {"feed": which, "profile": feed.quality_tier, "pinned": feed.quality_pinned}
```

`do_POST` — add next to the `/obs/*` routes (same console_policy gating already applied there), matching `POST /feed/<A|B>/quality`. Parse the tier from the body/query, `parse_quality_tier` it, 400 on `None`, and dispatch:

```python
            if len(seg) == 3 and seg[0] == "feed" and seg[2] == "quality":
                which = seg[1].upper()
                tier = parse_quality_tier(_body_or_query(...))   # reuse the file's body/query reader
                if which not in ("A", "B") or tier is None:
                    self._json(400, {"error": "usage: POST /feed/<A|B>/quality tier=full|robust|emergency|auto"})
                    return
                self._json(200, relay.set_feed_quality(which, tier))
                return
```
Follow the exact request-parsing + `console_policy.decide(...)` gating pattern the sibling `/obs/*` POST branch uses in this handler; do not invent a new auth path.

`Relay.status()` feed dict — add the profile/pin to each feed entry (find where the per-feed dict with `"state"/"stint"` is built) :

```python
            "profile": f.quality_tier,
            "pinned": f.quality_pinned,
```

`_health_current` (`:7383`) — mirror them into the redacted feed dict:

```python
                feeds[k] = {"state": v.get("state"), "down": v.get("down"),
                            "stint": v.get("stint"), "state_age_s": v.get("state_age_s"),
                            "quality": q, "profile": v.get("profile"), "pinned": v.get("pinned")}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_console_gate.py`, `python3 tests/test_console.py`, `python3 tests/test_pov.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/console_policy.py src/relay/racecast-feeds.py tests/
git commit -m "feat(relay): POST /feed/<A|B>/quality director control + status profile fields (#493)"
```

---

### Task 6: Director Panel — profile control, served resolution, source-max hint, step-down alert

**Files:**
- Modify: `src/director/director-panel.html` (+ any panel JS/CSS colocated in `src/director/`)
- Modify (screenshot): `src/docs/wiki/images/director-panel.png`
- Test: manual render via `ui-visual-verification`; `tests/test_ui_server.py` only if a panel data route changes (it does not — the panel reads the relay `/status` + posts to `/feed/<A|B>/quality`).

**Interfaces:**
- Consumes: `/status` (or the panel's existing relay-status poll) fields `feeds.<X>.profile`, `.pinned`, `.quality`; posts to `POST /feed/<A|B>/quality` via the panel's existing relay-call helper (`relayCall`/`RC_API`).

- [ ] **Step 1: Add the per-feed control** in the panel's feed section: a profile selector with the four actions **FULL / ROBUST / EMERGENCY / AUTO** (buttons or a segmented control matching the existing panel control styling — reuse the cue-compose / feed-control classes, do NOT introduce unstyled browser controls). The current profile renders as a badge; EMERGENCY styled loud (the panel's warn/danger token); a manual pin shown distinctly from AUTO.

- [ ] **Step 2: Show served resolution + source-max hint** next to the profile: render `feeds.<X>.quality` (e.g. "720p60"); when `profile === "full"` and `quality_height(quality) < 1080`, show the hint text **"source max <n>p — no 1080p"** (compute the height client-side with a small JS mirror of `quality_height`, or read a `source_capped` boolean if you prefer to compute it server-side — pick one and keep the backend emitting facts).

- [ ] **Step 3: Surface the auto-step-down alert** — when a feed's profile is ROBUST and not pinned (i.e. auto-dropped), show a panel alert row ("Feed A → ROBUST · source struggling") consistent with how the panel renders drop/churn alerts.

- [ ] **Step 4: Wire the buttons** to `POST /feed/<A|B>/quality` with `tier=` the chosen value, via the panel's existing relay-call helper (works over Funnel under `/console`). Confirm a click re-polls status so the badge updates.

- [ ] **Step 5: Visual verification (REQUIRED)** — follow the `ui-visual-verification` skill: boot the demo relay + obs-sim, element-screenshot the feed control (e.g. `#feeds` card) at a realistic width, `Read` the PNG, and check theme fit / alignment / the EMERGENCY loud state / the disabled-vs-active button states / the hint rendering. Fix and re-shoot until correct. Then record the marker:

```bash
python3 .claude/hooks/record_ui_verified.py src/director/director-panel.html
```

- [ ] **Step 6: Regenerate the committed wiki screenshot (REQUIRED, same change)** — via the `wiki-screenshots` skill, recapture `src/docs/wiki/images/director-panel.png` from the running demo build (dev-build version badge). Commit it with the code.

- [ ] **Step 7: Commit**

```bash
git add src/director/ src/docs/wiki/images/director-panel.png
git commit -m "feat(panel): per-feed quality profile control + served-res/source-max hint (#493)"
```

---

### Task 7: Companion buttons for the quality profiles

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig` (and the `export companion` generator in `src/scripts/…` if the config is generated rather than hand-edited — grep `export companion` / the buttons module first)
- Modify (screenshot): the relevant `src/docs/wiki/images/companion-page*-*.png`
- Test: `tests/test_companion.py` if the generator has pure helpers touched (else none).

**Interfaces:**
- Consumes: the relay endpoint `POST /feed/<A|B>/quality` (Generic-HTTP module, same pattern as the existing feed/OBS buttons).

- [ ] **Step 1: Add per-feed profile buttons** (Feed A + Feed B: FULL / ROBUST / EMERGENCY / AUTO) firing `POST /feed/<A|B>/quality` with the tier, mirroring the existing relay-control buttons' Generic-HTTP action shape and page layout. Keep the exported config **password-blanked** (build re-strips, but do not introduce a password).

- [ ] **Step 2: Regenerate the affected Companion screenshot(s)** via the `companion-screenshots` skill and commit alongside.

- [ ] **Step 3: Commit**

```bash
git add src/companion/ src/docs/wiki/images/companion-page*.png
git commit -m "feat(companion): per-feed quality profile buttons (#493)"
```

---

### Task 8: `.env.example`, soak harness, self-review sweep

**Files:**
- Modify: `.env.example`; `tools/fanout-soak.py`
- Test: `tests/test_fanout.py` (if a pure helper is added to the soak); `python3 tools/run-tests.py` (full suite)

- [ ] **Step 1: Document the flag** — add to `.env.example` under the feed section:

```
# #493 robust ingest: auto FULL->ROBUST (720p) step-down when a source can't sustain 1080p.
# Default ON. =0 disables ONLY the automatic step-down (manual profile switching stays).
RACECAST_FEED_ROBUST_AUTO=1
```

- [ ] **Step 2: Extend the soak harness** — add a `--switch-to {full,robust,emergency}` option to `tools/fanout-soak.py` that, after N seconds, rebuilds the source pull at the chosen tier (call `streamlink_serve_flags`/`quality_twitch_selector` as appropriate) so a maintainer can watch a manual switch hold a continuous 720p picture on a jittery source. Keep it serve-and-log only (no relay coupling), line-buffered stdout, Ctrl-C-safe — matching the file's existing conventions.

- [ ] **Step 3: Full suite green**

Run: `python3 tools/run-tests.py`
Expected: all pass. Then `python3 tools/lint.py`.

- [ ] **Step 4: Commit**

```bash
git add .env.example tools/fanout-soak.py tests/
git commit -m "chore(relay): RACECAST_FEED_ROBUST_AUTO env + soak manual-switch option (#493)"
```

---

## Self-Review

- **Spec coverage:** three profiles (T1/T2/T3), both platforms (T1/T2), auto FULL→ROBUST + 720p floor + source_state gate + kill-switch (T3/T4), @here + panel alert + incident (T4/T6), manual switch both directions + EMERGENCY operator-only (T5), pin suppresses auto / AUTO releases (T3/T5), reset at new source (T3), FULL=best≤1080 + source-max hint (T5 status + T6 UI), Director Panel + Companion + screenshots (T6/T7), env + soak (T8). ✅
- **Type consistency:** tier strings are the exact set `full|robust|emergency` (+ `auto` only at the endpoint/`parse_quality_tier`, never stored). `quality_step_down_due` / `maybe_step_down` / `set_quality` signatures match across tasks. `feeds.<X>.profile` == `quality_tier` everywhere.
- **Placeholders:** none — each code step carries the actual code; UI/Companion steps carry concrete instructions bounded by the existing patterns they must mirror.
- **Risk notes:** the run-loop wiring (T3/T4) is the only threaded integration — its decision logic is covered by pure tests (`quality_step_down_due`, `maybe_step_down`); the soak (T8) is the live confirmation. POV pinning removes `YTDLP_FORMAT_POV` — grep before deleting.
