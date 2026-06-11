# UI Self-Update + Preview Installs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Control Center UI install updates one-click (with release-notes preview), including CI preview builds, instead of only linking to the GitHub Releases page (issue #34).

**Architecture:** Thin UI over an extended CLI updater. `src/scripts/update.py` gains a `--tag` install path and pure functions to list pre-releases; `src/iro.py` exposes the listing + release notes to the UI; the UI spawns `iro update [--tag <tag>] --yes` as a streamed job using the existing op/job/console machinery. The regular-update banner opens a notes dialog with an "Update now" button; a Help-view section (behind an opt-in toggle) lists installable preview builds.

**Tech Stack:** Pure Python + stdlib (no framework), the project's no-pytest convention (each `tests/test_*.py` is a runnable script), vanilla JS in `src/ui/control-center.html`, GitHub Releases REST API (unauthenticated).

---

## Background the implementer must know

- **No-pytest convention.** Each test file is a script; the bottom runs every
  `t_*` function and prints `ALL PASS`. Run one file with `python3 tests/test_X.py`.
  `python3 tools/run-tests.py` runs the whole suite (glob over `tests/test_*.py`,
  so extending an existing file needs no registration). Lint: `python3 tools/lint.py`.
- **`src/scripts/update.py` is the single source of truth** for the version
  compare / release lookup. It is almost entirely pure functions with injected
  HTTP (`opener=`/`fetch=`); `main()` is the only I/O glue and is not unit-tested
  (mirror that — test the pure helpers, keep `main()` thin).
- **GitHub API facts:** `GET /releases/latest` excludes pre-releases. `GET
  /releases` returns all (newest first) with a `prerelease` boolean. `GET
  /releases/tags/<tag>` fetches one. Each release has `tag_name`, `name`,
  `body` (markdown notes), `target_commitish`, `published_at`, and `assets[]`
  (each with `name` + `browser_download_url`).
- **Preview tags/versions** (`tools/preview_meta.py`): tags `preview-pr-<n>` /
  `preview-<ref>`; versions `preview-pr<n>-<sha>` / `preview-<ref>-<sha>`. Not
  semver — `parse_version()` returns `None`. There can be several at once.
- **Asset names per platform** (existing `asset_name()`): `iro-windows.zip`,
  `iro-macos.tar.gz`, `iro-linux.tar.gz`.
- **UI job machinery already exists.** `op(name, confirmFirst, params)` POSTs to
  `/api/op/<name>`, then `watchJob()` streams the log into the docked console.
  Ops are defined in `src/ui/ui_ops.py` (`OPS` argv map + optional `PARAMS`
  validators). `iro update` is already a registered ONESHOT in `src/iro.py`
  (`ONESHOTS`), and `iro.py` injects `--current <version>` for it.
