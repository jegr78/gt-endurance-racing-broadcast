#!/usr/bin/env python3
"""Compute the identity (tag / version / title) of a preview build from the
triggering GitHub event. CI-only helper for .github/workflows/preview.yml; not
shipped (tools/ is never copied into the distributable). The pure
compute_preview_meta() is unit-tested in tests/test_preview.py; main() emits
`key=value` lines for $GITHUB_OUTPUT.

Usage (from the workflow):
  python tools/preview_meta.py --event pull_request --pr 42 \
      --sha "$SHA" >> "$GITHUB_OUTPUT"
  python tools/preview_meta.py --event workflow_dispatch --ref main \
      --sha "$SHA" >> "$GITHUB_OUTPUT"
"""
import argparse
import sys

PREVIEW_PREAMBLE = ("Automated preview build — not a release. Unsigned: expect a "
                    "one-time SmartScreen/Gatekeeper warning on first run.")


def format_preview_notes(commits, sha, limit=50):
    """Markdown body for a preview pre-release: a bulleted **Changes** list of the
    commit subjects in `commits` (already most-recent-first) above the standing
    preview preamble + build provenance. Blank/whitespace lines are dropped; more
    than `limit` commits are truncated with a '…and N more' line. An empty list
    (no commits in range, or git history unavailable) degrades gracefully to just
    the provenance + preamble, so the release is never noteless. Pure for tests."""
    short = (sha or "")[:7]
    clean = [c.strip() for c in commits if c and c.strip()]
    out = []
    if clean:
        shown = clean[:limit]
        out.append("### Changes")
        out.extend(f"- {c}" for c in shown)
        extra = len(clean) - len(shown)
        if extra > 0:
            out.append(f"- …and {extra} more commit{'' if extra == 1 else 's'}")
        out.append("")
    out.append(f"Built from commit `{short}`." if short else "Built from an unknown commit.")
    out.append("")
    out.append(PREVIEW_PREAMBLE)
    return "\n".join(out)


def _sanitize_ref(ref):
    """A git ref made safe for a tag suffix: drop a refs/heads/ or refs/tags/
    prefix and replace every '/' with '-' (feat/x -> feat-x). Empty -> 'main'."""
    ref = (ref or "").strip()
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    ref = ref.replace("/", "-")
    return ref or "main"


def compute_preview_meta(event_name, pr_number=None, ref=None, sha=None):
    """Return {'tag', 'version', 'title'} for a preview build.

    PR builds are keyed by PR number (one rolling pre-release per open PR);
    dispatch builds are keyed by the sanitized ref (one per branch, e.g.
    preview-main). The version embeds the 7-char short SHA so `racecast --version`
    pinpoints the exact commit a tester is running.
    """
    short = (sha or "")[:7]
    if event_name == "pull_request":
        if not pr_number:
            raise ValueError("pull_request event requires a PR number")
        n = int(pr_number)
        return {
            "tag": f"preview-pr-{n}",
            "version": f"preview-pr{n}-{short}",
            "title": f"Preview: PR #{n} ({short})",
        }
    if event_name == "workflow_dispatch":
        r = _sanitize_ref(ref)
        return {
            "tag": f"preview-{r}",
            "version": f"preview-{r}-{short}",
            "title": f"Preview: {r} ({short})",
        }
    raise ValueError(f"unsupported event: {event_name!r}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `notes` mode: read commit subjects from stdin (one per line, most-recent
    # first — from `git log --format=%s <range>`) and print the pre-release body.
    if argv and argv[0] == "notes":
        ap = argparse.ArgumentParser(prog="preview_meta.py notes")
        ap.add_argument("--sha", required=True)
        ap.add_argument("--limit", type=int, default=50)
        a = ap.parse_args(argv[1:])
        sys.stdout.write(format_preview_notes(sys.stdin.read().splitlines(),
                                              a.sha, a.limit) + "\n")
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--pr")
    ap.add_argument("--ref")
    ap.add_argument("--sha", required=True)
    a = ap.parse_args(argv)
    meta = compute_preview_meta(a.event, a.pr, a.ref, a.sha)
    for key, value in meta.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
