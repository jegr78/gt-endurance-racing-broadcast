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
