#!/usr/bin/env python3
"""Stdlib checks for install_apps decision helpers. Run: python3 tests/test_install_apps.py"""
import importlib.util, os, re
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "install_apps", os.path.join(ROOT, "src", "scripts", "install_apps.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_app_ids():
    assert m.WINGET_APP_IDS == {"obs": "OBSProject.OBSStudio",
                                "companion": "Bitfocus.Companion",
                                "tailscale": "Tailscale.Tailscale",
                                "discord": "Discord.Discord"}
    assert m.BREW_CASKS == {"obs": "obs", "companion": "companion",
                            "tailscale": "tailscale-app", "discord": "discord"}


def t_install_commands_winget_one_per_app():
    cmds = m.app_install_commands("winget", ["obs", "tailscale"])
    assert len(cmds) == 2
    assert cmds[0][:3] == ["winget", "install", "--id"]
    assert cmds[0][3] == "OBSProject.OBSStudio" and cmds[1][3] == "Tailscale.Tailscale"
    assert all("--interactive" not in c for c in cmds)


def t_install_commands_companion_is_interactive():
    # Companion's NSIS installer writes NOTHING without admin in silent mode
    # yet exits 0 — only the interactive wizard (with its UAC prompt) works.
    (cmd,) = m.app_install_commands("winget", ["companion"])
    assert cmd[3] == "Bitfocus.Companion" and "--interactive" in cmd


def t_install_commands_brew_single_cask_batch():
    assert m.app_install_commands("brew", ["obs", "tailscale"]) == \
        [["brew", "install", "--cask", "obs", "tailscale-app"]]
    assert m.app_install_commands("brew", []) == []


def t_install_commands_apt_is_manual():
    assert m.app_install_commands("apt", ["obs", "companion", "tailscale"]) == []


def t_app_present_darwin_bundles():
    exists = lambda p: p == "/Applications/OBS.app"
    assert m.app_present("obs", "darwin", exists=exists, which=lambda n: None)
    assert not m.app_present("companion", "darwin", exists=exists, which=lambda n: None)


def t_app_present_windows_paths():
    hit = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"
    env = {"ProgramFiles": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    assert m.app_present("obs", "win32", env=env, exists=lambda p: p == hit,
                         which=lambda n: None)
    # 32-bit-installer registrations land OBS in Program Files (x86) — seen on a
    # real producer machine; without this candidate install-apps re-"installs" it.
    x86 = r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"
    env_x86 = dict(env, **{"ProgramFiles(x86)": r"C:\Program Files (x86)"})
    assert m.app_present("obs", "win32", env=env_x86, exists=lambda p: p == x86,
                         which=lambda n: None)
    assert not m.app_present("tailscale", "win32", env=env, exists=lambda p: False,
                             which=lambda n: None)


def t_app_present_falls_back_to_which():
    assert m.app_present("tailscale", "linux", exists=lambda p: False,
                         which=lambda n: "/usr/bin/tailscale" if n == "tailscale" else None)


def t_app_present_linux_companion_service():
    # companion-pi installs a systemd service, not a PATH binary
    unit = "/etc/systemd/system/companion.service"
    assert m.app_present("companion", "linux", exists=lambda p: p == unit,
                         which=lambda n: None)
    assert not m.app_present("companion", "linux", exists=lambda p: False,
                             which=lambda n: None)


def t_app_present_discord_paths():
    # Windows: Squirrel per-user install — Update.exe is the version-stable path
    env = {"ProgramFiles": r"C:\Program Files",
           "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    hit = r"C:\Users\x\AppData\Local\Discord\Update.exe"
    assert m.app_present("discord", "win32", env=env, exists=lambda p: p == hit,
                         which=lambda n: None)
    assert m.app_present("discord", "darwin",
                         exists=lambda p: p == "/Applications/Discord.app",
                         which=lambda n: None)
    assert m.app_present("discord", "linux",
                         exists=lambda p: p == "/usr/bin/discord",
                         which=lambda n: None)
    assert not m.app_present("discord", "linux", exists=lambda p: False,
                             which=lambda n: None)
    # First linux candidate (/usr/share/discord) must also match
    assert m.app_present("discord", "linux",
                         exists=lambda p: p == "/usr/share/discord",
                         which=lambda n: None)


def t_manual_guide_has_urls_per_os():
    # Compare URL HOSTS, not substrings — '"x.com" in guide' would also match
    # an unrelated URL like https://evil.example/?x.com.
    for plat in ("win32", "darwin", "linux"):
        guide = m.apps_manual_guide(plat)
        urls = [u.rstrip("'\"),:") for u in re.findall(r"https?://\S+", guide)]
        hosts = {urlparse(u).hostname for u in urls}
        for want in ("obsproject.com", "bitfocus.io", "tailscale.com", "discord.com"):
            assert want in hosts, (plat, want, sorted(h for h in hosts if h))


def t_linux_plan_obs_with_ppa():
    steps = m.linux_install_steps(["obs"], which=lambda n: "/usr/bin/" + n)
    assert steps == [
        ("run", ["sudo", "add-apt-repository", "-y", "ppa:obsproject/obs-studio"]),
        ("run", ["sudo", "apt-get", "update"]),
        ("run", ["sudo", "apt-get", "install", "-y", "obs-studio"]),
    ]


def t_linux_plan_obs_without_ppa_tool():
    no_ppa = lambda n: None if n == "add-apt-repository" else "/usr/bin/" + n
    assert m.linux_install_steps(["obs"], which=no_ppa) == \
        [("run", ["sudo", "apt-get", "install", "-y", "obs-studio"])]


def t_linux_plan_scripts():
    steps = m.linux_install_steps(["tailscale", "companion"], which=lambda n: "/usr/bin/" + n)
    assert steps == [
        ("script", "https://tailscale.com/install.sh", ["sh"]),
        ("script",
         "https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh",
         ["sudo", "bash"]),
    ]


def t_linux_plan_discord_deb():
    steps = m.linux_install_steps(["discord"], which=lambda n: "/usr/bin/" + n)
    assert steps == [("deb", m.DISCORD_DEB)]
    assert m.DISCORD_DEB.startswith("https://discord.com/")


def t_confirmation_parsing():
    assert m.confirmed("y") and m.confirmed("Y") and m.confirmed("yes")
    assert not m.confirmed("") and not m.confirmed("n") and not m.confirmed("nein")


def t_app_install_commands_brew_absolute_path():
    assert m.app_install_commands("brew", ["obs"],
                                  brew_path="/opt/homebrew/bin/brew") == \
        [["/opt/homebrew/bin/brew", "install", "--cask", "obs"]]


def t_app_path_candidates():
    env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86",
           "LOCALAPPDATA": r"C:\LAD"}
    cands = m.app_path_candidates("obs", "win32", env)
    assert r"C:\PF\obs-studio\bin\64bit\obs64.exe" in cands
    assert r"C:\PF86\obs-studio\bin\64bit\obs64.exe" in cands
    assert m.app_path_candidates("discord", "win32", env) == [r"C:\LAD\Discord\Update.exe"]
    assert m.app_path_candidates("obs", "darwin") == ["/Applications/OBS.app"]
    assert m.app_path_candidates("obs", "linux") == []   # PATH fallback only
    assert m.app_path_candidates("bogus", "darwin") == []


def t_app_update_commands_winget_keeps_companion_interactive():
    cmds = m.app_update_commands("winget", ["obs", "companion"])
    assert len(cmds) == 2
    assert cmds[0][:3] == ["winget", "upgrade", "--id"]
    assert "--interactive" not in cmds[0]
    assert "--interactive" in cmds[1]


def t_app_update_commands_brew_cask_batch():
    assert m.app_update_commands("brew", ["obs", "tailscale"]) == \
        [["brew", "upgrade", "--cask", "obs", "tailscale-app"]]
    assert m.app_update_commands("brew", []) == []


def t_app_update_commands_apt_is_manual_guide():
    assert m.app_update_commands("apt", ["obs"]) == []
    guide = m.apps_update_guide()
    for word in ("obs-studio", "tailscale", "companion-update", "discord.deb"):
        assert word in guide, word


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
