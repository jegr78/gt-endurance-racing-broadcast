"""Reusable, mostly-pure logging helpers for the racecast daemons and log surface.
stdlib-only by design — DO NOT import config.py here (the relay stays
dependency-light, like the other self-contained scripts). Covers: rotating
timestamped loggers, the single log-prune authority, subprocess line
classification + a pump, external-app log discovery, and archive resolution."""
import logging, os, re, sys, time
from logging.handlers import TimedRotatingFileHandler

DEFAULT_RETENTION_DAYS = 7


def configure_logging(name, log_path, level=logging.INFO, to_stdout=None):
    """A logging.Logger writing timestamped, leveled lines to log_path with daily
    midnight rotation (archive suffix `.YYYY-MM-DD`). backupCount=0 -> the handler
    never deletes; prune_old_logs is the sole deletion authority. A stdout
    StreamHandler is added only on a TTY (foreground run) — a daemon whose stdout is
    a redirected file must not double-write. Idempotent per `name`."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if any(getattr(h, "_racecast", False) for h in logger.handlers):
        return logger
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = TimedRotatingFileHandler(log_path, when="midnight", backupCount=0,
                                  encoding="utf-8")
    fh.setFormatter(fmt)
    fh._racecast = True
    logger.addHandler(fh)
    on_tty = sys.stdout.isatty() if to_stdout is None else to_stdout
    if on_tty:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh._racecast = True
        logger.addHandler(sh)
    return logger


def prune_old_logs(log_dir, keep_days=DEFAULT_RETENTION_DAYS, now_ts=None):
    """Delete files in log_dir whose mtime is older than keep_days; return the
    removed paths. The ONLY log-deletion path — covers every log type (rotated
    console/feed logs, *.boot.log, the Tailscale snapshot, any local OBS copies).
    `now_ts` is injectable for deterministic tests. Best-effort: unreadable dir or
    a vanishing file is skipped, never raised."""
    now_ts = time.time() if now_ts is None else now_ts
    cutoff = now_ts - keep_days * 86400
    removed = []
    try:
        names = os.listdir(log_dir)
    except OSError:
        return removed
    for name in names:
        p = os.path.join(log_dir, name)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed.append(p)
        except OSError:
            pass  # file vanished between listdir and remove — skip it
    return sorted(removed)


_ERROR_HINTS = ("error", "fatal", "forbidden", "403", "401", "traceback",
                "exception", "failed", "denied", "could not", "no such")
_WARN_HINTS = ("warn", "retry", "retrying", "unable", "timeout", "timed out",
               "waiting for")


def classify_subproc_line(line):
    """Heuristic logging level for one pumped subprocess line."""
    low = line.lower()
    if any(h in low for h in _ERROR_HINTS):
        return logging.ERROR
    if any(h in low for h in _WARN_HINTS):
        return logging.WARNING
    return logging.INFO


def tag_line(source, line):
    """Prefix a single log line with its source tag for the merged view, stripping
    the trailing newline/carriage-return. chr(10)/chr(13) avoid a backslash escape
    inside the f-string expression (only allowed on Python 3.12+; the repo is 3.11)."""
    return f"[{source}] {line.rstrip(chr(10)).rstrip(chr(13))}"


def pump_subprocess(stream, logger, tag):
    """Read text lines from a subprocess pipe (stream) and log each at a classified
    level, prefixed `[tag]`. Runs to EOF; swallows read errors. Designed to run in a
    daemon thread so it never blocks daemon shutdown."""
    try:
        for raw in iter(stream.readline, ""):   # sentinel "" stops at EOF
            line = raw.rstrip("\n").rstrip("\r")
            logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
    except (ValueError, OSError):
        pass  # pipe closed mid-read — end the thread, never the daemon


def obs_log_dir(platform, home=None, env=None):
    """OBS Studio's log directory for a platform. Fixed-OS path -> string concat
    with '/', never os.path.join (see plan note). Returns the dir (may not exist)."""
    home = os.path.expanduser("~") if home is None else home
    env = os.environ if env is None else env
    if platform == "darwin":
        return home + "/Library/Application Support/obs-studio/logs"
    if platform.startswith("win") or platform == "nt":
        base = (env.get("APPDATA") or (home + "/AppData/Roaming")).replace("\\", "/")
        return base + "/obs-studio/logs"
    return home + "/.config/obs-studio/logs"


def list_logs(log_dir):
    """Regular files in log_dir, newest-first by mtime; [] if dir is absent."""
    try:
        files = [os.path.join(log_dir, f) for f in os.listdir(log_dir)]
    except OSError:
        return []
    files = [f for f in files if os.path.isfile(f)]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def newest_log(log_dir):
    """Newest file in log_dir, or None."""
    files = list_logs(log_dir)
    return files[0] if files else None


def archive_dates(log_dir, basenames):
    """Sorted-descending list of YYYY-MM-DD dates for which any of `basenames` has a
    rotated archive (`<basename>.<date>`) in log_dir."""
    dates = set()
    for path in list_logs(log_dir):
        name = os.path.basename(path)
        for base in basenames:
            m = re.fullmatch(re.escape(base) + r"\.(\d{4}-\d{2}-\d{2})", name)
            if m:
                dates.add(m.group(1))
    return sorted(dates, reverse=True)


def resolve_archive(log_dir, basename, date):
    """Realpath of the archive `<basename>.<date>` inside log_dir, or None. Guards
    traversal: `date` must be exactly YYYY-MM-DD, `basename` must carry no path
    separators, and the resolved path must stay inside log_dir."""
    if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    if not basename or "/" in basename or "\\" in basename or os.sep in basename:
        return None
    root = os.path.realpath(log_dir)
    full = os.path.realpath(os.path.join(log_dir, f"{basename}.{date}"))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:
        return None   # different drives on Windows
    if not inside or not os.path.isfile(full):
        return None
    return full
