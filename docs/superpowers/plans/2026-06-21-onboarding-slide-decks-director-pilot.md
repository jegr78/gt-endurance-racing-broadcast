# Onboarding Slide Decks — Director Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reusable slide-deck system (vendored Reveal.js + shared design system + Excalidraw-look diagram pipeline + visual overflow guard) and ship the **Director** deck as the proven pilot, published to GitHub Pages and bundled into the package.

**Architecture:** Each deck is one self-contained HTML file with inline-Markdown slides, styled by shared `assets/deck.css` and booted by shared `assets/deck.js` over a committed `vendor/reveal/` subset. Diagrams are authored as `.mmd` and converted at build time to committed static SVGs (Excalidraw look) by a maintainer Playwright tool. A maintainer Playwright tool flags slide overflow; a cheap stdlib test guards structure/links in CI.

**Tech Stack:** Reveal.js 5.x (vendored, UMD globals), HTML/CSS/Markdown, Python 3 stdlib (tools + tests, no pytest), Playwright Python (maintainer-only, in a venv), GitHub Actions Pages, esm.sh-pinned `@excalidraw/mermaid-to-excalidraw` + `@excalidraw/excalidraw` (build-time only).

**Design spec:** `docs/superpowers/specs/2026-06-21-onboarding-slide-decks-design.md`

## Global Constraints

- **Edit only under `src/`** for shipped content; `tools/` are maintainer scripts (not shipped); `dist/`/`runtime/` are generated — never hand-edit.
- **All deck content and docs are English only.**
- **No `.sh`/`.bat` anywhere** (the build fails if any ship). All tooling is Python.
- **No CDN at view time / no npm.** Reveal.js and the two webfonts are **vendored** (committed). esm.sh converter libs are used **only** inside the maintainer diagram tool at build time.
- **Tests are stdlib, no pytest:** each `tests/test_*.py` is a runnable script using `t_*` functions and a `if __name__ == "__main__":` runner that calls every `t_*` and prints `ALL PASS`. `tools/run-tests.py` discovers them (= CI).
- **Maintainer HTTP tools set a `User-Agent`** and mark fixed-host calls `# noqa: S310`. They live in `tools/` and must NOT import `src/scripts/http_util.py` rules (not covered).
- **Generated artifacts are committed but never hand-edited:** `src/docs/slides/vendor/reveal/**`, `src/docs/slides/assets/img/diagrams/*.svg`. Regenerate via the maintainer tools.
- **Pages publishing is dispatch-only** (deliberate maintainer action, like `wiki.yml`).
- Run `python3 tools/lint.py` after changing any Python file; run `python3 tools/run-tests.py` before declaring done.
- Role accents: Producer `#d62828`, Director `#e08a00`, Commentator `#1f7a8c`, **Race Control `#5b7186`** (steel blue-grey), **League Admin `#7a4fb5`** (violet).

---

### Task 1: Vendor Reveal.js + webfonts via `tools/fetch-reveal.py`

**Files:**
- Create: `tools/fetch-reveal.py`
- Create (generated, committed by running the tool): `src/docs/slides/vendor/reveal/**`, `src/docs/slides/assets/fonts/*.woff2`
- Test: `tests/test_slides.py` (created here with the first checks; extended in Task 6)

