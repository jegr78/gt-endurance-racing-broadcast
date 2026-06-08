#!/usr/bin/env python3
"""Build the standalone `iro` and `iro-ui` binaries with PyInstaller and
smoke-test both.  One pair of binaries per OS — run this on the OS you are
targeting (CI runs a 3-OS matrix).
Usage: python3 tools/build-binary.py [--version vX.Y.Z] [--skip-smoke]
Output: dist/bin/iro + dist/bin/iro-ui (+ .exe on Windows; + iro-ui.app on
macOS). The producer ZIP package is a separate artifact built by tools/build.py."""
import argparse, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
# Bundled data, laid out under _MEIPASS/src/ so every script's here-relative
# path resolution (hud.html, assets/, OBS template) keeps working unchanged.
DATA = ["relay", "scripts", "obs", "assets", "companion", "director", "ui", "setup-assets.py"]
# Operator docs the Control Center's Help page serves (iro.DOCS_FILES) — only
# these, kept under src/docs/; the docs/wiki/ subtree stays on GitHub.
DOC_FILES = ["docs/IRO_cheat_sheets.html", "docs/IRO_Broadcast_Setup_Guide.md",
             "docs/README_SETUP.md"]

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
    # ui_jobs.py (loaded via importlib through ui_server.py)
    "uuid",
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


def build_target(launcher, workdir, version_file, sep, entry, name, windowed):
    """Run PyInstaller for one entrypoint. `windowed` builds a no-console app
    (Windows: no console window; macOS: an .app bundle; Linux: ignored). Returns
    the path to the built executable."""
    cmd = launcher + ["--onefile", "--name", name, "--clean", "--noconfirm",
           "--distpath", os.path.join(ROOT, "dist", "bin"),
           "--workpath", os.path.join(workdir, "build", name),
           "--specpath", workdir,
           # services/companion_common/event (+ its imports preflight,
           # install_apps)/tailscale are real frozen modules (iro.py imports them)
           "--paths", os.path.join(SRC, "scripts"),
           "--hidden-import", "services", "--hidden-import", "companion_common",
           "--hidden-import", "event", "--hidden-import", "preflight",
           "--hidden-import", "install_apps", "--hidden-import", "obs_ws",
           "--hidden-import", "tailscale", "--hidden-import", "init_setup",
           "--hidden-import", "native_dialog",
           "--add-data", f"{version_file}{sep}src"]
    if windowed:
        cmd += ["--windowed"]
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
    # The Control Center's Help page serves these three docs (iro.DOCS_FILES).
    # Bundle them under src/docs/ (real dir DEST -> file lands inside) so
    # resource_path("docs/<f>") finds them. The docs/wiki/ subtree is NOT bundled
    # — it lives on GitHub and the Help page links to it.
    for rel in DOC_FILES:
        cmd += ["--add-data", f"{os.path.join(SRC, rel)}{sep}src/docs"]
    cmd.append(os.path.join(SRC, entry))
    print("Running:", " ".join(cmd), flush=True)
    if subprocess.call(cmd) != 0:
        sys.exit(f"pyinstaller failed for {name}.")
    ext = ".exe" if os.name == "nt" else ""
    binary = os.path.join(ROOT, "dist", "bin", name + ext)
    if not os.path.isfile(binary):
        sys.exit(f"expected binary missing: {binary}")
    print(f"Built {binary} ({os.path.getsize(binary) // (1024 * 1024)} MB)")
    return binary


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
    iro_bin = build_target(launcher, workdir, version_file, sep,
                           "iro.py", "iro", windowed=False)
    ui_bin = build_target(launcher, workdir, version_file, sep,
                          "iro_ui.py", "iro-ui", windowed=True)
    if not a.skip_smoke:
        smoke(iro_bin, a.version)
        smoke_ui(ui_bin)