- **Source-mode guard:** `update.main()` refuses to self-update a source
  checkout (`parse_version("dev") is None and not frozen` → "update with git
  pull"). The new `--tag` path must sit **after** that guard, so a dev/repo run
  of the UI also refuses (correct — you don't install a binary over a checkout).

## File structure

- `src/scripts/update.py` — **modify.** Add `fetch_release_by_tag`,
  `classify_tag`, `fetch_releases`, `classify_prereleases`, and a `--tag` branch
  in `main()`.
- `src/iro.py` — **modify.** Add `notes` to `update_check_data`; add
  `preview_list_data` + a cached provider; register `previews` in the UI ctx;
  extend the `iro update` usage line with `[--tag TAG]`.
- `src/ui/ui_ops.py` — **modify.** Add `update` + `update-preview` ops and a
  `_tag_arg` validator.
- `src/ui/ui_server.py` — **modify.** Add the `/api/previews` GET route.
- `src/ui/control-center.html` — **modify.** Notes dialog + wire the update
  banner; Help-view preview section behind an opt-in toggle.
- `tests/test_update.py` — **modify.** Cover the four new pure functions.
- `tests/test_ui_ops.py` — **modify.** Cover the two new ops + tag validator.
- `tests/test_ui_server.py` — **modify.** Cover the `/api/previews` route.
- `CLAUDE.md` — **modify.** Update the `iro update` line in the Commands list.

---

## Task 1: `update.py` — install a specific tag (pure decision)

**Files:**
- Modify: `src/scripts/update.py`
- Test: `tests/test_update.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_update.py` (above the `__main__` block):

```python
# --- classify_tag: install exactly one named release (no semver compare) -------
TAGREL = {"tag_name": "preview-pr-42",
          "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/m"},
                     {"name": "iro-windows.zip", "browser_download_url": "https://x/w"}]}


def t_classify_tag_install_when_asset_present():
    assert m.classify_tag(TAGREL, "darwin") == ("install", "preview-pr-42", "https://x/m")
    assert m.classify_tag(TAGREL, "win32") == ("install", "preview-pr-42", "https://x/w")


def t_classify_tag_building_when_platform_asset_missing():
    assert m.classify_tag(TAGREL, "linux") == ("building", "preview-pr-42", None)


def t_classify_tag_error_on_missing_tag():
    assert m.classify_tag({"assets": []}, "darwin")[0] == "error"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_update.py`
Expected: `AttributeError: module 'update' has no attribute 'classify_tag'`

- [ ] **Step 3: Implement `classify_tag` + `fetch_release_by_tag`**

In `src/scripts/update.py`, add after `classify(...)` (around line 56):

```python
def classify_tag(release, platform):
    """Decide how to install one *named* release (the UI's preview/explicit
    path). Pure. No semver compare — an explicit tag means 'install exactly
    this'. Returns a (kind, tag, url) 3-tuple:
    ('error',    message, None)  malformed release data (no tag_name)
    ('building', tag, None)      release exists, platform asset not uploaded yet
    ('install',  tag, url)"""
    tag = release.get("tag_name", "")
    if not tag:
        return ("error", "release has no tag_name", None)
    want = asset_name(platform)
    for asset in release.get("assets", []):
        if asset.get("name") == want:
            return ("install", tag, asset.get("browser_download_url"))
    return ("building", tag, None)


def fetch_release_by_tag(tag, opener=None):
    """GET one release by tag. `opener(request, timeout)` is injectable for tests.
    Raises urllib HTTPError(404) for an unknown tag (caller maps to a friendly
    'no such release')."""
    import urllib.request
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    req = urllib.request.Request(url, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    resp = opener(req, timeout=15)
    try:
        return json.load(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_update.py`
Expected: `ok t_classify_tag_*` lines, then `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/update.py tests/test_update.py
git commit -m "feat(update): classify_tag + fetch_release_by_tag for explicit installs"
```

---

## Task 2: `update.py` — wire `--tag` into `main()`

**Files:**
- Modify: `src/scripts/update.py` (`main()`)

No new unit test: `main()` is I/O glue (the existing `main()` is not unit-tested;
the decision is `classify_tag`, covered in Task 1). Verified by CLI smoke below.

- [ ] **Step 1: Add the `--tag` argument**

In `main()`, after the `--yes` argument (around line 175), add:

```python
    ap.add_argument("--tag", help="install this exact release tag (UI preview/pin path)")
```

- [ ] **Step 2: Add the `--tag` branch after the source-mode guard**

In `main()`, immediately after the source-mode guard block
(`if parse_version(a.current) is None and not frozen: sys.exit(...)`, ~line 184),
insert:

```python
    if a.tag:
        import urllib.error
        try:
            release = fetch_release_by_tag(a.tag)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                sys.exit(f"update: no release tagged {a.tag!r}.")
            sys.exit(f"update: cannot fetch release {a.tag!r} ({exc}).")
        except Exception as exc:
            sys.exit(f"update: cannot reach GitHub ({exc}). Check your connection.")
        kind, tag, url = classify_tag(release, sys.platform)
        if kind == "error":
            sys.exit(f"update: {tag if isinstance(tag, str) else release.get('tag_name')}")
        if kind == "building":
            sys.exit(f"update: {tag} has no {asset_name(sys.platform)} asset yet — "
                     "retry in a few minutes.")
        print(f"update: installing {tag}")
        if not a.yes and not confirmed(input("Download and replace this binary? [y/N] ")):
            print("aborted.")
            return
        _download_and_swap(url, tag)
        return
```

- [ ] **Step 3: Extract the shared download+swap tail into `_download_and_swap`**

The latest-release path and the `--tag` path share the download→swap→install_ui
tail. Refactor the existing tail of `main()` (from `exe = sys.executable` through
the final prints) into a module-level helper, and call it from both. Add:

```python
def _download_and_swap(url, tag):
    """Download the archive at `url`, swap the running binary, reinstall iro-ui.
    Shared by the latest-release flow and the --tag flow. Prints progress."""
    exe = sys.executable
    with tempfile.TemporaryDirectory(dir=os.path.dirname(exe)) as td:
        archive = os.path.join(td, asset_name(sys.platform))
        print("Downloading:", url)
        download(url, archive)
        new = extract_binary(archive, td)
        if not new:
            sys.exit("update: archive did not contain the iro binary — aborted, nothing changed.")
        try:
            perform(swap_plan(sys.platform, exe, new))
        except OSError as exc:
            hint = (" Restore by renaming iro-old.exe back to iro.exe."
                    if sys.platform.startswith("win") and not os.path.exists(exe) else "")
            sys.exit(f"update: swap failed ({exc}).{hint}")
        try:
            ui_path = install_ui(td, os.path.dirname(exe), sys.platform)
        except OSError as exc:
            ui_path = None
            print(f"update: note — iro-ui not installed ({exc}); "
                  "use `iro ui` from the CLI, or reinstall the archive.")
    print(f"updated to {tag} — restart iro to use it.")
    if ui_path:
        print(f"installed {os.path.basename(ui_path)} next to iro.")
    if sys.platform.startswith("win"):
        print("(the old binary was kept as iro-old.exe and is removed on the next start)")
```

Then replace the latest-release tail in `main()` (the `_, tag, url = action`
block's download/swap part) with:

```python
    _, tag, url = action
    if a.check:
        print(f"update available: {a.current} -> {tag}  (run `iro update` to install)")
        return
    print(f"update: {a.current} -> {tag}")
    if not a.yes and not confirmed(input("Download and replace this binary? [y/N] ")):
        print("aborted.")
        return
    _download_and_swap(url, tag)
```

- [ ] **Step 4: Run the existing suite (no regression)**

Run: `python3 tests/test_update.py`
Expected: `ALL PASS`

- [ ] **Step 5: CLI smoke (repo mode refuses, arg parses)**

Run: `python3 src/scripts/update.py --tag preview-main --current dev`
Expected: prints `update: running from source — update with git pull instead.`
(the source-mode guard fires before any network call — this proves `--tag`
parses and the guard ordering is correct).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/update.py
git commit -m "feat(update): --tag installs an exact release (shared download/swap)"
```

---

## Task 3: `update.py` — list installable pre-releases (pure)

**Files:**
- Modify: `src/scripts/update.py`
- Test: `tests/test_update.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_update.py`:

```python
# --- classify_prereleases: the UI's installable-previews list ------------------
RELEASES = [
    {"tag_name": "v1.2.2", "prerelease": False, "name": "1.2.2",
     "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/stable"}]},
    {"tag_name": "preview-pr-42", "prerelease": True, "name": "Preview: PR #42 (abc1234)",
     "target_commitish": "abc1234deadbeef", "published_at": "2026-06-10T08:00:00Z",
     "body": "notes for 42",
     "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/p42"}]},
    {"tag_name": "preview-main", "prerelease": True, "name": "Preview: main (deadbee)",
     "target_commitish": "", "published_at": "2026-06-09T08:00:00Z", "body": "notes main",
     "assets": []},   # still building — no platform asset yet
]


