# M5d — Per-Profile Overlay Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each profile override the relay-served HUD and race-timer pages (layout, positioning, fonts) via cascade-wins override CSS, with a Control Center editor and an OBS collection-name prefix convention — all on PR #43 (M5d, before M6).

**Architecture:** Base `src/obs/hud.html` / `timer.html` stay shared and unchanged except for one `<link href="/hud/override.css">` hook (last in `<head>`). The relay serves `profiles/<name>/overlay/{hud,timer}.css` (per request, empty when absent) and `profiles/<name>/overlay/fonts/<file>` (path-sanitized). The CLI passes `--overlay-dir` when the dir exists; the OBS auto-refresh hash-gate adds the two override.css paths so CSS edits trigger a refresh. The Control Center gains an overlay-CSS editor mirroring the existing `profile.env` editor.

**Tech Stack:** Python 3.11+ stdlib only; tests are runnable scripts (`t_`-prefixed, bare `assert`, `importlib` module loading, `ok <name>`/`ALL PASS` runner). No pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-per-profile-overlay-overrides-design.md` (read it for full rationale + non-goals).

**Conventions to follow (read before starting):**
- The relay file is `src/relay/racecast-feeds.py` — a hyphenated filename, so tests load it via `importlib.util.spec_from_file_location`. Mirror the loader boilerplate at the top of `tests/test_hud.py`.
- Security pattern for any request-derived path: copy `resolve_asset` (`src/relay/racecast-feeds.py:213`) — strict regex + extension allow-list + `os.path.realpath` containment (`path.startswith(base + os.sep)`) + content-type from a constant map (never request-derived).
- Run `python3 tools/lint.py` after editing any Python file (ruff rules mirror CodeQL alert classes).
- "IRO"/"IRO_Endurance"/`IRO operator CLI` prose stragglers are M6's job — do NOT touch docs/wiki/README/CLAUDE.md here. This plan is code only (+ the example profile templates).

---

## Task 1: Relay override-CSS + font endpoints + base-HTML hook

**Files:**
- Modify: `src/relay/racecast-feeds.py` (constants near `:204-210`; new helpers near `resolve_asset` `:213`; `make_handler` signature `:1402` + `do_GET` `:1446-1455`; argparse `:1645`; `make_handler` call `:1806`)
- Modify: `src/obs/hud.html` (head, after the `</style>` at `:54`)
- Modify: `src/obs/timer.html` (head, after the `</style>` at `:17`)
- Test: `tests/test_overlay.py` (new)

- [ ] **Step 1: Write the failing test** (`tests/test_overlay.py`)

Mirror the module loader from `tests/test_hud.py` (load `src/relay/racecast-feeds.py` as module `feeds`). Then:

```python
import os, tempfile

def _mkoverlay(tmp, hud_css=None, timer_css=None, fonts=None):
    od = os.path.join(tmp, "overlay")
    os.makedirs(os.path.join(od, "fonts"), exist_ok=True)
    if hud_css is not None:
        with open(os.path.join(od, "hud.css"), "w", encoding="utf-8") as f: f.write(hud_css)
    if timer_css is not None:
        with open(os.path.join(od, "timer.css"), "w", encoding="utf-8") as f: f.write(timer_css)
    for name, data in (fonts or {}).items():
        with open(os.path.join(od, "fonts", name), "wb") as f: f.write(data)
    return od

def t_read_overlay_css_present():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, hud_css="#stint{left:10px}")
        assert feeds.read_overlay_css(od, "hud") == b"#stint{left:10px}"

def t_read_overlay_css_absent_is_empty():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp)  # no hud.css
        assert feeds.read_overlay_css(od, "hud") == b""

def t_read_overlay_css_no_dir_is_empty():
    assert feeds.read_overlay_css(None, "hud") == b""
    assert feeds.read_overlay_css("", "timer") == b""

def t_read_overlay_css_rejects_unknown_page():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, hud_css="x")
        assert feeds.read_overlay_css(od, "../hud") == b""
        assert feeds.read_overlay_css(od, "panel") == b""

