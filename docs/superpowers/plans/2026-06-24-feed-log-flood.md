# Feed-log flood fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the streamlink pump from flooding a feed log (the observed 662 MB/day) and from writing manifest tokens, by throttling repeated lines and shortening long URLs at the single choke point `logsetup.pump_subprocess`.

**Architecture:** Three pure, independently testable units in `src/scripts/logsetup.py` — `shorten_urls` (compact long URLs, drop `sig`/`lsig`, keep `itag`), `normalize_for_dedup` (dedup key), and `LineThrottle` (dedup + rate-limit, injected clock) — wired into `pump_subprocess`. Both the relay feeds and static streams pump through this one function, so both benefit with no duplication.

**Tech Stack:** Python 3 stdlib only (`re`, `logging`, `time`). Tests are stdlib runnable scripts (no pytest).

## Global Constraints

- **Edit only under `src/` and `tests/`** (plus the already-committed `docs/` spec). (CLAUDE.md)
- **English only** in all code, comments, and log strings. (CLAUDE.md)
- **Stdlib only — no new dependency.** `logsetup.py` must NOT import `config.py` (the relay stays dependency-light). (file docstring)
- **`pump_subprocess` best-effort contract:** a failure in throttling/shortening must NEVER break the pump thread — fall back to logging the raw line; never let the daemon thread die.
- **`on_line` runs for every line, before throttling** — quality parsing is unaffected.
- **`classify_subproc_line` runs on the ORIGINAL line** (its hints `forbidden`/`403`/`retry` live in the message text, not the URL).
- **No size cap / no size-based rotation** (YAGNI) — rotation stays purely time-based.
- **Constants** (module-level, named): `URL_SHORTEN_MAX = 120`, `LINE_THROTTLE_RATE_MAX = 30`, `LINE_THROTTLE_WINDOW_S = 10.0`, `LINE_THROTTLE_SUMMARY_S = 30.0`. No env override.
- **Summary strings (verbatim):** `(last line repeated ×N)`, `(previous line repeated ×N)`, `(suppressed N lines)` — the `×` is U+00D7 MULTIPLICATION SIGN, identical in impl and tests.
- **Run after Python changes:** `python3 tools/lint.py`. **Before shipping:** `python3 tools/run-tests.py` and `python3 tools/build.py`.

---

### Task 1: `shorten_urls` + `normalize_for_dedup` (pure helpers)

**Files:**
- Modify: `src/scripts/logsetup.py` — add two pure helpers + their constant, near `classify_subproc_line` (line 129) / `tag_line` (line 139).
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: nothing (pure, stdlib `re`).
- Produces:
  - `shorten_urls(text, max_len=URL_SHORTEN_MAX) -> str` — replaces each `http(s)://…` run longer than `max_len` with `"<scheme>://<host>/…(itag <n>, +<elided> chars elided)"` (the `itag <n>, ` part only when an `itag/<n>` or `itag=<n>` is present); shorter URLs and non-URL text unchanged.
  - `normalize_for_dedup(text) -> str` — every URL run → `<url>`, every digit run → `<n>`.
  - Module constant `URL_SHORTEN_MAX = 120`.
  - Module-level compiled regexes `_URL_RE`, `_ITAG_RE`, `_DIGITS_RE`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_logs.py` (after `t_classify_subproc_line_levels`, before `t_tag_line_prefixes_and_strips_eol`):

```python
def t_shorten_urls_elides_long_url_keeps_itag():
    url = ("https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1781/"
           "itag/301/sig/SECRETSIG/lsig/SECRETLSIG/playlist/index.m3u8" + "z" * 120)
    line = "Unable to open URL: " + url + " (403 Forbidden)"
    out = lg.shorten_urls(line)
    assert "manifest.googlevideo.com" in out
    assert "itag 301" in out
    assert "SECRETSIG" not in out and "SECRETLSIG" not in out   # tokens elided
    assert "(403 Forbidden)" in out                             # non-URL text preserved
    assert len(out) < len(line)


