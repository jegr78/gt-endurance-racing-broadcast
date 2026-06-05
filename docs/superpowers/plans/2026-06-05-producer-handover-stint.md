# Producer Handover — Start Relay at a Given Stint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A producer taking over mid-event starts a fresh relay positioned at the
stint currently on air (`--stint N` flag + `/set/stint/<n>` correction endpoint +
documented handover checklist).

**Architecture:** A pure helper `stint_start_indices(stint, schedule_len)` in
`src/relay/iro-feeds.py` maps a 1-based stint number to clamped 0-based Feed A/B
start indices (A = stint N "on air now", B = N+1 preloaded). `Relay.__init__` gains a
`start_stint` parameter; a new `Relay.set_stint()` backs the `GET /set/stint/<n>`
endpoint. `iro relay start/run` already forward extra argv to the relay, so only
`iro event start` needs a tiny `--stint` extractor. Docs: handover checklist in the
wiki + small mentions in README/CLAUDE.md.

**Tech Stack:** Pure Python stdlib (project convention: no pytest — each test file is
a runnable script auto-discovered by `tools/run-tests.py`).

**Spec:** `docs/superpowers/specs/2026-06-05-producer-handover-stint-design.md`

**Key facts for the implementer (zero-context primer):**
- The relay (`src/relay/iro-feeds.py`) runs two `Feed` objects: A (port 53001) and
  B (53002), each holding a 0-based schedule index `idx`. `/next` advances the
  lower-index feed by +2 — the ping-pong works from ANY starting pair, so there is
  no global "A=odd stints" rule to preserve.
- `Feed.set_index()` clamps to the schedule itself and kills the serving
  subprocess; constructing `Relay` does NOT start threads or open ports
  (`relay.start()` does) — so tests can build a `Relay` safely.
- `iro relay start --stint 3` needs NO dispatcher change: `relay_start(rest)` /
  `relay_run(rest)` in `src/iro.py` already append `rest` to the relay argv (both
  repo and frozen mode). Only `event_start()` calls `relay_start([])` with a hard
  empty list.
- Tests import `iro-feeds.py` (dash in name) via `importlib.util.spec_from_file_location`
  — copy the loader header from `tests/test_pov.py`.
- `tools/run-tests.py` auto-discovers `tests/test_*.py` — a new file needs no wiring.
- Hard rules: edit only under `src/` (+ `tests/`, docs); English only; no secrets.

---

### Task 1: `stint_start_indices()` pure helper