def t_resolve_overlay_font_ok():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, fonts={"Title.woff2": b"OTTO"})
        hit = feeds.resolve_overlay_font(od, "Title.woff2")
        assert hit and hit[1] == "font/woff2"
        assert os.path.basename(hit[0]) == "Title.woff2"

def t_resolve_overlay_font_rejects_traversal_and_bad_ext():
    with tempfile.TemporaryDirectory() as tmp:
        od = _mkoverlay(tmp, fonts={"ok.ttf": b"x"})
        assert feeds.resolve_overlay_font(od, "../../etc/passwd") is None
        assert feeds.resolve_overlay_font(od, "ok.exe") is None
        assert feeds.resolve_overlay_font(od, "nope.woff2") is None
        assert feeds.resolve_overlay_font(None, "ok.ttf") is None

if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'read_overlay_css'`.

- [ ] **Step 3: Add the constants + pure helpers** (after `resolve_asset`, ~`:230`)

```python
# Per-profile overlay overrides (profiles/<name>/overlay/). Override CSS is read
# fresh per request (so a Control Center edit applies on the next OBS refresh
# without a relay restart); fonts reuse the resolve_asset security pattern.
OVERLAY_PAGES = ("hud", "timer")
FONT_CTYPES = {"woff2": "font/woff2", "woff": "font/woff",
               "ttf": "font/ttf", "otf": "font/otf"}
FONT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

def read_overlay_css(overlay_dir, page):
    """Bytes of profiles/<name>/overlay/<page>.css, or b'' when the dir is unset,
    the page is not a known overlay page, or the file is absent/unreadable. Read
    per request so editor saves apply without a relay restart."""
    if not overlay_dir or page not in OVERLAY_PAGES:
        return b""
    try:
        with open(os.path.join(overlay_dir, f"{page}.css"), "rb") as fh:
            return fh.read()
    except OSError:
        return b""

def resolve_overlay_font(overlay_dir, name):
    """Resolve overlay/fonts/<name> to (path, content_type); None if unsafe or
    missing. Same containment guarantees as resolve_asset (strict name + ext
    allow-list + realpath inside fonts/ + constant content-type)."""
    if not overlay_dir or not FONT_NAME_RE.match(name) or "." not in name:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    ctype = FONT_CTYPES.get(ext)
    if not ctype:
        return None
    base = os.path.realpath(os.path.join(overlay_dir, "fonts"))
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        return None
    return (path, ctype) if os.path.exists(path) else None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Wire the endpoints into the handler**

In `make_handler` (`:1402`) add an `overlay_dir=None` parameter (end of the signature). In `do_GET`, add these branches **before** the existing `if p[:1] == ["timer"]:` block (so `/timer/override.css` is matched here, not swallowed by the timer dispatch):

```python
                if p == ["hud", "override.css"]:
                    return self._send_css(read_overlay_css(overlay_dir, "hud"))
                if p == ["timer", "override.css"]:
                    return self._send_css(read_overlay_css(overlay_dir, "timer"))
                if len(p) == 3 and p[:2] == ["overlay", "fonts"]:
                    hit = resolve_overlay_font(overlay_dir, p[2])
                    if not hit:
                        return self._send({"error": "font not found", "key": p[2]}, 404)
                    return self._send_file(hit[0], hit[1])
```

Add a small `_send_css` helper next to `_send_file` (`:1411`):

```python
        def _send_css(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
            return None
```

**Important ordering:** the `["timer", "override.css"]` check must come before `if p[:1] == ["timer"]:` (`:1456`), otherwise the timer block returns "timer disabled"/404 for it.

- [ ] **Step 6: Add the `--overlay-dir` argument and thread it through**

After the `--no-hud` argument (`:1645`) add:

```python
    ap.add_argument("--overlay-dir", default=None,
                    help="profiles/<name>/overlay dir with per-profile hud.css/"
                         "timer.css/fonts (relay-served at /hud/override.css etc).")
```