def t_shorten_urls_leaves_short_url_and_plain_text():
    assert lg.shorten_urls("see http://h/x now") == "see http://h/x now"
    assert lg.shorten_urls("no url at all") == "no url at all"


def t_shorten_urls_handles_two_long_urls():
    u = "https://manifest.googlevideo.com/path/" + "a" * 200
    out = lg.shorten_urls("open " + u + " for url: " + u)
    assert out.count("googlevideo.com/…") == 2
    assert ("a" * 200) not in out


def t_normalize_for_dedup_collapses_url_and_digits():
    a = "Unable to open URL: https://x.com/expire/111/sig/AAA (403 Forbidden)"
    b = "Unable to open URL: https://y.com/expire/999/sig/BBB (403 Forbidden)"
    assert lg.normalize_for_dedup(a) == lg.normalize_for_dedup(b)
    assert lg.normalize_for_dedup("alpha line") != lg.normalize_for_dedup("beta line")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `AttributeError: module 'logsetup' has no attribute 'shorten_urls'`.

- [ ] **Step 3: Implement the helpers**

In `src/scripts/logsetup.py`, add immediately after `classify_subproc_line` (i.e. after line 137, before `def tag_line`):

```python
URL_SHORTEN_MAX = 120
_URL_RE = re.compile(r"https?://[^\s]+")
_ITAG_RE = re.compile(r"[/=]itag[/=](\d+)")
_DIGITS_RE = re.compile(r"\d+")


def shorten_urls(text, max_len=URL_SHORTEN_MAX):
    """Replace each URL longer than max_len with a compact host-only form, dropping
    the path+query (where googlevideo sig/lsig tokens live) and keeping the itag for
    diagnostics. URLs <= max_len and non-URL text are returned unchanged. Pure."""
    def _shrink(match):
        url = match.group(0)
        if len(url) <= max_len:
            return url
        scheme, _, after = url.partition("://")
        host = after.split("/", 1)[0].split("?", 1)[0]
        elided = len(url) - len(scheme) - len("://") - len(host)
        itag = _ITAG_RE.search(url)
        tag = f"itag {itag.group(1)}, " if itag else ""
        return f"{scheme}://{host}/…({tag}+{elided} chars elided)"
    return _URL_RE.sub(_shrink, text)


def normalize_for_dedup(text):
    """A dedup key that ignores the volatile parts of a repeated line: every URL
    becomes <url> and every digit run becomes <n>, so the same error with a
    different expired URL / timestamp maps to one key. Pure."""
    return _DIGITS_RE.sub("<n>", _URL_RE.sub("<url>", text))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_logs.py`
Expected: `ALL PASS` (existing tests plus the four new ones).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/scripts/logsetup.py`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): add shorten_urls + normalize_for_dedup pure helpers"
```

---

### Task 2: `LineThrottle` (dedup + rate-limit)

**Files:**
- Modify: `src/scripts/logsetup.py` — add the `LineThrottle` class + its constants, after `normalize_for_dedup` (from Task 1).
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: `normalize_for_dedup` (Task 1); `logging` levels.
- Produces:
  - Constants `LINE_THROTTLE_RATE_MAX = 30`, `LINE_THROTTLE_WINDOW_S = 10.0`, `LINE_THROTTLE_SUMMARY_S = 30.0`.
  - `class LineThrottle` with `__init__(self, rate_max=…, window_s=…, summary_s=…)`, `emit(self, level, text, now) -> list[(int, str)]`, and `flush(self, now) -> list[(int, str)]`. `text` is assumed already URL-shortened by the caller; `now` is a monotonic float. Returned tuples are `(logging level, message text WITHOUT the [tag] prefix)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_logs.py` (after the Task 1 tests):

