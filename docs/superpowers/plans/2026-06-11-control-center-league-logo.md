# League logo in the Control Center header — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the active league's `LOGO` (from `profiles/<name>/profile.env`) as a small image next to the active-profile name in the Control Center sidebar header.

**Architecture:** `config.py` already resolves `LOGO` → `ResolvedConfig.logo_path` (absolute, existence-checked). A pure extension gate (`servable_logo_path`) restricts serving to web images; a best-effort provider (`profile_logo`) exposes the active profile's logo path; a server-resolved route `GET /api/profile/logo` serves the bytes (no path in the request → no traversal surface); `/api/profiles` gains a `logo` boolean so the frontend knows whether to render the `<img>`.

**Tech Stack:** Pure Python stdlib (`http.server`), vanilla HTML/CSS/JS. Tests are stdlib runnable scripts (no pytest). Spec: `docs/superpowers/specs/2026-06-11-control-center-league-logo-design.md`.

---

## File Structure

- `src/racecast.py` — `servable_logo_path` helper, `profile_logo` provider + `ctx` entry, `logo` flag in `profiles_data`.
- `src/ui/ui_server.py` — `.svg` in `_CTYPES`, `GET /api/profile/logo` route.
- `src/ui/control-center.html` — `<img>` markup, `.pflogo` CSS + `.brandsub` flex, `loadProfiles` logo logic, `setHeaderLogo` helper, refresh-after-save.
- `profiles/example/profile.env` — clarify the `LOGO` comment.
- `tests/test_iro.py` — unit tests for `servable_logo_path`, `profile_logo`, and the `profiles_data` `logo` flag.
- `tests/test_ui_server.py` — `GET /api/profile/logo` route tests (+ `profile_logo` in the `_ctx` fixture).

---

## Task 1: `servable_logo_path` extension gate (pure helper)

**Files:**
- Modify: `src/racecast.py` (add helper just above `def profiles_data():`, line 1764)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_iro.py` (it loads `src/racecast.py` as module `m`):

```python
def t_servable_logo_path_allows_web_images_only():
    for p in ("a/logo.png", "a/logo.JPG", "x.jpeg", "x.webp", "x.gif", "brand.svg"):
        assert m.servable_logo_path(p) == p          # web image -> passed through
    for p in ("", "profile.env", "notes.txt", "clip.mp4", "a/logo", "x.PNG.bak"):
        assert m.servable_logo_path(p) == ""          # not a web image -> blanked
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_servable_logo_path_allows_web_images_only()"`
Expected: FAIL with `AttributeError: module 'iro' has no attribute 'servable_logo_path'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/racecast.py`, immediately above `def profiles_data():` (currently line 1764):

```python
_LOGO_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")


def servable_logo_path(logo_path):
    """Return `logo_path` only when it is a web-image file (by extension),
    else "". Pure extension gate: keeps the /api/profile/logo route from
    serving a non-image file someone put in LOGO (e.g. profile.env). Existence
    is validated upstream in config.py (ResolvedConfig.logo_path)."""
    if logo_path and os.path.splitext(logo_path)[1].lower() in _LOGO_EXTS:
        return logo_path
    return ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_servable_logo_path_allows_web_images_only()"`
Expected: no output, exit 0 (pass).

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_iro.py
git commit -m "feat(ui): servable_logo_path web-image extension gate"
```

---

## Task 2: `logo` flag in `profiles_data`

**Files:**
- Modify: `src/racecast.py` `profiles_data()` (line 1764)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_iro.py` (mirrors the existing `t_profiles_data_lists_active_and_available` seam):

```python
def t_profiles_data_reports_active_logo_flag():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "iro"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "iro", "profile.env"), "w") as fh:
            fh.write("NAME=IRO GTEC\nLOGO=logo.png\n")
        with open(os.path.join(prof, "iro", "logo.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\nFAKE")              # any bytes; isfile is what matters
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            with_logo = m.profiles_data()
            os.remove(os.path.join(prof, "iro", "logo.png"))   # file gone -> flag false
            without_logo = m.profiles_data()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert with_logo["ok"] is True and with_logo["logo"] is True
        assert without_logo["logo"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_profiles_data_reports_active_logo_flag()"`