Update the `make_handler(...)` call (`:1806`) to pass `overlay_dir=args.overlay_dir`:

```python
    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, timer_path, setup_ctl,
                           overlay_dir=args.overlay_dir)
```

- [ ] **Step 7: Add the override hook to the base pages**

`src/obs/hud.html` — insert immediately after `</style>` (`:54`), before `</head>`:

```html
<link rel="stylesheet" href="/hud/override.css">
```

`src/obs/timer.html` — insert immediately after `</style>` (`:17`), before `</head>`:

```html
<link rel="stylesheet" href="/timer/override.css">
```

(The base inline `<style>` stays untouched; the link is last so override rules win the cascade. With no override the endpoint returns empty CSS — harmless.)

- [ ] **Step 8: Run the full relay-affecting suite + lint**

Run: `python3 tests/test_overlay.py && python3 tests/test_hud.py && python3 tools/lint.py`
Expected: `ALL PASS` / clean.

- [ ] **Step 9: Commit**

```bash
git add tests/test_overlay.py src/relay/racecast-feeds.py src/obs/hud.html src/obs/timer.html
git commit -m "feat(m5d): relay serves per-profile overlay CSS + fonts"
```

---

## Task 2: Hash-gate + CLI overlay-dir wiring

**Files:**
- Modify: `src/racecast.py` (`OBS_PAGE_PATHS` `:466`; `_relay_runtime_args` `:457`; a new overlay-dir resolver near `_active_profile_env_strict` patterns)
- Test: `tests/test_iro.py` (add `t_`-functions; mirror existing style)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_iro.py`)

```python
def t_obs_page_paths_include_overrides():
    assert iro.OBS_PAGE_PATHS == ("/hud", "/timer", "/hud/override.css", "/timer/override.css")

def t_relay_runtime_args_adds_overlay_when_dir_exists(tmp_path=None):
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        od = os.path.join(tmp, "overlay"); os.makedirs(od)
        args = iro._overlay_relay_args(od)
        assert args == ["--overlay-dir", od]

def t_relay_runtime_args_omits_overlay_when_absent():
    assert iro._overlay_relay_args(None) == []
    assert iro._overlay_relay_args("/no/such/overlay/dir") == []
```

(If `test_iro.py` already loads the module as `iro`, reuse that alias; the module is `src/racecast.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `OBS_PAGE_PATHS` mismatch / `_overlay_relay_args` missing.

- [ ] **Step 3: Extend `OBS_PAGE_PATHS`** (`:466`)

```python
# The relay-served pages OBS renders as browser sources (panel is tablet-only).
# The two override.css are hashed too, so a per-profile CSS edit advances the
# staleness gate and triggers an OBS browser-source refresh.
OBS_PAGE_PATHS = ("/hud", "/timer", "/hud/override.css", "/timer/override.css")
```

- [ ] **Step 4: Add the overlay-dir resolver + fold it into the relay args**

Add a helper (near `_relay_runtime_args`, `:457`):

```python
def _active_overlay_dir():
    """profiles/<active>/overlay for the active profile, or None when no profile
    resolves. (Does not check existence — callers decide.)"""
    active = _active_profile_name()
    if not active:
        return None
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    return os.path.join(pcfg.profiles_dir(root), active, "overlay")

def _overlay_relay_args(overlay_dir):
    """['--overlay-dir', DIR] when DIR exists, else [] (pure for tests)."""
    if overlay_dir and os.path.isdir(overlay_dir):
        return ["--overlay-dir", overlay_dir]
    return []
```

Then append into `_relay_runtime_args` (`:457`) so every relay invocation that has an overlay dir gets it:

```python
def _relay_runtime_args():
    """Runtime args every relay invocation gets: its profile-scoped runtime dir
    plus the shared cookie jar (see _cookies_path), and --overlay-dir when the
    active profile ships an overlay/ dir. Placed before the caller's rest so an
    explicit flag in rest still wins."""
    return (["--runtime-dir", _runtime_dir(), "--cookies", _cookies_path()]
            + _overlay_relay_args(_active_overlay_dir()))
```

