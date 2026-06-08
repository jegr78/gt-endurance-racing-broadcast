#!/usr/bin/env python3
"""Stdlib checks for the Help-page Markdown renderer (src/ui/mdrender.py).
Run: python3 tests/test_mdrender.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import mdrender as md


def t_headings():
    assert md.render("# Title") == "<h1>Title</h1>"
    assert md.render("### Sub") == "<h3>Sub</h3>"


def t_inline_formatting():
    h = md.render("Use **bold**, *italic* and `code` here.")
    assert "<strong>bold</strong>" in h
    assert "<em>italic</em>" in h
    assert "<code>code</code>" in h


def t_inline_escapes_html_but_keeps_snake_case():
    h = md.render("a < b and file_name_here stays")
    assert "&lt; b" in h                                   # escaped
    assert "file_name_here" in h and "<em>" not in h      # underscores not italic


def t_links():
    h = md.render("See [the wiki](https://example/wiki).")
    assert '<a href="https://example/wiki" target="_blank" rel="noopener">the wiki</a>' in h


def t_fenced_code_is_escaped_verbatim():
    h = md.render("```\niro relay start <x>\n```")
    assert "<pre><code>" in h and "iro relay start &lt;x&gt;" in h
    assert "<em>" not in h                                 # no inline formatting in code


def t_unordered_list():
    h = md.render("- one\n- two")
    assert h == "<ul><li>one</li><li>two</li></ul>"


def t_ordered_list():
    h = md.render("1. first\n2. second")
    assert h.startswith("<ol>") and "<li>first</li>" in h and "<li>second</li>" in h


def t_nested_list():
    h = md.render("- parent\n  - child\n- sibling")
    assert "<ul><li>parent<ul><li>child</li></ul></li><li>sibling</li></ul>" == h


def t_table_with_alignment():
    src = ("| Component | Min | Rec |\n"
           "|:--|:-:|--:|\n"
           "| RAM | 8 GB | 16 GB |")
    h = md.render(src)
    assert "<table>" in h and "<thead>" in h
    assert "<th>Component</th>" in h
    assert 'style="text-align:center"' in h and 'style="text-align:right"' in h
    assert "<td>RAM</td>" in h and "<td" in h and "16 GB" in h


def t_blockquote():
    h = md.render("> note here")
    assert "<blockquote>" in h and "note here" in h


def t_paragraph_joins_wrapped_lines():
    h = md.render("one line\ncontinues here\n\nnew para")
    assert "<p>one line continues here</p>" in h and "<p>new para</p>" in h


def t_page_is_self_contained():
    doc = md.page("My Doc", "<p>hi</p>")
    assert doc.startswith("<!doctype html>")
    assert "<title>My Doc</title>" in doc and "<style>" in doc
    assert "<main><p>hi</p></main>" in doc


def t_renders_real_docs_without_crashing():
    # the actual bundled docs must render and produce tables/headings
    for rel in ("docs/README_SETUP.md", "docs/IRO_Broadcast_Setup_Guide.md"):
        with open(os.path.join(ROOT, "src", rel), encoding="utf-8") as fh:
            h = md.render(fh.read())
        assert "<h1>" in h and "<table>" in h and "<li>" in h
        assert "\x00" not in h                             # all code placeholders restored


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
