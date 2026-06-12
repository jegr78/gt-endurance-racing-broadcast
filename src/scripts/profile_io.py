"""Pure logic for whole-profile export/import: zip a league profile (its
profiles/<name>/ tree + optional runtime graphics/media) into a portable bundle,
and import such a bundle on another machine. No argv parsing, no network.
Mirrors backup_admin's discipline: validate before writing, atomic, fail-safe.
Standalone (no sibling imports) so it loads in a bare test the same way.

Bundle layout (a .zip):
  manifest.json   {kind, schema, name, display, created, includes_assets, counts}
  profile/...     the whole profiles/<name>/ tree (profile.env, overlay/, logo, …)
  graphics/...    runtime/<name>/graphics/   (only when includes_assets)
  media/...       runtime/<name>/media/      (only when includes_assets)
"""
import datetime
import json
import os
import re
import tempfile
import zipfile

KIND = "profile-export"
SCHEMA = 1
ASSET_SECTIONS = ("graphics", "media")   # top-level subtrees beside profile/
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(name):
    """Free-form league name -> directory-safe slug. Doubles as path-traversal
    defense ('../etc' -> 'etc'). Mirrors profile_admin.slugify — keep in sync."""
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-_")


def _iso_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_tree(zf, src_dir, arc_prefix):
    """Add every file under src_dir to the zip under arc_prefix/. Returns the count
    added (0 when src_dir is missing/empty)."""
    n = 0
    if not src_dir or not os.path.isdir(src_dir):
        return n
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            zf.write(full, f"{arc_prefix}/{rel}")
            n += 1
    return n


def _read_display(profile_dir):
    """The NAME= value from profile.env, or '' when absent/unreadable."""
    try:
        with open(os.path.join(profile_dir, "profile.env"), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() == "NAME":
                    return v.strip()
    except OSError:
        pass
    return ""


def export_profile(name, sources, include_assets, dest):
    """Zip a profile into a portable bundle. `sources` = {profile_dir, graphics,
    media}. `dest` is a target .zip path, or a directory (then <slug>-profile.zip
    inside it). Returns the written path. Raises ValueError on a bad name or a
    profile dir that is missing / has no profile.env."""
    slug = slugify(name)
    if not slug:
        raise ValueError(f"invalid profile name: {name!r}")
    profile_dir = sources.get("profile_dir")
    if not profile_dir or not os.path.isdir(profile_dir):
        raise ValueError(f"profile dir not found: {profile_dir}")
    if not os.path.isfile(os.path.join(profile_dir, "profile.env")):
        raise ValueError("profile has no profile.env")
    path = os.path.join(dest, f"{slug}-profile.zip") if os.path.isdir(dest) else dest
    display = _read_display(profile_dir) or slug
    counts = {}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            counts["profile"] = _add_tree(zf, profile_dir, "profile")
            if include_assets:
                for sect in ASSET_SECTIONS:
                    counts[sect] = _add_tree(zf, sources.get(sect), sect)
            manifest = {"kind": KIND, "schema": SCHEMA, "name": slug,
                        "display": display, "created": _iso_utc(),
                        "includes_assets": bool(include_assets), "counts": counts}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:  # best-effort cleanup of temp file on error
            pass
        raise
    return path