```python
def t_throttle_collapses_identical_flood():
    th = lg.LineThrottle()
    out = []
    for _ in range(1000):
        out += th.emit(logging.ERROR, "Unable to open URL: x (403)", 1000.0)
    out += th.flush(1000.0)
    texts = [t for _lvl, t in out]
    assert texts[0] == "Unable to open URL: x (403)"      # first occurrence emitted
    assert any("repeated ×999" in t for t in texts)       # the rest counted
    assert len(out) <= 3                                  # ~one real line + a summary
    assert all(lvl == logging.ERROR for lvl, _t in out)   # summary keeps the flood's level


def t_throttle_rate_limits_distinct_lines():
    th = lg.LineThrottle(rate_max=5, window_s=10.0, summary_s=30.0)
    out = []
    for i in range(20):
        out += th.emit(logging.INFO, "line " + chr(97 + i) + " alpha", 1000.0)
    out += th.flush(1000.0)
    emitted = [t for _lvl, t in out if "suppressed" not in t]
    assert len(emitted) == 5                              # capped at rate_max in the window
    assert any(lvl == logging.WARNING and "suppressed 15 lines" in t for lvl, t in out)


def t_throttle_flushes_dup_summary_on_pattern_change():
    th = lg.LineThrottle()
    out = []
    out += th.emit(logging.WARNING, "retrying connection", 1000.0)
    for _ in range(4):
        out += th.emit(logging.WARNING, "retrying connection", 1000.0)
    out += th.emit(logging.INFO, "stream opened", 1000.0)
    texts = [t for _lvl, t in out]
    assert texts == ["retrying connection", "(previous line repeated ×4)", "stream opened"]


def t_throttle_periodic_summary_while_flooding():
    th = lg.LineThrottle(summary_s=30.0)
    out = []
    out += th.emit(logging.ERROR, "boom", 1000.0)         # emitted
    out += th.emit(logging.ERROR, "boom", 1010.0)         # dup, 10s < 30 -> no summary
    out += th.emit(logging.ERROR, "boom", 1035.0)         # dup, 35s >= 30 -> summary
    texts = [t for _lvl, t in out]
    assert texts == ["boom", "(last line repeated ×2)"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_logs.py`
Expected: FAIL — `AttributeError: module 'logsetup' has no attribute 'LineThrottle'`.

- [ ] **Step 3: Implement `LineThrottle`**

In `src/scripts/logsetup.py`, add immediately after `normalize_for_dedup`:

```python
LINE_THROTTLE_RATE_MAX = 30
LINE_THROTTLE_WINDOW_S = 10.0
LINE_THROTTLE_SUMMARY_S = 30.0


class LineThrottle:
    """Per-stream throttle for pumped subprocess lines. Collapses consecutive
    duplicate-after-normalization lines (emitting a periodic '(last line repeated
    ×N)' at the line's own level, plus a '(previous line repeated ×N)' when the
    pattern changes) AND rate-limits distinct lines to rate_max per window_s (excess
    dropped, surfaced as a WARNING '(suppressed N lines)'). Pure given an injected
    monotonic clock. One instance per pump_subprocess call -> per feed, thread-isolated."""

    def __init__(self, rate_max=LINE_THROTTLE_RATE_MAX,
                 window_s=LINE_THROTTLE_WINDOW_S, summary_s=LINE_THROTTLE_SUMMARY_S):
        self.rate_max = rate_max
        self.window_s = window_s
        self.summary_s = summary_s
        self.last_key = None
        self.last_level = logging.INFO
        self.dup_count = 0
        self.last_summary_at = 0.0
        self.window_start = 0.0
        self.window_count = 0
        self.dropped_in_window = 0

    def emit(self, level, text, now):
        """Return the (level, text) records to log for one incoming line."""
        key = normalize_for_dedup(text)
        out = []
        if key == self.last_key:                       # consecutive duplicate
            self.dup_count += 1
            if now - self.last_summary_at >= self.summary_s:
                out.append((self.last_level, f"(last line repeated ×{self.dup_count})"))
                self.last_summary_at = now
            return out
        if self.dup_count > 0:                          # a new, distinct line ends a dup run
            out.append((self.last_level, f"(previous line repeated ×{self.dup_count})"))
            self.dup_count = 0
        self.last_key = key
        self.last_level = level
        self.last_summary_at = now
        if now - self.window_start >= self.window_s:    # roll the rate-limit window
            if self.dropped_in_window > 0:
                out.append((logging.WARNING, f"(suppressed {self.dropped_in_window} lines)"))
                self.dropped_in_window = 0
            self.window_start = now
            self.window_count = 0
        if self.window_count < self.rate_max:
            self.window_count += 1
            out.append((level, text))
        else:
            self.dropped_in_window += 1
        return out

    def flush(self, now):
        """Emit any pending summary at EOF so a trailing flood still reports its count."""
        out = []
        if self.dup_count > 0:
            out.append((self.last_level, f"(previous line repeated ×{self.dup_count})"))
            self.dup_count = 0
        if self.dropped_in_window > 0:
            out.append((logging.WARNING, f"(suppressed {self.dropped_in_window} lines)"))
            self.dropped_in_window = 0
        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_logs.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/scripts/logsetup.py`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "feat(logs): add LineThrottle (dedup + rate-limit) for pumped lines"
