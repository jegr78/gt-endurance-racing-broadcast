# Solo relay mode (#302) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the relay start and serve the reusable control surface (panel, OBS control, timer, HUD, POV, chat/console) for a `kind=solo` profile — "endurance minus the A/B-feed schedule" — with the Google Sheet still on.

**Architecture:** A new relay `--solo` flag (injected by the CLI from `ResolvedConfig.kind`) makes `Relay` construct with no `Schedule`/`Qualifying` source and no A/B feeds (`self.feeds = {}`), keeping the already-independent optional POV feed and every sheet-driven source (HUD/Channel/Crew/Producer/Timer/EventNotes) unchanged. The feed-touching `Relay` methods gain explicit solo guards so they never index `self.A`/`self.B` or `self.source`. `main()` gets a small `args.solo` branch that skips the schedule/A-B build and the yt-dlp/streamlink hard-exit.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest); the relay module `src/relay/racecast-feeds.py` is loaded via `importlib` (hyphen in filename).

## Global Constraints

- Edit only under `src/` (+ `tests/`). `dist/`/`runtime/` are generated.
- **The endurance path stays byte-identical.** Solo is a separate, guarded branch.
- **No existing test is commented out or disabled.** `python3 tools/run-tests.py` stays green with zero deactivations. (Two `#301` solo-profile assertions are *re-pointed* to the new sheet-always behavior — a deliberate design change, not a disable.)
- All scripts/docs English only. No machine paths / real IPs in committed files.
- Relay stays import-light: no `import config`. Solo is detected from `--solo` (whose default reads `os.environ["RACECAST_KIND"]`), mirroring `--sheet-id` ← `RACECAST_SHEET_ID`.
- Work on branch `feat/302-feedless-relay` (already created off `epic/300-solo-mode`). One PR, base `epic/300-solo-mode`, conventional title `feat(solo): ...`.

---

### Task 1: Solo `profile.env` keeps `SHEET_ID` (#301 correction)

Sheet-always means a solo profile needs a Sheet. Revise the generated solo `profile.env` from #301 (currently sheet-less) to carry `SHEET_ID` + the sheet-relevant keys.

**Files:**
- Modify: `src/scripts/profile_admin.py` (`_solo_profile_env_text`)
- Test: `tests/test_profile.py` (`t_create_solo_profile_*`)

