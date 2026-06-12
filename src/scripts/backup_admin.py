"""Pure logic for per-league look backups: zip overlay/+graphics/+media/ into a
named snapshot, list them, restore (full replace), delete. No argv parsing, no
network. Imported by the `racecast backup` CLI and the Control Center providers.
Mirrors chat_admin's discipline: validate before writing, atomic, fail-safe.

A snapshot is runtime/<profile>/backups/<slug>.zip with members:
  manifest.json   {label, slug, profile, created (ISO-UTC), files:[...], counts}
  overlay/...     profiles/<profile>/overlay/ contents
  graphics/...    runtime/<profile>/graphics/ contents
  media/...       runtime/<profile>/media/ contents
"""
import datetime
import json
import os
import re
import tempfile
import zipfile

SECTIONS = ("overlay", "graphics", "media")   # zip top-level dirs, in order


def sanitize_label(label):
    """A display label -> a safe filename slug (lowercase, spaces->-, drop other
    punctuation). Raises ValueError when nothing usable remains."""
    slug = re.sub(r"\s+", "-", (label or "").strip().lower())
    slug = re.sub(r"[^a-z0-9._-]", "", slug).strip("-._")
    if not slug:
        raise ValueError(f"label has no usable characters: {label!r}")
    return slug


def _iso_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_tree(zf, src_dir, arc_prefix):
    """Add every file under src_dir to the zip under arc_prefix/. Returns the list
    of relative arcnames added (empty when src_dir is missing/empty)."""
    added = []
    if not src_dir or not os.path.isdir(src_dir):
        return added
    for root, _dirs, files in os.walk(src_dir):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            arc = f"{arc_prefix}/{rel}"
            zf.write(full, arc)
            added.append(arc)
    return added


def create_backup(label, sources, profile, force=False):
    """Zip the three look dirs into runtime/<profile>/backups/<slug>.zip.
    `sources` is a {overlay,graphics,media,backups} dir map. Returns the zip path.
    Raises ValueError (bad label) or FileExistsError (slug taken, no force)."""
    slug = sanitize_label(label)
    backups_dir = sources["backups"]
    os.makedirs(backups_dir, exist_ok=True)
    path = os.path.join(backups_dir, f"{slug}.zip")
    if os.path.exists(path) and not force:
        raise FileExistsError(f"backup already exists: {slug} (use --force to overwrite)")
    files = []
    fd, tmp = tempfile.mkstemp(dir=backups_dir, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for sect in SECTIONS:
                files += _add_tree(zf, sources.get(sect), sect)
            manifest = {"label": label, "slug": slug, "profile": profile,
                        "created": _iso_utc(), "files": files,
                        "counts": {s: sum(1 for f in files if f.startswith(s + "/"))
                                   for s in SECTIONS}}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:  # best-effort cleanup of temp file on error
            pass
        raise
    return path


def read_manifest(path):
    """The manifest dict from a backup zip, or {} when unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}


def list_backups(backups_dir):
    """List snapshots in backups_dir -> [{slug,label,profile,created,bytes,counts}],
    newest 'created' first. Missing dir -> []."""
    out = []
    try:
        names = os.listdir(backups_dir)
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".zip"):
            continue
        path = os.path.join(backups_dir, fn)
        man = read_manifest(path)
        slug = man.get("slug") or fn[:-4]
        out.append({"slug": slug, "label": man.get("label", slug),
                    "profile": man.get("profile", ""),
                    "created": man.get("created", ""),
                    "counts": man.get("counts", {}),
                    "bytes": os.path.getsize(path)})
    out.sort(key=lambda i: i["created"], reverse=True)
    return out
