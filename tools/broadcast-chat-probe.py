#!/usr/bin/env python3
"""Probe the read-only YouTube broadcast-chat reader against a LIVE channel (#294).

Maintainer / diagnostic tool — NOT shipped. It resolves a channel's currently-live
videoId(s) via yt-dlp and tails each stream's Innertube live chat to the console,
exactly as the relay's BroadcastChatSupervisor does — but standalone (no Google
Sheet, no relay, no UI). Use it to confirm the real yt-dlp + Innertube path works
against a given live stream (the one part the unit suite can only fixture-test)
before wiring a `Channel` tab.

Usage:
    python3 tools/broadcast-chat-probe.py https://www.youtube.com/@LofiGirl
    python3 tools/broadcast-chat-probe.py @SomeChannel --resolve-only
    python3 tools/broadcast-chat-probe.py UCxxxx --cookies runtime/yt-cookies.txt

The parsing reuses src/scripts/broadcast_chat.py (the SAME pure functions the relay
uses — bootstrap, get_live_chat continuation, runs->text); only the network
(yt-dlp subprocess + Innertube HTTP) lives here. A reliable always-live test target
with active chat is e.g. a 24/7 lofi/news stream.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = _load("broadcast_chat", ("src", "scripts", "broadcast_chat.py"))

# Innertube/live_chat 403 the default urllib UA — present a browser UA (matches
# the relay's _YT_CHAT_UA). Public live chat needs no cookies.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def http_get(url, timeout=15):
    try:
        req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except OSError as e:
        print(f"  ! GET failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def http_post_json(url, body, timeout=15):
    try:
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method="POST",
                      headers={"User-Agent": UA, "Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError) as e:
        print(f"  ! POST failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _ytdlp(cmd, timeout=40):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  ! yt-dlp failed: {e}", file=sys.stderr)
        return None


def resolve_live_ids(channel, cookies):
    """Currently-live videoId(s) for a channel: the /streams tab (catches several
    concurrent live streams — the handover overlap), /live as the fallback."""
    cmd = ["yt-dlp", "--flat-playlist", "--no-warnings", "--playlist-items", "1-15", "-J"]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd += ["--", bc.channel_streams_url(channel)]
    r = _ytdlp(cmd)
    ids = []
    if r is not None and r.returncode == 0 and r.stdout:
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = {}
        for e in data.get("entries", []) or []:
            live = isinstance(e, dict) and (
                e.get("live_status") == "is_live" or e.get("is_live") is True)
            if live and e.get("id"):
                ids.append(e["id"])
    if ids:
        return ids
    # Fallback: the single primary /live stream (videoId only).
    cmd = ["yt-dlp", "--print", "id", "--no-warnings", "--no-playlist"]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd += ["--", bc.channel_live_url(channel)]
    r = _ytdlp(cmd)
    if r is not None and r.returncode == 0 and r.stdout.strip():
        return [r.stdout.strip().splitlines()[0]]
    if r is not None and r.stderr.strip():
        print(f"  ! yt-dlp: {r.stderr.strip().splitlines()[-1]}", file=sys.stderr)
    return []


def tail_chat(video_id):
    """Bootstrap the live_chat page, then follow the get_live_chat continuation,
    printing each new message. Returns when the chat/stream closes."""
    bs = bc.parse_bootstrap(http_get(bc.live_chat_page_url(video_id)) or "")
    if not bs["api_key"] or not bs["continuation"]:
        print(f"  ! could not bootstrap chat for {video_id} "
              f"(api_key={bool(bs['api_key'])}, continuation={bool(bs['continuation'])}) — "
              "is the stream live with chat enabled, and public?", file=sys.stderr)
        return
    api_url = bc.get_live_chat_api_url(bs["api_key"])
    cont, ver = bs["continuation"], bs["client_version"]
    print(f"  bootstrap OK (client {ver}); tailing live chat — Ctrl-C to stop\n")
    seen = set()
    while True:
        parsed = bc.parse_live_chat(http_post_json(api_url, bc.build_get_live_chat_body(cont, ver)))
        for m in parsed["messages"]:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            ts = time.strftime("%H:%M:%S", time.localtime(m["ts"])) if m.get("ts") else "--:--:--"
            print(f"  [{ts}] {m.get('user') or 'Viewer'}: {m.get('text')}")
        if not parsed["continuation"]:
            print("\n  (continuation ended — stream / chat closed)")
            return
        cont = parsed["continuation"]
        time.sleep(min(max((parsed["timeout_ms"] or 5000) / 1000.0, 1.0), 8.0))


def main():
    ap = argparse.ArgumentParser(
        description="Probe the YouTube broadcast-chat reader against a live channel (#294).")
    ap.add_argument("channel", help="channel URL / @handle / UC… id")
    ap.add_argument("--cookies", help="Netscape cookies.txt (only for gated streams)")
    ap.add_argument("--resolve-only", action="store_true",
                    help="just resolve and print the live videoId(s), do not tail chat")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)   # stream chat promptly when piped

    if not shutil.which("yt-dlp"):
        sys.exit("ERROR: yt-dlp not on PATH — run `racecast install-tools`.")

    print(f"Resolving live streams for {args.channel} …")
    ids = resolve_live_ids(args.channel, args.cookies)
    if not ids:
        sys.exit("No live stream found — is the channel live right now "
                 "(public, with chat enabled)?")
    print(f"Live videoId(s): {', '.join(ids)}")
    if args.resolve_only:
        return
    if len(ids) > 1:
        print(f"(note: {len(ids)} concurrent live streams — tailing the first; "
              "the relay merges them all)")
    try:
        tail_chat(ids[0])
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
