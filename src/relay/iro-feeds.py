#!/usr/bin/env python3
"""
iro-feeds.py — Relay mode for the IRO broadcast (2-feed ping-pong)
with a remotely-maintainable stint schedule from a Google Sheet.

Concept: exactly one commentator stream per stint. Two fixed OBS feeds
(Feed A = port 53001, Feed B = port 53002) "walk" along a stint schedule.
Feed A serves the odd stints (1,3,5…), Feed B the even ones (2,4,6…) when
starting from stint 1 — with `--stint N` (producer takeover) the same
ping-pong simply starts at stint N on Feed A. At each handover the feed
that is currently NOT on air advances to its next commentator.

OBS stays untouched: the media sources keep pointing at
http://127.0.0.1:53001 / :53002 — only the channel behind them changes.

SCHEDULE SOURCE (Google Sheet, editable remotely by anyone):
  The "Schedule" tab of the shared HUD sheet is read via CSV export
  (no API key). Any column holds the channel IDs (UC…) OR full URLs in
  stint order — the channel column is auto-detected (other columns such
  as stint number / commentator name are ignored).
  Requirement: the sheet is shared "Anyone with the link: Viewer"
  (same as the HUD sheet).

  Safe live behavior: a RUNNING feed is NOT torn off mid-stint by sheet
  edits. Changed entries take effect on the next /next (handover), where
  fresh data is fetched. To swap the CURRENT stream immediately, use /reload.

  If the sheet is unreachable, the last working list is kept (last-good +
  local cache); without a sheet the local schedule.txt is used.

COOKIES (against YouTube's "Sign in to confirm you're not a bot"):
  Put a cookies.txt (Netscape format, exported from a logged-in YouTube
  browser, e.g. via the "Get cookies.txt LOCALLY" extension) NEXT TO this
  script — it is auto-detected and passed to Streamlink (--http-cookies-file).
  Or pass it explicitly:  --cookies /path/to/cookies.txt
  Always enter UNLISTED streams as a watch URL (https://www.youtube.com/watch?v=…)
  in the schedule — the channel /live URL only works for PUBLIC streams.

Controls (HTTP, for Companion Generic-HTTP / browser / curl):
  GET /status          -> state of both feeds + source/sheet health (JSON)
  GET /next            -> fetch fresh & advance the off-air feed by 1 stint
  GET /next/A | /B      -> advance Feed A or B specifically
  GET /prev/A | /B      -> step back one (correction)
  GET /set/A/<n> | /B   -> pin Feed A/B to schedule index <n>
  GET /set/stint/<n>   -> producer takeover: stint <n> (1-based!) is on air now —
                           Feed A serves it, Feed B preloads <n+1> (tears running feeds)
  GET /reload          -> reconnect both feeds (applies a sheet change to the
                           CURRENT channel immediately)
  GET /reload/A | /B    -> reconnect only Feed A or B
  GET /pov/reload      -> re-read the POV sheet cell & (re)connect the POV PiP feed
  GET /pov/stop        -> stop the POV PiP pull (close port 53003, free bandwidth)
  Stop: Ctrl+C
"""

import argparse, csv, io, ipaddress, json, os, re, shutil, signal, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen

# ---------- Configuration ----------
# Pipeline: yt-dlp resolves the live HLS URL (passes YouTube's bot-check via
# cookies + JS-challenge solving) -> streamlink serves that direct URL to OBS
# (no YouTube plugin involved, so no bot-check on the serving side).
YTDLP_FORMAT = "b[height<=1080]/b"   # prefer <=1080p, auto-fall back to lower
YTDLP_FORMAT_POV = "b[height<=720]/b"  # driver-POV is shown small (PiP) -> cap at 720p
STREAMLINK_SERVE = ["--ringbuffer-size", "64M", "--hls-live-edge", "4"]
RESOLVE_RETRY = 15  # seconds between yt-dlp resolve attempts while a stint isn't live
RETRY_SLEEP = 10    # seconds after a stream ends / manifest expires before re-resolving
# Sheet ID is NOT hardcoded — it comes from IRO_SHEET_ID (env or a gitignored
# .env at the repo/package root). See .env.example. Override per-run with --sheet-id.
DEFAULT_SHEET_TAB = "Schedule"
DEFAULT_POV_TAB = "POV"

# ---------- Network bind resolution (auto dual-bind: localhost + Tailscale) ----
# OBS always reaches the control/HUD server on 127.0.0.1 (a fixed, machine-
# independent address — never edit the OBS collection). With --bind auto
# (the default) the server ALSO binds the machine's Tailscale IP so remote
# directors/tablets reach /panel + /hud over the tailnet — without exposing the
# unauthenticated server on the local LAN the way 0.0.0.0 would.
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's IPv4 range
# Candidate Tailscale CLI locations (PATH first, then the platform installers).
_TAILSCALE_BINS = [
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",  # macOS GUI app
    "/usr/bin/tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
]


def _in_cgnat(ip):
    """True iff ip is a valid IPv4 address inside Tailscale's 100.64.0.0/10 range."""
    try:
        return ipaddress.ip_address(ip) in _CGNAT_NET
    except ValueError:
        return False