**Frozen-mode note:** `_relay_daemon_argv` adds `_relay_runtime_args()` only in the non-frozen branch; in frozen mode the binary re-invokes `relay run`, and the foreground `relay_run` path adds runtime args there. Verify `relay_run` (grep `def relay_run`) also calls `_relay_runtime_args()` — it does for `--runtime-dir`/`--cookies`, so `--overlay-dir` rides along automatically. No extra change needed; confirm by reading.

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_iro.py && python3 tools/lint.py`
Expected: `ALL PASS` / clean.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py tests/test_iro.py
git commit -m "feat(m5d): hash-gate + CLI wire --overlay-dir for active profile"
```

---

## Task 3: OBS collection-name prefix convention

**Files:**
- Modify: `src/scripts/config.py` (`:194`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_config.py`, mirror existing profile-fixture helpers)

```python
def t_obs_collection_defaults_to_prefixed_name():
    with _profile(NAME="IRO Endurance", SHEET_ID="x") as root:
        rc = cfg.resolve_config(root)
        assert rc.obs_collection == "GT Endurance Racing — IRO Endurance"

def t_obs_collection_explicit_wins():
    with _profile(NAME="IRO Endurance", SHEET_ID="x",
                  OBS_COLLECTION="Custom Name") as root:
        rc = cfg.resolve_config(root)
        assert rc.obs_collection == "Custom Name"
```

(Reuse whatever profile-writing context manager/fixture `test_config.py` already defines — match its existing helper name; `_profile` above is illustrative.)

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_config.py`
Expected: FAIL — `obs_collection == "IRO Endurance"` (bare name).

- [ ] **Step 3: Add the prefix constant + default** (`src/scripts/config.py`)

Near the top constants add:

```python
# Default OBS scene-collection name = product prefix + the league NAME, so several
# leagues' collections group together in OBS. An explicit OBS_COLLECTION wins.
PRODUCT_COLLECTION_PREFIX = "GT Endurance Racing"
```

Change line `:194`:

```python
        obs_collection=prof.get("OBS_COLLECTION") or f"{PRODUCT_COLLECTION_PREFIX} — {resolved_name}",
```

- [ ] **Step 4: Run test + lint**

Run: `python3 tests/test_config.py && python3 tools/lint.py`
Expected: `ALL PASS` / clean.

**Note for later (do NOT change here):** the canonical fold-back name in `tools/tokenize-obs.py` (`CANONICAL_COLLECTION_NAME = "GT Endurance Racing"`) stays as-is — it resets the name on export so a league name never lands in git. This task only changes the *runtime default* an operator gets.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/config.py tests/test_config.py
git commit -m "feat(m5d): default OBS collection name to 'GT Endurance Racing — <league>'"
```

---

## Task 4: Control Center overlay-CSS editor — backend

**Files:**
- Modify: `src/racecast.py` (providers near `:1958`; ctx wiring `:2549`)
- Modify: `src/ui/ui_server.py` (GET branch near `:283`; POST branch near `:369`)
- Test: `tests/test_ui_ops.py`, `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_ui_ops.py` (or wherever `profile_env_*_data` are tested — grep; they live in `racecast.py`, tested via the `iro` alias). Add:

```python
def t_overlay_read_absent_ok_empty():
    # with an active profile that has no overlay/hud.css yet
    # (reuse the test's active-profile fixture used for profile_env tests)
    d = iro.overlay_read_data("hud")
    assert d["ok"] is True and d["css"] == "" and d["page"] == "hud"

def t_overlay_write_then_read_roundtrip():
    iro.overlay_write_data("hud", "#stint{left:5px}")
    d = iro.overlay_read_data("hud")
    assert d["ok"] is True and d["css"] == "#stint{left:5px}"

def t_overlay_rejects_unknown_page():
    assert iro.overlay_write_data("panel", "x")["ok"] is False
    assert iro.overlay_read_data("../etc")["ok"] is False
```

Mirror the active-profile fixture/setup the existing `profile_env_entries_data` tests use (a temp root with `profiles/<active>/` + `runtime/active-profile`). If those tests monkeypatch `_active_profile_env_strict`'s inputs via env/cwd, reuse the exact same mechanism.

In `tests/test_ui_server.py` add a route test (mirror the `/api/profile/env` GET + POST tests): `GET /api/overlay?page=hud` calls `ctx["overlay_read"]("hud")`; `POST /api/overlay` with `{page, content}` calls `ctx["overlay_write"]`. Use the existing fake-ctx harness in that file.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_ui_ops.py && python3 tests/test_ui_server.py`
Expected: FAIL — `overlay_read_data` missing / route 404.

- [ ] **Step 3: Add the providers** (`src/racecast.py`, after `profile_env_write_data` `:1965`)

```python
def _active_profile_overlay_path(page):
    """(active, abs path to overlay/<page>.css) for the active profile, or
    (None, None) when no profile resolves or `page` is not an overlay page.
    Server-resolved; never a client path. Mirrors _active_profile_env_strict."""
    if page not in ("hud", "timer"):
        return None, None
    active = _active_profile_name()
    if not active:
        return None, None
    root = _env_base(IS_FROZEN, _real_executable(), HERE)
    od = os.path.join(pcfg.profiles_dir(root), active, "overlay")
    return active, os.path.join(od, f"{page}.css")

def overlay_read_data(page):
    """The active profile's overlay/<page>.css text for the editor.
    {ok, page, active, css, path} or {ok:false, error}. Never raises."""
    try:
        active, path = _active_profile_overlay_path(page)
        if not active:
            return {"ok": False, "error": "no active profile or invalid page"}
        css = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                css = fh.read()
        return {"ok": True, "page": page, "active": active, "css": css, "path": path}
    except Exception as exc:
        return {"ok": False, "error": f"could not read overlay css: {exc}"}

def overlay_write_data(page, content):
    """Persist editor content to the active profile's overlay/<page>.css
    (creates overlay/ if needed, atomic tmp+replace). {ok,path} or
    {ok:false,error}. Server resolves the path, never a client value."""
    try:
        active, path = _active_profile_overlay_path(page)
        if not active:
            return {"ok": False, "error": "no active profile or invalid page"}
        if not isinstance(content, str):
            return {"ok": False, "error": "content must be a string"}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": f"could not write overlay css: {exc}"}
```

Wire into ctx (`:2549`, after `profile_env_write`):

```python
        "overlay_read": overlay_read_data,
        "overlay_write": overlay_write_data,
```

- [ ] **Step 4: Add the server routes** (`src/ui/ui_server.py`)

GET branch (after the `/api/profile/env` GET at `:283`):

```python
            if path == "/api/overlay":
                try:
                    page = (parse_qs(urlparse(self.path).query).get("page") or ["hud"])[0]
                    return self._json(ctx["overlay_read"](page))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not read overlay css: {exc}"}, 400)
```

(Confirm `parse_qs`/`urlparse` are imported at the top of `ui_server.py`; if not, add them — they are stdlib `urllib.parse`.)

POST branch (after the `/api/profile/env` POST at `:369`):

```python
            if path == "/api/overlay":
                try:
                    result = ctx["overlay_write"](body.get("page"), body.get("content"))
                    return self._json(result, 200 if result.get("ok") else 400)
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"could not write overlay css: {exc}"}, 400)
```

(Match the exact `_json`/status-code convention the sibling `/api/profile/*` POSTs use — return 400 on `ok:false` so the HTML branches on `d.ok`.)

- [ ] **Step 5: Run tests + lint**

Run: `python3 tests/test_ui_ops.py && python3 tests/test_ui_server.py && python3 tools/lint.py`
Expected: `ALL PASS` / clean.

- [ ] **Step 6: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_ui_ops.py tests/test_ui_server.py
git commit -m "feat(m5d): Control Center overlay-CSS editor backend (providers + routes)"
```

---

## Task 5: Control Center overlay-CSS editor — frontend

**Files:**
- Modify: `src/ui/control-center.html` (Profile view; mirror the existing `profile.env` editor card)

- [ ] **Step 1: Read the existing Profile-view editor**

Read `src/ui/control-center.html` and locate the Profile view's `profile.env` editor card and its JS (the `profile_env_read`/`profile_env_write` fetches, the `envEditorRow`/`collectEnvEditor` helpers, and the active-profile-aware rendering). The overlay editor mirrors this exactly — same card styling, same load-on-view, same save→toast pattern.

- [ ] **Step 2: Add an "Overlay CSS" card to the Profile view**

Add a card (below the `profile.env` editor, above/below the graphics/media assets — match surrounding layout) containing:
- A page selector (two buttons or a `<select>`: **HUD** / **Timer**), default HUD.
- A `<textarea id="overlayCss">` (monospace, ~12 rows).
- A **Save** button and a small **Apply in OBS** button.

JS (mirror the profile.env fetch/save style already in the file):

```javascript
let overlayPage = "hud";
async function loadOverlay() {
  const r = await fetch(`/api/overlay?page=${overlayPage}`);
  const d = await r.json();
  const ta = document.getElementById("overlayCss");
  if (d.ok) { ta.value = d.css; ta.disabled = false; }
  else { ta.value = ""; ta.disabled = true; toast(d.error || "no active profile"); }
}
async function saveOverlay() {
  const content = document.getElementById("overlayCss").value;
  const r = await fetch("/api/overlay", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ page: overlayPage, content }) });
  const d = await r.json();
  toast(d.ok ? "Overlay CSS saved — Apply in OBS to see it" : (d.error || "save failed"));
}
function setOverlayPage(p) { overlayPage = p; /* update active button state */ loadOverlay(); }
```

- The **Apply in OBS** button calls the existing OBS-refresh op the UI already exposes (find how the page triggers `obs refresh` — reuse that exact call; do NOT invent a new endpoint). It is best-effort and needs the relay + obs-websocket, exactly like `racecast obs refresh`.
- Call `loadOverlay()` when the Profile view becomes active (hook into the same place that triggers `profile_env` loading), and when the active profile switches.

- [ ] **Step 3: Live-smoke with Playwright**

Start the UI (`python3 src/racecast.py ui` on a test port, with at least one profile active), navigate to the Profile view, confirm: the Overlay card renders, switching HUD/Timer reloads the textarea, Save persists (re-open shows the saved CSS), zero console errors. (Use the Playwright MCP browser tools; mirror the M4 smoke approach.)

- [ ] **Step 4: Verify the build still assembles the UI**

Run: `python3 tools/build.py`
Expected: verify step passes (UI shipped).

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(m5d): Control Center overlay-CSS editor (Profile view)"
```

