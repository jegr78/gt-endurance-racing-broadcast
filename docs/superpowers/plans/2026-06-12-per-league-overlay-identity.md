# Per-League Overlay Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split team name/number into independently positionable HUD elements with panel-controlled Top-3 (issue #80), then add a named-snapshot backup/restore for a league's overlay+graphics+media look (issue #81).

**Architecture:** Part 1 turns the Configuration sheet tab into a team roster (`Team Name | Number | Brand`); the relay resolves number+logo from it, the HUD renders name and number as two separate elements (default = number badge before an auto-fit name), and three new panel dropdowns write the podium teams back through the existing async-optimistic webhook path. Part 2 adds a `backup_admin` module + `racecast backup` CLI + Control Center "Looks" card that zip/restore the three per-league asset locations. `hud.html` stays shared; all per-league look lives in `override.css` + runtime assets.

**Tech Stack:** Pure Python 3 + stdlib (no pytest — each `tests/test_*.py` is a runnable script with `t_*` functions and a `__main__` runner), vanilla HTML/CSS/JS for the HUD and panel, Google Apps Script (documented in the wiki) for the sheet webhook.

**Spec:** `docs/superpowers/specs/2026-06-12-per-league-overlay-identity-design.md`

---

## Conventions (read once)

- **Run one test file:** `python3 tests/test_hud.py` (prints `ok <name>` per test, `ALL PASS` at end). A failing `assert` aborts with a traceback — that is the "FAIL".
- **Run the whole suite (what CI runs):** `python3 tools/run-tests.py`.
- **Lint after any Python change:** `python3 tools/lint.py` (ruff; `--fix` auto-corrects).
- **Build self-verify before anything ships:** `python3 tools/build.py`.
- **The relay module** `src/relay/racecast-feeds.py` is loaded in tests via `importlib` as module `m` (see `tests/test_setup.py:8-10`). All relay symbols below are referenced as `m.<name>` in tests.
- **Commit after every green task.** Branch is already `feat/per-league-overlay-identity`.

## File Structure

