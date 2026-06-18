"""Reusable, mostly-pure logging helpers for the racecast daemons and log surface.
stdlib-only by design — DO NOT import config.py here (the relay stays
dependency-light, like the other self-contained scripts). Covers: rotating
timestamped loggers, the single log-prune authority, subprocess line
classification + a pump, external-app log discovery, and archive resolution."""
import logging, os, re, sys
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
