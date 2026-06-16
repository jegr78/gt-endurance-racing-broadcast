# Discord-web Audio Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On Linux hosts without native Discord (notably ARM64), capture end-of-race interview audio from Discord-web in a browser by retargeting the existing OBS PipeWire application-capture source to the browser process.

**Architecture:** A new pure helper module (`src/scripts/discord_web.py`) decides — from a machine `.env` override or auto-detection of a native Discord install — whether to use the browser variant and which browser to target. `src/setup-assets.py` gains a "linux web" form of the existing Discord audio source (same `pipewire_audio_application_capture` type and UUID, only `TargetName` changes — so the panel/Companion mute & volume bindings stay intact). `event.py` and `preflight.py` swap their "Discord missing/not running" warning for an informational note on web-variant hosts. No auto-launch, no Browser Source widget, no league config.

**Tech Stack:** Python 3 stdlib only; no pytest (each `tests/test_*.py` is a runnable script); OBS scene-collection JSON; `obs-pipewire-audio-capture` plugin (the existing Linux requirement).

**Spec:** `docs/superpowers/specs/2026-06-15-discord-web-audio-fallback-design.md`

---

## File Structure

- **Create** `src/scripts/discord_web.py` — pure decision/detection: `use_web()`, `native_installed()`, `resolve_browser()`, `detect_running_browser()`. Stdlib-only, importable normally by other `scripts/` modules; loaded by `setup-assets.py` via a `sys.path` insert of the `scripts/` dir.
- **Create** `tests/test_discord_web.py` — unit tests for the above (dependency-injected, no real `pgrep`/filesystem).
- **Modify** `src/setup-assets.py` — `discord_variant()`/`localize_discord_audio()` gain `web`/`browser` params; `main()` resolves the decision and reports it.
- **Modify** `tests/test_discord_audio.py` — web-variant shape + the new params keep old behaviour.
- **Modify** `src/scripts/event.py` (`classify_app`) + `src/racecast.py` (`_event_sections` caller) — web-aware Discord status line.
- **Modify** `tests/test_event.py` — web-variant classification.
- **Modify** `src/scripts/preflight.py` (`apps_section` + `gather`) — web-aware Discord install line.
- **Modify** `tests/test_preflight.py` — web-variant apps line.
- **Modify** `.env.example`, `src/docs/wiki/OBS-Setup.md`, `src/docs/wiki/If-something-goes-wrong.md`, `CLAUDE.md` — document the two `.env` knobs + the manual browser/voice step + register the new test.
- **No change** to `src/scripts/install_apps.py` — it already emits `DISCORD_NO_ARM64_NOTE` ("no official ARM64 Linux .deb … Use the web app … or a browser") and soft-skips the install on ARM64, which already satisfies the spec's install-time guidance. Its `_LINUX_APP_PATHS["discord"]` presence markers are mirrored by `discord_web._LINUX_DISCORD_PATHS` (keep the two in sync if either moves).

---

## Task 1: `discord_web` decision/detection module

