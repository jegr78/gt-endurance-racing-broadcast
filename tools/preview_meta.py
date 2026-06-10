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
    preview-main). The version embeds the 7-char short SHA so `iro --version`
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
