#!/usr/bin/env python3
"""Download the broadcast still-graphics for OBS from the Google Sheet 'Assets' tab.

Each Assets row whose value cell is a Google-Drive share link is downloaded as
'<Label>.png' into the graphics dir (repo: <repo>/runtime/graphics ; distributed
package: <package>/graphics). The Sheet label IS the filename — there is no mapping
table, so keep Sheet labels filesystem-clean. YouTube rows (Intro/Outro) are skipped;
those are handled by get-media.py. Never stored under src/, never committed.

Usage: python3 get-graphics.py [--out DIR] [--sheet-id ID] [--assets-tab NAME]
       [--only "Label[,Label...]"]
"""
import argparse, csv, io, os, re, sys
from urllib.parse import quote
from urllib.request import Request, urlopen


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root into
    os.environ (real env vars win). Bounded to the project (nearest ancestor with a
    .git/.env.example marker). KEEP IN SYNC with the copies in iro-feeds.py,
    setup-assets.py and get-media.py."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, mk)) for mk in (".git", ".env.example")):
            candidates.append(d)
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def drive_id(url):
    """Extract a Google-Drive file ID from a share or download URL, else None."""
    if not url:
        return None
    m = (re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
         or re.search(r"[?&]id=([A-Za-z0-9_-]+)", url))
    return m.group(1) if m else None


def to_download_url(file_id):
    """Direct-download endpoint for a Drive file ID (no API key)."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def safe_filename(label):
    """'<trimmed label>.png', or None if the label is empty or contains a path
    separator / control char. Spaces are allowed (OBS already uses them)."""
    name = (label or "").strip().strip(".")
    if not name or "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        return None
    return f"{name}.png"


def graphics_from_csv(rows):
    """Assets-tab rows -> {label: drive_url} for every row whose first non-empty value
    cell is a Google-Drive link. YouTube / non-Drive rows are skipped. Label verbatim."""
    out = {}
    for row in rows:
        if not row:
            continue
        label = (row[0] or "").strip()
        if not label:
            continue
        for cell in row[1:]:
            v = (cell or "").strip()
            if not v:
                continue
            if "drive.google.com" in v and drive_id(v):
                out[label] = v
            break  # only the first non-empty value cell matters
    return out


def graphics_dir(here):
    """Where graphics live when --out is not given. Mirrors get-media.media_dir():
    repo (src/relay) -> <repo>/runtime/graphics ; package (relay) -> <pkg>/graphics."""
    if os.path.basename(here) == "relay" and os.path.basename(os.path.dirname(here)) == "src":
        return os.path.join(os.path.dirname(os.path.dirname(here)), "runtime", "graphics")
    return os.path.join(os.path.dirname(here), "graphics")


def fetch_assets_csv(sheet_id, tab, timeout=15):
    """Fetch the Assets tab as CSV via the public gviz endpoint (no API key)."""
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/gviz/tq?tqx=out:csv&sheet={quote(tab)}")
    req = Request(url, headers={"User-Agent": "iro-graphics/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(url, out_path, timeout=60):
    """GET a Drive file to out_path as a PNG. Handles the large-file confirm
    interstitial. Writes atomically; verifies the PNG signature before committing."""
    req = Request(url, headers={"User-Agent": "iro-graphics/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    if ctype.startswith("text/html"):
        m = re.search(rb"confirm=([0-9A-Za-z_-]+)", data)
        if not m:
            raise RuntimeError("Drive returned an HTML interstitial with no confirm token")
        req2 = Request(url + "&confirm=" + m.group(1).decode(),
                       headers={"User-Agent": "iro-graphics/1.0"})
        with urlopen(req2, timeout=timeout) as resp2:
            data = resp2.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("downloaded data is not a PNG")
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=graphics_dir(here),
                    help="Target dir for <Label>.png files (default: graphics_dir).")
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID holding the Assets tab. Default: env IRO_SHEET_ID.")
    ap.add_argument("--assets-tab", default="Assets")
    ap.add_argument("--only", default=None,
                    help="Comma-separated labels to fetch (default: all graphic rows).")
    a = ap.parse_args()

    if not a.sheet_id:
        sys.exit("ERROR: no Sheet ID (set IRO_SHEET_ID in .env or pass --sheet-id).")
    try:
        csv_text = fetch_assets_csv(a.sheet_id, a.assets_tab)
    except Exception as e:
        sys.exit(f"ERROR: could not read sheet Assets tab: {e}")

    graphics = graphics_from_csv(list(csv.reader(io.StringIO(csv_text))))
    if a.only:
        wanted = {x.strip() for x in a.only.split(",") if x.strip()}
        graphics = {k: v for k, v in graphics.items() if k in wanted}
    if not graphics:
        sys.exit("ERROR: no graphic (Drive-link) rows found in the Assets tab.")

    os.makedirs(a.out, exist_ok=True)
    failed = []
    for label in sorted(graphics):
        fname = safe_filename(label)
        if not fname:
            print(f"WARNING: skipping unsafe label {label!r}")
            failed.append(label)
            continue
        out_path = os.path.join(a.out, fname)
        print(f"Downloading {label}: {fname}")
        try:
            download(to_download_url(drive_id(graphics[label])), out_path)
            print(f"OK -> {out_path}")
        except Exception as e:
            print(f"WARNING: download failed for {label}: {e}")
            failed.append(label)

    if failed:
        sys.exit(f"Incomplete: {', '.join(sorted(failed))} not downloaded.")


if __name__ == "__main__":
    main()
