#!/usr/bin/env python3
"""Download the curated overlay-font set and pack it into fonts.zip for bundling.

The set IS overlay_build.GOOGLE_FONTS (the single source of truth, shared with the
Control Center typeahead fallback). Each family is fetched from Google Fonts the
same way the live "add a font" download does: the fixed googleapis css2 endpoint
yields a gstatic .woff2 URL, which is then downloaded. The result is written to
fonts.zip at the repo root (gitignored); tools/build-binary.py bundles that zip
INTO each frozen binary, and racecast.ensure_bundled_fonts() extracts it into
runtime/fonts/ on first start (so every install has the baseline set).

Network dependency: the build (CI included) reaches fonts.googleapis.com +
fonts.gstatic.com. Missing families are skipped with a warning; the build only
fails if NOTHING downloaded.

Maintainer tool — not shipped in the distributable package.

Usage:
  python3 tools/fetch-fonts.py                  # build ./fonts.zip
  python3 tools/fetch-fonts.py --out PATH       # write elsewhere
  python3 tools/fetch-fonts.py --version vX.Y.Z # stamp the manifest version
"""
import argparse, os, re, sys
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import overlay_build as ob
import fonts_bundle as fb

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _http(url, headers=None, binary=False, timeout=30):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:    # noqa: S310 (fixed Google hosts)
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def fetch_family(name, css_fetch=None, bin_fetch=None):
    """Return the woff2 bytes for a Google font family (bold weight first, then the
    family's default face), or None if it yields no gstatic woff2. Fetchers are
    injectable for tests."""
    css_fetch = css_fetch or (lambda u: _http(u, headers={"User-Agent": _UA}))
    bin_fetch = bin_fetch or (lambda u: _http(u, binary=True))
    for url in (ob.google_font_css_url(name), ob.google_font_css_url(name, weight=None)):
        try:
            css = css_fetch(url)
        except Exception:                          # a 400 for a missing weight, etc.
            continue
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css or "")
        if m:
            data = bin_fetch(m.group(1))
            if data:
                return data
    return None


def build(out_path, version="dev", families=None, css_fetch=None, bin_fetch=None):
    """Fetch every family and write the fonts.zip. Returns (stamp, missing[])."""
    families = ob.GOOGLE_FONTS if families is None else families
    fonts, missing = {}, []
    for fam in families:
        data = fetch_family(fam, css_fetch=css_fetch, bin_fetch=bin_fetch)
        if data:
            fonts[ob.google_font_filename(fam)] = data
        else:
            missing.append(fam)
    if not fonts:
        raise SystemExit("fetch-fonts: no fonts downloaded (network?)")
    stamp = fb.build_zip(out_path, fonts, version=version)
    return stamp, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "fonts.zip"))
    ap.add_argument("--version", default="dev")
    a = ap.parse_args()
    stamp, missing = build(a.out, version=a.version)
    print(f"wrote {a.out} (stamp {stamp[:12]}…, "
          f"{len(ob.GOOGLE_FONTS) - len(missing)} fonts)")
    if missing:
        print("WARNING: no woff2 for: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