**Files:**
- Create: `tests/test_stint.py`
- Modify: `src/relay/iro-feeds.py` (add one module-level function, near the other
  pure helpers — e.g. directly above `class ScheduleSource`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_stint.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the producer-handover stint positioning.
Run: python3 tests/test_stint.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_indices_default_stint_1():
    # stint 1 == today's behaviour, bit-for-bit: A=0, B=1 (B=0 on 1-stint schedules)
    assert m.stint_start_indices(1, 8) == (0, 1)
    assert m.stint_start_indices(1, 2) == (0, 1)
    assert m.stint_start_indices(1, 1) == (0, 0)
    assert m.stint_start_indices(1, 0) == (0, 0)


def t_indices_takeover():
    # "--stint 3" = stint 3 is on air NOW: A serves it (idx 2), B preloads 4 (idx 3)
    assert m.stint_start_indices(3, 8) == (2, 3)
    assert m.stint_start_indices(4, 8) == (3, 4)


def t_indices_clamped():
    # beyond the schedule -> clamp to the last stint
    assert m.stint_start_indices(9, 8) == (7, 7)
    # last stint: B clamps onto A (same as 1-stint schedules today)
    assert m.stint_start_indices(8, 8) == (7, 7)


def t_indices_garbage_safe():
    # endpoint feeds raw ints in here — never produce a negative index
    assert m.stint_start_indices(0, 8) == (0, 1)
    assert m.stint_start_indices(-5, 8) == (0, 1)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_stint.py`
Expected: `AttributeError: module 'irofeeds' has no attribute 'stint_start_indices'`

- [ ] **Step 3: Write minimal implementation**

In `src/relay/iro-feeds.py`, add at module level (directly above
`class ScheduleSource`):

```python
def stint_start_indices(stint, schedule_len):
    """0-based (A, B) start indices for a producer takeover: 1-based stint
    <stint> is on air NOW -> Feed A serves it, Feed B preloads the next one.
    Both clamped to the schedule (last stint / empty schedule -> A == B)."""
    stint = max(1, int(stint))
    hi = max(0, schedule_len - 1)
    return min(stint - 1, hi), min(stint, hi)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_stint.py`
Expected: `ok t_indices_...` ×4, `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_stint.py src/relay/iro-feeds.py
git commit -m "feat(relay): stint_start_indices helper for producer takeover positioning"
```

---

### Task 2: `--stint` flag positions the feeds at startup

**Files:**
- Modify: `src/relay/iro-feeds.py` (`Relay.__init__` ~line 585, argparse ~line 807,
  validation after `args = ap.parse_args()` ~line 817, `Relay(...)` call + startup
  prints in `main()` ~line 908/945)
- Test: `tests/test_stint.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stint.py` (above the `if __name__` block):

```python
class FakeSource:
    """Minimal stand-in for ScheduleSource: get/refresh/health only."""
    def __init__(self, items): self.items = list(items)
    def get(self): return self.items
    def refresh(self, timeout=None): pass
    def health(self): return {"ok": True}


URLS8 = [f"https://www.youtube.com/watch?v=stint{i}" for i in range(1, 9)]


def t_relay_default_start_unchanged():
    r = m.Relay(FakeSource(URLS8), [53001, 53002], HERE)
    assert (r.A.idx, r.B.idx) == (0, 1)


def t_relay_start_stint_positions_feeds():
    r = m.Relay(FakeSource(URLS8), [53001, 53002], HERE, start_stint=3)
    assert (r.A.idx, r.B.idx) == (2, 3)          # A on air with stint 3, B preloads 4


def t_relay_start_stint_clamped():
    r = m.Relay(FakeSource(URLS8[:2]), [53001, 53002], HERE, start_stint=9)
    assert (r.A.idx, r.B.idx) == (1, 1)
```

(Note: constructing `Relay` does not start feeds or bind ports — safe in tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_stint.py`
Expected: `TypeError: __init__() got an unexpected keyword argument 'start_stint'`
(after the four Task-1 checks print `ok`)

- [ ] **Step 3: Implement**

In `src/relay/iro-feeds.py`:

(a) `Relay.__init__` — replace:

```python
    def __init__(self, source, ports, logdir, cookies=None, pov_source=None, pov_port=None):
        self.source = source
        self.cookies = cookies
        n = len(source.get())
        self.A = Feed("A", ports[0], 0, source.get, logdir, cookies)
        self.B = Feed("B", ports[1], 1 if n > 1 else 0, source.get, logdir, cookies)
```

with:

```python
    def __init__(self, source, ports, logdir, cookies=None, pov_source=None,
                 pov_port=None, start_stint=1):
        self.source = source
        self.cookies = cookies
        a_idx, b_idx = stint_start_indices(start_stint, len(source.get()))
        self.A = Feed("A", ports[0], a_idx, source.get, logdir, cookies)
        self.B = Feed("B", ports[1], b_idx, source.get, logdir, cookies)
```

(`stint_start_indices(1, n)` reproduces the old `0, 1 if n > 1 else 0` exactly.)

(b) argparse — after the `ap.add_argument("--ports", ...)` line add:

```python
    ap.add_argument("--stint", type=int, default=1,
                    help="1-based stint that is ON AIR right now (producer takeover): "
                         "Feed A serves it, Feed B preloads the next one. Default 1.")
```

(c) Fail-fast validation — after the existing `if not args.sheet_csv_url and not
args.sheet_id:` block add:

```python
    if args.stint < 1:
        sys.exit("ERROR: --stint must be >= 1 (1-based stint number, as in the sheet).")
```

(d) `Relay(...)` call in `main()` — replace:

```python
    relay = Relay(source, ports, logdir, cookies,
                  pov_source=pov_source, pov_port=args.pov_port)
```

with:

```python
    relay = Relay(source, ports, logdir, cookies,
                  pov_source=pov_source, pov_port=args.pov_port,
                  start_stint=args.stint)
```

(e) Startup visibility — in the final print block, directly after the
`print(f"  Feed A -> http://127.0.0.1:{ports[0]}   Feed B -> ...")` line add:

```python
    if args.stint != 1:
        if relay.A.idx != args.stint - 1:
            print(f"  WARN: --stint {args.stint} clamped to stint {relay.A.idx + 1} "
                  f"(schedule has {len(source.get())} stints).")
        print(f"  Takeover start: stint {relay.A.idx + 1} on Feed A; "
              f"Feed B preloads stint {relay.B.idx + 1}.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_stint.py`
Expected: all `ok`, `ALL PASS`
Also run (regression — relay internals touched): `python3 tests/test_pov.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_stint.py src/relay/iro-feeds.py
git commit -m "feat(relay): --stint N starts the feeds at the stint on air (producer takeover)"
```

---

### Task 3: `Relay.set_stint()` + `GET /set/stint/<n>` correction endpoint

**Files:**
- Modify: `src/relay/iro-feeds.py` (`Relay` class ~line 635, handler `do_GET`
  ~line 716, controls list in the module docstring ~line 44)
- Test: `tests/test_stint.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stint.py` (above the `if __name__` block; add
`import json, threading, urllib.request` to the imports at the top of the file):

```python
def t_set_stint_repositions_both_feeds():
    r = m.Relay(FakeSource(URLS8), [53001, 53002], HERE)
    st = r.set_stint(5)
    assert (r.A.idx, r.B.idx) == (4, 5)
    assert st["feeds"]["A"]["stint"] == 5 and st["feeds"]["B"]["stint"] == 6


def t_set_stint_endpoint_http():
    # Full round-trip through the control server (ephemeral port; feeds not started).
    r = m.Relay(FakeSource(URLS8), [53001, 53002], HERE)
    srv = m.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(r))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/set/stint/3", timeout=5).read()
    finally:
        srv.shutdown()
    st = json.loads(body)
    assert st["feeds"]["A"]["stint"] == 3 and st["feeds"]["B"]["stint"] == 4
    assert (r.A.idx, r.B.idx) == (2, 3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_stint.py`
Expected: `AttributeError: 'Relay' object has no attribute 'set_stint'`

- [ ] **Step 3: Implement**

In `src/relay/iro-feeds.py`:

(a) Add to the `Relay` class, directly below the existing `set_index` method:

```python
    def set_stint(self, stint):
        """Producer-takeover correction: 1-based stint <stint> is on air NOW ->
        Feed A serves it, Feed B preloads the next one. Tears a running feed off
        its stream (like /set) — use BEFORE going live, not mid-program."""
        self.source.refresh(timeout=6)      # clamp against fresh sheet data
        a_idx, b_idx = stint_start_indices(stint, len(self.source.get()))
        self.A.set_index(a_idx)
        self.B.set_index(b_idx)
        return self.status()
```

(b) In `do_GET`, insert **above** the existing generic
`if len(p)==3 and p[0]=="set":` line (order matters — the generic line would
swallow `/set/stint/<n>`):

```python
                if len(p)==3 and p[:2]==["set","stint"]: return self._send(relay.set_stint(int(p[2])))
```

(c) Module docstring controls list — after the `GET /set/A/<n> | /B` line add:

```
  GET /set/stint/<n>   -> producer takeover: stint <n> (1-based!) is on air now —
                           Feed A serves it, Feed B preloads <n+1> (tears running feeds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_stint.py`
Expected: all `ok`, `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_stint.py src/relay/iro-feeds.py
git commit -m "feat(relay): /set/stint/<n> repositions both feeds (takeover correction)"
```

---

### Task 4: `iro event start --stint N` forwards the flag to the relay

**Files:**
- Modify: `src/iro.py` (USAGE docstring ~line 10, new `_stint_args` helper next to
  `_event_modules()` ~line 556, `relay_start()` ~line 320, `event_start()` ~line 683)
- Test: `tests/test_iro.py` (append)

`iro relay start --stint 3` and `iro relay run --stint 3` already work — both
forward `rest` verbatim to the relay argv (repo AND frozen mode). Only
`event_start()` hard-codes `relay_start([])`. The spec additionally requires
invalid `--stint` values to **fail fast before anything is spawned** — important
for the detached `iro relay start`, where the relay's own error would only land
in the log file, not the console.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iro.py` (above the `if __name__` block):

```python
def t_stint_args_extraction():
    # event_start forwards only the --stint flag to the relay launch
    assert m._stint_args([]) == []
    assert m._stint_args(["--no-color"]) == []
    assert m._stint_args(["--stint", "4"]) == ["--stint", "4"]
    assert m._stint_args(["--no-color", "--stint=7"]) == ["--stint", "7"]
    assert m._stint_args(["--stint"]) == []          # missing value: let relay default


def t_stint_args_rejects_garbage():
    # fail fast BEFORE a daemon is spawned (its error would only hit the log)
    for bad in (["--stint", "abc"], ["--stint=0"], ["--stint", "-3"]):
        try:
            m._stint_args(bad)
            assert False, f"accepted {bad}"
        except SystemExit:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_iro.py`
Expected: `AttributeError: module 'iro' has no attribute '_stint_args'`

- [ ] **Step 3: Implement**

In `src/iro.py`:

(a) Add directly above `def _event_modules():`:

```python
def _stint_args(rest):
    """Extract + validate a --stint flag ("--stint 4" or "--stint=4") from an
    argv. Returns the fragment to forward to the relay launch; exits on an
    invalid value (fail fast BEFORE a detached daemon is spawned — its own
    error would only land in the log file)."""
    for i, tok in enumerate(rest):
        val = None
        if tok == "--stint" and i + 1 < len(rest):
            val = rest[i + 1]
        elif tok.startswith("--stint="):
            val = tok.split("=", 1)[1]
        if val is not None:
            if not val.isdigit() or int(val) < 1:
                sys.exit(f"--stint must be a 1-based stint number (got {val!r}).")
            return ["--stint", val]
    return []
```

(b) In `relay_start()`, add as the first line of the function body (validation
only — `rest` is still forwarded verbatim):

```python
    _stint_args(rest)   # fail fast on an invalid --stint before spawning the daemon
```

(c) In `event_start()`, replace:

```python
    # 3. Relay (before OBS — see docstring)
    relay_start([])
```

with:

```python
    # 3. Relay (before OBS — see docstring). A takeover bring-up forwards
    # --stint so the feeds start at the stint that is on air right now.
    relay_start(_stint_args(rest))
```

(d) USAGE docstring — after the
`  iro event     status|start|stop      # event-day readiness: ...` line add:

```
  iro event start --stint N             # takeover: stint N is on air now — the relay starts there
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_iro.py`
Expected: all `ok` (incl. `ok t_stint_args_extraction`), `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_iro.py src/iro.py
git commit -m "feat(event): iro event start --stint N forwards takeover stint to the relay"
```

---

### Task 5: Operator docs — handover checklist + endpoint reference

**Files:**
- Modify: `src/docs/wiki/Run-an-event.md` (new section after
  "During the race: driver POV (optional)")
- Modify: `src/docs/wiki/Relay-Mode.md` (section "3. Start the relay" + a note
  after the Companion endpoint table in section 4)
- Modify: `README.md` (line ~60, `iro event start` block)
- Modify: `CLAUDE.md` (commands block, `iro event start` line)

No code — docs-only task; keep everything English.

- [ ] **Step 1: Add the handover section to `src/docs/wiki/Run-an-event.md`**

Insert after the "During the race: driver POV (optional)" section (before
"Interviews (at the end)"):

```markdown
## Producer handover (12h/24h multi-part events)

Long events are split into broadcast parts run by different producers, each on
their own machine with their own stream key. Viewers follow via the channel's
end-of-stream redirect; plan a few minutes of deliberate overlap.

The relay does **not** need the previous producer's Feed A/B order — the
ping-pong works from any starting point. Rule of thumb: **after every takeover
you go on air with Feed A.**

1. Incoming producer: `iro event start --stint <N>` — N is the stint **on air
   right now** (1-based, from the schedule sheet / Discord). Feed A serves
   stint N, Feed B preloads stint N+1.
2. Verify Feed A shows the same commentator as the live broadcast (`/status`
   or the OBS preview).
3. Start your OBS stream with this part's stream key — the overlap begins.
4. Share your panel/tablet URLs with the directors (`iro event start` prints
   them — just forward).
5. Outgoing producer: stop the stream (the YouTube redirect takes over), then
   `iro event stop`.

Typo, or forgot `--stint`? Fix it **before going live**:
`http://127.0.0.1:8088/set/stint/<N>` repositions both feeds. Like the other
`/set` endpoints it tears a running feed off its stream — not for mid-program
use.

**Same producer runs the next part:** just stop the OBS stream and start it
again with the next part's stream key — the relay keeps running, no `--stint`
needed.
```

- [ ] **Step 2: Update `src/docs/wiki/Relay-Mode.md`**

(a) In section "3. Start the relay", after the existing code block + stop
paragraph, add:

```markdown
**Taking over mid-event (multi-part broadcasts):** start the relay at the stint
that is on air right now —

```bash
iro relay start --stint 4   # stint 4 is live: Feed A serves it, Feed B preloads stint 5
```

After every takeover the new producer goes on air with **Feed A** — there is no
need to continue the previous producer's A/B order. Full checklist:
[Run an event → Producer handover](Run-an-event#producer-handover-12h24h-multi-part-events).
```

(b) In section "4. Control it (Companion → relay)", after the
"Works for remote directors too …" paragraph, add:

```markdown
One more endpoint for the browser (not a Companion button — it needs a number):
`http://127.0.0.1:8088/set/stint/<n>` positions BOTH feeds for a producer
takeover (1-based: stint n on Feed A, n+1 preloaded on Feed B). It tears
running feeds — use it before going live, never mid-program.
```

- [ ] **Step 3: Mention the flag in `README.md` and `CLAUDE.md`**

(a) `README.md` — after the `iro event start` line (~line 60) add:

```
iro event start --stint 4 # take over mid-event (12h/24h): stint 4 is on air now
```

(b) `CLAUDE.md` — in the commands block, replace:

```
python3 src/iro.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion)
```

with:

```
python3 src/iro.py event start       # bring everything up (Tailscale, Discord, relay, OBS, Companion); --stint N = mid-event takeover (stint N is on air; /set/stint/<n> corrects later)
```

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/Run-an-event.md src/docs/wiki/Relay-Mode.md README.md CLAUDE.md
git commit -m "docs: producer handover checklist for 12h/24h multi-part events"
```

(Publishing: `python3 tools/sync-wiki.py` mirrors the wiki pages — maintainer
action after merge, not part of this task.)

---

### Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: every file `ALL PASS`, final `ALL TEST FILES PASS`

- [ ] **Step 2: Build + self-verify the distributable**

Run: `python3 tools/build.py`
Expected: build completes; verify step passes (tokenization, no secrets, no shell
scripts — the closest thing to CI)

- [ ] **Step 3: Manual smoke (cheap)**

Run: `python3 src/relay/iro-feeds.py --help | grep -A2 -- --stint`
Expected: the `--stint` help text from Task 2.

Run: `python3 src/iro.py relay start --stint 0`
Expected: exits with `--stint must be a 1-based stint number (got '0').` and NO
daemon is started (`python3 src/iro.py relay status` still says not running —
assuming the relay was not already running before this check).

- [ ] **Step 4: Done — no commit needed unless the build touched tracked files**
