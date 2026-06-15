#!/usr/bin/env python3
"""Stdlib checks for install_tools decision helpers. Run: python3 tests/test_install_tools.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "install_tools", os.path.join(ROOT, "src", "scripts", "install_tools.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_pick_manager_per_platform():
    have_all = lambda name: "/usr/bin/" + name
    assert m.pick_manager("win32", which=have_all) == "winget"
    assert m.pick_manager("darwin", which=have_all) == "brew"
    assert m.pick_manager("linux", which=have_all) == "apt"
    assert m.pick_manager("win32", which=lambda n: None) is None


def t_missing_tools():
    assert m.missing_tools(which=lambda n: None) == list(m.TOOLS)
    assert m.missing_tools(which=lambda n: "/bin/" + n) == []
    only_ffmpeg = lambda n: "/bin/ffmpeg" if n == "ffmpeg" else None
    assert m.missing_tools(which=only_ffmpeg) == ["yt-dlp", "streamlink", "deno"]


def t_install_commands_winget_one_per_tool():
    cmds = m.install_commands("winget", ["yt-dlp", "deno"])
    assert len(cmds) == 2
    assert cmds[0][:3] == ["winget", "install", "--id"]
    assert cmds[0][3] == "yt-dlp.yt-dlp" and cmds[1][3] == "DenoLand.Deno"


def t_install_commands_brew_single_batch():
    assert m.install_commands("brew", ["ffmpeg", "deno"]) == \
        [["brew", "install", "ffmpeg", "deno"]]
    assert m.install_commands("brew", []) == []


def t_install_commands_apt_skips_deno():
    cmds = m.install_commands("apt", ["yt-dlp", "deno"])
    assert cmds == [["apt-get", "install", "-y", "yt-dlp"]]
    assert m.install_commands("apt", ["deno"]) == []


def t_manual_guide_mentions_deno_on_linux():
    assert "deno" in m.manual_guide("linux")
    assert "brew install" in m.manual_guide("darwin")
    assert "winget" in m.manual_guide("win32")


def t_windows_fresh_path_joins_registry_values():
    vals = ["C:\\sys\\bin", "C:\\user\\bin"]
    assert m.windows_fresh_path(read_values=lambda: vals) == os.pathsep.join(vals)
    assert m.windows_fresh_path(read_values=lambda: []) is None
    assert m.windows_fresh_path(read_values=lambda: ["", ""]) is None


def t_install_commands_brew_absolute_path():
    assert m.install_commands("brew", ["ffmpeg", "deno"],
                              brew_path="/opt/homebrew/bin/brew") == \
        [["/opt/homebrew/bin/brew", "install", "ffmpeg", "deno"]]


def t_update_commands_winget_one_per_tool():
    cmds = m.update_commands("winget", ["yt-dlp", "streamlink"])
    assert len(cmds) == 2
    assert cmds[0][:3] == ["winget", "upgrade", "--id"]
    assert cmds[0][3] == "yt-dlp.yt-dlp"
    assert "--accept-package-agreements" in cmds[0]


def t_update_commands_brew_single_batch():
    assert m.update_commands("brew", ["ffmpeg", "deno"]) == \
        [["brew", "upgrade", "ffmpeg", "deno"]]
    assert m.update_commands("brew", [], brew_path="/opt/homebrew/bin/brew") == []
    assert m.update_commands("brew", ["ffmpeg"],
                             brew_path="/opt/homebrew/bin/brew")[0][0] == \
        "/opt/homebrew/bin/brew"


def t_update_commands_apt_only_upgrade_skips_deno():
    cmds = m.update_commands("apt", ["yt-dlp", "deno"])
    assert cmds == [["apt-get", "install", "-y", "--only-upgrade", "yt-dlp"]]
    assert m.update_commands("apt", ["deno"]) == []


def t_speedtest_install_commands_winget_only():
    # Windows installs via winget; mac/Linux are a direct download, not a command.
    win = m.speedtest_install_commands("winget")
    assert win == [["winget", "install", "--id", "Ookla.Speedtest.CLI", "-e",
                    "--accept-package-agreements", "--accept-source-agreements"]]
    assert m.speedtest_install_commands("brew") == []
    assert m.speedtest_install_commands("apt") == []


def t_speedtest_update_commands_winget_only():
    assert m.speedtest_update_commands("winget")[0][:3] == ["winget", "upgrade", "--id"]
    assert m.speedtest_update_commands("brew") == []
    assert m.speedtest_update_commands("apt") == []


def t_speedtest_asset_tag_per_os_arch():
    assert m.speedtest_asset_tag("darwin", "arm64") == "macosx-universal"
    assert m.speedtest_asset_tag("darwin", "x86_64") == "macosx-universal"
    assert m.speedtest_asset_tag("linux", "x86_64") == "linux-x86_64"
    assert m.speedtest_asset_tag("linux", "amd64") == "linux-x86_64"
    assert m.speedtest_asset_tag("linux", "aarch64") == "linux-aarch64"
    assert m.speedtest_asset_tag("linux", "arm64") == "linux-aarch64"
    assert m.speedtest_asset_tag("win32", "AMD64") is None     # winget handles Windows
    assert m.speedtest_asset_tag("linux", "ppc64") is None     # unsupported arch


def t_speedtest_download_url():
    url = m.speedtest_download_url("linux-x86_64")
    assert url == ("https://install.speedtest.net/app/cli/"
                   "ookla-speedtest-1.2.0-linux-x86_64.tgz")


def _fake_tgz(binary_bytes=b"#!/bin/echo speedtest\n"):
    """Build an in-memory .tgz holding a `speedtest` member (+ a noise file)."""
    import io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (("speedtest", binary_bytes), ("speedtest.md", b"# doc\n")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0   # deterministic (Date.now()-free)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def t_install_speedtest_binary_verifies_and_extracts(tmp=None):
    import hashlib, tempfile
    blob = _fake_tgz()
    sha = hashlib.sha256(blob).hexdigest()
    d = tempfile.mkdtemp()
    path = m.install_speedtest_binary(
        d, "linux-x86_64", opener=lambda url: blob, downloads={"linux-x86_64": sha})
    assert path == os.path.join(d, "speedtest")
    with open(path, "rb") as fh:
        assert fh.read() == b"#!/bin/echo speedtest\n"
    if os.name != "nt":                          # the +x bit is POSIX-only
        import stat
        assert os.stat(path).st_mode & stat.S_IXUSR


def t_install_speedtest_binary_rejects_bad_checksum():
    import tempfile
    blob = _fake_tgz()
    try:
        m.install_speedtest_binary(
            tempfile.mkdtemp(), "linux-x86_64",
            opener=lambda url: blob, downloads={"linux-x86_64": "deadbeef"})
    except RuntimeError as exc:
        assert "checksum mismatch" in str(exc)
        return
    raise AssertionError("expected a checksum-mismatch RuntimeError")


def t_manual_guide_mentions_speedtest():
    assert "Ookla.Speedtest.CLI" in m.manual_guide("win32")
    assert "speedtest.net/apps/cli" in m.manual_guide("darwin")
    assert "speedtest.net/apps/cli" in m.manual_guide("linux")
    assert "teamookla" not in m.manual_guide("darwin")   # no longer the brew-tap path


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