**Files:**
- Create: `src/scripts/discord_web.py`
- Test: `tests/test_discord_web.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discord_web.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the Discord-web/browser capture decision helpers.
Run: python3 tests/test_discord_web.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, *rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dw = _load("discord_web", "src", "scripts", "discord_web.py")

NONE = lambda app=None: False  # noqa: E731


def t_use_web_override_wins():
    # 1/true/on -> web even on a non-Linux platform; 0/off -> never web even on Linux.
    for val in ("1", "true", "on", "YES"):
        assert dw.use_web("darwin", {"RACECAST_DISCORD_WEB": val}) is True
    for val in ("0", "false", "off", "no"):
        assert dw.use_web("linux", {"RACECAST_DISCORD_WEB": val},
                          native_installed_fn=lambda p: False) is False


def t_use_web_auto_linux_depends_on_native():
    # auto (no override): Linux + no native Discord -> web; Linux + native -> not web.
    assert dw.use_web("linux", {}, native_installed_fn=lambda p: False) is True
    assert dw.use_web("linux", {}, native_installed_fn=lambda p: True) is False


def t_use_web_non_linux_never_auto():
    assert dw.use_web("darwin", {}, native_installed_fn=lambda p: False) is False
    assert dw.use_web("win32", {}, native_installed_fn=lambda p: False) is False


def t_native_installed_non_linux_true():
    assert dw.native_installed("darwin") is True
    assert dw.native_installed("win32") is True


def t_native_installed_linux_probes_path_and_binary():
    # binary on PATH -> True
    assert dw.native_installed("linux", which=lambda n: "/usr/bin/discord"
                               if n == "discord" else None,
                               exists=lambda p: False) is True
    # no binary, but a known install path exists -> True
    assert dw.native_installed("linux", which=lambda n: None,
                               exists=lambda p: p == "/usr/share/discord") is True
    # neither -> False (the ARM64 case)
    assert dw.native_installed("linux", which=lambda n: None,
                               exists=lambda p: False) is False


def t_resolve_browser_override_then_running_then_default():
    assert dw.resolve_browser({"RACECAST_DISCORD_WEB_BROWSER": "Chromium"}) == "Chromium"
    assert dw.resolve_browser({}, running="Firefox") == "Firefox"
    assert dw.resolve_browser({}) == dw.DEFAULT_BROWSER == "Firefox"


def t_detect_running_browser_matches_first_hit():
    class R:
        def __init__(self, rc): self.returncode = rc
    # firefox running -> "Firefox"
    assert dw.detect_running_browser(
        run=lambda argv, **kw: R(0 if argv[-1] == "firefox" else 1)) == "Firefox"
    # nothing running -> None
    assert dw.detect_running_browser(run=lambda argv, **kw: R(1)) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_discord_web.py`
Expected: FAIL — `No such file or directory` / `ModuleNotFoundError` for `src/scripts/discord_web.py`.

- [ ] **Step 3: Write minimal implementation**

Create `src/scripts/discord_web.py`:

```python
#!/usr/bin/env python3
"""Decide when interview audio comes from Discord-web in a browser instead of a
native Discord client, and which browser process the OBS capture targets.

Native Discord is unavailable on some Linux hosts (notably ARM64 — the official
.deb is amd64-only). There the OBS "Discord Audio Capture" source is retargeted
to the browser running Discord-web. The source TYPE is unchanged
(pipewire_audio_application_capture), so the panel/Companion mute & volume
bindings keep working — only the capture target differs.

Pure, stdlib-only, unit-tested (tests/test_discord_web.py)."""
import os
import shutil
import subprocess
import sys

# Native Discord install markers on Linux (mirror install_apps._LINUX_APP_PATHS).
_LINUX_DISCORD_PATHS = ("/usr/share/discord", "/usr/bin/discord")
# Browser process name -> the pipewire_audio_application_capture TargetName to
# emit, tried in order when auto-detecting a running browser.
_BROWSER_PROBES = (("firefox", "Firefox"), ("chromium", "Chromium"),
                   ("chrome", "Google Chrome"))
DEFAULT_BROWSER = "Firefox"

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def native_installed(platform=None, which=shutil.which, exists=os.path.exists):
    """True iff a native Discord client is present. Non-Linux platforms always
    have native Discord (the web fallback is Linux-only) -> True. Linux: a
    discord binary on PATH or a known install path."""
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return True
    if which("discord") or which("Discord"):
        return True
    return any(exists(p) for p in _LINUX_DISCORD_PATHS)


def use_web(platform, env, native_installed_fn=native_installed):
    """Whether to use the Discord-web/browser capture variant. Precedence:
    RACECAST_DISCORD_WEB override (1 -> True, 0 -> False) > auto (Linux AND no
    native Discord). Non-Linux is never web under auto."""
    override = (env.get("RACECAST_DISCORD_WEB") or "").strip().lower()
    if override in _TRUE:
        return True
    if override in _FALSE:
        return False
    if not platform.startswith("linux"):
        return False
    return not native_installed_fn(platform)


def detect_running_browser(run=subprocess.run):
    """The TargetName of a running browser (Firefox/Chromium/Chrome), or None.
    Best-effort `pgrep -x`; any failure -> None."""
    for proc, target in _BROWSER_PROBES:
        try:
            out = run(["pgrep", "-x", proc], capture_output=True, text=True,
                      timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            return target
    return None


def resolve_browser(env, running=None):
    """pipewire TargetName for the Discord-web browser: explicit
    RACECAST_DISCORD_WEB_BROWSER > a detected running browser > DEFAULT_BROWSER."""
    override = (env.get("RACECAST_DISCORD_WEB_BROWSER") or "").strip()
    if override:
        return override
    return running or DEFAULT_BROWSER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_discord_web.py`
