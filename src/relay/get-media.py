#!/usr/bin/env python3
"""Download the stream Intro/Outro clips for OBS from YouTube.

URL resolution priority per clip:  --intro-url/--outro-url  >  env
IRO_INTRO_URL/IRO_OUTRO_URL  >  Google Sheet 'Assets' tab (a cell whose
text is 'Intro Video'/'Outro Video', URL in the next non-empty cell to its right).

Clips are written as intro.mp4 / outro.mp4 into the media dir (repo:
<repo>/runtime/media ; distributed package: <package>/media). Never stored
under src/, never committed.

Usage: python3 get-media.py [--which intro|outro|both] [--out DIR]
       [--sheet-id ID] [--assets-tab NAME] [--intro-url U] [--outro-url U]
"""
import argparse, csv, io, os, subprocess, sys
from urllib.parse import quote
from urllib.request import Request, urlopen

# Single muxed MP4 with audio, capped at 1080p (falls back to best available).
YTDLP_FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

# Sheet label cell -> output key.
MEDIA_LABELS = {"intro video": "intro", "outro video": "outro"}


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with
    a .git/.env.example marker). KEEP IN SYNC with the copies in iro-feeds.py and
    setup-assets.py."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, mk)) for mk in (".git", ".env.example")):
            candidates.append(d)
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def media_urls_from_csv(rows):
    """Assets-tab rows -> {'intro': url, 'outro': url} (only found keys).
    Located by label cell so column positions can move: a cell equal (trimmed,
    case-insensitive) to a MEDIA_LABELS key marks the row; the value is the next
    non-empty cell to its right."""
    out = {}
    for row in rows:
        for i, cell in enumerate(row):
            key = MEDIA_LABELS.get((cell or "").strip().lower())
            if not key:
                continue
            for nxt in row[i + 1:]:
                v = (nxt or "").strip()
                if v:
                    out[key] = v
                    break
    return out


def media_dir(here):
    """Where clips live when --out is not given. Mirrors default_runtime_dir():
    repo layout (src/relay/) -> <repo>/runtime/media ; package (relay/) -> <pkg>/media."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "media")
    return os.path.join(os.path.dirname(here), "media")


def resolve_urls(which, cli, env, csv_text):
    """Resolve a URL per key in `which` (a set of 'intro'/'outro').
    Priority: cli[key]  >  env['IRO_<KEY>_URL']  >  sheet label lookup.
    `csv_text` may be None (sheet not fetched)."""
    sheet = media_urls_from_csv(list(csv.reader(io.StringIO(csv_text)))) if csv_text else {}
    out = {}
    for key in which:
        out[key] = (cli.get(key) or env.get(f"IRO_{key.upper()}_URL") or sheet.get(key))
    return out


def fetch_assets_csv(sheet_id, tab, timeout=15):
    """Fetch the Assets tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "iro-media/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(url, out_path, cookies=None):
    """Download `url` to `out_path` as a single muxed MP4 (audio included).
    Uses cookies.txt if it exists (YouTube bot-check parity with the relay)."""
    cmd = ["yt-dlp", "-f", YTDLP_FORMAT, "--merge-output-format", "mp4",
           "--no-warnings", "-o", out_path, url]
    if cookies and os.path.exists(cookies):
        cmd[1:1] = ["--cookies", cookies]
    subprocess.run(cmd, check=True, timeout=600)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["intro", "outro", "both"], default="both")
    ap.add_argument("--out", default=media_dir(here),
                    help="Target dir for intro.mp4 / outro.mp4 (default: media_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env IRO_SHEET_ID.")
    ap.add_argument("--assets-tab", default="Assets")
    ap.add_argument("--intro-url", default=None)
    ap.add_argument("--outro-url", default=None)
    a = ap.parse_args()

    which = {"intro", "outro"} if a.which == "both" else {a.which}
    cli = {"intro": a.intro_url, "outro": a.outro_url}

    # Only hit the sheet if a CLI/env URL is missing for something we need.
    csv_text = None
    need_sheet = any(not (cli.get(k) or os.environ.get(f"IRO_{k.upper()}_URL")) for k in which)
    if need_sheet and a.sheet_id:
        try:
            csv_text = fetch_assets_csv(a.sheet_id, a.assets_tab)
        except Exception as e:
            print(f"WARNING: could not read sheet Assets tab: {e}")

    urls = resolve_urls(which, cli, os.environ, csv_text)
    os.makedirs(a.out, exist_ok=True)
    # cookies.txt lives in the runtime dir (next to the default media dir),
    # independent of --out, matching get-cookies.py / iro-feeds.py.
    cookies = os.path.join(os.path.dirname(media_dir(here)), "cookies.txt")

    failed = []
    for key in sorted(which):
        url = urls.get(key)
        if not url:
            print(f"WARNING: no URL for {key} "
                  f"(sheet label '{key.title()} Video' / --{key}-url / IRO_{key.upper()}_URL)")
            failed.append(key)
            continue
        out_path = os.path.join(a.out, f"{key}.mp4")
        print(f"Downloading {key}: {url}")
        try:
            download(url, out_path, cookies)
            print(f"OK -> {out_path}")
        except FileNotFoundError:
            sys.exit("ERROR: yt-dlp not found (brew install yt-dlp / pip install -U yt-dlp).")
        except subprocess.TimeoutExpired:
            print(f"WARNING: download timed out for {key} (600 s).")
            failed.append(key)
        except Exception as e:
            print(f"WARNING: download failed for {key}: {e}")
            failed.append(key)

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
