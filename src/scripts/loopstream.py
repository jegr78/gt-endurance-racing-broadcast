#!/usr/bin/env python3
"""Keep ONE streamlink server alive for one public YouTube or Twitch channel (static mode).
Usage: python3 loopstream.py <CHANNEL_ID_or_URL> <PORT>
  CHANNEL_ID_or_URL: YouTube channel ID (UC…) or a full youtube.com/twitch.tv URL.
Serves http://127.0.0.1:<PORT> for an OBS media source.
YouTube: prefers 1080p, falls to 720p (public direct-streamlink, no yt-dlp/cookies).
Twitch: low-latency streamlink with optional OAuth from machine-level twitch-cookies.txt.
NOTE: PUBLIC channels only. The real (unlisted) flow is the relay (`racecast relay start`).
"""
import os, subprocess, sys, time
from urllib.parse import urlparse


# keep in sync with src/relay/racecast-feeds.py
STREAMLINK_TWITCH = ["--ringbuffer-size", "64M", "--hls-live-edge", "2", "--twitch-low-latency"]


def no_window_kwargs(os_name=None):
    """Popen/call kwargs that stop streamlink from flashing a terminal window on
    Windows. A static feed runs DETACHED (no console — start-streams' spawn_kwargs),
    so the streamlink child otherwise gets a fresh, PERSISTENT console window for
    the whole stint (same class as the relay's per-feed spawn, issue #30). The
    feed's stdout is redirected to a log file by start-streams, so CREATE_NO_WINDOW
    suppresses the window without losing logged output. No-op (empty) off Windows.
    Mirrors services.no_window_kwargs — duplicated so this standalone feed imports
    nothing from its siblings."""
    os_name = os.name if os_name is None else os_name
    if os_name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


# Duplicated from scripts/services.py (this standalone feed imports nothing from
# its siblings); tests/test_services.py cross-checks the copies stay identical.
def external_tool_env(frozen=None, environ=None):
    """Environment for spawning an EXTERNAL native tool (yt-dlp, streamlink,
    ffmpeg, deno, the tailscale CLI) from a possibly PyInstaller-frozen process.

    The onefile bootloader prepends its private _MEIPASS extraction dir to
    LD_LIBRARY_PATH (DYLD_LIBRARY_PATH on macOS) so the BUNDLED interpreter finds
    its own shared libs. An external tool that links the SYSTEM libraries — e.g.
    yt-dlp/streamlink running under the system Python, whose _ssl needs the system
    libcrypto — then mis-loads our older bundled libcrypto and dies with
    "version `OPENSSL_x.y.z' not found" (seen on ARM64 Linux with a system
    Python 3.14). PyInstaller stashes the pre-launch value in <VAR>_ORIG; restore
    it, or drop the var entirely when there was none, so the child sees the real
    system library path. Returns None when not frozen — the caller then inherits
    os.environ unchanged, leaving dev/source runs (which may set LD_LIBRARY_PATH
    legitimately) untouched."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen:
        return None
    env = dict(os.environ if environ is None else environ)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        orig = env.get(var + "_ORIG")
        if orig is not None:
            env[var] = orig
        else:
            env.pop(var, None)
    return env


# keep in sync with src/relay/racecast-feeds.py
def channel_url(entry: str) -> str:
    entry = entry.strip()
    if entry.startswith("http://") or entry.startswith("https://"):
        return entry
    return f"https://www.youtube.com/channel/{entry}/live"


# keep in sync with src/relay/racecast-feeds.py
def platform_of(url):
    """Which streaming platform a (possibly bare-ID-wrapped) URL targets.
    Host-based, reusing the userinfo-safe parse from _is_stream_url. Anything
    that is not a Twitch host (including bare UC ids, which channel_url wraps
    into a youtube.com URL) is treated as YouTube -- the default path."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return "twitch"
    return "youtube"


# keep in sync with src/relay/racecast-feeds.py
def twitch_oauth_from_cookies(path):
    """Extract the Twitch `auth-token` value from a Netscape cookies file, for
    Streamlink's --twitch-api-header. Returns the token or None (public/no auth).
    Pure-ish (reads a file); any error -> None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#") or "\t" not in line:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and parts[5] == "auth-token" and parts[6]:
                    return parts[6]
    except OSError:
        return None
    return None


def runtime_dir(here):
    """Shared runtime/ holding the machine-level twitch-cookies.txt. repo layout
    src/scripts/ -> <repo>/runtime ; distributed package -> next to this script."""
    if os.path.basename(here) == "scripts" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime")
    return here


def streamlink_argv(url, port, platform="youtube", twitch_token=None):
    """streamlink serve argv for one public channel. YouTube: prefer 1080p, fall to
    720p (unchanged). Twitch: served via Streamlink's twitch plugin (low-latency,
    automatic ad-filtering), mirroring the relay's Twitch serve; `--` hardens the
    positional URL."""
    base = ["streamlink", "--player-external-http", "--player-external-http-port", port]
    if platform == "twitch":
        base += STREAMLINK_TWITCH
        if twitch_token:
            base += ["--twitch-api-header", f"Authorization=OAuth {twitch_token}"]
        return base + ["--retry-streams", "15", "--retry-open", "5", "--", url, "best"]
    # YouTube (unchanged): URL + quality positional, then options
    return ["streamlink", url, "1080p60,1080p,720p60,720p",
            "--player-external-http", "--player-external-http-port", port,
            "--ringbuffer-size", "64M", "--hls-live-edge", "4",
            "--retry-streams", "15", "--retry-open", "5"]


def serve_once(url, port, platform="youtube", twitch_token=None, call=subprocess.call):
    """Serve `url` on `port` until streamlink exits; returns its exit code.
    `call` is an injectable seam for the unit test."""
    return call(streamlink_argv(url, port, platform, twitch_token),
                env=external_tool_env(), **no_window_kwargs())


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: loopstream.py <CHANNEL_ID_or_URL> <PORT>")
    ch, port = sys.argv[1], sys.argv[2]
    url = channel_url(ch)
    plat = platform_of(url)
    token = None
    if plat == "twitch":
        token = twitch_oauth_from_cookies(
            os.path.join(runtime_dir(os.path.dirname(os.path.abspath(__file__))), "twitch-cookies.txt"))
    while True:
        print(f">> [{port}] Connecting to {url} ({plat})", flush=True)
        try:
            serve_once(url, port, plat, token)
        except FileNotFoundError:
            sys.exit("ERROR: streamlink not found (brew install streamlink / pip install -U streamlink).")
        print(f">> [{port}] Stream ended or not live. Retrying in 10s...", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