def smoke_ui(binary):
    """The windowed launcher must bind, answer the ping with the Control Center
    signature, run a job through the sibling `iro` binary, and quit. No --version
    check: a windowed Windows build has no stdout. The sibling `iro` lives next
    to this binary in dist/bin/, so the job spawn exercises _iro_job_executable."""
    import json
    import time
    import urllib.request
    env = os.environ.copy()
    env["IRO_UI_PORT"] = "8390"
    ui = subprocess.Popen([binary, "--no-browser"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def _get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:8390{path}", timeout=2) as r:
            return r.read()

    def _post(path):
        return urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:8390{path}", method="POST", data=b"{}"),
            timeout=5).read()

    try:
        body = b""
        for _ in range(20):                  # up to ~10 s to bind
            time.sleep(0.5)
            try:
                body = _get("/api/ping")
                break
            except OSError:
                if ui.poll() is not None:
                    break
        if b"iro-control-center" not in body:
            out = ui.stdout.read().decode("utf-8", "replace") if ui.poll() is not None else ""
            sys.exit(f"smoke iro-ui FAILED: no Control Center ping on :8390 "
                     f"(rc={ui.poll()}) out={out!r}")
        # Start a read-only job (preflight) and confirm it spawns + completes —
        # this proves iro-ui spawns the sibling `iro` binary, not itself.
        # snapshot() returns {"id","op","running","exit_code","cancelled"};
        # /api/jobs/<id> returns {"ok": True, **snap}. A job is done when
        # exit_code is not None (running == False); there is no "done" key.
        job = json.loads(_post("/api/op/preflight"))
        if not job.get("ok") or not job.get("job_id"):
            sys.exit(f"smoke iro-ui FAILED: could not start preflight job ({job!r})")
        jid, snap = job["job_id"], {}
        for _ in range(60):                  # up to ~30 s for preflight to finish
            time.sleep(0.5)
            snap = json.loads(_get(f"/api/jobs/{jid}"))
            if snap.get("exit_code") is not None:
                break
        if snap.get("exit_code") is None:
            sys.exit(f"smoke iro-ui FAILED: preflight job never finished ({snap!r})")
        _post("/api/quit")
        ui.wait(timeout=10)
    finally:
        if ui.poll() is None:
            ui.kill()
    print("Smoke test OK (iro-ui: ping, sibling-iro job, quit).")


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
        su = run(["setup", "--out", imp, "--sheet-id", "smoke"])
        if su.returncode != 0 or not os.path.isfile(imp):
            sys.exit(f"smoke setup FAILED: rc={su.returncode} out={su.stdout!r} err={su.stderr!r}")
        with open(imp, encoding="utf-8") as fh:
            if "_MEI" in fh.read():
                sys.exit("smoke setup FAILED: the localized collection references "
                         "the throwaway _MEIPASS unpack dir (paths die with the process)")
    # `ui` starts the Control Center server in-process from the bundled
    # src/ui/ modules — catches a missing ui/ in DATA (ModuleNotFoundError).
    import json
    import time
    import urllib.request
    env = os.environ.copy()
    env["IRO_UI_PORT"] = "8389"
    ui = subprocess.Popen([binary, "ui", "--no-browser"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        body = b""
        for _ in range(20):                 # up to ~10 s for the server to bind
            time.sleep(0.5)
            try:
                with urllib.request.urlopen("http://127.0.0.1:8389/api/ping",
                                            timeout=2) as r:
                    body = r.read()
                break
            except OSError:
                if ui.poll() is not None:   # crashed before binding
                    break
        if b"iro-control-center" not in body:
            out = ui.stdout.read().decode("utf-8", "replace") if ui.poll() is not None else ""
            sys.exit(f"smoke ui FAILED: no Control Center ping on :8389 "
                     f"(rc={ui.poll()}) out={out!r}")
        # Help page docs must be bundled (DOC_FILES under src/docs/) — catches a
        # regression where the binary lists no local docs / 404s the cheat sheet.
        with urllib.request.urlopen("http://127.0.0.1:8389/api/docs", timeout=2) as r:
            docs = json.loads(r.read())
        if not any(d.get("key") == "cheat-sheet" for d in docs.get("local", [])):
            sys.exit(f"smoke ui FAILED: cheat sheet not bundled (local={docs.get('local')!r})")
        with urllib.request.urlopen("http://127.0.0.1:8389/api/docs/file/cheat-sheet",
                                    timeout=2) as r:
            if b"<html" not in r.read().lower():
                sys.exit("smoke ui FAILED: bundled cheat sheet did not serve as HTML")
        # a markdown doc must come back RENDERED (mdrender bundled + working),
        # not as raw text.
        with urllib.request.urlopen("http://127.0.0.1:8389/api/docs/file/setup-readme",
                                    timeout=2) as r:
            md = r.read().decode("utf-8", "replace")
        if "<!doctype html>" not in md or "<table" not in md:
            sys.exit("smoke ui FAILED: setup-readme markdown was not rendered to HTML")
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8389/api/quit", method="POST", data=b""), timeout=5).read()
        ui.wait(timeout=10)
    finally:
        if ui.poll() is None:
            ui.kill()
    print("Smoke test OK (--version, status, event status, export companion, setup, ui).")


if __name__ == "__main__":
    main()
