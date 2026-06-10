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


PROFILE_ENV_NAME = "profile.env"


def profiles_dir(root):
    return os.path.join(root, "profiles")


def list_profiles(root):
    """Sorted names of profiles/<name>/ dirs that contain a profile.env.
    'example' (the shipped template) is excluded — it is not a usable league."""
    pdir = profiles_dir(root)
    if not os.path.isdir(pdir):
        return []
    names = []
    for name in sorted(os.listdir(pdir)):
        if name == "example":
            continue
        if os.path.isfile(os.path.join(pdir, name, PROFILE_ENV_NAME)):
            names.append(name)
    return names


def parse_profile(root, name):
    """Read profiles/<name>/profile.env into a dict. Raises FileNotFoundError if
    the profile.env is missing."""
    p = os.path.join(profiles_dir(root), name, PROFILE_ENV_NAME)
    with open(p, encoding="utf-8") as fh:
        return parse_env_text(fh.read())


ACTIVE_PROFILE_FILE = "active-profile"   # lives under runtime/


def read_active_pointer(runtime_root):
    """Return the persisted active-profile name from runtime/active-profile, or
    None if the pointer file is absent/empty."""
    p = os.path.join(runtime_root, ACTIVE_PROFILE_FILE)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            return fh.read().strip() or None
    return None


class ProfileError(Exception):
    """The active profile could not be resolved (none / ambiguous / unknown)."""


def resolve_active_profile(available, *, override=None, env_value=None,
                           pointer=None):
    """Resolve the active profile by precedence:
        override (--profile) > env_value (RACECAST_PROFILE) > pointer
        (runtime/active-profile) > the sole profile when exactly one exists.
    `available` is the list of known profile names. Raises ProfileError with a
    helpful message on an unknown name, ambiguity, or no profiles at all."""
    for source, value in (("--profile", override),
                          ("RACECAST_PROFILE", env_value),
                          ("active-profile", pointer)):
        if value:
            if value not in available:
                raise ProfileError(
                    f"{source}={value!r} is not a known profile "
                    f"(available: {', '.join(available) or 'none'})")
            return value
    if len(available) == 1:
        return available[0]
    if not available:
        raise ProfileError(
            "no profiles found — create one under profiles/<name>/profile.env")
    raise ProfileError(
        "multiple profiles exist; choose one with --profile or "
        f"'racecast profile use <name>' (available: {', '.join(available)})")
