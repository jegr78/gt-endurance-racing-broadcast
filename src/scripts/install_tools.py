#!/usr/bin/env python3
"""`racecast install-tools` — install the external runtime tools (yt-dlp, streamlink,
ffmpeg, deno) via the platform's package manager: winget (Windows), brew (macOS),
apt (Linux). Never elevates privileges itself — the brew bootstrap and the
package managers prompt for sudo on their own; failed installs end with a manual
guide. Pure decision helpers up top (unit-tested); main() performs the installs."""
import os, shutil, subprocess, sys

_COMMON = None


def _common():
    """Load installer_common.py from the sibling path (repo + frozen bundle)."""
    global _COMMON
    if _COMMON is None:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            "installer_common", os.path.join(here, "installer_common.py"))
        _COMMON = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_COMMON)
    return _COMMON

TOOLS = ("yt-dlp", "streamlink", "ffmpeg", "deno")

WINGET_IDS = {"yt-dlp": "yt-dlp.yt-dlp", "streamlink": "Streamlink.Streamlink",
              "ffmpeg": "Gyan.FFmpeg", "deno": "DenoLand.Deno"}
APT_PACKAGES = {"yt-dlp": "yt-dlp", "streamlink": "streamlink", "ffmpeg": "ffmpeg"}
# deno ships no apt package — Linux users get a pointer in manual_guide().

# The Ookla speedtest CLI (used by `racecast speedtest`). It is a first-class
# tool the producer installs via `install-tools` / the Control Center "Install
# all" button, but it is kept OUT of the TOOLS tuple so its absence never turns
# the preflight tool-chain into a FAIL (a bandwidth check is advisory).
#
# Install is HYBRID (decided after Homebrew 6.x began refusing the teamookla
# third-party tap as "untrusted"):
#   * Windows  -> winget (Ookla.Speedtest.CLI, first-party).
#   * mac/Linux -> direct download of Ookla's official CLI tarball, version-pinned
#                  and SHA-256-verified, extracted into the racecast-managed bin
#                  dir (no brew tap / apt repo, no trust bypass).
SPEEDTEST_WINGET_ID = "Ookla.Speedtest.CLI"
SPEEDTEST_BIN_NAME = "speedtest"
SPEEDTEST_VERSION = "1.2.0"
SPEEDTEST_URL_TMPL = "https://install.speedtest.net/app/cli/ookla-speedtest-{ver}-{tag}.tgz"
# tag -> sha256 of the official v1.2.0 tarball (verified by download; the macOS +
# linux-x86_64 values match the canonical teamookla Homebrew formula).
SPEEDTEST_DOWNLOADS = {
    "macosx-universal": "c9f8192149ebc88f8699998cecab1ce144144045907ece6f53cf50877f4de66f",
    "linux-x86_64":     "5690596c54ff9bed63fa3732f818a05dbc2db19ad36ed68f21ca5f64d5cfeeb7",
    "linux-aarch64":    "3953d231da3783e2bf8904b6dd72767c5c6e533e163d3742fd0437affa431bd3",
}


def speedtest_asset_tag(platform, machine):
    """Map (sys.platform, platform.machine()) -> a SPEEDTEST_DOWNLOADS tag, or
    None for Windows (winget handles it) and unsupported arches. Pure."""
    if platform == "darwin":
        return "macosx-universal"   # universal binary covers Intel + Apple Silicon
    if platform.startswith("linux"):
        m = (machine or "").lower()
        if m in ("x86_64", "amd64"):
            return "linux-x86_64"
        if m in ("aarch64", "arm64"):
            return "linux-aarch64"
    return None


def speedtest_download_url(tag, ver=SPEEDTEST_VERSION):
    return SPEEDTEST_URL_TMPL.format(ver=ver, tag=tag)


def speedtest_install_commands(manager):
    """Package-manager commands to install speedtest (Windows winget only). On
    mac/Linux the install is a direct download — see install_speedtest_binary()."""
    if manager == "winget":
        return [["winget", "install", "--id", SPEEDTEST_WINGET_ID, "-e",
                 "--accept-package-agreements", "--accept-source-agreements"]]
    return []


def speedtest_update_commands(manager):
    if manager == "winget":
        return [["winget", "upgrade", "--id", SPEEDTEST_WINGET_ID, "-e",
                 "--accept-package-agreements", "--accept-source-agreements"]]
    return []