Expected: PASS — prints `ok t_...` for each and `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/discord_web.py tests/test_discord_web.py
git commit -m "feat(discord): web/browser capture decision helpers"
```

---

## Task 2: "Linux web" OBS audio variant in setup-assets

**Files:**
- Modify: `src/setup-assets.py:52-77` (`discord_variant`, `localize_discord_audio`), `:200` (`main()` call), `:216-221` (reporting), plus a `sys.path`/import near the top of the module.
- Test: `tests/test_discord_audio.py`

- [ ] **Step 1: Write the failing test**

Add these to `tests/test_discord_audio.py` (after `t_localize_linux_uses_pipewire_plugin`):

```python
def t_variant_linux_web_targets_browser():
    src_id, settings = sa.discord_variant("linux", web=True, browser="Firefox")
    assert src_id == "pipewire_audio_application_capture"
    assert settings == {"TargetName": "Firefox", "MatchPriorty": 0}
    # web flag only affects Linux; macOS/Windows ignore it.
    assert sa.discord_variant("darwin", web=True)[0] == "sck_audio_capture"
    assert sa.discord_variant("win32", web=True)[0] == "wasapi_process_output_capture"


def t_localize_linux_web_swaps_targetname():
    c = coll()
    assert sa.localize_discord_audio(c, "linux", web=True, browser="Chromium") \
        == "pipewire_audio_application_capture"
    s = c["sources"][0]
    assert s["id"] == s["versioned_id"] == "pipewire_audio_application_capture"
    assert s["settings"] == {"TargetName": "Chromium", "MatchPriorty": 0}


def t_localize_linux_web_default_off_is_native():
    # web defaults False -> the existing native behaviour is unchanged.
    c = coll()
    sa.localize_discord_audio(c, "linux")
    assert c["sources"][0]["settings"] == {"TargetName": "Discord", "MatchPriorty": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_discord_audio.py`
Expected: FAIL — `discord_variant()` got an unexpected keyword argument `web`.

- [ ] **Step 3: Write minimal implementation**

In `src/setup-assets.py`, replace `discord_variant` and `localize_discord_audio` (currently lines 52-77) with:

```python
def discord_variant(platform, web=False, browser="Firefox"):
    """(source id, settings) for this platform, or None when unknown.
    On Linux with web=True, target the browser running Discord-web instead of a
    native Discord process — same pipewire source type, only TargetName differs,
    so the panel/Companion mute & volume bindings stay intact."""
    if platform.startswith("win"):
        return DISCORD_AUDIO_VARIANTS["win"]
    if platform == "darwin":
        return DISCORD_AUDIO_VARIANTS["darwin"]
    if platform.startswith("linux"):
        if web:
            return ("pipewire_audio_application_capture",
                    {"TargetName": browser, "MatchPriorty": 0})
        return DISCORD_AUDIO_VARIANTS["linux"]
    return None


def localize_discord_audio(collection, platform, web=False, browser="Firefox"):
    """Swap the Discord audio source to this platform's variant, in place.
    Returns the new source id, or None (source absent / unknown platform —
    never fails, same contract as the missing-graphics warnings)."""
    variant = discord_variant(platform, web=web, browser=browser)
    if variant is None:
        return None
    src_id, settings = variant
    for s in collection.get("sources", []):
        if s.get("uuid") == DISCORD_AUDIO_UUID:
            s["id"] = src_id
            s["versioned_id"] = src_id
            s["settings"] = dict(settings)
            return src_id
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_discord_audio.py`
Expected: PASS (`ALL PASS`).

- [ ] **Step 5: Wire the decision into `main()`**

