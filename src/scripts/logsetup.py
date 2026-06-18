"""Reusable, mostly-pure logging helpers for the racecast daemons and log surface.
stdlib-only by design — DO NOT import config.py here (the relay stays
dependency-light, like the other self-contained scripts). Covers: rotating
timestamped loggers, the single log-prune authority, subprocess line
classification + a pump, external-app log discovery, and archive resolution."""
import logging, os, re, sys, time
from logging.handlers import TimedRotatingFileHandler

DEFAULT_RETENTION_DAYS = 7
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    the trailing newline/carriage-return."""
    return f"[{source}] {line.rstrip(chr(10)).rstrip(chr(13))}"


def pump_subprocess(stream, logger, tag):
    """Read text lines from a subprocess pipe (stream) and log each at a classified
    level, prefixed `[tag]`. Runs to EOF; swallows read errors. Designed to run in a
    daemon thread so it never blocks daemon shutdown."""
    try:
        for raw in iter(stream.readline, ""):
            if raw == "":
                break
            line = raw.rstrip("\n").rstrip("\r")
            logger.log(classify_subproc_line(line), "[%s] %s", tag, line)
    except (ValueError, OSError):
        pass  # pipe closed mid-read — end the thread, never the daemon
