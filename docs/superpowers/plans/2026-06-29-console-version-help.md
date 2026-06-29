# Console pages: version badge + Help button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clickable racecast-version badge (→ GitHub Releases) and a role-specific Help button (→ onboarding deck) to the headers of the Director Panel, Commentator Cockpit, and Race Control pages.

**Architecture:** A new pure helper `app_version.read_version()` is the single source of truth for the running build's version, used by both `racecast.py` and the relay. The relay injects the version into every served page via a new `__RC_VERSION__` placeholder in the existing `_send_page()` substitution step (no new HTTP endpoint). Each of the three role HTML files gets a right-aligned header control group with the version badge and a hardcoded role-specific Help link.

**Tech Stack:** Pure Python 3 stdlib (no framework, no package manager); plain HTML/CSS/vanilla JS in the served pages; stdlib-only runnable test scripts (no pytest).

## Global Constraints

- Edit only under `src/` (and `tests/`, `docs/`). `dist/`/`runtime/` are generated — never hand-edit.
- All scripts and docs are **English only**.
- Never hardcode secrets or machine paths. (The version string and the public GitHub URLs are not secrets.)
- Python-only tooling — no `.sh`/`.bat`.
- Tests must run on any machine and in CI — no real IPs, no machine paths, stdlib only; prefer TDD (failing test first).
- racecast is a **released** product (v1.1.0 shipped) — backward compatibility matters. The new `make_handler` parameter and `version()` refactor must be behavior-preserving (new param defaults so existing callers/tests keep working).
- Run `python3 tools/lint.py` after changing any Python file.
- **Static URLs used in this plan (verbatim):**
  - Releases: `https://github.com/jegr78/gt-endurance-racing-broadcast/releases`
  - Director deck: `https://jegr78.github.io/gt-endurance-racing-broadcast/director.html`
  - Commentator deck: `https://jegr78.github.io/gt-endurance-racing-broadcast/commentator.html`
  - Race Control deck: `https://jegr78.github.io/gt-endurance-racing-broadcast/race-control.html`
- **Repo rule:** changing the Director Panel / Commentator Cockpit / Race Control UI means the matching wiki screenshots are stale and MUST be refreshed in this same change (Task 6).

## File structure

- **Create** `src/scripts/app_version.py` — pure `read_version(src_base)` helper.
- **Create** `tests/test_app_version.py` — unit tests for the helper.
- **Modify** `src/racecast.py` — `version()` delegates to the helper (behavior-preserving).
- **Modify** `src/relay/racecast-feeds.py` — import helper, compute the version label once, thread it into `make_handler`, substitute `__RC_VERSION__` in `_send_page`.
- **Modify** `tests/test_cockpit.py` — fixture gains an `app_version` param; new test asserts the served page substitutes the version.
- **Modify** `src/director/director-panel.html` — header control group + CSS.
- **Modify** `src/cockpit/cockpit.html` — header control group + CSS.
- **Modify** `src/racecontrol/race-control.html` — header control group + CSS.
- **Refresh** `src/docs/wiki/images/{director-panel,console-cockpit,console-race-control}.png` (+ slide mirrors) via the `wiki-screenshots` skill.

---

### Task 1: Shared version helper + delegate `racecast.py version()`

**Files:**
- Create: `src/scripts/app_version.py`
- Create: `tests/test_app_version.py`
- Modify: `src/racecast.py` (the `version()` function, ~lines 3183-3190)

**Interfaces:**
- Produces: `app_version.read_version(src_base: str) -> str` — returns the trimmed contents of `<src_base>/VERSION`, or `"dev"` when the file is absent or empty/whitespace.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_version.py`:

```python
"""Unit tests for the shared build-version helper (src/scripts/app_version.py).
Stdlib only; runnable as a script (repo convention). Mirrors racecast.version()."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
import app_version as av  # noqa: E402


def t_reads_trimmed_version():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("1.2.3\n")
        assert av.read_version(d) == "1.2.3"


def t_whitespace_only_is_dev():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("   \n")
        assert av.read_version(d) == "dev"


def t_missing_file_is_dev():
    with tempfile.TemporaryDirectory() as d:
        assert av.read_version(d) == "dev"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("all app_version tests passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_app_version.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app_version'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/app_version.py`:

```python
"""Single source of truth for the running build's version string.