def parse_tailscale_status(output):
    """Self's first CGNAT IPv4 from `tailscale status --json`, or None.

    Requires BackendState == "Running": a stopped/disconnected node keeps its
    assigned tailnet IP, so `tailscale ip -4` alone reports "connected" even
    after the user toggled Tailscale off."""
    try:
        data = json.loads(output)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("BackendState") != "Running":
        return None
    for ip in (data.get("Self") or {}).get("TailscaleIPs") or []:
        if _in_cgnat(str(ip)):
            return str(ip)
    return None


def detect_tailscale_ip():
    """This machine's connected Tailscale IPv4 via the CLI, or None if the
    Tailscale backend is unavailable, stopped, or logged out.

    Deliberate divergence from scripts/tailscale.py's tailscale_backend():
    this detection-only copy keeps trying further binaries until one reports
    a Running IP, while the state-aware version stops at the first binary
    that answers at all (its callers need Stopped/NeedsLogin, not just the IP)."""
    for binary in _TAILSCALE_BINS:
        try:
            out = subprocess.run([binary, "status", "--json"], capture_output=True,
                                 text=True, errors="replace", timeout=3)
        except (OSError, subprocess.SubprocessError):
            continue
        ip = parse_tailscale_status(out.stdout)
        if ip:
            return ip
    return None


def resolve_bind_addresses(bind_arg, tailscale_ip):
    """Map the --bind value (+ a detected Tailscale IP) to bind addresses.

    'auto'  -> 127.0.0.1 plus the Tailscale IP when present (localhost only if not).
    localhost/127.0.0.1 -> [127.0.0.1].
    anything else (e.g. 0.0.0.0 or a specific IP) -> taken literally.
    """
    if bind_arg == "auto":
        addrs = ["127.0.0.1"]
        if tailscale_ip and tailscale_ip not in addrs:
            addrs.append(tailscale_ip)
        return addrs
    if bind_arg in ("127.0.0.1", "localhost"):
        return ["127.0.0.1"]
    return [bind_arg]

SCHEDULE_TEMPLATE = (
    "# IRO relay offline fallback schedule — used ONLY if the Google Sheet AND the\n"
    "# last-good cache are both unavailable. One entry per stint, in order:\n"
    "#   a YouTube channel ID (UC...) OR a full watch URL (https://www.youtube.com/watch?v=...).\n"
    "# Lines starting with # are ignored. The real schedule lives in the Sheet tab 'Schedule'.\n"
    "# Example:\n"
    "#   https://www.youtube.com/watch?v=VIDEOID_STINT_1\n"
    "#   UCxxxxxxxxxxxxxxxxxxxxxx\n"
)

CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_\-]{20,}$")
ASSET_KEY_RE = re.compile(r"^[a-z0-9-]+$")
# Resolution order when a HUD asset is requested by key (no extension).
ASSET_EXTS = (("png", "image/png"), ("svg", "image/svg+xml"),
              ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("webp", "image/webp"))
# Identity whitelist: the handler re-derives the Content-Type header value from
# this constant map, so a request-derived string can never reach send_header().
ASSET_CTYPES = {ctype: ctype for _, ctype in ASSET_EXTS}


def resolve_asset(assets_dir, sub, key):
    """Resolve a HUD asset by key (no extension) to (path, content_type).
    Tries known image extensions in order; returns None if nothing matches or
    inputs are unsafe (subdir whitelist + strict key + realpath containment =
    no path traversal)."""
    if not assets_dir or sub not in ("flags", "brands") or not ASSET_KEY_RE.match(key):
        return None
    base = os.path.realpath(os.path.join(assets_dir, sub))
    for ext, ctype in ASSET_EXTS:
        path = os.path.realpath(os.path.join(base, f"{key}.{ext}"))
        # Belt-and-braces on top of the strict key regex: the resolved path
        # must stay inside the whitelisted asset subdir (also cuts the CodeQL
        # taint path from the request URL into open()).
        if not path.startswith(base + os.sep):
            return None
        if os.path.exists(path):
            return path, ctype
    return None

def default_runtime_dir(here):
    """Where runtime data lives when --runtime-dir is not given.
    Repo layout (src/relay/) -> <repo>/runtime ; distributed package (relay/) -> next to the script.
    Keeps get-cookies.py and the relay consistent without an explicit flag."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime")
    return here


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root
    into os.environ. Real environment variables win (setdefault). Returns the
    path loaded, or None. Tiny on purpose — no python-dotenv dependency.

    SECURITY: bounded to the project. The project root is the nearest ancestor
    holding a .git/.env.example marker; we only ever read a .env from `start`
    or from that root, never from an unrelated parent (e.g. a stray
    ~/Downloads/.env that could inject HTTPS_PROXY/DYLD_* into the
    cookie-bearing yt-dlp/streamlink subprocesses)."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, m)) for m in (".git", ".env.example")):
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


def is_channel(v: str) -> bool:
    v = v.strip()
    return bool(CHANNEL_RE.match(v)) or v.startswith("http://") or v.startswith("https://")

def asset_key(s):
    """Normalize free text (country/brand) to an asset filename stem."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9-]", "", s)

OVERLAY_LABELS = {
    "stint": "stint", "streamer": "streamer", "session": "session",
    "round top": "round_top", "round bottom": "country",
    "race control": "race_control",
}


