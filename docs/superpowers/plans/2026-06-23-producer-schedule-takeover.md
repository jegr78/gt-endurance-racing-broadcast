# Producer Schedule + one-click takeover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the league's read-only `Producer` Sheet tab (`Part | Producer | MagicDNS`) on the Control Center Home view and let a producer trigger a Funnel takeover against the right machine in one click — never against their own machine.

**Architecture:** A pure CSV parser (`src/scripts/producer.py`) + a pure MagicDNS self-match helper (`src/scripts/tailscale.py`) feed a tolerant status provider in `src/racecast.py` that the Control Center exposes on demand at `/api/producer-schedule`. The Home view (`src/ui/control-center.html`) renders a table; each row reuses the existing `event-takeover --funnel` op. No relay endpoint and no running relay are required (takeover happens before B's relay is up).

**Tech Stack:** Pure Python 3 stdlib (`csv`, `io`, `urllib`), the repo's `http_util` outbound-HTTP helper, the existing `ui_server`/`ui_ops` Control Center, vanilla HTML/JS. Tests are stdlib runnable scripts under `tests/`.

## Global Constraints

- **Edit only under `src/`** (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- **All scripts and docs English only.**
- **Outbound HTTP goes through `src/scripts/http_util.py`** on the covered side (`racecast.py`). Never call `urllib`/`urlopen` directly there — `tests/test_http_util.py` enforces it.
- **Never hardcode secrets or machine paths.** No real IPs in tests; Tailscale test IPs are `100.64.0.0/10` constants.
- **Tests must run on any machine and in CI** — stdlib only, each test file is a runnable script; the whole suite is `python3 tools/run-tests.py`.
- **Run `python3 tools/lint.py` after changing any Python file.**
- **Changed a UI surface? Refresh its wiki screenshot in the SAME change.** The Home view image is `src/docs/wiki/images/cc-home.png`, captured from a **local dev build** (run `racecast ui` from `src/`, no `VERSION` stamped).
- **Self-match policy: exact FQDN** (case-insensitive, trailing dot ignored). The `MagicDNS` column must hold full `*.ts.net` names; bare hostnames do NOT match.
- **Takeover path: always Funnel** — a row runs `event takeover <MagicDNS> --funnel`.

---

### Task 1: Pure `Producer` tab parser

**Files:**
- Create: `src/scripts/producer.py`
- Test: `tests/test_producer.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `parse_producer_rows(text: str) -> list[dict]` where each dict is
    `{"part": str, "producer": str, "magicdns": str}`. Header REQUIRED (no
    positional fallback); order + duplicates preserved.
  - Module constants `PRODUCER_PART_HEADERS`, `PRODUCER_PRODUCER_HEADERS`,
    `PRODUCER_MAGICDNS_HEADERS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_producer.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the read-only Producer-tab parser.
Run: python3 tests/test_producer.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import producer as p


def t_header_mode_parses_three_columns():
    text = ("Part,Producer,MagicDNS\r\n"
            "1,Alice,producer-a.tail1234.ts.net\r\n"
            "2,Bob,producer-b.tail1234.ts.net\r\n")
    assert p.parse_producer_rows(text) == [
        {"part": "1", "producer": "Alice", "magicdns": "producer-a.tail1234.ts.net"},
        {"part": "2", "producer": "Bob", "magicdns": "producer-b.tail1234.ts.net"},
    ]


def t_header_synonyms_and_reordered_columns():
    text = ("MagicDNS,Magic-DNS-IGNORED,Producer,Part\r\n"  # first match wins for magicdns
            "host-x.ts.net,zzz,Carol,3\r\n")
    rows = p.parse_producer_rows(text)
    assert rows == [{"part": "3", "producer": "Carol", "magicdns": "host-x.ts.net"}], rows


def t_magic_dns_spaced_header_synonym():
    text = "Part,Producer,Magic DNS\r\n1,Dan,d.ts.net\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "1", "producer": "Dan", "magicdns": "d.ts.net"}]


def t_duplicates_preserved():
    text = ("Part,Producer,MagicDNS\r\n"
            "2,Bob,producer-b.ts.net\r\n"
            "3,Bob,producer-b.ts.net\r\n")
    rows = p.parse_producer_rows(text)
    assert len(rows) == 2 and rows[0] == rows[1], rows


def t_empty_magicdns_cell_kept():
    text = "Part,Producer,MagicDNS\r\n4,Eve,\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "4", "producer": "Eve", "magicdns": ""}]


def t_blank_spacer_rows_dropped():
    text = "Part,Producer,MagicDNS\r\n,,\r\n5,Frank,f.ts.net\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "5", "producer": "Frank", "magicdns": "f.ts.net"}]


def t_missing_header_returns_empty():
    # No recognizable header row -> empty (no positional fallback).
    text = "1,Alice,a.ts.net\r\n2,Bob,b.ts.net\r\n"
    assert p.parse_producer_rows(text) == []


def t_partial_header_returns_empty():
    text = "Part,Producer\r\n1,Alice\r\n"  # MagicDNS column absent
    assert p.parse_producer_rows(text) == []


def t_empty_text_returns_empty():
    assert p.parse_producer_rows("") == []
    assert p.parse_producer_rows(None) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all producer tests passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_producer.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'producer'`.

- [ ] **Step 3: Write the parser**

Create `src/scripts/producer.py`:

```python
#!/usr/bin/env python3
"""Pure parser for the league Sheet's read-only `Producer` tab
(`Part | Producer | MagicDNS`) — the per-event producer handover schedule shown
on the Control Center Home view. No I/O: the Control Center provider fetches the
gviz CSV and tags each row with `self` after parsing.

Header row is REQUIRED — unlike Schedule/Crew there is no positional fallback:
this is a new, documented tab, so an unrecognized header yields an empty list
(the Home card then hides itself) rather than a silent column mis-read."""
import csv
import io

PRODUCER_PART_HEADERS = ("part",)
PRODUCER_PRODUCER_HEADERS = ("producer",)
PRODUCER_MAGICDNS_HEADERS = ("magicdns", "magic-dns", "magicdns name", "magic dns")


def _find(header, names):
    """Index of the first cell in `header` (already lowercased/stripped) that
    matches any of `names`, or None."""
    for i, cell in enumerate(header):
        if cell in names:
            return i
    return None


def _cell(row, i):
    return row[i].strip() if (0 <= i < len(row) and row[i]) else ""


def parse_producer_rows(text):
    """Parse the `Producer` tab CSV into [{"part","producer","magicdns"}, ...].

    Header REQUIRED: returns [] unless all three columns are located in row 1 by
    case-insensitive header match. Order and duplicate rows are preserved (one
    producer may do consecutive parts). Cells are trimmed; a row whose Producer
    AND MagicDNS are both blank is dropped (spacer rows), but a present Producer
    with an empty MagicDNS is kept (the UI renders it with a disabled action)."""
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    header = [(c or "").strip().lower() for c in rows[0]]
    pi = _find(header, PRODUCER_PART_HEADERS)
    ri = _find(header, PRODUCER_PRODUCER_HEADERS)
    mi = _find(header, PRODUCER_MAGICDNS_HEADERS)
    if pi is None or ri is None or mi is None:
        return []
    out = []
    for row in rows[1:]:
        part, prod, magic = _cell(row, pi), _cell(row, ri), _cell(row, mi)
        if not prod and not magic:
            continue
        out.append({"part": part, "producer": prod, "magicdns": magic})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_producer.py`
Expected: PASS — prints `all producer tests passed`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/producer.py tests/test_producer.py
git commit -m "feat(producer): pure Producer-tab CSV parser (header-required)"
```

---

### Task 2: MagicDNS self-match helper

**Files:**
- Modify: `src/scripts/tailscale.py` (append a pure helper after `detect_magicdns_name`, ~line 181)
- Test: `tests/test_tailscale.py` (append test functions)

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `magicdns_is_self(value: str, self_name: str) -> bool` — exact FQDN
  match (case-insensitive, trailing dot ignored); False when `self_name` is
  empty.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tailscale.py` (before the `if __name__` runner, if any; this file's runner auto-discovers `t_*`):

```python
# --- magicdns_is_self: exact-FQDN takeover self-guard --------------------------
def t_magicdns_is_self_exact_fqdn():
    me = "producer-b.tail1234.ts.net"
    assert ts.magicdns_is_self("producer-b.tail1234.ts.net", me) is True
    assert ts.magicdns_is_self("PRODUCER-B.TAIL1234.TS.NET", me) is True   # case-insensitive
    assert ts.magicdns_is_self("producer-b.tail1234.ts.net.", me) is True  # trailing dot
    assert ts.magicdns_is_self("  producer-b.tail1234.ts.net  ", me) is True


def t_magicdns_is_self_short_name_does_not_match():
    me = "producer-b.tail1234.ts.net"
    assert ts.magicdns_is_self("producer-b", me) is False        # bare host: exact-FQDN policy
    assert ts.magicdns_is_self("producer-a.tail1234.ts.net", me) is False


def t_magicdns_is_self_unknown_self_is_false():
    assert ts.magicdns_is_self("producer-b.tail1234.ts.net", "") is False
    assert ts.magicdns_is_self("producer-b.tail1234.ts.net", None) is False
    assert ts.magicdns_is_self("", "producer-b.tail1234.ts.net") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_tailscale.py`
Expected: FAIL — `AttributeError: module 'tailscale' has no attribute 'magicdns_is_self'`.

- [ ] **Step 3: Add the helper**

In `src/scripts/tailscale.py`, immediately after the `detect_magicdns_name` function (after its `return ""`, ~line 181), add:

```python
def magicdns_is_self(value, self_name):
    """True when the Sheet `MagicDNS` cell `value` denotes THIS machine — an exact
    FQDN match against `self_name` (this node's `Self.DNSName`), case-insensitive
    and ignoring a trailing dot. False when `self_name` is empty (own identity
    unknown → the caller locks all takeover actions). Pure → unit-tested.

    Exact FQDN by design: the producer schedule carries full `*.ts.net` names, so
    a bare hostname must NOT match (a short-name collision could otherwise disable
    the wrong row)."""
    a = (value or "").strip().rstrip(".").lower()
    b = (self_name or "").strip().rstrip(".").lower()
    if not a or not b:
        return False
    return a == b
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_tailscale.py`
Expected: PASS (existing tests + the three new ones).

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/tailscale.py tests/test_tailscale.py
git commit -m "feat(tailscale): magicdns_is_self exact-FQDN takeover self-guard"
```

---

### Task 3: `producer_schedule_data()` provider + ctx wiring

**Files:**
- Modify: `src/racecast.py` (add `PRODUCER_TAB`, `_producer_fetch`, `producer_schedule_data`; wire into the `ctx` dict ~line 5183)
- Test: `tests/test_racecast.py` (append provider tests using the seams)

**Interfaces:**
- Consumes: `producer.parse_producer_rows`, `tailscale.magicdns_is_self`,
  `tailscale.detect_magicdns_name`, `http_util.get_bytes`,
  `_apply_active_profile_env` (existing).
- Produces:
  - `producer_schedule_data(fetch=None, self_name=None, refresh_env=None) -> dict`
    shaped `{"rows": [{"part","producer","magicdns","self"}...], "self_name": str,
    "self_known": bool}`.
  - `ctx["producer_schedule"] = producer_schedule_data` for the UI server.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_racecast.py`. This file loads the CLI module via importlib as **`m`** (see its top: `spec_from_file_location("racecast", …)` → `m = …`), and already does `import os`. Use `m.producer_schedule_data`:

```python
# --- producer_schedule_data: tolerant provider with seams ---------------------
_PRODUCER_CSV = ("Part,Producer,MagicDNS\r\n"
                 "1,Alice,producer-a.tail1234.ts.net\r\n"
                 "2,Bob,producer-b.tail1234.ts.net\r\n")


def t_producer_schedule_tags_self_and_shape():
    os.environ["RACECAST_SHEET_ID"] = "SHEET123"
    data = m.producer_schedule_data(
        fetch=lambda url: _PRODUCER_CSV,
        self_name="producer-b.tail1234.ts.net",
        refresh_env=lambda: None)
    assert data["self_name"] == "producer-b.tail1234.ts.net"
    assert data["self_known"] is True
    rows = data["rows"]
    assert [r["producer"] for r in rows] == ["Alice", "Bob"]
    assert rows[0]["self"] is False
    assert rows[1]["self"] is True           # Bob == me -> locked


def t_producer_schedule_unknown_self_known_false():
    os.environ["RACECAST_SHEET_ID"] = "SHEET123"
    data = m.producer_schedule_data(
        fetch=lambda url: _PRODUCER_CSV, self_name="", refresh_env=lambda: None)
    assert data["self_known"] is False
    assert all(r["self"] is False for r in data["rows"])


def t_producer_schedule_no_sheet_id_is_empty():
    os.environ.pop("RACECAST_SHEET_ID", None)
    data = m.producer_schedule_data(
        fetch=lambda url: _PRODUCER_CSV, self_name="x.ts.net", refresh_env=lambda: None)
    assert data == {"rows": [], "self_name": "x.ts.net", "self_known": True}


def t_producer_schedule_fetch_failure_is_empty():
    os.environ["RACECAST_SHEET_ID"] = "SHEET123"
    def boom(url):
        raise OSError("network down")
    data = m.producer_schedule_data(
        fetch=boom, self_name="x.ts.net", refresh_env=lambda: None)
    assert data["rows"] == [] and data["self_known"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL — `AttributeError: ... has no attribute 'producer_schedule_data'`.

- [ ] **Step 3: Add the provider**

In `src/racecast.py`, add near the other on-demand sheet providers (next to `assets_status_data`, ~line 3470). Note `producer`/`tailscale` are imported locally inside the function (the relay/scripts dir is already on `sys.path` in this process, matching how the file imports e.g. `obs_ws` locally):

```python
PRODUCER_TAB = "Producer"   # read-only league Sheet tab: Part | Producer | MagicDNS


def _producer_fetch(url):
    """Fetch the Producer-tab CSV as text. Covered side -> http_util (UA-stamped),
    never a bare urllib call (tests/test_http_util.py enforces this)."""
    return http_util.get_bytes(url, timeout=15).decode("utf-8", "replace")


def producer_schedule_data(fetch=None, self_name=None, refresh_env=None):
    """Read-only producer handover schedule from the active league Sheet's
    `Producer` tab (`Part | Producer | MagicDNS`), for the Control Center Home
    view. Network: a gviz CSV fetch (seconds) — served on demand via
    /api/producer-schedule, never from the status poll (like assets_status_data).

    Each row is tagged `self` (exact-FQDN match of its MagicDNS against this
    machine's own MagicDNS name) so the Home view disables takeover against this
    machine. `self_known` is False when our own MagicDNS can't be detected
    (Tailscale off/logged out) — the UI then locks ALL takeover actions.

    Tolerant: any fetch/parse failure returns empty rows (the card hides), never
    raises. `fetch`/`self_name`/`refresh_env` are test seams."""
    from urllib.parse import quote
    import producer as prod
    import tailscale as ts
    (refresh_env or _apply_active_profile_env)()
    own = ts.detect_magicdns_name() if self_name is None else self_name
    base = {"rows": [], "self_name": own, "self_known": bool(own)}
    sheet_id = os.environ.get("RACECAST_SHEET_ID") or ""
    if not sheet_id:
        return base
    url = ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s"
           % (sheet_id, quote(PRODUCER_TAB)))
    try:
        text = (fetch or _producer_fetch)(url)
        rows = prod.parse_producer_rows(text)
    except Exception:
        return base
    for r in rows:
        r["self"] = ts.magicdns_is_self(r.get("magicdns", ""), own)
    base["rows"] = rows
    return base
```

- [ ] **Step 4: Wire into the ctx dict**

In `src/racecast.py`, in the `ctx = { ... }` literal (~line 5205, next to `"assets": assets_status_data,`), add:

```python
        "producer_schedule": producer_schedule_data,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(ui): producer_schedule_data provider + ctx wiring"
```

---

### Task 4: `/api/producer-schedule` route

**Files:**
- Modify: `src/ui/ui_server.py` (add a GET route alongside `/api/assets`, ~line 278)
- Test: `tests/test_ui_server.py` (append a live-server route test + extend the ctx stub)

**Interfaces:**
- Consumes: `ctx["producer_schedule"]()` (Task 3).
- Produces: `GET /api/producer-schedule` → JSON body of the provider payload;
  failures return `{"ok": False, "error": ...}` with code 500 (matching
  `/api/assets`).

- [ ] **Step 1: Write the failing test**

In `tests/test_ui_server.py`, the live-server `ctx` is built by `_ctx()` (~line 76). Add a stub entry next to the existing `"assets": lambda: {...}` (~line 80):

```python
            "producer_schedule": lambda: {
                "rows": [{"part": "1", "producer": "Alice",
                          "magicdns": "producer-a.ts.net", "self": False},
                         {"part": "2", "producer": "Bob",
                          "magicdns": "producer-b.ts.net", "self": True}],
                "self_name": "producer-b.ts.net", "self_known": True},
```

Then add a route test mirroring `t_status_route_wraps_provider` exactly (uses `_serve(_ctx())` → `(httpd, port)`, the `_get(port, path)` helper returning `(code, body)`, and `httpd.shutdown()` teardown):

```python
def t_producer_schedule_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/producer-schedule")
        data = json.loads(body)
        assert code == 200
        assert data["self_known"] is True
        assert data["self_name"] == "producer-b.ts.net"
        assert [r["producer"] for r in data["rows"]] == ["Alice", "Bob"]
        assert data["rows"][1]["self"] is True
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the route returns 404 / "not found" (no such path yet).

- [ ] **Step 3: Add the route**

In `src/ui/ui_server.py`, immediately after the `/api/assets` block (the one returning `ctx["assets"]()`, ~line 284), add:

```python
            if path == "/api/producer-schedule":
                try:
                    return self._json(ctx["producer_schedule"]())
                except Exception as exc:    # sheet/probe failure must stay JSON
                    return self._json({"ok": False,
                                       "error": f"producer schedule failed: {exc}"},
                                      code=500)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_ui_server.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): /api/producer-schedule route"
```

---

### Task 5: Home view card + one-click takeover

**Files:**
- Modify: `src/ui/control-center.html` (add the `#home-producers` section, CSS, `fetchProducerSchedule()` + render, and the `showView('home')` hook)

**Interfaces:**
- Consumes: `GET /api/producer-schedule` (Task 4); existing JS helpers `$()`,
  `op('event-takeover', true, {...})`, `escapeHtml`/`textContent` patterns.
- Produces: the rendered Home-view table; per-row takeover calls
  `op('event-takeover', true, {ip: <magicdns>, funnel: true})`.

- [ ] **Step 1: Add the HTML section**

In `src/ui/control-center.html`, in the Home view, insert a new section **after** the `<section class="tiles">…</section>` block (~line 597, before the `<p class="evnote">`):

```html
        <section id="home-producers" hidden>
          <div class="row"><span class="name">Producer schedule</span>
            <span class="dim grow" id="prod-self">—</span>
            <button id="prod-refresh" title="Reload the Producer tab from the league Sheet">Refresh</button></div>
          <div id="prod-hint" class="dim" hidden></div>
          <table id="prod-table" class="prodtable">
            <thead><tr><th>Part</th><th>Producer</th><th>MagicDNS</th><th></th></tr></thead>
            <tbody id="prod-body"></tbody>
          </table>
        </section>
```

- [ ] **Step 2: Add minimal CSS**

Near the other Home/table styles (e.g. after the `section.tiles`/`.tile` rules ~line 368), add:

```css
        table.prodtable { width:100%; border-collapse:collapse; font:13px var(--mono); }
        table.prodtable th, table.prodtable td { text-align:left; padding:6px 8px;
          border-bottom:1px solid var(--line); }
        table.prodtable th { color:var(--dim); font-weight:600; }
        table.prodtable td.mono { color:var(--dim); word-break:break-all; }
        .prodyou { color:var(--dim); font:11px var(--mono); }
```

- [ ] **Step 3: Add the fetch + render JS**

Add these functions in the `<script>` block near `loadTakeoverPeers()` (~line 1745+). The render uses DOM `textContent` for all Sheet-supplied strings (XSS-safe — same rule as crew chat); the takeover host is passed as a JS value to `op()`, never interpolated into HTML:

```javascript
// Producer schedule (read-only league Sheet tab) on the Home view. On-demand
// (network: a Sheet fetch), loaded when Home opens and on manual Refresh — never
// from the 3s status poll. Each row offers a one-click Funnel takeover against
// that machine's MagicDNS; your OWN row(s) are disabled (server-tagged `self`),
// and ALL rows lock when our own MagicDNS is unknown (Tailscale offline).
async function fetchProducerSchedule() {
  let d;
  try { d = await (await fetch('/api/producer-schedule', {cache: 'no-store'})).json(); }
  catch (e) { return; }
  renderProducerSchedule(d);
}

function renderProducerSchedule(d) {
  const sec = $('home-producers');
  const rows = (d && d.rows) || [];
  if (!rows.length) { sec.hidden = true; return; }   // no tab / empty -> hide card
  sec.hidden = false;
  const known = !!(d && d.self_known);
  $('prod-self').textContent = known
    ? ('Your MagicDNS: ' + d.self_name) : '— (Tailscale offline)';
  const hint = $('prod-hint');
  if (!known) { hint.hidden = false;
    hint.textContent = 'Connect Tailscale to take over from the schedule.'; }
  else { hint.hidden = true; hint.textContent = ''; }
  const body = $('prod-body');
  body.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    const tdPart = document.createElement('td'); tdPart.textContent = r.part || '';
    const tdProd = document.createElement('td'); tdProd.textContent = r.producer || '';
    const tdDns = document.createElement('td'); tdDns.className = 'mono';
    tdDns.textContent = r.magicdns || '';
    const tdAct = document.createElement('td');
    if (r.self) {
      const span = document.createElement('span');
      span.className = 'prodyou'; span.textContent = 'you'; tdAct.appendChild(span);
    } else {
      const btn = document.createElement('button');
      btn.textContent = 'Take over';
      // Disabled when our identity is unknown (can't self-guard) or no host.
      btn.disabled = !known || !r.magicdns;
      const host = r.magicdns;
      btn.onclick = () => op('event-takeover', true, {ip: host, funnel: true});
      tdAct.appendChild(btn);
    }
    tr.append(tdPart, tdProd, tdDns, tdAct);
    body.appendChild(tr);
  }
}
```

- [ ] **Step 4: Wire the Home-open hook + Refresh button**

In `showView()`, next to the existing `if (name === 'home') loadTakeoverPeers();` (~line 1090), add:

```javascript
  if (name === 'home') fetchProducerSchedule();
```

And wire the Refresh button once, where other one-time listeners are bound (or inline via `onclick`). Simplest: change the button in Step 1 to `<button id="prod-refresh" onclick="fetchProducerSchedule()" ...>`. Apply that inline `onclick` now and drop any separate listener.

- [ ] **Step 5: Manually verify against a dev build**

```bash
# From a local dev build (no VERSION stamped). Use a free UI port — your real
# instance owns 8089 (see memory: uat-uses-free-ui-port).
RACECAST_UI_PORT=8090 python3 src/racecast.py ui
```

Open `http://127.0.0.1:8090/`, confirm on Home:
- With a profile whose Sheet has a `Producer` tab: the card lists the rows; your own row shows **you** (no button); other rows show an enabled **Take over**; the header shows **Your MagicDNS: …**.
- With Tailscale stopped: all buttons disabled + the hint appears.
- With a profile/Sheet lacking the tab: the card is hidden.

(Do NOT trigger a real takeover during this check — it would start an event.)

- [ ] **Step 6: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): Producer schedule card + one-click Funnel takeover on Home"
```

---

### Task 6: Wiki screenshot + Sheet docs

**Files:**
- Replace: `src/docs/wiki/images/cc-home.png` (regenerated from a dev build)
- Modify: the Sheet-setup wiki page documenting the league tabs (locate with the
  grep below — likely `src/docs/wiki/Sheet-Webhook.md` or a Sheet-setup page)

**Interfaces:** none (docs only).

- [ ] **Step 1: Recapture `cc-home.png` from a dev build**

Run the Control Center from `src/` on a free port (no `VERSION` file, so the badge reads "dev build" — keeps all `cc-*.png` uniform), with a profile whose Sheet has a populated `Producer` tab so the new card is visible. Drive a running instance with the Playwright MCP and take an **element** screenshot of the Home view that frames it like the existing `cc-home.png` (match the current crop, not a full-window grab). Overwrite `src/docs/wiki/images/cc-home.png`.

Verify it changed:

```bash
git status --short src/docs/wiki/images/cc-home.png   # expect: M
```

- [ ] **Step 2: Document the `Producer` tab**

Find the Sheet-tab documentation page:

```bash
grep -rln 'Crew tab\|Configuration tab\|gviz\|Sheet tab\|Qualifying tab' src/docs/wiki/*.md
```

In the page that enumerates the league Sheet's tabs (same one that documents the Crew/Configuration tabs), add a short subsection describing the **`Producer`** tab:
- Header row 1: `Part | Producer | MagicDNS`.
- Read-only / admin-owned, maintained per event by the league owner.
- `MagicDNS` must be each producer's **full `*.ts.net` name** (the Control Center shows your own as "Your MagicDNS: …"); a bare hostname will not match the self-guard.
- Duplicates are allowed (a producer doing consecutive parts → repeat the row).
- Surfaced on the Control Center **Home** view; each row offers a one-click Funnel takeover (disabled for your own machine).

Keep prose English, Control-Center-first and Funnel-first per the repo's doc ordering.

- [ ] **Step 3: Validate wiki links + commit**

```bash
python3 tests/test_wiki.py
git add src/docs/wiki/images/cc-home.png src/docs/wiki/*.md
git commit -m "docs(wiki): document Producer tab + refresh Home screenshot"
```

---

### Task 7: Full suite + build verify

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite (what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: all tests pass, including `test_producer.py`, `test_tailscale.py`, `test_racecast.py`, `test_ui_server.py`, `test_http_util.py` (the UA guard must still pass — the provider uses `http_util`).

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: clean.

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: build + verify step succeed (no secrets, no shell scripts, tokenization intact).

- [ ] **Step 4: Final commit (if anything changed) and open PR**

If build produced no source changes, nothing to commit. Then push the branch and open one PR per the repo's PR workflow (up-to-date branch required; full CI for this code PR).

---

## Self-Review notes

- **Spec coverage:** `Producer` tab parse → Task 1; exact-FQDN self-match → Task 2; direct Sheet read without a running relay + self tagging + tolerant failure → Task 3; on-demand `/api/producer-schedule` (no status-poll) → Task 4; Home card, per-row Funnel takeover, self/empty/Tailscale-off disabling, duplicates render-per-row, "Your MagicDNS" header → Task 5; `cc-home.png` refresh + Sheet docs → Task 6; full-suite/lint/build → Task 7. Header-required (no positional fallback) is enforced by `t_missing_header_returns_empty`/`t_partial_header_returns_empty` in Task 1. "Always Funnel" is enforced by Task 5 passing `funnel: true`.
- **Deviation from spec (intentional):** the spec mentioned a "~30s server-side cache" for the route; this plan omits it to match the established `/api/assets` on-demand pattern (no cache) — the frontend only fetches on Home open + manual Refresh, so a cache adds invalidation complexity for no real benefit. Flag at review if a cache is still wanted.
- **Type consistency:** provider returns `{"rows":[{"part","producer","magicdns","self"}], "self_name", "self_known"}` in Task 3; consumed verbatim by the route stub in Task 4 and the renderer in Task 5. `magicdns_is_self(value, self_name)` and `parse_producer_rows(text)` signatures match across tasks.
```
