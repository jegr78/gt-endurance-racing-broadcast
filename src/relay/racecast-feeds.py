#!/usr/bin/env python3
"""
racecast-feeds.py — Relay mode for the IRO broadcast (2-feed ping-pong)
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
  GET /timer           -> race-timer browser-source page (OBS 'HUD Race Timer')
  GET /timer/data      -> timer state JSON (anchor, mode, sync health)
  GET /timer/start | /timer/stop | /timer/reset | /timer/show | /timer/hide
                          (start resumes a paused timer; stop = pause;
                           reset = back to the full duration)
  GET /timer/set/<H:MM:SS>     -> set the race duration (next start)
  GET /timer/adjust/<±seconds> -> shift a RUNNING timer (correction)
  Stop: Ctrl+C
"""

import argparse, csv, datetime, io, ipaddress, json, os, re, shutil, signal, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, quote, unquote
from urllib.request import Request, urlopen

# OBS reflection (best effort). obs_ws lives in src/scripts (repo) or the
# bundled tree (frozen). A missing client just disables reflection — it must
# never break the relay.
_REL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_REL_HERE, "..", "scripts"),
              os.path.join(getattr(sys, "_MEIPASS", _REL_HERE), "src", "scripts")):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)
try:
    import obs_ws as _obs_ws
except Exception:                                # noqa: BLE001 — reflection is optional
    _obs_ws = None

# ---------- Configuration ----------
# Pipeline: yt-dlp resolves the live HLS URL (passes YouTube's bot-check via
# cookies + JS-challenge solving) -> streamlink serves that direct URL to OBS
# (no YouTube plugin involved, so no bot-check on the serving side).
YTDLP_FORMAT = "b[height<=1080]/b"   # prefer <=1080p, auto-fall back to lower
YTDLP_FORMAT_POV = "b[height<=720]/b"  # driver-POV is shown small (PiP) -> cap at 720p
STREAMLINK_SERVE = ["--ringbuffer-size", "64M", "--hls-live-edge", "4"]
RESOLVE_RETRY = 15  # seconds between yt-dlp resolve attempts while a stint isn't live
COOKIE_MAX_AGE_H = 12   # keep in sync with preflight.py cookies_status(max_age_hours)
RETRY_SLEEP = 10    # seconds after a stream ends / manifest expires before re-resolving
# Sheet ID is NOT hardcoded — it comes from RACECAST_SHEET_ID (injected by the CLI
# from the active profile). Override per-run with --sheet-id.
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


def _no_window_kwargs(os_name=None):
    """Popen/run kwargs that stop a console child from flashing its own terminal
    window on Windows. The relay is spawned as a daemon with DETACHED_PROCESS
    (services.spawn_kwargs), so it has NO console — every console subprocess it
    starts (yt-dlp, streamlink, the tailscale CLI) otherwise pops a transient
    window, and the per-feed yt-dlp resolve fires every ~15 s, so the desktop
    flickers continuously during an event (issue #30). CREATE_NO_WINDOW gives the
    child a hidden console instead; harmless when a console already exists (the
    foreground `racecast relay run`), and a no-op (empty kwargs) off Windows so the
    same spawn site stays cross-platform. Mirrors services.no_window_kwargs — the
    standalone relay imports nothing from scripts/, so the flag is duplicated here
    (same pattern as detect_tailscale_ip)."""
    os_name = os.name if os_name is None else os_name
    if os_name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


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
                                 text=True, errors="replace", timeout=3,
                                 **_no_window_kwargs())
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


# Configuration-tab vocabulary columns feeding the panel's Setup dropdowns
# (strict: the panel offers ONLY these values — spec: panel-sheet-control).
# Dict KEYS are the API field names used by panel endpoints; VALUES are sheet headers (matched case-insensitively).
VOCAB_COLUMNS = {"stint": "stints", "streamer": "streamers",
                 "session": "session", "racecontrol": "race control"}


def parse_config_vocab(text):
    """Configuration tab CSV -> {field_key: [options]} for the panel
    dropdowns. Columns located by header name (parse_config_brands precedent);
    blanks skipped, duplicates dropped, sheet order kept."""
    rows = list(csv.reader(io.StringIO(text)))
    out = {k: [] for k in VOCAB_COLUMNS}
    if not rows:
        return out
    header = [(h or "").strip().lower() for h in rows[0]]
    for key, name in VOCAB_COLUMNS.items():
        if name not in header:
            continue
        i = header.index(name)
        seen = set()
        for row in rows[1:]:
            v = (row[i] or "").strip() if len(row) > i else ""
            if v and v not in seen:
                seen.add(v)
                out[key].append(v)
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

# ---------- Race timer (relay-hosted countdown) ----------
# State model (spec: docs/superpowers/specs/2026-06-06-race-timer-design.md):
# one absolute end anchor + duration + visibility + an "updated" stamp that
# drives the newest-wins merge between the local file and the Sheet tab.
# Stopwatch semantics: START starts or resumes, STOP pauses (freezes the
# remainder in "remaining"), RESET clears. "end" and "remaining" are mutually
# exclusive — an anchor means running/finished, a remainder means paused.
TIMER_DEFAULT_DURATION = 6 * 3600          # seconds, until the Director sets one
DURATION_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")  # hours 1-2 digits (24h races OK)


def default_timer_state():
    return {"end": None, "duration": TIMER_DEFAULT_DURATION,
            "remaining": None, "visible": True, "updated": 0.0}


def parse_duration(s):
    """'H:MM:SS' (or HH:MM:SS) -> seconds, else None."""
    mt = DURATION_RE.match((s or "").strip())
    if not mt:
        return None
    h, mi, sec = (int(g) for g in mt.groups())
    return h * 3600 + mi * 60 + sec