Expected: FAIL with `KeyError: 'logo'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/racecast.py`, edit `profiles_data()` — capture the active profile's logo flag inside the existing resolve loop and add it to the return dict. Replace the loop + return:

```python
        out = []
        logo = False
        for n in pcfg.list_profiles(root):
            try:
                rc = pcfg.resolve_config(root, override=n, runtime_root=runtime_root)
                out.append({"name": n, "display": rc.name,
                            "sheet_set": bool(rc.sheet_id)})
                if n == active:
                    logo = bool(servable_logo_path(rc.logo_path))
            except pcfg.ProfileError:
                out.append({"name": n, "display": n, "sheet_set": False})
        return {"ok": True, "active": active, "logo": logo, "profiles": out}
```

- [ ] **Step 4: Run the test (and the existing profiles_data test) to verify they pass**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_profiles_data_reports_active_logo_flag(); t.t_profiles_data_lists_active_and_available()"`
Expected: no output, exit 0 (both pass — the existing test is unaffected because it ignores the new `logo` key).

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_iro.py
git commit -m "feat(ui): report active-profile logo flag in profiles_data"
```

---

## Task 3: `profile_logo` provider + ctx wiring

**Files:**
- Modify: `src/racecast.py` (add `profile_logo()` near `profiles_data`; add `"profile_logo"` to the `ctx` dict ~line 2655)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_iro.py`:

```python
def t_profile_logo_returns_active_servable_path():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        prof = os.path.join(td, "profiles")
        os.makedirs(os.path.join(prof, "iro"))
        open(os.path.join(td, ".env.example"), "w").close()
        with open(os.path.join(prof, "iro", "profile.env"), "w") as fh:
            fh.write("NAME=IRO\nLOGO=logo.svg\n")
        logo = os.path.join(prof, "iro", "logo.svg")
        with open(logo, "wb") as fh:
            fh.write(b"<svg/>")
        os.makedirs(os.path.join(td, "runtime"))
        with open(os.path.join(td, "runtime", "active-profile"), "w") as fh:
            fh.write("iro\n")
        orig_b, orig_r = m._env_base, m._runtime_base_dir
        m._env_base = lambda *a, **k: td
        m._runtime_base_dir = lambda: os.path.join(td, "runtime")
        try:
            got = m.profile_logo()
            os.remove(logo)                # file gone -> None
            gone = m.profile_logo()
        finally:
            m._env_base, m._runtime_base_dir = orig_b, orig_r
        assert got == logo
        assert gone is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_profile_logo_returns_active_servable_path()"`
Expected: FAIL with `AttributeError: module 'iro' has no attribute 'profile_logo'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/racecast.py`, add directly below `servable_logo_path` (above `profiles_data`):

```python
def profile_logo():
    """Absolute path to the ACTIVE profile's logo when it is a servable web
    image, else None. Best-effort (never raises) — the header logo is optional.
    Served by GET /api/profile/logo."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        rc = pcfg.resolve_config(root, runtime_root=_runtime_base_dir())
        return servable_logo_path(rc.logo_path) or None
    except Exception:
        return None
```

Then add to the `ctx` dict (after `"profiles": profiles_data,`, ~line 2655):

```python
        "profile_logo": profile_logo,
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -c "import sys; sys.path.insert(0,'tests'); import test_iro as t; t.t_profile_logo_returns_active_servable_path()"`
Expected: no output, exit 0 (pass).

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_iro.py
git commit -m "feat(ui): profile_logo provider for the active league logo"
```

---

## Task 4: `GET /api/profile/logo` route + `.svg` content type

**Files:**
- Modify: `src/ui/ui_server.py` (`_CTYPES` ~line 80; new route in `do_GET` after the `/api/profiles` block ~line 282)
- Test: `tests/test_ui_server.py` (add `profile_logo` to `_ctx`; two route tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_ui_server.py`, extend the `_ctx` signature and dict so the fixture provides a `profile_logo` (default → None):