The VERSION file is stamped into the source-tree root by tools/build-binary.py
(`--add-data <workdir>/VERSION:src`, so it lands at `<_MEIPASS>/src/VERSION` in a
frozen binary); a repo checkout has none -> 'dev'. Both racecast.py (CLI) and the
relay resolve their version through this helper so the two never drift.
"""
import os


def read_version(src_base):
    """Return the trimmed VERSION file under `src_base`, or 'dev' when absent/empty.

    `src_base` is the source-tree root: the dir holding racecast.py in a repo run,
    and `<_MEIPASS>/src` in a frozen binary.
    """
    try:
        with open(os.path.join(src_base, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_app_version.py`
Expected: PASS — prints `ok t_*` lines and `all app_version tests passed`.

- [ ] **Step 5: Delegate `racecast.py version()` to the helper**

`src/racecast.py` already imports its sibling `src/scripts` modules (e.g. `import fonts_bundle as fb`, `import ports as pt` near line 55). Add an import alongside them:

```python
import app_version as _app_version
```

Then replace the existing `version()` function (currently ~lines 3183-3190):

```python
def version():
    """Build version: a VERSION file is stamped into the bundle by
    tools/build-binary.py; a repo checkout has none -> 'dev'."""
    try:
        with open(resource_path("VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"
```

with the delegating version (`resource_path("")` is the source-tree root — `_src_base(...)`):

```python
def version():
    """Build version via the shared app_version helper (single source of truth).
    A VERSION file is stamped into the bundle by tools/build-binary.py; a repo
    checkout has none -> 'dev'."""
    return _app_version.read_version(resource_path(""))
```

- [ ] **Step 6: Verify the existing racecast version test still passes**

`tests/test_racecast.py::t_version_route_and_dev_default` asserts `m.version() == "dev"` in a repo checkout.

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_racecast as t; t.t_version_route_and_dev_default()" && echo OK`
Expected: prints `OK` (no assertion error).

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: clean (exit 0).

- [ ] **Step 8: Commit**

```bash
git add src/scripts/app_version.py tests/test_app_version.py src/racecast.py
git commit -m "feat(version): shared app_version.read_version helper; racecast version() delegates"
```

---

### Task 2: Relay wiring — compute version + `__RC_VERSION__` substitution

**Files:**
- Modify: `src/relay/racecast-feeds.py` (imports ~line 88-102; module globals near `_REL_HERE` ~line 77; `make_handler` signature ~line 4896; `_send_page` ~line 4961; `make_handler(...)` call site ~line 6770-6796)
- Modify: `tests/test_cockpit.py` (`_cockpit_client` fixture ~lines 300-370; add a new test)

**Interfaces:**
- Consumes: `app_version.read_version` (Task 1).
- Produces: `make_handler(..., app_version="dev")` — new keyword param (default `"dev"`); `_send_page` substitutes the page-bytes token `__RC_VERSION__` with this value. The display label (`"v1.2.3"` for a real build, `"dev"` for a dev build) is computed at the call site and passed in.

- [ ] **Step 1: Write the failing test**

In `tests/test_cockpit.py`, the `_cockpit_client` fixture builds `make_handler(...)`. Add an `app_version` parameter to the fixture and forward it.

Find the fixture signature (around line 300-304), which starts:

```python
                    page_path=None, graphics_dir=None,
                    console_page_path=None, discord_client_id=None,
```

Add `app_version="v9.9.9-test"` to the fixture's parameter list (e.g. on the `page_path=None, graphics_dir=None,` line, append it):

```python
                    page_path=None, graphics_dir=None, app_version="v9.9.9-test",
                    console_page_path=None, discord_client_id=None,
```

Then in the `m.make_handler(...)` call inside the fixture (around line 337-345), add the forward (e.g. right after `cockpit_page_path=page_path,`):

```python
                             cockpit_page_path=page_path, console_secret=secret,
                             app_version=app_version,
```

Now add a new test function (place it next to `t_page_sets_cookie_and_serves_html`):

```python
def t_page_substitutes_version():
    with tempfile.TemporaryDirectory() as d:
        page = os.path.join(d, "cockpit.html")
        with open(page, "w") as fh:
            fh.write("<!doctype html><title>cockpit</title><span>__RC_VERSION__</span>")
        srv, get, _post = _cockpit_client(page_path=page, app_version="v9.9.9-test")
        try:
            tok = ca.mint_token("sek", "alpha-racing")
            code, _headers, body = get("/cockpit?t=" + tok)
            assert code == 200, code
            assert b"v9.9.9-test" in body, body
            assert b"__RC_VERSION__" not in body, body   # placeholder fully replaced
        finally:
            srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_cockpit as t; t.t_page_substitutes_version()"`
Expected: FAIL — either `TypeError: make_handler() got an unexpected keyword argument 'app_version'` or an `AssertionError` because `__RC_VERSION__` is still present in the body.

- [ ] **Step 3: Add the `app_version` import to the relay**

In `src/relay/racecast-feeds.py`, alongside the other `src/scripts` imports (the block around lines 88-102, e.g. after `import console_admin`):

```python
import app_version   # shared build-version helper (single source of truth)
```

- [ ] **Step 4: Compute the version label once (module-level)**

The relay already defines `_REL_HERE = os.path.dirname(os.path.abspath(__file__))` (~line 77) and prepends `src/scripts` to `sys.path` just below it. After that block (after the `import app_version` line is resolvable), add the module-level version resolution:

```python
# Running build version, resolved like racecast.py: the VERSION file is stamped
# into the source-tree root by tools/build-binary.py (frozen: <_MEIPASS>/src),
# absent in a repo checkout -> 'dev'. Injected into served pages as __RC_VERSION__.
_SRC_BASE = (os.path.join(sys._MEIPASS, "src") if getattr(sys, "frozen", False)
             else os.path.join(_REL_HERE, ".."))
APP_VERSION = app_version.read_version(_SRC_BASE)
VERSION_LABEL = ("v" + APP_VERSION) if APP_VERSION != "dev" else "dev"
```

- [ ] **Step 5: Add the `app_version` param to `make_handler`**

In the `make_handler(...)` signature, the last line is `flag_graphic_store=None):` (~line 4896). Change it to add the new param:

```python
                 flag_graphic_store=None, app_version="dev"):
```

- [ ] **Step 6: Substitute `__RC_VERSION__` in `_send_page`**

In `_send_page` (inside `make_handler`), the existing substitutions are:

```python
            body = body.replace(b"__RC_API_BASE__", (api_base or "").encode())
            oauth_flag = b"1" if (discord_client_id and discord_client_secret) else b""
            body = body.replace(b"__RC_OAUTH__", oauth_flag)
```

Add a third substitution immediately after the `__RC_OAUTH__` line (`app_version` is the closure variable from the `make_handler` param):

```python
            body = body.replace(b"__RC_VERSION__", (app_version or "dev").encode())
```

- [ ] **Step 7: Pass the label at the `make_handler(...)` call site**

In the real `make_handler(...)` call in `main()` (the multi-line call ending around line 6796 with `flag_graphic_store=flag_graphic_store)`), add the new keyword argument (e.g. right before `flag_graphic_store=flag_graphic_store)`):

```python
                           app_version=VERSION_LABEL,
                           flag_graphic_store=flag_graphic_store)
```

- [ ] **Step 8: Run the new test + the existing page tests to verify they pass**

Run: `python3 tests/test_cockpit.py`
Expected: PASS — all cockpit tests pass, including `t_page_substitutes_version` and the unchanged `t_page_sets_cookie_and_serves_html`.

- [ ] **Step 9: Lint**

Run: `python3 tools/lint.py`
Expected: clean (exit 0).

- [ ] **Step 10: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_cockpit.py
git commit -m "feat(relay): inject running version into served pages via __RC_VERSION__"
```

---

### Task 3: Director Panel header — version badge + Help button

**Files:**
- Modify: `src/director/director-panel.html` (CSS block ~lines 64-79; header markup ~lines 396-398)

**Interfaces:**
- Consumes: the `__RC_VERSION__` placeholder substituted by the relay (Task 2).

- [ ] **Step 1: Add the CSS**

In `src/director/director-panel.html`, the header CSS ends with the `a.back:hover` rule:

```css
  a.back:hover{border-color:var(--live)}
```

Add the `.appmeta` rules immediately after that line:

```css
  .appmeta{display:flex;align-items:center;gap:8px;margin-left:auto}
  .appmeta a{display:inline-flex;align-items:center;gap:5px;text-decoration:none;color:#e7edf3;
    background:#0c0f13;border:1px solid var(--edge);border-radius:8px;padding:7px 11px;
    font:inherit;font-size:12px;font-weight:600;letter-spacing:.04em}
  .appmeta a:hover{border-color:var(--live)}
  .appmeta .ver{color:var(--amber);font-variant-numeric:tabular-nums}
```

- [ ] **Step 2: Add the header control group**

The header ends with two `.led` divs then `</header>` (~lines 396-398):

```html
    <div class="led"><span class="dot" id="ledObs"></span>OBS</div>
    <div class="led"><span class="dot" id="ledRelay"></span>Relay</div>
  </header>
```

Insert the control group between the second `.led` div and `</header>`:

```html
    <div class="led"><span class="dot" id="ledObs"></span>OBS</div>
    <div class="led"><span class="dot" id="ledRelay"></span>Relay</div>
    <div class="appmeta">
      <a class="ver" href="https://github.com/jegr78/gt-endurance-racing-broadcast/releases"
         target="_blank" rel="noopener" title="Running racecast version — view releases">__RC_VERSION__ ↗</a>
      <a class="help" href="https://jegr78.github.io/gt-endurance-racing-broadcast/director.html"
         target="_blank" rel="noopener">? Help</a>
    </div>
  </header>
```

- [ ] **Step 3: Verify the page is well-formed and the placeholder/links are present**

Run:
```bash
python3 -c "import re;s=open('src/director/director-panel.html').read();assert '__RC_VERSION__ ↗' in s;assert s.count('class=\"appmeta\"')==1;assert '/director.html' in s and '/releases' in s;print('director ok')"
```
Expected: prints `director ok`.

- [ ] **Step 4: Commit**

```bash
git add src/director/director-panel.html
git commit -m "feat(panel): version badge + Help link in the Director Panel header"
```

---

### Task 4: Commentator Cockpit header — version badge + Help button

**Files:**
- Modify: `src/cockpit/cockpit.html` (header CSS ~line 30-38; header markup ~lines 195-204)

**Interfaces:**
- Consumes: the `__RC_VERSION__` placeholder substituted by the relay (Task 2).

- [ ] **Step 1: Add the CSS**

In `src/cockpit/cockpit.html`, find the `#eventTitle::before` rule (~line 38):

```css
  #eventTitle:not(:empty)::before { content: "· "; opacity: .5; font-weight: 400; }
```

Add the `.appmeta` rules immediately after it:

```css
  .appmeta { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .appmeta a { display: inline-flex; align-items: center; gap: 5px; text-decoration: none;
    color: #e7edf3; background: #0c0f13; border: 1px solid #2a2f37; border-radius: 8px;
    padding: 6px 10px; font-size: 12px; font-weight: 600; }
  .appmeta a:hover { border-color: #3da9fc; }
  .appmeta .ver { color: #ffb454; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 2: Add the header control group**

The header is (~lines 201-204):

```html
  <h1>Commentator Cockpit</h1>
  <span id="eventTitle"></span>
  <span id="who"></span>
</header>
```

Insert the control group between `<span id="who"></span>` and `</header>`:

```html
  <h1>Commentator Cockpit</h1>
  <span id="eventTitle"></span>
  <span id="who"></span>
  <div class="appmeta">
    <a class="ver" href="https://github.com/jegr78/gt-endurance-racing-broadcast/releases"
       target="_blank" rel="noopener" title="Running racecast version — view releases">__RC_VERSION__ ↗</a>
    <a class="help" href="https://jegr78.github.io/gt-endurance-racing-broadcast/commentator.html"
       target="_blank" rel="noopener">? Help</a>
  </div>
</header>
```

- [ ] **Step 3: Verify**

Run:
```bash
python3 -c "s=open('src/cockpit/cockpit.html').read();assert '__RC_VERSION__ ↗' in s;assert s.count('class=\"appmeta\"')==1;assert '/commentator.html' in s and '/releases' in s;print('cockpit ok')"
```
Expected: prints `cockpit ok`.

- [ ] **Step 4: Commit**

```bash
git add src/cockpit/cockpit.html
git commit -m "feat(cockpit): version badge + Help link in the Commentator Cockpit header"
```

---

### Task 5: Race Control header — version badge + Help button

**Files:**
- Modify: `src/racecontrol/race-control.html` (header CSS ~line 31-39; header markup ~lines 111-114)

**Interfaces:**
- Consumes: the `__RC_VERSION__` placeholder substituted by the relay (Task 2).

- [ ] **Step 1: Add the CSS**

In `src/racecontrol/race-control.html`, find the `#eventTitle::before` rule (~line 39):

```css
  #eventTitle:not(:empty)::before { content: "· "; opacity: .5; font-weight: 400; }
```

Add the `.appmeta` rules immediately after it:

```css
  .appmeta { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .appmeta a { display: inline-flex; align-items: center; gap: 5px; text-decoration: none;
    color: #e7edf3; background: #0c0f13; border: 1px solid #2a2f37; border-radius: 8px;
    padding: 6px 10px; font-size: 12px; font-weight: 600; }
  .appmeta a:hover { border-color: #3da9fc; }
  .appmeta .ver { color: #ffb454; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 2: Add the header control group**

The header is (~lines 111-114):

```html
  <h1>Race Control</h1>
  <span id="eventTitle"></span>
  <span id="who"></span>
</header>
```

Insert the control group between `<span id="who"></span>` and `</header>`:

```html
  <h1>Race Control</h1>
  <span id="eventTitle"></span>
  <span id="who"></span>
  <div class="appmeta">
    <a class="ver" href="https://github.com/jegr78/gt-endurance-racing-broadcast/releases"
       target="_blank" rel="noopener" title="Running racecast version — view releases">__RC_VERSION__ ↗</a>
    <a class="help" href="https://jegr78.github.io/gt-endurance-racing-broadcast/race-control.html"
       target="_blank" rel="noopener">? Help</a>
  </div>
</header>
```

- [ ] **Step 3: Verify**

Run:
```bash
python3 -c "s=open('src/racecontrol/race-control.html').read();assert '__RC_VERSION__ ↗' in s;assert s.count('class=\"appmeta\"')==1;assert '/race-control.html' in s and '/releases' in s;print('race-control ok')"
```
Expected: prints `race-control ok`.

- [ ] **Step 4: Commit**

```bash
git add src/racecontrol/race-control.html
git commit -m "feat(race-control): version badge + Help link in the Race Control header"
```

---

### Task 6: Full suite, build verify, and refresh wiki screenshots

**Files:**
- Refresh: `src/docs/wiki/images/director-panel.png`, `src/docs/wiki/images/console-cockpit.png`, `src/docs/wiki/images/console-race-control.png` (+ any slide mirrors the skill updates).

- [ ] **Step 1: Run the whole test suite**

Run: `python3 tools/run-tests.py`
Expected: all tests pass (this is exactly what CI runs).

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: clean (exit 0).

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: build succeeds and its verify step passes (tokenization, blanked password, no secrets, no shell scripts). This confirms the new HTML/Python ship cleanly.

- [ ] **Step 4: Refresh the wiki screenshots**

Use the `wiki-screenshots` skill to recapture the three changed pages so the version badge + Help button appear:
- Director Panel → `src/docs/wiki/images/director-panel.png`
- Commentator Cockpit → `src/docs/wiki/images/console-cockpit.png`
- Race Control → `src/docs/wiki/images/console-race-control.png`

Follow the skill's reproducible recipe (demo profile + `tools/obs-sim.py` OBS stand-in, element screenshots framed to match the existing images). Per the repo rule, capture from a **local dev build** (no stamped `VERSION`) so the badge reads `dev` and stays reproducible.

- [ ] **Step 5: Commit the screenshots**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/wiki/images/console-cockpit.png src/docs/wiki/images/console-race-control.png
git commit -m "docs(wiki): refresh console screenshots for version badge + Help button"
```

---

## Self-Review

**Spec coverage:**
- Version source / shared helper → Task 1. ✓
- Relay exposure via `__RC_VERSION__` injection (no endpoint) → Task 2. ✓
- Director Panel / Cockpit / Race Control front-end (badge → releases, Help → deck) → Tasks 3/4/5. ✓
- Tests (`test_app_version.py`, preserved `version()` behavior, relay substitution test) → Tasks 1 & 2. ✓
- Out-of-scope launcher untouched (no `console.html` task). ✓
- Wiki screenshot refresh (repo rule) → Task 6. ✓

**Type/name consistency:** `read_version(src_base)`, the `make_handler(..., app_version="dev")` keyword, the `__RC_VERSION__` placeholder, the `.appmeta`/`.ver`/`.help` class names, and the four static URLs are used identically across all tasks. ✓

**Placeholder scan:** every code/markup step contains the actual content and exact anchors; no TBD/TODO. ✓
