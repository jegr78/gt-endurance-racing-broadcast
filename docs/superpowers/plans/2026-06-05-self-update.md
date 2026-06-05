# `iro update` Self-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `iro update [--check] [--yes]` lets the frozen binary replace itself with the latest GitHub release.

**Architecture:** New one-shot `src/scripts/update.py` (pure decision helpers + thin network/swap shell, the installer pattern); `src/iro.py` wires the verb, injects `--current <version()>`, and cleans up Windows' `iro-old.exe` leftover at startup. All decision logic is unit-tested with injected data; network and the actual swap stay untested like the installers.

**Tech Stack:** Python stdlib only (urllib, zipfile, tarfile, tempfile). Tests are runnable scripts (NO pytest).

**Spec:** `docs/superpowers/specs/2026-06-05-self-update-design.md`

**Workspace:** ALL work happens in a dedicated worktree on branch `feat/self-update` — the main checkout at `/Users/jegr/Downloads/IRO_Broadcast_Setup` is in parallel use and must not be touched. Execute AFTER the release-automation plan has merged (its `feat:` squash commit then rides the same v0.2.0 Release PR as this one — not a hard dependency, just tidier).

---

### Task 1: Worktree + branch

- [ ] **Step 1: Create the worktree** (base on latest main)

```bash
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup fetch origin
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup worktree add -b feat/self-update /Users/jegr/Downloads/IRO-wt-self-update origin/main
cd /Users/jegr/Downloads/IRO-wt-self-update && git status
```

Expected: new worktree on fresh branch, clean tree. All later tasks run from `/Users/jegr/Downloads/IRO-wt-self-update`.

---

### Task 2: Pure decision helpers in `update.py` (TDD)

**Files:**
- Create: `src/scripts/update.py`
- Create: `tests/test_update.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_update.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the `iro update` decision helpers. Run: python3 tests/test_update.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "update", os.path.join(ROOT, "src", "scripts", "update.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- parse_version ------------------------------------------------------------
def t_parse_version_good():
    assert m.parse_version("v0.1.0") == (0, 1, 0)
    assert m.parse_version("v12.34.56") == (12, 34, 56)


def t_parse_version_bad():
    for bad in ("dev", "", None, "0.1.0", "v1.2", "v1.2.3.4", "va.b.c", "v1.2.x"):
        assert m.parse_version(bad) is None, bad


# --- asset_name ----------------------------------------------------------------
def t_asset_name_per_platform():
    assert m.asset_name("win32") == "iro-windows.zip"
    assert m.asset_name("darwin") == "iro-macos.tar.gz"
    assert m.asset_name("linux") == "iro-linux.tar.gz"


# --- classify: the whole decision in one pure function --------------------------
REL = {"tag_name": "v0.2.0",
       "assets": [{"name": "iro-macos.tar.gz", "browser_download_url": "https://x/m"},
                  {"name": "iro-windows.zip", "browser_download_url": "https://x/w"}]}


def t_classify_dev_refused():
    assert m.classify(REL, "darwin", "dev") == ("dev",)


def t_classify_up_to_date_equal_and_newer_current():
    assert m.classify(REL, "darwin", "v0.2.0") == ("up-to-date", "v0.2.0")
    assert m.classify(REL, "darwin", "v0.3.0") == ("up-to-date", "v0.2.0")


def t_classify_update_with_url():
    assert m.classify(REL, "darwin", "v0.1.0") == ("update", "v0.2.0", "https://x/m")
    assert m.classify(REL, "win32", "v0.1.0") == ("update", "v0.2.0", "https://x/w")


def t_classify_building_window():
    # newer release exists but the platform asset is not uploaded yet
    assert m.classify(REL, "linux", "v0.1.0") == ("building", "v0.2.0")


def t_classify_bad_tag_is_error():
    assert m.classify({"tag_name": "nightly", "assets": []}, "darwin", "v0.1.0")[0] == "error"


# --- swap_plan -------------------------------------------------------------------
def t_swap_plan_posix_inplace():
    assert m.swap_plan("darwin", "/app/iro", "/tmp/new/iro") == \
        [("replace", "/tmp/new/iro", "/app/iro"), ("chmod", "/app/iro")]


def t_swap_plan_windows_rename_trick():
    # impl must use ntpath so this is computable when the test runs on macOS/Linux
    plan = m.swap_plan("win32", r"C:\IRO\iro.exe", r"C:\tmp\iro.exe")
    assert plan == [("rename", r"C:\IRO\iro.exe", r"C:\IRO\iro-old.exe"),
                    ("move", r"C:\tmp\iro.exe", r"C:\IRO\iro.exe")]


# --- safe_member: archive extraction guard ----------------------------------------
def t_safe_member():
    assert m.safe_member("iro") and m.safe_member(".env.example")
    assert m.safe_member("sub/iro")
    assert not m.safe_member("/etc/passwd")
    assert not m.safe_member("..\\iro.exe")
    assert not m.safe_member("a/../../b")
    assert not m.safe_member("C:\\evil")
    assert not m.safe_member("")


# --- fetch_latest: parsing with an injected opener ---------------------------------
def t_fetch_latest_parses_json():
    import io, json
    body = json.dumps(REL).encode()
    rel = m.fetch_latest(opener=lambda req, timeout: io.BytesIO(body))
    assert rel["tag_name"] == "v0.2.0"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_update.py`
