# Ubuntu amd64 install-path hardening (issue #409)

Status: approved 2026-07-02
Refs: #409 (this) · #408 (apt-update-first, already merged) · #395 (cloud-producer spike) ·
`docs/superpowers/specs/2026-07-02-cloud-producer-spike-runbook.md`

## Problem

The #395 cloud-producer spike ran the **amd64 Linux install path for the first time**
since pre-v1.0.0, on a fresh **GCP Ubuntu 24.04** VM. It works, but surfaced rough edges:

1. `install-tools` ran no `apt-get update` before `apt-get install` → "Unable to locate
   package". **Already fixed and merged (#408).** Out of scope here.
2. apt's `yt-dlp` lags upstream; a fresh box needs a **current** yt-dlp (plus deno on
   PATH) to pass YouTube's bot-check. apt's stale build would not.
3. No **minimum-OS gating**: deno 2.8.3 needs glibc ≥ 2.35 (Ubuntu 22.04+); the racecast
   **binary** needs glibc 2.38 (Ubuntu 24.04). Older boxes fail with a cryptic
   loader / "Unable to locate" error instead of a clear message.
4. `install-apps` on amd64 Ubuntu was **not exercised** (Stage 2). Needs validation on a
   real VM — **manual, not code**; tracked in #409, out of scope for this spec.

Root cause of "this went untested": the e2e harness **stubs** yt-dlp/streamlink/ffmpeg/deno,
so it can never assert the real install path produces **runnable** tools.

## Scope

**In:** code changes to `src/scripts/install_tools.py` and `src/scripts/preflight.py`, plus
a new maintainer tool `tools/test-install-container.py` with a unit-tested pure command
builder.

**Out:** finding (4) — the manual install-apps validation run on a real 24.04 VM
(OBS/Companion/Tailscale/Discord, OBS Browser Source PPA, NVENC). It requires a live box and
is a Stage-2 activity; #409 stays open for it (or is noted in the PR).

## Decisions (locked)

- **yt-dlp on Linux → pinned standalone binary download**, exactly like deno/speedtest
  (SHA-256 verified, into `runtime/bin`, refreshed by `racecast update` / `install-tools
  --update`). Not pip, not apt. Windows (winget) and macOS (brew) keep their package.
