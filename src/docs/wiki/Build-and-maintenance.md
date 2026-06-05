# Build & maintenance

> Technical reference — for the maintainer.

How the repository is built, kept secret-free, and how this wiki is published. Everything
here is **maintainer-only** (not shipped in the operator package).

## Single source: edit only `src/`

`src/` is the only source of truth. `dist/` and `runtime/` are generated and gitignored —
never hand-edit them. `tools/` holds maintainer scripts. After any change that ships, run
`python3 tools/build.py` — its verify step is the closest thing to CI.

## Build the distributable

```bash
python3 tools/build.py      # assembles dist/IRO_Broadcast_Package/ + .zip and self-verifies
```

The verify step checks: tokens are in place (no raw sheet/timer URLs or machine paths),
the Companion password is blanked, the relay POV endpoint is present, no shell scripts are
shipped, and preflight + `.env.example` are included.

## Releases (standalone binaries)

Operators download `iro` from GitHub Releases and never need Python. Cutting a
release: make sure CI is green on `main`, then push a semver tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

`.github/workflows/release.yml` then tests on all three OSes, builds the
binaries with PyInstaller, stamps the tag into `iro --version`, creates the
GitHub release with generated notes, and uploads `iro-windows.zip` /
`iro-macos.tar.gz` / `iro-linux.tar.gz`. Each archive contains the `iro`
binary plus `.env.example`; on first run the binary copies it to `.env` next
to itself. The binaries are unsigned — operators see a one-time
SmartScreen/Gatekeeper warning (documented on the setup page).

## Round-trips that keep secrets/paths out of git

- **OBS collection.** Edit scenes in OBS, export, then fold back with
  `python3 tools/tokenize-obs.py exported.json src/obs/IRO_Endurance.json` (re-tokenizes
  sheet/timer URLs + asset paths). `src/setup-assets.py` does the reverse for a machine.
- **Companion config.** Export into the gitignored `incoming/` folder, then
  `python3 tools/strip_companion_pass.py` blanks the WebSocket password and writes
  `src/companion/iro-buttons.companionconfig`. `build.py` re-strips defensively.

## Publish this wiki

These pages are **generated from the repo**, not edited on GitHub. Source: `src/docs/wiki/`.

```bash
python3 tools/sync-wiki.py            # clone/pull the wiki repo, mirror pages, commit, push
python3 tools/sync-wiki.py --dry-run  # show what would change, push nothing
```

`tools/sync-wiki.py` derives the wiki remote (`<origin>.wiki.git`), clones it into
`runtime/wiki/`, mirrors `src/docs/wiki/*.md` + `images/` (adds/updates/**deletes**), and
pushes. Renaming a page therefore cleanly replaces the old one.

**First-time bootstrap (once per repo):** GitHub creates the wiki's Git repo only after the
first page is saved in the web UI. Open the repo's **Wiki** tab → create+save any page,
then run `sync-wiki.py` to overwrite it with the real pages.

## Page & diagram conventions

- `Home.md` is the landing page; `_Sidebar.md` is the left navigation (two tiers:
  operators first, technical reference below).
- Link by page name, no extension: `[Run an event](Run-an-event)`. Spaces in a title map to
  `-` in the file name.
- Diagrams are **Mermaid** in ```` ```mermaid ```` fences. GitHub renders them in a
  sandboxed iframe. **Pitfall:** never put a `;` inside a node/edge/note label — Mermaid
  treats it as a statement separator and the diagram fails with *"Unable to render rich
  display."* After publishing, spot-check the rendered pages.
- Screenshots live in `src/docs/wiki/images/`, referenced relatively:
  `![alt](images/your-file.png)`.

See also: [Architecture](Architecture) for the system design.
