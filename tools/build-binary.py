#!/usr/bin/env python3
"""Build the standalone `iro` binary with PyInstaller and smoke-test it.
One binary per OS — run this on the OS you are targeting (CI runs a 3-OS matrix).
Usage: python3 tools/build-binary.py [--version vX.Y.Z] [--skip-smoke]
Output: dist/bin/iro (dist/bin/iro.exe on Windows). The producer ZIP package is
a separate artifact built by tools/build.py."""
import argparse, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
# Bundled data, laid out under _MEIPASS/src/ so every script's here-relative
# path resolution (hud.html, assets/, OBS template) keeps working unchanged.
DATA = ["relay", "scripts", "obs", "assets", "companion", "director", "setup-assets.py"]

# The bundled scripts (relay, oneshots) are loaded at runtime via importlib, so
# PyInstaller's static analyser cannot see their imports.  List every stdlib
# module they use that is NOT already guaranteed by iro.py's own imports.
HIDDEN_STDLIB = [
    # iro-feeds.py
    "http.server", "ipaddress",
    # iro-feeds.py + get-graphics.py + get-media.py
    "urllib.parse", "urllib.request",
    # preflight.py
    "ctypes", "dataclasses", "socket",
    # hud.html data endpoint (iro-feeds.py uses csv, io at module level)
    "csv", "io",
]


def _pyinstaller_cmd():
    """Return the PyInstaller invocation as a list.  Prefers the `pyinstaller`
    executable on PATH; falls back to `python3 -m PyInstaller` when the module
    is importable but the wrapper script is not on PATH (common after a
    --user pip install on macOS)."""
    if shutil.which("pyinstaller"):
        return ["pyinstaller"]
    try:
        import PyInstaller  # noqa: F401 — importability check only
        return [sys.executable, "-m", "PyInstaller"]
    except ImportError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev")
    ap.add_argument("--skip-smoke", action="store_true")
    a = ap.parse_args()
    launcher = _pyinstaller_cmd()
    if launcher is None:
        sys.exit("pyinstaller not found (pip install pyinstaller / brew install pyinstaller).")
    workdir = tempfile.mkdtemp(prefix="iro-build-")
    version_file = os.path.join(workdir, "VERSION")
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(a.version + "\n")
    sep = ";" if os.name == "nt" else ":"
    cmd = launcher + ["--onefile", "--name", "iro", "--clean", "--noconfirm",
           "--distpath", os.path.join(ROOT, "dist", "bin"),
           "--workpath", os.path.join(workdir, "build"),
           "--specpath", workdir,
           # services/companion_common/event (+ its imports preflight,
           # install_apps) are real frozen modules (iro.py imports them)
           "--paths", os.path.join(SRC, "scripts"),
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "install_apps",
           "--add-data", f"{version_file}{sep}src"]
    for mod in HIDDEN_STDLIB:
        cmd += ["--hidden-import", mod]
    for rel in DATA:
        path = os.path.join(SRC, rel)
        # --add-data's DEST is always a target *directory*. A directory source
        # mirrors into src/<rel>, but a FILE must target "src" — "src/<file>"
        # would create a directory named like the file, and the frozen
        # in-process import then dies with EACCES trying to open() it.
        dest = f"src/{rel}" if os.path.isdir(path) else "src"
        cmd += ["--add-data", f"{path}{sep}{dest}"]
    cmd.append(os.path.join(SRC, "iro.py"))
    print("Running:", " ".join(cmd), flush=True)
    if subprocess.call(cmd) != 0:
        sys.exit("pyinstaller failed.")
    binary = os.path.join(ROOT, "dist", "bin", "iro.exe" if os.name == "nt" else "iro")
    if not os.path.isfile(binary):
        sys.exit(f"expected binary missing: {binary}")
    print(f"Built {binary} ({os.path.getsize(binary) // (1024 * 1024)} MB)")
    if not a.skip_smoke:
        smoke(binary, a.version)


def smoke(binary, version):
    """The binary must self-report the version, print aggregate status, and export
    the Companion config — proves bundled data + frozen dispatch actually work."""
    def run(args):
        return subprocess.run([binary] + args, capture_output=True, text=True, timeout=60)

    out = run(["--version"])
    if out.returncode != 0 or version not in out.stdout:
        sys.exit(f"smoke --version FAILED: rc={out.returncode} out={out.stdout!r} err={out.stderr!r}")
    st = run(["status"])
    if st.returncode != 0 or "relay" not in st.stdout:
        sys.exit(f"smoke status FAILED: rc={st.returncode} out={st.stdout!r} err={st.stderr!r}")
    ev = run(["event", "status"])
    if ev.returncode not in (0, 1) or "Go-live" not in ev.stdout:
        sys.exit(f"smoke event status FAILED: rc={ev.returncode} "
                 f"out={ev.stdout!r} err={ev.stderr!r}")
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "iro-buttons.companionconfig")
        ex = run(["export", "companion", "--out", dst])
        if ex.returncode != 0 or not os.path.isfile(dst):
            sys.exit(f"smoke export FAILED: rc={ex.returncode} err={ex.stderr!r}")
        # `setup` loads the bundled setup-assets.py in-process — catches bundle
        # layout regressions (e.g. --add-data turning the file into a directory).
        imp = os.path.join(td, "import.json")
        su = run(["setup", "--out", imp, "--sheet-id", "smoke",
                  "--timer-url", "https://example.com/timer"])
        if su.returncode != 0 or not os.path.isfile(imp):
            sys.exit(f"smoke setup FAILED: rc={su.returncode} out={su.stdout!r} err={su.stderr!r}")
        with open(imp, encoding="utf-8") as fh:
            if "_MEI" in fh.read():
                sys.exit("smoke setup FAILED: the localized collection references "
                         "the throwaway _MEIPASS unpack dir (paths die with the process)")
    print("Smoke test OK (--version, status, event status, export companion, setup).")


if __name__ == "__main__":
    main()