```

---

### Task 3: Rewire `pump_subprocess`

**Files:**
- Modify: `src/scripts/logsetup.py` — `pump_subprocess` (lines 146-161): add a `now=time.monotonic` parameter, shorten + throttle each line, flush at EOF, keep the best-effort contract.
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: `shorten_urls` (Task 1), `LineThrottle` (Task 2), `classify_subproc_line` (existing).
- Produces: `pump_subprocess(stream, logger, tag, on_line=None, now=time.monotonic)` — unchanged behaviour for distinct lines (each logged once, prefixed `[tag]`), but a repeated flood is collapsed and long URLs are shortened. `on_line` still receives every original line.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logs.py` (after `t_pump_subprocess_on_line_hook`):

```python
def t_pump_throttles_identical_flood_and_strips_tokens():
    import io
    records = []

    class _Cap(logging.Handler):
        def emit(self, r):
            records.append((r.levelno, r.getMessage()))

    logger = logging.getLogger("t.pump.flood")
    logger.handlers = [_Cap()]
    logger.setLevel(logging.DEBUG)
    url = "https://manifest.googlevideo.com/itag/301/sig/SECRETTOKEN/" + "z" * 200
    one = "[cli][error] Unable to fetch new streams: Unable to open URL: " + url + " (403 Forbidden)\n"
    seen = []
    lg.pump_subprocess(io.StringIO(one * 500), logger, "streamlink",
                       on_line=seen.append, now=lambda: 1000.0)
    msgs = [m for _lvl, m in records]
    assert len(records) <= 4                              # 500 identical -> a handful
    assert any("repeated ×499" in m for m in msgs)        # the rest counted
    assert all("SECRETTOKEN" not in m for m in msgs)      # manifest token stripped
    assert len(seen) == 500                               # on_line saw every original line
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_logs.py`
Expected: FAIL — the current `pump_subprocess` logs all 500 lines verbatim, so `len(records) <= 4` fails and `SECRETTOKEN` is present.

- [ ] **Step 3: Rewire `pump_subprocess`**

In `src/scripts/logsetup.py`, replace the whole `pump_subprocess` function (lines 146-161) with:

```python
def pump_subprocess(stream, logger, tag, on_line=None, now=time.monotonic):
    """Read text lines from a subprocess pipe (stream) and log each at a classified
    level, prefixed `[tag]`. Repeated lines are throttled and long URLs shortened
    (LineThrottle + shorten_urls) so a stuck retry loop can't flood the log; the
    first occurrence and periodic counts survive. When on_line is given, call it per
    (stripped) ORIGINAL line for side-channel parsing (e.g. feed quality) — a failing
    callback never breaks the pump. Runs to EOF; swallows read errors. Designed for a
    daemon thread."""
    throttle = LineThrottle()
    try:
        for raw in iter(stream.readline, ""):   # sentinel "" stops at EOF
            line = raw.rstrip("\n").rstrip("\r")
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:                # noqa: BLE001 — observer is best-effort
                    pass
            try:
                level = classify_subproc_line(line)   # classify the ORIGINAL line
                for lvl, text in throttle.emit(level, shorten_urls(line), now()):
                    logger.log(lvl, "[%s] %s", tag, text)
            except Exception:                    # noqa: BLE001 — throttling must never break the pump
                logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
    except (ValueError, OSError):
        pass  # pipe closed mid-read — end the thread, never the daemon
    finally:
        try:
            for lvl, text in throttle.flush(now()):   # surface a trailing flood's count
                logger.log(lvl, "[%s] %s", tag, text)
        except Exception:                        # noqa: BLE001 — flush is best-effort too
            pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_logs.py`
