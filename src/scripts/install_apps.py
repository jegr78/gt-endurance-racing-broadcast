#!/usr/bin/env python3
"""`iro install-apps` — install the producer APPLICATIONS (OBS Studio, Bitfocus
Companion, Tailscale) via winget (Windows) / brew casks (macOS) / official vendor
paths (Linux, apt-based distros). Linux is automated after an explicit operator
confirmation (sudo prompts surface to the operator); other distros get the manual
guide. Never elevates privileges itself — the vendor installers and package
managers prompt for sudo on their own. The required CLI tools live in
install_tools.py."""
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

APPS = ("obs", "companion", "tailscale", "discord")

WINGET_APP_IDS = {"obs": "OBSProject.OBSStudio",
                  "companion": "Bitfocus.Companion",
                  "tailscale": "Tailscale.Tailscale",
                  "discord": "Discord.Discord"}
# The tailscale-app CASK is the GUI app; the plain `tailscale` formula is the
# bare daemon — producers need the app.
BREW_CASKS = {"obs": "obs", "companion": "companion",
              "tailscale": "tailscale-app", "discord": "discord"}

# Default install locations per app — heuristics like companion_common's
# WINDOWS_COMPANION_CANDIDATES (keep the Companion entries in sync with it).
_WINDOWS_APP_PATHS = {
    # OBS lands in Program Files (x86) when a 32-bit installer registered it —
    # seen on a real producer machine.
    "obs": (r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe",
            r"%ProgramFiles(x86)%\obs-studio\bin\64bit\obs64.exe"),
    "companion": (r"%LOCALAPPDATA%\Programs\companion\Companion.exe",
                  r"C:\Program Files\Companion\Companion.exe",
                  r"C:\Program Files (x86)\Companion\Companion.exe"),
    "tailscale": (r"C:\Program Files\Tailscale\tailscale.exe",),
    # Discord is a Squirrel per-user install — the versioned app-x.y.z\Discord.exe
    # folder moves on every update; Update.exe is the version-stable path.
    "discord": (r"%LOCALAPPDATA%\Discord\Update.exe",),
}
_DARWIN_APP_PATHS = {
    "obs": ("/Applications/OBS.app",),
    "companion": ("/Applications/Companion.app",),
    "tailscale": ("/Applications/Tailscale.app",),
    "discord": ("/Applications/Discord.app",),
}
# companion-pi installs a systemd service, not a `companion` binary on PATH —
# without these candidates the post-install re-check would call a successful
# install "still missing".
_LINUX_APP_PATHS = {
    "companion": ("/opt/companion", "/etc/systemd/system/companion.service"),
    "discord": ("/usr/share/discord", "/usr/bin/discord"),
}

# Official Linux install paths (verified against vendor docs). The two installer
# scripts are downloaded over HTTPS (cert-verified) to a temp file and executed
# VISIBLY — never via shell pipes — after an explicit operator confirmation.
OBS_PPA = "ppa:obsproject/obs-studio"
TAILSCALE_INSTALLER = "https://tailscale.com/install.sh"          # escalates itself
COMPANION_INSTALLER = \
    "https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh"  # needs root
# Discord's official Linux .deb (the snap is community-maintained, not Discord Inc.)
DISCORD_DEB = "https://discord.com/api/download?platform=linux&format=deb"


def _expand_windows(path, env):
    path = path.replace("%ProgramFiles(x86)%", env.get("ProgramFiles(x86)", ""))
    path = path.replace("%ProgramFiles%", env.get("ProgramFiles", ""))
    path = path.replace("%LOCALAPPDATA%", env.get("LOCALAPPDATA", ""))
    return path


def app_path_candidates(app, platform, env=None):
    """Expanded well-known install paths for `app` on `platform` (may be empty —
    Linux mostly relies on the PATH fallback in app_present)."""
    env = os.environ if env is None else env
    if platform.startswith("win"):
        return [_expand_windows(p, env) for p in _WINDOWS_APP_PATHS.get(app, ())]
    if platform == "darwin":
        return list(_DARWIN_APP_PATHS.get(app, ()))
    return list(_LINUX_APP_PATHS.get(app, ()))


def app_present(app, platform, env=None, exists=os.path.exists, which=shutil.which):
    """True iff the app is already installed (well-known paths, then PATH)."""
    for path in app_path_candidates(app, platform, env):
        if not path.startswith("\\") and exists(path):
            return True
    return bool(which(app))  # CLI fallback (e.g. tailscale on PATH)


# Apps whose winget SILENT install is broken: Companion's NSIS installer
# writes NOTHING without admin yet exits 0, so winget reports success while
# nothing was installed (seen live). --interactive runs the UI wizard, whose
# UAC prompt the operator can actually answer.
WINGET_INTERACTIVE = ("companion",)


