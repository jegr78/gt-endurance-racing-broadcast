# HUD overlays

> Operator reference for restyling the on-screen HUD and race timer per league.
> Profiles in general are covered in [League profiles](Profiles).

The relay serves the lower-third **HUD** and the **race timer** as two shared pages — the
same `hud.html` / `timer.html` for every league. A league can **restyle** them — reposition
elements, change fonts and colors — **without forking** those pages, by shipping a small CSS
override (and optional fonts) in its profile.

## Where it lives

A league's overlay styling sits in its profile folder:

```
profiles/<name>/overlay/hud.css      # restyle the lower-third HUD
profiles/<name>/overlay/timer.css    # restyle the race timer
profiles/<name>/overlay/fonts/       # optional custom font files
```

`profiles/example/overlay/` ships as a commented template. Both CSS files are **optional**:
an empty or missing file means the base look is used unchanged.

## How it works

The base `hud.html` and `timer.html` stay shared. The relay serves the active league's CSS
files at fixed paths:

- **`/hud/override.css`** ← `profiles/<name>/overlay/hud.css`
- **`/timer/override.css`** ← `profiles/<name>/overlay/timer.css`

Each base page links its override **last** in `<head>`, so any rule in the league CSS
**wins the cascade** over the page's own styles. The CSS is read **per request**, so editor
saves apply without restarting the relay (with one first-time caveat below).

Custom fonts are served at **`/overlay/fonts/<file>`** from `profiles/<name>/overlay/fonts/`.
Reference them with a normal `@font-face`:

```css
@font-face { font-family: "League"; src: url(/overlay/fonts/League.woff2); }
```

## Overridable elements

The base HUD (`hud.html`, a 1920×1080 canvas, elements positioned from the top-left)
exposes these ids:

| Id | Element |
|---|---|
| `#stint` | the stint / label line |
| `#session` | the session line |
| `#streamer` | the commentator/streamer line |
| `#round-top` | the round header |
| `#round-flag` | the round country flag image |
| `#round-country` | the round country text |
| `#team0` `#team1` `#team2` | the three team rows (each holds a logo image + a `.name` span) |
| `#race-control` | the race-control line |

The race timer (`timer.html`) exposes one id: **`#clock`** (the digits).

## Editing

In the Control Center's **Profile** view, the **Overlay CSS** editor edits the HUD and
Timer CSS for the active league. **Save** writes the file; **Apply in OBS** reloads the
browser sources (the same as `racecast obs refresh`).

> **First-override caveat.** The relay only watches a profile's `overlay/` directory when
> that directory **existed at the moment the relay started** (the relay is launched with
> `--overlay-dir` only when the dir is present). So the **very first** override on a profile
> whose `overlay/` did not exist yet needs **one `racecast relay restart`** to activate.
> After that, later edits apply live via **Apply in OBS** — no restart.

> **CLI alternative:** edit `profiles/<name>/overlay/{hud,timer}.css` in any text editor,
> drop fonts in `profiles/<name>/overlay/fonts/`, then `racecast obs refresh`.

## Example `hud.css`

```css
/* Move the stint line and restyle race control */
#stint        { left: 800px; top: 30px; font-size: 44px; }
#race-control { background: #222a2f; }

/* Custom font (drop the file in overlay/fonts/ first) */
@font-face { font-family: "League"; src: url(/overlay/fonts/League.woff2); }
html, body { font-family: "League", "Arial Narrow", sans-serif; }
```

## OBS collection naming

Per-league overlay styling pairs naturally with a per-league OBS scene collection. The
naming convention is **`GT Endurance Racing — <league>`** (set via the profile's
`OBS_COLLECTION`); switch OBS to it with `racecast obs collection set`. See
[League profiles](Profiles) and [OBS & scenes](OBS-Setup).

---

> This page is generated from `src/docs/wiki/` in the
> [main repository](https://github.com/jegr78/gt-endurance-racing-broadcast) — don't edit it
> here by hand. See [Build & maintenance](Build-and-maintenance).
