# Producer Docs Consolidation — Design

**Date:** 2026-06-07
**Status:** Approved

## Problem

The producer documentation exists three times and the copies are drifting:

- **Two legacy documents duplicate the wiki.** `src/docs/README_SETUP.md`
  (335 lines) and `src/docs/IRO_Broadcast_Setup_Guide.md` (421 lines) cover
  ~90 % of the same ground as the wiki, predate `iro init` / `iro event
  start`, carry a section-numbering collision (two 4c/4d pairs), and must be
  hand-updated by every feature that touches the flow — ten implementation
  plans have patched them so far. An audit (this feature's exploration) found
  no factual contradictions yet, only divergence — but divergence is how
  contradictions start.
- **The printable cheat sheets are already stale.** `IRO_cheat_sheets.html`
  still opens the director panel as a local `director-panel.html` file
  (`file://`) — the panel has been relay-served at `:8088/panel` for two
  releases — and starts services per-command instead of `iro event start`.
- **Intra-wiki links rot silently.** Feature 2's final review caught two
  anchors broken by a heading rename (`Director#the-button-board`); nothing
  in CI would have noticed. There is no automated link/anchor check.
- **The wiki assumes terminal literacy.** "Open a terminal in that folder"
  is the first instruction a brand-new producer cannot follow; there is no
  glossary for the project's own vocabulary (relay, feed, stint, HUD, …),
  no per-step time estimates, and few "what you should see now" checkpoints.
- **Companion import guidance is incomplete.** The docs only describe
  "Replace current configuration" — re-imports should instead use
  "Import, Resetting only Selected Components" (default checkboxes), which
  preserves Companion's Settings **including the OBS WebSocket password**;
  only a first-ever import needs the password entered once (the shipped
  config is password-stripped).
- Carry-over: `install_apps.py` tells the user to "join the IRO tailnet" —
  Tailscale jargon a first-time producer doesn't know.

Persona review (non-technical producer) drove the scope. Feature 3 of 3.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Legacy docs | Both become **~20-line stub pages** pointing at the wiki (plus the quickstart commands). They stay in the dist package — `tools/build.py` needs no change. The 4c/4d numbering collision and all drift vanish with the content. |
| Cheat sheets | **Keep and update** `IRO_cheat_sheets.html` — printable one-pagers are valuable on event day. Bring to current flow (`iro event start/stop`, relay-served panel URL). Layout/print format unchanged. |
| Link checker | **Tool + CI gate**: `tools/check-wiki-links.py` (pure stdlib) + `tests/test_wiki.py`. The test file is picked up by `tools/run-tests.py`'s glob, so it gates every PR on all three OSes with **zero `ci.yml` change**. `tools/sync-wiki.py` additionally runs the check before pushing and aborts on failure. |
| Code touches | Message-string one-liners allowed; concretely the `install_apps.py` "tailnet" de-jargoning. No logic changes. |
| Screenshots | **Text checkpoints + invisible markers**: every checkpoint describes in words what the reader should see (useful immediately); an HTML comment `<!-- screenshot: … -->` marks each insertion point. The wish-list below is the work list for the screenshots (provided later by the maintainer). |
| "Terminal in 60 seconds" | A section on `Set-up-the-broadcast-PC.md` directly after "What you need" (where the first terminal contact happens), anchor-linkable from other pages. |
| Producer handover | Touch up the **existing** `Run-an-event.md` handover section (it already covers `--stint N` and `/status`): add where the incoming producer finds the stint number. No new page/section. |
| Glossary | On `Home.md` (new section after "Pick your path"), ~12 terms, one sentence each, each linking the responsible wiki page. Definitions only — no procedures. |

## Architecture

Docs-heavy feature with one new tool:

```
tools/check-wiki-links.py            NEW   intra-wiki link/anchor checker (pure stdlib)
tests/test_wiki.py                   NEW   unit tests + integration run over src/docs/wiki/
tools/sync-wiki.py                   MOD   run the checker before pushing, abort on errors
src/docs/README_SETUP.md             STUB  ~20-line pointer to the wiki + quickstart
src/docs/IRO_Broadcast_Setup_Guide.md STUB ~20-line pointer to the wiki + quickstart
src/docs/IRO_cheat_sheets.html       MOD   current flow (event start/stop, :8088/panel)
src/scripts/install_apps.py          MOD   one message string (tailnet → plain language)
src/docs/wiki/Home.md                MOD   glossary section
src/docs/wiki/Set-up-the-broadcast-PC.md  MOD  terminal section, checkpoints, time estimates,
                                               Companion import note
src/docs/wiki/Companion.md           MOD   first-import vs re-import guidance
src/docs/wiki/Run-an-event.md        MOD   handover stint-number source, go-live checkpoint,
                                           lead-time note
```

### 1. Wiki link checker

`tools/check-wiki-links.py` — pure functions, no dependencies:

- `github_anchor(heading, seen)` — GitHub's anchor algorithm: strip markdown
  emphasis, lowercase, drop every character that is not alphanumeric, space,
  hyphen, or underscore, then spaces → `-`. Duplicate headings get `-1`,
  `-2`, … suffixes. Must reproduce the double-dash case from Feature 2:
  `"Through the broadcast (scene + sheet cues)"` →
  `through-the-broadcast-scene--sheet-cues` (the removed `+` sits between
  two spaces).
- `extract_headings(markdown)` — ATX headings (`#`–`######`), **skipping
  fenced code blocks** (a `#` inside a ``` fence — e.g. Mermaid — is not a
  heading). Headings inside `<details>` blocks count (GitHub anchors them).
- `extract_links(markdown)` — inline links `[text](target)` with their line
  numbers. **Checked:** intra-wiki targets — `Page`, `Page#anchor`,
  `#anchor` (same page). **Skipped:** any scheme (`http://`, `https://`,
  `mailto:`), image embeds `![…](…)`, and relative file targets containing
  `/` (e.g. `images/…`).
- `check_wiki(directory)` — loads every `*.md`, builds the page → anchors
  map, returns a list of `"<file>:<line>: broken link …"` strings for
  (a) links to a page with no matching `<Page>.md` (exact match — our links
  are case-consistent) and (b) anchor links whose anchor no heading
  produces. `_Sidebar.md` is checked like any page; `_Footer.md` would be
  too if it existed.
- CLI: `python3 tools/check-wiki-links.py [dir]` (default
  `src/docs/wiki/`), prints errors, exit 1 if any.

`tests/test_wiki.py` (project convention: runnable script, `t_*` functions,
`ALL PASS`): unit tests for the anchor algorithm (lowercase/punctuation,
the double-dash case, duplicate suffixes), code-fence skipping, link
extraction (skips external/images, keeps `Page#anchor` and `#anchor`), and
an integration check: `check_wiki(<repo>/src/docs/wiki)` returns `[]`.
Repo-relative paths only — machine-independent, runs in CI via the
`run-tests.py` glob.

`tools/sync-wiki.py` runs the checker first and aborts the sync when it
reports errors (the suite is the primary gate; this is the last line of
defense for maintainers pushing directly).

### 2. Legacy docs → stubs

Both files become short pointer documents (~20 lines): one paragraph on what
the package is, the quickstart (`iro init` for first-time setup,
`iro cookies firefox` + `iro event start` on event day, `iro event stop`
after), and **absolute** wiki URLs
(`https://github.com/jegr78/IRO_Broadcast_Setup/wiki/<Page>`) — the files
are read outside the repo, so relative links would be dead. Page-level links
only (no anchors), so they cannot rot to heading renames; the checker's
scope stays `src/docs/wiki/`. `README_SETUP.md` keeps its role as the
"start here" file in the package; the Guide stub additionally names the
wiki's Architecture page for the technical background it used to provide.
`tools/build.py` ships both unchanged — no build change.

### 3. Cheat sheets refresh

`IRO_cheat_sheets.html` keeps its printable card layout; content updates:

- Event start: one `iro event start` (brings up Tailscale, Discord, relay,
  OBS, Companion, prints the director URLs) instead of the per-service
  command list; `iro event stop` at the end.
- Director access card: panel at `http://<producer-tailscale-ip>:8088/panel`
  (replacing the stale `director-panel.html` via `file://`/`http://` line);
  Companion tablet URL unchanged.
- Pre-event card: keep `iro install-tools --update`, add
  `iro cookies firefox` (refresh before each event) if missing, and
  `iro preflight`.
- Verify against the current wiki wording — the cards must not contradict
  `Run-an-event.md`.

### 4. tailnet de-jargoning

`src/scripts/install_apps.py` (currently line 309):
`"  Tailscale: sign in and join the IRO tailnet (invited account).")` →
`"  Tailscale: sign in and join the team's private Tailscale network "
"(your invited account).")`. Message string only; adjust any test asserting
the old text.

### 5. Glossary on `Home.md`

New section **"The words we use"** after "Pick your path": a table, one row
per term, one sentence each, linking the page that owns the topic. Terms
(~12): relay · feed (A/B) · stint · handover / NEXT · HUD · race timer ·
the panel · Companion · Tailscale · the Sheet · cookies · preflight · POV.
Definitions describe mechanism only.

### 6. "Terminal in 60 seconds" on `Set-up-the-broadcast-PC.md`

New `## Never used a terminal?` section between "What you need" and step 1:

- Open one **in a folder**: Windows — Explorer, right-click inside the
  folder → "Open in Terminal"; macOS — Finder, right-click the folder →
  Services → "New Terminal at Folder" (or Spotlight → "Terminal" and `cd`
  into it); Linux — most file managers: right-click → "Open Terminal Here".
- You get a **prompt** (a line ending in `$`, `%`, or `>`): paste or type a
  command, press **Enter**, read what comes back. Paste: `Ctrl+V`
  (Windows/Linux) / `Cmd+V` (macOS).
- One sentence of reassurance: commands here only act on the `iro` folder;
  nothing happens without pressing Enter.

The page's existing "open a terminal" mentions (step 1 and step 3) link to
this section's anchor; other wiki pages may link it the same way.

### 7. Checkpoints + screenshot markers

Each step on `Set-up-the-broadcast-PC.md` (1–9) ends with a short
**"You should now see:"** line describing the observable result in words,
followed by an invisible `<!-- screenshot: <what must be visible> -->`
marker. `Run-an-event.md` gets one checkpoint at the go-live moment.
Existing check commands (`./iro --version`, `iro preflight`) become part of
their step's checkpoint rather than separate afterthoughts.

**Screenshot wish-list** (the maintainer captures these later and replaces
the markers; the text checkpoints stay either way):

1. Terminal open in the `iro` folder with `./iro --version` output.
2. `.env` open in an editor, `IRO_SHEET_ID` filled (value blurred).
3. OBS **Scene Collection → Import** dialog with
   `runtime/IRO_Endurance.import.json` selected.
4. OBS after the import: scene list visible, **Standby** scene active.
5. Companion launcher with the **Launch GUI** button.
6. Companion **Import/Export → Import** dialog showing the
   "Reset/Replace" choices (used by both import cases).
7. Companion **Connections** tab with the OBS connection green.
8. OBS **WebSocket Server Settings** dialog (enabled, port 4455,
   authentication on).
9. Tailscale menu showing this machine's `100.x.y.z` IP.
10. `iro preflight` output with everything green.
11. OBS on **Standby** with the **Start Streaming** button (go-live
    checkpoint on Run-an-event).

### 8. Companion import guidance

`Companion.md` "Import the button board" and `Set-up-the-broadcast-PC.md`
step 6 distinguish two cases (mechanism from the maintainer, verified
against Companion's import dialog):

- **First import on a fresh machine:** confirm **"Replace current
  configuration"**; afterwards enter the OBS WebSocket password once in the
  OBS connection (the shipped config is password-stripped).
- **Re-import** (button-config update): choose **"Import, Resetting only
  Selected Components"** and keep the **default checkboxes** — this
  preserves Companion's Settings **including the stored OBS WebSocket
  password**; nothing needs re-typing. The existing "replaces the entire
  configuration — back up first" warning stays attached to the
  Replace path.

### 9. Handover detail + time estimates

- `Run-an-event.md` "Producer handover": one added sentence on where the
  stint number comes from — the **outgoing producer's** panel status strip
  (or `/status`) shows the stint on air right now. Mechanism only; how the
  teams coordinate the number is theirs.
- `Set-up-the-broadcast-PC.md`: coarse per-step estimates ("~5 min";
  downloads dominate step 2/3), consistent with the existing "about 30
  minutes" total.
- `Run-an-event.md`: one lead-time sentence near the top — start the
  pre-event steps ~30 minutes before the slot (cookies + `event start` +
  checks), matching what the page already implies.

## Testing

- `tests/test_wiki.py` — unit tests for the checker's pure functions plus
  the integration run over the real `src/docs/wiki/` (must be green over
  the enriched wiki — the new sections/anchors are checked the moment they
  land).
- Existing suite, `tools/lint.py`, and `tools/build.py` (verify step) stay
  green; the build must still ship both stubs and the refreshed cheat
  sheets (no `build.py` change expected).
- Manual: render-check the cheat sheets HTML in a browser once (print
  preview unaffected).

## Out of scope (deliberate)

- The screenshots themselves (maintainer-provided later; markers and the
  wish-list above are the contract).
- Director-facing pages (`Director.md`, `Director-Setup.md`) — Feature 2.
- Any code change beyond the `install_apps.py` message string.
- External-link checking (only intra-wiki links/anchors).
- Any statement of crew procedure — docs describe mechanism only.
- Deleting the legacy files or changing what `build.py` ships.