```python
def _ctx(jobs=None, init_plan=None, init_step=None, profile_logo=None):
```

and add this entry to the returned dict (next to `"profiles": ...`, ~line 99):

```python
            "profile_logo": profile_logo or (lambda: None),
```

Then add the two tests (near the other route tests):

```python
def t_profile_logo_route_serves_image_with_type():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        svg = os.path.join(td, "logo.svg")
        with open(svg, "wb") as fh:
            fh.write(b"<svg/>")
        httpd, port = _serve(_ctx(profile_logo=lambda: svg))
        try:
            with _urlopen(f"http://127.0.0.1:{port}/api/profile/logo") as r:
                assert r.status == 200
                assert r.headers.get("Content-Type") == "image/svg+xml"
                assert r.read() == b"<svg/>"
        finally:
            httpd.shutdown()


def t_profile_logo_route_404_when_no_logo():
    httpd, port = _serve(_ctx())            # default profile_logo -> None
    try:
        code, _ = _get(port, "/api/profile/logo")
        assert code == 404
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the svg test gets `Content-Type: application/octet-stream` (no `.svg` in `_CTYPES`) **and** both routes currently fall through to 404 (no `/api/profile/logo` handler), so `t_profile_logo_route_serves_image_with_type` fails first.

- [ ] **Step 3: Write the minimal implementation**

In `src/ui/ui_server.py`, add `.svg` to `_CTYPES` (line 80 block):

```python
        _CTYPES = {".png": "image/png", ".jpg": "image/jpeg",
                   ".jpeg": "image/jpeg", ".webp": "image/webp",
                   ".gif": "image/gif", ".svg": "image/svg+xml",
                   ".mp4": "video/mp4",
                   ".webm": "video/webm", ".mov": "video/quicktime",
                   ".html": "text/html; charset=utf-8",
                   ".md": "text/plain; charset=utf-8",
                   ".txt": "text/plain; charset=utf-8"}
```

Then add the route in `do_GET`, immediately after the `if path == "/api/profile/env":` block (~line 289):

```python
            if path == "/api/profile/logo":
                p = ctx["profile_logo"]()
                return self._serve_file(p) if p else self._not_found("no logo")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_ui_server.py`
Expected: `ALL PASS` (the whole file's tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): GET /api/profile/logo route + svg content type"
```

---

## Task 5: Sidebar header — markup, CSS, and JS

No automated test (the project unit-tests the server, not the HTML/JS). Verification is manual via the running Control Center at the end of this task.

**Files:**
- Modify: `src/ui/control-center.html` (CSS ~line 46; markup line 363; `loadProfiles` ~line 1827; `saveProfileEnv` ~line 1944)

- [ ] **Step 1: CSS — make `.brandsub` a flex row and add `.pflogo`**

Replace line 46 and add the logo rule after the `:hover` rule (line 47):

```css
  .brandsub { font-size:11px; color:var(--dim); padding:2px 14px 8px; cursor:pointer;
              display:flex; align-items:center; }
  .brandsub:hover { color:var(--txt); }
  .pflogo { max-height:24px; max-width:90px; height:auto; width:auto;
            border-radius:3px; margin-right:6px; vertical-align:middle; }
```

- [ ] **Step 2: Markup — add the logo `<img>` and a name `<span>` inside the badge**

Replace line 363:

```html
        <div class="brandsub" id="active-profile-badge" title="Active league profile — click to manage" onclick="showView('profile')"><img id="active-profile-logo" class="pflogo" alt="" hidden onerror="this.hidden=true"><span id="active-profile-name">—</span></div>
```

- [ ] **Step 3: JS — add `setHeaderLogo` and wire it into `loadProfiles`**

In `loadProfiles()`, replace the badge block (lines 1827–1831):

