#!/usr/bin/env python3
"""Download the stream Intro/Outro clips and Intermission Music for OBS.

URL resolution priority per clip:  --intro-url/--outro-url  >  env
RACECAST_INTRO_URL/RACECAST_OUTRO_URL  >  Google Sheet 'Assets' tab (a cell whose
text is 'Intro Video'/'Outro Video', URL in the next non-empty cell to its right).

Intermission Music (--music-url / env RACECAST_INTERMISSION_MUSIC_URL / Assets tab
label 'Intermission Music') is downloaded as intermission.mp3. Accepts a Google
Drive share link (direct download) or any http(s) URL (yt-dlp audio extraction).
A missing music URL is a WARNING, not a failure — the neutral ambient-loop
placeholder is seeded instead.

Clips are written as intro.mp4 / outro.mp4 / intermission.mp3 into the media dir
(repo: <repo>/runtime/media ; distributed package: <package>/media). Never stored
under src/, never committed.

Usage: python3 get-media.py [--which intro|outro|music|both|all] [--out DIR]
       [--sheet-id ID] [--assets-tab NAME] [--intro-url U] [--outro-url U]
       [--music-url U]
"""
import argparse, csv, io, os, re, subprocess, sys, time
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

# src/scripts holds the shared external_tool_env(); add it to sys.path the way
# racecast-feeds.py does so both a bare `python3 src/relay/get-media.py` (source,
# never frozen) and the frozen in-process run resolve it.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_HERE, "..", "scripts"),
              os.path.join(getattr(sys, "_MEIPASS", _HERE), "src", "scripts")):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)
from services import external_tool_env  # de-PyInstaller the env for the yt-dlp spawn
import placeholders  # noqa: E402  (pure stdlib helper — fills a missing clip)


# Single muxed MP4 with audio, capped at 1080p (falls back to best available).
YTDLP_FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"

# Transient-failure retry (#344). YouTube intermittently throws "HTTP Error 403:
# Forbidden" on the media-data fetch (throttling / an expired signed format URL),
# preferentially on the 2nd clip of a batch. A *fresh* yt-dlp invocation
# re-extracts new signed URLs, which is what actually clears the 403, so we retry
# the whole download a few times with a short backoff rather than skipping the clip.
DOWNLOAD_ATTEMPTS = 3                 # total yt-dlp invocations before giving up
RETRY_BACKOFF_SECONDS = (3, 8)        # sleep before retry 2, retry 3, then last value

# Sheet label cell -> output key.
MEDIA_LABELS = {"intro video": "intro", "outro video": "outro"}

# Music asset constants.
MUSIC_LABEL = "intermission music"   # Assets-tab label
MUSIC_KEY = "intermission"           # output basename stem -> intermission.mp3


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


# Drive helpers — copied verbatim from get-graphics.py (kept in sync; the test
# t_drive_helpers_match_get_graphics asserts byte-identical source). Do NOT move
# these into src/scripts/ — see the "duplicated load_dotenv ×4" philosophy.

def is_drive_url(url):
    """True iff the URL's HOST is drive.google.com (or a subdomain). A plain
    substring check would also match e.g. https://evil.example/?drive.google.com."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "drive.google.com" or host.endswith(".drive.google.com")


def drive_id(url):
    """Extract a Google-Drive file ID from a share or download URL, else None."""
    if not url:
        return None
    m = (re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
         or re.search(r"[?&]id=([A-Za-z0-9_-]+)", url))
    return m.group(1) if m else None


def to_download_url(file_id):
    """Direct-download endpoint for a Drive file ID (no API key)."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


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


def music_url_from_csv(rows):
    """Assets-tab rows -> the Intermission-Music URL (Drive link OR YouTube/URL),
    located by a label cell == MUSIC_LABEL (trimmed, case-insensitive); value is
    the next non-empty cell. None if absent."""
    for row in rows:
        for i, cell in enumerate(row):
            if (cell or "").strip().lower() != MUSIC_LABEL:
                continue
            for nxt in row[i + 1:]:
                v = (nxt or "").strip()
                if v:
                    return v
    return None


