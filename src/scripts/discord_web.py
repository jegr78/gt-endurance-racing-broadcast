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