**Interfaces:**
- Consumes: `cfg.SOLO_TEMPLATES` (from #301).
- Produces: a solo `profile.env` string containing `NAME`, `KIND=solo`, `TEMPLATE=<t>`, `SHEET_ID=`, `SHEET_PUSH_URL=`, `OBS_COLLECTION=`, `LOGO=`, `EVENT_TITLE=`, `CONSOLE_SECRET=`.

- [ ] **Step 1: Re-point the existing solo test to sheet-always**

In `tests/test_profile.py` rename `t_create_solo_profile_is_sheetless_and_carries_template` → `t_create_solo_profile_has_sheet_and_carries_template` and change the sheet-less assertion:

```python
def t_create_solo_profile_has_sheet_and_carries_template():
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot_with_example(td)
        target = m.create_profile(root, "Demo Solo", kind="solo", template="pov")
        assert target == os.path.join(root, "profiles", "demo-solo")
        assert m.cfg.list_profiles(root) == ["demo-solo"]
        prof = m.cfg.parse_profile(root, "demo-solo")
        assert prof["NAME"] == "Demo Solo"
        assert prof["KIND"] == "solo"
        assert prof["TEMPLATE"] == "pov"
        # sheet-always: a solo profile carries SHEET_ID (blank, to be filled)
        assert "SHEET_ID" in prof and prof["SHEET_ID"] == ""
        assert "SHEET_PUSH_URL" in prof
        rcfg = m.cfg.resolve_config(root, override="demo-solo",
                                    runtime_root=os.path.join(td, "runtime"))
        assert rcfg.kind == "solo" and rcfg.template == "pov"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_profile as t; t.t_create_solo_profile_has_sheet_and_carries_template()"`
Expected: FAIL (`AssertionError` — SHEET_ID not in prof, current text is sheet-less).

- [ ] **Step 3: Add the sheet keys to the generated solo profile.env**

In `src/scripts/profile_admin.py`, `_solo_profile_env_text`, insert the sheet keys after the `TEMPLATE` block (before `OBS_COLLECTION`):

```python
        "# Google Sheet that drives the HUD, timer, crew/console roles, broadcast\n"
        "# chat and assets (the long ID from the sheet URL). A solo Sheet uses the\n"
        "# same tabs as endurance MINUS the Schedule/Qualifying tabs.\n"
        "SHEET_ID=\n"
        "\n"
        "# OPTIONAL: sheet-write webhook (Apps Script /exec URL incl. its ?key=...)\n"
        "# enabling the Director Panel's Setup/POV write-back + the race timer.\n"
        "SHEET_PUSH_URL=\n"
        "\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_profile.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/profile_admin.py tests/test_profile.py
git commit -m "fix(profile): solo profiles keep SHEET_ID (sheet-always solo design)"
```

---

### Task 2: CLI `--solo` wiring (env `RACECAST_KIND` + relay flag)

**Files:**
- Modify: `src/racecast.py` (`_profile_env_vars`, ~line 208)
- Modify: `src/relay/racecast-feeds.py` (argparse, ~line 7619)
- Test: `tests/test_racecast.py`

**Interfaces:**
- Produces: env var `RACECAST_KIND` (value `endurance`|`solo`) in child processes; relay arg `args.solo` (bool, default `os.environ["RACECAST_KIND"] == "solo"`).

- [ ] **Step 1: Write the failing test for RACECAST_KIND injection**

In `tests/test_racecast.py` (find how it imports racecast.py as a module — reuse that; call the module `rc`). Add:

```python
def t_profile_env_vars_includes_kind():
    class _RC:  # minimal ResolvedConfig stand-in
        sheet_id = "abc"; sheet_push_url = ""; intro_url = ""; outro_url = ""
        discord_webhook_url = ""; obs_collection = ""; console_secret = ""
        discord_client_id = ""; discord_client_secret = ""; discord_voice_url = ""
        event_title = ""; name = "Solo League"; logo_path = ""; kind = "solo"
    env = rc._profile_env_vars(_RC())
    assert env["RACECAST_KIND"] == "solo"
    assert env["RACECAST_SHEET_ID"] == "abc"
```

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_profile_env_vars_includes_kind()"`
Expected: FAIL (`KeyError: 'RACECAST_KIND'`).

- [ ] **Step 2: Inject RACECAST_KIND**

In `src/racecast.py` `_profile_env_vars`, add to the `pairs` tuple (after `RACECAST_LOGO`):

```python
             ("RACECAST_LOGO", rc.logo_path),
             ("RACECAST_KIND", rc.kind))
```

(Move the closing `)` accordingly. `rc.kind` is always `"endurance"`/`"solo"`, so it always injects.)

- [ ] **Step 3: Run the test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: `ALL PASS`.

- [ ] **Step 4: Add the relay `--solo` flag**

In `src/relay/racecast-feeds.py`, in the argparse block (near the other flags, ~line 7690), add:

```python
    ap.add_argument("--solo", action="store_true",
                    default=(os.environ.get("RACECAST_KIND", "").strip().lower() == "solo"),
                    help="Solo mode: no Schedule/Qualifying tab and no A/B feeds "
                         "(local capture program). The Sheet + POV + HUD stay on.")
```

- [ ] **Step 5: Verify the flag parses**

Run: `python3 -c "import importlib.util,os; os.environ['RACECAST_KIND']='solo'; s=importlib.util.spec_from_file_location('rf','src/relay/racecast-feeds.py')"`
(Argparse default is exercised by the Task 6 solo run; here just confirm the import line has no syntax error via lint.)
Run: `python3 tools/lint.py`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py src/relay/racecast-feeds.py tests/test_racecast.py
git commit -m "feat(solo): CLI injects RACECAST_KIND; relay gains --solo flag"
```

---

### Task 3: `Relay` solo construction (feed-less A/B, optional POV)

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`Relay.__init__`, ~line 5002)
- Test: `tests/test_solo.py` (new)

**Interfaces:**
- Consumes: `Relay(source, ports, logdir, ..., solo=False)`.
- Produces: a solo `Relay` with `self.solo is True`, `self.feeds == {}`, `self.race_source is None`, `self.pov` present iff a `pov_source` was passed. Endurance construction (`solo=False`) is unchanged; `self.solo` exists (`False`) on every Relay.

- [ ] **Step 1: Write the failing test (new file)**

Create `tests/test_solo.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for solo relay mode (#302). Run: python3 tests/test_solo.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = tempfile.mkdtemp(prefix="racecast-test-solo-")
spec = importlib.util.spec_from_file_location(
    "irofeeds_solo", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _solo_relay():
    return m.Relay(None, [], LOGDIR, solo=True, sheet_id="abc", league_name="Solo")


def t_solo_relay_has_no_feeds():
    r = _solo_relay()
    assert r.solo is True
    assert r.feeds == {}
    assert r.race_source is None and r.qual_source is None
    assert r.pov is None                      # no pov_source passed


def t_endurance_relay_still_has_ab_and_solo_false():
    class _Src:
        def get(self): return ["u1", "u2"]
        def get_rows(self): return [("u1", "", "", 1), ("u2", "", "", 2)]
        def refresh(self, timeout=None): pass
        def health(self): return {"ok": True}
    r = m.Relay(_Src(), [53001, 53002], LOGDIR)
    assert r.solo is False
    assert set(r.feeds) == {"A", "B"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

Run: `python3 tests/test_solo.py`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument 'solo'`).

- [ ] **Step 2: Add the `solo` param + branch in `Relay.__init__`**

In `src/relay/racecast-feeds.py`, change the `Relay.__init__` signature to add `solo=False`:

```python
    def __init__(self, source, ports, logdir, cookies=None, pov_source=None,
                 pov_port=None, start_stint=1, cookie_dir=None,
                 qual_source=None, mode="race", discord_webhook_url=None,
                 sheet_id=None, event_title_store=None, league_name="",
                 producer_name="", solo=False):
```

Then replace the A/B build block (the four lines `a_idx, b_idx = slot_start_indices(...)` … `self.feeds = {"A": self.A, "B": self.B}`) with:

```python
        self.solo = solo
        if solo:
            # Solo: no Schedule/Qualifying and no A/B ping-pong feeds. POV (below)
            # is the only optional feed; every sheet-driven source is built by main()
            # exactly as endurance.
            self.on_air_row = 0
            self.A = self.B = None
            self.feeds = {}
        else:
            a_idx, b_idx = slot_start_indices(start_stint, self.active_source().get_rows())
            self.on_air_row = a_idx
            self.A = Feed("A", ports[0], a_idx, self.active_items, logdir, cookies, cookie_dir=cookie_dir)
            self.B = Feed("B", ports[1], b_idx, self.active_items, logdir, cookies, cookie_dir=cookie_dir)
            self.feeds = {"A": self.A, "B": self.B}
```

(The `self.mode = "qualifying" if ... else "race"` line above stays; in solo `qual_source` is None so `self.mode` is `"race"` — harmless, never read because status() is guarded in Task 4.)

- [ ] **Step 3: Run the test to verify it passes**

Run: `python3 tests/test_solo.py`
Expected: `ALL PASS`.

- [ ] **Step 4: Guard against regressions on the endurance POV/feed suite**

Run: `python3 tests/test_pov.py`
Expected: `ALL PASS` (endurance construction unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_solo.py
git commit -m "feat(solo): Relay constructs feed-less in solo mode (no A/B)"
```

---

### Task 4: Solo guards on the feed-touching `Relay` methods

Every method that indexes `self.A`/`self.B` or `self.source` (which are `None` in solo) gets an explicit solo guard. `advance`/`set_index` already `return None` on a missing feed, so they need no change.

Two categories: (1) **public** methods reached by feed endpoints, and (2) **internal** methods that run in the **heartbeat loop** — which `start()` launches in solo too. Both must be solo-safe. `advance`/`set_index` already `return None` on a missing feed; `pov_*` (toggle/name/reflect), `_health_facts`, `_refresh_health`, `_sample_connectivity`, `splitscreen_state`, `live_after_next` are already solo-safe (empty-feeds loop / degenerate-but-no-crash) — leave them.

**Files:**
- Modify: `src/relay/racecast-feeds.py`
  - public: `status` (add `_solo_status`), `live_feed`, `on_air_row_idx`, `next_auto`, `set_stint`, `set_mode`, `reload`, `live_row_map`, `live_schedule_row`
  - internal (heartbeat): `_maybe_auto_failover` (indexes `self.feeds[live]`, **not** inside a try/except at its call site → would crash the heartbeat if `RACECAST_AUTO_FAILOVER=1`), `_health_snapshot` (indexes `self.feeds["A"/"B"]` + `self.source`)
- Test: `tests/test_solo.py`

**Interfaces:**
- Consumes: the solo `Relay` from Task 3.
- Produces: `status()` returns `{"mode": "solo", "solo": True, "feeds": {}, "pov": {...}|absent, "obs": {...}, "live": {"feed": None, "stint": None, "mode": "solo"}, "league": {...}, "health": {...}, ...}`; `live_feed()` → `None`; `on_air_row_idx()` → `0`; `next_auto`/`set_stint`/`set_mode`/`reload` → `{"error": "not available in solo mode", "solo": True}`; `live_row_map()` → `{}`; `live_schedule_row()` → `None`; `_maybe_auto_failover(now)` → early return; `_health_snapshot(now)` → a snapshot with the feed_a/b + source fields `None` (POV/OBS/timer/system fields still populated).

- [ ] **Step 1: Write the failing guard tests**

Append to `tests/test_solo.py` (before the `__main__` block):

```python
def t_solo_status_is_feedless_and_shaped():
    r = _solo_relay()
    s = r.status()
    assert s["mode"] == "solo" and s["solo"] is True
    assert s["feeds"] == {}
    assert s["live"] == {"feed": None, "stint": None, "mode": "solo"}
    assert s["league"]["sheet_id"] == "abc"
    assert "health" in s and "obs" in s


def t_solo_feed_controls_are_guarded_not_crashing():
    r = _solo_relay()
    assert r.live_feed() is None
    assert r.on_air_row_idx() == 0
    assert r.live_row_map() == {}
    assert r.live_schedule_row() is None
    for call in (r.next_auto, lambda: r.set_stint(2),
                 lambda: r.set_mode("qualifying"), lambda: r.reload()):
        out = call()
        assert out.get("solo") is True and "error" in out


def t_solo_heartbeat_paths_never_crash():
    import time as _t
    r = _solo_relay()
    now = _t.time()
    # the heartbeat body constituents must not raise in solo (no A/B feeds)
    r._sample_connectivity()
    r._refresh_health(now)
    snap = r._health_snapshot(now)          # feed fields NULL, POV/system fields present
    assert snap["feed_a_state"] is None and snap["feed_b_state"] is None
    assert snap["live_feed"] is None
    r.auto_failover = True                   # even opted-in, solo must early-return
    r._maybe_auto_failover(now)              # must not KeyError on feeds[None]
```

Run: `python3 tests/test_solo.py`
Expected: FAIL (`AttributeError`/`TypeError`/`KeyError` — `status()`/`_health_snapshot` dereference `self.source`/`self.feeds["A"]`, `live_feed()` reads `self.A.idx`).

- [ ] **Step 2: Guard `status()` + add `_solo_status()`**

In `status()`, insert right after `self._maybe_probe_obs(now)`:

```python
        if self.solo:
            return self._solo_status(now)
```

Add the new method immediately after `status()`:

```python
    def _solo_status(self, now):
        """Solo status: no A/B schedule/feeds. POV + OBS + health + league identity
        (the console/panel read these); mirrors the tail of status()."""
        out = {"mode": "solo", "solo": True, "feeds": {},
               "cookies": bool(self.cookies),
               "cookies_health": cookie_health(self.cookies, now=now)}
        if self.pov:
            raw = (self.pov_source.get()[:1] or [None])[0] if self.pov_source else None
            out["pov"] = {"port": self.pov.port, "url": raw,
                          "name": self.pov_name(), "shown": self.pov_shown,
                          "state": "stopped" if self.pov.paused else self.pov.phase,
                          "state_age_s": round(now - self.pov.phase_since, 1),
                          "down": self.pov.dropped and not self.pov.paused,
                          "source": self.pov_source.health() if self.pov_source else None}
        out["obs"] = {"reachable": self.obs_reachable, "note": self.obs_note}
        out["live"] = {"feed": None, "stint": None, "mode": "solo"}
        out["league"] = {"sheet_id": self.sheet_id, "name": self.league_name}
        out["producer"] = self.producer_name
        self._refresh_health(now)
        out["health"] = {"level": self.health_level, "reasons": self.health_reasons,
                         "since_s": round(now - self.health_since, 1)}
        return out
```

- [ ] **Step 3: Guard `live_feed`, `on_air_row_idx`, and the control methods**

`live_feed()` — insert as the first line of the body:

```python
        if self.solo:
            return None
```

`on_air_row_idx()` — insert as the first line of the body:

```python
        if self.solo:
            return 0
```

At the top of each of `next_auto(self)`, `set_stint(self, stint)`, `set_mode(self, mode)`, and `reload(self, which=None)`, insert:

```python
        if self.solo:
            return {"error": "not available in solo mode", "solo": True}
```

`live_row_map(self)` — insert as the first line of the body:

```python
        if self.solo:
            return {}
```

`live_schedule_row(self)` — insert as the first line of the body:

```python
        if self.solo:
            return None
```

- [ ] **Step 3b: Guard the heartbeat-internal methods**

`_maybe_auto_failover(self, now)` — fold solo into the existing early-return guard. Change:

```python
        if not self.auto_failover or _obs_ws is None:
            return
```
to:
```python
        if self.solo or not self.auto_failover or _obs_ws is None:
            return
```

`_health_snapshot(self, now)` — make the A/B/source fields solo-aware. Replace the two `feed_fields(...)` lines and the `live = self.live_feed()` line:

```python
        a_state, a_down, a_stint = feed_fields(self.feeds["A"])
        b_state, b_down, b_stint = feed_fields(self.feeds["B"])
        ch = cookie_health(self.cookies, now=now)
        live = self.live_feed()
```
with:
```python
        if self.solo:
            a_state = a_down = a_stint = None
            b_state = b_down = b_stint = None
            live = None
        else:
            a_state, a_down, a_stint = feed_fields(self.feeds["A"])
            b_state, b_down, b_stint = feed_fields(self.feeds["B"])
            live = self.live_feed()
        ch = cookie_health(self.cookies, now=now)
```

Then make the three feed/source-indexing dict values solo-safe. Change:
- `"source_last_ok_age_s": self.source.health().get("last_ok_age_s"),` → `"source_last_ok_age_s": (None if self.solo else self.source.health().get("last_ok_age_s")),`
- `"source_count": self.source.health().get("count"),` → `"source_count": (None if self.solo else self.source.health().get("count")),`
- `"live_feed": live, "live_stint": self.feeds[live].idx + 1,` → `"live_feed": live, "live_stint": (None if self.solo else self.feeds[live].idx + 1),`
- `"feed_a_quality": _q(self.feeds["A"]),` → `"feed_a_quality": (None if self.solo else _q(self.feeds["A"])),`
- `"feed_b_quality": _q(self.feeds["B"]),` → `"feed_b_quality": (None if self.solo else _q(self.feeds["B"])),`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_solo.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Full relay regression**

Run: `python3 tests/test_pov.py && python3 tests/test_timer.py`
Expected: both `ALL PASS` (endurance status/handover/reload paths unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_solo.py
git commit -m "feat(solo): guard feed-touching Relay methods in solo mode"
```

---

### Task 5: `main()` solo startup branch

Make the relay `main()` honor `args.solo`: skip the schedule/A-B build + the yt-dlp/streamlink hard-exit; keep every sheet-driven source (HUD/Channel/Crew/Producer/Timer/EventNotes/POV).

**Files:**
- Modify: `src/relay/racecast-feeds.py` (`main()`, ~lines 7736, 7999–8034)

**Interfaces:**
- Consumes: `args.solo` (Task 2), `Relay(..., solo=True)` (Task 3).
- Produces: a running solo relay serving the control surface; no `ScheduleSource`, no A/B feeds, no A/B feed ports bound.

- [ ] **Step 1: Make the tool hard-exit conditional**

Wrap the yt-dlp/streamlink check (`for _tool in ("yt-dlp", "streamlink"): ...`, ~line 7736):

```python
    if not args.solo:
        for _tool in ("yt-dlp", "streamlink"):
            if not shutil.which(_tool):
                sys.exit(f"ERROR: '{_tool}' not found on PATH "
                         f"(brew install {_tool} / pip install -U {_tool}).")
```

(Solo needs the tools only for the optional POV feed; if absent, the POV feed logs and idles — existing runtime behavior — everything else runs.)

- [ ] **Step 2: Skip the Schedule/Qualifying source + branch the Relay build**

Replace the block that builds `source`, `setup_ctl` and the `Relay(...)`/`_reflect(...)` (the `source = ScheduleSource(csv_url, cache, local)` line through `relay._reflect(relay.live_feed(), cut=False)`, ~lines 7999–8023) with a solo-aware version:

```python
    source = None
    if not args.solo:
        source = ScheduleSource(csv_url, cache, local)
        source.load_initial(SCHEDULE_TEMPLATE)
    # SetupControl already defaults schedule_source=None and only dereferences it
    # on the /schedule editor write path (unused in solo), so source=None is safe;
    # the Setup HUD-field writes solo uses do not touch it.
    setup_ctl = (SetupControl(push_url, hud_source, schedule_source=source,
                              qual_source=qual_source, pov_source=pov_source,
                              crew_source=crew_source)
                 if hud_source else None)
    if source is not None and len(source.get()) < 2:
        LOG.info("schedule has fewer than 2 stints — Feed B idles on the empty next "
                 "slot (black) until that stint's link is added; Feed A keeps serving stint 1.")

    relay = Relay(source, ports, logdir, cookies,
                  pov_source=pov_source, pov_port=args.pov_port,
                  start_stint=args.stint,
                  cookie_dir=(os.path.dirname(cookies) if cookies else runtime),
                  qual_source=qual_source,
                  mode=("qualifying" if args.qualifying else "race"),
                  discord_webhook_url=os.environ.get("RACECAST_DISCORD_WEBHOOK_URL"),
                  sheet_id=args.sheet_id,
                  event_title_store=event_store,
                  league_name=args.league_name,
                  producer_name=os.environ.get("RACECAST_PRODUCER_NAME", ""),
                  solo=args.solo)
    relay.health_store = _health_store_obj
    relay.timer_store = timer_store
    relay.start()
    if not args.solo:
        relay._reflect(relay.live_feed(), cut=False)   # pre-set Stint visibility/audio for the live feed
```

(In solo, `qual_source` is already `None` because it is only built `if not args.sheet_csv_url` from a POV-style tab; if you also want to skip the `Qualifying` fetch, gate its build block on `not args.solo` — see Step 3.)

- [ ] **Step 3: Skip Schedule/Qualifying source construction + the schedule poller in solo**

Gate the `qual_source` build block (`if not args.no_qualifying and not args.sheet_csv_url:`) to also require `not args.solo`:

```python
    qual_source = None
    if not args.no_qualifying and not args.sheet_csv_url and not args.solo:
```

Gate the schedule poller (`threading.Thread(target=poller, args=(source, args.poll, stop_evt), daemon=True).start()`, ~line 8031):

```python
    if source is not None:
        threading.Thread(target=poller, args=(source, args.poll, stop_evt), daemon=True).start()
```

- [ ] **Step 4: Lint + full suite**

Run: `python3 tools/lint.py && python3 tools/run-tests.py`
Expected: `All checks passed!` then `ALL TEST FILES PASS` (nothing disabled).

- [ ] **Step 5: Manual real-behavior verification (the acceptance)**

`main()` isn't unit-testable without a subprocess; verify it by running the CLI. From `src/`, with **no yt-dlp/streamlink needed** and a throwaway solo profile that has a (dummy) `SHEET_ID`:

```bash
# create a temp solo profile with a dummy sheet id, point the CLI at it
python3 src/racecast.py profile new zz-solo-smoke --kind solo --template commentary
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("profiles/zz-solo-smoke/profile.env"); t = p.read_text()
p.write_text(re.sub(r"^SHEET_ID=$", "SHEET_ID=dummy", t, flags=re.M))
PY
RACECAST_PROFILE=zz-solo-smoke python3 src/racecast.py relay run &
sleep 4
curl -s 127.0.0.1:8088/status | python3 -m json.tool | head -20   # expect "mode": "solo"
python3 src/racecast.py relay stop 2>/dev/null; pkill -f racecast-feeds 2>/dev/null
# no feed ports bound:
python3 src/scripts/ports.py 53001 || echo "53001 free (expected)"
rm -rf profiles/zz-solo-smoke
```

Expected: `/status` shows `"mode": "solo"`, `"feeds": {}`; `/panel`, `/timer/data`, `/obs/state`, `/hud/data` respond; port `53001`/`53002` are NOT bound. Confirm `git status --porcelain profiles/` is clean after cleanup.

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py
git commit -m "feat(solo): relay main() starts feed-less in solo mode"
```

---

### Task 6: Final gates + PR

**Files:** none (verification + PR)

- [ ] **Step 1: Full local gates**

```bash
python3 tools/run-tests.py     # ALL TEST FILES PASS, nothing disabled
python3 tools/lint.py          # All checks passed!
python3 tools/build.py         # exit 0
python3 tests/test_pov.py      # relay path green
```

- [ ] **Step 2: Confirm no existing test was disabled**

Run: `git diff epic/300-solo-mode -- tests/ | grep -E "^-\s*(def t_|assert)" | grep -v "is_sheetless"`
Expected: only the intentional `#301` rename/re-point (Task 1) appears; no other removed test/assert lines.

- [ ] **Step 3: Push + open PR (after user OK)**

```bash
git push -u origin feat/302-feedless-relay
gh pr create --base epic/300-solo-mode --head feat/302-feedless-relay \
  --title "feat(solo): feed-less, sheet-driven solo relay mode" \
  --body "... Closes #302. Corrects #301 (solo keeps SHEET_ID). Spec: docs/superpowers/specs/2026-07-06-solo-relay-mode-design.md ..."
```

- [ ] **Step 4: Green CI (epic/** triggers), then merge (after user OK)**

Poll `gh pr checks <PR>`; on green + user OK: `gh pr merge <PR> --squash --delete-branch`.
```
