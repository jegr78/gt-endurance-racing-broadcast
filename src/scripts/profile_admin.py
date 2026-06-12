#!/usr/bin/env python3
"""Profile (league) management commands for the operator CLI: list / show /
use / new. Pure logic over config.py + the filesystem; racecast.py thin-wraps these.

config.py owns the READ side (resolve the active profile, load its values).
This module owns the WRITE side (create a profile directory, set the active
pointer) plus CLI arg-parsing, the global --profile splitter, and output
formatting. Stdlib only."""

import os
import re
import shutil

import config as cfg   # sibling in src/scripts (sys.path injected by racecast.py/tests)

PROFILE_VERBS = ("list", "show", "use", "new", "export", "import")
_USAGE = ("usage: racecast profile {list | show [<name>] | use <name> | "
          "new <name> [--from <source>] | export <name> [--no-assets] [--out PATH] | "
          "import <file> [--force]}")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def valid_profile_name(name):
    """A profile name is a lowercase slug: starts alphanumeric, then letters,
    digits, '-' or '_'. (It becomes a directory name + an env-var value.)"""
    return bool(_NAME_RE.match(name or ""))


def slugify(name):
    """Turn a free-form league name into a directory-safe slug: lowercase, runs of
    anything outside [a-z0-9_-] collapse to a single '-', and leading/trailing
    '-'/'_' are trimmed. 'Demo League' -> 'demo-league'; an already-valid slug is
    unchanged. Returns '' when nothing usable remains. Doubles as path-traversal
    defense ('../etc' -> 'etc')."""
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower())
    return s.strip("-_")


def _display_name(name):
    """The league display NAME we store from a typed profile name: trimmed, with
    internal whitespace runs collapsed to single spaces. 'Demo  League ' -> 'Demo League'."""
    return " ".join((name or "").split())