def format_duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_utc_ts(s):
    """Lenient UTC timestamp -> epoch seconds, else None. Accepts the canonical
    '...T..Z', Apps Script's toISOString ('.000Z'), and the 'YYYY-MM-DD HH:MM:SS'
    form gviz CSV produces when Sheets re-types the cell as a date."""
    s = (s or "").strip().replace("T", " ").rstrip("Zz").strip()
    s = s.split(".", 1)[0]                     # drop fractional seconds
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=datetime.timezone.utc).timestamp()


def iso_utc(epoch):
    """Epoch seconds -> canonical ISO UTC string (whole-second precision —
    a Sheet 'updated' stamp can therefore never out-rank the local stamp of
    the very write that produced it; the newest-wins merge stays correct)."""
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timer_tab(text):
    """Timer tab CSV (label col A, value col B) -> state dict. Unknown labels
    and unparseable values fall back to the defaults — never throws."""
    raw = {}
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) >= 2 and (row[0] or "").strip():
            raw[row[0].strip().lower()] = (row[1] or "").strip()
    st = default_timer_state()
    st["end"] = parse_utc_ts(raw.get("race end (utc)", ""))
    dur = parse_duration(raw.get("duration", ""))
    if dur is not None:
        st["duration"] = dur
    st["remaining"] = parse_duration(raw.get("remaining", ""))
    if st["end"] is not None:
        st["remaining"] = None   # mutually exclusive — a set anchor wins
    st["visible"] = raw.get("visible", "").upper() != "FALSE"
    st["updated"] = parse_utc_ts(raw.get("updated (utc)", "")) or 0.0
    return st


def timer_mode(state, now):
    """hidden | prestart | running | paused | finished (pure; the page renders
    blank for hidden and finished — spec: no 0:00:00 left standing)."""
    if not state.get("visible", True):
        return "hidden"
    end = state.get("end")
    if end is not None:
        return "running" if now < end else "finished"
    if state.get("remaining") is not None:
        return "paused"
    return "prestart"


def merge_timer_states(local, sheet):
    """Newest write wins; tie (or no sheet state) -> local. Makes a producer
    takeover adopt the Sheet anchor without letting a stale Sheet revert a
    fresh local action whose webhook push failed."""
    if sheet is None:
        return local
    return sheet if sheet.get("updated", 0.0) > local.get("updated", 0.0) else local