def install_speedtest_binary(dest_dir, tag, opener=None, downloads=None):
    """Download Ookla's CLI tarball for `tag`, verify its SHA-256 against the
    pinned value, extract just the `speedtest` binary into dest_dir, and make it
    executable. Returns the binary path. Raises on a checksum mismatch or an
    unexpected archive layout. Pure-ish: `opener` (url -> bytes) is injectable for
    tests; defaults to a stdlib HTTPS GET."""
    import hashlib
    import io
    import tarfile
    downloads = downloads or SPEEDTEST_DOWNLOADS
    want = downloads[tag]
    if opener is None:
        import urllib.request
        def opener(url):
            with urllib.request.urlopen(url, timeout=60) as resp:  # nosec - pinned Ookla host, checksum-verified
                return resp.read()
    blob = opener(speedtest_download_url(tag))
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError(
            f"speedtest download checksum mismatch for {tag}: {got} != {want}")
    os.makedirs(dest_dir, exist_ok=True)
    binpath = os.path.join(dest_dir, SPEEDTEST_BIN_NAME)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        member = tf.getmember(SPEEDTEST_BIN_NAME)   # KeyError if the layout ever changes
        if not member.isfile():
            raise RuntimeError("unexpected speedtest archive layout")
        src = tf.extractfile(member)
        with open(binpath, "wb") as out:
            shutil.copyfileobj(src, out)
    os.chmod(binpath, 0o755)
    return binpath


def pick_manager(platform, which=shutil.which):
    """Package manager for this platform, or None (-> manual guide)."""
    if platform.startswith("win"):
        return "winget" if which("winget") else None
    if platform == "darwin":
        return "brew" if which("brew") else None
    return "apt" if which("apt-get") else None


def missing_tools(which=shutil.which):
    return [t for t in TOOLS if not which(t)]


def windows_fresh_path(read_values=None):
    """The PATH a NEW shell would get (system + user, from the registry).
    Installers (winget, Streamlink) update the registry, not running processes —
    this process's PATH predates anything installed during or shortly before
    this run. Returns None when there is nothing to read (non-Windows)."""
    if read_values is None:
        if not sys.platform.startswith("win"):
            return None
        read_values = _registry_path_values
    parts = [os.path.expandvars(v) for v in read_values() if v]
    return os.pathsep.join(parts) or None


def _registry_path_values():
    import winreg
    values = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                values.append(winreg.QueryValueEx(k, "Path")[0])
        except OSError:
            pass  # key/value absent (e.g. no user Path) — skip that hive
    return values


