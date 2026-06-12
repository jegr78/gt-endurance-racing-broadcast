# Profile Export / Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a producer export a whole league profile as one portable `.zip` and import it on another machine, so onboarding a new producer no longer means hand-creating `profiles/<name>/` and re-entering every league setting.

**Architecture:** A new stdlib-only module `src/scripts/profile_io.py` does the pure zip build/validate/restore (mirroring `backup_admin.py`). Thin providers in `src/racecast.py` wire it to the active profile's paths. The Control Center gets a streaming download route (`GET /api/profile/export`) and a raw-body upload route (`POST /api/profile/import`, no multipart — `cgi` is gone in Python 3.13+), plus Export/Import buttons in the Profile view. CLI parity via `racecast profile export|import`.

**Tech Stack:** Pure Python 3 + stdlib (`zipfile`, `tempfile`, `shutil`, `http.server`), no framework. Tests are runnable scripts (no pytest), auto-discovered by `tools/run-tests.py` as `tests/test_*.py`.

**Spec:** `docs/superpowers/specs/2026-06-12-profile-export-import-design.md`

---

## File Structure

- **Create** `src/scripts/profile_io.py` — pure export/import logic (zip build, manifest, `_safe_members` validation, atomic `.old`-swap restore). Standalone (no sibling imports), like `backup_admin.py`.
- **Create** `tests/test_profile_io.py` — stdlib unit checks for `profile_io` (auto-discovered).
- **Modify** `src/racecast.py` — add `import tempfile`; add providers `profile_export_data` / `profile_import_data`; wire both into the `ctx` dict; add `export`/`import` dispatch in `profile_cmd`.
- **Modify** `src/scripts/profile_admin.py` — extend `PROFILE_VERBS`, `_USAGE`, and `parse_profile_args` for `export`/`import`.
- **Modify** `tests/test_profile.py` — parse-args checks for the two new verbs.
- **Modify** `src/ui/ui_server.py` — add `import tempfile, shutil`; `MAX_IMPORT_BYTES`; `_download_file` + `_body_to_tempfile` handler helpers; `GET /api/profile/export`; `POST /api/profile/import`.
- **Modify** `tests/test_ui_server.py` — live-server checks for the export download + import upload routes (extend `_ctx`).
- **Modify** `src/ui/control-center.html` — Export button + "Include assets" checkbox per profile, Import button + hidden file input + upload/force flow.
- **Modify** `CLAUDE.md`, `README.md` — document the new commands.
- **Modify/Create** `src/docs/wiki/` — onboarding page; note that Control Center screenshots must be regenerated.

---

## Task 1: `profile_io.py` — export + manifest

**Files:**
- Create: `src/scripts/profile_io.py`
- Test: `tests/test_profile_io.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_io.py`:

```python
#!/usr/bin/env python3
"""Stdlib unit checks for whole-profile export/import bundles.
Run: python3 tests/test_profile_io.py"""
import importlib.util, json, os, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "profile_io", os.path.join(ROOT, "src", "scripts", "profile_io.py"))
pio = importlib.util.module_from_spec(spec); spec.loader.exec_module(pio)


def _profile(d, name="iro-gtec", with_logo=True):
    """A fake profile tree + runtime assets. Returns (sources, roots)."""
    pdir = os.path.join(d, "profiles", name)
    overlay = os.path.join(pdir, "overlay")
    os.makedirs(overlay, exist_ok=True)
    with open(os.path.join(pdir, "profile.env"), "w") as f:
        f.write("NAME=IRO GTEC\nSHEET_ID=abc\nSHEET_PUSH_URL=https://x/exec?key=s\n"
                + ("LOGO=logo.png\n" if with_logo else ""))
    with open(os.path.join(overlay, "hud.css"), "w") as f:
        f.write("body{}")
    if with_logo:
        with open(os.path.join(pdir, "logo.png"), "wb") as f:
            f.write(b"PNG")
    gdir = os.path.join(d, "runtime", name, "graphics")
    mdir = os.path.join(d, "runtime", name, "media")
    os.makedirs(gdir, exist_ok=True); os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(gdir, "Overlay.png"), "wb") as f:
        f.write(b"PNG")
    with open(os.path.join(mdir, "Intro.mp4"), "wb") as f:
        f.write(b"MP4")
    sources = {"profile_dir": pdir, "graphics": gdir, "media": mdir}
    roots = {"profiles_root": os.path.join(d, "profiles"),
             "runtime_root": os.path.join(d, "runtime")}
    return sources, roots


def t_export_with_assets():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    path = pio.export_profile("iro-gtec", sources, include_assets=True, dest=d)
    assert path.endswith("iro-gtec-profile.zip")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        man = json.loads(z.read("manifest.json"))
        assert man["kind"] == "profile-export"
        assert man["includes_assets"] is True
        assert man["display"] == "IRO GTEC"
        assert "profile/profile.env" in names
        assert "profile/overlay/hud.css" in names
        assert "profile/logo.png" in names
        assert "graphics/Overlay.png" in names
        assert "media/Intro.mp4" in names


def t_export_without_assets():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    path = pio.export_profile("iro-gtec", sources, include_assets=False, dest=d)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        man = json.loads(z.read("manifest.json"))
        assert man["includes_assets"] is False
        assert "profile/profile.env" in names
        assert not any(n.startswith("graphics/") for n in names)
        assert not any(n.startswith("media/") for n in names)


def t_export_rejects_missing_env():
    d = tempfile.mkdtemp()
    pdir = os.path.join(d, "profiles", "empty"); os.makedirs(pdir)
    try:
        pio.export_profile("empty", {"profile_dir": pdir}, True, d)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print(f"ok {n}")
    print("All profile_io tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_profile_io.py`
