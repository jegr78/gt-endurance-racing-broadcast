# Control Center — League logo in the sidebar header

**Date:** 2026-06-11
**Status:** Approved design (pre-implementation)

## Problem

The `LOGO` field in `profiles/<name>/profile.env` is resolved by `config.py`
into `ResolvedConfig.logo_path` (absolute path, relative to the profile dir,
blanked when the file is missing) but is **not wired to anything visible** — its
only consumer is the `racecast profile show` CLI output
(`src/scripts/profile_admin.py:192`). The `profile.env` comment even claims it
is "for the Control Center", which is misleading because no such rendering
exists.

Goal: show the active league's logo as a small image in the Control Center
sidebar header, **next to the active-profile name** (the `#active-profile-badge`
line). The generic "GT" app-mark stays. When no logo is set, the file is
missing, or it is not a web image, the header shows just the name as it does
today.

## Scope

In scope:
- Serve the active profile's logo from the Control Center UI server.
- Render it next to the active-profile name in the sidebar; fall back to
  "name only" when absent.
- Restrict what is served to web-image file types.

Out of scope (YAGNI):
- Logo upload UI, resizing/optimization, format conversion.
- Logos for non-active profiles (e.g. in the switcher dropdown).
- Showing the logo anywhere other than the sidebar header.

## Approach

Dedicated, **server-resolved** route `GET /api/profile/logo` that returns the
*active* profile's logo bytes. The request carries **no path** — the active
profile is resolved server-side via `config.py` — so there is no path-traversal
surface and no filename is exposed. (Rejected alternatives: extending the
generic `/api/assets/file/<kind>/<name>` route adds a traversal surface and
leaks the filename; embedding a base64 `data:` URI in `/api/profiles` bloats the
status JSON on every poll.)

## Components & data flow

### Backend

1. **Reuse** `config.py` `resolve_config()` → `ResolvedConfig.logo_path`
   (already absolute + `os.path.isfile`-validated, blank when missing). No change
   to `config.py`.

2. **New pure helper** `servable_logo_path(rc)` (in `src/racecast.py`, near the
   other UI provider helpers): returns `rc.logo_path` only when it is non-empty
   **and** its lowercased extension is in the web-image allowlist
   `{.png, .jpg, .jpeg, .webp, .gif, .svg}`; otherwise `""`. This prevents a
   stray `LOGO=profile.env` (or any non-image file in the profile dir) from being
   served as the "logo". Unit-tested.

3. **Content type:** add `".svg": "image/svg+xml"` to `_CTYPES` in
   `src/ui/ui_server.py` (currently png/jpg/jpeg/webp/gif but no svg, so SVG
   logos would otherwise be served as `application/octet-stream` and not render).
   *Trust note:* SVG can embed scripts, but it is served same-origin from a file
   the operator placed in their own profile dir on a local single-user tool —
   acceptable; no sanitization added.