**Part 1 (#80) — modify:**
- `src/relay/racecast-feeds.py` — `split_team_label` (new), `parse_config_brands` → `parse_config_roster` (number+brand), `build_hud_data` (+`team_entry`, number), `HudSource` (roster storage, `resolve_team`, `roster_names`, team overrides), `SETUP_FIELDS`/`SetupControl` (team fields + `/setup/team` endpoint).
- `src/obs/hud.html` — split `.num`/`.name`, default badge layout, CSS variables, auto-fit JS, `setTeam`.
- `src/director/director-panel.html` — P1/P2/P3 dropdowns.
- `src/docs/wiki/Sheet-Webhook.md` — Overlay-teams action + Apps Script writer; Configuration `Number` column + roster/Overlay schema.
- `tests/test_hud.py`, `tests/test_setup.py` — coverage.

**Part 2 (#81) — create/modify:**
- `src/scripts/backup_admin.py` (new) — snapshot create/list/restore/delete, manifest, zip-member safety, atomic swap.
- `src/racecast.py` — `backup_cmd` + `route`/`main` wiring; `backup_list_data`/`backup_create_data`/`backup_restore_data`/`backup_delete_data` UI providers.
- `src/ui/ui_server.py` (+ the Profile-view frontend served by it) — `/api/backup*` routes + "Looks" card.
- `tests/test_backup.py` (new), `tests/test_ui_server.py` — coverage.

---

# PART 1 — #80: Split team name/number + panel Top-3

## Task 1: `split_team_label` helper

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add after `asset_key`, near line 326)
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_hud.py` (before the `__main__` runner):

```python
def t_split_team_label_trailing_number():
    assert m.split_team_label("OVO eSports #111") == ("OVO eSports", "111")
    assert m.split_team_label("Apex Racing #7") == ("Apex Racing", "7")

def t_split_team_label_no_number():
    assert m.split_team_label("OVO eSports") == ("OVO eSports", "")
    assert m.split_team_label("") == ("", "")

def t_split_team_label_mid_string_hash_kept():
    # only a TRAILING "#<digits>" token is split off; a mid-string # stays in the name
    assert m.split_team_label("Team #1 Racing") == ("Team #1 Racing", "")
    assert m.split_team_label("  Spaced #42  ") == ("Spaced", "42")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: `AttributeError: module ... has no attribute 'split_team_label'`.

- [ ] **Step 3: Implement** — add to `src/relay/racecast-feeds.py` right after `asset_key` (line 325):

```python
TEAM_NUMBER_RE = re.compile(r"^(.*?)\s*#(\d+)\s*$")

def split_team_label(s):
    """Split a team label into (name, number): a TRAILING '#<digits>' token is
    peeled off ('OVO eSports #111' -> ('OVO eSports', '111')); no trailing number
    -> (stripped, ''). A '#' that is not a trailing all-digit token stays in the
    name. Used to strip the embedded number so it never double-displays, and as
    the backward-compat number source when the Configuration tab has no Number
    column."""
    s = (s or "").strip()
    mtch = TEAM_NUMBER_RE.match(s)
    if mtch:
        return mtch.group(1).strip(), mtch.group(2)
    return s, ""
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ok t_split_team_label_...` lines, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(hud): split_team_label helper (peel trailing #NNN off a team label)"
```

---

## Task 2: `parse_config_roster` (number + brand, column-wins precedence)

Replaces `parse_config_brands`. The roster maps a **stripped** team name to `{number, brandKey}`; the `Number` column wins over an embedded `#NNN`, which is the fallback.

**Files:**
- Modify: `src/relay/racecast-feeds.py:362-386`
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_hud.py`:

```python
ROSTER_CSV_WITH_NUMBER = (
    "Teams,Number,Brand Name\n"
    "OVO eSports,111,Porsche\n"
    "Feel Good,303,BMW\n")

ROSTER_CSV_EMBEDDED_ONLY = (
    "Teams,Brand Name\n"
    "OVO eSports #111,Porsche\n"
    "Apex Racing #7,Audi\n")

ROSTER_CSV_BOTH = (
    "Teams,Number,Brand Name\n"
    "OVO eSports #999,111,Porsche\n")   # embedded #999 must be ignored, column wins

def t_roster_number_column():
    r = m.parse_config_roster(ROSTER_CSV_WITH_NUMBER)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche"},
                 "Feel Good": {"number": "303", "brandKey": "bmw"}}, r

def t_roster_embedded_fallback():
    r = m.parse_config_roster(ROSTER_CSV_EMBEDDED_ONLY)
    assert r["OVO eSports"] == {"number": "111", "brandKey": "porsche"}
    assert r["Apex Racing"] == {"number": "7", "brandKey": "audi"}

def t_roster_column_wins_over_embedded():
    r = m.parse_config_roster(ROSTER_CSV_BOTH)
    # name stripped of #999, number is the column's 111 (no double display)
    assert r == {"OVO eSports": {"number": "111", "brandKey": "porsche"}}, r

def t_roster_no_teams_header_is_empty():
    assert m.parse_config_roster("Foo,Bar\n1,2\n") == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: `AttributeError: ... 'parse_config_roster'`.

- [ ] **Step 3: Implement** — replace `parse_config_brands` (lines 362-386) with:

```python
# Accepted headers for the team's brand TEXT column (priority order). The sheet's
# image columns ("Brand Logo", "Brands") are deliberately NOT in this set.
BRAND_TEXT_HEADERS = ("brand key", "brand name", "brand")
# Accepted headers locating the team-name and (optional) car-number columns.
TEAM_NAME_HEADERS = ("teams", "team name")
NUMBER_HEADERS = ("number",)


def parse_config_roster(text):
    """Configuration tab CSV -> roster {team_name: {"number": str, "brandKey": str}}.
    The team name is always stripped of a trailing '#NNN' (split_team_label); the
    Number column wins over that embedded token, which is only the fallback. Columns
    are located by header name so positions stay free. A missing team-name header ->
    {}. A missing Brand/Number column just yields '' for that field."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}
    header = [(h or "").strip().lower() for h in rows[0]]
    ti = next((header.index(h) for h in TEAM_NAME_HEADERS if h in header), None)
    if ti is None:
        return {}
    bi = next((header.index(h) for h in BRAND_TEXT_HEADERS if h in header), None)
    ni = next((header.index(h) for h in NUMBER_HEADERS if h in header), None)
    out = {}
    for row in rows[1:]:
        if len(row) <= ti:
            continue
        name, embedded = split_team_label(row[ti])
        if not name:
            continue
        col_num = (row[ni].strip() if ni is not None and len(row) > ni else "")
        brand = (asset_key(row[bi]) if bi is not None and len(row) > bi else "")
        out[name] = {"number": col_num or embedded, "brandKey": brand}
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: new tests pass. **Existing tests that call `parse_config_brands` will now fail** — that is expected; Task 3 updates the caller. If `tests/test_hud.py` still references `parse_config_brands`, update those references to `parse_config_roster` with the new shape as part of this task.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(hud): parse_config_roster (Number column wins over embedded #NNN)"
```

---

## Task 3: `build_hud_data` carries `number`; `team_entry` join

**Files:**
- Modify: `src/relay/racecast-feeds.py:418-432`, and `HudSource.EMPTY` (line 1021-1023), and `HudSource.refresh` (line 1054)
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_hud.py`:

```python
def t_build_hud_data_team_number_and_strip():
    roster = {"OVO eSports": {"number": "111", "brandKey": "porsche"}}
    overlay = {"teams": ["OVO eSports #999", "Unknown #5", ""]}
    d = m.build_hud_data(overlay, roster)
    # known team: name stripped, number+logo from roster (embedded #999 ignored)
    assert d["teams"][0] == {"name": "OVO eSports", "number": "111", "brandKey": "porsche"}
    # unknown team: stripped name, number falls back to its own embedded token, no logo
    assert d["teams"][1] == {"name": "Unknown", "number": "5", "brandKey": ""}
    # empty slot
    assert d["teams"][2] == {"name": "", "number": "", "brandKey": ""}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: `KeyError: 'number'` / assertion mismatch (current `build_hud_data` has no `number`).

- [ ] **Step 3: Implement** — replace `build_hud_data` (lines 418-432) with:

```python
def team_entry(raw, roster):
    """One /hud/data team object from an Overlay slot value + the roster. Name is
    always the stripped form; number/logo come from the roster (Number column
    precedence already baked in), with the slot's own embedded #NNN as the only
    fallback when the team is absent from the roster."""
    name, embedded = split_team_label(raw)
    info = roster.get(name, {})
    return {"name": name,
            "number": info.get("number") or embedded,
            "brandKey": info.get("brandKey", "")}


def build_hud_data(overlay, roster):
    """Combine an Overlay map + roster {team: {number, brandKey}} into /hud/data."""
    return {
        "stint": overlay.get("stint", ""),
        "streamer": overlay.get("streamer", ""),
        "session": overlay.get("session", ""),
        "round": {
            "top": overlay.get("round_top", ""),
            "country": overlay.get("country", ""),
            "flagKey": asset_key(overlay.get("country", "")),
        },
        "teams": [team_entry(n, roster) for n in overlay.get("teams", ["", "", ""])],
        "raceControl": overlay.get("race_control", ""),
    }
```

- [ ] **Step 4: Update `HudSource`** — two edits in `src/relay/racecast-feeds.py`:

In `EMPTY` (lines 1021-1023) give team entries a `number`:

```python
    EMPTY = {"stint": "", "streamer": "", "session": "",
             "round": {"top": "", "country": "", "flagKey": ""},
             "teams": [{"name": "", "number": "", "brandKey": ""} for _ in range(3)],
             "raceControl": ""}
```

In `refresh` (line 1054) swap the brand parse for the roster parse and store it (the `self._roster = ...` line is consumed by Task 4):

```python
            overlay = parse_overlay(self._fetch(self.overlay_url, timeout))
            config_text = self._fetch(self.config_url, timeout)
            roster = parse_config_roster(config_text)
            vocab = parse_config_vocab(config_text)
            data = build_hud_data(overlay, roster)
```

And inside the `with self.lock:` block of `refresh` (after `self._vocab = vocab`, line 1062) add:

```python
            self._roster = roster
```

Add `self._roster = {}` to `__init__` next to `self._vocab` (line 1031).

- [ ] **Step 5: Run to verify it passes**

Run: `python3 tests/test_hud.py` then `python3 tests/test_setup.py`
Expected: both `ALL PASS` (the `_hs_stub` CONFIG_CSV `T #1`/`T #2` now parses to roster `T`→number `1`/`2`).

- [ ] **Step 6: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(hud): /hud/data carries team number; roster-joined team_entry"
```

---

## Task 4: `HudSource` roster access + team overrides

Adds roster lookup for the panel vocabulary and per-slot optimistic overrides (teams is a list, so it needs its own override store separate from the scalar `overrides`).

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `HudSource.__init__`, `refresh`, `data`, plus new methods
- Test: `tests/test_hud.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_hud.py`:

```python
def _roster_hud():
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config",
                     _os.path.join(d, "hud.cache.json"))
    overlay = (",Teams P1,OVO eSports,,\n,Teams P2,Feel Good,,\n,Teams P3,,,\n")
    config = "Teams,Number,Brand Name\nOVO eSports,111,Porsche\nFeel Good,303,BMW\n"
    hs._fetch = lambda url, timeout=10: overlay if url == "http://overlay" else config
    hs.refresh()
    return hs

def t_hud_roster_names_and_resolve():
    hs = _roster_hud()
    assert hs.roster_names() == ["OVO eSports", "Feel Good"]
    assert hs.resolve_team("OVO eSports") == {"name": "OVO eSports", "number": "111", "brandKey": "porsche"}
    # unknown -> stripped name, blank number/logo
    assert hs.resolve_team("Ghost #9") == {"name": "Ghost", "number": "9", "brandKey": ""}

