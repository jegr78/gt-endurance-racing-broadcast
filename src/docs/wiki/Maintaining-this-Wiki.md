# Maintaining this Wiki

These pages are **generated from the repository**, not edited here. The canonical source
is `src/docs/wiki/*.md` in
[the main repo](https://github.com/jegr78/IRO_Broadcast_Setup). Editing a page in the
GitHub web UI would be overwritten on the next sync.

## Edit → sync

1. Edit the Markdown under `src/docs/wiki/` in the repo (English only, like all shipped
   docs).
2. Push the wiki:

   ```bash
   python3 tools/sync-wiki.py            # clone/pull the wiki repo, mirror pages, commit, push
   python3 tools/sync-wiki.py --dry-run  # show what would change, push nothing
   ```

`tools/sync-wiki.py` is a **maintainer** script (not shipped in the package). It:

- derives the wiki remote (`<origin>.wiki.git`) from the repo's `origin`,
- clones it into `runtime/wiki/` (gitignored) or pulls if already there,
- mirrors `src/docs/wiki/*.md` into the clone (adds/updates/deletes),
- commits and pushes.

## First-time bootstrap (once per repo)

GitHub only creates the wiki's Git repository **after the first page is saved through the
web UI**. Until then `sync-wiki.py` can't clone or push. One-time step:

1. Open the repo's **Wiki** tab → **Create the first page**.
2. Type anything → **Save Page**.
3. Now run `python3 tools/sync-wiki.py` — it overwrites that placeholder with the real
   pages.

## Page conventions

- **`Home.md`** is the landing page; **`_Sidebar.md`** is the left navigation.
- Link between pages by title with no extension: `[Relay Mode](Relay-Mode)`. A space in a
  page title maps to a `-` in the file name and link (`OBS Setup` → `OBS-Setup.md`).
- Diagrams are **Mermaid** in ```` ```mermaid ```` fences — GitHub renders them natively.
