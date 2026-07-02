# Ubuntu amd64 install-path hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `racecast install-tools` produce a working feed toolchain on a fresh amd64 Ubuntu 24.04 box — a current yt-dlp (not apt's stale one), a clear min-OS error instead of a cryptic glibc failure, and a reproducible container test that asserts the tools are actually runnable.

**Architecture:** Add a pinned yt-dlp standalone-binary download on Linux (identical shape to the existing `install_deno_binary`), a two-threshold glibc gate (pure helpers used by both `install-tools` and `preflight`), and a maintainer `tools/` script whose `docker/podman run` argv is built by a pure, unit-tested function.

**Tech Stack:** Python stdlib only (`platform.libc_ver`, `hashlib`, `http_util`); no new dependencies. Tests are runnable scripts (no pytest).

## Global Constraints

- Edit only under `src/`, `tools/`, `tests/` (never `dist/`/`runtime/`). — CLAUDE.md
- English only; no machine paths / real IPs in committed files. — CLAUDE.md
- Python-only tooling — NO `.sh`/`.bat` (`tools/test-install-container.py` is Python that *invokes* docker/podman). — CLAUDE.md
- Outbound HTTP in `install_tools.py` goes through `http_util` (already imported there). — CLAUDE.md
- Tests must run on any machine and in CI (macOS + **Windows** + Linux): no Docker required by unit tests, no real IPs. Build fixed-OS paths with forward slashes, not `os.path.join`. — CLAUDE.md
- Pinned yt-dlp release for this change: **`2026.06.09`**
  - `yt-dlp_linux` sha256 = `bf8aac79b72287a6d2043074415132558b43743a8f9461a22b0141e90f16ce66`
  - `yt-dlp_linux_aarch64` sha256 = `cabd246445bdfde0eda0dfe68bbe90354be83f3fdbbf077df11a2ea55f41cdbd`
- glibc floors: `MIN_GLIBC_TOOLS = (2, 35)` (deno; install-tools hard-fails below), `MIN_GLIBC_BINARY = (2, 38)` (frozen binary; preflight warns below).
- Run after each task: `python3 tests/test_install_tools.py`, `python3 tests/test_preflight.py`, `python3 tests/test_install_container.py` (as they come into existence), then `python3 tools/lint.py`. Final gate: `python3 tools/run-tests.py` + `python3 tools/build.py` (exit 0).

---

## File structure

- Modify `src/scripts/install_tools.py` — add yt-dlp download constants + helpers + main() wiring; add glibc helpers + gate; drop `yt-dlp` from `APT_PACKAGES`; update `manual_guide`.
- Modify `src/scripts/preflight.py` — add `classify_glibc`; append its row on Linux.
- Create `tools/test-install-container.py` — pure `build_container_command` + maintainer runner.
- Modify `tests/test_install_tools.py` — yt-dlp + glibc unit tests.
- Modify `tests/test_preflight.py` — `classify_glibc` unit tests.
- Create `tests/test_install_container.py` — command-builder unit tests.

---

## Task 1: yt-dlp standalone binary download (pure helpers)

**Files:**
- Modify: `src/scripts/install_tools.py` (add constants + 3 helpers after the deno block, ~line 187)
- Test: `tests/test_install_tools.py`

**Interfaces:**
- Produces: `YTDLP_VERSION`, `YTDLP_BIN_NAME`, `YTDLP_URL_TMPL`, `YTDLP_DOWNLOADS`; `ytdlp_asset_tag(platform, machine) -> str|None`; `ytdlp_download_url(tag, ver=YTDLP_VERSION) -> str`; `install_ytdlp_binary(dest_dir, tag, opener=None, downloads=None) -> str` (path). Mirrors the deno trio.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_install_tools.py` (after the deno tests near the end, before `if __name__`):

```python
def t_ytdlp_asset_tag_per_os_arch():
    assert m.ytdlp_asset_tag("linux", "x86_64") == "linux"
    assert m.ytdlp_asset_tag("linux", "amd64") == "linux"
    assert m.ytdlp_asset_tag("linux", "aarch64") == "linux_aarch64"
    assert m.ytdlp_asset_tag("linux", "arm64") == "linux_aarch64"
    assert m.ytdlp_asset_tag("darwin", "arm64") is None     # brew ships yt-dlp
    assert m.ytdlp_asset_tag("win32", "AMD64") is None       # winget ships yt-dlp
    assert m.ytdlp_asset_tag("linux", "ppc64") is None       # unsupported arch


