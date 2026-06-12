#!/usr/bin/env python3
"""`racecast install-apps` — install the producer APPLICATIONS (OBS Studio, Bitfocus
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


def _read_plist(path):
    import plistlib
    with open(path, "rb") as fh:
        return plistlib.load(fh)


def darwin_app_version(app, exists=os.path.exists, read_plist=_read_plist):
    """Installed version of a macOS .app from its bundle Info.plist
    (CFBundleShortVersionString, then CFBundleVersion), or None when the bundle
    or the keys are absent / the plist is unreadable. The reader is injected so
    the logic is unit-tested without a real .app on disk."""
    for bundle in _DARWIN_APP_PATHS.get(app, ()):
        plist = os.path.join(bundle, "Contents", "Info.plist")
        if not exists(plist):
            continue
        try:
            data = read_plist(plist)
        except Exception:   # noqa: BLE001 — unreadable/corrupt plist -> no version, never raise
            return None
        return (data.get("CFBundleShortVersionString")
                or data.get("CFBundleVersion") or None)
    return None


def _read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _run(argv, run=None, timeout=8):
    """subprocess.run() wrapper that hides the Windows console window and turns
    any spawn failure into None. Used only for TRUE CLIs (tailscale, dpkg-query),
    never GUI app binaries — exec'ing those could pop a window."""
    run = subprocess.run if run is None else run
    try:
        import services
        nw = services.no_window_kwargs()
    except Exception:   # noqa: BLE001 — services optional (standalone) / probe is best-effort
        nw = {}
    try:
        return run(argv, capture_output=True, text=True, errors="replace",
                   timeout=timeout, **nw)
    except (OSError, subprocess.SubprocessError):
        return None


def cli_version(argv, run=None):
    """First non-empty stdout line of a CLI's version output (e.g.
    `tailscale version` -> '1.98.5'), or None on non-zero exit / spawn failure."""
    out = _run(argv, run=run)
    if out is None or out.returncode != 0:
        return None
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if line:
            return line
    return None


def dpkg_version(pkg, run=None):
    """Installed Debian package version via `dpkg-query`, or None when the
    package is not installed / dpkg is unavailable (Linux)."""
    out = _run(["dpkg-query", "-W", "-f=${Version}", pkg], run=run)
    if out is None or out.returncode != 0:
        return None
    return (out.stdout or "").strip() or None


def build_info_version(path, read_text=_read_text):
    """`version` from a Discord build_info.json (Linux/macOS), or None."""
    import json
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError):
        return None
    return data.get("version") or None


def _version_key(v):
    """Sort key for dotted version folders: leading-numeric of each segment."""
    key = []
    for chunk in v.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        key.append(int(num) if num else 0)
    return key


def discord_squirrel_version(local_appdata, listdir=os.listdir):
    """Highest 'app-X.Y.Z' folder version under %LOCALAPPDATA%\\Discord, or None.
    Discord's per-user Windows install names its version folder this way; reading
    it needs no subprocess and never launches Discord."""
    try:
        entries = listdir(os.path.join(local_appdata, "Discord"))
    except OSError:
        return None
    versions = [n[4:] for n in entries
                if n.startswith("app-") and n[4:5].isdigit()]
    return max(versions, key=_version_key) if versions else None


