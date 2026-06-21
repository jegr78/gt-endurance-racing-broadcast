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


import re as _re

_WIKI = os.path.join(ROOT, "src", "docs", "wiki")
_WIKI_LINK = _re.compile(r"github\.com/[^/]+/[^/]+/wiki/([A-Za-z0-9_\-]+)")
_LOCAL_ASSET = _re.compile(r'(?:href|src)="((?:assets|vendor)/[^"]+)"')
_MD_IMG = _re.compile(r"!\[[^\]]*\]\((assets/[^)]+)\)")


def _decks():
    return [os.path.join(SLIDES, f) for f in ("director.html", "index.html")]


def t_director_deck_scaffolded():
    with open(os.path.join(SLIDES, "director.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'data-role="director"' in html
    assert 'assets/deck.css' in html and 'assets/deck.js' in html
    assert 'vendor/reveal/dist/reveal.js' in html
    assert 'data-markdown' in html


def t_landing_links_director_deck():
    with open(os.path.join(SLIDES, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'href="director.html"' in html


def t_outbound_wiki_links_resolve():
    for deck in _decks():
        with open(deck, encoding="utf-8") as fh:
            html = fh.read()
        for page in _WIKI_LINK.findall(html):
            assert os.path.isfile(os.path.join(_WIKI, page + ".md")), \
                f"{os.path.basename(deck)} -> missing wiki page {page}"


def t_referenced_local_assets_exist():
    for deck in _decks():
        with open(deck, encoding="utf-8") as fh:
            html = fh.read()
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
