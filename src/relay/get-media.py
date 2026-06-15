#!/usr/bin/env python3
"""Download the stream Intro/Outro clips for OBS from YouTube.

URL resolution priority per clip:  --intro-url/--outro-url  >  env
RACECAST_INTRO_URL/RACECAST_OUTRO_URL  >  Google Sheet 'Assets' tab (a cell whose
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


# Duplicated from scripts/services.py (this standalone script imports nothing
# from scripts/); tests/test_services.py cross-checks the copies stay identical.
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

# Single muxed MP4 with audio, capped at 1080p (falls back to best available).
YTDLP_FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

# Sheet label cell -> output key.
MEDIA_LABELS = {"intro video": "intro", "outro video": "outro"}


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with
    a .git/.env.example marker). KEEP IN SYNC with the copies in racecast-feeds.py and
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
            with open(p, encoding="utf-8") as fh:
                for line in fh:
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
    Priority: cli[key]  >  env['RACECAST_<KEY>_URL']  >  sheet label lookup.
    `csv_text` may be None (sheet not fetched)."""
    sheet = media_urls_from_csv(list(csv.reader(io.StringIO(csv_text)))) if csv_text else {}
    out = {}
    for key in which:
        out[key] = (cli.get(key) or env.get(f"RACECAST_{key.upper()}_URL") or sheet.get(key))
    return out


def fetch_assets_csv(sheet_id, tab, timeout=15):
    """Fetch the Assets tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "racecast-media/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def build_download_cmd(url, out_path, cookies=None):
    """Argv for downloading one clip. `--` precedes the URL so a sheet cell
    beginning with '-' cannot be parsed as a yt-dlp flag (e.g. --exec, which
    would be arbitrary command execution). Cookies are inserted before the
    separator so they stay an option."""
    cmd = ["yt-dlp", "-f", YTDLP_FORMAT, "--merge-output-format", "mp4",
           "--no-warnings", "-o", out_path]
    if cookies and os.path.exists(cookies):
        cmd += ["--cookies", cookies]
    cmd += ["--", url]
    return cmd


def download(url, out_path, cookies=None):
    """Download `url` to `out_path` as a single muxed MP4 (audio included).
    Uses yt-cookies.txt if it exists (YouTube bot-check parity with the relay).
    The URL comes from the (multi-editor, semi-trusted) Sheet Assets tab, so it
    must be a real http(s) URL — never a file:// path or a flag-like value."""
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"refusing non-http(s) media URL: {url!r}")
    cmd = build_download_cmd(url, out_path, cookies)
    subprocess.run(cmd, check=True, timeout=600, env=external_tool_env())


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["intro", "outro", "both"], default="both")
    ap.add_argument("--out", default=media_dir(here),
                    help="Target dir for intro.mp4 / outro.mp4 (default: media_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env RACECAST_SHEET_ID.")
    ap.add_argument("--assets-tab", default="Assets")
    ap.add_argument("--intro-url", default=None)
    ap.add_argument("--outro-url", default=None)
    a = ap.parse_args()

    which = {"intro", "outro"} if a.which == "both" else {a.which}
    cli = {"intro": a.intro_url, "outro": a.outro_url}

    # Only hit the sheet if a CLI/env URL is missing for something we need.
    csv_text = None
    need_sheet = any(not (cli.get(k) or os.environ.get(f"RACECAST_{k.upper()}_URL")) for k in which)
    if need_sheet and a.sheet_id:
        try:
            csv_text = fetch_assets_csv(a.sheet_id, a.assets_tab)
        except Exception as e:
            print(f"WARNING: could not read sheet Assets tab: {e}")

    urls = resolve_urls(which, cli, os.environ, csv_text)
    os.makedirs(a.out, exist_ok=True)
    # yt-cookies.txt lives in the runtime dir (next to the default media dir),
    # independent of --out, matching get-cookies.py / racecast-feeds.py.
    # Fall back to legacy cookies.txt on not-yet-migrated installs (read-only).
    _ck = os.path.join(os.path.dirname(media_dir(here)), "yt-cookies.txt")
    cookies = _ck if os.path.exists(_ck) else os.path.join(os.path.dirname(media_dir(here)), "cookies.txt")

    failed = []
    for key in sorted(which):
        url = urls.get(key)
        if not url:
            print(f"WARNING: no URL for {key} "
                  f"(sheet label '{key.title()} Video' / --{key}-url / RACECAST_{key.upper()}_URL)")
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