def t_ytdlp_download_url():
    url = m.ytdlp_download_url("linux")
    assert url == ("https://github.com/yt-dlp/yt-dlp/releases/download/"
                   f"{m.YTDLP_VERSION}/yt-dlp_linux")
    assert m.ytdlp_download_url("linux_aarch64").endswith("/yt-dlp_linux_aarch64")


def t_install_ytdlp_binary_verifies_and_writes():
    import hashlib, tempfile
    blob = b"#!/usr/bin/env python3\n# yt-dlp standalone\n"
    sha = hashlib.sha256(blob).hexdigest()
    d = tempfile.mkdtemp()
    path = m.install_ytdlp_binary(
        d, "linux", opener=lambda url: blob, downloads={"linux": sha})
    assert path == os.path.join(d, "yt-dlp")
    with open(path, "rb") as fh:
        assert fh.read() == blob
    if os.name != "nt":                          # the +x bit is POSIX-only
        import stat
        assert os.stat(path).st_mode & stat.S_IXUSR


def t_install_ytdlp_binary_rejects_bad_checksum():
    import tempfile
    try:
        m.install_ytdlp_binary(
            tempfile.mkdtemp(), "linux",
            opener=lambda url: b"x", downloads={"linux": "deadbeef"})
    except RuntimeError as exc:
        assert "checksum mismatch" in str(exc)
        return
    raise AssertionError("expected a checksum-mismatch RuntimeError")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_install_tools.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'ytdlp_asset_tag'`.

- [ ] **Step 3: Implement the constants + helpers**

In `src/scripts/install_tools.py`, immediately after the `install_deno_binary` function (before `def pick_manager`), add:

```python
# yt-dlp on Linux: apt's package lags upstream badly and cannot pass YouTube's
# current bot-check. So — like deno — Linux gets a pinned, SHA-256-verified
# standalone binary straight from yt-dlp's GitHub releases, into the managed bin
# dir. The release asset is a BARE executable (no archive), so there is no
# extraction step. Windows (winget) and macOS (brew) keep their yt-dlp package.
YTDLP_VERSION = "2026.06.09"
YTDLP_BIN_NAME = "yt-dlp"
YTDLP_URL_TMPL = ("https://github.com/yt-dlp/yt-dlp/releases/download/"
                  "{ver}/yt-dlp_{tag}")
# tag -> sha256 of the official release asset (from the release's SHA2-256SUMS).
YTDLP_DOWNLOADS = {
    "linux":         "bf8aac79b72287a6d2043074415132558b43743a8f9461a22b0141e90f16ce66",
    "linux_aarch64": "cabd246445bdfde0eda0dfe68bbe90354be83f3fdbbf077df11a2ea55f41cdbd",
}


def ytdlp_asset_tag(platform, machine):
    """Map (sys.platform, platform.machine()) -> a YTDLP_DOWNLOADS tag, or None for
    Windows/macOS (their package managers ship yt-dlp) and unsupported arches. Pure."""
    if platform.startswith("linux"):
        m = (machine or "").lower()
        if m in ("x86_64", "amd64"):
            return "linux"
        if m in ("aarch64", "arm64"):
            return "linux_aarch64"
    return None


def ytdlp_download_url(tag, ver=YTDLP_VERSION):
    return YTDLP_URL_TMPL.format(ver=ver, tag=tag)