def _first_value(row, start=2):
    for c in range(start, len(row)):
        v = (row[c] or "").strip()
        if v:
            return v
    return ""


def parse_overlay(text):
    """Overlay tab CSV -> {streamer, session, round_top, country,
    race_control, teams:[p1,p2,p3]}. Label is column B; value is the first
    non-empty cell from column C on."""
    out = {v: "" for v in OVERLAY_LABELS.values()}
    teams = {"teams p1": 0, "teams p2": 1, "teams p3": 2}
    out["teams"] = ["", "", ""]
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        label = (row[1] or "").strip().lower()
        if label in OVERLAY_LABELS:
            out[OVERLAY_LABELS[label]] = _first_value(row)
        elif label in teams:
            out["teams"][teams[label]] = _first_value(row)
    return out


# Accepted headers for the team's brand TEXT column (priority order). The sheet's
# image columns ("Brand Logo", "Brands") are deliberately NOT in this set.
BRAND_TEXT_HEADERS = ("brand key", "brand name", "brand")


def parse_config_brands(text):
    """Configuration tab CSV -> {team_name: brand_key}. Columns are located by
    header name ('Teams' + one of BRAND_TEXT_HEADERS) so positions can change."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}
    header = [(h or "").strip().lower() for h in rows[0]]
    if "teams" not in header:
        return {}
    ti = header.index("teams")
    bi = next((header.index(h) for h in BRAND_TEXT_HEADERS if h in header), None)
    if bi is None:
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) <= max(ti, bi):
            continue
        name = (row[ti] or "").strip()
        brand = asset_key(row[bi])
        if name and brand:
            out[name] = brand
    return out


def build_hud_data(overlay, brands):
    """Combine an Overlay map + {team: brand_key} into the /hud/data contract."""
    return {
        "stint": overlay.get("stint", ""),
        "streamer": overlay.get("streamer", ""),
        "session": overlay.get("session", ""),
        "round": {
            "top": overlay.get("round_top", ""),
            "country": overlay.get("country", ""),
            "flagKey": asset_key(overlay.get("country", "")),
        },
        "teams": [{"name": n, "brandKey": brands.get(n, "")}
                  for n in overlay.get("teams", ["", "", ""])],
        "raceControl": overlay.get("race_control", ""),
    }

def channel_url(entry: str) -> str:
    entry = entry.strip()
    if entry.startswith("http://") or entry.startswith("https://"):
        return entry
    return f"https://www.youtube.com/channel/{entry}/live"


def resolve_hls(url, cookies, logfile, fmt=YTDLP_FORMAT):
    """Resolve a YouTube live URL to a direct HLS manifest URL via yt-dlp
    (handles cookies + the bot-check). Returns the URL or None (not live / failed)."""
    cmd = ["yt-dlp", "-g", "-f", fmt, "--no-warnings", "--no-playlist", url]
    if cookies:
        cmd += ["--cookies", cookies]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=90)
    except FileNotFoundError:
        # Startup checks for yt-dlp; reaching here means it vanished mid-run.
        try:
            with open(logfile, "a", encoding="utf-8") as log:
                log.write("   yt-dlp not found on PATH\n")
        except Exception:
            pass  # logging is best-effort; never let it break the resolve loop
        return None
    except subprocess.TimeoutExpired:
        return None
    out = [l for l in (r.stdout or "").splitlines() if l.startswith("http")]
    if out:
        return out[0]
    try:
        with open(logfile, "a", encoding="utf-8") as log:
            err = (r.stderr or "").strip().splitlines()
            log.write(f"   yt-dlp could not resolve {url} ({err[-1] if err else 'not live?'})\n")
    except Exception:
        pass  # logging is best-effort; never let it break the resolve loop
    return None


def stint_start_indices(stint, schedule_len):
    """0-based (A, B) start indices for a producer takeover: 1-based stint
    <stint> is on air NOW -> Feed A serves it, Feed B preloads the next one.
    Both clamped to the schedule (last stint / empty schedule -> A == B)."""
    stint = max(1, int(stint))
    hi = max(0, schedule_len - 1)
    return min(stint - 1, hi), min(stint, hi)


class ScheduleSource:
    """Reads the schedule from the Google Sheet (CSV) with last-good + fallback."""
    def __init__(self, csv_url, cache_path, local_fallback):
        self.csv_url = csv_url
        self.cache_path = cache_path
        self.local_fallback = local_fallback
        self.lock = threading.Lock()
        self.items = []
        self.last_ok = None
        self.last_error = None

    @staticmethod
    def _parse_csv(text):
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return None
        ncols = max((len(r) for r in rows), default=0)
        best_col, best_cnt = None, 0
        for c in range(ncols):
            cnt = sum(1 for r in rows if len(r) > c and is_channel(r[c]))
            if cnt > best_cnt:
                best_cnt, best_col = cnt, c
        if best_col is None or best_cnt == 0:
            return None
        items = [r[best_col].strip() for r in rows
                 if len(r) > best_col and is_channel(r[best_col])]
        return items or None

    def fetch(self, timeout=15):
        if not self.csv_url:
            return None
        try:
            req = Request(self.csv_url, headers={"User-Agent": "iro-feeds/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            items = self._parse_csv(text)
            if not items:
                self.last_error = ("Sheet reachable, but no channel IDs found "
                                   "(correct tab name? a column with UC… IDs / watch URLs? sharing?)")
                return None
            return items
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def refresh(self, timeout=15):
        items = self.fetch(timeout)
        if items:
            with self.lock:
                self.items = items
                self.last_ok = time.time()
                self.last_error = None
            try:
                with open(self.cache_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(items) + "\n")
            except Exception:
                pass  # cache write is best-effort; the in-memory schedule is current
            return True
        return False

    def load_initial(self, template=None):
        if self.refresh():
            print(f"Schedule loaded from Google Sheet: {len(self.items)} stints.")
            return
        # Sheet unreachable -> cache, then a user-filled local fallback
        for path, label in ((self.cache_path, "cache"), (self.local_fallback, "local schedule.txt")):
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    items = [l.split("#", 1)[0].strip() for l in fh]
                items = [i for i in items if i]
                if items:
                    with self.lock:
                        self.items = items
                    print(f"WARN: sheet unreachable ({self.last_error}). "
                          f"Using {label}: {len(items)} stints.")
                    return
        # Nothing available: drop a commented template (if missing) and explain.
        if template and self.local_fallback and not os.path.exists(self.local_fallback):
            try:
                os.makedirs(os.path.dirname(self.local_fallback), exist_ok=True)
                with open(self.local_fallback, "w", encoding="utf-8") as fh:
                    fh.write(template)
                print(f"Wrote a fallback template to {self.local_fallback}")
            except OSError:
                pass  # template is a convenience; the sys.exit below explains anyway
        sys.exit(f"ERROR: no schedule available. Sheet error: {self.last_error}\n"
                 f"Check tab '{DEFAULT_SHEET_TAB}', sharing (Anyone with the link: Viewer), "
                 f"or fill {self.local_fallback}.")

    def get(self):
        with self.lock:
            return list(self.items)

    def health(self):
        with self.lock:
            n = len(self.items)
        return {"count": n,
                "last_ok_age_s": (round(time.time() - self.last_ok, 1) if self.last_ok else None),
                "last_error": self.last_error}


class HudSource:
    """Reads the Overlay + Configuration tabs and serves the /hud/data dict
    with last-good caching (mirrors ScheduleSource robustness)."""
    EMPTY = {"stint": "", "streamer": "", "session": "",
             "round": {"top": "", "country": "", "flagKey": ""},
             "teams": [{"name": "", "brandKey": ""}] * 3, "raceControl": ""}

    def __init__(self, overlay_url, config_url, cache_path):
        self.overlay_url = overlay_url
        self.config_url = config_url
        self.cache_path = cache_path
        self.lock = threading.Lock()
        self._data = None
        self.last_ok = None
        self.last_error = None
        self._load_cache()

    @staticmethod
    def _fetch(url, timeout=10):
        req = Request(url, headers={"User-Agent": "iro-feeds/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (OSError, ValueError):
            self._data = None

    def refresh(self, timeout=10):
        try:
            overlay = parse_overlay(self._fetch(self.overlay_url, timeout))
            brands = parse_config_brands(self._fetch(self.config_url, timeout))
            data = build_hud_data(overlay, brands)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            self._data = data
            self.last_ok = time.time()
            self.last_error = None
        try:
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass  # cache write is best-effort; the in-memory HUD data is current
        return True

    def data(self):
        with self.lock:
            return self._data if self._data is not None else dict(self.EMPTY)

    def health(self):
        with self.lock:
            return {"last_ok_age_s": (round(time.time() - self.last_ok, 1)
                                      if self.last_ok else None),
                    "last_error": self.last_error}


class Feed:
    def __init__(self, name, port, idx, provider, logdir, cookies=None, fmt=YTDLP_FORMAT):
        self.name = name
        self.port = port
        self.idx = idx
        self.provider = provider          # callable -> current schedule list
        self.cookies = cookies            # path to cookies.txt (bot-check protection) or None
        self.fmt = fmt                    # yt-dlp format string (POV uses a lower cap)
        self.paused = False               # when True the feed idles (POV off / stopped)
        self.lock = threading.Lock()
        self.proc = None
        self.stop = False
        self.advance = threading.Event()
        self.logfile = os.path.join(logdir, f"feed_{name}.log")

    def current_channel(self):
        if self.paused:
            return None, self.idx
        sched = self.provider()
        with self.lock:
            if not sched:
                return None, self.idx
            i = min(self.idx, len(sched) - 1)
            return sched[i], i

    def is_serving(self):
        p = self.proc
        return bool(p and p.poll() is None)

    def _kill_proc(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired: p.kill()
            except Exception:
                pass  # the process may already be gone — nothing left to kill

    def set_index(self, new_idx):
        sched = self.provider()
        hi = max(0, len(sched) - 1)
        new_idx = max(0, min(new_idx, hi))
        with self.lock:
            if new_idx == self.idx:
                return False
            self.idx = new_idx
        self.advance.set(); self._kill_proc()
        return True

    def reload(self):
        """Reconnect to the (possibly changed) channel at the CURRENT index."""
        self.advance.set(); self._kill_proc()
        return True

    def run(self):
        while not self.stop:
            ch, i = self.current_channel()
            if not ch:
                time.sleep(3); continue
            url = channel_url(ch)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f"\n>> [{self.name}:{self.port}] stint {i+1} -> resolving {url}\n"); log.flush()
            # 1) resolve the live HLS URL via yt-dlp (cookies + bot-check handling)
            hls = resolve_hls(url, self.cookies, self.logfile, self.fmt)
            if self.stop: break
            if self.advance.is_set():
                self.advance.clear(); continue
            if not hls:
                time.sleep(RESOLVE_RETRY)   # not live yet / could not resolve -> poll again
                continue
            # 2) serve the direct HLS URL via streamlink (no YouTube plugin -> no bot-check)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f">> [{self.name}:{self.port}] serving stint {i+1}\n"); log.flush()
                cmd = ["streamlink", hls, "best", "--player-external-http",
                       "--player-external-http-port", str(self.port)] + STREAMLINK_SERVE
                try:
                    self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                    self.proc.wait()
                except FileNotFoundError:
                    # Startup checks for streamlink; reaching here means it vanished mid-run.
                    log.write(f">> [{self.name}] streamlink not found on PATH — retrying\n"); log.flush()
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            if self.stop:
                break
            if self.advance.is_set():
                self.advance.clear(); continue
            time.sleep(RETRY_SLEEP)   # stream ended / manifest expired -> re-resolve

    def shutdown(self):
        self.stop = True; self._kill_proc()


class Relay:
    def __init__(self, source, ports, logdir, cookies=None, pov_source=None,
                 pov_port=None, start_stint=1):
        self.source = source
        self.cookies = cookies
        a_idx, b_idx = stint_start_indices(start_stint, len(source.get()))
        self.A = Feed("A", ports[0], a_idx, source.get, logdir, cookies)
        self.B = Feed("B", ports[1], b_idx, source.get, logdir, cookies)
        self.feeds = {"A": self.A, "B": self.B}
        # POV is a THIRD, independent feed — not part of the A/B index. Starts
        # paused (off) until the Director calls /pov/reload.
        self.pov_source = pov_source
        self.pov = None
        if pov_source is not None and pov_port is not None:
            self.pov = Feed("POV", pov_port, 0, pov_source.get, logdir, cookies,
                            fmt=YTDLP_FORMAT_POV)
            self.pov.paused = True

    def start(self):
        for f in self.feeds.values():
            threading.Thread(target=f.run, daemon=True).start()
        if self.pov:
            threading.Thread(target=self.pov.run, daemon=True).start()

    def status(self):
        sched = self.source.get()
        out = {"schedule_len": len(sched), "cookies": bool(self.cookies),
               "source": self.source.health(), "feeds": {}}
        for k, f in self.feeds.items():
            ch, i = f.current_channel()
            out["feeds"][k] = {"port": f.port, "index": i, "stint": i + 1, "channel": ch}
        if self.pov:
            raw = (self.pov_source.get()[:1] or [None])[0] if self.pov_source else None
            if self.pov.paused:         state = "stopped"
            elif self.pov.is_serving(): state = "serving"
            elif raw:                   state = "connecting"
            else:                       state = "idle"
            out["pov"] = {"port": self.pov.port, "url": raw, "state": state,
                          "source": self.pov_source.health() if self.pov_source else None}
        return out

    def next_auto(self):
        self.source.refresh(timeout=6)              # fresh sheet data at handover (bounded wait)
        target = "A" if self.A.idx <= self.B.idx else "B"
        return self.advance(target, +2)

    def advance(self, which, delta):
        f = self.feeds.get(which.upper())
        if not f: return None
        changed = f.set_index(f.idx + delta)
        return {"changed": changed, "feed": which.upper(), **self.status()}

    def set_index(self, which, idx):
        f = self.feeds.get(which.upper())
        if not f: return None
        f.set_index(idx); return self.status()

    def set_stint(self, stint):
        """Producer-takeover correction: 1-based stint <stint> is on air NOW ->
        Feed A serves it, Feed B preloads the next one. Tears a running feed off
        its stream (like /set) — use BEFORE going live, not mid-program."""
        self.source.refresh(timeout=6)      # clamp against fresh sheet data
        a_idx, b_idx = stint_start_indices(stint, len(self.source.get()))
        self.A.set_index(a_idx)
        self.B.set_index(b_idx)
        return self.status()

    def reload(self, which=None):
        self.source.refresh(timeout=6)
        targets = [which.upper()] if which else list(self.feeds)
        for t in targets:
            if t in self.feeds: self.feeds[t].reload()
        return {"reloaded": targets, **self.status()}

    def pov_reload(self):
        if not self.pov:
            return {"error": "pov disabled"}
        if self.pov_source:
            self.pov_source.refresh()   # re-read the POV cell on demand
        self.pov.paused = False
        self.pov.reload()
        return self.status()

    def pov_stop(self):
        if not self.pov:
            return {"error": "pov disabled"}
        self.pov.paused = True
        self.pov.reload()               # advance.set() + kill the serving proc -> port closes
        return self.status()

    def shutdown(self):
        for f in self.feeds.values(): f.shutdown()
        if self.pov: self.pov.shutdown()


def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None):
    class H(BaseHTTPRequestHandler):
        def _send(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def _send_file(self, path, ctype):
            try:
                with open(path, "rb") as fh: body = fh.read()
            except OSError:
                return self._send({"error": "panel not found", "looked_for": path}, 404)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
            return None
        def _send_asset(self, assets_dir, sub, key):
            hit = resolve_asset(assets_dir, sub, key)
            if not hit:
                return self._send({"error": "asset not found", "key": key}, 404)
            path, ctype = hit
            # Header value comes from the ASSET_CTYPES constant, never from the
            # request-derived tuple (defense vs. header injection).
            ctype = ASSET_CTYPES.get(ctype)
            if not ctype:
                return self._send({"error": "asset not found", "key": key}, 404)
            return self._send_file(path, ctype)
        def log_message(self, *a): pass
        def do_GET(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                if not p or p == ["status"]:          return self._send(relay.status())
                if p == ["panel"]:
                    if not panel_path: return self._send({"error":"panel disabled"}, 404)
                    return self._send_file(panel_path, "text/html; charset=utf-8")
                if p == ["hud"]:
                    if not (hud_source and hud_path):
                        return self._send({"error": "hud disabled"}, 404)
                    return self._send_file(hud_path, "text/html; charset=utf-8")
                if p == ["hud", "data"]:
                    if not hud_source:
                        return self._send({"error": "hud disabled"}, 404)
                    return self._send(hud_source.data())
                if len(p) == 4 and p[:2] == ["hud", "assets"]:
                    return self._send_asset(assets_dir, p[2], p[3])
                if p == ["next"]:                       return self._send(relay.next_auto())
                if p == ["reload"]:                     return self._send(relay.reload())
                if p == ["pov", "reload"]:              return self._send(relay.pov_reload())
                if p == ["pov", "stop"]:                return self._send(relay.pov_stop())
                if len(p)==2 and p[0]=="next":          return self._ok(relay.advance(p[1], +2))
                if len(p)==2 and p[0]=="prev":          return self._ok(relay.advance(p[1], -2))
                if len(p)==2 and p[0]=="reload":        return self._ok(relay.reload(p[1]))
                if len(p)==3 and p[:2]==["set","stint"]: return self._send(relay.set_stint(int(p[2])))
                if len(p)==3 and p[0]=="set":           return self._ok(relay.set_index(p[1], int(p[2])))
                return self._send({"error":"unknown","path":self.path}, 404)
            except Exception as e:
                return self._send({"error": str(e)}, 500)
        def _ok(self, r):
            self._send(r) if r else self._send({"error":"feed? (A/B)"}, 404)
    return H


def poller(source, interval, stop_evt):
    while not stop_evt.wait(interval):
        source.refresh()


def _cookie_hint(stderr_text, browser):
    """failure_hint() from the sibling get-cookies.py — one source of truth
    for the actionable export-failure hints (locked DB, no profile, DPAPI)."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "get_cookies", os.path.join(here, "get-cookies.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.failure_hint(stderr_text, browser)