def t_hud_team_override_echo_and_pending():
    hs = _roster_hud()
    entry = hs.resolve_team("Feel Good")
    hs.set_team_override(0, entry, now=1000.0)
    assert hs.data(now=1001.0)["teams"][0] == entry      # optimistic echo into slot 0
    assert hs.team_pending(now=1001.0) == {0}
    # expiry
    assert hs.team_pending(now=1000.0 + m.OVERRIDE_TTL + 1) == set()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_hud.py`
Expected: `AttributeError: 'HudSource' object has no attribute 'roster_names'`.

- [ ] **Step 3: Implement** — in `HudSource.__init__` add next to `self.overrides = {}` (line 1032):

```python
        self.team_overrides = {}   # slot index 0..2 -> (entry_dict, expires_ts)
```

In `refresh`, inside the `with self.lock:` block, after the `self.overrides = {...}` prune (line 1065) add a parallel prune for team overrides (a slot the sheet now matches is confirmed):

```python
            self.team_overrides = {
                s: (e, exp) for s, (e, exp) in self.team_overrides.items()
                if (data["teams"][s] if s < len(data["teams"]) else None) != e}
```

Replace `data` (lines 1088-1100) with a version that also applies team overrides:

```python
    def data(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.overrides = {k: (v, exp) for k, (v, exp) in self.overrides.items()
                              if exp > now}
            self.team_overrides = {s: (e, exp) for s, (e, exp) in self.team_overrides.items()
                                   if exp > now}
            base = dict(self._data) if self._data is not None else dict(self.EMPTY)
            out = dict(base)
            if self.overrides:
                out.update({k: v for k, (v, _exp) in self.overrides.items()})
            if self.team_overrides:
                teams = [dict(t) for t in out.get("teams", [])]
                while len(teams) < 3:
                    teams.append({"name": "", "number": "", "brandKey": ""})
                for s, (e, _exp) in self.team_overrides.items():
                    if 0 <= s < len(teams):
                        teams[s] = dict(e)
                out["teams"] = teams
            return out
```

Add these methods to `HudSource` (after `vocab`, line 1104):

```python
    def roster_names(self):
        """Team names from the Configuration roster, in sheet order (panel vocab)."""
        with self.lock:
            return list(self._roster.keys())

    def resolve_team(self, name):
        """A /hud/data team entry for a roster name (or a stripped unknown name)."""
        name, embedded = split_team_label(name)
        with self.lock:
            info = self._roster.get(name, {})
        return {"name": name,
                "number": info.get("number") or embedded,
                "brandKey": info.get("brandKey", "")}

    def set_team_override(self, slot, entry, now=None):
        """Optimistic echo for a panel team write into podium slot 0..2."""
        now = time.time() if now is None else now
        with self.lock:
            self.team_overrides[slot] = (entry, now + OVERRIDE_TTL)

    def team_pending(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            return {s for s, (_e, exp) in self.team_overrides.items() if exp > now}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_hud.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_hud.py
git commit -m "feat(hud): HudSource roster access + per-slot team overrides"
```

---

## Task 5: `SetupControl` team fields (set_team + data)

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `SETUP_FIELDS` block area (lines 1113-1121) add `TEAM_SLOTS`; `SetupControl.set_team` (new), `_push_team` (new), `data` (extend)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_setup.py` (the file's `_ctl`/`_hs_stub` need a roster; add a roster-aware stub):

```python
TEAM_OVERLAY_CSV = (",Teams P1,Old A,,\n,Teams P2,Old B,,\n,Teams P3,,,\n")
TEAM_CONFIG_CSV = ("Teams,Number,Brand Name\n"
                   "OVO eSports,111,Porsche\nFeel Good,303,BMW\n")

def _team_ctl(pushes):
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    hs = m.HudSource("http://overlay", "http://config", _os.path.join(d, "h.json"))
    hs._fetch = lambda url, timeout=10: TEAM_OVERLAY_CSV if url == "http://overlay" else TEAM_CONFIG_CSV
    hs.refresh()
    ctl = m.SetupControl("http://push", hs)
    def fake_post(url, payload, timeout=10):
        pushes.append(payload)
        return b'{"ok": true, "action": "teams", "v": 2}'
    m.post_webhook, orig = fake_post, m.post_webhook
    return ctl, hs, orig

def t_set_team_validates_vocab():
    ctl, hs, orig = _team_ctl([])
    try:
        assert "error" in ctl.set_team("p1", "Not A Team")   # not in roster
        assert "error" in ctl.set_team("p9", "OVO eSports")   # bad slot
    finally:
        m.post_webhook = orig

def t_set_team_echo_and_push():
    pushes = []
    ctl, hs, orig = _team_ctl(pushes)
    try:
        r = ctl.set_team("p1", "OVO eSports", now=1000.0)
        assert r.get("ok") and r.get("pending")
        assert hs.data(now=1001.0)["teams"][0]["name"] == "OVO eSports"
        assert hs.data(now=1001.0)["teams"][0]["number"] == "111"
        ctl._push_team(1, "OVO eSports")                      # thread body, run sync
        assert pushes[-1] == {"action": "teams", "slot": 1, "name": "OVO eSports"}
        assert ctl.push_status == "ok"
    finally:
        m.post_webhook = orig

def t_setup_data_includes_teams():
    ctl, hs, orig = _team_ctl([])
    try:
        d = ctl.data()
        assert d["options"]["p1"] == ["OVO eSports", "Feel Good"]
        assert d["fields"]["p1"] == "Old A" and d["fields"]["p2"] == "Old B"
        assert "p1" in d["options"] and "p2" in d["options"] and "p3" in d["options"]
    finally:
        m.post_webhook = orig
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_setup.py`
Expected: `AttributeError: 'SetupControl' object has no attribute 'set_team'`.

- [ ] **Step 3: Implement** — add after `SETUP_FIELDS` (line 1121):

```python
# Panel team slots: URL segment -> 1-based podium slot (Overlay tab "Teams P<n>").
TEAM_SLOTS = {"p1": 1, "p2": 2, "p3": 3}
```

Add to `SetupControl` (after `_push_setup`, line 1176):

```python
    # -- team slots (async-optimistic, writes the Overlay tab Teams rows) -------
    def set_team(self, slot_key, name, now=None):
        if slot_key not in TEAM_SLOTS:
            return {"error": f"unknown team slot: {slot_key!r} "
                             f"(one of {', '.join(sorted(TEAM_SLOTS))})"}
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        name = (name or "").strip()
        if name not in self.hud.roster_names():
            return {"error": f"not in the team roster: {name!r} "
                             "(add it to the Configuration tab first)"}
        slot = TEAM_SLOTS[slot_key]
        self.hud.set_team_override(slot - 1, self.hud.resolve_team(name), now)
        threading.Thread(target=self._push_team, args=(slot, name),
                         daemon=True).start()
        return {"ok": True, "slot": slot_key, "value": name, "pending": True}

    def _push_team(self, slot, name):
        ok, _err = self._push({"action": "teams", "slot": slot, "name": name},
                              "teams")
        if ok:
            self.hud.refresh()
```

Extend `SetupControl.data` (lines 1222-1230) to add team fields/options/pending:

```python
    def data(self):
        hud = self.hud.data()
        pending = self.hud.pending()
        team_pending = self.hud.team_pending()
        teams = hud.get("teams", [])
        names = self.hud.roster_names()
        fields = {k: hud.get(hk, "") for k, (_h, hk) in SETUP_FIELDS.items()}
        options = self.hud.vocab()
        out_pending = sorted(k for k, (_h, hk) in SETUP_FIELDS.items() if hk in pending)
        for key, slot in TEAM_SLOTS.items():
            i = slot - 1
            fields[key] = teams[i]["name"] if i < len(teams) else ""
            options[key] = list(names)
            if i in team_pending:
                out_pending.append(key)
        return {"fields": fields, "options": options,
                "pending": sorted(out_pending),
                "push": self.push_status, "last_error": self.last_error}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_setup.py`
Expected: `ALL PASS` (existing `t_setup_data_shape` still holds — it asserts the four scalar fields equal their values and `pending == []`; the new `p1/p2/p3` keys are additive).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(hud): SetupControl team slots (set_team + data) writing Overlay Teams rows"
```

---

## Task 6: Relay `/setup/team/<slot>/<value>` endpoint

**Files:**
- Modify: `src/relay/racecast-feeds.py:1598-1608` (the `if p[:1] == ["setup"]:` GET branch)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** — use the real handler harness `_client(setup_ctl)` (defined at `tests/test_setup.py:241`, returns `(srv, get, post)`) and the roster-backed `_team_ctl` from Task 5. Append to `tests/test_setup.py`:

```python
def t_endpoint_setup_team_sets_slot():
    ctl, hs, orig = _team_ctl([])
    srv, get, post = _client(ctl)
    try:
        r = get("/setup/team/p1/OVO%20eSports")
        assert r.get("ok") and r.get("slot") == "p1" and r.get("value") == "OVO eSports", r
        d = get("/setup/data")                       # optimistic echo visible in slot p1
        assert d["fields"]["p1"] == "OVO eSports", d
    finally:
        srv.shutdown(); m.post_webhook = orig
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_setup.py`
Expected: FAIL — before the route exists, `GET /setup/team/...` falls through to the `{"error":"unknown",...}` 404 branch, so `r.get("ok")` is `None`.

- [ ] **Step 3: Implement** — in the `if p[:1] == ["setup"]:` branch (after the `set` route, line 1605) add:

```python
                    if len(p) == 4 and p[1] == "team":
                        return self._send(setup_ctl.set_team(p[2].lower(),
                                                             unquote(p[3])))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_setup.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(relay): GET /setup/team/<slot>/<value> routes to SetupControl.set_team"
```

---

## Task 7: HUD renders name + number as separate, auto-fit elements

**Files:**
- Modify: `src/obs/hud.html` (lines 40-47 CSS, 64-66 markup, 83-91 `setTeam`)
- Test: none (static page; verified by `build.py` + manual). Keep `tests/test_hud.py` data-shape coverage from Tasks 3-4.

- [ ] **Step 1: Replace the team markup** (lines 64-66) with name+number spans:

```html
  <div id="team0" class="el team white"><img alt=""><span class="num"></span><span class="name"></span></div>
  <div id="team1" class="el team white"><img alt=""><span class="num"></span><span class="name"></span></div>
  <div id="team2" class="el team white"><img alt=""><span class="num"></span><span class="name"></span></div>
```

- [ ] **Step 2: Replace the team CSS** (lines 40-47) with the badge default + auto-fit variables:

```css
  /* Team podium row: brand box + number badge + auto-fit name.
     Name/number are two elements so a per-league override.css can reposition or
     restyle either independently; --team-name-max/min bound the auto-fit. */
  .team { height: 56px; --team-name-max: 30px; --team-name-min: 16px; }
  .team img { width: 54px; height: 50px; object-fit: contain; flex-shrink: 0; }
  .team .num { margin-left: 10px; flex-shrink: 0; background: #c8202a; color: #fff;
    font-size: 20px; padding: 2px 9px; border-radius: 3px; }
  .team .num.empty { display: none; }
  .team .name { margin-left: 12px; min-width: 0; flex: 1; overflow: hidden;
    white-space: nowrap; font-size: var(--team-name-max); }
  #team0 { left: 323px; top: 1005px; width: 382px; }
  #team1 { left: 766px; top: 1005px; width: 379px; }
  #team2 { left: 1210px; top: 1005px; width: 380px; }
```

- [ ] **Step 3: Replace `setTeam`** (lines 83-91) and add `fitName`:

```javascript
  function fitName(el) {
    const cs = getComputedStyle(el);
    const max = parseFloat(cs.getPropertyValue("--team-name-max")) || 30;
    const min = parseFloat(cs.getPropertyValue("--team-name-min")) || 16;
    let size = max;
    el.style.fontSize = size + "px";
    while (size > min && el.scrollWidth > el.clientWidth) {
      size -= 1;
      el.style.fontSize = size + "px";
    }
  }
  function setTeam(i, team) {
    const el = document.getElementById("team" + i);
    const name = (team && team.name) || "";
    const number = (team && team.number) || "";
    const numEl = el.querySelector(".num");
    numEl.textContent = number;
    numEl.classList.toggle("empty", !number);
    const nameEl = el.querySelector(".name");
    nameEl.textContent = name;
    const img = el.querySelector("img");
    if (team && team.brandKey) { img.src = `/hud/assets/brands/${team.brandKey}`; img.style.visibility = "visible"; }
    else img.style.visibility = "hidden";
    el.classList.toggle("empty", !name && !number);
    fitName(nameEl);
  }
```

- [ ] **Step 4: Verify the page builds** (no test runner for HTML; the build's verify step copies it):

Run: `python3 tools/build.py`
Expected: build completes; `dist/` verify passes (HTML is copied, not validated, but a syntax-broken `<style>`/`<script>` would not break the build — eyeball the diff).

- [ ] **Step 5: Commit**

```bash
git add src/obs/hud.html
git commit -m "feat(hud): render team number badge + name as separate auto-fit elements"
```

---

## Task 8: Director panel P1/P2/P3 dropdowns

**Files:**
- Modify: `src/director/director-panel.html` — `SETUP_FIELDS` area (line 817), the setup-row render (~894-903 per the panel-sheet-control spec), `setupSet`/`setupPoll`
- Test: none (static page)

- [ ] **Step 1: Add a teams field list** next to `SETUP_FIELDS` (after line 820):

```javascript
const TEAM_FIELDS = [["p1","P1"], ["p2","P2"], ["p3","P3"]];
```

- [ ] **Step 2: Render the three team selects** alongside the existing setup selects. In the block that builds the setup row (the `SETUP_FIELDS.forEach(...)` loop), append after it:

```javascript
TEAM_FIELDS.forEach(([key,label])=>{
  const w = document.createElement("div"); w.className = "fld";
  w.innerHTML = `<label>${label}</label><select data-team="${key}" disabled></select>`;
  w.querySelector("select").addEventListener("change", e=>teamSet(key, e.target.value));
  $("#setupRow").appendChild(w);
});
```

- [ ] **Step 3: Add `teamSet`** next to `setupSet`:

```javascript
async function teamSet(slot, value){
  if (!value) return;                         // teams are never cleared to empty
  try{
    const r = await fetch("/setup/team/" + slot + "/" + encodeURIComponent(value), {cache:"no-store"});
    const d = await r.json();
    if (d.error){ log("HUD " + slot + ": " + d.error, "err"); toast("HUD " + slot + ": " + d.error); setupPoll(); return; }
    log("HUD " + slot + " → " + value);
    setupPoll();
  }catch(e){ log("HUD " + slot + " failed (relay reachable?): " + e, "err"); toast("HUD " + slot + " failed — relay unreachable"); }
}
```

- [ ] **Step 4: Extend `setupPoll`** to also fill the team selects. Inside `setupPoll`, after the `SETUP_FIELDS` loop, add a parallel loop:

```javascript
for (const [key] of TEAM_FIELDS){
  const sel = document.querySelector(`select[data-team="${key}"]`);
  if (!sel || sel === document.activeElement) continue;
  const opts = d.options[key] || [];
  const sig = JSON.stringify(opts);
  if (sel.dataset.sig !== sig){
    sel.innerHTML = opts.map(o=>`<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("");
    sel.dataset.sig = sig;
  }
  const cur = d.fields[key] || "";
  if ([...sel.options].some(o=>o.value===cur)) sel.value = cur;
  sel.classList.toggle("pending", d.pending.includes(key));
  sel.disabled = d.push === "disabled";
}
```

- [ ] **Step 5: Verify build**

Run: `python3 tools/build.py`
Expected: completes. (If Companion screenshots reference these buttons, no change — this is panel HTML, not Companion.)

- [ ] **Step 6: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): P1/P2/P3 team dropdowns (roster vocab, async-optimistic)"
```

---

## Task 9: Document the sheet schema + Apps Script `teams` writer

**Files:**
- Modify: `src/docs/wiki/Sheet-Webhook.md`
- Test: none (docs). English only.

- [ ] **Step 1: Add the Configuration `Number` column + roster note** near the Setup/Configuration description. Document: the Configuration tab's team-name column may be `Teams` or `Team Name`; an optional `Number` column holds the car number; the relay strips a trailing `#NNN` from the name and the `Number` column wins over it. The Overlay tab `Teams P1/P2/P3` now holds just the team name.

- [ ] **Step 2: Add the `teams` action to the Apps Script** `doPost` dispatch (mirror the existing `setup`/`schedule`/`pov` branches):

```javascript
  else if (action === 'teams') writeTeams(ss, p);
```

- [ ] **Step 3: Add the `writeTeams` function** to the documented Apps Script:

```javascript
function writeTeams(ss, p) {
  const slot = Number(p.slot);
  if (!(slot >= 1 && slot <= 3)) throw 'slot out of range: ' + p.slot;
  const sheet = tab(ss, TABS.overlay);          // the Overlay tab
  const grid = sheet.getDataRange().getValues();
  const label = ('teams p' + slot);             // label lives in column B
  for (let r = 0; r < grid.length; r++) {
    if (String(grid[r][1]).trim().toLowerCase() === label) {
      sheet.getRange(r + 1, 3).setNumberFormat('@').setValue(p.name || '');  // value in col C
      return;
    }
  }
  throw 'label not found in Overlay tab: Teams P' + slot;
}
```

> Confirm `TABS.overlay` exists in the documented script's `TABS` map; if the Overlay tab is referenced by another key, use that. The response contract (`{ok:true, action:'teams', v:2}`) is unchanged — the relay's `check_webhook_response` already enforces the `action` echo.

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/Sheet-Webhook.md
git commit -m "docs(wiki): Configuration Number column + Apps Script teams writer (Overlay tab)"
```

---

## Task 10 (gate): Part 1 green end-to-end

- [ ] **Step 1: Full suite + lint**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
```
Expected: suite `ALL PASS` across files; lint clean.

- [ ] **Step 2: Build verify**

```bash
python3 tools/build.py
```
Expected: assembles `dist/` and passes its self-check (tokenization, no secrets, no shell scripts).

- [ ] **Step 3: Commit any lint fixes** (if `lint.py --fix` changed files):

```bash
git add -A && git commit -m "chore: lint after #80 team split" || echo "nothing to commit"
```

---

# PART 2 — #81: Backup & Restore (library of named looks)

## Task 11: `backup_admin` — label sanitize + manifest + create/list

**Files:**
- Create: `src/scripts/backup_admin.py`
- Test: `tests/test_backup.py` (new)

- [ ] **Step 1: Write the failing test** — create `tests/test_backup.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for profile look backups (overlay+graphics+media zips).
Run: python3 tests/test_backup.py"""
import importlib.util, os, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "backup_admin", os.path.join(ROOT, "src", "scripts", "backup_admin.py"))
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)


def _sources(d):
    """Make a fake profile look: overlay/ + graphics/ + media/ with one file each."""
    overlay = os.path.join(d, "profiles", "x", "overlay")
    graphics = os.path.join(d, "runtime", "x", "graphics")
    media = os.path.join(d, "runtime", "x", "media")
    for sub in (overlay, graphics, media):
        os.makedirs(sub, exist_ok=True)
    open(os.path.join(overlay, "hud.css"), "w").write("body{}")
    open(os.path.join(graphics, "Overlay.png"), "wb").write(b"PNG")
    open(os.path.join(media, "Intro.mp4"), "wb").write(b"MP4")
    return {"overlay": overlay, "graphics": graphics, "media": media,
            "backups": os.path.join(d, "runtime", "x", "backups")}


def t_label_sanitize():
    assert ba.sanitize_label("Winter Theme!") == "winter-theme"
    assert ba.sanitize_label("  v2 2026 ") == "v2-2026"
    try:
        ba.sanitize_label("***"); assert False
    except ValueError:
        pass


def t_create_writes_zip_with_manifest():
    d = tempfile.mkdtemp(); src = _sources(d)
    path = ba.create_backup("Winter Theme", src, profile="x")
    assert path.endswith(os.path.join("backups", "winter-theme.zip"))
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert "manifest.json" in names
        assert "overlay/hud.css" in names
        assert "graphics/Overlay.png" in names
        assert "media/Intro.mp4" in names
        import json
        man = json.loads(z.read("manifest.json"))
        assert man["label"] == "Winter Theme" and man["profile"] == "x"


def t_create_duplicate_needs_force():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("dup", src, profile="x")
    try:
        ba.create_backup("dup", src, profile="x"); assert False
    except FileExistsError:
        pass
    ba.create_backup("dup", src, profile="x", force=True)   # ok


def t_list_reads_manifests():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("Alpha", src, profile="x")
    ba.create_backup("Beta", src, profile="x")
    items = ba.list_backups(src["backups"])
    labels = sorted(i["label"] for i in items)
    assert labels == ["Alpha", "Beta"], labels
    assert all("created" in i and "bytes" in i and i["slug"] for i in items)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_backup.py`
Expected: `FileNotFoundError`/`ModuleNotFound` for `backup_admin.py`.

- [ ] **Step 3: Implement** — create `src/scripts/backup_admin.py`:

```python
"""Pure logic for per-league look backups: zip overlay/+graphics/+media/ into a
named snapshot, list them, restore (full replace), delete. No argv parsing, no
network. Imported by the `racecast backup` CLI and the Control Center providers.
Mirrors chat_admin's discipline: validate before writing, atomic, fail-safe.

A snapshot is runtime/<profile>/backups/<slug>.zip with members:
  manifest.json   {label, slug, profile, created (ISO-UTC), files:[...], counts}
  overlay/...     profiles/<profile>/overlay/ contents
  graphics/...    runtime/<profile>/graphics/ contents
  media/...       runtime/<profile>/media/ contents
"""
import datetime
import io
import json
import os
import re
import shutil
import tempfile
import zipfile

SECTIONS = ("overlay", "graphics", "media")   # zip top-level dirs, in order


def sanitize_label(label):
    """A display label -> a safe filename slug (lowercase, spaces->-, drop other
    punctuation). Raises ValueError when nothing usable remains."""
    slug = re.sub(r"\s+", "-", (label or "").strip().lower())
    slug = re.sub(r"[^a-z0-9._-]", "", slug).strip("-._")
    if not slug:
        raise ValueError(f"label has no usable characters: {label!r}")
    return slug


def _iso_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_tree(zf, src_dir, arc_prefix):
    """Add every file under src_dir to the zip under arc_prefix/. Returns the list
    of relative arcnames added (empty when src_dir is missing/empty)."""
    added = []
    if not src_dir or not os.path.isdir(src_dir):
        return added
    for root, _dirs, files in os.walk(src_dir):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            arc = f"{arc_prefix}/{rel}"
            zf.write(full, arc)
            added.append(arc)
    return added


def create_backup(label, sources, profile, force=False):
    """Zip the three look dirs into runtime/<profile>/backups/<slug>.zip.
    `sources` is a {overlay,graphics,media,backups} dir map. Returns the zip path.
    Raises ValueError (bad label) or FileExistsError (slug taken, no force)."""
    slug = sanitize_label(label)
    backups_dir = sources["backups"]
    os.makedirs(backups_dir, exist_ok=True)
    path = os.path.join(backups_dir, f"{slug}.zip")
    if os.path.exists(path) and not force:
        raise FileExistsError(f"backup already exists: {slug} (use --force to overwrite)")
    files = []
    fd, tmp = tempfile.mkstemp(dir=backups_dir, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for sect in SECTIONS:
                files += _add_tree(zf, sources.get(sect), sect)
            manifest = {"label": label, "slug": slug, "profile": profile,
                        "created": _iso_utc(), "files": files,
                        "counts": {s: sum(1 for f in files if f.startswith(s + "/"))
                                   for s in SECTIONS}}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def read_manifest(path):
    """The manifest dict from a backup zip, or {} when unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}


def list_backups(backups_dir):
    """List snapshots in backups_dir -> [{slug,label,profile,created,bytes,counts}],
    newest 'created' first. Missing dir -> []."""
    out = []
    try:
        names = os.listdir(backups_dir)
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".zip"):
            continue
        path = os.path.join(backups_dir, fn)
        man = read_manifest(path)
        slug = man.get("slug") or fn[:-4]
        out.append({"slug": slug, "label": man.get("label", slug),
                    "profile": man.get("profile", ""),
                    "created": man.get("created", ""),
                    "counts": man.get("counts", {}),
                    "bytes": os.path.getsize(path)})
    out.sort(key=lambda i: i["created"], reverse=True)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_backup.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/backup_admin.py tests/test_backup.py
git commit -m "feat(backup): backup_admin create/list + label sanitize + manifest"
```

---

## Task 12: `backup_admin.restore` — validate, traversal-safe, full replace, atomic

**Files:**
- Modify: `src/scripts/backup_admin.py`
- Test: `tests/test_backup.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_backup.py`:

```python
def t_restore_full_replace():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("snap", src, profile="x")
    # mutate live: extra graphic that must be DROPPED, changed css
    open(os.path.join(src["graphics"], "Extra.png"), "wb").write(b"X")
    open(os.path.join(src["overlay"], "hud.css"), "w").write("CHANGED")
    ba.restore_backup(os.path.join(src["backups"], "snap.zip"), src)
    assert open(os.path.join(src["overlay"], "hud.css")).read() == "body{}"   # restored
    assert not os.path.exists(os.path.join(src["graphics"], "Extra.png"))     # dropped
    assert os.path.exists(os.path.join(src["graphics"], "Overlay.png"))

def t_restore_rejects_traversal():
    d = tempfile.mkdtemp(); src = _sources(d)
    bad = os.path.join(src["backups"], "bad.zip"); os.makedirs(src["backups"], exist_ok=True)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", '{"label":"bad","slug":"bad"}')
        zf.writestr("overlay/../../escape.txt", "x")
    try:
        ba.restore_backup(bad, src); assert False
    except ValueError:
        pass

def t_restore_missing_manifest_rejected():
    d = tempfile.mkdtemp(); src = _sources(d)
    bad = os.path.join(src["backups"], "nomani.zip"); os.makedirs(src["backups"], exist_ok=True)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("overlay/hud.css", "x")
    try:
        ba.restore_backup(bad, src); assert False
    except ValueError:
        pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_backup.py`
Expected: `AttributeError: ... 'restore_backup'`.

- [ ] **Step 3: Implement** — append to `src/scripts/backup_admin.py`:

```python
def _safe_members(zf):
    """Validate every zip member name: no absolute paths, no '..' traversal, only
    manifest.json or a known SECTION/ subtree. Returns the member list or raises
    ValueError. (Defends a restore the same way the relay's asset resolver does.)"""
    members = zf.namelist()
    if "manifest.json" not in members:
        raise ValueError("not a look backup (no manifest.json)")
    for name in members:
        if name == "manifest.json":
            continue
        norm = name.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/"):
            raise ValueError(f"unsafe path in backup: {name!r}")
        top = norm.split("/", 1)[0]
        if top not in SECTIONS:
            raise ValueError(f"unexpected entry in backup: {name!r}")
    return members


def restore_backup(zip_path, sources):
    """Full-replace the three live look dirs with the snapshot's contents. Atomic
    per section: extract to a temp dir, validate, then for each section swap the
    live dir for the extracted one (live-only files are dropped). Raises ValueError
    on a malformed/unsafe archive BEFORE touching any live dir."""
    if not os.path.exists(zip_path):
        raise ValueError(f"backup not found: {zip_path}")
    tmp = tempfile.mkdtemp(prefix="restore-")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_members(zf)                 # raises before any extract
            zf.extractall(tmp)                # safe: names validated above
        for sect in SECTIONS:
            live = sources.get(sect)
            if not live:
                continue
            staged = os.path.join(tmp, sect)
            os.makedirs(staged, exist_ok=True)   # empty section -> empty live dir
            parent = os.path.dirname(live)
            os.makedirs(parent, exist_ok=True)
            old = live + ".old"
            if os.path.exists(old):
                shutil.rmtree(old, ignore_errors=True)
            if os.path.exists(live):
                os.replace(live, old)
            shutil.move(staged, live)
            shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_backup.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/backup_admin.py tests/test_backup.py
git commit -m "feat(backup): restore_backup (traversal-safe validate + full-replace swap)"
```

---

## Task 13: `delete_backup` + `racecast backup` CLI

**Files:**
- Modify: `src/scripts/backup_admin.py` (add `delete_backup`)
- Modify: `src/racecast.py` — `route` (add `backup`), `main` dispatch, `backup_cmd`, source-dir resolver, and the top usage docstring
- Test: `tests/test_backup.py` (delete), `tests/test_racecast.py` (route)

- [ ] **Step 1: Write the failing tests.**

Append to `tests/test_backup.py`:

```python
def t_delete_backup():
    d = tempfile.mkdtemp(); src = _sources(d)
    ba.create_backup("gone", src, profile="x")
    p = os.path.join(src["backups"], "gone.zip")
    assert os.path.exists(p)
    assert ba.delete_backup(src["backups"], "gone") is True
    assert not os.path.exists(p)
    assert ba.delete_backup(src["backups"], "gone") is False   # already gone
```

Add a route test to `tests/test_racecast.py` (match its existing `route` test style):

```python
def t_route_backup():
    assert m.route(["backup", "list"]) == {"kind": "backup", "rest": ["list"]}
    assert m.route(["backup", "create", "Winter"]) == {"kind": "backup", "rest": ["create", "Winter"]}
```

> Open `tests/test_racecast.py` first to confirm the module alias (it loads `src/racecast.py`); reuse that alias instead of `m` if it differs.

- [ ] **Step 2: Run to verify both fail**

Run: `python3 tests/test_backup.py` then `python3 tests/test_racecast.py`
Expected: `AttributeError: ... 'delete_backup'`; route returns `unknown command`.

- [ ] **Step 3: Implement `delete_backup`** — append to `src/scripts/backup_admin.py`:

```python
def delete_backup(backups_dir, slug):
    """Remove backups_dir/<slug>.zip. Returns True if a file was removed, False if
    it was already absent. Raises ValueError on a bad slug."""
    slug = sanitize_label(slug)
    path = os.path.join(backups_dir, f"{slug}.zip")
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
```

- [ ] **Step 4: Wire the CLI.** In `src/racecast.py`:

(a) In `route` add after the `chat` branch (line 649):

```python
    if cmd == "backup":
        return {"kind": "backup", "rest": rest}
```

(b) In `main` add after the `chat` dispatch (line 2916):

```python
    if action["kind"] == "backup":
        return backup_cmd(action["rest"])
```

(c) Add the source-dir resolver + command near `chat_cmd` (after line 717). It reuses the existing `_active_overlay_dir`, `_runtime_dir`, `_active_profile_name`, and `_graphics_media_dirs` (lines 1343-1347) helpers:

```python
BACKUP_VERBS = ("create", "list", "restore", "delete")


def _backup_sources():
    """The four dirs a look backup spans for the active profile."""
    overlay = _active_overlay_dir()              # profiles/<active>/overlay
    g_dir, m_dir = _asset_dirs()                 # runtime/<active>/graphics|media
    return {"overlay": overlay, "graphics": g_dir, "media": m_dir,
            "backups": os.path.join(_runtime_dir(), "backups")}


def backup_cmd(rest):
    """`racecast backup create|list|restore|delete <label>` — named look snapshots
    (overlay CSS + graphics + media) for the active profile."""
    import backup_admin as ba
    verb = rest[0] if rest else None
    if verb not in BACKUP_VERBS:
        sys.exit(f"usage: racecast backup {{{'|'.join(BACKUP_VERBS)}}} [<label>]")
    args = rest[1:]
    src = _backup_sources()
    profile = _active_profile_name() or ""

    if verb == "list":
        items = ba.list_backups(src["backups"])
        if not items:
            print("No backups yet. Create one: racecast backup create <label>")
            return None
        for it in items:
            c = it["counts"]
            print(f"  {it['label']}  ({it['created']}, {it['bytes']} bytes, "
                  f"overlay {c.get('overlay',0)} / graphics {c.get('graphics',0)} "
                  f"/ media {c.get('media',0)})")
        return None

    if verb == "create":
        if not args:
            sys.exit("usage: racecast backup create <label> [--force]")
        force = "--force" in args
        label = " ".join(a for a in args if a != "--force").strip()
        if not label:
            sys.exit("racecast: backup create needs a label")
        try:
            path = ba.create_backup(label, src, profile=profile, force=force)
        except FileExistsError as e:
            sys.exit(f"racecast: {e}")
        except ValueError as e:
            sys.exit(f"racecast: {e}")
        print(f"Saved look '{label}' -> {path}")
        return None

    if verb == "delete":
        if not args:
            sys.exit("usage: racecast backup delete <label>")
        try:
            removed = ba.delete_backup(src["backups"], args[0])
        except ValueError as e:
            sys.exit(f"racecast: {e}")
        print("Deleted." if removed else "racecast: no such backup.")
        return None

    # verb == "restore"
    if not args:
        sys.exit("usage: racecast backup restore <label>")
    try:
        slug = ba.sanitize_label(args[0])
    except ValueError as e:
        sys.exit(f"racecast: {e}")
    zip_path = os.path.join(src["backups"], f"{slug}.zip")
    try:
        ba.restore_backup(zip_path, src)
    except ValueError as e:
        sys.exit(f"racecast: restore failed — {e} (live look unchanged)")
    print(f"Restored look '{args[0]}'.")
    _refresh_obs_pages(force=True)   # best-effort: reload the overlay browser sources
    print("Note: OBS graphics/media sources reload on the next scene activation "
          "(or right-click → Refresh).")
    return None
```

> `_asset_dirs` is the existing helper at `src/racecast.py` (returns `(graphics_dir, media_dir)` for the active profile). `backup_admin` imports by bare name the same way the CLI already does `import obs_ws` / `import tailscale` (`src/scripts` is on `sys.path`).

(d) Add `backup` to the usage docstring command list near the top of `src/racecast.py` (the `racecast ...` synopsis around line 21), e.g. append `| backup {create|list|restore|delete}`.

- [ ] **Step 5: Run to verify it passes**

Run: `python3 tests/test_backup.py` then `python3 tests/test_racecast.py`
Expected: both `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/backup_admin.py src/racecast.py tests/test_backup.py tests/test_racecast.py
git commit -m "feat(backup): racecast backup create|list|restore|delete CLI"
```

---

## Task 14: Control Center "Looks" card (providers + routes + UI)

**Files:**
- Modify: `src/racecast.py` — `backup_list_data` / `backup_create_data` / `backup_restore_data` / `backup_delete_data` providers
- Modify: `src/ui/ui_server.py` — `/api/backup` (GET list, POST create) + `/api/backup/restore` + `/api/backup/delete` routes, and register the providers in the `ctx` map where `overlay_read`/`overlay_write` are wired
- Modify: the Profile-view frontend (served by `ui_server.py`; find it next to the existing overlay-CSS editor) — a "Looks" card
- Test: `tests/test_ui_server.py`

- [ ] **Step 1a: Extend the `_ctx()` factory** in `tests/test_ui_server.py` (the dict returned at lines 36-115) with four backup stubs, mirroring the `streams_read`/`streams_write` echo style (add inside the returned dict, e.g. after `overlay_write`):

```python
            "backup_list": lambda: {"ok": True, "active": "demo",
                                    "items": [{"label": "Winter", "slug": "winter",
                                               "created": "2026-06-12T10:00:00Z",
                                               "bytes": 10, "counts": {}}]},
            "backup_create": lambda label, force=None: {"ok": True,
                                    "_got": {"label": label, "force": force}},
            "backup_restore": lambda slug: {"ok": True, "slug": slug},
            "backup_delete": lambda slug: {"ok": True, "removed": True},
```

- [ ] **Step 1b: Write the failing test** — append to `tests/test_ui_server.py`, mirroring `t_streams_get_and_post_routes` (real server via `_serve`/`_get`/`_post_json`):

```python
def t_api_backup_routes():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/backup")
        data = json.loads(body)
        assert code == 200 and data["ok"] and data["items"][0]["label"] == "Winter"
        code, body = _post_json(port, "/api/backup", {"label": "Spring", "force": False})
        got = json.loads(body)
        assert code == 200 and got["ok"] and got["_got"] == {"label": "Spring", "force": False}
        code, body = _post_json(port, "/api/backup/restore", {"slug": "winter"})
        assert code == 200 and json.loads(body)["ok"]
        code, body = _post_json(port, "/api/backup/delete", {"slug": "winter"})
        assert code == 200 and json.loads(body)["removed"] is True
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: 404 / KeyError for the unrouted `/api/backup`.

- [ ] **Step 3: Add the providers** to `src/racecast.py` (near `overlay_read_data`, line 2190). They wrap `backup_admin` and never raise:

```python
def backup_list_data():
    """{ok, active, items:[...]} for the Control Center Looks card."""
    try:
        import backup_admin as ba
        active = _active_profile_name()
        if not active:
            return {"ok": False, "error": "no active profile"}
        return {"ok": True, "active": active,
                "items": ba.list_backups(_backup_sources()["backups"])}
    except Exception as exc:
        return {"ok": False, "error": f"could not list backups: {exc}"}


def backup_create_data(label, force=False):
    try:
        import backup_admin as ba
        if not _active_profile_name():
            return {"ok": False, "error": "no active profile"}
        if not isinstance(label, str) or not label.strip():
            return {"ok": False, "error": "label required"}
        path = ba.create_backup(label, _backup_sources(),
                                profile=_active_profile_name(), force=bool(force))
        return {"ok": True, "path": path}
    except FileExistsError:
        return {"ok": False, "error": "a backup with that name exists (use force)"}
    except Exception as exc:
        return {"ok": False, "error": f"could not create backup: {exc}"}


def backup_restore_data(slug):
    try:
        import backup_admin as ba
        src = _backup_sources()
        zip_path = os.path.join(src["backups"], f"{ba.sanitize_label(slug)}.zip")
        ba.restore_backup(zip_path, src)
        try:
            _refresh_obs_pages(force=True)
        except Exception:
            pass   # OBS refresh is best-effort; the restore already succeeded
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"restore failed: {exc} (live look unchanged)"}


def backup_delete_data(slug):
    try:
        import backup_admin as ba
        removed = ba.delete_backup(_backup_sources()["backups"], slug)
        return {"ok": True, "removed": removed}
    except Exception as exc:
        return {"ok": False, "error": f"could not delete backup: {exc}"}
```

- [ ] **Step 4: Register providers in the `ctx` map.** Find where `ui_cmd` builds the `ctx` dict passed to `ui_server` (it already wires `overlay_read`/`overlay_write`, `profile_new`, etc.). Add:

```python
        "backup_list": backup_list_data,
        "backup_create": backup_create_data,
        "backup_restore": backup_restore_data,
        "backup_delete": backup_delete_data,
```

- [ ] **Step 5: Add the routes** in `src/ui/ui_server.py`. In `do_GET`, next to the `/api/overlay` route (line 301):

```python
            if path == "/api/backup":
                return self._json(ctx["backup_list"]())
```

In `do_POST`, next to the `/api/overlay` route (line 401):

```python
            if path == "/api/backup":
                return self._json(ctx["backup_create"](
                    body.get("label"), body.get("force")))
            if path == "/api/backup/restore":
                return self._json(ctx["backup_restore"](body.get("slug")))
            if path == "/api/backup/delete":
                return self._json(ctx["backup_delete"](body.get("slug")))
```

- [ ] **Step 6: Add the "Looks" card** to the Profile view in `src/ui/control-center.html` (the single served frontend — grep it for `api/overlay` to find the overlay-CSS editor and add the card next to it). Add a card that:
  - on load `GET /api/backup` → renders each item as `<label> (<created>)` with **Restore** and **Delete** buttons,
  - a text input + **Create backup** button → `POST /api/backup {label}`,
  - **Restore** → confirm dialog → `POST /api/backup/restore {slug}` → toast + a note that OBS graphics/media reload on next scene activation,
  - **Delete** → confirm → `POST /api/backup/delete {slug}` → refresh the list.

Follow the exact fetch/render/toast patterns the overlay-CSS editor already uses in that file (same `$`/`fetch`/error-handling helpers). Keep all strings English.

- [ ] **Step 7: Run to verify it passes**

Run: `python3 tests/test_ui_server.py`
Expected: `ALL PASS`.

- [ ] **Step 8: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py src/ui/ tests/test_ui_server.py
git commit -m "feat(ui): Control Center Looks card (backup list/create/restore/delete)"
```

---

## Task 15: Final gate — suite, lint, build, docs

**Files:**
- Modify: `README.md` (add the `racecast backup` line to the command list), `CLAUDE.md` (one line under the CLI commands + a `tests/test_backup.py` entry in the test list)

- [ ] **Step 1: Add docs lines.** In `README.md` and `CLAUDE.md` command lists add:

```
python3 src/racecast.py backup create|list|restore|delete <label>   # named look snapshots (overlay+graphics+media)
```
and in `CLAUDE.md`'s test list:
```
python3 tests/test_backup.py         # profile look backups (zip snapshot create/list/restore/delete)
```

- [ ] **Step 2: Full suite + lint + build**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: suite `ALL PASS`, lint clean, build self-verify passes.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document racecast backup (look snapshots)"
```

- [ ] **Step 4: Push + open the PR**

```bash
git push -u origin feat/per-league-overlay-identity
gh pr create --title "Per-league overlay identity: split team name/number + panel Top-3 (#80) + look backup/restore (#81)" \
  --body "Implements #80 and #81 per docs/superpowers/specs/2026-06-12-per-league-overlay-identity-design.md. See the plan for task breakdown."
```

---

## Notes for the implementer

- **Run order matters in Part 1.** Tasks 2-4 temporarily break callers between commits within a task but each task ends green. Always run the named test file at each step.
- **The `_hs_stub` CONFIG_CSV** in `tests/test_setup.py` uses `T #1`/`T #2` with no `Number` column — exercising the embedded-`#NNN` fallback for free. Don't "fix" it to add a Number column; the fallback path needs the coverage.
- **No real IPs / machine paths in tests** (CLAUDE.md hard rule) — the backup tests use `tempfile.mkdtemp()` trees only.
- **English-only** for every shipped string and doc (CLAUDE.md). German is for the chat, not the code.
- **Grep before renaming a flag/endpoint** across `tools/` and `.github/` (CLAUDE.md) — this plan adds endpoints/verbs, removes none, so the binary smoke test is unaffected; still run `tools/build.py`.
- **OBS image/media auto-reload after restore** is intentionally minimal (browser-source refresh + a printed note). Deeper per-input reload is a deferred open question in the spec — do not expand scope here.
```
