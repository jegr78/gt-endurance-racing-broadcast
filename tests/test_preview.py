#!/usr/bin/env python3
"""Stdlib unit checks for the preview-build identity helper.
Run: python3 tests/test_preview.py"""
import contextlib, importlib.util, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "preview_meta", os.path.join(ROOT, "tools", "preview_meta.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


# --- compute_preview_meta: PR builds keyed by PR number ----------------------
def t_pr_meta():
    out = m.compute_preview_meta("pull_request", pr_number=42,
                                 sha="0123abcdef9999")
    assert out == {
        "tag": "preview-pr-42",
        "version": "preview-pr42-0123abc",
        "title": "Preview: PR #42 (0123abc)",
    }, out


def t_pr_meta_accepts_string_number():
    out = m.compute_preview_meta("pull_request", pr_number="7",
                                 sha="abcdef1234567")
    assert out["tag"] == "preview-pr-7"
    assert out["version"] == "preview-pr7-abcdef1"


# --- compute_preview_meta: dispatch builds keyed by sanitized ref ------------
def t_dispatch_main():
    out = m.compute_preview_meta("workflow_dispatch", ref="main",
                                 sha="deadbeef0001")
    assert out == {
        "tag": "preview-main",
        "version": "preview-main-deadbee",
        "title": "Preview: main (deadbee)",
    }, out


def t_dispatch_sanitizes_slash():
    out = m.compute_preview_meta("workflow_dispatch", ref="feat/preview-builds",
                                 sha="cafebabe1234")
    assert out["tag"] == "preview-feat-preview-builds"
    assert out["version"] == "preview-feat-preview-builds-cafebab"


def t_dispatch_strips_refs_heads():
    out = m.compute_preview_meta("workflow_dispatch", ref="refs/heads/main",
                                 sha="cafebabe1234")
    assert out["tag"] == "preview-main"


def t_dispatch_empty_ref_defaults_main():
    out = m.compute_preview_meta("workflow_dispatch", ref="",
                                 sha="0000000aaaa")
    assert out["tag"] == "preview-main"


# --- guards ------------------------------------------------------------------
def t_pr_requires_number():
    try:
        m.compute_preview_meta("pull_request", pr_number=None, sha="abc1234")
    except ValueError:
        return
    raise AssertionError("expected ValueError for PR event with no number")


def t_unknown_event_raises():
    try:
        m.compute_preview_meta("push", sha="abc1234")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unsupported event")


# --- format_preview_notes: changelog body for the pre-release ----------------
def t_notes_lists_commits():
    body = m.format_preview_notes(
        ["fix: thing (abc1234)", "feat: other (def5678)"], sha="0123abcdef")
    assert "### Changes" in body
    assert "- fix: thing (abc1234)" in body
    assert "- feat: other (def5678)" in body
    assert "Built from commit `0123abc`." in body
    assert "Automated preview build" in body


def t_notes_empty_degrades_to_preamble():
    body = m.format_preview_notes([], sha="0123abcdef")
    assert "### Changes" not in body
    assert "Built from commit `0123abc`." in body
    assert "Automated preview build" in body


def t_notes_skips_blank_lines():
    body = m.format_preview_notes(["real subject", "", "   "], sha="abc1234")
    assert body.count("\n- ") == 1
    assert "- real subject" in body


def t_notes_truncates_to_limit():
    commits = [f"commit {i}" for i in range(60)]
    body = m.format_preview_notes(commits, sha="abc1234", limit=50)
    assert body.count("\n- commit") == 50
    assert "…and 10 more commits" in body


def t_main_notes_mode_reads_stdin():
    import sys
    buf, stdin = io.StringIO(), io.StringIO("fix: one\nfeat: two\n")
    old = sys.stdin
    sys.stdin = stdin
    try:
        with contextlib.redirect_stdout(buf):
            m.main(["notes", "--sha", "1234567abc"])
    finally:
        sys.stdin = old
    out = buf.getvalue()
    assert "- fix: one" in out and "- feat: two" in out
    assert "Built from commit `1234567`." in out


# --- main(): emits GITHUB_OUTPUT key=value lines -----------------------------
def t_main_pr_emits_output_lines():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main(["--event", "pull_request", "--pr", "5", "--sha",
                "1234567abcdef"])
    lines = buf.getvalue().strip().splitlines()
    assert "tag=preview-pr-5" in lines, lines
    assert "version=preview-pr5-1234567" in lines, lines
    assert "title=Preview: PR #5 (1234567)" in lines, lines


def t_main_dispatch_ignores_empty_pr():
    # The workflow always passes --pr (empty on dispatch) and --ref (empty on
    # PR). main() must route on --event, not on which optional arg is empty.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main(["--event", "workflow_dispatch", "--pr", "", "--ref", "main",
                "--sha", "deadbeef0001"])
    lines = buf.getvalue().strip().splitlines()
    assert "tag=preview-main" in lines, lines


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
