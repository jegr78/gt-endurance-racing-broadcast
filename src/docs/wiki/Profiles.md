# League profiles

> Operator reference. The config keys these set are detailed in
> [Configuration & secrets](Configuration); the per-league HUD/timer look is in
> [HUD overlays](HUD-Overlays).

One machine can run **several leagues**. Each league is a **profile** — a self-contained
folder with its own Google Sheet, broadcast graphics/media, OBS scene collection and
overlay look. Switching leagues is a one-command profile switch; you never edit `.env` or
the OBS collection to change leagues.

## What a profile is

A profile lives in `profiles/<name>/`. Its config is the file
`profiles/<name>/profile.env`, with **un-prefixed** keys (the file *is* the league — real
environment variables and the machine `.env` do **not** override these). `profiles/example/`
is the shipped template.

```ini
# profiles/<name>/profile.env
NAME=My League
SHEET_ID=
SHEET_PUSH_URL=
INTRO_URL=
OUTRO_URL=
LOGO=
OBS_COLLECTION=
```

| Key | Meaning |
|---|---|
| **`NAME`** | Display name shown in the CLI / Control Center / docs (not the HUD). |
| **`SHEET_ID`** | The long ID from the league's HUD/schedule sheet URL (`…/spreadsheets/d/`**`<THIS>`**`/edit`). Drives the relay: stint schedule, POV tab, and the HUD overlay. |
| **`SHEET_PUSH_URL`** *(optional)* | The Apps Script write webhook (the `/exec` URL **including** its `?key=…` secret) shared by the race timer and the director panel's sheet controls. Unset = those write-backs are read-only. See [Sheet-Webhook](Sheet-Webhook). |
| **`INTRO_URL` / `OUTRO_URL`** *(optional)* | Override the Intro/Outro clip URLs that normally come from the Sheet's Assets tab (used by `racecast media`). |
| **`LOGO`** *(optional)* | A logo image (path relative to the profile dir) for the Control Center. |
| **`OBS_COLLECTION`** *(optional)* | The OBS scene-collection name this league uses, so several leagues keep separate collections in OBS on one machine. Blank = the profile's `NAME`. |

A profile folder also holds the league's overlay CSS (`overlay/`, see
[HUD overlays](HUD-Overlays)); its downloaded graphics and media live under
`runtime/<name>/`, not in the profile folder.

## Machine config vs. league config

Two kinds of config live in two different places — keep them straight:

- **League (per profile)** — everything in `profiles/<name>/profile.env` above. This is the
  league.
- **Machine (shared)** — a handful of optional, machine-only switches in the gitignored
  `.env` at the repo (or package) root: `RACECAST_OBS_WS_PASSWORD`,
  `RACECAST_COMPANION_EXE` (Windows), `RACECAST_UI_PORT`, `RACECAST_PROFILE` (the default
  active league), and `RACECAST_UI_PASSWORD` (reserved, not yet read). These apply to the
  machine regardless of which league is active.

Some state is **shared across leagues** and lives at the machine level: the YouTube
**cookies** and the `runtime/active-profile` pointer (which league is current).
**Per-league** state — downloaded graphics, intro/outro media, the localized OBS import —
lives under `runtime/<name>/`.

## The CLI

```bash
racecast profile list                          # which leagues exist (★ = active)
racecast profile show                          # the active league's resolved config
racecast profile use <name>                    # make it the active league
racecast profile new <name> --from example     # copy a profile dir to start a new league
```

`racecast profile new <name>` copies `profiles/example/` (or another profile via
`--from <src>`) into `profiles/<name>/`. `--from` defaults to `example`.

A global **`--profile <name>`** flag runs a single command against a non-active league
without switching:

```bash
racecast --profile otherleague relay start
```

**Which profile is active** (resolution order):

1. the `--profile <name>` flag (highest);
2. then `RACECAST_PROFILE` (a real environment variable, or the machine `.env`);
3. then the `runtime/active-profile` pointer (set by `racecast profile use`);
4. and if you keep **exactly one** profile, it is selected implicitly.

With several profiles and none of the above set, the CLI asks you to choose one.

## Add a second league

```bash
racecast profile new <name> --from example   # copy the template into profiles/<name>/
# edit profiles/<name>/profile.env — fill in NAME, SHEET_ID, (optional) SHEET_PUSH_URL, …
racecast profile use <name>                  # make it active
```

Then run the per-league setup steps for it — `racecast graphics`, `racecast media`,
`racecast setup` — exactly as for the first league. They all act on the active profile.

## Per-league OBS collection

Each profile gets its own localized OBS import file at
`runtime/<name>/GT_Endurance.import.json`, named after the profile's `OBS_COLLECTION`
(blank = the league's `NAME`). The per-league naming convention is
**`GT Endurance Racing — <league>`**, so OBS can hold a separate scene collection per
league on one machine. After importing, switch OBS to a league's collection with:

```bash
racecast obs collection set
```

Switching the OBS collection is always an explicit producer action (it rebuilds every
source) — it is never automatic. See [OBS & scenes](OBS-Setup).

## The Control Center Profile view

The Control Center's **Profile** view exposes all of the above in one place: a switcher
for the active league, a **New profile** dialog that copies an existing profile, a
`profile.env` editor (with masked secrets), the per-league **overlay-CSS** editor (HUD and
Timer — see [HUD overlays](HUD-Overlays)), and the profile-scoped graphics/media.

> **CLI alternative:** the `racecast profile …` verbs above, plus `racecast graphics` /
> `racecast media`. Edit `profiles/<name>/profile.env` in any text editor.

---

> This page is generated from `src/docs/wiki/` in the
> [main repository](https://github.com/jegr78/gt-endurance-racing-broadcast) — don't edit it
> here by hand. See [Build & maintenance](Build-and-maintenance).
