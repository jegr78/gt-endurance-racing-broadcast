#!/usr/bin/env python3
"""Export YouTube cookies from a logged-in browser to <runtime>/cookies.txt via yt-dlp
(against YouTube's "Sign in to confirm you're not a bot" check).

Usage: python3 get-cookies.py [browser] [--runtime-dir DIR]
  browser: firefox | chrome | safari | edge | brave   (default: firefox)
Default runtime dir auto-detects: repo -> <repo>/runtime, distributed package -> next to relay/.
"""
import argparse, os, re, subprocess, sys


def default_runtime_dir(here):
    """Match iro-feeds.py: repo layout (src/relay/) -> <repo>/runtime ; dist (relay/) -> here."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime")
    return here


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("browser", nargs="?", default="firefox")
    ap.add_argument("--runtime-dir", default=default_runtime_dir(here))
    a = ap.parse_args()
    os.makedirs(a.runtime_dir, exist_ok=True)
    try: os.chmod(a.runtime_dir, 0o700)   # runtime holds the cookie jar — keep it private
    except OSError: pass
    out = os.path.join(a.runtime_dir, "cookies.txt")
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    print(f"Exporting YouTube cookies from '{a.browser}' ...")
    try:
        subprocess.run(["yt-dlp", "--cookies-from-browser", a.browser, "--cookies", out,
                        "--skip-download", "--no-warnings", url],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except FileNotFoundError:
        sys.exit("ERROR: yt-dlp not found (brew install yt-dlp / pip install -U yt-dlp).")
    except subprocess.TimeoutExpired:
        sys.exit("ERROR: cookie export timed out (approve the Keychain prompt?).")
    if os.path.exists(out):
        try: os.chmod(out, 0o600)   # live YouTube session — owner-only
        except OSError: pass
        txt = open(out, encoding="utf-8", errors="replace").read()
        if re.search(r"LOGIN_INFO|SAPISID|__Secure-[0-9]?PSID", txt):
            print(f"OK -> {out}  (logged-in session detected)")
        else:
            print(f"WARNING: cookies written but no login found — log into YouTube in "
                  f"'{a.browser}' and re-run.")
    else:
        sys.exit(f"FAILED to export from '{a.browser}'. Installed + logged into YouTube?")


if __name__ == "__main__":
    main()