---

## Task 6: Example profile overlay templates

**Files:**
- Create: `profiles/example/overlay/hud.css`
- Create: `profiles/example/overlay/timer.css`
- Create: `profiles/example/overlay/fonts/.gitkeep`

- [ ] **Step 1: Confirm `profiles/example/` is tracked (not gitignored)**

Run: `git check-ignore -v profiles/example/overlay/hud.css || echo "tracked-ok"`
Expected: `tracked-ok` (the `.gitignore` rule excludes other profiles but keeps `profiles/example/`). If it IS ignored, add a negation rule `!profiles/example/` consistent with the existing `profile.env` exception, then re-check.

- [ ] **Step 2: Write `profiles/example/overlay/hud.css`** (commented no-op template)

```css
/* Per-league HUD override — OPTIONAL. The relay serves this file at
 * /hud/override.css and loads it AFTER the base hud.html styles, so any rule
 * here wins the cascade. Delete what you don't need; an empty/missing file
 * means the base look is used unchanged.
 *
 * Overridable elements (ids in the base hud.html, canvas 1920x1080, top-left):
 *   #stint #session #streamer #round-top #round-flag #round-country
 *   #team0 #team1 #team2 #race-control
 *
 * Examples — uncomment and adjust:
 *   #stint    { left: 800px; top: 30px; font-size: 44px; }
 *   #race-control { background: #222a2f; }
 *
 * Custom font (drop the file in overlay/fonts/ first):
 *   @font-face { font-family: "League"; src: url(/overlay/fonts/League.woff2); }
 *   html, body { font-family: "League", "Arial Narrow", sans-serif; }
 */
```