def t_classify_prereleases_filters_stable_and_shapes_rows():
    rows = m.classify_prereleases(RELEASES, "darwin")
    assert [r["tag"] for r in rows] == ["preview-pr-42", "preview-main"]
    r0 = rows[0]
    assert r0["title"] == "Preview: PR #42 (abc1234)"
    assert r0["commit"] == "abc1234deadbeef"
    assert r0["published_at"] == "2026-06-10T08:00:00Z"
    assert r0["notes"] == "notes for 42"
    assert r0["asset_url"] == "https://x/p42"


def t_classify_prereleases_marks_building_with_none_asset():
    rows = m.classify_prereleases(RELEASES, "darwin")
    building = [r for r in rows if r["tag"] == "preview-main"][0]
    assert building["asset_url"] is None


def t_classify_prereleases_commit_falls_back_to_version_sha():
    rel = [{"tag_name": "preview-pr-9", "prerelease": True, "name": "x",
            "version": "preview-pr9-cafef00", "target_commitish": "",
            "assets": []}]
    assert m.classify_prereleases(rel, "linux")[0]["commit"] == "cafef00"


def t_classify_prereleases_empty():
    assert m.classify_prereleases([], "darwin") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_update.py`
Expected: `AttributeError: module 'update' has no attribute 'classify_prereleases'`

- [ ] **Step 3: Implement `classify_prereleases` + `fetch_releases`**

In `src/scripts/update.py`, add after `classify_tag` (Task 1):

```python
def _commit_of(release):
    """Best commit id for a pre-release row: the release target SHA, else the
    short SHA embedded in the version/name (e.g. 'cafef00' in 'preview-pr9-cafef00')."""
    target = (release.get("target_commitish") or "").strip()
    if target:
        return target
    text = release.get("version") or release.get("name") or release.get("tag_name") or ""
    tail = text.rsplit("-", 1)[-1]
    return tail if tail and tail.isalnum() else ""