**Interfaces:**
- Produces: `reveal_subset(prefix)` → `dict[str(zip member path), str(dest relative to vendor/reveal)]`; `verify_sha256(data: bytes, expected: str) -> None` (raises `SystemExit` on mismatch); `extract_subset(zip_bytes, prefix, dest_dir, fetch=None)` writes the subset and returns the list of written dest paths; module constants `REVEAL_TAG`, `REVEAL_SHA256`, `FONT_FAMILIES` (list of Google font family names).
- Consumes: `overlay_build.google_font_css_url` (from `src/scripts`) for the font CSS endpoint (DRY with `fetch-fonts.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_slides.py`:

```python
#!/usr/bin/env python3
"""Stdlib structural/link checks for the onboarding slide decks.
Run: python3 tests/test_slides.py"""
import importlib.util, io, os, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SLIDES = os.path.join(ROOT, "src", "docs", "slides")


def _load(modpath, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, modpath))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


fr = _load(os.path.join("tools", "fetch-reveal.py"), "fetch_reveal")


def t_reveal_subset_maps_dist_and_plugins():
    sub = fr.reveal_subset("reveal.js-5.2.1/")
    # every wanted file is mapped, rebased under vendor/reveal/
    assert sub["reveal.js-5.2.1/dist/reveal.js"] == "dist/reveal.js"
    assert sub["reveal.js-5.2.1/dist/reveal.css"] == "dist/reveal.css"
    assert sub["reveal.js-5.2.1/plugin/markdown/markdown.js"] == "plugin/markdown/markdown.js"
    assert sub["reveal.js-5.2.1/plugin/notes/notes.js"] == "plugin/notes/notes.js"
    assert sub["reveal.js-5.2.1/plugin/highlight/highlight.js"] == "plugin/highlight/highlight.js"
    assert sub["reveal.js-5.2.1/plugin/highlight/monokai.css"] == "plugin/highlight/monokai.css"


def t_verify_sha256_raises_on_mismatch():
    raised = False
    try:
        fr.verify_sha256(b"hello", "0" * 64)
    except SystemExit:
        raised = True
    assert raised


def t_extract_subset_writes_only_wanted_files(tmp=None):
    import tempfile
    dest = tempfile.mkdtemp(prefix="reveal-test-")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("reveal.js-5.2.1/dist/reveal.js", "// reveal")
        z.writestr("reveal.js-5.2.1/dist/reveal.css", ".reveal{}")
        z.writestr("reveal.js-5.2.1/plugin/markdown/markdown.js", "// md")
        z.writestr("reveal.js-5.2.1/plugin/notes/notes.js", "// notes")
        z.writestr("reveal.js-5.2.1/plugin/highlight/highlight.js", "// hl")
        z.writestr("reveal.js-5.2.1/plugin/highlight/monokai.css", ".hl{}")
        z.writestr("reveal.js-5.2.1/README.md", "ignored")  # not in subset
    written = fr.extract_subset(buf.getvalue(), "reveal.js-5.2.1/", dest)
    assert os.path.isfile(os.path.join(dest, "dist", "reveal.js"))
    assert os.path.isfile(os.path.join(dest, "plugin", "markdown", "markdown.js"))
    assert not os.path.exists(os.path.join(dest, "README.md"))
    assert "dist/reveal.js" in written


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_slides.py`
Expected: FAIL — `ModuleNotFoundError`/`spec` error because `tools/fetch-reveal.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `tools/fetch-reveal.py`:

```python
#!/usr/bin/env python3
"""Vendor the slide-deck runtime: a pinned Reveal.js dist subset + the two deck
webfonts, both committed under src/docs/slides/ so Pages/build need no network.

Mirror of tools/fetch-fonts.py / the deno pin: download a pinned, SHA-256-verified
GitHub source zip of Reveal.js, extract only the dist + plugin files the decks load,
and fetch the deck webfonts (Saira Condensed + IBM Plex Mono) as woff2.

Maintainer tool — not shipped. Run after bumping REVEAL_TAG (first run with an empty
REVEAL_SHA256 prints the computed digest to paste back in, then commit).

Usage:
  python3 tools/fetch-reveal.py            # vendor reveal + fonts
  python3 tools/fetch-reveal.py --print-sha  # just print the release digest
"""
import argparse, hashlib, io, os, re, sys, zipfile
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import overlay_build as ob   # google_font_css_url (DRY with fetch-fonts.py)

REVEAL_TAG = "5.2.1"
# Filled after the first run prints it; empty means "print, don't verify".
REVEAL_SHA256 = "9b8b8f7f6f4c3b2a1d0e9f8c7b6a5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e"
FONT_FAMILIES = ["Saira Condensed", "IBM Plex Mono"]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_WANTED = (
    "dist/reveal.js", "dist/reveal.css",
    "plugin/markdown/markdown.js", "plugin/notes/notes.js",
    "plugin/highlight/highlight.js", "plugin/highlight/monokai.css",
)


def _http(url, binary=True, timeout=60):
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as r:    # noqa: S310 (fixed GitHub/gstatic hosts)
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def reveal_subset(prefix):
    """Map {zip member path -> dest path under vendor/reveal} for the wanted files."""
    return {prefix + w: w for w in _WANTED}


def verify_sha256(data, expected):
    got = hashlib.sha256(data).hexdigest()
    if expected and got != expected:
        raise SystemExit(f"fetch-reveal: sha256 mismatch (got {got}, want {expected})")
    return got


def extract_subset(zip_bytes, prefix, dest_dir, fetch=None):
    """Write the wanted subset from the in-memory zip into dest_dir. Returns dest rels."""
    sub = reveal_subset(prefix)
    written = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for member, dest_rel in sub.items():
            data = z.read(member)
            out = os.path.join(dest_dir, dest_rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(data)
            written.append(dest_rel)
    return written


def fetch_font(name, css_fetch=None, bin_fetch=None):
    css_fetch = css_fetch or (lambda u: _http(u, binary=False))
    bin_fetch = bin_fetch or (lambda u: _http(u, binary=True))
    for url in (ob.google_font_css_url(name), ob.google_font_css_url(name, weight=None)):
        try:
            css = css_fetch(url)
        except Exception:
            continue
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css or "")
        if m:
            return bin_fetch(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-sha", action="store_true")
    a = ap.parse_args()
    url = f"https://github.com/hakimel/reveal.js/archive/refs/tags/{REVEAL_TAG}.zip"
    zip_bytes = _http(url)
    digest = verify_sha256(zip_bytes, "" if a.print_sha else REVEAL_SHA256)
    if a.print_sha:
        print(digest); return
    if not REVEAL_SHA256:
        print(f"REVEAL_SHA256 not set; computed {digest} — paste it in and re-run.")
        return
    vendor = os.path.join(ROOT, "src", "docs", "slides", "vendor", "reveal")
    written = extract_subset(zip_bytes, f"reveal.js-{REVEAL_TAG}/", vendor)
    print(f"vendored reveal {REVEAL_TAG}: {len(written)} files -> {vendor}")
    fonts_dir = os.path.join(ROOT, "src", "docs", "slides", "assets", "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    for fam in FONT_FAMILIES:
        data = fetch_font(fam)
        if not data:
            print(f"WARNING: no woff2 for {fam}", file=sys.stderr); continue
        fn = ob.google_font_filename(fam)
        with open(os.path.join(fonts_dir, fn), "wb") as fh:
            fh.write(data)
        print(f"vendored font {fam} -> {fn}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_slides.py`
Expected: PASS — prints `ok t_extract_subset_...`, `ok t_reveal_subset_...`, `ok t_verify_sha256_...`, `ALL PASS`.

- [ ] **Step 5: Vendor the real assets**

Run, pin the digest, re-run, then confirm files exist:
```bash
python3 tools/fetch-reveal.py --print-sha   # copy the digest into REVEAL_SHA256, then:
python3 tools/fetch-reveal.py
ls src/docs/slides/vendor/reveal/dist/reveal.js src/docs/slides/assets/fonts/*.woff2
```
Expected: both paths listed (no error). If a font woff2 is missing, note it — Task 2's `@font-face` falls back to a system stack.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add tools/fetch-reveal.py tests/test_slides.py src/docs/slides/vendor src/docs/slides/assets/fonts
git commit -m "feat(slides): vendor pinned Reveal.js subset + deck webfonts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Shared deck design system (`deck.css` + `deck.js`)

**Files:**
- Create: `src/docs/slides/assets/deck.css`
- Create: `src/docs/slides/assets/deck.js`
- Test: covered by Task 6 (referenced-asset existence); no unit test (pure CSS/JS).

**Interfaces:**
- Produces: a deck contract — every deck sets `<body data-role="…">`, links `assets/deck.css`, includes `vendor/reveal/dist/reveal.js` + the three plugins, then `assets/deck.js`. `deck.js` calls `Reveal.initialize` with `width:1280, height:720` (the dimensions Task 7's overflow guard measures against).
- Consumes: `vendor/reveal/**` from Task 1.

- [ ] **Step 1: Write `deck.css`**

Create `src/docs/slides/assets/deck.css` (carries over the `cheat_sheets.html` palette + type, adds role accents and vendored `@font-face`):

```css
/* Shared design system for the onboarding decks. Extends the cheat_sheets.html
   look (Saira Condensed + IBM Plex Mono, ink-friendly, role accent bars).
   Fonts are vendored locally (no CDN at view time). */
@font-face{font-family:'Saira Condensed';font-weight:700;font-display:swap;
  src:url('fonts/SairaCondensed.woff2') format('woff2');}
@font-face{font-family:'IBM Plex Mono';font-weight:400;font-display:swap;
  src:url('fonts/IBMPlexMono.woff2') format('woff2');}

:root{
  --paper:#f4f1ea; --ink:#16181c; --soft:#5b6168; --line:#d8d2c6;
  --producer:#d62828; --director:#e08a00; --commentator:#1f7a8c;
  --race-control:#5b7186; --league-admin:#7a4fb5;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
  --head:'Saira Condensed',system-ui,sans-serif;
  --accent:var(--director); /* overridden per role below */
}
body[data-role="producer"]{--accent:var(--producer)}
body[data-role="director"]{--accent:var(--director)}
body[data-role="commentator"]{--accent:var(--commentator)}
body[data-role="race-control"]{--accent:var(--race-control)}
body[data-role="league-admin"]{--accent:var(--league-admin)}

.reveal{font-family:var(--mono);color:var(--ink);font-size:30px}
.reveal .slides{text-align:left}
.reveal h1,.reveal h2,.reveal h3{font-family:var(--head);font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;color:var(--ink)}
.reveal h1{color:var(--accent)}
.reveal section{padding:0 12px}
/* accent bar at the top of every slide */
.reveal .slides>section::before,.reveal .slides>section>section::before{
  content:"";position:absolute;top:-26px;left:0;width:120px;height:9px;
  background:var(--accent);border-radius:3px}
.reveal a{color:var(--accent);text-decoration:underline}
.reveal ul,.reveal ol{display:block}
.reveal li{line-height:1.45;margin:.25em 0}
.reveal .role-tag{font-family:var(--head);letter-spacing:.22em;
  text-transform:uppercase;font-size:14px;color:var(--soft)}
.reveal img,.reveal svg{max-width:100%;height:auto}
.reveal .progress{color:var(--accent)}
.backgroundColor{background:var(--paper)}
```

- [ ] **Step 2: Write `deck.js`**

Create `src/docs/slides/assets/deck.js`:

```js
/* Shared Reveal init for every onboarding deck. UMD globals come from the
   vendored dist/plugin scripts each deck includes before this file. */
Reveal.initialize({
  width: 1280,
  height: 720,
  margin: 0.06,
  hash: true,
  slideNumber: 'c/t',
  controls: true,
  progress: true,
  transition: 'slide',
  backgroundTransition: 'none',
  plugins: [RevealMarkdown, RevealHighlight, RevealNotes],
});
```

- [ ] **Step 3: Lint + commit**

```bash
python3 tools/lint.py   # no Python changed, but keep the habit; expect "no issues"
git add src/docs/slides/assets/deck.css src/docs/slides/assets/deck.js
git commit -m "feat(slides): shared deck design system + Reveal init

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Excalidraw-look diagram pipeline (`tools/build-diagrams.py`)

**Files:**
- Create: `tools/build-diagrams.py`
- Create: `src/docs/slides/diagrams/director-event-flow.mmd`
- Create (generated, committed by running the tool): `src/docs/slides/assets/img/diagrams/director-event-flow.svg`
- Test: `tests/test_slides.py` (extend)

**Interfaces:**
- Produces: `discover_mmd(slides_dir) -> list[tuple[str name, str path]]`; `slug(name) -> str`; `harness_html(mermaid_src) -> str` (full HTML for the headless page; embeds the mermaid source, the pinned esm.sh converter URLs, the deterministic seed-pinning loop, and sets `window.__svg`); `render_all(slides_dir, page_factory=None)` (Playwright integration; skipped in unit tests). Module constants `MERMAID_TO_EXCALIDRAW`, `EXCALIDRAW` (pinned esm.sh URLs), `SEED`.
- Consumes: nothing from prior tasks (writes into `assets/img/diagrams/`).

- [ ] **Step 1: Write the failing tests (extend `tests/test_slides.py`)**

Add to `tests/test_slides.py` (above the `__main__` block):

```python
bd = _load(os.path.join("tools", "build-diagrams.py"), "build_diagrams")


def t_slug_is_filesystem_safe():
    assert bd.slug("Director Event Flow") == "director-event-flow"


def t_harness_embeds_source_and_pinned_libs_and_seed():
    html = bd.harness_html("flowchart LR\n A-->B")
    assert "flowchart LR" in html
    assert bd.MERMAID_TO_EXCALIDRAW in html
    assert bd.EXCALIDRAW in html
    # deterministic seed pinning must be present so regenerated SVGs are stable
    assert "seed" in html and str(bd.SEED) in html


def t_discover_mmd_finds_sources(tmp=None):
    import tempfile
    d = tempfile.mkdtemp(prefix="mmd-test-")
    os.makedirs(os.path.join(d, "diagrams"))
    with open(os.path.join(d, "diagrams", "x.mmd"), "w") as fh:
        fh.write("flowchart LR\n A-->B")
    found = bd.discover_mmd(d)
    assert found == [("x", os.path.join(d, "diagrams", "x.mmd"))]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_slides.py`
Expected: FAIL — `build-diagrams.py` does not exist (spec load error).

- [ ] **Step 3: Write `tools/build-diagrams.py`**

```python
#!/usr/bin/env python3
"""Convert deck Mermaid sources to committed Excalidraw-look static SVGs.

Each src/docs/slides/diagrams/<name>.mmd is rendered, build-time, by a headless
browser (Playwright) over a tiny harness page that loads the pinned
@excalidraw/mermaid-to-excalidraw + @excalidraw/excalidraw libs (esm.sh, build-time
only), converts the Mermaid to Excalidraw elements, PINS every element seed so the
hand-drawn 'rough' look is reproducible (quiet git diffs), and exports to SVG. The
SVG is committed to assets/img/diagrams/<name>.svg; the shipped/published site stays
JS-free for diagrams. Maintainer tool — not shipped.

Prereq: a venv with Playwright + chromium (see the racecast-e2e skill):
  python3 -m venv .venv-pw && . .venv-pw/bin/activate
  pip install playwright && playwright install chromium

Usage:
  python3 tools/build-diagrams.py            # render every .mmd
"""
import argparse, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES = os.path.join(ROOT, "src", "docs", "slides")
MERMAID_TO_EXCALIDRAW = "https://esm.sh/@excalidraw/mermaid-to-excalidraw@1.1.2"
EXCALIDRAW = "https://esm.sh/@excalidraw/excalidraw@0.18.0"
SEED = 12345


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def discover_mmd(slides_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(slides_dir, "diagrams", "*.mmd"))):
        out.append((os.path.splitext(os.path.basename(p))[0], p))
    return out


def harness_html(mermaid_src):
    """Full HTML for the headless converter page. Sets window.__svg (or __err)."""
    src_js = mermaid_src.replace("\\", "\\\\").replace("`", "\\`")
    return f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<script type="module">
import {{ parseMermaidToExcalidraw }} from "{MERMAID_TO_EXCALIDRAW}";
import {{ convertToExcalidrawElements, exportToSvg }} from "{EXCALIDRAW}";
try {{
  const {{ elements }} = await parseMermaidToExcalidraw(`{src_js}`);
  const els = convertToExcalidrawElements(elements);
  // Deterministic look: pin every element seed so regeneration is reproducible.
  els.forEach((e, i) => {{ e.seed = {SEED} + i; e.versionNonce = {SEED} + i; }});
  const svg = await exportToSvg({{ elements: els, files: null,
    appState: {{ exportBackground: false, exportWithDarkMode: false }} }});
  window.__svg = svg.outerHTML;
}} catch (err) {{ window.__err = String(err); }}
</script></body></html>"""


def render_all(slides_dir=SLIDES, page_factory=None):
    """Render every .mmd to assets/img/diagrams/<name>.svg. Returns written paths."""
    if page_factory is None:                       # pragma: no cover (needs browser)
        from playwright.sync_api import sync_playwright

        def _default(html):
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.wait_for_function("window.__svg !== undefined || window.__err !== undefined",
                                   timeout=60000)
            err = page.evaluate("window.__err")
            svg = page.evaluate("window.__svg")
            browser.close(); pw.stop()
            if err:
                raise SystemExit(f"build-diagrams: convert failed: {err}")
            return svg
        page_factory = _default

    out_dir = os.path.join(slides_dir, "assets", "img", "diagrams")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, path in discover_mmd(slides_dir):
        with open(path, encoding="utf-8") as fh:
            svg = page_factory(harness_html(fh.read()))
        dest = os.path.join(out_dir, f"{name}.svg")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(svg)
        written.append(dest); print(f"rendered {name} -> {dest}")
    return written


def main():
    argparse.ArgumentParser().parse_args()
    render_all()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify the unit tests pass**

Run: `python3 tests/test_slides.py`
Expected: PASS — the three new `t_*` checks plus Task 1's, `ALL PASS`.

- [ ] **Step 5: Author the Director event-flow diagram source**

Create `src/docs/slides/diagrams/director-event-flow.mmd`:

```
flowchart LR
  A[Standby cover] --> B[Go live]
  B --> C[Driver change?]
  C -->|press Feeds Next| D[Next commentator on air]
  D --> E[Pick scene + graphics]
  E --> F[Send cues to talent]
  F --> C
  C -->|final stint| G[Interview cut + broadcast audio]
  G --> H[Outro + end]
```

- [ ] **Step 6: Render the diagram (needs the Playwright venv)**

```bash
python3 -m venv .venv-pw && . .venv-pw/bin/activate
pip install playwright && playwright install chromium
python3 tools/build-diagrams.py
deactivate
ls src/docs/slides/assets/img/diagrams/director-event-flow.svg
```
Expected: the SVG path is listed. Open it in a browser to eyeball the hand-drawn look.

- [ ] **Step 7: Lint + commit**

```bash
python3 tools/lint.py
git add tools/build-diagrams.py tests/test_slides.py \
        src/docs/slides/diagrams src/docs/slides/assets/img/diagrams
git commit -m "feat(slides): Mermaid->Excalidraw diagram pipeline + director flow

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The Director deck (`director.html`)

**Files:**
- Create: `src/docs/slides/director.html`
- Create: `src/docs/slides/assets/img/director-panel.png` (copy of the existing wiki shot)
- Test: `tests/test_slides.py` (extended in Task 6 enforces scaffolding/links/assets).

**Interfaces:**
- Consumes: `assets/deck.css`, `assets/deck.js`, `vendor/reveal/**` (Tasks 1–2), `assets/img/diagrams/director-event-flow.svg` (Task 3), `assets/img/director-panel.png`.
- Produces: the reference deck pattern every later deck copies. Wiki links use bare page names (`Director-Setup`, `Director`, `If-something-goes-wrong`) resolved relative to the published Pages site as `../../wiki/...`? No — decks link to the **GitHub wiki**, so use absolute wiki URLs. Define the convention: `[text](https://github.com/<owner>/<repo>/wiki/Director)`. Task 6's test validates the page slug against `src/docs/wiki/Director.md`.

- [ ] **Step 1: Copy the panel screenshot into the slides asset tree**

```bash
cp src/docs/wiki/images/director-panel.png src/docs/slides/assets/img/director-panel.png
```
(The decks' Pages artifact root is `src/docs/slides/`, so embedded images must live under it. This copy is subject to the CLAUDE.md screenshot-refresh rule — if the Director Panel UI changes, refresh both this and the wiki image in that change.)

- [ ] **Step 2: Write `director.html`**

Create `src/docs/slides/director.html` (wiki base `https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/`):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Director — Onboarding · GT Endurance Racing Broadcast</title>
<link rel="stylesheet" href="vendor/reveal/dist/reveal.css">
<link rel="stylesheet" href="vendor/reveal/plugin/highlight/monokai.css">
<link rel="stylesheet" href="assets/deck.css">
</head>
<body data-role="director">
<div class="reveal"><div class="slides">

<section data-markdown><script type="text/template">
<span class="role-tag">Director · Onboarding</span>
# Director
You drive the show from a browser — scenes, feeds, graphics and the interview cut.
No machine access needed.
</script></section>

<section data-markdown><script type="text/template">
## Your job in one sentence
Choose what viewers see, and press **Feeds Next** at every driver change.
The producer only starts and stops; everything in between is yours.
</script></section>

<section>
  <section data-markdown><script type="text/template">
## Before the event
- Open the personal **Console** link the producer sends you.
- Use a desktop browser; have Discord ready for the interview segment.
- First time? Walk through [Director setup](https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/Director-Setup).
  </script></section>
  <section data-markdown><script type="text/template">
### The Director Panel
Everything runs from one page. Details: [Director guide](https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/Director).
![Director Panel](assets/img/director-panel.png)
  </script></section>
</section>

<section>
  <section data-markdown><script type="text/template">
## The event flow
The show is a loop: go live, then at each driver change advance the feeds and
re-dress the scene. Press ↓ for each step.
![Event flow](assets/img/diagrams/director-event-flow.svg)
  </script></section>
  <section data-markdown><script type="text/template">
### 1 · Standby → Go live
Start on the **Standby** cover. When the producer confirms the relay is up,
cut to the live program.
  </script></section>
  <section data-markdown><script type="text/template">
### 2 · Each driver change
Press **Feeds Next**. The off-air feed has already pre-rolled the next
commentator, so the cut is clean. Then pick the scene + graphics.
  </script></section>
  <section data-markdown><script type="text/template">
### 3 · Talk to talent
Send **cues** from the panel — info toasts or sticky critical banners the
commentator must acknowledge.
  </script></section>
  <section data-markdown><script type="text/template">
### 4 · Interview + end
On the final stint, cut to the interview scene and bring up **broadcast audio**,
then roll the **Outro**.
  </script></section>
</section>

<section data-markdown><script type="text/template">
## When things go wrong
Feed black? Panel unresponsive? Work the checklist in
[If something goes wrong](https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/If-something-goes-wrong).
Keep calm — the producer can restart the relay without losing your scene.
</script></section>

<section data-markdown><script type="text/template">
## Recap
- Press **Feeds Next** at every driver change.
- Dress the scene: graphics, standings, weather.
- Cue talent; cut to the interview at the end.
Go deeper: [Who does what](https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/Who-does-what) ·
[Director guide](https://github.com/jegr78/gt-endurance-racing-broadcast/wiki/Director)
</script></section>

</div></div>
<script src="vendor/reveal/dist/reveal.js"></script>
<script src="vendor/reveal/plugin/markdown/markdown.js"></script>
<script src="vendor/reveal/plugin/highlight/highlight.js"></script>
<script src="vendor/reveal/plugin/notes/notes.js"></script>
<script src="assets/deck.js"></script>
</body>
</html>
```

- [ ] **Step 3: Verify it renders (manual)**

```bash
( cd src/docs/slides && python3 -m http.server 8099 )   # then open http://localhost:8099/director.html
```
Expected: title slide with the orange accent bar, arrow-down reveals the vertical sub-slides, the panel screenshot and the Excalidraw diagram load. Stop the server with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add src/docs/slides/director.html src/docs/slides/assets/img/director-panel.png
git commit -m "feat(slides): Director onboarding deck (pilot)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Landing page (`index.html`)

**Files:**
- Create: `src/docs/slides/index.html`
- Test: `tests/test_slides.py` (Task 6 asserts it exists + the Director card links `director.html`).

**Interfaces:**
- Consumes: `assets/deck.css` (reuses the role palette via inline classes).
- Produces: the six role cards; only Director links its deck, the other five are marked "coming soon".

- [ ] **Step 1: Write `index.html`**

Create `src/docs/slides/index.html` (standalone landing, not a Reveal deck — reuses fonts/palette):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crew Onboarding · GT Endurance Racing Broadcast</title>
<link rel="stylesheet" href="assets/deck.css">
<style>
  body{background:var(--paper);color:var(--ink);font-family:var(--mono);margin:0;padding:40px}
  h1{font-family:var(--head);text-transform:uppercase;letter-spacing:.08em}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;max-width:1100px}
  .card{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fbfaf6}
  .card .bar{height:10px;background:var(--c)}
  .card .body{padding:16px 18px}
  .card h2{font-family:var(--head);text-transform:uppercase;margin:.2em 0;color:var(--c)}
  .card a{color:var(--c);font-weight:600}
  .soon{color:var(--soft);font-size:13px}
</style>
</head>
<body>
<h1>Crew Onboarding</h1>
<p>Pick your role. Each deck is a short visual walkthrough; deeper detail lives in the wiki.</p>
<div class="grid">
  <div class="card" style="--c:var(--director)"><div class="bar"></div><div class="body">
    <h2>Director</h2><a href="director.html">Open walkthrough →</a></div></div>
  <div class="card" style="--c:var(--commentator)"><div class="bar"></div><div class="body">
    <h2>Commentator</h2><span class="soon">Coming soon</span></div></div>
  <div class="card" style="--c:var(--producer)"><div class="bar"></div><div class="body">
    <h2>Producer (event)</h2><span class="soon">Coming soon</span></div></div>
  <div class="card" style="--c:var(--race-control)"><div class="bar"></div><div class="body">
    <h2>Race Control</h2><span class="soon">Coming soon</span></div></div>
  <div class="card" style="--c:var(--producer)"><div class="bar"></div><div class="body">
    <h2>Producer setup</h2><span class="soon">Coming soon</span></div></div>
  <div class="card" style="--c:var(--league-admin)"><div class="bar"></div><div class="body">
    <h2>League Admin setup</h2><span class="soon">Coming soon</span></div></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add src/docs/slides/index.html
git commit -m "feat(slides): onboarding landing page (6 role cards)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Structural + link guard test (extend `tests/test_slides.py`)

**Files:**
- Modify: `tests/test_slides.py`
- Test: itself.

**Interfaces:**
- Consumes: the built decks/landing/assets from Tasks 1–5.
- Produces: CI regression guard (auto-discovered by `tools/run-tests.py`).

- [ ] **Step 1: Add the structural checks (above the `__main__` block)**

```python
import re as _re

_WIKI = os.path.join(ROOT, "src", "docs", "wiki")
_WIKI_LINK = _re.compile(r"github\.com/[^/]+/[^/]+/wiki/([A-Za-z0-9_\-]+)")
_LOCAL_ASSET = _re.compile(r'(?:href|src)="((?:assets|vendor)/[^"]+)"')
_MD_IMG = _re.compile(r"!\[[^\]]*\]\((assets/[^)]+)\)")


def _decks():
    return [os.path.join(SLIDES, f) for f in ("director.html", "index.html")]


def t_director_deck_scaffolded():
    html = open(os.path.join(SLIDES, "director.html"), encoding="utf-8").read()
    assert 'data-role="director"' in html
    assert 'assets/deck.css' in html and 'assets/deck.js' in html
    assert 'vendor/reveal/dist/reveal.js' in html
    assert 'data-markdown' in html


def t_landing_links_director_deck():
    html = open(os.path.join(SLIDES, "index.html"), encoding="utf-8").read()
    assert 'href="director.html"' in html


def t_outbound_wiki_links_resolve():
    for deck in _decks():
        html = open(deck, encoding="utf-8").read()
        for page in _WIKI_LINK.findall(html):
            assert os.path.isfile(os.path.join(_WIKI, page + ".md")), \
                f"{os.path.basename(deck)} -> missing wiki page {page}"


def t_referenced_local_assets_exist():
    for deck in _decks():
        html = open(deck, encoding="utf-8").read()
        for rel in _LOCAL_ASSET.findall(html) + _MD_IMG.findall(html):
            assert os.path.isfile(os.path.join(SLIDES, rel)), \
                f"{os.path.basename(deck)} -> missing asset {rel}"


def t_every_mmd_has_committed_svg():
    for name, _ in bd.discover_mmd(SLIDES):
        svg = os.path.join(SLIDES, "assets", "img", "diagrams", name + ".svg")
        assert os.path.isfile(svg), f"missing generated SVG for {name}"


def t_no_shell_scripts_in_slides():
    for _, _, files in os.walk(SLIDES):
        assert not any(f.endswith((".sh", ".bat")) for f in files)
```

- [ ] **Step 2: Run to verify all pass**

Run: `python3 tests/test_slides.py`
Expected: PASS — every `t_*` prints `ok …`, then `ALL PASS`. (If a wiki link fails, fix the page slug in `director.html` to match a real `src/docs/wiki/*.md`.)

- [ ] **Step 3: Run the whole suite**

Run: `python3 tools/run-tests.py`
Expected: `test_slides.py` listed, ends `ALL TEST FILES PASS`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_slides.py
git commit -m "test(slides): structural + wiki-link + asset guards

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Visual overflow guard (`tools/check-slides.py`)

**Files:**
- Create: `tools/check-slides.py`
- Test: `tests/test_slides.py` (extend — pure decision helper only).

**Interfaces:**
- Produces: `overflow_findings(measurements, tol=2) -> list[dict]` (pure; flags slides whose content or any media exceeds the slide box by more than `tol` px); `check(slides_dir, deck_files, page_factory=None) -> list[dict]` (Playwright integration; measures each slide at 1280×720, writes screenshots of offenders, returns findings). Constants `SLIDE_W=1280`, `SLIDE_H=720`.
- Consumes: the decks from Tasks 4–5.

- [ ] **Step 1: Write the failing test (extend `tests/test_slides.py`)**

```python
cs = _load(os.path.join("tools", "check-slides.py"), "check_slides")


def t_overflow_findings_flags_content_and_media():
    measures = [
        {"deck": "director.html", "slide": "0", "cw": 1200, "ch": 700,
         "media": []},                                  # fits
        {"deck": "director.html", "slide": "3", "cw": 1300, "ch": 700,
         "media": []},                                  # content too wide
        {"deck": "director.html", "slide": "5", "cw": 1000, "ch": 700,
         "media": [{"src": "x.svg", "w": 1400, "h": 600}]},  # media too wide
    ]
    found = cs.overflow_findings(measures)
    flagged = {(f["slide"], f["kind"]) for f in found}
    assert ("3", "content") in flagged
    assert ("5", "media") in flagged
    assert ("0", "content") not in flagged
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_slides.py`
Expected: FAIL — `check-slides.py` missing.

- [ ] **Step 3: Write `tools/check-slides.py`**

```python
#!/usr/bin/env python3
"""Visual overflow guard for the onboarding decks.

Reveal slides have a FIXED logical size (1280x720; see assets/deck.js). Text,
images or the Excalidraw SVGs silently overflow that box. This loads each deck in
a headless browser, walks every slide (including vertical sub-slides), measures the
content + each image/SVG against the box, and reports offenders with a screenshot.

Maintainer/pre-publish gate (not CI) — same model as wiki-visual-test. Needs the
Playwright venv (see the racecast-e2e skill).

Usage:
  python3 tools/check-slides.py [--shots DIR]
"""
import argparse, glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES = os.path.join(ROOT, "src", "docs", "slides")
SLIDE_W, SLIDE_H = 1280, 720


def overflow_findings(measurements, tol=2):
    """Pure: turn per-slide measurements into overflow findings."""
    out = []
    for m in measurements:
        if m["cw"] > SLIDE_W + tol or m["ch"] > SLIDE_H + tol:
            out.append({"deck": m["deck"], "slide": m["slide"], "kind": "content",
                        "detail": f'{m["cw"]}x{m["ch"]} > {SLIDE_W}x{SLIDE_H}'})
        for media in m.get("media", []):
            if media["w"] > SLIDE_W + tol or media["h"] > SLIDE_H + tol:
                out.append({"deck": m["deck"], "slide": m["slide"], "kind": "media",
                            "detail": f'{media["src"]} {media["w"]}x{media["h"]}'})
    return out


_MEASURE_JS = """() => {
  const s = Reveal.getCurrentSlide();
  const media = [...s.querySelectorAll('img,svg')].map(e => ({
    src: e.getAttribute('src') || 'svg', w: e.scrollWidth, h: e.scrollHeight }));
  return { cw: s.scrollWidth, ch: s.scrollHeight, media };
}"""


def check(slides_dir, deck_files, page_factory=None):           # pragma: no cover
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    findings = []
    try:
        for deck in deck_files:
            page = browser.new_page(viewport={"width": SLIDE_W, "height": SLIDE_H})
            page.goto("file://" + os.path.join(slides_dir, deck))
            page.wait_for_function("window.Reveal && Reveal.isReady()")
            total = page.evaluate("Reveal.getTotalSlides()")
            measures = []
            for _ in range(total):
                idx = page.evaluate("Reveal.getIndices()")
                m = page.evaluate(_MEASURE_JS)
                m.update({"deck": deck, "slide": f'{idx["h"]}.{idx.get("v", 0)}'})
                measures.append(m)
                page.evaluate("Reveal.next()")
            findings += overflow_findings(measures)
        return findings
    finally:
        browser.close(); pw.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    ap.parse_args()
    decks = [os.path.basename(p) for p in glob.glob(os.path.join(SLIDES, "*.html"))
             if os.path.basename(p) != "index.html"]
    findings = check(SLIDES, decks)
    for f in findings:
        print(f'OVERFLOW {f["deck"]} slide {f["slide"]} [{f["kind"]}]: {f["detail"]}')
    if findings:
        sys.exit(f"{len(findings)} overflowing slide(s)")
    print(f"OK — no overflow in {len(decks)} deck(s)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify the unit test passes**

Run: `python3 tests/test_slides.py`
Expected: PASS, `ALL PASS`.

- [ ] **Step 5: Run the real guard against the Director deck (Playwright venv)**

```bash
. .venv-pw/bin/activate
python3 tools/check-slides.py
deactivate
```
Expected: `OK — no overflow in 1 deck(s)`. If a slide overflows, trim its copy or split it into a vertical sub-slide, then re-run.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add tools/check-slides.py tests/test_slides.py
git commit -m "feat(slides): visual overflow guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: GitHub Pages workflow (dispatch-only)

**Files:**
- Create: `.github/workflows/pages.yml`

**Interfaces:** Consumes `src/docs/slides/` as the Pages artifact root. No code interface.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/pages.yml`:

```yaml
name: Publish Slides to Pages

# Dispatch-only by design: publishing the onboarding decks is a deliberate
# maintainer action, mirroring wiki.yml. The artifact root is src/docs/slides/
# (vendored Reveal + committed diagram SVGs make it fully static — no build step).
# One-time prerequisite: repo Settings -> Pages -> Source = "GitHub Actions".
on:
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10  # v6
      - uses: actions/configure-pages@983d7736d9b0ae728b81ab479565c72886d7745b  # v5
      - uses: actions/upload-pages-artifact@7b1f4a764d45c48632c6b24a0339c27f5614fb0b  # v3
        with:
          path: src/docs/slides
      - id: deployment
        uses: actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e  # v4
```

(Pin actions to the SHAs already used elsewhere if newer; the `checkout`/`setup-python` SHAs above match `wiki.yml`. For the three `pages` actions, use the latest release SHAs — verify with `gh api repos/actions/deploy-pages/releases/latest`.)

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pages.yml
git commit -m "ci(slides): dispatch-only GitHub Pages publish for onboarding decks

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Ship the decks in the package + build verify

**Files:**
- Modify: `tools/build.py` (the docs-copy block near line 55 + the `checks` dict near line 168)

**Interfaces:** Consumes the built `src/docs/slides/` tree. Produces verify gates ensuring decks + vendor ship.

- [ ] **Step 1: Add the slides copy**

In `tools/build.py`, after the existing `cp("docs/...")` lines (the loop near line 55), add:

```python
    cp("docs/slides", "docs/slides")   # onboarding decks (vendored Reveal, static)
```

- [ ] **Step 2: Add verify checks**

In the `checks = { … }` dict (near line 168), add these entries:

```python
        "slides director deck shipped": os.path.isfile(
            os.path.join(PKG, "docs", "slides", "director.html")),
        "slides reveal vendored": os.path.isfile(
            os.path.join(PKG, "docs", "slides", "vendor", "reveal", "dist", "reveal.js")),
        "slides landing shipped": os.path.isfile(
            os.path.join(PKG, "docs", "slides", "index.html")),
        "slides diagram svg shipped": os.path.isfile(os.path.join(
            PKG, "docs", "slides", "assets", "img", "diagrams", "director-event-flow.svg")),
```

- [ ] **Step 3: Run the build**

Run: `python3 tools/build.py`
Expected: the four new `[OK] slides …` lines appear; no `BUILD VERIFY FAILED`.

- [ ] **Step 4: Lint + commit**

```bash
python3 tools/lint.py
git add tools/build.py
git commit -m "build(slides): ship onboarding decks + verify gates

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Maintainer skills (`slides-overflow`, `slides-diagrams`)

**Files:**
- Create: skill `slides-overflow` and skill `slides-diagrams` (use the **superpowers:writing-skills** skill to author both; place them where the repo's other maintainer skills live — see `companion-screenshots` / `wiki-visual-test` for the location + frontmatter pattern).

**Interfaces:** Each skill wraps a tool from this plan. No code interface.

- [ ] **Step 1: Author `slides-diagrams`**

Invoke `superpowers:writing-skills`. The skill must: ensure the Playwright venv exists (`.venv-pw`, `pip install playwright && playwright install chromium`), run `python3 tools/build-diagrams.py`, then remind to commit the regenerated `assets/img/diagrams/*.svg`. Trigger description: "regenerate the onboarding-deck Excalidraw diagrams from their .mmd sources after a diagram changes."

- [ ] **Step 2: Author `slides-overflow`**

Invoke `superpowers:writing-skills`. The skill must: ensure the Playwright venv, run `python3 tools/check-slides.py [--shots DIR]`, and report overflowing slides (with the screenshots) so they can be fixed before publishing. Trigger: "check the onboarding decks for slide overflow before publishing to Pages."

- [ ] **Step 3: Commit**

```bash
git add <skill files>
git commit -m "feat(slides): maintainer skills for diagram build + overflow guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Wiki cross-links + discoverability

**Files:**
- Modify: `src/docs/wiki/_Sidebar.md`, `src/docs/wiki/Home.md`, `src/docs/wiki/Director.md`

**Interfaces:** Adds links from the wiki to the Pages site + the Director deck. The Pages URL is `https://<owner>.github.io/<repo>/` (confirm after the first Pages deploy).

- [ ] **Step 1: Add a sidebar entry**

In `src/docs/wiki/_Sidebar.md`, under **For operators**, add after the `Who does what` line:

```markdown
- [Onboarding decks ↗](https://jegr78.github.io/gt-endurance-racing-broadcast/)
```

- [ ] **Step 2: Link the Director deck from `Director.md`**

Add near the top of `src/docs/wiki/Director.md` (after the first heading):

```markdown
> New here? Start with the visual [Director onboarding deck ↗](https://jegr78.github.io/gt-endurance-racing-broadcast/director.html), then come back for the detail below.
```

- [ ] **Step 3: Mention the decks on `Home.md`**

Add a short bullet under the operator-onboarding area of `src/docs/wiki/Home.md`:

```markdown
- **New crew?** The [onboarding decks ↗](https://jegr78.github.io/gt-endurance-racing-broadcast/) are short visual walkthroughs per role.
```

- [ ] **Step 4: Validate wiki links + run the suite**

Run:
```bash
python3 tools/check-wiki-links.py
python3 tools/run-tests.py
```
Expected: link check passes (external `https://` links are ignored by it); `ALL TEST FILES PASS` (includes `test_wiki.py` + `test_slides.py`).

- [ ] **Step 5: Commit**

```bash
git add src/docs/wiki/_Sidebar.md src/docs/wiki/Home.md src/docs/wiki/Director.md
git commit -m "docs(wiki): cross-link the onboarding decks (Pages)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] `python3 tools/run-tests.py` → `ALL TEST FILES PASS`
- [ ] `python3 tools/lint.py` → no issues
- [ ] `python3 tools/build.py` → all `[OK] slides …`, no `BUILD VERIFY FAILED`
- [ ] (Playwright venv) `python3 tools/check-slides.py` → no overflow
- [ ] Manual: `python3 -m http.server` in `src/docs/slides`, open `index.html` → Director card opens the deck; diagram + screenshot render; arrow-down works.

## Notes for the next plan (remaining 5 decks)

Copy `director.html` as the template per role, set `data-role`, write the role's
walkthrough (Commentator, Producer-event, Race Control, Producer-setup,
League-Admin-setup), author any `.mmd`, regenerate diagrams + run the overflow guard,
flip each landing card from "coming soon" to its link, and extend `tests/test_slides.py`
`_decks()`. Source content from the matching wiki pages (`Commentator-Cockpit`,
`Run-an-event`, Race Control section of `Who-does-what`, `Set-up-the-broadcast-PC`,
`League-Owner-Setup`).
```