Near the top of `src/setup-assets.py`, after the existing imports (the file currently imports `argparse, json, os, re, sys`), add the sibling-module load so `main()` can resolve the decision. Insert right before `def graphics_dir(base):` (after the import lines, around line 23):

```python
# Load the sibling decision helper (scripts/ sits next to this script in both
# the repo and the package). setup-assets stays config.py-free, but discord_web
# is a tiny pure stdlib helper — importing it does not pull in the heavy resolver.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import discord_web  # noqa: E402
```

Then in `main()`, replace the single localize call (currently line 200):

```python
    swapped = localize_discord_audio(localized, sys.platform)
```

with:

```python
    web = discord_web.use_web(sys.platform, os.environ)
    browser = discord_web.resolve_browser(os.environ,
                                          discord_web.detect_running_browser())
    swapped = localize_discord_audio(localized, sys.platform, web=web, browser=browser)
```

And extend the reporting block (currently lines 216-221) to mention the browser target. Replace:

```python
    if swapped:
        print(f"  Discord audio source: {swapped}")
```

with:

```python
    if swapped:
        print(f"  Discord audio source: {swapped}")
        if web:
            print(f"  Discord interview audio: capturing browser '{browser}' "
                  "(Discord-web) — open it and join the voice channel manually")
```

- [ ] **Step 6: Run the Discord-audio tests again**

Run: `python3 tests/test_discord_audio.py`
Expected: PASS (`ALL PASS`) — the `main()` wiring does not affect the unit-level tests, and the import insert keeps the module loadable.

- [ ] **Step 7: Commit**

```bash
git add src/setup-assets.py tests/test_discord_audio.py
git commit -m "feat(obs): Linux Discord-web browser audio capture variant"
```

---

## Task 3: Web-aware Discord status in event report

**Files:**
- Modify: `src/scripts/event.py:200-206` (`classify_app`), `src/racecast.py:1604-1607` (`_event_sections`)
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_event.py`, extend `t_classify_app_levels` (currently ends after the discord WARN assertion) by appending:

```python
    # Web-variant host: no native Discord process; report an informational note.
    rw = m.classify_app("discord", False, web=True)
    assert rw.level == "INFO" and rw.name == "Discord"
    assert "Discord-web" in rw.detail and "browser" in rw.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_event.py`
Expected: FAIL — `classify_app()` got an unexpected keyword argument `web`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/event.py`, replace `classify_app` (lines 200-206) with:

```python
def classify_app(app, running, web=False):
    """OBS is broadcast-critical (FAIL); Discord only carries interview audio.
    On a web-variant host (no native Discord — e.g. ARM64 Linux) interview audio
    comes from Discord-web in a browser, so report an informational note instead
    of a 'Discord not running' warning."""
    if app == "obs":
        return (Result(PASS, "OBS", "running") if running else
                Result(FAIL, "OBS", "not running — launch OBS (or `racecast event start`)"))
    if app == "discord" and web:
        return Result(INFO, "Discord",
                      "interview audio via Discord-web in the browser — open it "
                      "and join the voice channel manually")
    return (Result(PASS, "Discord", "running") if running else
            Result(WARN, "Discord", "not running — interview audio unavailable; launch Discord"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_event.py`
Expected: PASS.

- [ ] **Step 5: Thread `web` through the racecast caller**

In `src/racecast.py`, `_event_sections` (lines 1604-1607 currently), replace:

```python
    # Apps
    obs_running = ev.app_running("obs")
    apps = [ev.classify_app("obs", obs_running),
            ev.classify_app("discord", ev.app_running("discord")),
            ev.classify_tailscale(_tailscale_ip())]
```

with:

```python
    # Apps
    import discord_web
    obs_running = ev.app_running("obs")
    discord_web_mode = discord_web.use_web(sys.platform, os.environ)
    apps = [ev.classify_app("obs", obs_running),
            ev.classify_app("discord", ev.app_running("discord"), web=discord_web_mode),
            ev.classify_tailscale(_tailscale_ip())]
```

(`scripts/` is already on `sys.path` from `src/racecast.py:36`, so `import discord_web` resolves.)