- [ ] **Step 3: Write `profiles/example/overlay/timer.css`** (commented no-op template)

```css
/* Per-league race-timer override — OPTIONAL. Served at /timer/override.css,
 * loaded after the base timer.html styles (cascade wins). Empty/missing = base.
 *
 * Overridable element: #clock (the digits). Examples:
 *   #clock { font-size: 380px; top: 240px; color: #f4f4f4; }
 *   @font-face { font-family: "League"; src: url(/overlay/fonts/League.woff2); }
 *   #clock { font-family: "League", monospace; }
 */
```

- [ ] **Step 4: Create the fonts keep file**

```bash
mkdir -p profiles/example/overlay/fonts
printf '%s\n' '# Drop league font files here (woff2/woff/ttf/otf); reference them from' \
              '# hud.css/timer.css via url(/overlay/fonts/<file>). See ../hud.css.' \
  > profiles/example/overlay/fonts/.gitkeep
```

- [ ] **Step 5: Verify the relay serves the example end-to-end**

Run the relay against the example profile and confirm the override endpoints exist (empty CSS, 200) and a dropped font resolves. Quick check:
```bash
python3 - <<'PY'
import importlib.util, os
spec = importlib.util.spec_from_file_location("feeds", "src/relay/racecast-feeds.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
od = "profiles/example/overlay"
print("hud css bytes:", len(m.read_overlay_css(od, "hud")))   # >0 (the comment template)
print("font None:", m.resolve_overlay_font(od, "nope.woff2")) # None
PY
```
Expected: prints a non-zero byte count and `None`.