def _set_env_name(env_path, display):
    """Rewrite the first `NAME=` line in a profile.env to `display`, preserving the
    rest of the file (comments, other keys). Appends a NAME line if none exists."""
    with open(env_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for i, ln in enumerate(lines):
        if not ln.lstrip().startswith("#") and re.match(r"\s*NAME\s*=", ln):
            lines[i] = f"NAME={display}"
            break
    else:
        lines.append(f"NAME={display}")
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def parse_profile_args(rest):
    """argv after `profile` -> {verb, name, source, no_assets, out, file, force}.
    Raises ValueError (with usage text) on an unknown/missing verb, wrong arity,
    or an unknown flag."""
    if not rest or rest[0] not in PROFILE_VERBS:
        raise ValueError(_USAGE)
    verb, args = rest[0], rest[1:]
    out = {"verb": verb, "name": None, "source": "example",
           "no_assets": False, "out": None, "file": None, "force": False}
    if verb == "list":
        if args:
            raise ValueError(_USAGE)
    elif verb == "show":
        if len(args) > 1:
            raise ValueError(_USAGE)
        if args:
            out["name"] = args[0]
    elif verb == "use":
        if len(args) != 1:
            raise ValueError(_USAGE)
        out["name"] = args[0]
    elif verb == "new":
        if not args:
            raise ValueError(_USAGE)
        out["name"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--from":
                if not toks:
                    raise ValueError("--from requires a profile name")
                out["source"] = toks.pop(0)
            elif t.startswith("--from="):
                src = t.split("=", 1)[1]
                if not src:
                    raise ValueError("--from requires a profile name")
                out["source"] = src
            else:
                raise ValueError(_USAGE)
    elif verb == "export":
        if not args:
            raise ValueError(_USAGE)
        out["name"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--no-assets":
                out["no_assets"] = True
            elif t == "--out":
                if not toks:
                    raise ValueError("--out requires a path")
                out["out"] = toks.pop(0)
            elif t.startswith("--out="):
                val = t.split("=", 1)[1]
                if not val:
                    raise ValueError("--out requires a path")
                out["out"] = val
            else:
                raise ValueError(_USAGE)
    elif verb == "import":
        if not args:
            raise ValueError(_USAGE)
        out["file"] = args[0]
        toks = list(args[1:])
        while toks:
            t = toks.pop(0)
            if t == "--force":
                out["force"] = True
            else:
                raise ValueError(_USAGE)
    return out


def split_profile_flag(argv):
    """Pull a global `--profile <name>` / `--profile=<name>` out of anywhere in
    argv. Returns (cleaned_argv, name_or_None). Raises ValueError if --profile
    is given without a value."""
    out, name, i, toks = [], None, 0, list(argv)
    while i < len(toks):
        t = toks[i]
        if t == "--profile":
            if i + 1 >= len(toks):
                raise ValueError("--profile requires a profile name")
            name = toks[i + 1]
            i += 2
            continue
        if t.startswith("--profile="):
            name = t.split("=", 1)[1]
            if not name:
                raise ValueError("--profile requires a profile name")
            i += 1
            continue
        out.append(t)
        i += 1
    return out, name


def create_profile(root, name, source="example"):
    """Copy profiles/<source>/ -> profiles/<slug>/ and return the new dir path.
    The typed `name` may contain spaces/capitals (e.g. "Demo League"): it is slugged
    for the directory ("demo-league") and kept verbatim as the league display NAME in
    the new profile.env. Raises ValueError when the name has no sluggable
    characters, the slug is reserved/already exists, or the source is missing."""
    slug = slugify(name)
    if not valid_profile_name(slug):
        raise ValueError(f"invalid profile name {name!r} (needs at least one "
                         "letter or digit)")
    if slug == "example":
        raise ValueError("'example' is the reserved template name")
    pdir = cfg.profiles_dir(root)
    target = os.path.join(pdir, slug)
    if os.path.exists(target):
        raise ValueError(f"profile {slug!r} already exists ({target})")
    src = os.path.join(pdir, source)
    if not os.path.isfile(os.path.join(src, cfg.PROFILE_ENV_NAME)):
        raise ValueError(
            f"source profile {source!r} not found "
            f"({os.path.join(src, cfg.PROFILE_ENV_NAME)})")
    shutil.copytree(src, target)
    _set_env_name(os.path.join(target, cfg.PROFILE_ENV_NAME), _display_name(name))
    return target


def set_active_profile(root, runtime_root, name):
    """Write runtime/active-profile = name. Raises ValueError if `name` is not a
    known profile. Creates runtime_root if needed. Returns the name."""
    available = cfg.list_profiles(root)
    if name not in available:
        raise ValueError(f"unknown profile {name!r} "
                         f"(available: {', '.join(available) or 'none'})")
    os.makedirs(runtime_root, exist_ok=True)
    with open(os.path.join(runtime_root, cfg.ACTIVE_PROFILE_FILE),
              "w", encoding="utf-8") as fh:
        fh.write(name + "\n")
    return name


def format_profile_list(names, active):
    """One profile per line, the active one marked with '* '. ASCII only."""
    if not names:
        return "no profiles -- create one with `racecast profile new <name>`"
    return "\n".join(("* " if n == active else "  ") + n for n in names)


def mask_secret(value):
    """Show enough of a secret URL to recognize it without revealing the key.
    Empty -> '(unset)'; short -> '****'; else first 8 chars + '...'. ASCII only."""
    if not value:
        return "(unset)"
    if len(value) <= 8:
        return "****"
    return value[:8] + "..."


def format_profile_show(rcfg, active):
    """Multi-line human view of a ResolvedConfig. The sheet-push-url (carries a
    ?key= secret) is masked; the sheet id is shown (it is link-shared, not a
    secret). ASCII only."""
    tag = "  (active)" if rcfg.profile == active else ""
    return "\n".join([
        f"profile:        {rcfg.profile}{tag}",
        f"name:           {rcfg.name}",
        f"sheet_id:       {rcfg.sheet_id or '(unset)'}",
        f"sheet_push_url: {mask_secret(rcfg.sheet_push_url)}",
        f"intro_url:      {rcfg.intro_url or '(unset)'}",
        f"outro_url:      {rcfg.outro_url or '(unset)'}",
        f"logo:           {rcfg.logo_path or '(none)'}",
        f"profile_dir:    {rcfg.profile_dir}",
        f"runtime_dir:    {rcfg.runtime_dir}",
    ])
