#!/usr/bin/env python3
"""Profile-aware configuration resolver for the GT Endurance Racing Broadcast
toolkit (binary: racecast).

Single source of truth for resolving which league ("profile") is active and
loading its config. Two layers:

  * machine .env  (repo root / next to the binary) — RACECAST_* vars, all leagues
  * profiles/<name>/profile.env — the league: SHEET_ID, SHEET_PUSH_URL, NAME, ...

The bounded .env loader here is the CANONICAL copy. The standalone scripts
(relay/iro-feeds.py, setup-assets.py, relay/get-media.py, relay/get-graphics.py)
keep their own self-contained load_dotenv on purpose — the relay is deliberately
import-free (same rationale as its duplicated detect_tailscale_ip) and all four
run in-process under the frozen binary. Keep the parsing/boundary rules in sync.
"""

import os

PROJECT_MARKERS = (".git", ".env.example")


def find_project_root(start, markers=PROJECT_MARKERS, max_levels=4):
    """Walk up from `start` (at most `max_levels`) to the nearest ancestor that
    holds a marker. Returns that directory, or None. Bounded on purpose: never
    reaches an unrelated parent (same security boundary as the scripts)."""
    d = start
    for _ in range(max_levels):
        if any(os.path.exists(os.path.join(d, mk)) for mk in markers):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def parse_env_text(text):
    """Parse KEY=VALUE lines into a dict. Ignores blank lines, '#' comments and
    lines without '='; strips surrounding whitespace and a single layer of
    matching quotes. '=' inside a value is preserved. Pure."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_machine_env(start):
    """Read the machine .env (from `start` or the project root above it) into a
    dict. Does NOT mutate os.environ — callers decide precedence. Bounded to the
    project (same boundary as find_project_root). Returns {} if no .env."""
    candidates = [start]
    root = find_project_root(start)
    if root and root != start:
        candidates.append(root)
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return parse_env_text(fh.read())
    return {}
