#!/usr/bin/env python3
"""Stdlib checks for build.py's secret-pattern verify. Run: python3 tests/test_build.py

Importing build.py only runs its module-level defs (the __main__ guard does not
fire), so this never triggers an actual build."""
import importlib.util, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "build", os.path.join(ROOT, "tools", "build.py"))
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def _build_src():
    with open(os.path.join(ROOT, "tools", "build.py"), encoding="utf-8") as fh:
        return fh.read()


def _served_html_relpaths():
    """All src/ HTML pages the relay/Control Center serve (posix relpaths under
    src/), excluding the docs/ subtree (cheat_sheets.html ships via the docs loop)."""
    src = os.path.join(ROOT, "src")
    out = []
    for dirpath, _dirs, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        if rel.split(os.sep)[0] == "docs":
            continue
        for f in files:
            if f.endswith(".html"):
                p = os.path.normpath(os.path.join(rel, f)) if rel != "." else f
                out.append(p.replace(os.sep, "/"))
    return sorted(out)


def t_has_appscript_secret_flags_exec_endpoint():
    # the SHEET_PUSH_URL secret class most likely to leak into the OBS json
    assert b.has_appscript_secret("https://script.google.com/macros/s/ABC123def/exec")
    assert b.has_appscript_secret(
        '{"url": "https://script.googleusercontent.com/macros/echo?key=secret"}')
    assert b.has_appscript_secret("anything .../exec trailing")


def t_has_appscript_secret_flags_key_query():
    assert b.has_appscript_secret("https://api.example.com/data?key=AIzaSyXXXX")
    assert b.has_appscript_secret("https://x/y?a=1&key=zzz")


def t_has_appscript_secret_clean_text_passes():
    assert not b.has_appscript_secret("http://127.0.0.1:8088/hud")
    assert not b.has_appscript_secret("__RACECAST_GRAPHICS__/Overlay.png")
    assert not b.has_appscript_secret("http://127.0.0.1:8088/timer/data")
    assert not b.has_appscript_secret("")


def _wholedir_copies(build_src):
    """Top-level src items copied verbatim, e.g. cp("ui", "ui") -> {"ui", ...}."""
    return set(re.findall(r'cp\("([^"/]+)",\s*"[^"]*"\)', build_src))


def t_every_served_html_page_is_shipped():
    # Each relay/Control-Center-served .html must be copied into the dist package,
    # or the distributed package 404s that page. Sibling of test_build_binary's
    # t_every_served_html_dir_is_bundled (which guards the standalone binary).
    # Regression for the #216/#236 console.html + buttons.html omission found in
    # the #244 release test (and the original cockpit.html one).
    build_src = _build_src()
    wholedirs = _wholedir_copies(build_src)
    missing = []
    for rel in _served_html_relpaths():
        top = rel.split("/")[0]
        shipped = (f'cp("{rel}"' in build_src) or (top in wholedirs)
        if not shipped:
            missing.append(rel)
    assert not missing, (
        "served HTML pages not copied into the dist package by tools/build.py "
        f"(they would 404 in the distributed package): {missing}")


def t_console_pages_are_shipped():
    # Explicit pins for the omission found in the #244 release test.
    build_src = _build_src()
    assert 'cp("console/console.html"' in build_src, "console.html not shipped"
    assert 'cp("console/buttons.html"' in build_src, "buttons.html not shipped"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