Expected: FAIL — `No such file or directory: '.../src/scripts/profile_io.py'` (module missing).

- [ ] **Step 3: Write the module (export half)**

Create `src/scripts/profile_io.py`:

```python
"""Pure logic for whole-profile export/import: zip a league profile (its
profiles/<name>/ tree + optional runtime graphics/media) into a portable bundle,
and import such a bundle on another machine. No argv parsing, no network.
Mirrors backup_admin's discipline: validate before writing, atomic, fail-safe.
Standalone (no sibling imports) so it loads in a bare test the same way.

Bundle layout (a .zip):
  manifest.json   {kind, schema, name, display, created, includes_assets, counts}
  profile/...     the whole profiles/<name>/ tree (profile.env, overlay/, logo, …)
  graphics/...    runtime/<name>/graphics/   (only when includes_assets)
  media/...       runtime/<name>/media/      (only when includes_assets)
"""
import datetime
import json
import os
import re
import shutil
import tempfile
import zipfile

KIND = "profile-export"
SCHEMA = 1
ASSET_SECTIONS = ("graphics", "media")   # top-level subtrees beside profile/
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(name):
    """Free-form league name -> directory-safe slug. Doubles as path-traversal
    defense ('../etc' -> 'etc'). Mirrors profile_admin.slugify — keep in sync."""
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-_")


def _iso_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_tree(zf, src_dir, arc_prefix):
    """Add every file under src_dir to the zip under arc_prefix/. Returns the count
    added (0 when src_dir is missing/empty)."""
    n = 0
    if not src_dir or not os.path.isdir(src_dir):
        return n
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            zf.write(full, f"{arc_prefix}/{rel}")
            n += 1
    return n


def _read_display(profile_dir):
    """The NAME= value from profile.env, or '' when absent/unreadable."""
    try:
        with open(os.path.join(profile_dir, "profile.env"), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() == "NAME":
                    return v.strip()
    except OSError:
        pass
    return ""


def export_profile(name, sources, include_assets, dest):
    """Zip a profile into a portable bundle. `sources` = {profile_dir, graphics,
    media}. `dest` is a target .zip path, or a directory (then <slug>-profile.zip
    inside it). Returns the written path. Raises ValueError on a bad name or a
    profile dir that is missing / has no profile.env."""
    slug = slugify(name)
    if not slug:
        raise ValueError(f"invalid profile name: {name!r}")
    profile_dir = sources.get("profile_dir")
    if not profile_dir or not os.path.isdir(profile_dir):
        raise ValueError(f"profile dir not found: {profile_dir}")
    if not os.path.isfile(os.path.join(profile_dir, "profile.env")):
        raise ValueError("profile has no profile.env")
    path = os.path.join(dest, f"{slug}-profile.zip") if os.path.isdir(dest) else dest
    display = _read_display(profile_dir) or slug
    counts = {}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            counts["profile"] = _add_tree(zf, profile_dir, "profile")
            if include_assets:
                for sect in ASSET_SECTIONS:
                    counts[sect] = _add_tree(zf, sources.get(sect), sect)
            manifest = {"kind": KIND, "schema": SCHEMA, "name": slug,
                        "display": display, "created": _iso_utc(),
                        "includes_assets": bool(include_assets), "counts": counts}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:  # best-effort cleanup of temp file on error
            pass
        raise
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_profile_io.py`
Expected: PASS — `ok t_export_rejects_missing_env`, `ok t_export_with_assets`, `ok t_export_without_assets`, `All profile_io tests passed.`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/profile_io.py tests/test_profile_io.py
git commit -m "feat(profile): export a league profile to a portable zip bundle"
```

---

## Task 2: `profile_io.py` — validation + import

**Files:**
- Modify: `src/scripts/profile_io.py`
- Test: `tests/test_profile_io.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_profile_io.py` (before the `if __name__` block):

```python
def t_round_trip():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    bundle = pio.export_profile("iro-gtec", sources, include_assets=True, dest=d)
    e = tempfile.mkdtemp()
    roots = {"profiles_root": os.path.join(e, "profiles"),
             "runtime_root": os.path.join(e, "runtime")}
    info = pio.import_profile(bundle, roots)
    assert info["name"] == "iro-gtec"
    assert info["display"] == "IRO GTEC"
    assert info["includes_assets"] is True
    pdir = os.path.join(e, "profiles", "iro-gtec")
    assert os.path.isfile(os.path.join(pdir, "profile.env"))
    assert os.path.isfile(os.path.join(pdir, "overlay", "hud.css"))
    assert os.path.isfile(os.path.join(pdir, "logo.png"))
    assert os.path.isfile(os.path.join(e, "runtime", "iro-gtec", "graphics", "Overlay.png"))
    assert os.path.isfile(os.path.join(e, "runtime", "iro-gtec", "media", "Intro.mp4"))