Expected: `ALL PASS` — the new flood test plus the unchanged `t_pump_subprocess_logs_each_line` (two distinct lines still logged once each) and `t_pump_subprocess_on_line_hook` (still sees every line, still survives a raising callback).

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: no findings for `src/scripts/logsetup.py`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/logsetup.py tests/test_logs.py
git commit -m "fix(logs): throttle + URL-shorten the streamlink pump (stops feed-log flood)"
```

---

### Task 4: Full-suite + build verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: all test scripts pass — in particular `test_logs.py` and `test_streams.py` (the static-stream path also pumps through `pump_subprocess`).

- [ ] **Step 2: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 3: Build verify**

Run: `python3 tools/build.py`
Expected: build completes and the verify step passes (no secrets, no shell scripts, etc.). (Missing media/graphics `[warn]` lines are expected — they are gitignored runtime assets.)

- [ ] **Step 4: Manual smoke (optional)**

Synthesize a flood through the real pump and eyeball the output:

```bash
python3 - <<'PY'
import io, logging, sys
sys.path.insert(0, "src/scripts")
import logsetup as lg
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
url = "https://manifest.googlevideo.com/itag/301/sig/TOKEN/" + "z"*300
flood = ("[cli][error] Unable to fetch new streams: Unable to open URL: " + url + " (403 Forbidden)\n")*200
lg.pump_subprocess(io.StringIO(flood), logging.getLogger("smoke"), "streamlink")
PY
```

Expected: one shortened ERROR line (no `TOKEN`, `itag 301` present) plus a `(previous line repeated ×199)` summary — not 200 multi-KB lines.

---

## Self-Review

**Spec coverage:**
- `shorten_urls` (compact long URLs, drop sig/lsig, keep itag, multi-URL, short/plain unchanged) → Task 1. ✓
- `normalize_for_dedup` (URL→`<url>`, digits→`<n>`, two 403s collapse) → Task 1. ✓
- `LineThrottle` dedup + periodic summary at the flood's level → Task 2 (`t_throttle_collapses_identical_flood`, `t_throttle_periodic_summary_while_flooding`). ✓
- `LineThrottle` rate-limit of distinct lines + `(suppressed N lines)` → Task 2 (`t_throttle_rate_limits_distinct_lines`). ✓
- Pattern change flushes `(previous line repeated ×N)` → Task 2 (`t_throttle_flushes_dup_summary_on_pattern_change`). ✓
- `flush(now)` for a trailing flood → Task 2 (`t_throttle_collapses_identical_flood` uses flush) + Task 3 (pump flushes at EOF). ✓
- `pump_subprocess` wiring: `on_line` every line, classify on original, best-effort fallback, `now` injectable → Task 3. ✓
- Tokens stripped from the log → Task 3 (`t_pump_throttles_identical_flood_and_strips_tokens`). ✓
- Both relay + static streams benefit (single choke point) → Task 4 runs `test_streams.py`; no per-caller change needed. ✓
- No size cap, stdlib only, English only → constraints honored (no handler/rotation change). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has an expected result.

**Type consistency:** `shorten_urls`/`normalize_for_dedup` defined in Task 1 and consumed by `LineThrottle` (Task 2) / `pump_subprocess` (Task 3); `LineThrottle.emit`/`flush` return `list[(int level, str text)]` consistently across Tasks 2-3; the `×` (U+00D7) and the exact summary strings match between the Task 2 implementation, the Task 2 tests, and the Task 3 flood test (`repeated ×N`, `suppressed N lines`); constant names (`URL_SHORTEN_MAX`, `LINE_THROTTLE_*`) match between definition and use.
