# Event Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Event Notes" Google-Sheet tab the league owner maintains, shown as a toggleable modal opened from a header button in the Director Panel, Commentator Cockpit, and Race Control pages.

**Architecture:** A pure parser (`event_notes.py`) turns the tab CSV into note dicts; an `EventNotesSource` (clone of `ChannelSource`) polls it in the relay; a dual GET endpoint (`/event-notes/data` tailnet + `/console/event-notes/data` Funnel, `ANY`-auth) serves the same payload; each of the three console pages gets a `📋 Notes` button + a native `<dialog>` modal polled via the `RC_API` shim.

**Tech Stack:** Python 3 stdlib only (`csv`, `io`, `threading`, `urllib`); vanilla JS + native `<dialog>` in the HTML pages. No new dependencies.

## Global Constraints

- Edit only under `src/` (and `tests/`, `docs/`). Never hand-edit `dist/`/`runtime/`.
- Python 3 stdlib only — no new third-party imports.
- All shipped scripts/docs English only.
- No machine paths / real IPs in committed files (Tailscale test IPs are `100.64.0.0/10`).
- Read-only feature: no write path from any console; notes are admin-managed in the Sheet.
- One shared notes list for all three roles; `Requirement(ANY, False)` on the Funnel endpoint.
- Relay sources are exempt from the `http_util` UA guard (relay stays dependency-light) — use the same `Request(..., headers={"User-Agent": "racecast-feeds/1.0"})` idiom as `ChannelSource`.
- Director Panel is screenshot-blocking (CLAUDE.md): `director-panel.png` must be refreshed in this PR.
- After any Python change run `python3 tools/lint.py`; gate the PR on `python3 tools/run-tests.py` + `python3 tools/build.py` (exit 0).

---

### Task 1: Pure parser — `event_notes.py`