- [ ] **Step 6: Commit**

```bash
git add profiles/example/overlay/
git commit -m "feat(m5d): example profile overlay templates (hud/timer css + fonts dir)"
```

---

## Gate (after all tasks; before pushing)

- [ ] **Full suite:** `python3 tools/run-tests.py` → ALL TEST FILES PASS
- [ ] **Lint:** `python3 tools/lint.py` → clean
- [ ] **Build:** `python3 tools/build.py` → verify passes (UI + obs pages shipped; the new `<link>` is in the shipped hud/timer html; example overlay templates copied)
- [ ] **Straggler check (code scope only):** confirm no test or code still expects the bare-name OBS collection default (`grep -rn '"IRO Endurance"' tests/ src/scripts/config.py` — fixtures may keep the league NAME, but the resolved `obs_collection` default is now prefixed).
- [ ] **Manual relay sanity (optional):** start the relay with `--overlay-dir profiles/example/overlay`, `curl -s 127.0.0.1:8088/hud/override.css` returns the template; `curl -s 127.0.0.1:8088/hud` contains the `<link ... /hud/override.css>`.
- [ ] **Final cross-cutting review:** dispatch a code-reviewer over the whole M5d diff — focus: endpoint ordering (timer/override.css before the timer block), font path-traversal containment, the hash-gate now fetches 4 paths and stays `None`-safe when `--no-hud`/`--no-timer`, the editor resolver can never escape `profiles/<active>/overlay/`, and frozen-mode relay inherits `--overlay-dir`.

## After the gate

- Push `feat/multi-profile-rebrand`.
- Update the rolling **PR #43** title + body: add the **M5d** row (per-profile overlay overrides + collection-name convention) and a "What's landed" bullet.
- Update memory `multi-profile-rebrand.md`: mark M5d DONE; reaffirm **M6 must document the overlay feature**.
- Watch CI to green (`gh pr checks 43 --watch --fail-fast`).
- **Do NOT merge** — M6 (docs/wiki/README de-brand + repo rename, now also documenting overlay) is still the final, irreversible step.