def post_webhook(url, payload, timeout=10):
    """POST JSON to the Apps-Script sheet-write webhook -> raw response bytes."""
    req = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                  headers={"User-Agent": "iro-feeds/1.0",
                           "Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_webhook_response(body, expected_action=None):
    """(ok, error) from an Apps-Script response body. Apps Script answers
    HTTP 200 even for errors, so only its own {"ok": true} counts. The v2
    script echoes the action; an ok WITHOUT the echo on an action write is a
    still-deployed v1 (timer-only) script -> report it, never a false success."""
    try:
        d = json.loads((body or b"{}").decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        d = None
    if not isinstance(d, dict) or d.get("ok") is not True:
        snippet = (body or b"")[:120].decode("utf-8", "replace")
        return False, f"webhook did not confirm: {snippet!r}"
    if expected_action and d.get("action") != expected_action:
        return False, ("webhook script outdated (no action echo) — redeploy "
                       "the v2 script (wiki: Sheet-Webhook)")
    return True, None


class TimerStore:
    """Race-timer state with three layers (spec §3): in-memory + local JSON
    file (restart-safe) + Sheet tab via CSV poll / Apps-Script webhook push
    (producer-handover-safe). Director actions apply locally first and push in
    the background — a webhook failure degrades, never breaks."""

    def __init__(self, csv_url, push_url, path):
        self.csv_url = csv_url            # None -> local-only (no sheet poll)
        self.push_url = push_url          # None -> push disabled
        self.path = path
        self.lock = threading.Lock()
        self.state = default_timer_state()
        self.last_ok = None               # last successful sheet read
        self.last_error = None
        self.push_status = "disabled" if not push_url else "never"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            # The runtime dir normally exists; a fresh layout must not break
            # startup — _save_file() degrades per-write if the dir is missing.
            pass
        self._load_file()

    # -- persistence ------------------------------------------------------
    def _load_file(self):
        """Adopt only known keys with sane types — a hand-edited timer.json
        must never crash data()/timer_mode() later."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return  # no/corrupt file -> defaults; the sheet poll may catch us up
        st = default_timer_state()
        def num(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if num(saved.get("end")):
            st["end"] = float(saved["end"])
        if num(saved.get("duration")):
            st["duration"] = int(saved["duration"])
        if num(saved.get("remaining")) and st["end"] is None:
            st["remaining"] = int(saved["remaining"])
        if isinstance(saved.get("visible"), bool):
            st["visible"] = saved["visible"]
        if num(saved.get("updated")):
            st["updated"] = float(saved["updated"])
        self.state = st

    def _save_file(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh)
        except OSError:
            pass  # best-effort, same contract as the schedule/HUD caches

    # -- sheet read (poller + adopt-if-newer merge) -------------------------
    @staticmethod
    def _fetch(url, timeout=10):
        req = Request(url, headers={"User-Agent": "iro-feeds/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def refresh(self, timeout=10):
        if not self.csv_url:
            return False
        try:
            sheet = parse_timer_tab(self._fetch(self.csv_url, timeout))
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            merged = merge_timer_states(self.state, sheet)
            if merged is not self.state:
                self.state = merged
                self._save_file()
        self.last_ok = time.time()       # diagnostics outside the lock (HudSource precedent)
        self.last_error = None
        return True

    # -- webhook push (Apps Script writes the Timer tab) --------------------
    def _push(self, payload):
        """Success = the Apps Script's own {"ok": true} (see
        check_webhook_response). Timer pushes carry no expected_action: a v1
        script keeps working for the timer."""
        try:
            body = post_webhook(self.push_url, payload)
        except Exception as e:
            self.push_status = "failed"
            self.last_error = f"push: {type(e).__name__}: {e}"
            return
        ok, err = check_webhook_response(body)
        if ok:
            self.push_status = "ok"  # diagnostics: single ref assignments, no lock needed
        else:
            self.push_status = "failed"
            self.last_error = f"push: {err}"

    def _spawn_push(self, payload):
        threading.Thread(target=self._push, args=(payload,), daemon=True).start()

    @staticmethod
    def _payload(st):
        """Webhook body: the full state, strings only (Apps Script writes it 1:1)."""
        return {"end": iso_utc(st["end"]) if st["end"] is not None else "",
                "duration": format_duration(st["duration"]),
                "visible": "TRUE" if st["visible"] else "FALSE",
                "remaining": (format_duration(st["remaining"])
                              if st["remaining"] is not None else "")}

    # -- director actions (stopwatch semantics: start/resume, pause, reset) --
    def _apply(self, now=None, **changes):
        """Local-first write: update + stamp + save, then push full state."""
        now = time.time() if now is None else now
        with self.lock:
            self.state.update(changes)
            self.state["updated"] = now
            self._save_file()
            st = dict(self.state)
        if self.push_url:
            self._spawn_push(self._payload(st))
        return self.data(now)

    def start(self, now=None):
        """Start from prestart (full duration) or resume a paused remainder.
        No-op while an anchor is set (running/finished) — RESET clears first."""
        now = time.time() if now is None else now
        with self.lock:
            if self.state["end"] is not None:
                anchored = True
            else:
                base = self.state["remaining"]
                self.state["end"] = now + (base if base is not None
                                           else self.state["duration"])
                self.state["remaining"] = None
                self.state["updated"] = now
                self._save_file()
                anchored = False
            st = dict(self.state)
        if anchored:
            return {"note": "already started — /timer/reset to clear", **self.data(now)}
        if self.push_url:
            self._spawn_push(self._payload(st))
        return self.data(now)

    def stop(self, now=None):
        """Pause: freeze the remainder (the STOP button). Full reset = reset()."""
        now = time.time() if now is None else now
        with self.lock:
            end = self.state["end"]
            if end is not None:
                self.state["remaining"] = max(0, int(end - now))
                self.state["end"] = None
                self.state["updated"] = now
                self._save_file()
            st = dict(self.state)
        if end is None:
            return {"note": "not running — nothing to pause", **self.data(now)}
        if self.push_url:
            self._spawn_push(self._payload(st))
        return self.data(now)

    def reset(self, now=None):
        """Back to 'not started': clears the anchor and any paused remainder."""
        return self._apply(now=now, end=None, remaining=None)

    def show(self, now=None):
        return self._apply(now=now, visible=True)

    def hide(self, now=None):
        return self._apply(now=now, visible=False)

    def set_duration(self, seconds, now=None):
        # Never re-anchors a running timer (spec §5) — corrections use adjust.
        return self._apply(now=now, duration=int(seconds))

    def adjust(self, delta_s, now=None):
        """Shift whichever clock is relevant by ± seconds: a RUNNING anchor,
        a paused remainder, or — before start — the configured duration.
        Check-and-write under ONE lock so a concurrent stop/reset can never
        be overwritten."""
        now = time.time() if now is None else now
        delta = int(delta_s)
        with self.lock:
            if self.state["end"] is not None:
                self.state["end"] += delta
            elif self.state["remaining"] is not None:
                self.state["remaining"] = max(0, self.state["remaining"] + delta)
            else:
                self.state["duration"] = max(0, self.state["duration"] + delta)
            self.state["updated"] = now
            self._save_file()
            st = dict(self.state)
        if self.push_url:
            self._spawn_push(self._payload(st))
        return self.data(now)

    # -- read side ----------------------------------------------------------
    def data(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            st = dict(self.state)
        return {"visible": st["visible"], "end": st["end"],
                "duration_s": st["duration"], "remaining_s": st["remaining"],
                "server_now": now, "mode": timer_mode(st, now),
                "sync": {"push": self.push_status,
                         "sheet_last_ok_age_s": (round(now - self.last_ok, 1)
                                                 if self.last_ok else None),
                         "last_error": self.last_error}}

    def summary(self):
        """Compact line for /status and `racecast status`."""
        d = self.data()
        return {"mode": d["mode"], "visible": d["visible"],
                "remaining_s": (max(0, int(d["end"] - d["server_now"]))
                                if d["end"] is not None else d["remaining_s"]),
                "push": d["sync"]["push"]}


def channel_url(entry: str) -> str:
    entry = entry.strip()
    if entry.startswith("http://") or entry.startswith("https://"):
        return entry
    return f"https://www.youtube.com/channel/{entry}/live"


def resolve_hls(url, cookies, logfile, fmt=YTDLP_FORMAT):
    """Resolve a YouTube live URL to a direct HLS manifest URL via yt-dlp
    (handles cookies + the bot-check). Returns (url, None) on success or
    (None, error_line) — the error line feeds /status so the panel can show
    WHY a feed is stuck connecting (previously it only landed in feed_X.log)."""
    cmd = ["yt-dlp", "-g", "-f", fmt, "--no-warnings", "--no-playlist", url]
    if cookies:
        cmd += ["--cookies", cookies]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=90, **_no_window_kwargs())
    except FileNotFoundError:
        # Startup checks for yt-dlp; reaching here means it vanished mid-run.
        try:
            with open(logfile, "a", encoding="utf-8") as log:
                log.write("   yt-dlp not found on PATH\n")
        except Exception:
            pass  # logging is best-effort; never let it break the resolve loop
        return None, "yt-dlp not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "yt-dlp timed out (90 s)"
    out = [l for l in (r.stdout or "").splitlines() if l.startswith("http")]
    if out:
        return out[0], None
    err = (r.stderr or "").strip().splitlines()
    last = err[-1] if err else "not live?"
    try:
        with open(logfile, "a", encoding="utf-8") as log:
            log.write(f"   yt-dlp could not resolve {url} ({last})\n")
    except Exception:
        pass  # logging is best-effort; never let it break the resolve loop
    return None, last


def stint_start_indices(stint, schedule_len):
    """0-based (A, B) start indices for a producer takeover: 1-based stint
    <stint> is on air NOW -> Feed A serves it, Feed B preloads the NEXT slot.
    A is clamped to a real stint; B is always A+1 and may point past the end
    (an empty/missing slot) — the off-air feed then idles (black) until that
    stint's link appears, instead of duplicating A's stream."""
    stint = max(1, int(stint))
    hi = max(0, schedule_len - 1)
    a = min(stint - 1, hi)
    return a, a + 1


class ScheduleSource:
    """Reads the schedule from the Google Sheet (CSV) with last-good + fallback."""
    def __init__(self, csv_url, cache_path, local_fallback):
        self.csv_url = csv_url
        self.cache_path = cache_path
        self.local_fallback = local_fallback
        self.lock = threading.Lock()
        self.items = []
        self.rows = []
        self.last_ok = None
        self.last_error = None

    @staticmethod
    def _parse_rows(text):
        """CSV -> [(url, name, line)] rows where *line* is the 1-based CSV line
        index of each accepted row (== physical sheet row when the Schedule tab
        starts at sheet row 1 with no leading blank rows — gviz export maps
        1:1).  Header rows or any row whose URL cell fails is_channel() are
        silently skipped; their line numbers are NOT remapped.  The URL column
        is auto-detected (most cells matching is_channel); the name is the
        cell right of it."""
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
        out = [(r[best_col].strip(),
                (r[best_col + 1].strip() if len(r) > best_col + 1 else ""),
                line)
               for line, r in enumerate(rows, 1)
               if len(r) > best_col and is_channel(r[best_col])]
        return out or None

    @staticmethod
    def _parse_csv(text):
        """URL-only wrapper around _parse_rows; kept for the URL-list callers/tests."""
        rows = ScheduleSource._parse_rows(text)
        return [u for u, _n, _l in rows] if rows else None

    def fetch(self, timeout=15):
        if not self.csv_url:
            return None
        try:
            req = Request(self.csv_url, headers={"User-Agent": "iro-feeds/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            rows = self._parse_rows(text)
            if not rows:
                self.last_error = ("Sheet reachable, but no channel IDs found "
                                   "(correct tab name? a column with UC… IDs / watch URLs? sharing?)")
                return None
            return rows
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def refresh(self, timeout=15):
        rows = self.fetch(timeout)
        if rows:
            with self.lock:
                self.rows = rows
                self.items = [u for u, _n, _l in rows]
                self.last_ok = time.time()
                self.last_error = None
            try:
                with open(self.cache_path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(u for u, _n, _l in rows) + "\n")
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
                        self.rows = [(u, "", i + 1) for i, u in enumerate(items)]
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

    def get_rows(self):
        with self.lock:
            return list(self.rows)

    def inject_row(self, physical_row, url, name=""):
        """Optimistically merge a panel schedule write into the in-memory
        schedule so an idling feed adopts it before the next poll. Keyed by
        physical sheet row (matches _parse_rows line numbers); the next poll
        reconciles against the sheet. No-op for an empty/invalid URL."""
        url = (url or "").strip()
        if not is_channel(url):
            return False
        with self.lock:
            rows = [r for r in self.rows if r[2] != physical_row]
            rows.append((url, (name or "").strip(), physical_row))
            rows.sort(key=lambda r: r[2])
            self.rows = rows
            self.items = [u for u, _n, _l in rows]
        return True

    def health(self):
        with self.lock:
            n = len(self.items)
        return {"count": n,
                "last_ok_age_s": (round(time.time() - self.last_ok, 1) if self.last_ok else None),
                "last_error": self.last_error}


OVERRIDE_TTL = 30  # s: unconfirmed panel write -> HUD falls back to sheet truth


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
        self._vocab = {k: [] for k in VOCAB_COLUMNS}
        self.overrides = {}   # hud-data key -> (value, expires_ts)
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
            config_text = self._fetch(self.config_url, timeout)
            brands = parse_config_brands(config_text)
            vocab = parse_config_vocab(config_text)
            data = build_hud_data(overlay, brands)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            self._data = data
            self._vocab = vocab
            # a sheet poll that already shows the pushed value = confirmation
            self.overrides = {k: (v, exp) for k, (v, exp) in self.overrides.items()
                              if data.get(k) != v}
            self.last_ok = time.time()
            self.last_error = None
        try:
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass  # cache write is best-effort; the in-memory HUD data is current
        return True

    def set_override(self, key, value, now=None):
        """Optimistic echo for a panel write: /hud/data shows the value NOW;
        the sheet poll confirms (clears) it, or it expires after OVERRIDE_TTL."""
        now = time.time() if now is None else now
        with self.lock:
            self.overrides[key] = (value, now + OVERRIDE_TTL)

    def pending(self, now=None):
        """Keys with an unconfirmed (and unexpired) optimistic override."""
        now = time.time() if now is None else now
        with self.lock:
            return {k for k, (_v, exp) in self.overrides.items() if exp > now}

    def data(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.overrides = {k: (v, exp) for k, (v, exp) in self.overrides.items()
                              if exp > now}
            # Always shallow-copy: callers (and /setup/data decoration) must never
            # be able to mutate the canonical dict.
            base = dict(self._data) if self._data is not None else dict(self.EMPTY)
            if not self.overrides:
                return base
            out = dict(base)
            out.update({k: v for k, (v, _exp) in self.overrides.items()})
            return out

    def vocab(self):
        with self.lock:
            return {k: list(v) for k, v in self._vocab.items()}

    def health(self):
        with self.lock:
            return {"last_ok_age_s": (round(time.time() - self.last_ok, 1)
                                      if self.last_ok else None),
                    "last_error": self.last_error}


# Panel setup fields: URL segment -> (Setup-tab header, /hud/data key).
# NOTE: the Setup "Stint" is the HUD display LABEL — it has no relationship
# to the relay's feed stint index (/set/stint, NEXT).
SETUP_FIELDS = {
    "stint": ("Stint", "stint"),
    "streamer": ("Streamer", "streamer"),
    "session": ("Session", "session"),
    "racecontrol": ("Race Control", "raceControl"),
}


class SetupControl:
    """Panel -> sheet writes (spec: panel-sheet-control). Setup fields are
    async-optimistic (override now, push in the background, the sheet poll
    confirms); Schedule/POV URL writes are synchronous (no local echo target,
    and answering after the webhook confirm removes the save-vs-RELOAD race).
    The sheet stays authoritative throughout."""

    def __init__(self, push_url, hud_source, schedule_source=None):
        self.push_url = push_url
        self.hud = hud_source
        self.schedule_source = schedule_source
        self.push_status = "disabled" if not push_url else "never"
        self.last_error = None

    # -- shared blocking push -> (ok, error); diagnostics like TimerStore ----
    def _push(self, payload, expected_action):
        try:
            body = post_webhook(self.push_url, payload)
        except Exception as e:
            self.push_status = "failed"
            self.last_error = f"push: {type(e).__name__}: {e}"
            return False, self.last_error
        ok, err = check_webhook_response(body, expected_action)
        # diagnostics: single ref assignments, no lock needed
        self.push_status = "ok" if ok else "failed"
        self.last_error = None if ok else err
        return ok, err

    # -- setup fields (async-optimistic) -------------------------------------
    def set_field(self, key, value, now=None):
        if key not in SETUP_FIELDS:
            return {"error": f"unknown field: {key!r} "
                             f"(one of {', '.join(sorted(SETUP_FIELDS))})"}
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        header, hud_key = SETUP_FIELDS[key]
        if not value and key != "racecontrol":
            return {"error": "empty value only allowed for racecontrol"}
        if value and value not in self.hud.vocab().get(key, []):
            return {"error": f"not in the Configuration vocabulary: {value!r} "
                             "(add it to the Configuration tab first)"}
        self.hud.set_override(hud_key, value, now)
        threading.Thread(target=self._push_setup, args=(header, value),
                         daemon=True).start()
        return {"ok": True, "field": key, "value": value, "pending": True}

    def _push_setup(self, header, value):
        ok, _err = self._push({"action": "setup", "fields": {header: value}},
                              "setup")
        if ok:
            self.hud.refresh()   # confirm now, not at the next poll tick

    # -- URL writes (synchronous) --------------------------------------------
    def schedule_set(self, row, url=None, name=None):
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        if isinstance(row, bool) or not isinstance(row, (int, str)):
            return {"error": "row must be a whole number (1-based)"}
        try:
            row = int(row)
        except (TypeError, ValueError):
            return {"error": "row must be a number (1-based)"}
        if row < 1:
            return {"error": "row must be >= 1"}
        if url is None and name is None:
            return {"error": "nothing to write (provide url and/or name)"}
        if url is not None and not isinstance(url, str):
            return {"error": "url must be a string"}
        if name is not None and not isinstance(name, str):
            return {"error": "name must be a string"}
        payload = {"action": "schedule", "row": row}
        if url is not None:
            url = url.strip()
            if url and not is_channel(url):
                return {"error": "url must be a watch URL or UC… channel ID"}
            payload["url"] = url
        if name is not None:
            payload["name"] = name.strip()
        ok, err = self._push(payload, "schedule")
        if ok and self.schedule_source is not None and url:
            self.schedule_source.inject_row(row, url, payload.get("name", ""))
        return {"ok": True, "row": row} if ok else {"error": err}

    def pov_set(self, url):
        if not self.push_url:
            return {"error": "webhook not configured — set RACECAST_SHEET_PUSH_URL "
                             "in the active profile or .env (wiki: Sheet-Webhook)"}
        if url is not None and not isinstance(url, str):
            return {"error": "url must be a string"}
        url = (url or "").strip()
        if url and not is_channel(url):
            return {"error": "url must be a watch URL or UC… channel ID"}
        ok, err = self._push({"action": "pov", "url": url}, "pov")
        return {"ok": True} if ok else {"error": err}

    # -- panel poll ------------------------------------------------------------
    def data(self):
        hud = self.hud.data()
        pending = self.hud.pending()
        return {"fields": {k: hud.get(hk, "") for k, (_h, hk) in SETUP_FIELDS.items()},
                "options": self.hud.vocab(),
                "pending": sorted(k for k, (_h, hk) in SETUP_FIELDS.items()
                                  if hk in pending),
                "push": self.push_status,
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
        # Health for /status: phase ("idle" | "connecting" | "serving"),
        # since-when, and the last yt-dlp error line. Written by the run()
        # thread, read by Relay.status() — a reader may briefly pair a new
        # phase with a stale timestamp; tolerable for a 2 s-polled display
        # (same convention as self.proc).
        self.phase = "idle"
        self.phase_since = time.time()
        self.last_error = None

    def current_channel(self):
        if self.paused:
            return None, self.idx
        sched = self.provider()
        with self.lock:
            if not sched or self.idx >= len(sched):
                return None, self.idx          # idle: empty schedule or own slot not filled yet
            return sched[self.idx], self.idx

    def is_serving(self):
        p = self.proc
        return bool(p and p.poll() is None)

    def _set_phase(self, phase):
        """Phase + timestamp, updated only on change — so state_age_s keeps
        accumulating across resolve retries within one 'connecting' stretch."""
        if phase != self.phase:
            self.phase = phase
            self.phase_since = time.time()

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
        new_idx = max(0, min(new_idx, len(sched)))   # len == idle slot (one past the last stint)
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
                self._set_phase("idle")
                time.sleep(3); continue
            self._set_phase("connecting")
            url = channel_url(ch)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f"\n>> [{self.name}:{self.port}] stint {i+1} -> resolving {url}\n"); log.flush()
            # 1) resolve the live HLS URL via yt-dlp (cookies + bot-check handling)
            hls, err = resolve_hls(url, self.cookies, self.logfile, self.fmt)
            if self.stop: break
            if self.advance.is_set():
                self.advance.clear(); continue
            if not hls:
                self.last_error = err       # surfaced via /status (panel health line)
                time.sleep(RESOLVE_RETRY)   # not live yet / could not resolve -> poll again
                continue
            # 2) serve the direct HLS URL via streamlink (no YouTube plugin -> no bot-check)
            with open(self.logfile, "a", encoding="utf-8") as log:
                log.write(f">> [{self.name}:{self.port}] serving stint {i+1}\n"); log.flush()
                cmd = ["streamlink", hls, "best", "--player-external-http",
                       "--player-external-http-port", str(self.port)] + STREAMLINK_SERVE
                try:
                    self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                                 **_no_window_kwargs())
                    self.last_error = None
                    self._set_phase("serving")
                    self.proc.wait()
                except FileNotFoundError:
                    # Startup checks for streamlink; reaching here means it vanished mid-run.
                    log.write(f">> [{self.name}] streamlink not found on PATH — retrying\n"); log.flush()
                    self.proc = None
                    time.sleep(RETRY_SLEEP); continue
            self._set_phase("connecting")   # child gone -> we are reconnecting
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
        self.obs_note = None          # last OBS-reflection note (None/"" = ok); read by status()
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
        now = time.time()
        sched = self.source.get()
        out = {"schedule_len": len(sched), "cookies": bool(self.cookies),
               "cookies_health": cookie_health(self.cookies, now=now),
               "source": self.source.health(), "feeds": {}}
        for k, f in self.feeds.items():
            ch, i = f.current_channel()
            out["feeds"][k] = {"port": f.port, "index": i, "stint": i + 1,
                               "channel": ch,
                               "state": "stopped" if f.paused else f.phase,
                               "state_age_s": round(now - f.phase_since, 1),
                               "last_error": f.last_error}
        if self.pov:
            raw = (self.pov_source.get()[:1] or [None])[0] if self.pov_source else None
            out["pov"] = {"port": self.pov.port, "url": raw,
                          "state": "stopped" if self.pov.paused else self.pov.phase,
                          "state_age_s": round(now - self.pov.phase_since, 1),
                          "source": self.pov_source.health() if self.pov_source else None}
        out["obs"] = {"reachable": not self.obs_note, "note": self.obs_note}
        return out

    def live_feed(self):
        """The on-air feed = the one on the lower (earlier) stint index."""
        return "A" if self.A.idx <= self.B.idx else "B"

    def live_after_next(self):
        """Which feed will be on air after the next /next: the one NOT advanced."""
        return "B" if self.live_feed() == "A" else "A"

    def _reflect(self, live, cut):
        """Push the on-air feed (A/B) into OBS off-thread; never blocks the HTTP
        response, never raises. Records the note for /status."""
        if _obs_ws is None:
            return

        def run():
            _applied, note = _obs_ws.reflect_feed_state(live, cut)
            self.obs_note = note or None
        threading.Thread(target=run, daemon=True).start()

    def next_auto(self):
        self.source.refresh(timeout=6)               # fresh sheet data at handover (bounded wait)
        new_live = self.live_after_next()
        target = "A" if new_live == "B" else "B"     # advance the OTHER (currently on-air) feed
        result = self.advance(target, +2)
        cut = self.feeds[new_live].phase == "serving"  # only hand over to a feed that is actually live
        if cut:
            self._reflect(new_live, cut=True)        # never flip visibility/audio onto a black/not-yet-serving feed
        return {**result, "obs_cut": cut}

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
        self._reflect(self.live_feed(), cut=False)   # set visibility/audio; director picks the scene
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


def _benign_client_disconnect(exc):
    """True when `exc` is a client hanging up mid-response — an OBS browser
    source closing, a panel tab refreshing, a director's tablet going to sleep.
    ConnectionError covers BrokenPipeError, ConnectionResetError and
    ConnectionAbortedError (WinError 10053, issue #25) on every platform. These
    are never a relay fault, so the server must neither try to answer on the dead
    socket nor log a traceback. A plain OSError (e.g. disk full) is NOT a
    ConnectionError and still surfaces."""
    return isinstance(exc, ConnectionError)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that stays silent when a client disconnects mid-
    response. The stdlib's handle_error() dumps a full traceback for the
    ConnectionAbortedError that wfile.flush() raises after the client is gone
    (issue #25: the HUD/timer browser sources poll and close constantly), which
    floods the relay console with noise that looks like a crash."""
    def handle_error(self, request, client_address):
        if _benign_client_disconnect(sys.exc_info()[1]):
            return                       # client went away — nothing to report
        super().handle_error(request, client_address)


def make_handler(relay, panel_path=None, hud_source=None, hud_path=None, assets_dir=None,
                 timer_store=None, timer_path=None, setup_ctl=None):
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
            # The panel/HUD/timer pages change between releases — never let a
            # browser serve a stale copy (e.g. a panel without the latest JS).
            self.send_header("Cache-Control", "no-store")
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
                if not p or p == ["status"]:
                    base = relay.status()
                    if timer_store: base["timer"] = timer_store.summary()
                    return self._send(base)
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
                if p[:1] == ["timer"]:
                    if p == ["timer"]:
                        if not timer_path: return self._send({"error": "timer disabled"}, 404)
                        return self._send_file(timer_path, "text/html; charset=utf-8")
                    if not timer_store:
                        return self._send({"error": "timer disabled"}, 404)
                    if p == ["timer", "data"]:   return self._send(timer_store.data())
                    if p == ["timer", "start"]:  return self._send(timer_store.start())
                    if p == ["timer", "stop"]:   return self._send(timer_store.stop())
                    if p == ["timer", "reset"]:  return self._send(timer_store.reset())
                    if p == ["timer", "show"]:   return self._send(timer_store.show())
                    if p == ["timer", "hide"]:   return self._send(timer_store.hide())
                    if len(p) == 3 and p[1] == "set":
                        dur = parse_duration(p[2])
                        if dur is None:
                            return self._send({"error": "duration must be H:MM:SS"}, 400)
                        return self._send(timer_store.set_duration(dur))
                    if len(p) == 3 and p[1] == "adjust":
                        try: delta = int(p[2])
                        except ValueError:
                            return self._send({"error": "adjust takes +/- seconds"}, 400)
                        return self._send(timer_store.adjust(delta))
                    return self._send({"error": "unknown", "path": self.path}, 404)
                if p[:1] == ["setup"]:
                    if not setup_ctl:
                        return self._send({"error": "setup control disabled"}, 404)
                    if p == ["setup", "data"]:
                        return self._send(setup_ctl.data())
                    if len(p) == 4 and p[1] == "set":
                        return self._send(setup_ctl.set_field(p[2].lower(),
                                                              unquote(p[3])))
                    if len(p) == 3 and p[1] == "clear":
                        return self._send(setup_ctl.set_field(p[2].lower(), ""))
                    return self._send({"error": "unknown", "path": self.path}, 404)
                if p == ["schedule", "data"]:
                    rows = relay.source.get_rows()
                    live = {f.idx: k for k, f in relay.feeds.items()}
                    return self._send({"rows": [{"row": i + 1, "sheetRow": line,
                                                 "url": u, "name": n,
                                                 "live": live.get(i)}
                                                for i, (u, n, line) in enumerate(rows)],
                                       "source": relay.source.health()})
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
            except ConnectionError:
                return None              # client hung up mid-response — benign (issue #25)
            except Exception as e:
                try:
                    return self._send({"error": str(e)}, 500)
                except ConnectionError:
                    return None          # client also gone before the error could be sent
        def _ok(self, r):
            self._send(r) if r else self._send({"error":"feed? (A/B)"}, 404)
        def do_POST(self):
            p = [x for x in urlparse(self.path).path.split("/") if x]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 65536:
                    return self._send({"error": "body too large"}, 413)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send({"error": "body must be JSON"}, 400)
                if not isinstance(body, dict):
                    return self._send({"error": "body must be a JSON object"}, 400)
                if not setup_ctl:
                    return self._send({"error": "setup control disabled"}, 404)
                if p == ["schedule", "set"]:
                    return self._send(setup_ctl.schedule_set(
                        body.get("row"), body.get("url"), body.get("name")))
                if p == ["pov", "set"]:
                    return self._send(setup_ctl.pov_set(body.get("url")))
                return self._send({"error": "unknown", "path": self.path}, 404)
            except ConnectionError:
                return None              # client hung up mid-response — benign (issue #25)
            except Exception as e:
                try:
                    return self._send({"error": str(e)}, 500)
                except ConnectionError:
                    return None          # client also gone before the error could be sent
    return H


def poller(source, interval, stop_evt):
    while not stop_evt.wait(interval):
        source.refresh()


def cookie_health(path, now=None, max_age_hours=COOKIE_MAX_AGE_H):
    """Cookie staleness for /status, computed on demand from the file mtime —
    during a 24 h event the cookies age while the relay runs, so this must be
    live, not a startup snapshot. Running cookie-less (path None / file gone)
    is a legitimate configuration (public streams): present=False, stale=False
    — the panel raises its cookie banner only on stale=True."""
    try:
        mtime = os.path.getmtime(path) if path and os.path.isfile(path) else None
    except OSError:
        mtime = None   # swapped/deleted between isfile and getmtime (cookie refresh)
    if mtime is None:
        return {"present": False, "age_h": None, "stale": False}
    now = time.time() if now is None else now
    age_h = round((now - mtime) / 3600, 1)
    return {"present": True, "age_h": age_h, "stale": age_h > max_age_hours}


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
                              timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              **_no_window_kwargs())
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
    ap.add_argument("--sheet-id", default=os.environ.get("RACECAST_SHEET_ID"),
                    help="Google Sheet ID for the schedule/POV tabs. Default: env "
                         "RACECAST_SHEET_ID (injected by the CLI from the active profile).")
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
    ap.add_argument("--timer-tab", default="Timer",
                    help="Google-Sheet tab holding the race-timer anchor (default 'Timer').")
    ap.add_argument("--no-timer", action="store_true",
                    help="Do not serve the race timer at /timer.")
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
    # line_buffering: show logs immediately. encoding="utf-8": the relay runs as a
    # daemon with stdout piped to a log file, so Python would otherwise use the
    # locale/ANSI codepage (cp1252 on Windows) and crash/mojibake on the non-ASCII
    # glyphs in our banner (-> arrows, em dashes) — same class as issue #24.
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception: pass   # not all stdout objects support reconfigure (e.g. pipes)

    if not args.sheet_csv_url and not args.sheet_id:
        sys.exit("ERROR: no Google Sheet configured. Set SHEET_ID in the active profile "
                 "(profiles/<name>/profile.env), or pass --sheet-id / --sheet-csv-url.")

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
    if cookies:
        _ch = cookie_health(cookies)
        if _ch["stale"]:
            print(f"WARN: cookies.txt is {_ch['age_h']:.0f} h old — cookies rotate; "
                  "run 'racecast cookies firefox' before the event.")

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

    # One sheet-write webhook powers the race timer AND the panel's
    # Setup/Schedule/POV controls (wiki: Sheet-Webhook).
    push_url = os.environ.get("RACECAST_SHEET_PUSH_URL")

    # Race timer: local file always; sheet sync derived from sheet-id/tab
    # (custom --sheet-csv-url -> local-only); push via RACECAST_SHEET_PUSH_URL.
    timer_store = None
    timer_path = None
    if not args.no_timer:
        timer_csv = None
        if not args.sheet_csv_url:
            timer_csv = (f"https://docs.google.com/spreadsheets/d/{args.sheet_id}"
                         f"/gviz/tq?tqx=out:csv&sheet={quote(args.timer_tab)}")
        timer_store = TimerStore(timer_csv, push_url,
                                 os.path.join(runtime, "timer.json"))
        timer_store.refresh()   # non-fatal: adopt a newer sheet anchor on startup
        for cand in (os.path.join(here, "timer.html"),
                     os.path.join(here, "..", "timer.html"),
                     os.path.join(here, "..", "obs", "timer.html")):
            if os.path.exists(cand):
                timer_path = os.path.abspath(cand); break
        if not timer_path:
            print("WARN: timer.html not found — /timer will 404.")

    source = ScheduleSource(csv_url, cache, local)
    source.load_initial(SCHEDULE_TEMPLATE)
    setup_ctl = SetupControl(push_url, hud_source, schedule_source=source) if hud_source else None
    if len(source.get()) < 2:
        print("INFO: schedule has fewer than 2 stints — Feed B idles on the empty next "
              "slot (black) until that stint's link is added; Feed A keeps serving stint 1.")

    relay = Relay(source, ports, logdir, cookies,
                  pov_source=pov_source, pov_port=args.pov_port,
                  start_stint=args.stint)
    relay.start()
    relay._reflect(relay.live_feed(), cut=False)     # pre-set Stint visibility/audio for the live feed

    stop_evt = threading.Event()
    threading.Thread(target=poller, args=(source, args.poll, stop_evt), daemon=True).start()
    if hud_source:
        threading.Thread(target=poller, args=(hud_source, args.hud_poll, stop_evt),
                         daemon=True).start()
    if timer_store and timer_store.csv_url:
        threading.Thread(target=poller, args=(timer_store, args.hud_poll, stop_evt),
                         daemon=True).start()

    handler = make_handler(relay, panel_path, hud_source, hud_path, assets_dir,
                           timer_store, timer_path, setup_ctl)
    bind_addrs = resolve_bind_addresses(
        args.bind, detect_tailscale_ip() if args.bind == "auto" else None)
    servers = []
    for addr in bind_addrs:
        try:
            servers.append(QuietThreadingHTTPServer((addr, args.http_port), handler))
        except OSError as e:
            print(f"  (warn) could not bind {addr}:{args.http_port} — {e}")
    if not servers:
        sys.exit(f"Could not bind the control server on {bind_addrs} port {args.http_port} "
                 f"— port may already be in use: run 'racecast preflight' or 'racecast status' "
                 f"to see what holds it.")

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
    if setup_ctl:
        mode = "writes ON" if push_url else "read-only (set RACECAST_SHEET_PUSH_URL)"
        print(f"  Panel sheet controls (/setup /schedule /pov/set): {mode}")
    if timer_store and timer_path:
        push = "sheet+push" if timer_store.push_url else (
            "sheet read-only (set RACECAST_SHEET_PUSH_URL for handover sync)"
            if timer_store.csv_url else "local only")
        print(f"  Race timer (OBS source): http://127.0.0.1:{args.http_port}/timer  "
              f"(tab '{args.timer_tab}', {push}; controls /timer/start | /timer/stop)")
    print(f"  Cookies (bot-check protection): {'ON — ' + cookies if cookies else 'off (no cookies.txt)'}")
    print(f"  Sheet poll every {args.poll}s.  Ctrl+C to stop.")
    # Serve every bound address; keep the last on the main thread for signals.
    for httpd in servers[:-1]:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    servers[-1].serve_forever()

if __name__ == "__main__":
    main()