- **Min-OS → two thresholds:** `install-tools` **hard-fails** below glibc 2.35 (deno floor —
  tools literally won't run); `preflight` **warns** below 2.38 (binary floor) and **fails**
  below 2.35, using the existing FAIL/WARN/OK `Result` model.
- **Container test → maintainer Python tool now, opt-in CI later.** The pure command
  builder is unit-tested (runs in CI); the actual `docker/podman run` is network-heavy and
  stays opt-in.

## A. Current yt-dlp on Linux (`install_tools.py`)

Mirror `install_deno_binary` / `install_speedtest_binary`, but simpler — the yt-dlp release
asset is a **bare executable**, so there is no archive-extraction step.

New module constants:

```python
YTDLP_VERSION = "<latest stable at implementation>"   # e.g. 2025.xx.xx
YTDLP_BIN_NAME = "yt-dlp"
YTDLP_URL_TMPL = ("https://github.com/yt-dlp/yt-dlp/releases/download/"
                  "{ver}/yt-dlp_{tag}")
# tag -> sha256 of the official release asset, from that release's SHA2-256SUMS
YTDLP_DOWNLOADS = {
    "linux":          "<sha256 of yt-dlp_linux>",
    "linux_aarch64":  "<sha256 of yt-dlp_linux_aarch64>",
}
```

Pure helpers (unit-tested), matching the deno signatures:

- `ytdlp_asset_tag(platform, machine) -> "linux" | "linux_aarch64" | None`
  (`None` on Windows/macOS — their package managers ship yt-dlp — and on unsupported arches).
- `ytdlp_download_url(tag, ver=YTDLP_VERSION) -> str`.
- `install_ytdlp_binary(dest_dir, tag, opener=None, downloads=None) -> path`:
  download bytes → SHA-256 verify against the pinned value (raise `RuntimeError` "checksum
  mismatch" on mismatch) → write `dest_dir/yt-dlp` → `chmod 0o700`. `opener(url) -> bytes`
  injectable for tests; default `http_util.get_bytes(url, timeout=120)`.

`main()` wiring:

- **Remove `"yt-dlp"` from `APT_PACKAGES`** so the apt install/upgrade batch is only
  `streamlink` + `ffmpeg`. (This also makes `install_commands("apt", ["yt-dlp"]) == []`,
  same as deno today.)
- Add a yt-dlp direct-download block next to the deno block, running when
  `manager == "apt" and ("yt-dlp" in missing or a.update)` — so `--update` (the
  before-every-event path) refreshes yt-dlp to the pinned-current version. Best-effort:
  network/checksum/write errors append to `failed`, never crash (same contract as deno).
- The post-install re-check already uses `_which_with_managed_bin(managed_bin, brew)`, which
  looks in `runtime/bin`, so a yt-dlp landing there is found; `_ensure_tool_path` in
  `racecast.py` already puts `runtime/bin` on PATH for the spawned relay.
- Update the Linux branch of `manual_guide()`: yt-dlp is auto-downloaded now (like deno),
  drop the "apt-get install … yt-dlp" / pip note for it; keep streamlink + ffmpeg on apt.

Everything else (streamlink, ffmpeg via apt with the #408 `apt-get update` prefix; speedtest;
deno) is unchanged.

## B. Min-OS gate (`install_tools.py` + `preflight.py`)

Detection uses stdlib `platform.libc_ver()` (returns e.g. `('glibc', '2.39')`) — no ctypes.

Pure helpers (unit-tested):

- `glibc_version(libc_ver_output) -> (major, minor) | None`
  — parse the `(lib, version)` tuple; `None` when `lib` is not `glibc` (musl/unknown) or the
  version does not parse. `None` means "cannot tell → do not block".
- `min_os_error(libc_tuple, floor=MIN_GLIBC_TOOLS) -> str | None`
  — a clear multi-line message when `libc_tuple` is below `floor`, else `None`.

Constants: `MIN_GLIBC_TOOLS = (2, 35)`, `MIN_GLIBC_BINARY = (2, 38)`.

`install-tools` (`main()`): early, on Linux only, compute `glibc_version(platform.libc_ver())`;
if it is known and `< MIN_GLIBC_TOOLS`, `sys.exit(min_os_error(...))`. Message names the
concrete cause and fix, e.g.:

```
Unsupported OS: glibc 2.31 < 2.35.
deno requires glibc >= 2.35 (Ubuntu 22.04+); the racecast binary needs 2.38 (Ubuntu 24.04).
Use Ubuntu 24.04 LTS. Aborting.
```

`preflight` (`preflight.py`): new `classify_glibc(libc_tuple) -> Result` — **FAIL** below 2.35,
**WARN** below 2.38 (naming the 24.04/binary requirement), **OK** otherwise; **skip** (no row)
off Linux or when glibc is undeterminable. Wired into the Linux section of the report next to
the existing tool/hardware rows.

## C. Container install test (`tools/test-install-container.py`, maintainer-only)

Purpose: the reproducible check the stubbed e2e can't do — a real `ubuntu:24.04` container
runs the actual install path and asserts each tool is **runnable**.

Pure, unit-tested builder (in `tools/`, importable by the test):

- `build_container_command(engine, image, repo_dir, runtime_dir="/tmp/rc-rt") -> list[str]`
  → the `[engine, "run", "--rm", "-v", f"{repo_dir}:/repo", image, "bash", "-lc", SCRIPT]`
  argv, where `SCRIPT` is:
  1. `apt-get update && apt-get install -y python3 curl ca-certificates`
  2. `cd /repo && python3 src/racecast.py install-tools --runtime-dir <runtime_dir>`
     (root in the container ⇒ `geteuid()==0` ⇒ the apt steps take no `sudo` prefix, which is
     correct — there is no `sudo` binary in the base image)
  3. `export PATH=<runtime_dir>/bin:$PATH`
  4. assert `yt-dlp --version && deno --version && streamlink --version && ffmpeg -version`

Runner (`main()`, not in CI): pick `docker` or `podman` via `shutil.which`; if neither, print
a clear note and exit non-zero. Run the built command, stream output, exit with the container's
status. Network-heavy (real apt + GitHub downloads) → opt-in; a dedicated CI job is a
documented follow-up, not part of this PR.

New `tests/test_install_container.py`: asserts `build_container_command` shape — engine/image/
mount, the `--runtime-dir` flag threaded through, all four `--version` assertions present, and
that a `podman` engine is honoured. No Docker required (pure string check) → CI-safe.

## Testing

TDD, failing test first each step:

- `tests/test_install_tools.py`: `ytdlp_asset_tag` per os/arch; `ytdlp_download_url`;
  `install_ytdlp_binary` verify+extract and bad-checksum (fake bytes + injected opener);
  `install_commands("apt", ["yt-dlp"]) == []` (now a managed download, not apt);
  `glibc_version` parsing (glibc/musl/garbage); `min_os_error` below/at/above floor.
- `tests/test_preflight.py`: `classify_glibc` FAIL/WARN/OK/skip.
- `tests/test_install_container.py`: the command builder.

Local gates before the PR: `python3 tools/run-tests.py`, `python3 tools/lint.py`,
`python3 tools/build.py` (exit 0). One PR, conventional title
`feat(install): current yt-dlp binary + min-OS gate on Linux`, `Closes #409` (with a note that
the manual install-apps Stage-2 validation remains).

## Non-goals / YAGNI

- No pip path, no apt yt-dlp fallback — the pinned binary is the single Linux source.
- No auto-bump of `YTDLP_VERSION` — bumped by a maintainer like `DENO_VERSION`, refreshed on
  the box via `install-tools --update` / `racecast update`.
- No CI container job in this PR (opt-in follow-up).
- No install-apps code changes beyond the merged #408 apt-update.