def install_ytdlp_binary(dest_dir, tag, opener=None, downloads=None):
    """Download yt-dlp's standalone Linux binary for `tag`, verify its SHA-256
    against the pinned value, write it to dest_dir/yt-dlp, and make it executable.
    Returns the binary path. Raises on a checksum mismatch. The asset is a bare
    executable (no archive) — simpler than install_deno_binary. `opener` (url ->
    bytes) is injectable for tests; defaults to a stdlib HTTPS GET."""
    import hashlib
    downloads = downloads or YTDLP_DOWNLOADS
    want = downloads[tag]
    if opener is None:
        def opener(url):
            return http_util.get_bytes(url, timeout=120)   # nosec - pinned GitHub host, checksum-verified
    blob = opener(ytdlp_download_url(tag))
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError(
            f"yt-dlp download checksum mismatch for {tag}: {got} != {want}")
    os.makedirs(dest_dir, exist_ok=True)
    binpath = os.path.join(dest_dir, YTDLP_BIN_NAME)
    with open(binpath, "wb") as out:
        out.write(blob)
    os.chmod(binpath, 0o700)   # owner rwx only — racecast runs the binary as the producer
    return binpath
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_tools.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_tools.py tests/test_install_tools.py
git commit -m "feat(install): pinned yt-dlp standalone binary download helpers (#409)"
```

---

## Task 2: Drop yt-dlp from apt; wire the download into main()

**Files:**
- Modify: `src/scripts/install_tools.py` (`APT_PACKAGES` ~line 29; the deno block in `main()` ~line 411; `manual_guide` ~line 273)
- Test: `tests/test_install_tools.py`

**Interfaces:**
- Consumes: `install_ytdlp_binary`, `ytdlp_asset_tag` (Task 1).
- Produces: `install_commands("apt", ["yt-dlp"]) == []` (yt-dlp no longer an apt package); a yt-dlp download step in `main()` running when `"yt-dlp" in missing or a.update`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_install_tools.py`, update the apt tests to reflect yt-dlp leaving apt. Replace the body of `t_install_commands_apt_updates_then_skips_deno` and add a yt-dlp assertion:

```python
def t_install_commands_apt_updates_then_skips_managed():
    # apt handles ONLY streamlink + ffmpeg now. yt-dlp (bot-check-sensitive) and
    # deno are pinned managed downloads, not apt packages (#409).
    cmds = m.install_commands("apt", ["yt-dlp", "streamlink", "deno"])
    assert cmds == [["apt-get", "update"], ["apt-get", "install", "-y", "streamlink"]]
    assert m.install_commands("apt", ["yt-dlp"]) == []
    assert m.install_commands("apt", ["deno"]) == []
    assert "yt-dlp" not in m.APT_PACKAGES
```

Delete the now-superseded `t_install_commands_apt_updates_then_skips_deno` (its name/assertions are replaced above). Also update `t_install_commands_apt_sudo_prefix` — its first assertion used `yt-dlp`; change the sample apt package to `streamlink`:

```python
def t_install_commands_apt_sudo_prefix():
    # apt path = update then install; both get the sudo prefix (Linux non-root)
    assert m.install_commands("apt", ["streamlink"]) == \
        [["apt-get", "update"], ["apt-get", "install", "-y", "streamlink"]]
    assert m.install_commands("apt", ["streamlink", "ffmpeg"], sudo=True) == \
        [["sudo", "apt-get", "update"],
         ["sudo", "apt-get", "install", "-y", "streamlink", "ffmpeg"]]
    assert m.install_commands("brew", ["ffmpeg"], sudo=True) == [["brew", "install", "ffmpeg"]]
    assert m.install_commands("winget", ["deno"], sudo=True)[0][0] == "winget"
    assert m.install_commands("apt", ["deno"], sudo=True) == []   # deno has no apt pkg
```

And `t_update_commands_apt_only_upgrade_skips_deno` + `t_update_commands_apt_sudo_prefix` used `yt-dlp`; switch their sample to `streamlink`:

```python
def t_update_commands_apt_only_upgrade_skips_managed():
    cmds = m.update_commands("apt", ["streamlink", "deno", "yt-dlp"])
    assert cmds == [["apt-get", "update"],
                    ["apt-get", "install", "-y", "--only-upgrade", "streamlink"]]
    assert m.update_commands("apt", ["deno"]) == []
    assert m.update_commands("apt", ["yt-dlp"]) == []


def t_update_commands_apt_sudo_prefix():
    assert m.update_commands("apt", ["streamlink"], sudo=True) == \
        [["sudo", "apt-get", "update"],
         ["sudo", "apt-get", "install", "-y", "--only-upgrade", "streamlink"]]
    assert m.update_commands("apt", ["streamlink"]) == \
        [["apt-get", "update"],
         ["apt-get", "install", "-y", "--only-upgrade", "streamlink"]]
```

