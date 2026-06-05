#!/usr/bin/env python3
"""`iro install-tools` — install the external runtime tools (yt-dlp, streamlink,
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


def manual_guide(platform):
    if platform.startswith("win"):
        return ("Install manually with winget (one per line):\n"
                + "\n".join(f"  winget install --id {WINGET_IDS[t]} -e" for t in TOOLS))
    if platform == "darwin":
        return "Install manually:  brew install yt-dlp streamlink ffmpeg deno"
    return ("Install manually:  sudo apt-get install -y yt-dlp streamlink ffmpeg\n"
            "deno has no apt package — see https://docs.deno.com/runtime/getting_started/installation/\n"
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
        print("NOTE: open a NEW terminal before `iro preflight` / `iro relay start` —")
        print("      not on this shell's PATH yet:", ", ".join(not_on_path))


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="install-tools", add_help=True)
    ap.add_argument("--yes", action="store_true",
                    help="skip the Homebrew bootstrap confirmation (macOS)")
    a = ap.parse_args()

    missing = missing_tools(which=_which_with_fresh_path(windows_fresh_path()))
    if not missing:
        print("All external tools already installed:", ", ".join(TOOLS))
        _note_new_terminal()
        return
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

    failed = []
    for cmd in install_commands(manager, missing, brew_path=brew or "brew"):
        print("Running:", " ".join(cmd))
        if not _common().install_exit_ok(manager, subprocess.call(cmd)):
            failed.append(" ".join(cmd))
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
    print("All tools installed. Run `iro preflight` to verify.")


if __name__ == "__main__":
    main()