- [ ] **Step 6: Run the event tests + a racecast smoke import**

Run: `python3 tests/test_event.py && python3 tests/test_racecast.py`
Expected: PASS for both (the racecast suite imports the module and exercises CLI routing; the new local import must not break it).

- [ ] **Step 7: Commit**

```bash
git add src/scripts/event.py src/racecast.py tests/test_event.py
git commit -m "feat(event): web-aware Discord interview-audio status line"
```

---

## Task 4: Web-aware Discord line in preflight apps section

**Files:**
- Modify: `src/scripts/preflight.py:367-377` (`apps_section`), `:436-438` (`gather` caller)
- Test: `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_preflight.py`, add a new test next to `t_apps_section_levels` (around line 174):

```python
def t_apps_section_web_discord_is_info():
    # Web-variant host: native Discord absent is informational, not a WARN.
    rs = m.apps_section(lambda app: False, web=True)
    disc = [r for r in rs if r.name == "Discord"][0]
    assert disc.level == "INFO" and "Discord-web" in disc.detail
    # The other apps still WARN/FAIL as before when absent.
    obs = [r for r in rs if r.name == "OBS Studio"][0]
    assert obs.level == "FAIL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_preflight.py`
Expected: FAIL — `apps_section()` got an unexpected keyword argument `web`.

- [ ] **Step 3: Write minimal implementation**

In `src/scripts/preflight.py`, replace `apps_section` (lines 367-377) with:

```python
def apps_section(present, web=False):
    """Classify each producer app given `present(app) -> bool`. On a web-variant
    host (no native Discord — e.g. ARM64 Linux) a missing Discord client is
    informational: interview audio comes from Discord-web in a browser."""
    results = []
    for app, pretty, miss_level, consequence in APP_CHECKS:
        if present(app):
            results.append(Result(PASS, pretty, "installed"))
        elif app == "discord" and web:
            results.append(Result(INFO, pretty,
                                  "native client not installed — interview audio via "
                                  "Discord-web in the browser (open it and join the "
                                  "voice channel manually)"))
        else:
            results.append(Result(miss_level, pretty,
                                  f"not installed — {consequence}; run `racecast install-apps`"))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_preflight.py`
Expected: PASS.

- [ ] **Step 5: Thread `web` through `gather`**

In `src/scripts/preflight.py`, `gather()` (the `apps_section` call is at line 438), replace:

```python
    try:
        ia = _install_apps_module(here)
        apps = apps_section(lambda app: ia.app_present(app, sys.platform))
    except Exception as exc:  # never let a probe break the report
        apps = [Result(WARN, "applications", f"check failed: {exc}")]
```

with:

```python
    try:
        import discord_web
        ia = _install_apps_module(here)
        web = discord_web.use_web(sys.platform, os.environ)
        apps = apps_section(lambda app: ia.app_present(app, sys.platform), web=web)
    except Exception as exc:  # never let a probe break the report
        apps = [Result(WARN, "applications", f"check failed: {exc}")]
```

(`preflight.py` lives in `scripts/`, so `import discord_web` resolves directly.)

- [ ] **Step 6: Run the preflight tests**

Run: `python3 tests/test_preflight.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/scripts/preflight.py tests/test_preflight.py
git commit -m "feat(preflight): web-aware Discord install line"
```

---

## Task 5: Docs + config + test registration

**Files:**
- Modify: `.env.example`, `src/docs/wiki/OBS-Setup.md`, `src/docs/wiki/If-something-goes-wrong.md`, `CLAUDE.md`

- [ ] **Step 1: Document the two `.env` knobs**

In `.env.example`, append (keep the existing `RACECAST_*` grouping/comment style — match the surrounding format):

```bash
# Discord interview audio on Linux without a native client (e.g. ARM64, where the
# official .deb is amd64-only): capture Discord-web from a browser instead.
# RACECAST_DISCORD_WEB: leave empty for auto (web when no native Discord is found),
# 1 to force the browser variant, 0 to force the native source.
# RACECAST_DISCORD_WEB_BROWSER: the browser process to capture (PipeWire match
# name) — defaults to a detected running browser, else Firefox.
#RACECAST_DISCORD_WEB=
#RACECAST_DISCORD_WEB_BROWSER=Firefox
```