(Delete the old `t_update_commands_apt_only_upgrade_skips_deno`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_install_tools.py`
Expected: FAIL — `yt-dlp` still in `APT_PACKAGES`, so the apt command still contains it.

- [ ] **Step 3: Implement — drop yt-dlp from apt, wire the download**

Edit `APT_PACKAGES` (remove the yt-dlp entry):

```python
APT_PACKAGES = {"streamlink": "streamlink", "ffmpeg": "ffmpeg"}
# deno and yt-dlp ship no usable apt package — Linux gets pinned managed
# downloads (see install_deno_binary / install_ytdlp_binary).
```

In `main()`, immediately after the deno download block (the `if manager == "apt" and "deno" in missing:` block, ~line 411-423), add the yt-dlp block:

```python
    # yt-dlp on Linux: current pinned binary, not apt (apt's lags upstream and
    # fails YouTube's bot-check). Refreshed on --update too, so the before-event
    # `install-tools --update` bumps it to the pinned-current version (#409).
    if manager == "apt" and ("yt-dlp" in missing or a.update):
        tag = ytdlp_asset_tag(sys.platform, _platform.machine())
        if tag is None:
            print("NOTE: no prebuilt yt-dlp for this OS/arch — install it manually:")
            print("  https://github.com/yt-dlp/yt-dlp#installation")
        else:
            dest = st.managed_bin_dir(runtime_dir)
            print(f"Installing yt-dlp v{YTDLP_VERSION} -> {dest} ...")
            try:
                install_ytdlp_binary(dest, tag)
                print("  yt-dlp installed.")
            except Exception as exc:   # network/checksum/write — report, don't crash
                failed.append(f"yt-dlp download ({exc})")
```

Update the Linux branch of `manual_guide()` — yt-dlp is auto-downloaded now:

```python
    return ("Install manually:  sudo apt-get update && sudo apt-get install -y streamlink ffmpeg\n"
            "yt-dlp and deno have no usable apt package — install-tools downloads them\n"
            "automatically (pinned, checksum-verified). Manually:\n"
            "  yt-dlp: https://github.com/yt-dlp/yt-dlp#installation\n"
            "  deno:   https://docs.deno.com/runtime/getting_started/installation/\n"
            "bandwidth speed test (Ookla CLI): download the Linux build from\n"
            "  https://www.speedtest.net/apps/cli and put `speedtest` on your PATH")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_tools.py`
Expected: `ALL PASS`. Also confirm the manual-guide test still holds:
`python3 -c "import sys; sys.path.insert(0,'tests'); import test_install_tools as t; t.t_manual_guide_mentions_deno_on_linux()"`
Expected: no error (the guide still mentions deno).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_tools.py tests/test_install_tools.py
git commit -m "feat(install): install yt-dlp via pinned binary on Linux, not apt (#409)"
```

---

## Task 3: glibc detection + min-OS gate (install-tools)

**Files:**
- Modify: `src/scripts/install_tools.py` (constants near the top ~line 25; helpers near `pick_manager`; gate at the top of `main()`)
- Test: `tests/test_install_tools.py`

**Interfaces:**
- Produces: `MIN_GLIBC_TOOLS = (2, 35)`, `MIN_GLIBC_BINARY = (2, 38)`; `glibc_version(libc_ver_output) -> tuple[int,int]|None`; `min_os_error(libc_tuple, floor=MIN_GLIBC_TOOLS) -> str|None`.
- Consumed by Task 4 (`preflight` imports nothing from here — it defines its own `classify_glibc`; the floors live in `install_tools`, so `preflight` hard-codes the same two constants with a comment cross-referencing this module).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_install_tools.py`:

```python
def t_glibc_version_parses_glibc_only():
    assert m.glibc_version(("glibc", "2.39")) == (2, 39)
    assert m.glibc_version(("glibc", "2.35")) == (2, 35)
    # non-glibc (musl / undeterminable) -> None ("cannot tell, do not block")
    assert m.glibc_version(("", "")) is None
    assert m.glibc_version(("musl", "1.2.4")) is None
    assert m.glibc_version(("glibc", "")) is None
    assert m.glibc_version(("glibc", "garbage")) is None


def t_min_os_error_below_at_above_floor():
    # below the deno floor -> a clear, actionable message
    msg = m.min_os_error((2, 31))
    assert msg is not None
    assert "2.31" in msg and "2.35" in msg and "24.04" in msg
    # at/above the floor -> None (no error)
    assert m.min_os_error((2, 35)) is None
    assert m.min_os_error((2, 39)) is None
    # undeterminable glibc must never block
    assert m.min_os_error(None) is None
    assert m.MIN_GLIBC_TOOLS == (2, 35) and m.MIN_GLIBC_BINARY == (2, 38)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_install_tools.py`
Expected: FAIL — `has no attribute 'glibc_version'`.

- [ ] **Step 3: Implement the helpers + the gate**

Add near the other module constants (after `TOOLS = (...)`, ~line 25):

```python
# Minimum glibc: deno needs >= 2.35 (Ubuntu 22.04+) to run at all, so install-tools
# hard-fails below it; the frozen racecast binary needs 2.38 (Ubuntu 24.04), which
# preflight warns about. Two real failure points, one clear story (#409).
MIN_GLIBC_TOOLS = (2, 35)
MIN_GLIBC_BINARY = (2, 38)
```

Add the pure helpers just above `def pick_manager`:

```python
def glibc_version(libc_ver_output):
    """Parse platform.libc_ver()'s (lib, version) tuple into a (major, minor)
    int pair, or None when the C library is not glibc (musl/unknown) or the
    version does not parse. None means 'cannot tell' -> callers must not block."""
    lib, ver = (libc_ver_output or ("", ""))
    if lib != "glibc" or not ver:
        return None
    parts = ver.split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return None


def min_os_error(libc_tuple, floor=MIN_GLIBC_TOOLS):
    """A clear multi-line 'unsupported OS' message when `libc_tuple` is below
    `floor`, else None. None `libc_tuple` (undeterminable) -> None (never block)."""
    if libc_tuple is None or libc_tuple >= floor:
        return None
    have = f"{libc_tuple[0]}.{libc_tuple[1]}"
    need = f"{floor[0]}.{floor[1]}"
    return (f"Unsupported OS: glibc {have} < {need}.\n"
            "deno requires glibc >= 2.35 (Ubuntu 22.04+); the racecast binary needs "
            "2.38 (Ubuntu 24.04).\nUse Ubuntu 24.04 LTS. Aborting.")
```

At the very top of `main()`, right after `a = ap.parse_args()` and the `import platform as _platform` line (move/ensure `_platform` is imported before the gate), add the gate:

```python
    # Fail fast on an OS too old to run the toolchain (deno's glibc floor) — a
    # clear message beats a cryptic loader error mid-download (#409).
    if sys.platform.startswith("linux"):
        err = min_os_error(glibc_version(_platform.libc_ver()))
        if err:
            sys.exit(err)
```

Note: `_platform` is currently imported a few lines into `main()`; ensure the `import platform as _platform` appears BEFORE this gate (move that import up to the first line of `main()` if needed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_tools.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_tools.py tests/test_install_tools.py
git commit -m "feat(install): fail-fast glibc min-OS gate in install-tools (#409)"
```

---

## Task 4: glibc row in preflight

**Files:**
- Modify: `src/scripts/preflight.py` (add `classify_glibc` near `classify_pipewire_audio` ~line 416; append its row in `gather()` ~line 484)
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: nothing from Task 3 at runtime (defines its own thresholds with a comment cross-referencing `install_tools`).
- Produces: `classify_glibc(libc_tuple) -> Result|None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_preflight.py`:

```python
def t_classify_glibc_levels():
    assert m.classify_glibc((2, 31)).level == "FAIL"   # below deno floor
    assert m.classify_glibc((2, 35)).level == "WARN"   # runs; below binary floor
    assert m.classify_glibc((2, 37)).level == "WARN"
    assert m.classify_glibc((2, 38)).level == "PASS"   # Ubuntu 24.04
    assert m.classify_glibc((2, 39)).level == "PASS"
    # undeterminable glibc (musl/unknown) -> no row
    assert m.classify_glibc(None) is None
    # FAIL/WARN detail names the concrete requirement
    assert "2.35" in m.classify_glibc((2, 31)).detail
    assert "24.04" in m.classify_glibc((2, 35)).detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `has no attribute 'classify_glibc'`.

- [ ] **Step 3: Implement `classify_glibc` + wire the row**

Add just after `classify_pipewire_audio` (~line 427):

```python
# glibc floors mirror install_tools.MIN_GLIBC_TOOLS / MIN_GLIBC_BINARY (kept in
# sync deliberately — preflight must not import the installer module).
PF_MIN_GLIBC_TOOLS = (2, 35)
PF_MIN_GLIBC_BINARY = (2, 38)


def classify_glibc(libc_tuple):
    """Linux glibc gate. FAIL below 2.35 (deno won't run), WARN below 2.38 (the
    racecast binary needs Ubuntu 24.04), else PASS. None (undeterminable / non-glibc)
    -> None (no row)."""
    if libc_tuple is None:
        return None
    have = f"{libc_tuple[0]}.{libc_tuple[1]}"
    if libc_tuple < PF_MIN_GLIBC_TOOLS:
        return Result(FAIL, "glibc", f"{have} — below 2.35; deno/the toolchain "
                      "won't run. Use Ubuntu 24.04 LTS.")
    if libc_tuple < PF_MIN_GLIBC_BINARY:
        return Result(WARN, "glibc", f"{have} — works from source; the racecast "
                      "binary needs 2.38 (Ubuntu 24.04).")
    return Result(PASS, "glibc", have)
```

In `gather()`, right after the `tools.append(... python3 ...)` block (~line 484), append the glibc row on Linux:

```python
    if sys.platform.startswith("linux"):   # OS floor (deno glibc 2.35 / binary 2.38)
        try:
            import platform as _pf
            import install_tools as _it
            g = classify_glibc(_it.glibc_version(_pf.libc_ver()))
            if g is not None:
                tools.append(g)
        except Exception:
            pass  # never let the glibc probe break the report
```

`platform` is NOT imported at module level in `preflight.py`, so import it locally
inside the try (as shown). Reuse `install_tools.glibc_version` (the single parser) —
`install_tools` is already importable on `sys.path` in every context preflight runs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_preflight.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): glibc min-OS row (FAIL 2.35 / WARN 2.38) (#409)"
```

---

## Task 5: container install test (pure builder + maintainer runner)

**Files:**
- Create: `tools/test-install-container.py`
- Create: `tests/test_install_container.py`

**Interfaces:**
- Produces: `build_container_command(engine, image, repo_dir, runtime_dir="/tmp/rc-rt") -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_install_container.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the container install-test command builder. No Docker required.
Run: python3 tests/test_install_container.py"""
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "tic", os.path.join(ROOT, "tools", "test-install-container.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_build_command_shape():
    cmd = m.build_container_command("docker", "ubuntu:24.04", "/repo", "/tmp/rt")
    assert cmd[:4] == ["docker", "run", "--rm", "-v"]
    assert "/repo:/repo" in cmd
    assert "ubuntu:24.04" in cmd
    assert cmd[-3] == "bash" and cmd[-2] == "-lc"
    script = cmd[-1]
    # runs the REAL install path from source, into the isolated runtime dir
    assert "python3 src/racecast.py install-tools --runtime-dir /tmp/rt" in script
    assert "/tmp/rt/bin" in script            # managed bin on PATH for the asserts
    # asserts every tool is actually runnable
    for probe in ("yt-dlp --version", "deno --version",
                  "streamlink --version", "ffmpeg -version"):
        assert probe in script, probe
    # bootstraps python3 in the base image
    assert "apt-get install -y python3" in script


def t_build_command_honours_podman():
    cmd = m.build_container_command("podman", "ubuntu:24.04", "/x")
    assert cmd[0] == "podman"
    assert "/x:/repo" in cmd
    assert "/tmp/rc-rt" in cmd[-1]            # default runtime dir


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_install_container.py`
Expected: FAIL — `No such file or directory: tools/test-install-container.py`.

- [ ] **Step 3: Create the tool**

Create `tools/test-install-container.py`:

```python
#!/usr/bin/env python3
"""Maintainer tool: run the REAL `racecast install-tools` path inside a fresh
`ubuntu:24.04` container and assert every feed tool ends up runnable. This is the
check the e2e harness cannot do — it stubs the tools; here they are really
downloaded/installed and probed with `<tool> --version`.

Network-heavy (real apt + GitHub downloads) and needs Docker or Podman, so it is
opt-in and NOT part of CI. The command builder below is pure and unit-tested
(tests/test_install_container.py); only main() touches Docker."""
import os
import shutil
import subprocess
import sys

IMAGE = "ubuntu:24.04"


def build_container_command(engine, image, repo_dir, runtime_dir="/tmp/rc-rt"):
    """The `<engine> run` argv that installs the toolchain from source inside the
    container and asserts each tool is runnable. Pure — no Docker touched here.
    Root in the container => install-tools' apt steps take no sudo (correct: the
    base image has no sudo binary), and yt-dlp/deno land in <runtime_dir>/bin."""
    script = (
        "set -euo pipefail; "
        "apt-get update && apt-get install -y python3 curl ca-certificates; "
        f"cd /repo && python3 src/racecast.py install-tools --runtime-dir {runtime_dir}; "
        f"export PATH={runtime_dir}/bin:$PATH; "
        "yt-dlp --version && deno --version && "
        "streamlink --version && ffmpeg -version"
    )
    return [engine, "run", "--rm", "-v", f"{repo_dir}:/repo", image,
            "bash", "-lc", script]


def _pick_engine(which=shutil.which):
    for engine in ("docker", "podman"):
        if which(engine):
            return engine
    return None


def main():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    engine = _pick_engine()
    if engine is None:
        sys.exit("Needs Docker or Podman on PATH — neither found.")
    cmd = build_container_command(engine, IMAGE, repo_dir)
    print("Running:", " ".join(cmd[:6]), "...")
    rc = subprocess.call(cmd)
    if rc == 0:
        print("PASS: all tools installed and runnable in", IMAGE)
    else:
        print("FAIL: container install test exited", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_install_container.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add tools/test-install-container.py tests/test_install_container.py
git commit -m "test(install): container install-path test with unit-tested builder (#409)"
```

---

## Task 6: full local gates + lint

**Files:** none (verification only).

- [ ] **Step 1: Lint**

Run: `python3 tools/lint.py`
Expected: `All checks passed!` (fix anything it flags, e.g. an unused import from the `_platform` move in Task 3).

- [ ] **Step 2: Full suite**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS`.

- [ ] **Step 3: Build (CI mirror)**

Run: `python3 tools/build.py`
Expected: exit 0; verify step reports `install-tools shipped`.

- [ ] **Step 4: Sanity — the new tool ships or is correctly excluded**

Run: `python3 -c "import ast; ast.parse(open('tools/test-install-container.py').read()); print('ok')"`
Expected: `ok` (tools/ is maintainer-only, not shipped — build.py already excludes it; this just confirms the file parses).

No commit (verification only).

---

## Self-review notes

- **Spec coverage:** A. yt-dlp binary → Tasks 1–2. B. min-OS gate → Task 3 (install-tools) + Task 4 (preflight). C. container test → Task 5. Testing → tests folded into each task + Task 6 gates. Out-of-scope install-apps validation is intentionally excluded (manual Stage-2).
- **Placeholder scan:** yt-dlp version + both SHA-256 values are concrete (pinned `2026.06.09`). No TBD/TODO.
- **Type consistency:** helper names match across tasks (`ytdlp_asset_tag`, `install_ytdlp_binary`, `glibc_version`, `min_os_error`, `classify_glibc`, `build_container_command`); `glibc_version` is defined once in `install_tools` and reused by preflight.
- **Known follow-ups (not this PR):** opt-in CI job that runs `tools/test-install-container.py`; manual install-apps Stage-2 validation on a real 24.04 VM. Note both in the PR body so #409 stays open for them.
