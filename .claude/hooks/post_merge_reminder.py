#!/usr/bin/env python3
"""PostToolUse (Bash) hook: after a real `gh pr merge`, inject the post-merge
repository security follow-up reminder.

Self-gates on the Bash command string. The settings.json `if` field
(`"if": "Bash(gh pr merge*)"`) is not honored in every Claude Code build — when
it is ignored the reminder fires on *every* Bash call (curl, ls, git …), which
is noise and, worse, injects a "a merge just completed" instruction when nothing
was merged. Deciding here on `.tool_input.command` is version-independent.

Reads the PostToolUse JSON payload on stdin; on a match, prints the
additionalContext stdout JSON that Claude Code injects into the transcript.
Emits nothing (exit 0) for any other command.
"""
import json
import sys

REMINDER = (
    "A merge to main just completed. Before treating the task as done, do the "
    "repository security follow-up: (1) Wait for the CodeQL run this merge "
    "triggered on main to finish (poll: gh run list --workflow=CodeQL "
    "--branch=main --limit=3, then gh run watch the newest id). (2) List OPEN "
    "Code Scanning alerts: gh api repos/:owner/:repo/code-scanning/alerts "
    "--paginate, and keep the ones whose state is open. (3) For each open "
    "alert, judge whether it is a real issue or a false positive. Fix the REAL "
    "ones under src/ on a NEW branch and open a PR (run python3 "
    "tools/run-tests.py and python3 tools/lint.py first); never commit to main "
    "directly. Record any false positives in the PR body instead of "
    "auto-dismissing them. If there are zero open alerts, report that briefly "
    "and stop."
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        # A missing/malformed payload — nothing to react to.
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    # Only fire for an actual PR merge, not every Bash call.
    if "gh pr merge" not in cmd:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": REMINDER,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