Expected: FAIL — `FileNotFoundError` (src/scripts/update.py missing).

- [ ] **Step 3: Implement the helpers**

Create `src/scripts/update.py`:

```python
#!/usr/bin/env python3
"""`iro update` — self-update the standalone binary from GitHub Releases.
Checks /releases/latest, compares semver tags, downloads the platform archive
and swaps the running binary (Windows: rename trick — a running exe can be
renamed but not overwritten). Frozen-only: a repo checkout updates with
`git pull`. Design: docs/superpowers/specs/2026-06-05-self-update-design.md."""
import argparse, json, os, shutil, sys, tarfile, tempfile, zipfile

REPO = "jegr78/IRO_Broadcast_Setup"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(tag):
    """'vX.Y.Z' -> (X, Y, Z); None for anything else (incl. 'dev')."""
    if not tag or not isinstance(tag, str) or not tag.startswith("v"):
        return None
    parts = tag[1:].split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def asset_name(platform):
    """The release asset for a sys.platform value (mirrors release.yml's matrix)."""
    if platform.startswith("win"):
        return "iro-windows.zip"
    if platform == "darwin":
        return "iro-macos.tar.gz"
    return "iro-linux.tar.gz"


def classify(release, platform, current):
    """The whole update decision, pure. Returns one of:
    ('dev',)                running from source -> refuse
    ('error', message)      malformed release data
    ('up-to-date', tag)
    ('building', tag)       newer release exists, platform asset not uploaded yet
    ('update', tag, url)"""
    cur = parse_version(current)
    if cur is None:
        return ("dev",)
    tag = release.get("tag_name", "")
    new = parse_version(tag)
    if new is None:
        return ("error", f"unexpected tag on the latest release: {tag!r}")
    if new <= cur:
        return ("up-to-date", tag)
    want = asset_name(platform)
    for asset in release.get("assets", []):
        if asset.get("name") == want:
            return ("update", tag, asset.get("browser_download_url"))
    return ("building", tag)


def swap_plan(platform, exe, new):
    """Ordered steps that put `new` in place of the running `exe`.
    ntpath for the Windows branch — keeps the function pure/computable when
    tests run on macOS/Linux (os.path.dirname can't split C:\\ paths there)."""
    if platform.startswith("win"):
        import ntpath
        old = ntpath.join(ntpath.dirname(exe), "iro-old.exe")
        return [("rename", exe, old), ("move", new, exe)]
    return [("replace", new, exe), ("chmod", exe)]


def safe_member(name):
    """True iff an archive member path is safe to extract (no abs, no drive, no ..)."""
    if not name or name.startswith(("/", "\\")):
        return False
    if len(name) > 1 and name[1] == ":":
        return False
    return ".." not in name.replace("\\", "/").split("/")


def fetch_latest(opener=None):
    """GET the latest-release JSON. `opener(request, timeout)` is injectable for tests."""
    import urllib.request
    req = urllib.request.Request(API_LATEST, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    with_resp = opener(req, timeout=15)
    try:
        return json.load(with_resp)
    finally:
        close = getattr(with_resp, "close", None)
        if close:
            close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_update.py`