4. **New ctx provider** `profile_logo()` (in `src/racecast.py`, added to the
   `ctx` dict ~line 2655 alongside `"profiles"`): resolves the active profile
   (`resolve_config` with no override) and returns
   `servable_logo_path(rc) or None`. Best-effort — any exception returns `None`,
   never raises (matches the other providers' contract).

5. **New route** `GET /api/profile/logo` (in `ui_server.py do_GET`, near
   `/api/profiles`): `p = ctx["profile_logo"]()`; if `p` → `self._serve_file(p)`
   (existing helper: sets `Content-Type` from `_CTYPES` + `Cache-Control:
   no-store`); else `self._not_found("no logo")`. Behind the existing
   `_allowed()` auth gate like every other route.

6. **Extend `/api/profiles`** payload: `profiles_data()` (in `src/racecast.py`)
   gains a top-level `"logo": bool` = whether the *active* profile has a servable
   logo (`bool(servable_logo_path(resolve_config(active)))`, best-effort, default
   `False`). The per-profile list entries are unchanged.

### Frontend (`src/ui/control-center.html`)

7. **Markup:** add `<img id="active-profile-logo" class="pflogo" hidden alt="">`
   inside the `.brandsub` line (id `active-profile-badge`), before the name text.
   Keep the name text clickable (→ `showView('profile')`) as today.

8. **CSS:** `.pflogo { max-height:24px; max-width:90px; height:auto;
   width:auto; border-radius:3px; margin-right:6px; vertical-align:middle; }` —
   **both** maxima are capped while `height:auto`/`width:auto` preserve the
   intrinsic aspect ratio; the browser scales the logo down to fit within
   whichever bound binds first and **never upscales** a small logo past its
   native size. The logo stays **inline** in the 11px `.brandsub` line next to
   the profile name (modest by design); `max-height` (24px) is the only value to
   tune. `object-fit` is intentionally omitted (it only matters when both
   dimensions are fixed). To keep the line tidy the `.brandsub` becomes a flex
   row (`display:flex; align-items:center`) so a slightly taller logo and the
   name stay vertically centered.

9. **JS in `loadProfiles()`** (after `activeProfile`/label are set, ~line 1827):
   - if `d.logo` → `img.src = '/api/profile/logo?p=' +
     encodeURIComponent(d.active)` (the `p` query is a cache-bust so switching
     profiles reloads the image; the server ignores it), `img.hidden = false`.
   - else → `img.hidden = true; img.removeAttribute('src')`.
   - `img.onerror = () => { img.hidden = true; }` (defensive: broken file).

10. **Refresh points:** `loadProfiles()` already runs on startup and on profile
    switch, covering both. Additionally call a small `refreshHeaderLogo()` (or
    re-invoke `loadProfiles()`) after a successful `profile.env` save so an edited
    `LOGO` value reflects without a full page reload.

11. **Fix the misleading comment** in `profiles/example/profile.env`: the `LOGO`
    line now genuinely is "shown in the Control Center sidebar header" — keep/clarify
    the wording so it matches reality.

## Error handling

Every backend provider is best-effort and returns `None`/`False` rather than
raising or 500-ing, so a missing/invalid/oversized logo never breaks the header
or the `/api/profiles` poll. A broken `<img>` hides itself via `onerror`. Net
effect of any failure: the header shows the profile name only, exactly as today.

## Testing (TDD — failing test first)

- **Unit** (`tests/test_iro.py` — it loads `src/racecast.py` as a module and
  tests its pure helpers): `servable_logo_path` — `.png`/`.svg` paths pass
  through; `.env`/`.txt`/empty/unknown extension → `""`. (File need not exist for
  the extension check; the `isfile` gate lives in `config.py` and is already
  covered by `tests/test_config.py`.)
- **Route** (`tests/test_ui_server.py`, using the `_get(port, path)` harness):
  with a ctx whose `profile_logo` returns a temp PNG path → `GET
  /api/profile/logo` is `200` with an `image/...` content-type and the file
  bytes; with `profile_logo` returning `None` → `404`.
- **Payload** (`tests/test_iro.py`): `profiles_data()` includes a boolean
  `logo` key (e.g. monkeypatch the resolver / use a temp profile with and
  without a logo file).

## Files touched

- `src/racecast.py` — `servable_logo_path` helper, `profile_logo` provider +
  `ctx` entry, `logo` flag in `profiles_data`.
- `src/ui/ui_server.py` — `.svg` in `_CTYPES`, `GET /api/profile/logo` route.
- `src/ui/control-center.html` — `<img>` markup, `.pflogo` CSS, `loadProfiles`
  logo logic + refresh-after-save.
- `profiles/example/profile.env` — clarify the `LOGO` comment.
- Tests: `tests/test_iro.py` (helper + `profiles_data` logo flag),
  `tests/test_ui_server.py` (`/api/profile/logo` route).