def export_cookies(browser, out):
    """Export YouTube cookies from a logged-in browser to a Netscape cookies.txt
    using yt-dlp. Best-effort: returns True on success."""
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    try:
        proc = subprocess.run(["yt-dlp", "--cookies-from-browser", browser, "--cookies", out,
                               "--skip-download", "--no-warnings", url],
                              timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("WARN: yt-dlp not found — cannot auto-export cookies."); return False
    except subprocess.TimeoutExpired:
        print("WARN: cookie export timed out (Keychain prompt not approved?)."); return False
    ok = os.path.exists(out)
    if ok:
        try: os.chmod(out, 0o600)   # live YouTube session — owner-only
        except OSError: pass        # best-effort hardening; never block the export
        print(f"Cookie export from '{browser}': OK -> {out}")
    else:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        for line in [l for l in err.splitlines() if l.strip()][-1:]:
            print("WARN:", line)   # the real yt-dlp reason, not a guess
        print(f"Cookie export from '{browser}': FAILED — " + _cookie_hint(err, browser))
    return ok


def main():
    load_dotenv(os.path.dirname(os.path.abspath(__file__)))  # before defaults are read
    ap = argparse.ArgumentParser(description="IRO 2-feed relay with Google-Sheet schedule")
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID for the schedule/POV tabs. Default: env "
                         "IRO_SHEET_ID (or a .env at the repo/package root). See .env.example.")
    ap.add_argument("--sheet-tab", default=DEFAULT_SHEET_TAB)
    ap.add_argument("--sheet-csv-url", default=None,
                    help="Full CSV URL (overrides sheet-id/tab; e.g. publish-to-web)")
    ap.add_argument("--pov-tab", default=DEFAULT_POV_TAB,
                    help="Google-Sheet tab holding the ad-hoc driver-POV URL (cell A2).")
    ap.add_argument("--pov-port", type=int, default=53003,
                    help="Local port for the driver-POV PiP feed (OBS 'Feed POV').")
    ap.add_argument("--no-pov", action="store_true",
                    help="Disable the driver-POV PiP feed entirely.")
    ap.add_argument("--poll", type=int, default=30, help="Sheet poll interval (seconds)")
    ap.add_argument("--schedule", default="schedule.txt", help="Local offline fallback")
    ap.add_argument("--http-port", type=int, default=8088)
    ap.add_argument("--runtime-dir", default=None,
                    help="Directory for runtime data (cookies.txt, logs/, *.cache.txt). "
                         "Default: next to this script (keeps the distributed package "
                         "self-locating). The repo passes its runtime/ folder.")
    ap.add_argument("--bind", default="auto",
                    help="Address(es) the control/panel/HUD HTTP server binds to. "
                         "Default 'auto': binds 127.0.0.1 (for OBS, always) AND this "
                         "machine's Tailscale IP when present, so remote directors/"
                         "tablets reach /panel + /hud over the tailnet without "
                         "exposing the server on the local LAN. Pass '127.0.0.1' to "
                         "force local-only, or an explicit address (e.g. 0.0.0.0) to "
                         "override.")
    ap.add_argument("--no-panel", action="store_true",
                    help="Do not serve the director panel at /panel.")
    ap.add_argument("--overlay-tab", default="Overlay",
                    help="Google-Sheet tab with the live HUD values (default 'Overlay').")
    ap.add_argument("--config-tab", default="Configuration",
                    help="Google-Sheet tab with the team→brand map (default 'Configuration').")
    ap.add_argument("--hud-poll", type=int, default=5,
                    help="HUD sheet refresh interval in seconds (default 5).")
    ap.add_argument("--no-hud", action="store_true",
                    help="Do not serve the HUD overlay at /hud.")
    ap.add_argument("--ports", default="53001,53002")
    ap.add_argument("--stint", type=int, default=1,
                    help="1-based stint that is ON AIR right now (producer takeover): "
                         "Feed A serves it, Feed B preloads the next one. Default 1.")
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--cookies", default=None,
                    help="Path to cookies.txt (Netscape format) for YouTube login — "
                         "bypasses the 'Sign in to confirm you're not a bot' check. "
                         "Default: cookies.txt next to this script, if present.")
    ap.add_argument("--cookies-from-browser", default=None,
                    help="Auto-export YouTube cookies from this browser on startup via "
                         "yt-dlp (e.g. firefox, chrome, safari, edge, brave) and use them. "
                         "Writes cookies.txt next to this script.")
    args = ap.parse_args()
    try: sys.stdout.reconfigure(line_buffering=True)   # show logs immediately
    except Exception: pass   # not all stdout objects support reconfigure (e.g. pipes)

    if not args.sheet_csv_url and not args.sheet_id:
        sys.exit("ERROR: no Google Sheet configured. Set IRO_SHEET_ID in a .env file "
                 "at the repo/package root (see .env.example) or the environment, "
                 "or pass --sheet-id / --sheet-csv-url.")

    if args.stint < 1:
        sys.exit("ERROR: --stint must be >= 1 (1-based stint number, as in the sheet).")

    for _tool in ("yt-dlp", "streamlink"):
        if not shutil.which(_tool):
            sys.exit(f"ERROR: '{_tool}' not found on PATH "
                     f"(brew install {_tool} / pip install -U {_tool}).")

    here = os.path.dirname(os.path.abspath(__file__))
    runtime = os.path.abspath(args.runtime_dir) if args.runtime_dir else default_runtime_dir(here)
    os.makedirs(runtime, exist_ok=True)
    try: os.chmod(runtime, 0o700)   # holds the cookie jar / caches — keep it private
    except OSError: pass            # best-effort hardening; never block startup
    logdir = args.logdir if os.path.isabs(args.logdir) else os.path.join(runtime, args.logdir)
    os.makedirs(logdir, exist_ok=True)
    local = args.schedule if os.path.isabs(args.schedule) else os.path.join(runtime, args.schedule)
    cache = os.path.join(runtime, "schedule.cache.txt")
    ports = [int(x) for x in args.ports.split(",")]

    csv_url = args.sheet_csv_url or (
        f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={quote(args.sheet_tab)}")

    # POV source: own sheet tab (cell A2). Derivable only from sheet-id/tab,
    # so a custom --sheet-csv-url disables POV (no tab to point at).
    pov_source = None
    if not args.no_pov and not args.sheet_csv_url:
        pov_csv_url = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                       f"/gviz/tq?tqx=out:csv&sheet={quote(args.pov_tab)}")
        pov_cache = os.path.join(runtime, "pov.cache.txt")
        pov_source = ScheduleSource(pov_csv_url, pov_cache, None)
        pov_source.refresh()   # non-fatal: empty cell / unreachable = POV simply off

    # Optionally auto-export cookies from a logged-in browser first (yt-dlp)
    if args.cookies_from_browser:
        export_cookies(args.cookies_from_browser, os.path.join(runtime, "cookies.txt"))

    # Cookies: explicit via --cookies, otherwise auto-detect cookies.txt in the runtime dir
    cookies = args.cookies
    if cookies is None:
        auto = os.path.join(runtime, "cookies.txt")
        cookies = auto if os.path.exists(auto) else None
    elif not os.path.isabs(cookies):
        cookies = os.path.join(runtime, cookies)
    if cookies and not os.path.exists(cookies):
        sys.exit(f"ERROR: cookies file not found: {cookies}")
    if cookies:
        try: os.chmod(cookies, 0o600)   # contains a live YouTube session — owner-only
        except OSError: pass            # best-effort hardening; never block startup

    # Locate the director panel (shipped in the package root, one level up from relay/)
    panel_path = None
    if not args.no_panel:
        for cand in (os.path.join(here, "director-panel.html"),
                     os.path.join(here, "..", "director-panel.html"),
                     os.path.join(here, "..", "director", "director-panel.html")):
            if os.path.exists(cand):
                panel_path = os.path.abspath(cand); break

    # HUD overlay: derived from sheet-id/tab (disabled with a custom CSV URL).
    hud_source = None
    hud_path = None
    assets_dir = os.path.abspath(os.path.join(here, "..", "assets"))
    if not args.no_hud and not args.sheet_csv_url:
        base = f"https://docs.google.com/spreadsheets/d/{args.sheet_id}/gviz/tq?tqx=out:csv&sheet="
        overlay_url = base + quote(args.overlay_tab)
        config_url = base + quote(args.config_tab)
        hud_cache = os.path.join(runtime, "hud.cache.json")
        hud_source = HudSource(overlay_url, config_url, hud_cache)
        hud_source.refresh()   # non-fatal: keeps last-good / empty if unreachable
        for cand in (os.path.join(here, "hud.html"),
                     os.path.join(here, "..", "hud.html"),
                     os.path.join(here, "..", "obs", "hud.html")):
            if os.path.exists(cand):
                hud_path = os.path.abspath(cand); break
        if not hud_path:
            print("WARN: hud.html not found — /hud will 404 (assets dir: "
                  f"{assets_dir}).")

    source = ScheduleSource(csv_url, cache, local)
    source.load_initial(SCHEDULE_TEMPLATE)
    if len(source.get()) < 2:
        print("WARN: schedule has fewer than 2 stints — Feed A and Feed B will serve the "
              "SAME stream (no off-air feed to hand over to).")

    relay = Relay(source, ports, logdir, cookies,
                  pov_source=pov_source, pov_port=args.pov_port,
                  start_stint=args.stint)
    relay.start()

    stop_evt = threading.Event()
    threading.Thread(target=poller, args=(source, args.poll, stop_evt), daemon=True).start()
    if hud_source:
        threading.Thread(target=poller, args=(hud_source, args.hud_poll, stop_evt),
                         daemon=True).start()

    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir)
    bind_addrs = resolve_bind_addresses(
        args.bind, detect_tailscale_ip() if args.bind == "auto" else None)
    servers = []
    for addr in bind_addrs:
        try:
            servers.append(ThreadingHTTPServer((addr, args.http_port), handler))
        except OSError as e:
            print(f"  (warn) could not bind {addr}:{args.http_port} — {e}")
    if not servers:
        sys.exit(f"Could not bind the control server on {bind_addrs} port {args.http_port}.")

    def shutdown(*_):
        # IMPORTANT: do NOT call shutdown() from the thread running serve_forever()
        # (deadlock). Stop the feeds and exit hard — the OS frees the sockets; the
        # streamlink subprocesses are cleanly terminated.
        print("\nStopping feeds…")
        stop_evt.set(); relay.shutdown(); os._exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # The non-loopback bind (if any) is the address remote directors/tablets use.
    remote_host = next((a for a in bind_addrs if a not in ("127.0.0.1", "localhost")), None)

    print(f"IRO relay running.  Schedule source: {'CSV URL' if args.sheet_csv_url else f'sheet tab “{args.sheet_tab}”'}")
    print(f"  Feed A -> http://127.0.0.1:{ports[0]}   Feed B -> http://127.0.0.1:{ports[1]}")
    if args.stint != 1:
        if relay.A.idx != args.stint - 1:
            print(f"  WARN: --stint {args.stint} clamped to stint {relay.A.idx + 1} "
                  f"(schedule has {len(source.get())} stints).")
        print(f"  Takeover start: stint {relay.A.idx + 1} on Feed A; "
              f"Feed B preloads stint {relay.B.idx + 1}.")
    print(f"  Controls: http://127.0.0.1:{args.http_port}/status | /next | /reload")
    if relay.pov:
        print(f"  Driver-POV PiP -> http://127.0.0.1:{args.pov_port}  "
              f"(sheet tab '{args.pov_tab}' A2; control /pov/reload | /pov/stop)")
    if panel_path:
        print(f"  Director panel (local): http://127.0.0.1:{args.http_port}/panel")
        if remote_host:
            print(f"    remote (tailnet):      http://{remote_host}:{args.http_port}/panel")
        elif args.bind == "auto":
            print("    (no Tailscale IP found — local only; start Tailscale for remote access)")
    if hud_source and hud_path:
        print(f"  HUD overlay (OBS source): http://127.0.0.1:{args.http_port}/hud  "
              f"(tabs '{args.overlay_tab}'/'{args.config_tab}', refresh {args.hud_poll}s)")
    print(f"  Cookies (bot-check protection): {'ON — ' + cookies if cookies else 'off (no cookies.txt)'}")
    print(f"  Sheet poll every {args.poll}s.  Ctrl+C to stop.")
    # Serve every bound address; keep the last on the main thread for signals.
    for httpd in servers[:-1]:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    servers[-1].serve_forever()

if __name__ == "__main__":
    main()