**Files:**
- Create: `src/scripts/event_notes.py`
- Test: `tests/test_event_notes.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces: `parse_event_notes(csv_text) -> list[dict]`, each dict `{"heading": str, "note": str, "priority": "info"|"important"}`. Consumed by `EventNotesSource.refresh()` (Task 2) and the endpoint payload.

- [ ] **Step 1: Write the failing test**

Create `tests/test_event_notes.py` (runnable script style — mirrors `tests/test_streams.py`: `t_*` functions, a `run()` that calls each, `print("ALL PASS")`, `if __name__ == "__main__": run()`):

```python
#!/usr/bin/env python3
"""Unit checks for the Event Notes Sheet-tab parser (pure, stdlib only)."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_path = os.path.join(HERE, "..", "src", "scripts", "event_notes.py")
_spec = importlib.util.spec_from_file_location("event_notes", _path)
event_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(event_notes)
parse = event_notes.parse_event_notes


def t_basic_rows():
    csv_text = "Heading,Note,Priority\nWelcome,Mind the sponsor read,Important\n,Running order on screen,\n"
    out = parse(csv_text)
    assert out == [
        {"heading": "Welcome", "note": "Mind the sponsor read", "priority": "important"},
        {"heading": "", "note": "Running order on screen", "priority": "info"},
    ], out


def t_header_order_independent():
    csv_text = "Note,Priority,Heading\nDo the thing,info,Hi\n"
    out = parse(csv_text)
    assert out == [{"heading": "Hi", "note": "Do the thing", "priority": "info"}], out


def t_priority_normalisation():
    csv_text = "Heading,Note,Priority\nA,n1,IMPORTANT\nB,n2,important\nC,n3,Info\nD,n4,\nE,n5,banana\n"
    pris = [r["priority"] for r in parse(csv_text)]
    assert pris == ["important", "important", "info", "info", "info"], pris


def t_empty_note_rows_skipped():
    csv_text = "Heading,Note,Priority\nH,,Important\nH2,real note,\n"
    out = parse(csv_text)
    assert [r["note"] for r in out] == ["real note"], out


def t_missing_columns_and_empty_degrade():
    assert parse("") == []
    assert parse("Heading,Priority\nH,Important\n") == []        # no Note column
    assert parse("Heading,Note,Priority\n") == []                 # header only
    # Missing Heading/Priority columns still parse Note rows:
    out = parse("Note\njust a note\n")
    assert out == [{"heading": "", "note": "just a note", "priority": "info"}], out


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_event_notes.py`
Expected: FAIL — `FileNotFoundError` / `ModuleNotFoundError` for `event_notes.py` (file not created yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/event_notes.py`:

```python
#!/usr/bin/env python3
"""Pure parser for the Sheet `Event Notes` tab (#owner-notes).

Header-located like broadcast_chat.parse_channel_tab: a `Note` column is
required; `Heading` and `Priority` are optional. Each data row with a non-empty
Note becomes {"heading", "note", "priority"} with priority normalised to
"important" (the only highlighted value) or "info" (empty/unknown). No header /
no Note column / empty CSV -> [] (the modal then has nothing to show). No I/O,
no network -- the relay's EventNotesSource does the fetch."""

import csv
import io

NOTE_HEADERS = ("note", "notes", "text")
HEADING_HEADERS = ("heading", "title", "section")
PRIORITY_HEADERS = ("priority", "level")


def _col(header, names):
    return next((header.index(h) for h in names if h in header), None)


def parse_event_notes(text):
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    header = [(h or "").strip().lower() for h in rows[0]]
    note_i = _col(header, NOTE_HEADERS)
    if note_i is None:
        return []
    head_i = _col(header, HEADING_HEADERS)
    pri_i = _col(header, PRIORITY_HEADERS)
    out = []
    for r in rows[1:]:
        note = r[note_i].strip() if len(r) > note_i else ""
        if not note:
            continue
        heading = r[head_i].strip() if head_i is not None and len(r) > head_i else ""
        pri_raw = r[pri_i].strip().lower() if pri_i is not None and len(r) > pri_i else ""
        priority = "important" if pri_raw == "important" else "info"
        out.append({"heading": heading, "note": note, "priority": priority})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_event_notes.py`
Expected: PASS — prints `ok t_*` lines then `ALL PASS`.

- [ ] **Step 5: Lint**

Run: `python3 tools/lint.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/scripts/event_notes.py tests/test_event_notes.py
git commit -m "feat(notes): pure parser for the Event Notes Sheet tab"
```

---

### Task 2: Relay source, wiring, endpoints + policy

**Files:**
- Modify: `src/relay/racecast-feeds.py` (add `EventNotesSource` after `ChannelSource` ~`:1808`; import `parse_event_notes`; CLI flags ~`:6573`; gviz wiring ~`:6741`; poller registration ~`:6929`; `do_GET` root branch ~`:6163`)
- Modify: `src/scripts/console_policy.py` (add `event-notes/data` → `Requirement(ANY, False)` ~`:113`)
- Test: `tests/test_console.py` (add an event-notes ANY-policy check)

**Interfaces:**
- Consumes: `parse_event_notes(csv_text)` (Task 1); the existing `poller(source, interval, stop_evt)` and gviz-URL idiom.
- Produces: `EventNotesSource(csv_url, cache_path)` with `.refresh()` / `.get()` (returns `list[dict]` of notes); root endpoint `GET /event-notes/data` → `{"available": bool, "notes": [...]}`; Funnel mirror `GET /console/event-notes/data` (same payload, `ANY`). `args.event_notes_tab` (default `"Event Notes"`) and `args.no_event_notes` flags.

- [ ] **Step 1: Import the parser**

The relay imports `src/scripts` modules near the top of `src/relay/racecast-feeds.py` (find the block importing `broadcast_chat`). Add alongside it:

```python
import event_notes   # noqa: E402  (pure Event Notes tab parser)
```
(Match the exact import style used for `broadcast_chat` in that file — if it is `from scripts import broadcast_chat` or a path-injected `import broadcast_chat`, mirror that form for `event_notes`.)

- [ ] **Step 2: Add the `EventNotesSource` class**

Insert immediately after `ChannelSource` ends (`src/relay/racecast-feeds.py:1808`, before `class _BroadcastReader`):

```python
class EventNotesSource:
    """Reads the Sheet `Event Notes` tab (CSV) -> [{heading, note, priority}].

    Thin fetch+parse wrapper (parsing is the pure event_notes.parse_event_notes).
    A missing/empty/unreachable tab is non-fatal -- it simply yields no notes, so
    the console modal button self-hides."""

    def __init__(self, csv_url, cache_path=None):
        self.csv_url = csv_url
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self.rows = []
        self.last_error = None

    def _fetch_text(self, timeout=15):
        if not self.csv_url:
            return None
        try:
            req = Request(self.csv_url, headers={"User-Agent": "racecast-feeds/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def refresh(self, timeout=15):
        text = self._fetch_text(timeout)
        if text is None:
            return False
        rows = event_notes.parse_event_notes(text)
        with self.lock:
            self.rows = rows
            self.last_error = None
        return True

    def get(self):
        with self.lock:
            return list(self.rows)
```

- [ ] **Step 3: Add CLI flags**

After the `--channel-tab` / `--no-broadcast-chat` arguments (`src/relay/racecast-feeds.py:6573-6578`), add:

```python
    ap.add_argument("--event-notes-tab", default="Event Notes",
                    help="Sheet tab name for the Event Notes modal "
                         "(default 'Event Notes'). Disabled by a custom "
                         "--sheet-csv-url or --no-event-notes.")
    ap.add_argument("--no-event-notes", action="store_true",
                    help="Disable the Event Notes reader/modal.")
```

- [ ] **Step 4: Build the source (gviz URL + warm refresh)**

After the channel-source block (`src/relay/racecast-feeds.py:6734-6741`), add:

```python
    # Event Notes (#owner-notes): a read-only league-owner notes tab shown as a
    # modal in the three console pages. Derived from sheet-id/tab like the crew
    # roster, so a custom --sheet-csv-url (or --no-event-notes) disables it.
    event_notes_source = None
    if not args.sheet_csv_url and not args.no_event_notes:
        event_notes_csv_url = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                               f"/gviz/tq?tqx=out:csv&sheet={quote(args.event_notes_tab)}")
        event_notes_cache = os.path.join(runtime, "event-notes.cache.txt")
        event_notes_source = EventNotesSource(event_notes_csv_url, event_notes_cache)
        event_notes_source.refresh()   # non-fatal: empty/unreachable = no notes
```

- [ ] **Step 5: Register the poller**

After the crew poller registration (`src/relay/racecast-feeds.py:6927-6929`), add:

```python
    if event_notes_source:
        threading.Thread(target=poller, args=(event_notes_source, args.poll, stop_evt),
                         daemon=True).start()
```

- [ ] **Step 6: Add the root endpoint branch**

In `do_GET`, after the `["crew", "data"]` branch (`src/relay/racecast-feeds.py:6163`), add (`event_notes_source` is a closure variable like `crew_source`):

```python
                if p == ["event-notes", "data"]:
                    # League-owner notes shown as a modal in the three console
                    # pages. Read-only; one shared list for all roles. Mirrored
                    # at /console/event-notes/data (ANY-auth) via the gate's
                    # generic ALLOW fall-through. Disabled -> available:false ->
                    # the front-end hides the button.
                    notes = event_notes_source.get() if event_notes_source else []
                    return self._send({"available": bool(notes), "notes": notes})
```

- [ ] **Step 7: Add the policy line (Funnel ANY-auth)**

In `src/scripts/console_policy.py`, after the health-monitor block (`:111-113`), add:

```python
    # --- event notes: read-only league-owner notes, any authenticated subject ---
    # One shared list for Director/Commentator/Race Control. Read-only, no stream
    # URLs -> same tier as the cockpit monitors. Mirrored from the root branch via
    # the gate's generic ALLOW fall-through (return sub).
    if p == ["event-notes", "data"]:
        return Requirement(ANY, False)
```

- [ ] **Step 8: Write the failing policy test**

In `tests/test_console.py`, add a test mirroring the existing health-monitor/ANY policy checks (find an existing `decide(...)` assertion to copy the import + call style):

```python
def t_event_notes_any_authenticated():
    # Any authenticated subject (even role-less) may read the notes...
    assert console_policy.decide(set(), ["event-notes", "data"], "GET") == console_policy.ALLOW
    assert console_policy.decide({"commentator"}, ["event-notes", "data"], "GET") == console_policy.ALLOW
    # ...and it is NOT a recognized POST/write route.
    assert console_policy.decide({"director"}, ["event-notes", "send"], "GET") == console_policy.NOT_FOUND
```
(Register it the way `tests/test_console.py` registers its other `t_*` functions — match that file's runner convention.)

- [ ] **Step 9: Run the policy test to verify it fails, then passes**

Run: `python3 tests/test_console.py`
Expected (before Step 7 applied): FAIL — `event-notes/data` returns `NOT_FOUND`, not `ALLOW`. After Step 7: PASS.
(If Steps 7 and 8 are applied together, run once and confirm PASS.)

- [ ] **Step 10: Relay smoke + full relay/console suites + lint**

```bash
python3 tests/test_pov.py          # relay still imports/parses cleanly
python3 tests/test_console.py
python3 tests/test_console_gate.py
python3 tools/lint.py
```
Expected: all PASS / `All checks passed!`.

- [ ] **Step 11: Commit**

```bash
git add src/relay/racecast-feeds.py src/scripts/console_policy.py tests/test_console.py
git commit -m "feat(notes): relay Event Notes source + dual endpoint (tailnet + Funnel ANY)"
```

---

### Task 3: Front-end button + modal in the three console pages

**Files:**
- Modify: `src/cockpit/cockpit.html` (header `.appmeta` `:244-249`; add modal markup + CSS + JS)
- Modify: `src/racecontrol/race-control.html` (header `.appmeta` `:138-143`)
- Modify: `src/director/director-panel.html` (header `.appmeta` `:412-417`)

**Interfaces:**
- Consumes: `GET /event-notes/data` → `{"available": bool, "notes": [{heading, note, priority}]}` (Task 2), fetched via the page's patched `fetch`/`RC_API` shim on the bare path.
- Produces: a `📋 Notes` button (`id="notesBtn"`, hidden until notes exist) + a `<dialog id="notesModal">` in each page.

The three pages duplicate the shim/header boilerplate; the snippets below are identical in all three — only the insertion line anchors differ. Apply to **all three** pages.

- [ ] **Step 1: Add the button to `.appmeta` (all three pages)**

In each page's `.appmeta` block, immediately before the `<a class="help" ...>` link, add:

```html
    <button type="button" id="notesBtn" class="notesbtn" hidden onclick="openNotes()">📋 Notes</button>
```
Anchors: `cockpit.html:247`, `race-control.html:141`, `director-panel.html:415`.

- [ ] **Step 2: Add the modal markup (all three pages)**

Immediately before `</body>` in each page, add:

```html
<dialog id="notesModal" class="notesmodal">
  <h3>Event Notes</h3>
  <div id="notesBody" class="notesbody"></div>
  <div class="notesactions"><button type="button" onclick="closeNotes()" autofocus>Close</button></div>
</dialog>
```

- [ ] **Step 3: Add the CSS (all three pages)**

Add to each page's `<style>` block (the values are theme-neutral and self-contained):

```css
  .notesbtn { font: inherit; cursor: pointer; background: transparent;
    border: 1px solid currentColor; border-radius: 6px; padding: 2px 8px; color: inherit; }
  .notesmodal { max-width: 560px; width: 90vw; border: none; border-radius: 10px;
    padding: 20px; background: #1c1f26; color: #e8eaed; }
  .notesmodal::backdrop { background: rgba(0,0,0,.45); }
  .notesmodal h3 { margin: 0 0 12px; }
  .notesbody { display: flex; flex-direction: column; gap: 10px; max-height: 60vh; overflow: auto; }
  .noteitem { padding-left: 10px; border-left: 3px solid transparent; }
  .noteitem.important { border-left-color: #f5a623; }
  .notehd { font-weight: 700; margin-bottom: 2px; }
  .notetxt { white-space: pre-wrap; }
  .notesactions { display: flex; justify-content: flex-end; margin-top: 16px; }
```

- [ ] **Step 4: Add the JS (all three pages)**

Add to each page's main `<script>` block (after the RC_API shim is already in place — it patches `window.fetch`, so the bare path is Funnel-safe):

```js
  function openNotes() { document.getElementById('notesModal').showModal(); }
  function closeNotes() { document.getElementById('notesModal').close(); }
  function renderNotes(d) {
    const notes = (d && d.available && Array.isArray(d.notes)) ? d.notes : [];
    document.getElementById('notesBtn').hidden = notes.length === 0;
    const body = document.getElementById('notesBody');
    body.textContent = '';
    notes.forEach(function (n) {
      const item = document.createElement('div');
      item.className = 'noteitem' + (n.priority === 'important' ? ' important' : '');
      if (n.heading) {
        const h = document.createElement('div');
        h.className = 'notehd';
        h.textContent = n.heading;
        item.appendChild(h);
      }
      const t = document.createElement('div');
      t.className = 'notetxt';
      t.textContent = n.note;
      item.appendChild(t);
      body.appendChild(item);
    });
  }
  async function pollNotes() {
    try {
      const r = await fetch('/event-notes/data', { cache: 'no-store' });
      if (r.ok) renderNotes(await r.json());
    } catch (e) { /* transient — keep last state */ }
    setTimeout(pollNotes, 30000);
  }
  pollNotes();
```

- [ ] **Step 5: Manual verify against a demo relay**

Follow the `wiki-screenshots` recipe (demo profile + obs-sim), add an `Event Notes` tab to a local CSV or temporarily seed notes, then load each page and confirm: button hidden when no notes, visible when notes exist, modal opens/closes (Esc + Close), `Important` row highlighted, heading bold. (No automated DOM test — this is HTML; verified by build + the screenshot pass in Task 4.)

- [ ] **Step 6: Commit**

```bash
git add src/cockpit/cockpit.html src/racecontrol/race-control.html src/director/director-panel.html
git commit -m "feat(notes): Event Notes button + modal in cockpit, race-control, director panel"
```

---

### Task 4: Docs, screenshots, and full gates

**Files:**
- Modify: a Sheet-side wiki page documenting tabs (`src/docs/wiki/Sheet-Template.md` and/or `Sheet-Webhook.md` — match where `Channel`/`Crew`/`Cue Preset` are documented)
- Modify: `src/docs/wiki/images/director-panel.png` (mandatory), `console-cockpit.png`, `console-race-control.png` (good practice)

**Interfaces:** none (docs/assets only).

- [ ] **Step 1: Document the `Event Notes` tab**

In the Sheet wiki page that lists the tabs/columns (where `Channel` and the `Cue Preset` column are described), add an `Event Notes` section: tab name `Event Notes`, header `Heading | Note | Priority`, semantics (one note per row with non-empty `Note`; `Heading` optional bold label; `Priority` = `Important` to highlight, else normal), and that it is read-only/optional (absent tab → the modal button self-hides). Keep it parallel in tone to the existing tab docs.

- [ ] **Step 2: Validate wiki links**

Run: `python3 tests/test_wiki.py`
Expected: PASS (no broken links/anchors introduced).

- [ ] **Step 3: Refresh screenshots**

Use the `wiki-screenshots` skill (demo profile + `tools/obs-sim.py`, dev build). The demo Sheet is read-only and has no `Event Notes` tab, so seed notes locally with a temporary, env-guarded block in `src/relay/racecast-feeds.py` right after `event_notes_source` is constructed (mirroring the broadcast-chat seed pattern the skill documents):

```python
    if os.environ.get("RACECAST_SEED_NOTES") == "1":
        event_notes_source = EventNotesSource(None)   # no network
        event_notes_source.rows = [
            {"heading": "Welcome", "note": "Sponsor read at the top of stint 3.", "priority": "important"},
            {"heading": "", "note": "Running order is on the lower third.", "priority": "info"},
            {"heading": "", "note": "Wrap each interview to ~90s.", "priority": "info"},
        ]
```

Run the relay with `RACECAST_SEED_NOTES=1`, capture, then **delete exactly those added lines** with a targeted edit (never `git checkout` the whole relay file — it would wipe other uncommitted work). Capture:
- `src/docs/wiki/images/director-panel.png` (**mandatory**) — with the `📋 Notes` button visible and the modal open.
- `src/docs/wiki/images/console-cockpit.png` and `console-race-control.png` (good practice).
Write the identical file to `src/docs/slides/assets/img/<name>.png` for any shot a slide deck reuses. Revert any temporary seed edit surgically (never `git checkout` the whole relay file) and `git checkout -- profiles/demo/profile.env` (CONSOLE_SECRET gotcha).

- [ ] **Step 4: Full local gates**

```bash
python3 tools/run-tests.py     # whole suite
python3 tools/lint.py          # ruff
python3 tools/build.py         # must exit 0 (verify step ~= CI)
```
Expected: suite `ALL TEST FILES PASS`, lint `All checks passed!`, build exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/ src/docs/slides/ 2>/dev/null; git add -A src/docs
git commit -m "docs(notes): document the Event Notes tab + refresh console screenshots"
```

---

## Self-Review

**Spec coverage:**
- Sheet tab schema (`Heading | Note | Priority`, header-located, `Important` highlight, no grouping) → Task 1 parser + Task 4 docs. ✓
- Pure parser in dedicated module → Task 1. ✓
- `EventNotesSource` (ChannelSource clone), flags, gviz wiring, poller → Task 2. ✓
- Dual endpoint tailnet + Funnel `ANY` → Task 2 (root branch + policy line + gate fall-through). ✓
- Disabled/empty → `available:false`, button hidden → Task 2 (endpoint) + Task 3 (renderNotes). ✓
- Button in `.appmeta`, native `<dialog>`, 30 s poll via RC_API shim, all three pages → Task 3. ✓
- Tests: parser + policy → Tasks 1, 2. ✓
- Director Panel screenshot (mandatory) + cockpit/RC + Sheet wiki doc → Task 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the full code. The screenshot seeding step (Task 4 Step 3) references the `wiki-screenshots` skill's documented seed mechanism rather than inventing one — acceptable, it is an asset-capture step, not code.

**Type consistency:** `parse_event_notes` returns `list[{heading,note,priority}]` everywhere; `EventNotesSource.get()` returns that list; the endpoint wraps it as `{available, notes}`; `renderNotes` reads `d.available` + `d.notes[].{heading,note,priority}`. `priority` is the lowercase token `"important"`/`"info"` in parser, endpoint, and JS check. Flag `args.event_notes_tab` / `args.no_event_notes` consistent between flag def and wiring. ✓