def install_commands(manager, tools, brew_path="brew"):
    """The argv list(s) to install `tools` with `manager`."""
    if manager == "winget":
        return [["winget", "install", "--id", WINGET_IDS[t], "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]
                for t in tools]
    if manager == "brew":
        return [[brew_path, "install"] + list(tools)] if tools else []
    if manager == "apt":
        pkgs = [APT_PACKAGES[t] for t in tools if t in APT_PACKAGES]
        return [["apt-get", "install", "-y"] + pkgs] if pkgs else []
    return []


def update_commands(manager, tools, brew_path="brew"):
    """The argv list(s) to UPGRADE already-installed `tools` with `manager`.
    winget's "no applicable update" exit code is whitelisted in
    installer_common.install_exit_ok; brew exits 0 for up-to-date formulae."""
    if manager == "winget":
        return [["winget", "upgrade", "--id", WINGET_IDS[t], "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]
                for t in tools]
    if manager == "brew":
        return [[brew_path, "upgrade"] + list(tools)] if tools else []
    if manager == "apt":
        pkgs = [APT_PACKAGES[t] for t in tools if t in APT_PACKAGES]
        return [["apt-get", "install", "-y", "--only-upgrade"] + pkgs] if pkgs else []
    return []


def manual_guide(platform):
    if platform.startswith("win"):
        return ("Install manually with winget (one per line):\n"
                + "\n".join(f"  winget install --id {WINGET_IDS[t]} -e" for t in TOOLS)
                + f"\n  winget install --id {SPEEDTEST_WINGET_ID} -e   # bandwidth speed test")
    if platform == "darwin":
        return ("Install manually:  brew install yt-dlp streamlink ffmpeg deno\n"
                "  bandwidth speed test (Ookla CLI): download the macOS build from\n"
                "  https://www.speedtest.net/apps/cli and put `speedtest` on your PATH")
    return ("Install manually:  sudo apt-get install -y yt-dlp streamlink ffmpeg\n"
            "deno has no apt package — see https://docs.deno.com/runtime/getting_started/installation/\n"
            "bandwidth speed test (Ookla CLI): download the Linux build from\n"
            "  https://www.speedtest.net/apps/cli and put `speedtest` on your PATH\n"
            "NOTE: apt's yt-dlp lags upstream; for a current build: pip install -U yt-dlp")


def _which_with_brew_prefix(brew):
    """which() that also looks in brew's bin dir (not on PATH right after a
    fresh bootstrap)."""
    prefix_bin = os.path.dirname(brew) if brew else None

    def probe(name):
        hit = shutil.which(name)
        if hit:
            return hit
        if prefix_bin:
            cand = os.path.join(prefix_bin, name)
            if os.path.exists(cand):
                return cand
        return None
    return probe


def _which_with_fresh_path(fresh_path):
    """which() that falls back to the registry PATH (Windows) — same idea as
    _which_with_brew_prefix: a just-installed tool is not on THIS process's
    PATH yet, but a new shell will see it."""
    def probe(name):
        hit = shutil.which(name)
        if hit:
            return hit
        return shutil.which(name, path=fresh_path) if fresh_path else None
    return probe


def _note_new_terminal():
    """Tools installed/found may not be on this shell's PATH yet — installers
    update the registry / shell profile, not running shells."""
    not_on_path = [t for t in TOOLS if not shutil.which(t)]
    if not_on_path:
        print("NOTE: open a NEW terminal before `racecast preflight` / `racecast relay start` —")
        print("      not on this shell's PATH yet:", ", ".join(not_on_path))


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="install-tools", add_help=True)
    ap.add_argument("--yes", action="store_true",
                    help="skip the Homebrew bootstrap confirmation (macOS)")
    ap.add_argument("--update", action="store_true",
                    help="also upgrade the already-installed tools to their "
                         "latest versions (recommended before every event)")
    ap.add_argument("--runtime-dir", default=None,
                    help="base runtime dir for the managed speedtest binary "
                         "(default: the project runtime dir)")
    a = ap.parse_args()

    import platform as _platform
    import speedtest as st
    runtime_dir = a.runtime_dir or st.default_runtime_dir(
        os.path.dirname(os.path.abspath(__file__)))

    missing = missing_tools(which=_which_with_fresh_path(windows_fresh_path()))
    # speedtest is provisioned here too — a setup whose core tools are already
    # present can still get it. find_binary() looks on PATH (winget) AND in the
    # managed bin dir (the mac/Linux direct download).
    speedtest_missing = st.find_binary(runtime_dir) is None
    if not missing and not speedtest_missing and not a.update:
        print("All external tools already installed:", ", ".join(TOOLS) + ", speedtest")
        print("  (run `racecast install-tools --update` to upgrade them)")
        _note_new_terminal()
        return
    if missing:
        print("Missing tools:", ", ".join(missing))

    brew = None
    if sys.platform == "darwin":
        brew = _common().find_brew()
        if not brew:
            brew = _common().bootstrap_brew(a.yes)
        if not brew:
            sys.exit("No supported package manager found.\n" + manual_guide(sys.platform))
        manager = "brew"
    else:
        manager = pick_manager(sys.platform)
        if manager is None:
            sys.exit("No supported package manager found.\n" + manual_guide(sys.platform))

    cmds = []
    if a.update:
        present = [t for t in TOOLS if t not in missing]
        if present:
            print("Updating installed tools:", ", ".join(present))
            cmds += update_commands(manager, present, brew_path=brew or "brew")
    cmds += install_commands(manager, missing, brew_path=brew or "brew")
    # speedtest on Windows is a winget package; mac/Linux is a direct download
    # (handled after the command loop). Best-effort, never blocks the core tools.
    if manager == "winget":
        if speedtest_missing:
            cmds += speedtest_install_commands("winget")
        elif a.update:
            cmds += speedtest_update_commands("winget")

    failed = []
    for cmd in cmds:
        print("Running:", " ".join(cmd))
        if not _common().install_exit_ok(manager, subprocess.call(cmd)):
            failed.append(" ".join(cmd))

    # speedtest direct download (macOS/Linux) — a pinned, SHA-256-verified Ookla
    # binary extracted into the managed bin dir. Windows got it via winget above.
    if manager != "winget" and (speedtest_missing or a.update):
        tag = speedtest_asset_tag(sys.platform, _platform.machine())
        if tag is None:
            print("NOTE: no prebuilt Ookla speedtest CLI for this OS/arch — see")
            print("      https://www.speedtest.net/apps/cli")
        else:
            dest = st.managed_bin_dir(runtime_dir)
            print(f"Installing Ookla speedtest CLI v{SPEEDTEST_VERSION} -> {dest} ...")
            try:
                install_speedtest_binary(dest, tag)
                print("  speedtest installed.")
            except Exception as exc:   # network/checksum/extract — report, don't crash
                failed.append(f"speedtest download ({exc})")

    if manager == "apt" and "deno" in missing:
        print("NOTE: deno is not packaged for apt — install it manually:")
        print("  https://docs.deno.com/runtime/getting_started/installation/")
    if manager == "winget":
        # The installs just changed the registry PATH — re-read it for the check.
        still = missing_tools(which=_which_with_fresh_path(windows_fresh_path()))
    else:
        still = missing_tools(which=_which_with_brew_prefix(brew))
    if failed or still:
        parts = ["Some installs did not complete."]
        if failed:
            parts.append("Failed: " + "; ".join(failed))
        if still:
            parts.append("Still missing: " + ", ".join(still))
        sys.exit("\n".join(parts) + "\n" + manual_guide(sys.platform))
    # Tools may sit in brew's prefix / the registry PATH but not THIS shell's.
    _note_new_terminal()
    print("All tools " + ("up to date" if a.update else "installed")
          + ". Run `racecast preflight` to verify.")


if __name__ == "__main__":
    main()