Expected: `ALL PASS` (12 tests). (run-tests.py globs `tests/test_*.py` — no registration needed.)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/update.py tests/test_update.py
git commit -m "feat(update): pure decision helpers (version compare, classify, swap plan)"
```

---

### Task 3: Download, extract, swap + `main()` in `update.py`

**Files:**
- Modify: `src/scripts/update.py` (append below `fetch_latest`)

These are the side-effectful shells around the tested decisions — deliberately untested like the installers' network paths (spec: no CI smoke, no network in tests).

- [ ] **Step 1: Append download/extract/perform**

```python
def download(url, dst, opener=None):
    """Fetch `url` to file path `dst` (HTTPS, cert-verified)."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "iro-update"})
    opener = urllib.request.urlopen if opener is None else opener
    resp = opener(req, timeout=120)
    try:
        with open(dst, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def extract_binary(archive, dest_dir):
    """Extract the archive (zip or tar.gz) into dest_dir with the safe_member
    guard and return the path of the contained iro binary, or None."""
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if safe_member(n)]
            zf.extractall(dest_dir, members=names)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            members = [mem for mem in tf.getmembers() if safe_member(mem.name)]
            tf.extractall(dest_dir, members=members)
    for name in ("iro.exe", "iro"):
        path = os.path.join(dest_dir, name)
        if os.path.isfile(path):
            return path
    return None


def perform(plan):
    """Execute a swap_plan. Steps are tiny on purpose — the logic lives in
    swap_plan() where it is unit-tested."""
    for step in plan:
        if step[0] == "rename":
            os.replace(step[1], step[2])
        elif step[0] in ("move", "replace"):
            shutil.move(step[1], step[2]) if step[0] == "move" else os.replace(step[1], step[2])
        elif step[0] == "chmod":
            os.chmod(step[1], os.stat(step[1]).st_mode | 0o755)


def confirmed(answer):
    return answer.strip().lower().startswith("y")
```

- [ ] **Step 2: Append `main()`**

```python
def main():
    ap = argparse.ArgumentParser(prog="update", add_help=True)
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--current", default="dev", help=argparse.SUPPRESS)  # injected by iro
    a = ap.parse_args()

    if parse_version(a.current) is None:
        sys.exit("update: running from source — update with `git pull` instead.")
    try:
        release = fetch_latest()
    except Exception as exc:
        sys.exit(f"update: cannot reach GitHub releases ({exc}). Check your connection.")

    action = classify(release, sys.platform, a.current)
    if action[0] == "error":
        sys.exit(f"update: {action[1]}")
    if action[0] == "up-to-date":
        print(f"up to date ({a.current}; latest release is {action[1]}).")
        return
    if action[0] == "building":
        sys.exit(f"update: {action[1]} is out but the binaries are still building — "
                 "retry in a few minutes.")

    _, tag, url = action
    if a.check:
        print(f"update available: {a.current} -> {tag}  (run `iro update` to install)")
        return
    print(f"update: {a.current} -> {tag}")
    if not a.yes and not confirmed(input("Download and replace this binary? [y/N] ")):
        print("aborted.")
        return

    exe = sys.executable
    with tempfile.TemporaryDirectory() as td:
        archive = os.path.join(td, asset_name(sys.platform))
        print("Downloading:", url)
        download(url, archive)
        new = extract_binary(archive, td)
        if not new:
            sys.exit("update: archive did not contain the iro binary — aborted, nothing changed.")
        perform(swap_plan(sys.platform, exe, new))
    print(f"updated to {tag} — restart iro to use it.")
    if sys.platform.startswith("win"):
        print("(the old binary was kept as iro-old.exe and is removed on the next start)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the suite (helpers still green) + a repo-mode functional check**

```bash
python3 tests/test_update.py
python3 src/scripts/update.py --check          # no --current -> defaults to dev
```

Expected: `ALL PASS`; the second command exits 1 with `update: running from source — update with \`git pull\` instead.`

- [ ] **Step 4: Commit**

```bash
git add src/scripts/update.py
git commit -m "feat(update): download/extract/swap shell + CLI entrypoint"
```

---

### Task 4: Wire the verb into `iro.py` (TDD)

**Files:**
- Modify: `src/iro.py` — USAGE block (~line 11), `ONESHOTS` tuple (line ~190), `ONESHOT_MAP` (~line 495), `oneshot()` (~line 522), plus a `cleanup_old_binary()` near `ensure_env_file()` and its call in `main()`
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_iro.py`, add next to the other routing tests:

```python
def t_update_routes_as_oneshot():
    a = m.route(["update", "--check"])
    assert a == {"kind": "oneshot", "command": "update", "rest": ["--check"]}, a


def t_update_oneshot_extra_injects_nothing():
    # update needs no runtime-dir/--out injection; --current is added in oneshot()
    assert m._oneshot_extra("update", [], True, "/rt") == []
    assert m._oneshot_extra("update", [], False, "/rt") == []
```

And next to `t_ensure_env_file_creates_once`:

```python
def t_cleanup_old_binary():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        old = os.path.join(d, "iro-old.exe")
        with open(old, "wb") as fh:
            fh.write(b"x")
        # only frozen windows cleans up
        assert m.cleanup_old_binary(d, frozen=False, platform="win32") is False
        assert m.cleanup_old_binary(d, frozen=True, platform="darwin") is False
        assert os.path.exists(old)
        assert m.cleanup_old_binary(d, frozen=True, platform="win32") is True
        assert not os.path.exists(old)
        # absent file -> quiet False
        assert m.cleanup_old_binary(d, frozen=True, platform="win32") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `t_update_routes_as_oneshot` (`update` not in ONESHOTS → route raises/help) or AttributeError for `cleanup_old_binary`.

- [ ] **Step 3: Implement the wiring**

In `src/iro.py`:

a) USAGE block — add after the `iro export companion` line:

```
  iro update [--check] [--yes]          # self-update the binary from GitHub Releases
```

b) `ONESHOTS` tuple (line ~190) gains `"update"`:

```python
ONESHOTS = ("preflight", "cookies", "graphics", "media", "setup", "install-tools", "install-apps", "update")
```

c) `ONESHOT_MAP` gains:

```python
    "update":        "scripts/update.py",
```

d) `oneshot()` injects the binary's own version (keeps `_oneshot_extra` pure):

```python
def oneshot(command, rest):
    extra = _oneshot_extra(command, rest, IS_FROZEN, _runtime_dir())
    if command == "update" and "--current" not in rest:
        extra += ["--current", version()]
    raise SystemExit(_run_script(ONESHOT_MAP[command], list(rest) + extra))
```

e) Add directly below `ensure_env_file()`:

```python
def cleanup_old_binary(exe_dir, frozen=None, platform=None):
    """Best-effort removal of the iro-old.exe that `iro update` leaves behind on
    Windows (a running exe can only be renamed, not deleted, during the swap).
    Returns True iff the leftover existed and was removed."""
    frozen = IS_FROZEN if frozen is None else frozen
    platform = sys.platform if platform is None else platform
    if not frozen or not platform.startswith("win"):
        return False
    old = os.path.join(exe_dir, "iro-old.exe")
    try:
        if os.path.exists(old):
            os.remove(old)
            return True
    except OSError:
        pass
    return False
```

f) `main()` — call it right after `ensure_env_file(...)`:

```python
def main(argv=None):
    ensure_env_file(os.path.dirname(sys.executable))
    cleanup_old_binary(os.path.dirname(sys.executable))
    _load_env_frozen()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_iro.py && python3 tools/run-tests.py`
Expected: `ALL PASS` / `ALL TEST FILES PASS`. Also functional: `python3 src/iro.py update --check` exits with the run-from-source refusal (route → oneshot → dev guard).

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): update verb wiring, --current injection, iro-old.exe startup cleanup"
```

---

### Task 5: Docs

**Files:**
- Modify: `src/docs/wiki/Set-up-the-broadcast-PC.md` (step 1)
- Modify: `src/docs/wiki/Run-an-event.md` (pre-event checklist)
- Modify: `src/docs/wiki/If-something-goes-wrong.md` (one table row)
- Modify: `README.md` (one line in the operator part)

- [ ] **Step 1: Apply the four small edits** (read each file first; wording below, placement per the page's existing structure)

- Set-up page, end of step 1 (after the command-style note): `Updating later is one command: \`iro update\`.`
- Run-an-event, new FIRST item in the pre-event list: `**Update the tool:** \`iro update\` — picks up the latest release (skip if the team froze the version for the event).`
- If-something-goes-wrong, new row: `| \`iro update\` says binaries are still building | The release was just cut and CI is still uploading — retry in a few minutes. |`
- README, after the binary-download paragraph: `Update later with a single command: \`iro update\`.`

- [ ] **Step 2: Verify English-only + no command typos**

Run: `grep -rn "iro update" src/docs/wiki/ README.md`
Expected: the four additions, nothing else odd.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/ README.md
git commit -m "docs: operators update with iro update"
```

---

### Task 6: Verify, push, PR, merge

- [ ] **Step 1: Full suite + build verify**

Run: `python3 tools/run-tests.py && python3 tools/build.py`
Expected: `ALL TEST FILES PASS` + build self-verify OK.

- [ ] **Step 2: Local E2E against the REAL latest release (macOS — this machine)**

The trick: build a binary stamped with a version OLDER than the published release, then let it really update itself.

```bash
python3 -m pip show pyinstaller >/dev/null 2>&1 || python3 -m pip install pyinstaller
python3 tools/build-binary.py --version v0.0.1
rm -rf /tmp/iro-e2e && mkdir /tmp/iro-e2e && cp dist/bin/iro /tmp/iro-e2e/
cd /tmp/iro-e2e
./iro --version                 # iro v0.0.1 (+ creates .env)
./iro update --check            # update available: v0.0.1 -> v0.1.0 (or newer)
./iro update --yes              # downloads + swaps
./iro --version                 # the REAL latest release version
cd -
```

Expected: exactly as commented; `.env` still present afterwards. (If the latest release's macOS asset is missing — building window — the command must say so and leave the binary untouched.)

- [ ] **Step 3: Push the branch and open the PR**

```bash
git push -u origin feat/self-update
gh pr create --title "feat(update): self-updating binary via GitHub Releases" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-06-05-self-update-design.md:
iro update [--check|--yes] — semver check against releases/latest, platform
archive download, self-swap (Windows rename trick + startup cleanup), dev-mode
guard, building-window handling. Decision logic unit-tested; E2E verified
locally on macOS against the real release.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: CI green, then squash-merge with a conventional title**

```bash
gh pr checks --watch
gh pr merge --squash --subject "feat(update): self-updating binary via GitHub Releases"
```

- [ ] **Step 5: Clean up the worktree**

```bash
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup worktree remove /Users/jegr/Downloads/IRO-wt-self-update
git -C /Users/jegr/Downloads/IRO_Broadcast_Setup branch -d feat/self-update 2>/dev/null || true
```

- [ ] **Step 6: Hand over** — note for the user: the release-please Release PR now includes this feature; merging it cuts the first release whose binaries can self-update from then on. Windows-side verification of the rename-trick swap happens on the streaming PC with that release.

---

## Self-review notes (spec coverage)

- Dev guard / `--current` injection → Tasks 3+4 (route/oneshot tested; functional check in both).
- Check / compare / asset selection / building window → Task 2 (`classify` covers the whole matrix).
- Confirm prompt, `--yes`, `--check` → Task 3 `main()`.
- Download/extract with manual `safe_member` guard (3.11–3.13) → Tasks 2+3.
- Per-OS swap incl. Windows rename trick → Task 2 (`swap_plan` tested) + Task 3 (`perform`).
- `iro-old.exe` next-start cleanup → Task 4 (tested).
- `.env`/`runtime/` untouched → swap touches only the binary path; E2E step 2 asserts `.env` survives.
- No CI smoke / no checksums / no auto-check on other verbs → nothing added anywhere (explicit non-goals).
- Docs (4 places) → Task 5. Acceptance 1/2/4/5 → Task 6 step 2 + Task 3 step 3; acceptance 3 (building window) covered by unit test + E2E caveat note.