def windows_file_version(path):
    """Numeric FileVersion from a Windows PE binary's VERSIONINFO resource
    (e.g. obs64.exe -> '32.1.2.0'), or None. Reads metadata only — never
    executes the binary. No-op (None) off Windows."""
    try:
        import ctypes
        ver = ctypes.windll.version       # AttributeError off Windows -> None
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        block = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(block),
                                  ctypes.byref(length)) or not length.value:
            return None
        words = ctypes.cast(
            block, ctypes.POINTER(ctypes.c_uint * (length.value // 4))).contents
        ms, ls = words[2], words[3]       # dwFileVersionMS, dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:   # noqa: BLE001 — any API/format hiccup -> no version, never raise
        return None


def _first_existing(paths, exists):
    for p in paths:
        if p and not p.startswith("\\") and exists(p):
            return p
    return None


def _windows_app_version(app, env, exists, listdir, run, file_version):
    if app == "discord":
        local = env.get("LOCALAPPDATA", "")
        return discord_squirrel_version(local, listdir=listdir) if local else None
    cands = app_path_candidates(app, "win32", env)
    if app == "tailscale":   # a real CLI — `tailscale version` is safe
        exe = _first_existing(cands, exists) or "tailscale"
        return cli_version([exe, "version"], run=run)
    exe = _first_existing(cands, exists)   # obs64.exe / Companion.exe
    return file_version(exe) if exe else None


# Discord's bundled build_info.json — the .deb (/usr/share) and tarball (/opt).
_LINUX_DISCORD_BUILD_INFO = ("/usr/share/discord/resources/build_info.json",
                             "/opt/discord/resources/build_info.json")


def _linux_app_version(app, exists, read_text, run):
    if app == "tailscale":
        return cli_version(["tailscale", "version"], run=run)
    if app == "obs":
        return dpkg_version("obs-studio", run=run)
    if app == "discord":
        for bi in _LINUX_DISCORD_BUILD_INFO:
            if exists(bi):
                v = build_info_version(bi, read_text=read_text)
                if v:
                    return v
        return dpkg_version("discord", run=run)
    # companion-pi (service install) exposes no stable version file we can rely
    # on — the running web server is the source instead (companion_http_version,
    # tried as a fallback in app_version).
    return None


def _http_fetch(url, range_bytes):
    """GET `url` (optionally only its first `range_bytes`) and return the decoded
    body. Short timeout; raises on any failure (callers treat that as 'unknown')."""
    import urllib.request
    headers = {"Range": f"bytes=0-{range_bytes - 1}"} if range_bytes else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=4) as resp:
        body = resp.read(range_bytes) if range_bytes else resp.read()
    return body.decode("utf-8", "replace")


def companion_http_version(base_url="http://127.0.0.1:8000", fetch=_http_fetch):
    """Installed Companion version from its running web server, or None. Companion
    serves no version REST endpoint, but its built frontend embeds the release as
    `SENTRY_RELEASE={id:"<ver>+<build>-<channel>-<sha>"}` in the first ~1 KB of
    its main bundle. Fetch the SPA shell to find the content-hashed bundle name,
    then a small Range GET of its head to read the marker. This is the only version
    source for the companion-pi Linux service and for WSL/Docker setups where
    Companion runs on another host — it works wherever Companion is reachable.
    `fetch(url, range_bytes)` returns the body (range_bytes=None = whole shell)
    and raises on failure; the default uses urllib with a short timeout."""
    import re
    base = base_url.rstrip("/")
    try:
        shell = fetch(base + "/", None)
        scripts = re.findall(r'src="(/assets/index-[^"]+\.js)"', shell)
        bundle = next((s for s in scripts if "legacy" not in s), None)
        if not bundle:
            return None
        head = fetch(base + bundle, 65536)
        marker = re.search(r'SENTRY_RELEASE=\{id:"(\d+\.\d+\.\d+)', head)
        return marker.group(1) if marker else None
    except Exception:   # noqa: BLE001 — Companion unreachable / markup changed -> unknown
        return None


def app_version(app, platform=None, *, exists=os.path.exists, read_plist=_read_plist,
                read_text=_read_text, run=None, listdir=os.listdir, env=None,
                file_version=windows_file_version,
                companion_url="http://127.0.0.1:8000", companion_fetch=_http_fetch):
    """Best-effort installed version string for `app`, or None. Per platform,
    using only non-launching sources: macOS reads the .app Info.plist; Windows
    reads obs64.exe/Companion.exe file-version metadata, the Discord Squirrel
    folder, and `tailscale version`; Linux uses dpkg-query (OBS), Discord's
    build_info.json, and `tailscale version`. Companion has no local version file
    on Linux, so when the local probe comes back empty its running web server is
    queried (companion_http_version). Anything unavailable -> None, so the surfaces
    show presence without a version, never an error (issue #91)."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if platform == "darwin":
        version = darwin_app_version(app, exists=exists, read_plist=read_plist)
    elif platform.startswith("win"):
        version = _windows_app_version(app, env, exists, listdir, run, file_version)
    else:
        version = _linux_app_version(app, exists, read_text, run)
    if version is None and app == "companion" and companion_url:
        version = companion_http_version(companion_url, fetch=companion_fetch)
    return version


def installed_apps_report(apps, version_fn):
    """Aligned 'name  version' lines for already-installed `apps` (version_fn(app)
    -> str|None). Apps with no probed version show '(version unavailable)' rather
    than an empty column (issue #91)."""
    width = max((len(a) for a in apps), default=0)
    return [f"  {a.ljust(width)}  {version_fn(a) or '(version unavailable)'}"
            for a in apps]


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
        print("All apps already installed:")
        for line in installed_apps_report(list(APPS),
                                          lambda x: app_version(x, sys.platform)):
            print(line)
        print("  (run `racecast install-apps --update` to upgrade them)")
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
        print("All apps up to date:")
        for line in installed_apps_report(list(APPS),
                                          lambda x: app_version(x, sys.platform)):
            print(line)
        return
    print("All apps installed. First-run setup still needed:")
    print("  Tailscale: sign in and join the team's private Tailscale "
          "network (your invited account).")
    print("  Companion: launch once, then `racecast export companion` + import the config.")
    print("  OBS: run `racecast setup` and import the localized collection.")
    print("  Discord: sign in — used for the interview audio (OBS app-audio capture).")


if __name__ == "__main__":
    main()