def _bundle_with(d, members, manifest=None):
    """Write a hand-built zip with the given {arcname: bytes} members."""
    path = os.path.join(d, "bad.zip")
    with zipfile.ZipFile(path, "w") as z:
        if manifest is not None:
            z.writestr("manifest.json", json.dumps(manifest))
        for arc, data in members.items():
            z.writestr(arc, data)
    return path


def t_import_rejects_wrong_kind():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x"},
                       manifest={"kind": "look-backup", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_missing_env():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/overlay/hud.css": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_traversal():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x", "../evil.txt": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_rejects_foreign_top():
    d = tempfile.mkdtemp()
    bad = _bundle_with(d, {"profile/profile.env": b"x", "secrets/x": b"x"},
                       manifest={"kind": "profile-export", "name": "z"})
    try:
        pio.import_profile(bad, {"profiles_root": d, "runtime_root": d})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def t_import_exists_needs_force():
    d = tempfile.mkdtemp(); sources, _ = _profile(d)
    bundle = pio.export_profile("iro-gtec", sources, True, d)
    e = tempfile.mkdtemp()
    roots = {"profiles_root": os.path.join(e, "profiles"),
             "runtime_root": os.path.join(e, "runtime")}
    pio.import_profile(bundle, roots)
    try:
        pio.import_profile(bundle, roots)
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass
    pio.import_profile(bundle, roots, force=True)   # replaces, no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_profile_io.py`
Expected: FAIL — `AttributeError: module 'profile_io' has no attribute 'import_profile'`.

- [ ] **Step 3: Add validation + import to the module**

Append to `src/scripts/profile_io.py`:

```python
def _read_manifest_from(zf):
    try:
        return json.loads(zf.read("manifest.json"))
    except (KeyError, ValueError):
        raise ValueError("bundle has no readable manifest.json")


def _safe_members(zf, manifest):
    """Validate every member: manifest.json, or under profile/ or an ASSET_SECTION,
    with no absolute path and no '..'. profile/profile.env must be present and the
    manifest kind must match. Returns the member list or raises ValueError."""
    if manifest.get("kind") != KIND:
        raise ValueError("not a profile export (wrong or missing kind)")
    members = zf.namelist()
    if "profile/profile.env" not in members:
        raise ValueError("profile export missing profile/profile.env")
    allowed_top = ("profile",) + ASSET_SECTIONS
    for name in members:
        if name == "manifest.json":
            continue
        norm = name.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/"):
            raise ValueError(f"unsafe path in bundle: {name!r}")
        if norm.split("/", 1)[0] not in allowed_top:
            raise ValueError(f"unexpected entry in bundle: {name!r}")
    return members


def _swap_dir(staged, live):
    """Replace live with staged atomically-ish via an .old backup."""
    parent = os.path.dirname(live)
    os.makedirs(parent, exist_ok=True)
    old = live + ".old"
    if os.path.exists(old):
        shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(live):
        os.replace(live, old)
    shutil.move(staged, live)
    shutil.rmtree(old, ignore_errors=True)


def read_manifest(path):
    """The manifest dict from a bundle zip, or {} when unreadable. (For UI/list.)"""
    try:
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}


def import_profile(src_zip, roots, force=False):
    """Create profiles/<slug>/ (+ runtime/<slug>/graphics|media when present) from a
    bundle. `roots` = {profiles_root, runtime_root}. Returns {name, display,
    includes_assets}. Validates the whole archive BEFORE touching any live dir;
    raises ValueError (malformed/unsafe) or FileExistsError (slug taken, no force)."""
    if not os.path.exists(src_zip):
        raise ValueError(f"bundle not found: {src_zip}")
    tmp = tempfile.mkdtemp(prefix="profimport-")
    try:
        with zipfile.ZipFile(src_zip) as zf:
            manifest = _read_manifest_from(zf)
            _safe_members(zf, manifest)       # raises before any extract
            zf.extractall(tmp)                # safe: names validated above
        slug = slugify(manifest.get("name") or "")
        if not slug:
            raise ValueError("bundle manifest has no usable profile name")
        target = os.path.join(roots["profiles_root"], slug)
        if os.path.exists(target) and not force:
            raise FileExistsError(f"profile already exists: {slug} (use force to replace)")
        _swap_dir(os.path.join(tmp, "profile"), target)
        for sect in ASSET_SECTIONS:
            staged = os.path.join(tmp, sect)
            if os.path.isdir(staged):
                _swap_dir(staged, os.path.join(roots["runtime_root"], slug, sect))
        return {"name": slug, "display": manifest.get("display") or slug,
                "includes_assets": bool(manifest.get("includes_assets"))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_profile_io.py`
Expected: PASS — all `ok t_*` lines incl. `t_round_trip`, `t_import_rejects_*`, `t_import_exists_needs_force`, then `All profile_io tests passed.`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/profile_io.py tests/test_profile_io.py
git commit -m "feat(profile): import a profile bundle with validation + atomic swap"
```

---

## Task 3: racecast.py providers + ctx wiring

**Files:**
- Modify: `src/racecast.py:28` (add `import tempfile`)
- Modify: `src/racecast.py` (add providers near the `backup_*_data` block ~line 2361)
- Modify: `src/racecast.py:2954` (ctx dict — after `"backup_delete"`)

- [ ] **Step 1: Add `tempfile` to the imports**

Change `src/racecast.py:28` from:

```python
import glob, hashlib, json, os, re, shutil, sys, time, webbrowser
```

to:

```python
import glob, hashlib, json, os, re, shutil, sys, tempfile, time, webbrowser
```

- [ ] **Step 2: Add the providers**

Insert after `backup_delete_data` (immediately before `def _streams_config_path()` ~line 2363):

```python
def profile_export_data(name=None, include_assets=True, dest=None):
    """Build a portable profile bundle for `name` (default the active profile).
    {ok, path, slug} or {ok:false, error}. `dest` default is a temp .zip the UI
    streams then deletes; the CLI passes a directory or an --out path."""
    try:
        import profile_io as pio
        slug = name or _active_profile_name()
        if not slug:
            return {"ok": False, "error": "no profile to export"}
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        profile_dir = os.path.join(root, "profiles", slug)
        rt = _profile_runtime(_runtime_base_dir(), slug)
        sources = {"profile_dir": profile_dir,
                   "graphics": os.path.join(rt, "graphics"),
                   "media": os.path.join(rt, "media")}
        if dest is None:
            fd, dest = tempfile.mkstemp(prefix="profexport-", suffix=".zip")
            os.close(fd)
        path = pio.export_profile(slug, sources, bool(include_assets), dest)
        return {"ok": True, "path": path, "slug": pio.slugify(slug)}
    except Exception as exc:
        return {"ok": False, "error": f"could not export profile: {exc}"}


def profile_import_data(src_path, force=False):
    """Import a profile bundle file. {ok, name, display, includes_assets} or
    {ok:false, error}. Does NOT switch the active profile."""
    try:
        import profile_io as pio
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        roots = {"profiles_root": os.path.join(root, "profiles"),
                 "runtime_root": _runtime_base_dir()}
        info = pio.import_profile(src_path, roots, force=bool(force))
        return {"ok": True, **info}
    except FileExistsError:
        return {"ok": False,
                "error": "a profile with that name exists (use force to replace)"}
    except Exception as exc:
        return {"ok": False, "error": f"could not import profile: {exc}"}
```

- [ ] **Step 3: Wire into the ctx dict**

In `src/racecast.py`, after the line `"backup_delete": backup_delete_data,` (~line 2954) add:

```python
        "profile_export": profile_export_data,
        "profile_import": profile_import_data,
```

- [ ] **Step 4: Smoke-check the module imports and a provider runs**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'src/scripts'); import racecast as r; print(r.profile_export_data('does-not-exist')['ok'])"
```
Expected: prints `False` (no such profile → graceful `{ok:false}`; no traceback).

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py
git commit -m "feat(profile): Control Center providers for profile export/import"
```

---

## Task 4: ui_server export download + import upload routes

**Files:**
- Modify: `src/ui/ui_server.py:7` (imports), add constant + two handler helpers + two routes
- Test: `tests/test_ui_server.py`

- [ ] **Step 1: Add the failing tests**

In `tests/test_ui_server.py`, extend `_ctx` (the live-server context dict) with two entries. Add inside the dict returned by `_ctx(...)`:

```python
            "profile_export": lambda name=None, assets=True: _export_stub(name, assets),
            "profile_import": lambda path, force=False: _import_stub(path, force),
```

And add these module-level helpers + tests near the other live-server tests:

```python
def _export_stub(name, assets):
    fd, p = tempfile.mkstemp(suffix=".zip"); os.close(fd)
    with open(p, "wb") as f:
        f.write(b"PK\x03\x04stub-zip-bytes")
    return {"ok": True, "path": p, "slug": (name or "active")}


_IMPORTED = {}
def _import_stub(path, force):
    with open(path, "rb") as f:
        _IMPORTED["bytes"] = f.read()
    return {"ok": True, "name": "iro-gtec", "display": "IRO GTEC",
            "includes_assets": True}


def t_profile_export_streams_zip():
    port = _start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profile/export?name=iro-gtec")
        assert r.status == 200
        assert r.headers.get("Content-Disposition", "").startswith("attachment")
        body = r.read()
        assert body.startswith(b"PK")
    finally:
        _stop(port)


def t_profile_import_accepts_raw_body():
    port = _start()
    try:
        data = b"PK\x03\x04uploaded"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/profile/import?force=1",
            data=data, method="POST")
        r = urllib.request.urlopen(req)
        out = json.loads(r.read())
        assert out["ok"] is True and out["name"] == "iro-gtec"
        assert _IMPORTED["bytes"] == data
    finally:
        _stop(port)