def app_install_commands(manager, apps, brew_path="brew"):
    """The argv list(s) to install `apps` with `manager`. apt: none (manual)."""
    if manager == "winget":
        return [["winget", "install", "--id", WINGET_APP_IDS[a], "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]
                + (["--interactive"] if a in WINGET_INTERACTIVE else [])
                for a in apps]
    if manager == "brew":
        casks = [BREW_CASKS[a] for a in apps]
        return [[brew_path, "install", "--cask"] + casks] if casks else []
    return []


def app_update_commands(manager, apps, brew_path="brew"):
    """The argv list(s) to UPGRADE already-installed `apps` with `manager`.
    brew skips self-updating casks (Discord/Tailscale update themselves) —
    that is fine, not a failure. Linux: see apps_update_guide()."""
    if manager == "winget":
        return [["winget", "upgrade", "--id", WINGET_APP_IDS[a], "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]
                + (["--interactive"] if a in WINGET_INTERACTIVE else [])
                for a in apps]
    if manager == "brew":
        casks = [BREW_CASKS[a] for a in apps]
        return [[brew_path, "upgrade", "--cask"] + casks] if casks else []
    return []


def apps_update_guide():
    """Per-app Linux update paths (no single manager covers all four)."""
    return ("Linux app updates (manual):\n"
            "  OBS:       sudo apt-get update && sudo apt-get install --only-upgrade -y obs-studio\n"
            "  Tailscale: sudo apt-get install --only-upgrade -y tailscale\n"
            "             (the installer added Tailscale's apt repo)\n"
            "  Companion: sudo companion-update   (companion-pi service install)\n"
            "  Discord:   re-download the official .deb:\n"
            "             curl -fsSL 'https://discord.com/api/download?platform=linux&format=deb' \\\n"
            "               -o /tmp/discord.deb && sudo apt-get install -y /tmp/discord.deb")


def apps_manual_guide(platform):
    lines = ["Install the apps manually:"]
    if platform not in ("darwin",) and not platform.startswith("win"):
        lines.append("  (Linux/WSL: install them on the HOST machine that runs OBS)")
        lines.append("  OBS Studio  (https://obsproject.com/download):")
        lines.append("    sudo add-apt-repository -y ppa:obsproject/obs-studio")
        lines.append("    sudo apt-get update && sudo apt-get install -y obs-studio")
        lines.append("    (Debian without add-apt-repository: sudo apt-get install -y obs-studio)")
        lines.append("  Tailscale  (https://tailscale.com/download):")
        lines.append("    curl -fsSL https://tailscale.com/install.sh | sh")
        lines.append("    sudo tailscale up")
        lines.append("  Companion  (https://bitfocus.io/companion) — headless/service, Debian/Ubuntu x64/arm64:")
        lines.append("    curl -fsSL https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh | sudo bash")
        lines.append("  Discord  (https://discord.com/download):")
        lines.append("    curl -fsSL 'https://discord.com/api/download?platform=linux&format=deb' -o /tmp/discord.deb")
        lines.append("    sudo apt-get install -y /tmp/discord.deb")
    else:
        lines.append("  OBS Studio : https://obsproject.com/download")
        lines.append("  Companion  : https://bitfocus.io/companion")
        lines.append("  Tailscale  : https://tailscale.com/download")
        lines.append("  Discord    : https://discord.com/download")
    if platform.startswith("win"):
        lines.append("NOTE: approve the UAC (admin) prompts — Companion's installer "
                     "writes nothing without admin yet still reports success.")
    return "\n".join(lines)


def linux_install_steps(apps, which=shutil.which):
    """Ordered (kind, ...) steps to install `apps` on an apt-based distro.
    ('run', argv) executes argv; ('script', url, runner) downloads url and runs
    it with runner + [path]; ('deb', url) downloads url and installs it with
    apt-get. OBS uses the official PPA when add-apt-repository exists (Ubuntu),
    else plain apt (Debian ships obs-studio)."""
    steps = []
    if "obs" in apps:
        if which("add-apt-repository"):
            steps.append(("run", ["sudo", "add-apt-repository", "-y", OBS_PPA]))
            steps.append(("run", ["sudo", "apt-get", "update"]))
        steps.append(("run", ["sudo", "apt-get", "install", "-y", "obs-studio"]))
    if "tailscale" in apps:
        steps.append(("script", TAILSCALE_INSTALLER, ["sh"]))
    if "companion" in apps:
        steps.append(("script", COMPANION_INSTALLER, ["sudo", "bash"]))
    if "discord" in apps:
        steps.append(("deb", DISCORD_DEB))
    return steps


def confirmed(answer):
    return _common().confirmed(answer)


def _run_remote_script(url, runner):
    return _common().run_remote_script(url, runner)


def _install_linux(missing, assume_yes):
    if not shutil.which("apt-get"):
        print("No apt-based distro detected — install manually:")
        print(apps_manual_guide(sys.platform))
        return 0
    steps = linux_install_steps(missing)
    print("Planned steps (sudo will prompt for your password; the two installer")
    print("scripts are official vendor installers, downloaded over HTTPS):")
    for step in steps:
        if step[0] == "run":
            print("  $", " ".join(step[1]))
        elif step[0] == "deb":
            print("  $ sudo apt-get install -y <downloaded .deb>   #", step[1])
        else:
            print("  $", " ".join(step[2]), "<", step[1])
    if not assume_yes and not confirmed(input("Proceed? [y/N] ")):
        print("aborted.")
        return 0
    failed = []
    for step in steps:
        if step[0] == "run":
            print("Running:", " ".join(step[1]))
            rc = subprocess.call(step[1])
        elif step[0] == "deb":
            rc = _common().install_remote_deb(step[1])
        else:
            rc = _run_remote_script(step[1], step[2])
        if rc != 0:
            failed.append(step[1])  # argv for 'run' steps, URL for 'script'/'deb' steps
    if "tailscale" in missing:
        print("Tailscale installed? Finish with:  sudo tailscale up")
    if "companion" in missing:
        print("Companion: this is the headless/service install (companion-pi).")
    return 1 if failed else 0


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="install-apps", add_help=True)
    ap.add_argument("--yes", action="store_true",
                    help="skip confirmation prompts: Linux install steps and macOS Homebrew bootstrap")
    ap.add_argument("--update", action="store_true",
                    help="also upgrade the already-installed apps "
                         "(winget/brew; Linux prints the per-app update guide)")
    a = ap.parse_args()

    missing = [app for app in APPS if not app_present(app, sys.platform)]
    if not missing and not a.update:
        print("All apps already installed:", ", ".join(APPS))
        print("  (run `iro install-apps --update` to upgrade them)")
        return
    if missing:
        print("Missing apps:", ", ".join(missing))
    if not (sys.platform.startswith("win") or sys.platform == "darwin"):
        if a.update:
            print(apps_update_guide())
        if not missing:
            return
        rc = _install_linux(missing, a.yes)
        still = [x for x in APPS if not app_present(x, sys.platform)]
        if rc != 0 or (still and shutil.which("apt-get")):
            sys.exit("Some app installs did not complete. Still missing: "
                     + ", ".join(still) + "\n" + apps_manual_guide(sys.platform))
        return
    if sys.platform == "darwin":
        brew = _common().find_brew()
        if not brew:
            brew = _common().bootstrap_brew(a.yes)
        if not brew:
            sys.exit("brew not available.\n" + apps_manual_guide(sys.platform))
        manager = "brew"
        brew_path = brew
    else:
        manager = "winget"
        brew_path = "brew"
        if not shutil.which(manager):
            sys.exit(f"{manager} not found.\n" + apps_manual_guide(sys.platform))
    cmds = []
    if a.update:
        present = [x for x in APPS if x not in missing]
        if present:
            print("Updating installed apps:", ", ".join(present))
            cmds += app_update_commands(manager, present, brew_path=brew_path)
    cmds += app_install_commands(manager, missing, brew_path=brew_path)
    failed = []
    for cmd in cmds:
        print("Running:", " ".join(cmd))
        # winget "already installed / no upgrade" exit codes are not failures
        # (an app the path heuristics in app_present() missed lands here).
        if not _common().install_exit_ok(manager, subprocess.call(cmd)):
            failed.append(" ".join(cmd))
    still = [a for a in APPS if not app_present(a, sys.platform)]
    if failed or still:
        parts = ["Some app installs did not complete."]
        if failed:
            parts.append("Failed: " + "; ".join(failed))
        if still:
            parts.append("Still missing: " + ", ".join(still))
        sys.exit("\n".join(parts) + "\n" + apps_manual_guide(sys.platform))
    if not missing:
        print("All apps up to date.")
        return
    print("All apps installed. First-run setup still needed:")
    print("  Tailscale: sign in and join the IRO tailnet (invited account).")
    print("  Companion: launch once, then `iro export companion` + import the config.")
    print("  OBS: run `iro setup` and import the localized collection.")
    print("  Discord: sign in — used for the interview audio (OBS app-audio capture).")


if __name__ == "__main__":
    main()
