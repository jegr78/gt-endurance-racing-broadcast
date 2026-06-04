#!/usr/bin/env python3
"""Shared helpers for the iro installer verbs (install-tools, install-apps).
Loaded by both via importlib from the sibling path — works in repo mode, the
test loaders, and the frozen binary (scripts ship as data under _MEIPASS)."""
import os, shutil, subprocess, sys

# Standard Homebrew locations: Apple Silicon, then Intel. A fresh bootstrap is
# NOT on the current process PATH (shellenv only runs in new shells), so brew
# must be invoked via the absolute path find_brew() returns.
BREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
BREW_INSTALLER = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"


def confirmed(answer):
    """True iff the operator's reply means yes."""
    return answer.strip().lower().startswith("y")


def find_brew(which=shutil.which, exists=os.path.exists):
    """Absolute brew invocation path, or None. PATH first, then the standard
    install locations (covers both a fresh bootstrap and an unconfigured PATH)."""
    hit = which("brew")
    if hit:
        return hit
    for path in BREW_PATHS:
        if exists(path):
            return path
    return None


def run_remote_script(url, runner):
    """Download url to a temp file (HTTPS, cert-verified) and run it visibly.
    No shell pipes — the operator saw the URL and confirmed beforehand."""
    import tempfile, urllib.request
    print("Downloading:", url)
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sh")
    try:
        tmp.write(body)
        tmp.close()
        cmd = runner + [tmp.name]
        print("Running:", " ".join(cmd))
        return subprocess.call(cmd)
    finally:
        os.unlink(tmp.name)


def bootstrap_brew(assume_yes, input_fn=input, run=None, find=None):
    """Offer the official brew.sh installer (macOS). Returns the absolute brew
    path on success, None if declined or failed. The installer runs as the
    current user, prompts for sudo itself, and may download the Xcode Command
    Line Tools — a one-time setup that can take a while."""
    run = run_remote_script if run is None else run
    find = find_brew if find is None else find
    print("Homebrew is required but not installed. Official installer:")
    print(" ", BREW_INSTALLER)
    print("  (runs as your user, asks for sudo + RETURN; may download the")
    print("   Xcode Command Line Tools — this one-time setup can take a while)")
    if not assume_yes and not confirmed(input_fn("Bootstrap Homebrew now? [y/N] ")):
        print("aborted.")
        return None
    if run(BREW_INSTALLER, ["/bin/bash"]) != 0:
        return None
    return find()