```

> Note: use the same `_start()`/`_stop()` (or equivalent live-server start/stop) helpers the existing tests in this file already use. If the existing tests start the server differently, mirror that exact pattern — do not invent new ones.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — the export/import routes return 404 (`urllib.error.HTTPError: 404`).

- [ ] **Step 3: Add imports + constant**

Change `src/ui/ui_server.py:7` from:

```python
import json, os, threading, time
```

to:

```python
import json, os, shutil, tempfile, threading, time
```

After `TAIL_LINES = 40` (~line 13) add:

```python
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024   # 2 GiB — profile bundles include media
```

- [ ] **Step 4: Add the handler helpers**

In the request-handler class, after `_serve_file` (~line 138), add:

```python
        def _download_file(self, full, filename, cleanup=False):
            """Stream a file back as an attachment. Deletes it after (cleanup)."""
            try:
                size = os.path.getsize(full)
                fh = open(full, "rb")
            except OSError:
                return self._not_found("bundle not found")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                shutil.copyfileobj(fh, self.wfile)
            finally:
                fh.close()
                if cleanup:
                    try:
                        os.unlink(full)
                    except OSError:  # best-effort temp cleanup
                        pass
            return None

        def _body_to_tempfile(self, max_bytes):
            """Stream the request body to a temp file in chunks. Returns the path,
            or None when there is no body or it exceeds max_bytes."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if length <= 0 or length > max_bytes:
                return None
            fd, tmp = tempfile.mkstemp(prefix="upload-", suffix=".zip")
            remaining = length
            try:
                with os.fdopen(fd, "wb") as out:
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        out.write(chunk)
                        remaining -= len(chunk)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return None
            return tmp
```

- [ ] **Step 5: Add the GET export route**

In `do_GET`, immediately before the final `return self._not_found()` (the one right before `def _page`), add:

```python
            if path == "/api/profile/export":
                q = parse_qs(urlparse(self.path).query or "")
                name = (q.get("name") or [None])[0]
                assets = (q.get("assets") or ["1"])[0] != "0"
                try:
                    result = ctx["profile_export"](name, assets)
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"export failed: {exc}"}, code=500)
                if not result.get("ok"):
                    return self._json(result, code=400)
                return self._download_file(result["path"],
                                           f"{result['slug']}-profile.zip",
                                           cleanup=True)
```

- [ ] **Step 6: Add the POST import route**

In `do_POST`, immediately before the final `return self._not_found()` (before `def _page`), add:

```python
            if path == "/api/profile/import":
                q = parse_qs(urlparse(self.path).query or "")
                force = (q.get("force") or ["0"])[0] == "1"
                tmp = self._body_to_tempfile(MAX_IMPORT_BYTES)
                if tmp is None:
                    return self._json({"ok": False,
                                       "error": "upload too large or unreadable"},
                                      code=413)
                try:
                    result = ctx["profile_import"](tmp, force)
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"import failed: {exc}"}, code=500)
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:  # best-effort temp cleanup
                        pass
                return self._json(result, code=200 if result.get("ok") else 400)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 tests/test_ui_server.py`
Expected: PASS — incl. `t_profile_export_streams_zip`, `t_profile_import_accepts_raw_body`.

- [ ] **Step 8: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): /api/profile/export download + /api/profile/import upload routes"
```

---

## Task 5: CLI verbs `profile export` / `profile import`

**Files:**
- Modify: `src/scripts/profile_admin.py` (`PROFILE_VERBS`, `_USAGE`, `parse_profile_args`)
- Modify: `src/racecast.py:662` (`profile_cmd` dispatch)
- Test: `tests/test_profile.py`

- [ ] **Step 1: Add the failing parse tests**

Append to `tests/test_profile.py` (before any `if __name__` runner; follow the file's existing test style — `m` is the loaded `profile_admin` module, `_raises` is defined at the top):

```python
def t_parse_export_defaults():
    o = m.parse_profile_args(["export", "iro-gtec"])
    assert o["verb"] == "export" and o["name"] == "iro-gtec"
    assert o["no_assets"] is False and o["out"] is None


def t_parse_export_flags():
    o = m.parse_profile_args(["export", "iro-gtec", "--no-assets", "--out", "/tmp/x.zip"])
    assert o["no_assets"] is True and o["out"] == "/tmp/x.zip"
    o2 = m.parse_profile_args(["export", "iro-gtec", "--out=/tmp/y.zip"])
    assert o2["out"] == "/tmp/y.zip"


def t_parse_import():
    o = m.parse_profile_args(["import", "/tmp/bundle.zip"])
    assert o["verb"] == "import" and o["file"] == "/tmp/bundle.zip" and o["force"] is False
    o2 = m.parse_profile_args(["import", "/tmp/bundle.zip", "--force"])
    assert o2["force"] is True


def t_parse_export_needs_name():
    _raises(lambda: m.parse_profile_args(["export"]))


def t_parse_import_needs_file():
    _raises(lambda: m.parse_profile_args(["import"]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_profile.py`
Expected: FAIL — `export` is not in `PROFILE_VERBS`, so `parse_profile_args(["export", ...])` raises `ValueError(_USAGE)` and `o["verb"]` is never reached.

- [ ] **Step 3: Extend the parser**

In `src/scripts/profile_admin.py`:

Change `PROFILE_VERBS`:

```python
PROFILE_VERBS = ("list", "show", "use", "new", "export", "import")
```

Change `_USAGE`:

```python
_USAGE = ("usage: racecast profile {list | show [<name>] | use <name> | "
          "new <name> [--from <source>] | export <name> [--no-assets] [--out PATH] | "
          "import <file> [--force]}")
```

In `parse_profile_args`, change the `out` initializer:

```python
    out = {"verb": verb, "name": None, "source": "example",
           "no_assets": False, "out": None, "file": None, "force": False}
```

and add these branches after the `new` branch (before `return out`):

```python
    elif verb == "export":
        if not args:
            raise ValueError(_USAGE)
        out["name"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--no-assets":
                out["no_assets"] = True
            elif t == "--out":
                if not toks:
                    raise ValueError("--out requires a path")
                out["out"] = toks.pop(0)
            elif t.startswith("--out="):
                val = t.split("=", 1)[1]
                if not val:
                    raise ValueError("--out requires a path")
                out["out"] = val
            else:
                raise ValueError(_USAGE)
    elif verb == "import":
        if not args:
            raise ValueError(_USAGE)
        out["file"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--force":
                out["force"] = True
            else:
                raise ValueError(_USAGE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_profile.py`
Expected: PASS — incl. the five new `t_parse_*` tests.

- [ ] **Step 5: Add `profile_cmd` dispatch**

In `src/racecast.py` `profile_cmd` (~line 662), add these two branches after the `new` branch and before the `use` branch:

```python
    if verb == "export":
        res = profile_export_data(opts["name"],
                                  include_assets=not opts["no_assets"],
                                  dest=opts["out"] or os.getcwd())
        if not res.get("ok"):
            sys.exit(f"racecast: {res['error']}")
        print(f"exported profile '{opts['name']}' -> {res['path']}")
        return None
    if verb == "import":
        res = profile_import_data(opts["file"], force=opts["force"])
        if not res.get("ok"):
            sys.exit(f"racecast: {res['error']}")
        print(f"imported profile '{res['name']}' ({res['display']})")
        print(f"  switch to it: racecast profile use {res['name']}")
        return None
```

- [ ] **Step 6: Manual round-trip smoke test**

Run (from the repo root, against the real `iro-gtec` profile if present, else `example`):
```bash
python3 src/racecast.py profile export example --out /tmp/example-profile.zip && \
python3 -c "import zipfile; z=zipfile.ZipFile('/tmp/example-profile.zip'); print('profile/profile.env' in z.namelist())"
```
Expected: `exported profile 'example' -> /tmp/example-profile.zip` then `True`.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/profile_admin.py src/racecast.py tests/test_profile.py
git commit -m "feat(cli): racecast profile export|import"
```

---

## Task 6: Control Center UI — Export/Import buttons

**Files:**
- Modify: `src/ui/control-center.html` (Profiles card markup ~line 505-515; JS near `loadProfiles` ~line 1844 and `createProfile`/`profile-new` ~line 1903)

This task is HTML/JS only (no unit test — covered manually). Use the existing patterns in the file: `$('id')` helper, `showProfileErr(elId, msg)` for inline errors, `fetch('/api/...')`, and `loadProfiles()` to refresh.

- [ ] **Step 1: Add the Import button + hidden file input + Export controls to the Profiles card**

Find the Profiles card header (grep for `loadProfiles(true)` around line 510 — the refresh button). Next to it, add an Import button and a hidden file input. Insert this markup just after the existing header button:

```html
          <button onclick="document.getElementById('profile-import-file').click()">
            <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Import profile</button>
          <input type="file" id="profile-import-file" accept=".zip" hidden
                 onchange="importProfile(this)">
```

Add an inline error element if the Profiles card does not already have one near the top of its body (grep for `profile-err`; reuse it if present, otherwise add `<div class="enverr" id="profile-err" hidden></div>`).

- [ ] **Step 2: Add per-profile Export controls**

In `loadProfiles()` where each profile row is built (grep `loadProfiles` ~1844 — find where it appends a row per profile), add an Export button and an "Include assets" checkbox to each row. Append to the row element:

```javascript
    const exWrap = document.createElement('span');
    exWrap.className = 'export-ctl';
    const exAssets = document.createElement('input');
    exAssets.type = 'checkbox'; exAssets.checked = true;
    exAssets.id = 'exassets-' + p.name;
    exAssets.title = 'Include graphics & media';
    const exLbl = document.createElement('label');
    exLbl.htmlFor = exAssets.id; exLbl.textContent = 'assets';
    const exBtn = document.createElement('button');
    exBtn.textContent = 'Export';
    exBtn.onclick = () => exportProfile(p.name, exAssets.checked);
    exWrap.append(exAssets, exLbl, exBtn);
    row.append(exWrap);
```

> Use the actual per-profile object/field names this function already uses (e.g. `p.name`). If rows are built from a different variable, match it exactly.

- [ ] **Step 3: Add the JS functions**

Near the other profile functions (after `createProfile`, ~line 1922), add:

```javascript
function exportProfile(name, assets) {
  // A plain navigation triggers the browser's download of the streamed zip.
  const q = 'name=' + encodeURIComponent(name) + (assets ? '' : '&assets=0');
  window.location = '/api/profile/export?' + q;
}

async function importProfile(input, force) {
  const file = input.files && input.files[0];
  if (!file) return;
  $('profile-err').hidden = true;
  let d;
  try {
    const url = '/api/profile/import' + (force ? '?force=1' : '');
    d = await (await fetch(url, {method: 'POST', body: file})).json();
  } catch (e) {
    showProfileErr('profile-err', 'Control Center not reachable.');
    input.value = ''; return;
  }
  if (!d.ok) {
    // Name collision -> offer to replace with force=1 (re-uses the same file).
    if (/exists/i.test(d.error || '') && !force) {
      if (confirm('A profile with that name exists. Replace it?')) {
        return importProfile(input, true);
      }
      input.value = ''; return;
    }
    showProfileErr('profile-err', d.error || 'could not import profile');
    input.value = ''; return;
  }
  input.value = '';
  if (confirm('Imported "' + d.display + '". Switch to it now?')) {
    await fetch('/api/profile/use', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: d.name})});
  }
  loadProfiles();
}
```

> The `force` re-call relies on the file still being in the input — do NOT clear `input.value` before the confirm path. Only clear it on the terminal branches as shown.

- [ ] **Step 4: Manual verification**

Run the Control Center and exercise both paths:
```bash
python3 src/racecast.py ui
```
Then in the browser Profile view: click **Export** on a profile (a `<slug>-profile.zip` downloads), then **Import profile** and pick that zip (with a different active profile) — it should report "Imported …" and offer to switch. Re-importing the same name should prompt "Replace it?".

Confirm the page still passes its own load (no JS console errors).

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): Export/Import profile controls in the Control Center"
```

---

## Task 7: Docs + wiki

**Files:**
- Modify: `CLAUDE.md` (Commands list + Profiles section)
- Modify: `README.md`
- Modify/Create: `src/docs/wiki/` onboarding page

- [ ] **Step 1: CLAUDE.md — Commands list**

In `CLAUDE.md`, in the `racecast profile …` command block, after the `profile new` line add:

```
python3 src/racecast.py profile export NAME      # export a league profile to a portable zip (--no-assets, --out PATH)
python3 src/racecast.py profile import FILE       # import a profile bundle (--force to replace an existing one)
```

- [ ] **Step 2: CLAUDE.md — Profiles section note**

In the "Profiles + config" / Control Center sections, add one sentence: that a whole profile (its `profiles/<name>/` tree + optional runtime `graphics/media`) can be exported to a single zip and imported on another machine — the onboarding path — and that `SHEET_PUSH_URL` travels with it by design. Distinguish it from the look-backup (`backup_*`), which is the profile-internal snapshot of overlay+graphics+media only.

- [ ] **Step 3: README.md**

Add the two `profile export|import` commands to the operator quickstart command list, with a one-line description ("share a league with another producer").

- [ ] **Step 4: Wiki onboarding page**

In `src/docs/wiki/`, add a short "Onboard a new producer" section (new page or an addition to the profiles page): export → send the zip → `profile import` (or Control Center Import) → `profile use`. Note assets are optional in the bundle and re-fetchable with `racecast graphics`/`media`. Do NOT run `tools/sync-wiki.py` here — publishing is a separate maintainer step.

- [ ] **Step 5: Wiki screenshots note**

Add a checklist note (in the PR description and/or as a `<!-- screenshot -->` marker on the wiki page) that the Control Center Profile-view screenshots must be regenerated after this UI lands (Export/Import buttons + Include-assets checkbox). Capturing/embedding the actual screenshots is a follow-up maintainer step (same flow as the existing wiki screenshots), not part of this code PR.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md src/docs/wiki/
git commit -m "docs: profile export/import (CLI, onboarding wiki, screenshot note)"
```

---

## Task 8: Full verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python3 tools/run-tests.py`
Expected: every `tests/test_*.py` passes, including the new `test_profile_io.py` and the extended `test_profile.py` / `test_ui_server.py`.

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: no findings (clean exit).

- [ ] **Step 3: Build self-verify**

Run: `python3 tools/build.py`
Expected: build succeeds; the verify step passes (tokenization, blanked password, no secrets, preflight present, no shell scripts). Confirms `profile_io.py` ships in `dist/`.

- [ ] **Step 4: Frozen-mode note (manual, optional)**

`profile_io.py` is loaded via `import profile_io` inside the providers — it ships as part of the bundled `src/scripts/` tree, so frozen mode resolves it like the other sibling modules (`backup_admin`, `profile_admin`). No extra PyInstaller datas entry is needed (the whole `src/` tree is bundled). No action unless the build verify flags a missing module.

- [ ] **Step 5: Final commit (if any docs/cleanup remain) and open the PR**

```bash
git log --oneline origin/main..HEAD
```
Expected: the Task 1-7 commits. Open a PR titled `feat(profile): export/import a whole league profile (onboarding)` referencing the spec and this plan.

---

## Self-Review notes (for the implementer)

- **Spec coverage:** export bundle format (Task 1), validation + atomic import (Task 2), providers (Task 3), download + raw-upload routes incl. the 2 GiB cap and no-multipart constraint (Task 4), CLI parity (Task 5), UI buttons + include-assets + force-on-collision (Task 6), docs + wiki + screenshot note (Task 7), gates (Task 8). The look-backup feature is intentionally untouched.
- **SHEET_PUSH_URL** travels inside `profile/profile.env` verbatim — no special handling, per the approved decision.
- **`_allowed()`** in `ui_server.py` is currently a localhost-only no-op stub; the new routes inherit it like every other route — no auth work in this PR.
- **Slug duplication:** `profile_io.slugify` mirrors `profile_admin.slugify` (same regex) and is documented as "keep in sync" — consistent with the repo's existing small-duplication pattern (`load_dotenv`, `detect_tailscale_ip`).
