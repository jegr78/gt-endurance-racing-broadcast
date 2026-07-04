#!/usr/bin/env python3
"""Install the obs-pipewire-audio-capture plugin (dimtpap) on Linux.

The plugin backs OBS's PipeWire audio-capture source, which is how the Discord
interview audio is captured on Linux (native Discord AND Discord-web). OBS's
apt/PPA package does NOT bundle it, so a fresh Linux box has no Discord audio path
until it is installed — the relay/OBS otherwise render a silent interview.

Unlike the Browser Source plugin (obs_browser_linux, a from-source CEF build), this
plugin ships a prebuilt .so in an upstream release tarball, so the install is a
pinned, SHA-256-verified download extracted into the per-user OBS plugins dir
(`~/.config/obs-studio/plugins/`) — the dimtpap release layout preflight already
probes (preflight.pipewire_audio_candidates). x86_64 only (the release has no
aarch64 build); flatpak OBS must use the Flathub plugin instead.

Pure helpers (paths, arch/flatpak gating, the pinned asset, the install hint) are
unit-tested; the heavy download is behind an injectable `opener` seam."""
import hashlib
import io
import os
import tarfile

try:
    import http_util
except ImportError:                                   # pragma: no cover - source layout only
    http_util = None

# Pinned upstream release (dimtpap/obs-pipewire-audio-capture). The non-flatpak
# asset carries a 64bit (x86_64) libobs plugin compatible with OBS 30/31/32.
PLUGIN_VERSION = "1.2.1"
PLUGIN_ASSET = f"linux-pipewire-audio-{PLUGIN_VERSION}.tar.gz"   # non-flatpak variant
PLUGIN_URL_TMPL = ("https://github.com/dimtpap/obs-pipewire-audio-capture/"
                   "releases/download/{ver}/{asset}")
# sha256 of the official 1.2.1 non-flatpak tarball (verified by download).
PLUGIN_SHA256 = "9e2842ea850a61609021e7efeb5af7d95effd30ec1476e4b23d8437485aa8d12"
PLUGIN_SO = "linux-pipewire-audio.so"

_X86_64 = ("x86_64", "amd64")


# --- pure helpers --------------------------------------------------------
def user_plugins_dir(home):
    """The per-user OBS plugins dir. A fixed POSIX path -> build it with explicit
    forward slashes, never os.path.join (backslashes on the Windows CI runner;
    CLAUDE.md cross-platform rule)."""
    return home.replace("\\", "/").rstrip("/") + "/.config/obs-studio/plugins"


def plugin_so_path(home):
    """Where the plugin .so lands — must equal preflight.pipewire_audio_candidates()[0]."""
    return user_plugins_dir(home) + "/linux-pipewire-audio/bin/64bit/" + PLUGIN_SO


def plugin_installed(home, exists=os.path.exists):
    """True iff the plugin .so is present in the per-user layout."""
    return exists(plugin_so_path(home))


def is_prebuilt_arch(machine):
    """The release ships a 64bit (x86_64) .so only — no aarch64 prebuilt. Pure."""
    return (machine or "").lower() in _X86_64


def is_flatpak_obs(home, exists=os.path.exists):
    """True when OBS is a flatpak install (its tree lives under
    ~/.var/app/com.obsproject.Studio) — those must use the Flathub plugin, not this
    tarball. Fixed POSIX path -> explicit '/'."""
    base = home.replace("\\", "/").rstrip("/") + "/.var/app/com.obsproject.Studio"
    return exists(base)


def download_url(ver=PLUGIN_VERSION):
    return PLUGIN_URL_TMPL.format(ver=ver, asset=f"linux-pipewire-audio-{ver}.tar.gz")


def _safe_members(tf, dest):
    """Yield tar members whose resolved path stays within dest (zip/tar-slip guard)."""
    dest_abs = os.path.realpath(dest)
    for member in tf.getmembers():
        target = os.path.realpath(os.path.join(dest, member.name))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise RuntimeError(f"unsafe path in archive (traversal): {member.name}")
        yield member


def install_pipewire_audio(home, opener=None, sha256=PLUGIN_SHA256):
    """Download the pinned plugin tarball, verify its SHA-256, and extract it into
    the per-user OBS plugins dir. Returns the installed .so path. Raises on a
    checksum mismatch or an unsafe (path-traversal) archive. `opener` (url -> bytes)
    is injectable for tests; defaults to a stdlib HTTPS GET."""
    if opener is None:
        def opener(url):
            return http_util.get_bytes(url, timeout=120)   # nosec - pinned GitHub host, checksum-verified
    blob = opener(download_url())
    got = hashlib.sha256(blob).hexdigest()
    if got != sha256:
        raise RuntimeError(
            f"obs-pipewire-audio download checksum mismatch: {got} != {sha256}")
    dest = user_plugins_dir(home)
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        tf.extractall(dest, members=list(_safe_members(tf, dest)))   # nosec B202 - members validated
    return plugin_so_path(home)


def install_hint(machine, obs_present, plugin_present, is_flatpak):
    """One-line guidance for install-apps when the plugin can't be auto-installed,
    or None when there is nothing to say (no OBS, or already installed)."""
    if not obs_present or plugin_present:
        return None
    if is_flatpak:
        return ("OBS PipeWire audio plugin: your OBS is a Flatpak — install the plugin "
                "from Flathub (com.obsproject.Studio.Plugin.PipeWireAudioCapture); the "
                "Discord interview audio source needs it.")
    if not is_prebuilt_arch(machine):
        return ("OBS PipeWire audio plugin: no prebuilt build for this arch "
                f"({machine}) — build obs-pipewire-audio-capture from source; the "
                "Discord interview audio source needs it.")
    return None