def classify_prereleases(releases, platform):
    """Map the GitHub /releases list to the UI's installable-preview rows. Pure.
    Keeps only prereleases; for each returns
    {tag, version, title, commit, published_at, asset_url|None, notes}
    where asset_url is None when this platform's asset is not uploaded yet."""
    want = asset_name(platform)
    rows = []
    for rel in releases:
        if not rel.get("prerelease"):
            continue
        url = None
        for asset in rel.get("assets", []):
            if asset.get("name") == want:
                url = asset.get("browser_download_url")
                break
        rows.append({
            "tag": rel.get("tag_name", ""),
            "version": rel.get("version") or rel.get("name") or rel.get("tag_name", ""),
            "title": rel.get("name") or rel.get("tag_name", ""),
            "commit": _commit_of(rel),
            "published_at": rel.get("published_at", ""),
            "asset_url": url,
            "notes": rel.get("body") or "",
        })
    return rows


def fetch_releases(per_page=30, opener=None):
    """GET the releases list (newest first). `opener` injectable for tests."""
    import urllib.request
    url = f"https://api.github.com/repos/{REPO}/releases?per_page={int(per_page)}"
    req = urllib.request.Request(url, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    resp = opener(req, timeout=15)
    try:
        return json.load(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_update.py`
Expected: new `ok t_classify_prereleases_*` lines, then `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add src/scripts/update.py tests/test_update.py
git commit -m "feat(update): classify_prereleases + fetch_releases for the UI list"
```

---

## Task 4: `iro.py` — notes on the update check + previews provider

**Files:**
- Modify: `src/iro.py` (`update_check_data`, ctx wiring, usage string)

- [ ] **Step 1: Add `notes` to `update_check_data`**

In `src/iro.py`, in `update_check_data` (~line 1335), after
`out["update_available"] = kind in ("update", "building")`, add:

```python
    out["notes"] = release.get("body") or ""
```

- [ ] **Step 2: Add `preview_list_data` next to `update_check_data`**

Immediately after `update_check_data(...)` returns (after its `def`), add:

```python
def preview_list_data(fetch=None, platform=None):
    """On-demand list of installable preview builds for the Control Center's
    Help view. Thin wrapper over scripts/update.py's pure classifier — never
    downloads. Network call; {"ok": False} when offline / rate-limited. `fetch`/
    `platform` are test seams."""
    import update as upd
    out = {"ok": True, "previews": []}
    try:
        releases = (fetch or upd.fetch_releases)()
    except Exception:
        out["ok"] = False
        return out
    try:
        out["previews"] = upd.classify_prereleases(releases, platform or sys.platform)
    except Exception:
        out["ok"] = False
    return out
```

- [ ] **Step 3: Add a cached provider + register it in ctx**

In the `ui()` function, next to `update_check_cached` (~line 2044), add a second
cache and provider:

```python
    _prev = {"at": 0.0, "data": None}

    def preview_list_cached(force=False):
        now = time.time()
        if not force and _prev["data"] is not None and now - _prev["at"] <= 600:
            return _prev["data"]
        fresh = preview_list_data()
        if fresh.get("ok"):
            _prev["data"], _prev["at"] = fresh, now
            return fresh
        return _prev["data"] or fresh
```

Then in the `ctx = {...}` dict, after `"update_check": update_check_cached,`, add:

```python
        "previews": preview_list_cached,
```

- [ ] **Step 4: Update the usage string**

Change the `iro update` line (line 20) to:

```
  iro update [--check] [--yes] [--tag TAG]   # self-update the binary (--tag installs an exact release)
```

- [ ] **Step 5: Verify the module imports and tests still pass**

Run: `python3 -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'src/scripts'); import iro"`
Expected: no output (imports clean).
Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/iro.py
git commit -m "feat(ui): expose release notes + installable previews to the Control Center"
```

---

## Task 5: `ui_ops.py` — update + update-preview ops

**Files:**
- Modify: `src/ui/ui_ops.py`
- Test: `tests/test_ui_ops.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_ops.py` (near the other `build_argv` tests, ~line 176):

```python
def t_build_argv_update():
    assert ui_ops.build_argv("update") == ["update", "--yes"]


def t_build_argv_update_preview_tag():
    assert ui_ops.build_argv("update-preview", {"tag": "preview-pr-42"}) == \
        ["update", "--yes", "--tag", "preview-pr-42"]
    assert ui_ops.build_argv("update-preview", {"tag": "v1.2.3"}) == \
        ["update", "--yes", "--tag", "v1.2.3"]


def t_build_argv_update_preview_rejects_bad_tag():
    # An empty/blank tag is treated as "not provided" by build_argv (it just
    # omits --tag), so it is NOT in this bad-tag loop — only malformed tags raise.
    for bad in ("preview-pr-42; rm -rf /", "../../etc", "weird tag", "release"):
        try:
            ui_ops.build_argv("update-preview", {"tag": bad})
            assert False, f"accepted bad tag {bad!r}"
        except ValueError:
            pass
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 tests/test_ui_ops.py`
Expected: `ValueError: unknown operation: update` (the op isn't registered yet).

- [ ] **Step 3: Register the ops + validator**

In `src/ui/ui_ops.py`, add to the `OPS` dict (after `"install-apps": [...]`):

```python
    "update": ["update", "--yes"],
    "update-preview": ["update", "--yes"],
```

Add the validator next to `_update_flag` (~line 55):

```python
import re

_TAG_RE = re.compile(r"^(v\d|preview-)[\w.-]+$")


def _tag_arg(value):
    """A release tag the UI may install. Allowlist: a vX… stable tag or a
    preview-… tag. Defends against argv junk (the UI only ever sends a tag it
    got from /api/previews)."""
    s = str(value)
    if not _TAG_RE.match(s):
        raise ValueError(f"invalid release tag: {value!r}")
    return ["--tag", s]
```

(If `ui_ops.py` already imports `re` at the top, do not add a second import —
move `_TAG_RE`/`_tag_arg` below the existing imports.)

Add to the `PARAMS` dict:

```python
    "update-preview": {"tag": _tag_arg},
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 tests/test_ui_ops.py`
Expected: new `ok t_build_argv_update*` lines, then `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_ops.py tests/test_ui_ops.py
git commit -m "feat(ui): update + update-preview ops with tag allowlist"
```

---

## Task 6: `ui_server.py` — /api/previews route

**Files:**
- Modify: `src/ui/ui_server.py`
- Test: `tests/test_ui_server.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_ui_server.py`, first extend the `_ctx` helper (~line 36) so the
test context provides a `previews` provider. Add inside the returned ctx dict,
near `"update_check": ...`:

```python
        "previews": lambda force=False: {"ok": True, "previews": [
            {"tag": "preview-pr-42", "title": "Preview: PR #42", "commit": "abc1234",
             "published_at": "2026-06-10T08:00:00Z", "asset_url": "https://x/p42",
             "notes": "n"}]},
```

Then add the route test (near `t_update_route_wraps_provider`, ~line 160):

```python
def t_previews_route_wraps_provider():
    httpd, port = _serve(_ctx())
    try:
        code, body = _get(port, "/api/previews")
        assert code == 200
        d = json.loads(body)
        assert d["ok"] and d["previews"][0]["tag"] == "preview-pr-42"
        _c, body2 = _get(port, "/api/previews?force=1")        # force re-check
        assert json.loads(body2)["ok"]
    finally:
        httpd.shutdown()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_ui_server.py`
Expected: FAIL — `/api/previews` returns 404 (route not handled).

- [ ] **Step 3: Add the route**

In `src/ui/ui_server.py`, after the `/api/update` block (ends ~line 223), add:

```python
            if path == "/api/previews":
                force = "force=1" in (urlparse(self.path).query or "")
                try:
                    return self._json(ctx["previews"](force))
                except Exception as exc:
                    return self._json({"ok": False,
                                       "error": f"preview list failed: {exc}"},
                                      code=500)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_ui_server.py`
Expected: `ok t_previews_route_wraps_provider`, then `ALL PASS`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/ui/ui_server.py tests/test_ui_server.py
git commit -m "feat(ui): /api/previews route over the previews provider"
```

---

## Task 7: `control-center.html` — notes dialog + wire the update banner

**Files:**
- Modify: `src/ui/control-center.html`

No unit test (vanilla-JS UI; verified by the build's verify step + manual run).

- [ ] **Step 1: Add a reusable update-notes modal (markup)**

Near the end of the `<body>`, before the closing `</body>` (or alongside the
docked console markup ~line 620), add a `<dialog>`:

```html
<dialog id="updmodal" class="updmodal">
  <h3 id="updtitle">Update</h3>
  <p id="updwarn" class="updwarn" hidden></p>
  <div id="updnotes" class="updnotes"></div>
  <div class="updactions">
    <a id="updgh" class="dlink" target="_blank" rel="noopener">View on GitHub ↗</a>
    <span style="flex:1"></span>
    <button onclick="closeUpdModal()">Cancel</button>
    <button class="primary" id="updgo">Update now</button>
  </div>
</dialog>
```

Add CSS near the other component styles (anywhere in the `<style>` block):

```css
.updmodal { max-width: 640px; width: 90vw; border: none; border-radius: 10px;
            padding: 20px; }
.updmodal::backdrop { background: rgba(0,0,0,.45); }
.updnotes { max-height: 50vh; overflow: auto; font-size: 13px; line-height: 1.5;
            border: 1px solid var(--line, #ddd); border-radius: 6px; padding: 10px;
            margin: 10px 0; white-space: pre-wrap; }
.updwarn { color: #b26a00; background: #fff5e6; border-radius: 6px; padding: 8px 10px; }
.updactions { display: flex; align-items: center; gap: 10px; }
```

- [ ] **Step 2: Add the modal controller JS**

Near `checkUpdate` (~line 820), add:

```javascript
// Open the update dialog for either the latest release (tag omitted -> op
// 'update') or a specific preview tag (op 'update-preview'). Renders notes and
// a non-blocking "services running" warning, then runs the streamed job.
// Status payload shape (see updateHome/onStatus): s.relay.alive,
// s.companion.running, and s.streams is an ARRAY of feeds each with .alive.
function servicesRunning() {
  const s = lastStatus || {};
  const out = [];
  if (s.relay && s.relay.alive) out.push('relay');
  if (s.companion && s.companion.running) out.push('companion');
  if (Array.isArray(s.streams) && s.streams.some(f => f.alive)) out.push('static streams');
  return out;
}

function openUpdModal(opts) {
  // opts: {title, notes, releasesUrl, op, tag}
  $('updtitle').textContent = opts.title || 'Update';
  $('updnotes').textContent = opts.notes || '(no release notes)';
  const gh = $('updgh');
  if (opts.releasesUrl) { gh.hidden = false; gh.href = opts.releasesUrl; }
  else gh.hidden = true;
  const running = servicesRunning();
  const warn = $('updwarn');
  if (running.length) {
    warn.hidden = false;
    warn.textContent = 'Running now: ' + running.join(', ') +
      '. Updating swaps the binary and needs a restart — avoid this during a live show.';
  } else warn.hidden = true;
  $('updgo').onclick = () => {
    closeUpdModal();
    if (opts.tag) op('update-preview', false, {tag: opts.tag});
    else op('update', false);
  };
  $('updmodal').showModal();
}

function closeUpdModal() { $('updmodal').close(); }
```

- [ ] **Step 3: Make the update banner open the modal instead of linking out**

In `checkUpdate` (~line 832), replace the banner wiring inside
`if (d && d.ok && d.update_available && d.latest) { ... }`. Change the `<a>`
banner into a button-like trigger: keep the element but set an `onclick` that
opens the modal, and stop it navigating away. Replace:

```javascript
    b.hidden = false;
    b.href = d.releases_url;
    b.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 19V5"/>' +
                  '<path d="m5 12 7-7 7 7"/></svg>Update → ' + d.latest;
    b.title = 'A newer release (' + d.latest + ') is available — click to view it on GitHub';
```

with:

```javascript
    b.hidden = false;
    b.href = '#';
    b.onclick = (e) => { e.preventDefault();
      openUpdModal({title: 'Update → ' + d.latest, notes: d.notes,
                    releasesUrl: d.releases_url, op: 'update'}); };
    b.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 19V5"/>' +
                  '<path d="m5 12 7-7 7 7"/></svg>Update → ' + d.latest;
    b.title = 'A newer release (' + d.latest + ') is available — click for notes and to install';
```

- [ ] **Step 4: Add a restart notice when the update job ends**

In `watchJob`'s `done` handler (~line 1119), after the `chip` is set, add a
branch so update jobs prompt a restart:

```javascript
    if ((name === 'update' || name === 'update-preview') && ok) {
      alert('Update installed. Quit and reopen the Control Center to use the new version.');
    }
```

- [ ] **Step 5: Manual verification**

Run: `python3 src/iro.py ui` (opens the Control Center). Confirm:
- the sidebar version note still renders;
- if an update is available, clicking the banner opens the dialog with notes +
  "Update now" (do NOT click Update unless you intend to);
- with the relay running, the dialog shows the amber "Running now…" warning.

(If no update is available, temporarily verify the modal by calling
`openUpdModal({title:'Test', notes:'hello', op:'update'})` in the browser
console; then reload.)

- [ ] **Step 6: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): release-notes dialog + one-click update from the banner"
```

---

## Task 8: `control-center.html` — Help-view preview section (opt-in)

**Files:**
- Modify: `src/ui/control-center.html`

- [ ] **Step 1: Add the opt-in section markup to the Help view**

In the Help/Guides view (the block with `<h2>Guides — rendered on the GitHub
wiki</h2>` ~line 598), add a section after the guides/issue paragraph:

```html
<section class="prevsec">
  <h2>Preview / testing builds</h2>
  <label class="prevtoggle">
    <input type="checkbox" id="prevopt" onchange="togglePreviews()">
    Show preview builds (pre-release CI binaries — for testing)
  </label>
  <p class="envhint" id="prevhint" hidden>
    Preview builds come from open PRs and branches. They are not version-ordered —
    install one to test it, then restart the Control Center. Use a stable release
    for production.
  </p>
  <div id="prevlist" hidden></div>
</section>
```

CSS (in the `<style>` block):

```css
.prevsec { margin-top: 24px; border-top: 1px solid var(--line, #ddd); padding-top: 16px; }
.prevtoggle { display: flex; gap: 8px; align-items: center; font-size: 14px; }
.prevrow { display: flex; align-items: center; gap: 10px; padding: 8px 0;
           border-bottom: 1px solid var(--line, #eee); }
.prevrow .meta { flex: 1; font-size: 13px; }
.prevrow .sub { color: #777; font-size: 12px; }
```

- [ ] **Step 2: Add the preview-list controller JS**

Near `openUpdModal` (Task 7), add:

```javascript
const PREV_OPT_KEY = 'iro.previews.optin';

function initPreviewOptin() {
  const on = localStorage.getItem(PREV_OPT_KEY) === '1';
  const box = $('prevopt');
  if (box) { box.checked = on; if (on) loadPreviews(); }
  $('prevhint').hidden = !on;
  $('prevlist').hidden = !on;
}

function togglePreviews() {
  const on = $('prevopt').checked;
  localStorage.setItem(PREV_OPT_KEY, on ? '1' : '0');
  $('prevhint').hidden = !on;
  $('prevlist').hidden = !on;
  if (on) loadPreviews();
}

async function loadPreviews() {
  const box = $('prevlist');
  box.textContent = 'loading…';
  let d;
  try { d = await (await fetch('/api/previews', {cache: 'no-store'})).json(); }
  catch (e) { box.textContent = 'could not reach the Control Center.'; return; }
  if (!d || !d.ok) { box.textContent = 'preview list unavailable (offline or rate-limited).'; return; }
  if (!d.previews.length) { box.textContent = 'no preview builds right now.'; return; }
  box.textContent = '';
  d.previews.forEach(p => {
    const row = document.createElement('div'); row.className = 'prevrow';
    const meta = document.createElement('div'); meta.className = 'meta';
    const date = (p.published_at || '').slice(0, 10);
    meta.innerHTML = '<div>' + escapeHtml(p.title || p.tag) + '</div>' +
      '<div class="sub">' + escapeHtml(p.commit ? p.commit.slice(0, 7) : '') +
      (date ? ' · ' + date : '') + '</div>';
    const btn = document.createElement('button');
    if (p.asset_url) {
      btn.textContent = 'Install';
      btn.className = 'primary';
      btn.onclick = () => openUpdModal({title: p.title || p.tag, notes: p.notes,
                                        op: 'update-preview', tag: p.tag});
    } else {
      btn.textContent = 'building…';
      btn.disabled = true;
    }
    row.appendChild(meta); row.appendChild(btn);
    box.appendChild(row);
  });
}
```

If an `escapeHtml` helper does not already exist in the file, add a minimal one
near the other helpers:

```javascript
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
```

(First grep the file for `escapeHtml` / `function esc` — if one exists, reuse it
and skip this block.)

- [ ] **Step 3: Initialise the opt-in on load**

Find where the Help view is first rendered or where startup wiring runs (search
for `checkUpdate();` ~line 1611, which runs once at startup). Add right after it:

```javascript
initPreviewOptin();
```

If the Help view is lazily rendered (its DOM only exists once shown), instead
call `initPreviewOptin()` from the view's render/switch function so `$('prevopt')`
exists. Grep for how other views (e.g. Apps) initialise on switch and mirror it.

- [ ] **Step 4: Manual verification**

Run: `python3 src/iro.py ui`. In the Help view:
- the "Show preview builds" toggle is OFF by default;
- toggling ON persists across reload (localStorage) and lists current
  pre-releases (or "no preview builds right now");
- each installable row has "Install" → opens the notes dialog with that
  preview's notes; "building…" rows are disabled.

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(ui): opt-in preview-builds list in the Help view"
```

---

## Task 9: Docs + full verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the CLAUDE.md command list**

In `CLAUDE.md`, in the `## Commands` block, change the `iro update` reference (or
add one if absent) under the unified-CLI list to mention `--tag`. Find the
`python3 src/iro.py init` area and add/adjust:

```
python3 src/iro.py update             # self-update the binary from GitHub Releases (--tag TAG installs an exact release; UI previews use this)
```

- [ ] **Step 2: Run the full suite**

Run: `python3 tools/run-tests.py`
Expected: every `test_*.py` prints `ALL PASS`, ending `ALL TEST FILES PASS`.

- [ ] **Step 3: Lint the whole tree**

Run: `python3 tools/lint.py`
Expected: no errors.

- [ ] **Step 4: Build verify (UI files ship — closest thing to CI)**

Run: `python3 tools/build.py`
Expected: assembles `dist/IRO_Broadcast_Package/` and the verify step passes
(tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 5: Commit + open PR**

```bash
git add CLAUDE.md
git commit -m "docs: note iro update --tag in the command list"
git push -u origin feat/ui-self-update
gh pr create --fill --base main
```

The PR body should reference issue #34 and summarise: one-click update with
notes dialog, opt-in preview installs in the Help view, non-blocking
services-running warning, manual-restart UX.

---

## Self-review notes (already reconciled)

- **Spec coverage:** `--tag` install (Task 1–2), preview listing (Task 3),
  notes + provider (Task 4), ops + validator (Task 5), `/api/previews` (Task 6),
  notes dialog + banner + warning + restart notice (Task 7), opt-in Help-view
  list (Task 8), docs + verify (Task 9). Every spec component maps to a task.
- **Type consistency:** the preview row shape `{tag, version, title, commit,
  published_at, asset_url, notes}` is produced in Task 3 and consumed verbatim in
  Tasks 6 (test fixture) and 8 (UI). `op('update'|'update-preview', …)` matches
  the ops registered in Task 5. `openUpdModal({title, notes, releasesUrl, op,
  tag})` is defined in Task 7 and called in Tasks 7–8.
- **Restart UX:** notice-only (no auto-relaunch), per the approved spec.
- **Service warning:** non-blocking, reads `lastStatus` from the existing status
  poll. `servicesRunning()` already matches the verified payload shape
  (`s.relay.alive`, `s.companion.running`, `s.streams[]` with `.alive` — same
  fields `updateHome` reads at ~line 696–712).