def music_download_kind(url):
    """'drive' (direct download), 'ytdlp' (audio extract), or 'invalid'."""
    if not (url or "").startswith(("http://", "https://")):
        return "invalid"
    return "drive" if (is_drive_url(url) and drive_id(url)) else "ytdlp"


def build_music_cmd(url, out_path, cookies=None):
    """Argv to extract audio to an mp3 at out_path's dir, stem 'intermission'.
    `--` precedes the URL so a sheet cell starting with '-' cannot be a flag."""
    stem = os.path.join(os.path.dirname(out_path), "intermission.%(ext)s")
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--no-warnings", "-o", stem]
    if cookies and os.path.exists(cookies):
        cmd += ["--cookies", cookies]
    cmd += ["--", url]
    return cmd


def media_dir(here):
    """Where clips live when --out is not given. Mirrors default_runtime_dir():
    repo layout (src/relay/) -> <repo>/runtime/media ; package (relay/) -> <pkg>/media."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "media")
    return os.path.join(os.path.dirname(here), "media")


def seed_missing_media(out_dir, which, want_music=False):
    """Drop the right neutral placeholder for any missing intro.mp4/outro.mp4 (in
    `which`) and intermission.mp3 (when want_music). Returns sorted names written."""
    written = []
    for k in sorted(which):
        written += placeholders.fill_missing(
            [f"{k}.mp4"], out_dir, placeholders.media_placeholder_for(f"{k}.mp4"))
    if want_music:
        written += placeholders.fill_missing(
            ["intermission.mp3"], out_dir,
            placeholders.media_placeholder_for("intermission.mp3"))
    return sorted(written)


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


def run_download(cmd, *, attempts=DOWNLOAD_ATTEMPTS, backoff=RETRY_BACKOFF_SECONDS,
                 runner=None, sleeper=time.sleep, timeout=600, env=None):
    """Run the yt-dlp download `cmd`, retrying a transient failure (a non-zero
    exit such as YouTube's intermittent 'HTTP Error 403' on the media data —
    each fresh invocation re-extracts new signed format URLs, which is what
    clears the 403). `FileNotFoundError` (yt-dlp not installed) and
    `TimeoutExpired` are NOT retried (the latter would mean up to attempts×timeout
    of stall). Returns the runner's result; re-raises the last error after the
    final attempt. `runner`/`sleeper` are injectable for tests."""
    runner = runner or subprocess.run
    for i in range(attempts):
        try:
            return runner(cmd, check=True, timeout=timeout, env=env)
        except subprocess.CalledProcessError:
            if i + 1 >= attempts:
                raise                       # final attempt: propagate the live error
            delay = backoff[min(i, len(backoff) - 1)]
            print(f"  transient download failure (attempt {i + 1}/{attempts}); "
                  f"retrying in {delay}s")
            sleeper(delay)
    raise ValueError("attempts must be >= 1")   # only reachable if attempts <= 0


def download(url, out_path, cookies=None):
    """Download `url` to `out_path` as a single muxed MP4 (audio included).
    Uses yt-cookies.txt if it exists (YouTube bot-check parity with the relay).
    The URL comes from the (multi-editor, semi-trusted) Sheet Assets tab, so it
    must be a real http(s) URL — never a file:// path or a flag-like value.
    Retries a transient yt-dlp failure (e.g. an intermittent HTTP 403)."""
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"refusing non-http(s) media URL: {url!r}")
    cmd = build_download_cmd(url, out_path, cookies)
    run_download(cmd, env=external_tool_env())


def download_drive_file(url, out_path, timeout=120):
    """GET a Drive file to out_path (binary). Handles the large-file confirm
    interstitial. Atomic write. (Music variant of get-graphics.download — no PNG check.)"""
    req = Request(url, headers={"User-Agent": "racecast-media/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    if ctype.startswith("text/html"):
        m = re.search(rb"confirm=([0-9A-Za-z_-]+)", data)
        if not m:
            raise RuntimeError("Drive returned an HTML interstitial with no confirm token")
        req2 = Request(url + "&confirm=" + m.group(1).decode(),
                       headers={"User-Agent": "racecast-media/1.0"})
        with urlopen(req2, timeout=timeout) as resp2:
            data = resp2.read()
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)


def download_music(url, out_path, cookies=None):
    """Download intermission music to out_path (intermission.mp3). Drive link ->
    direct download; otherwise yt-dlp audio extraction. Retries the transient
    yt-dlp failure like the video path."""
    kind = music_download_kind(url)
    if kind == "invalid":
        raise ValueError(f"refusing non-http(s) music URL: {url!r}")
    if kind == "drive":
        download_drive_file(to_download_url(drive_id(url)), out_path)
    else:
        run_download(build_music_cmd(url, out_path, cookies), env=external_tool_env())


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["intro", "outro", "music", "both", "all"],
                    default="all",
                    help="Which assets to fetch: intro, outro, music, both (=intro+outro), "
                         "all (=intro+outro+music, default).")
    ap.add_argument("--out", default=media_dir(here),
                    help="Target dir for intro.mp4 / outro.mp4 / intermission.mp3 "
                         "(default: media_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env RACECAST_SHEET_ID.")
    ap.add_argument("--assets-tab", default="Assets")
    ap.add_argument("--intro-url", default=None)
    ap.add_argument("--outro-url", default=None)
    ap.add_argument("--music-url", default=None,
                    help="Intermission Music URL (Drive link or yt-dlp-compatible). "
                         "Default: env RACECAST_INTERMISSION_MUSIC_URL or Assets tab.")
    a = ap.parse_args()

    # Determine video clip set and music flag.
    if a.which in ("both", "all"):
        which = {"intro", "outro"}
    elif a.which == "music":
        which = set()
    else:
        which = {a.which}
    want_music = a.which in ("all", "music")

    cli = {"intro": a.intro_url, "outro": a.outro_url}

    # Only hit the sheet if a CLI/env URL is missing for something we need.
    csv_text = None
    need_sheet = (
        any(not (cli.get(k) or os.environ.get(f"RACECAST_{k.upper()}_URL")) for k in which)
        or (want_music and not (a.music_url or os.environ.get("RACECAST_INTERMISSION_MUSIC_URL")))
    )
    if need_sheet and a.sheet_id:
        try:
            csv_text = fetch_assets_csv(a.sheet_id, a.assets_tab)
        except Exception as e:
            print(f"WARNING: could not read sheet Assets tab: {e}")

    # Resolve music URL: CLI > env > sheet.
    music_url = (
        a.music_url
        or os.environ.get("RACECAST_INTERMISSION_MUSIC_URL")
        or (music_url_from_csv(list(csv.reader(io.StringIO(csv_text)))) if csv_text else None)
    )

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

    # Download intermission music (missing URL -> WARNING only, placeholder seeded below).
    if want_music:
        out_music = os.path.join(a.out, "intermission.mp3")
        if not music_url:
            print("WARNING: no Intermission Music URL "
                  "(sheet label 'Intermission Music' / --music-url / "
                  "RACECAST_INTERMISSION_MUSIC_URL); placeholder will be seeded.")
        else:
            print(f"Downloading intermission music: {music_url}")
            try:
                download_music(music_url, out_music, cookies)
                print(f"OK -> {out_music}")
            except FileNotFoundError:
                sys.exit("ERROR: yt-dlp not found (brew install yt-dlp / pip install -U yt-dlp).")
            except subprocess.TimeoutExpired:
                print("WARNING: intermission music download timed out (600 s).")
            except Exception as e:
                print(f"WARNING: intermission music download failed: {e}")

    seeded = seed_missing_media(a.out, which, want_music=want_music)
    if seeded:
        print(f"Wrote neutral placeholder for {len(seeded)} missing: "
              f"{', '.join(seeded)}")

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