- [ ] **Step 2: Document the Linux browser fallback in OBS-Setup**

In `src/docs/wiki/OBS-Setup.md`, in the "Discord audio (interviews)" Linux subsection (around line 120-135), add a paragraph after the existing Linux note:

```markdown
**Linux without native Discord (e.g. ARM64):** the official Discord `.deb` is
amd64-only, so there is no native client to capture. `racecast setup` detects this
and points the **Discord Audio Capture** source at the browser instead — it stays a
PipeWire Application Capture source (so the panel/Companion mute & volume controls
are unchanged), only its target becomes the browser. Open **Discord-web**
(<https://discord.com/app>) in that browser, join the **Interviews** voice channel
before race end, and keep the tab playing. Override the auto-detection with
`RACECAST_DISCORD_WEB` (`1`/`0`) and the captured browser with
`RACECAST_DISCORD_WEB_BROWSER` (e.g. `Chromium`) in `.env`. The PipeWire capture
grabs *all* audio from that browser, so use a browser/profile dedicated to the
interview if other tabs make sound.
```

- [ ] **Step 3: Document the troubleshooting case**

In `src/docs/wiki/If-something-goes-wrong.md`, in the "No Discord audio (interviews)" section (around lines 39-45), append a bullet:

```markdown
- **ARM64 / no native Discord:** interview audio is captured from **Discord-web in a
  browser**, not a Discord app. Make sure the browser is the one named by
  `RACECAST_DISCORD_WEB_BROWSER` (default Firefox), that Discord-web is in the voice
  channel, and that the **Discord Audio Capture** source's *TargetName* matches the
  browser's PipeWire node (check it in OBS → the source's properties). If audio is
  silent, try the other match (`RACECAST_DISCORD_WEB_BROWSER=Chromium`) or confirm the
  `obs-pipewire-audio-capture` plugin is installed.
```

- [ ] **Step 4: Register the new test file**

In `CLAUDE.md`, in the Commands test list, add a line after the `test_obsws.py` entry (keep the aligned-comment style):

```
python3 tests/test_discord_web.py     # Discord-web/browser capture decision (native-vs-web, browser target)
```

- [ ] **Step 5: Commit**

```bash
git add .env.example src/docs/wiki/OBS-Setup.md src/docs/wiki/If-something-goes-wrong.md CLAUDE.md
git commit -m "docs(discord): document the Linux Discord-web audio fallback"
```

---

## Task 6: Full-suite verification + build

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite (exactly what CI runs)**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS` — including the new `test_discord_web.py` (auto-discovered by the glob).

- [ ] **Step 2: Lint (the CI lint job)**

Run: `python3 tools/lint.py`
Expected: no findings. If the `import discord_web  # noqa: E402` or the local imports trip a rule, confirm the `# noqa` is present and the lint config matches; fix any real findings.

- [ ] **Step 3: Build self-verify (the closest thing to CI's package check)**

Run: `python3 tools/build.py`
Expected: build completes; the verify step (tokenization, blanked password, no secrets, preflight present, no shell scripts) passes. Confirm `dist/` assembled without error.

- [ ] **Step 4: Commit any verification fixups (only if needed)**

```bash
git add -A
git commit -m "test(discord): verification fixups for the web audio fallback"
```

---

## Out of scope (do NOT implement)

- OBS **Browser Source** widget for Discord (breaks panel/Companion mute & volume; CEF login/mic/WebRTC risk).
- Auto-launching the browser or the Discord channel from `racecast event start`.
- Any league/profile-level Discord configuration (channel URL, server).
- A health check that the browser is running.

## Post-merge spike (manual, on the ARM64 VM — tracked separately, not a code task)

Verify on real hardware: that `pipewire_audio_application_capture` matches the browser's audio node during a Discord-web voice call; which `TargetName`/`MatchPriorty` isolate only the Discord-web audio; no echo/doubled audio; and that `tools/tokenize-obs.py` folds the web variant back to the canonical macOS form on re-export. Feed findings back into the defaults if needed.
```
