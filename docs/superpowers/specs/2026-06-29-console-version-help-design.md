# Console pages: version badge + Help button

**Date:** 2026-06-29
**Status:** Approved

## Goal

Show the running racecast version and a role-specific **Help** link in the header of
the three crew console pages: the **Director Panel**, the **Commentator Cockpit**, and
the **Race Control** desk.

- The **version badge** displays the running build's version (`v1.1.0`, or `dev` for a
  repo/dev build) and links to the GitHub Releases page in a new tab.
- The **Help button** links to that page's role-specific onboarding deck (GitHub Pages),
  in a new tab.

The `/console` launcher (`console.html`) is **out of scope** — only the three role pages.

## Scope: pages and targets

| Role | File | Served at | Help target (onboarding deck) |
|---|---|---|---|
| Director Panel | `src/director/director-panel.html` | `/panel`, `/console/panel` | `https://jegr78.github.io/gt-endurance-racing-broadcast/director.html` |
| Commentator Cockpit | `src/cockpit/cockpit.html` | `/cockpit`, `/console/cockpit` | `https://jegr78.github.io/gt-endurance-racing-broadcast/commentator.html` |
| Race Control | `src/racecontrol/race-control.html` | `/console/race-control` | `https://jegr78.github.io/gt-endurance-racing-broadcast/race-control.html` |

Releases URL (shared, static): `https://github.com/jegr78/gt-endurance-racing-broadcast/releases`.

## Architecture

### 1. Version source — shared pure helper

The relay (`src/relay/racecast-feeds.py`) does not currently know its own version. Add a
tiny pure helper so the relay and the CLI resolve it identically:

`src/scripts/app_version.py`

```python
import os

def read_version(src_base):
    """Running build version. The VERSION file is stamped into the source-tree root
    (`src_base`) by tools/build-binary.py; a repo checkout has none -> 'dev'.
    `src_base` is HERE in a repo run and `<_MEIPASS>/src` in a frozen binary."""
    try:
        with open(os.path.join(src_base, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"
```

- `racecast.py`'s existing `version()` is refactored to delegate:
  `return app_version.read_version(_src_base(IS_FROZEN, getattr(sys, "_MEIPASS", ""), HERE))`.
  Behavior is identical (same file, same `dev` fallback) — single source of truth.
- The relay computes the same value once at startup:
  `_SRC_BASE = os.path.join(sys._MEIPASS, "src") if frozen else os.path.join(_REL_HERE, "..")`,
  then `app_version.read_version(_SRC_BASE)`. (`app_version` is importable — the relay
  already adds `src/scripts` to `sys.path`.) VERSION resolves to `<src>/VERSION` in both
  frozen and repo modes, matching `racecast.py`.

### 2. Exposure to pages — HTML placeholder injection (no new endpoint)

`_send_page()` in the relay already substitutes `__RC_API_BASE__` and `__RC_OAUTH__` in
every served page. Add one more substitution: `__RC_VERSION__` → the resolved version
string.

- The version value is threaded into `make_handler(...)` as a new parameter
  (e.g. `app_version=...`) and closed over by `_send_page`, exactly like the existing
  `discord_client_id` / `discord_client_secret` closure values.
- **All** serving routes flow through `_send_page` — root `/panel` and `/cockpit`, and the
  Funnel routes `/console/panel`, `/console/cockpit`, `/console/race-control` — so a single
  substitution covers every route uniformly.

Rationale (no dedicated `/version` endpoint): version is static for the life of the
process, so injecting it once into the served HTML is simpler than a fetched endpoint,
needs no root+`/console` route pair, adds no public/auth surface, and is Funnel-correct by
construction. Only the version string is dynamic; both the releases URL and each deck URL
are static and live in the HTML.

### 3. Front-end — header control group (per page)

Add a small control group in the top/header area of each of the three pages, right-aligned
so it doesn't collide with existing header content (e.g. the Director Panel's event-title
block on the left):

- **Version badge** — an `<a>` reading `v__RC_VERSION__ ↗` (renders `v1.1.0 ↗`, or
  `vdev ↗` / `dev` for dev builds), `href` = the static releases URL,
  `target="_blank" rel="noopener"`.
- **Help button** — an `<a>` styled as a button reading `? Help`, `href` = that file's
  role-specific deck URL (hardcoded per file), `target="_blank" rel="noopener"`.

Each page has its own header markup and CSS; the control group is added to match each
page's existing styling. The `__RC_VERSION__` placeholder appears only inside these three
HTML files.

## Testing

- New `tests/test_app_version.py` (stdlib runnable script, repo convention):
  - VERSION file with content -> that version (trimmed).
  - VERSION file empty / whitespace -> `dev`.
  - VERSION file absent -> `dev`.
- `racecast.py`'s `version()` keeps its current behavior; any existing version test in
  `tests/test_racecast.py` continues to pass (refactor is behavior-preserving).
- Lint: `python3 tools/lint.py` clean.

## Out of scope / non-goals

- No "update available" indicator (the badge only displays + links to releases; the
  Control Center already has the update check).
- No version on the `/console` launcher (`console.html`), the HUD, or other relay pages.
- No new HTTP endpoint.

## Follow-up in the same change (repo rule)

Changing the Director Panel, Commentator Cockpit, and Race Control UI surfaces means the
matching wiki screenshots are stale and MUST be regenerated and committed in the same
change (CLAUDE.md rule): `director-panel.png` and the cockpit / race-control images under
`src/docs/wiki/images/` (and the slide mirrors), via the `wiki-screenshots` skill.