```javascript
  activeProfile = d.active || null;
  const label = d.active || 'no profile';
  $('profile-active-sub').textContent = label;
  const nameEl = $('active-profile-name');
  if (nameEl) nameEl.textContent = label;
  setHeaderLogo(d.active, d.logo);
```

Add this helper directly above `async function loadProfiles(` (the function that starts ~line 1798; place the helper just before it):

```javascript
// Header league logo: point the <img> at the server-resolved active-profile
// logo (cache-bust per profile so a switch reloads it); hide it when the active
// profile has no servable logo. onerror in the markup hides a broken file.
function setHeaderLogo(active, hasLogo) {
  const img = $('active-profile-logo');
  if (!img) return;
  if (active && hasLogo) {
    img.src = '/api/profile/logo?p=' + encodeURIComponent(active);
    img.hidden = false;
  } else {
    img.hidden = true;
    img.removeAttribute('src');
  }
}
```

- [ ] **Step 4: JS — refresh the header logo after a profile.env save**

In `saveProfileEnv()`, after `loadProfileEnv();` (line 1944) add:

```javascript
  loadProfileEnv();                        // reflect the canonical file (masked again)
  fetch('/api/profiles', {cache: 'no-store'}).then(r => r.json())
    .then(d => { if (d.ok) setHeaderLogo(d.active, d.logo); }).catch(() => {});
```

- [ ] **Step 5: Manual verification**

```bash
# In a profile that exists (e.g. example), drop an image and point LOGO at it:
cp <any-image>.png profiles/example/logo.png
printf '\nLOGO=logo.png\n' >> profiles/example/profile.env
RACECAST_PROFILE=example python3 src/racecast.py ui
```

Open `http://127.0.0.1:8089`. Expected: the logo appears next to the profile name in the sidebar header, ≤24px tall, aspect ratio intact. Remove the `LOGO` line (or the file) and reload → the name shows alone (no broken image). Revert the throwaway edits:

```bash
git checkout profiles/example/profile.env && rm -f profiles/example/logo.png
```

- [ ] **Step 6: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): show the active league logo in the sidebar header"
```

---

## Task 6: Clarify the `LOGO` comment + full gates

**Files:**
- Modify: `profiles/example/profile.env`

- [ ] **Step 1: Update the misleading comment**

Replace the `LOGO` comment block:

```bash
# OPTIONAL: a logo image (relative to this profile dir) for the Control Center.
LOGO=
```

with:

```bash
# OPTIONAL: a league logo image (PNG/JPG/WebP/GIF/SVG), path relative to this
# profile dir, shown next to the profile name in the Control Center sidebar.
LOGO=
```

- [ ] **Step 2: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: all suites pass (exactly what CI runs).

- [ ] **Step 3: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (clean). `--fix` auto-corrects if needed.

- [ ] **Step 4: Build self-verify (ships? run build)**

Run: `python3 tools/build.py`
Expected: assembles `dist/` and the verify step passes (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 5: Commit**

```bash
git add profiles/example/profile.env
git commit -m "docs(profile): LOGO is shown in the Control Center sidebar"
```

---

## Self-Review (author checklist — done before handoff)

- **Spec coverage:** servable filter → Task 1; `/api/profiles` logo flag → Task 2; provider + ctx → Task 3; route + `.svg` _CTYPES → Task 4; markup/CSS (24px, inline, flex)/JS + refresh-after-save → Task 5; example comment fix → Task 6. All spec sections mapped.
- **Names consistent across tasks:** `servable_logo_path(logo_path)`, `profile_logo()`, ctx key `"profile_logo"`, route `/api/profile/logo`, `/api/profiles` key `logo`, DOM ids `active-profile-logo` / `active-profile-name`, JS `setHeaderLogo(active, hasLogo)` — used identically everywhere.
- **No placeholders:** every code/test step carries real code and an exact run command with expected output.
- **Note:** `profile_logo()` uses `_env_base`/`_runtime_base_dir`/`pcfg`/`IS_FROZEN`/`_real_executable`/`HERE`, all already module-level in `src/racecast.py` (confirmed against `profiles_data`).
