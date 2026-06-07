# Producer Docs Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the wiki the single canonical producer doc — legacy docs become stubs, cheat sheets get current, an automated link checker stops anchor rot, and the wiki gains the onboarding aids a non-technical producer needs (glossary, terminal primer, checkpoints, import guidance, time estimates).

**Architecture:** One new pure-stdlib tool (`tools/check-wiki-links.py`) gated through the existing test suite (a new `tests/test_wiki.py` is picked up by `tools/run-tests.py`'s glob — zero CI change) and through `tools/sync-wiki.py`. Everything else is content work on `src/docs/` files that ship as-is.

**Tech Stack:** Python 3 stdlib only (`re`, `os`, `sys`). No pytest — tests are runnable scripts with `t_*` functions, ending `ALL PASS`. Spec: `docs/superpowers/specs/2026-06-07-producer-docs-consolidation-design.md`.

**Conventions that bind every task:**
- Branch: `feat/producer-docs-consolidation` (already created; the spec is committed on it).
- All docs/code English. Never invent crew procedure — mechanism only.
- After changing any Python file run `python3 tools/lint.py`.
- Run the suite with `python3 tools/run-tests.py`; a single file with `python3 tests/test_wiki.py`.

---

### Task 1: Wiki link checker — tool + tests

**Files:**
- Create: `tools/check-wiki-links.py`
- Create: `tests/test_wiki.py`

The checker validates intra-wiki links (`[text](Page)`, `[text](Page#anchor)`, `[text](#anchor)`) in `src/docs/wiki/*.md` against the pages and their GitHub-generated heading anchors. External links (`http://`, `https://`, `mailto:`), image embeds (`![…](…)`), and slash-containing relative targets (`images/…`) are out of scope.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wiki.py`. Mirror the repo's import pattern (see the top of `tests/test_event.py`): load the dashed filename via `importlib`. The `__main__` runner block at the bottom is the repo's standard one (verbatim from `tests/test_event.py`).

```python
#!/usr/bin/env python3
"""Stdlib unit checks for the intra-wiki link checker (tools/check-wiki-links.py)
plus the integration run over the real src/docs/wiki/ pages.
Run: python3 tests/test_wiki.py"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "check_wiki_links", os.path.join(ROOT, "tools", "check-wiki-links.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def _write(directory, name, text):
    with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
        fh.write(text)


def t_anchor_basic():
    assert m.github_anchor("Run an event") == "run-an-event"
    # em-dash and dots drop, backticks are decoration, parens drop:
    assert m.github_anchor("4 — Add your secrets (`.env`)") == "4--add-your-secrets-env"


def t_anchor_double_dash_from_dropped_plus():
    # F2 regression case: the removed '+' sits between two spaces -> double dash.
    assert (m.github_anchor("Through the broadcast (scene + sheet cues)")
            == "through-the-broadcast-scene--sheet-cues")


def t_anchor_duplicate_headings_get_suffixes():
    seen = {}
    assert m.github_anchor("Setup", seen) == "setup"
    assert m.github_anchor("Setup", seen) == "setup-1"
    assert m.github_anchor("Setup", seen) == "setup-2"


def t_anchor_unescapes_html_entities():
    # OBS-Setup.md writes '&amp;' literally; GitHub renders '&', then drops it.
    assert m.github_anchor("4. HUD &amp; graphics (Browser Sources)") \
        == "4-hud--graphics-browser-sources"


def t_headings_skip_fenced_code():
    md = "# Real\n```bash\n# not a heading\n```\n## Also real\n~~~\n# nope\n~~~\n"
    assert m.extract_headings(md) == ["Real", "Also real"]


def t_extract_links_targets_and_lines():
    md = ("See [guide](Director) and [step](Director-Setup#step-1).\n"
          "```\n[in a fence](Ignored)\n```\n"
          "[same page](#local) and ![image](images/p.png) embed.\n")
    links = m.extract_links(md)
    assert (1, "Director") in links
    assert (1, "Director-Setup#step-1") in links
    assert all(t != "Ignored" for _, t in links)          # fences skipped
    assert (5, "#local") in links
    assert all("images/p.png" != t for _, t in links)     # image embed skipped


def t_check_wiki_reports_missing_page_and_anchor():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "Home.md",
               "# Home\n[ok](Page)\n[ok2](Page#a-section)\n[bad](Missing)\n"
               "[badanchor](Page#nope)\n[ext](https://example.com/x)\n"
               "[file](images/p.png)\n")
        _write(d, "Page.md", "# Page\n## A section\n")
        errors = m.check_wiki(d)
        assert len(errors) == 2, errors
        assert any("Missing" in e for e in errors)
        assert any("nope" in e for e in errors)


def t_check_wiki_same_page_anchor():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "Solo.md", "# Solo\n## Deep dive\n[jump](#deep-dive)\n[bad](#none)\n")
        errors = m.check_wiki(d)
        assert len(errors) == 1 and "#none" in errors[0], errors


def t_check_wiki_real_pages_are_clean():
    errors = m.check_wiki(os.path.join(ROOT, "src", "docs", "wiki"))
    assert errors == [], "\n".join(errors)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_wiki.py`
Expected: FAIL — `FileNotFoundError` / spec is None (the tool does not exist yet).

- [ ] **Step 3: Implement the checker**

Create `tools/check-wiki-links.py`:

```python
#!/usr/bin/env python3
"""Check intra-wiki links and anchors in src/docs/wiki/.

Heading renames silently break [text](Page#anchor) links (it happened: two
`Director#the-button-board` links rotted when that heading was renamed).
This tool builds the page -> anchors map with GitHub's anchor algorithm and
reports links pointing at missing pages or anchors.

Checked:   [text](Page) · [text](Page#anchor) · [text](#anchor)
Ignored:   schemes (https:, mailto:), image embeds ![…](…), and relative
           file targets containing '/' (e.g. images/…).

Usage:
  python3 tools/check-wiki-links.py            # checks src/docs/wiki/
  python3 tools/check-wiki-links.py some/dir   # checks another directory

Exit 1 when broken links are found. Gates: tests/test_wiki.py runs this over
the real wiki in the suite (= CI); tools/sync-wiki.py runs it before pushing.
"""
import html, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# inline links, image embeds excluded via lookbehind; optional "title" allowed
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*:")
_MD_DECOR = re.compile(r"[*_`]")        # emphasis/code markers in heading text
_ANCHOR_DROP = re.compile(r"[^\w\- ]")  # GitHub keeps word chars, '-', spaces


def github_anchor(heading, seen=None):
    """GitHub's heading -> anchor id; `seen` (dict) makes duplicates -1, -2…
    HTML entities are unescaped first: the wiki source writes '&amp;' literally,
    GitHub renders '&' and anchors the rendered text."""
    text = _MD_DECOR.sub("", html.unescape(heading.strip())).lower()
    text = _ANCHOR_DROP.sub("", text).replace(" ", "-")
    if seen is None:
        return text
    n = seen.get(text)
    seen[text] = (n or 0) + 1
    return text if n is None else f"{text}-{n}"


def _content_lines(markdown):
    """(line_number, line) pairs outside fenced code blocks."""
    fence = None
    for i, line in enumerate(markdown.splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in ("```", "~~~"):
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            yield i, line


def extract_headings(markdown):
    """ATX heading texts in order, fenced code blocks skipped."""
    heads = []
    for _, line in _content_lines(markdown):
        h = HEADING_RE.match(line)
        if h:
            heads.append(h.group(2))
    return heads


def page_anchors(markdown):
    """Every anchor id the page provides (duplicates suffixed like GitHub)."""
    seen = {}
    return {github_anchor(h, seen) for h in extract_headings(markdown)}


def extract_links(markdown):
    """(line_number, target) for every inline link outside code fences."""
    links = []
    for i, line in _content_lines(markdown):
        for match in LINK_RE.finditer(line):
            links.append((i, match.group(1)))
    return links


def check_wiki(directory):
    """List of '<file>:<line>: …' problems for intra-wiki links in `directory`."""
    docs = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith(".md"):
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                docs[name] = fh.read()
    anchors = {name[:-3]: page_anchors(md) for name, md in docs.items()}
    errors = []
    for name, md in docs.items():
        for line, target in extract_links(md):
            if SCHEME_RE.match(target) or "/" in target:
                continue  # external link or relative file (images/…)
            page, _, anchor = target.partition("#")
            if page and page not in anchors:
                errors.append(f"{name}:{line}: link to missing page "
                              f"'{page}' ({target})")
                continue
            have = anchors[page or name[:-3]]
            if anchor and anchor not in have:
                errors.append(f"{name}:{line}: broken anchor '{target}'")
    return errors


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    directory = args[0] if args else os.path.join(ROOT, "src", "docs", "wiki")
    errors = check_wiki(directory)
    for e in errors:
        print(e)
    if errors:
        sys.exit(1)
    print(f"wiki links OK ({os.path.relpath(directory, ROOT)})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `python3 tests/test_wiki.py`
Expected: PASS (`ALL PASS`). **If `t_check_wiki_real_pages_are_clean` fails**, inspect each reported error by opening the named page/line: a genuinely broken link in a wiki page gets fixed **in the wiki page** (that is the checker doing its job — mention it in the commit message); a link the checker *wrongly* rejects (compare against how GitHub actually renders the anchor) is a checker bug — fix the checker, never the page. Do not weaken the assertion.

- [ ] **Step 5: Lint and full suite**

Run: `python3 tools/lint.py` → `All checks passed!`
Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS` (the new file is picked up automatically by the glob).

- [ ] **Step 6: Commit**

```bash
git add tools/check-wiki-links.py tests/test_wiki.py
git commit -m "feat: intra-wiki link/anchor checker, gated through the test suite"
```

---

### Task 2: Gate `sync-wiki.py` on the link check

**Files:**
- Modify: `tools/sync-wiki.py` (current `main()` starts at line 120)
- Test: manual run (maintainer script — not covered by the suite, same as the rest of the file)

- [ ] **Step 1: Add the gate**

In `tools/sync-wiki.py`, add this function after `wiki_remote_from_origin()` (after line 46):

```python
def run_link_check():
    """Abort the sync when tools/check-wiki-links.py finds broken links.
    (The test suite is the primary gate; this is the maintainer's last line
    of defense before pages go public.)"""
    import importlib.util
    path = os.path.join(ROOT, "tools", "check-wiki-links.py")
    spec = importlib.util.spec_from_file_location("check_wiki_links", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors = mod.check_wiki(WIKI_SRC)
    if errors:
        sys.exit("ERROR: broken wiki links — fix before publishing:\n  "
                 + "\n  ".join(errors))
```

In `main()`, call it right after the existing `WIKI_SRC` sanity checks — i.e. directly below the `if not any(f.endswith(".md") …)` block (currently lines 131–132):

```python
    run_link_check()
```

- [ ] **Step 2: Verify both paths**

Run: `python3 tools/sync-wiki.py --dry-run`
Expected: the link check passes silently and the script proceeds to `Wiki remote: …` (network failures after that point are irrelevant to this task). Then prove the gate fires: append `\n[broken](No-Such-Page)\n` to `src/docs/wiki/Home.md`, run again, expect `ERROR: broken wiki links` with the file:line — then **revert that test edit** (`git checkout -- src/docs/wiki/Home.md`).

- [ ] **Step 3: Lint, then commit**

Run: `python3 tools/lint.py` → `All checks passed!`

```bash
git add tools/sync-wiki.py
git commit -m "feat: refuse to publish the wiki over broken intra-wiki links"
```

---

### Task 3: Legacy docs become wiki-pointer stubs

**Files:**
- Rewrite: `src/docs/README_SETUP.md` (full replacement)
- Rewrite: `src/docs/IRO_Broadcast_Setup_Guide.md` (full replacement)

`tools/build.py:41` ships both files by name — names don't change, so no build change. Absolute wiki URLs (the files are read outside the repo), page-level only (no anchors — they can't rot).

- [ ] **Step 1: Replace `src/docs/README_SETUP.md`**

Replace the entire file content with:

```markdown
# IRO Endurance Broadcast — Setup Package

This package sets up a complete producer station for the IRO Endurance
broadcast: OBS scenes + HUD, the Companion button board, the director panel,
and the relay that pulls each commentator's stream into OBS.

**The documentation lives in the project wiki** — always current, written for
first-time producers:

- **First-time setup** (one time, ~30 min):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Set-up-the-broadcast-PC>
- **Event day:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Run-an-event>
- **Start page** (all roles):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki>

## Quickstart

First-time setup — one guided command (it skips whatever is already done):

    iro init

On event day:

    iro cookies firefox    # refresh YouTube cookies (log into YouTube in Firefox first)
    iro event start        # bring everything up; prints the director URLs
    iro event stop         # after the broadcast

`iro preflight` checks this machine any time and names the exact fix for
anything missing.

The printable role cheat sheets are in `IRO_cheat_sheets.html` (open it in a
browser, print).
```

- [ ] **Step 2: Replace `src/docs/IRO_Broadcast_Setup_Guide.md`**

Replace the entire file content with:

```markdown
# IRO Endurance Broadcast — Setup Guide

This guide has moved to the project wiki, which is always current:

- **How the system works:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Architecture>
- **Set up the broadcast PC** (step by step):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Set-up-the-broadcast-PC>
- **Run an event** (the producer's checklist):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Run-an-event>
- **The relay — how the feeds work:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Relay-Mode>
- **If something goes wrong:**
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/If-something-goes-wrong>
- **Who does what** (roles + streamer requirements):
  <https://github.com/jegr78/IRO_Broadcast_Setup/wiki/Who-does-what>

For the quickstart commands, start with `README_SETUP.md` in this package.
```

- [ ] **Step 3: Verify nothing else points into the removed content**

Run: `grep -rn "README_SETUP\|Setup_Guide" --include="*.py" --include="*.md" --include="*.yml" . | grep -v dist/ | grep -v runtime/ | grep -v docs/superpowers/ | grep -v node_modules`
Expected: only `tools/build.py` (ships by filename — fine), `CLAUDE.md` (describes the files — fine), and the stubs' own cross-reference. Anything that links a *section* of the old content (e.g. `README_SETUP.md#...`) must be re-pointed at the wiki — there should be none.

- [ ] **Step 4: Build check + suite, then commit**

Run: `python3 tools/build.py`
Expected: build + self-verify pass (both stubs land in `dist/IRO_Broadcast_Package/`).
Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS`

```bash
git add src/docs/README_SETUP.md src/docs/IRO_Broadcast_Setup_Guide.md
git commit -m "docs: legacy setup docs become wiki-pointer stubs

The wiki is the single canonical producer documentation; the two package
docs had drifted (pre-dating iro init / iro event start) and duplicated
~90% of it. Stubs keep their filenames, so tools/build.py is unchanged."
```

---

### Task 4: Cheat-sheets refresh + tailnet de-jargoning

**Files:**
- Modify: `src/docs/IRO_cheat_sheets.html` (5 edits, lines referenced from current file)
- Modify: `src/scripts/install_apps.py:309` (one message string)

- [ ] **Step 1: Update the header version tag (line 55)**

Old:
```html
    <span>Print &amp; pin · v3 setup</span>
```
New:
```html
    <span>Print &amp; pin · v4 setup</span>
```

- [ ] **Step 2: Replace the Producer "Before the event" list (lines 102–110)**

Old:
```html
        <ol>
          <li>Update tools: <code>iro install-tools --update</code>.</li>
          <li>Update GPU driver.</li>
          <li>Tailscale running; a Director confirms access.</li>
          <li>OBS → Tools → <span class="k">WebSocket on</span>; Companion green.</li>
          <li>Run <span class="k">iro relay start</span>; confirm the feeds appear in OBS.</li>
          <li>Test the Discord audio source.</li>
          <li>Enter the <span class="k">IRO stream key</span> in OBS.</li>
        </ol>
```
New:
```html
        <ol>
          <li>Update: <code>iro update</code>, then <code>iro install-tools --update</code>.</li>
          <li>Update GPU driver; <span class="k">reboot</span> the PC.</li>
          <li>Refresh cookies: <code>iro cookies firefox</code> (log into YouTube in Firefox first).</li>
          <li>Check the machine: <code>iro preflight</code> — fix anything it flags.</li>
          <li>Bring everything up: <span class="k">iro event start</span> — Tailscale, Discord, relay, OBS, Companion; prints the director URLs to forward.</li>
          <li>Companion green; a Director confirms access. Test the Discord audio source.</li>
          <li>Enter the <span class="k">IRO stream key</span> in OBS.</li>
        </ol>
```

- [ ] **Step 3: Replace the Producer "End" list item (line 130)**

Old:
```html
          <li>Close feeds: <code>iro relay stop</code>.</li>
```
New:
```html
          <li>Shut down services: <code>iro event stop</code>.</li>
```

- [ ] **Step 4: Replace the Director "Connect" list (lines 143–146)**

Old:
```html
        <ol>
          <li>Open <span class="k">director-panel.html</span> (via <code>file://</code> or <code>http://</code> — <span class="warn">not https</span>),<br>or Companion: <code>http://&lt;producer-tailscale-ip&gt;:8000/tablet</code>.</li>
          <li>Enter Producer Tailscale IP + port <code>4455</code> + password → Connect.</li>
        </ol>
```
New:
```html
        <ol>
          <li>Panel: <code>http://&lt;producer-tailscale-ip&gt;:8088/panel</code>,<br>or Companion buttons: <code>http://&lt;producer-tailscale-ip&gt;:8000/tablet</code>.</li>
          <li>Panel scene/audio control only: enter the producer's Tailscale IP + port <code>4455</code> + the OBS WebSocket password → Connect (asked once — the browser remembers it). Companion buttons need no password.</li>
        </ol>
```

- [ ] **Step 5: Update the POV status reference (line 165)**

Old:
```html
          <li>URL in Sheet tab <span class="k">POV</span> A2 → <code>POV Reload</code> → wait until <code>/status</code> shows <span class="k">serving</span> → <code>POV Toggle</code> (PiP bottom-right).</li>
```
New:
```html
          <li>URL in Sheet tab <span class="k">POV</span> A2 → <code>POV Reload</code> → wait until the panel health line (or <code>/status</code>) shows <span class="k">serving</span> → <code>POV Toggle</code> (PiP bottom-right).</li>
```

- [ ] **Step 6: De-jargon the Tailscale first-run hint**

In `src/scripts/install_apps.py` line 309, old:
```python
    print("  Tailscale: sign in and join the IRO tailnet (invited account).")
```
New:
```python
    print("  Tailscale: sign in and join the team's private Tailscale "
          "network (your invited account).")
```

- [ ] **Step 7: Verify**

Run: `python3 tools/lint.py` → `All checks passed!`
Run: `python3 tools/run-tests.py` → `ALL TEST FILES PASS` (no test asserts the old string — verified during design).
Open `src/docs/IRO_cheat_sheets.html` in a browser once (e.g. `open src/docs/IRO_cheat_sheets.html` on macOS): the three cards render, no stray markup, print preview unaffected. Cross-check the Producer card against `src/docs/wiki/Run-an-event.md` "Before you go live" — the cards must not contradict it.

- [ ] **Step 8: Commit**

```bash
git add src/docs/IRO_cheat_sheets.html src/scripts/install_apps.py
git commit -m "docs: refresh cheat sheets to event start/stop + relay-served panel; de-jargon tailnet hint"
```

---

### Task 5: Glossary on Home.md

**Files:**
- Modify: `src/docs/wiki/Home.md` (insert after the "Pick your path" list, line 35, before the `---`)

- [ ] **Step 1: Insert the glossary section**

In `src/docs/wiki/Home.md`, between the last "Pick your path" bullet (line 35, `…**Technical reference** section in the sidebar.`) and the `---` (line 37), insert:

```markdown

## The words we use

| Term | Meaning |
|---|---|
| **The relay** | the small server on the producer's PC that pulls each commentator's YouTube stream and hands it to OBS — [Relay — how the feeds work](Relay-Mode) |
| **Feed A / Feed B** | the two fixed slots the relay serves; they take turns so the picture never drops at a driver change — [Relay-Mode](Relay-Mode) |
| **Stint** | one commentator's stretch of the race; the schedule is a numbered list of stints — [Run an event](Run-an-event) |
| **NEXT / handover** | the driver-change moment: the off-air feed advances to the next stint's stream — [Director guide](Director) |
| **HUD** | the on-screen overlay (drivers, teams, session info) the relay serves to OBS — [OBS & scenes](OBS-Setup) |
| **Race timer** | the on-screen countdown, controlled by the director — [Race Timer](Race-Timer) |
| **The panel** | the director's browser page at `:8088/panel` — every control of the show on one page — [Director guide](Director) |
| **Companion** | Bitfocus Companion, the big-buttons board (browser or Stream Deck), the panel's sibling — [Companion](Companion) |
| **Tailscale** | the private-network app that makes the producer's PC reachable for remote directors — [Director setup](Director-Setup) |
| **The Sheet** | the shared Google Sheet that drives the schedule, the HUD and the downloadable assets — [Configuration & secrets](Configuration) |
| **Cookies** | the exported YouTube login the relay needs to pass YouTube's bot check — [Relay-Mode](Relay-Mode) |
| **Preflight** | `iro preflight`, the machine check that names the exact fix for anything missing — [Set up the broadcast PC](Set-up-the-broadcast-PC) |
| **POV** | the optional driver picture-in-picture feed — [Director guide](Director) |
```

- [ ] **Step 2: Verify and commit**

Run: `python3 tests/test_wiki.py` → `ALL PASS` (all 13 link targets exist).

```bash
git add src/docs/wiki/Home.md
git commit -m "docs(wiki): glossary on Home — the project vocabulary in one table"
```

---

### Task 6: Set-up-the-broadcast-PC — terminal primer, checkpoints, time estimates, import guidance

**Files:**
- Modify: `src/docs/wiki/Set-up-the-broadcast-PC.md` (line numbers from the current file)

All edits below; apply top-to-bottom (later line numbers shift as you insert — work bottom-up or re-locate by quoted context).

- [ ] **Step 1: Insert the terminal primer after "What you need"**

After line 13 (`- A **YouTube login** (for cookies) and the **shared Google Sheet** link from the team.`), before `## 1 — Get the iro tool`, insert:

```markdown

## Never used a terminal?

Sixty seconds of background, and every command on this page makes sense:

- **Open a terminal in a folder.** Windows: open the folder in Explorer,
  right-click an empty spot → **Open in Terminal**. macOS: right-click the
  folder in Finder → **Services → New Terminal at Folder** (or open
  **Terminal** via Spotlight, type `cd `, drag the folder into the window,
  press Enter). Linux: most file managers — right-click → **Open Terminal
  Here**.
- **You get a prompt** — a line ending in `$`, `%`, or `>`. Type or paste a
  command (paste: `Ctrl+V`, macOS `Cmd+V`), press **Enter**, and read what
  comes back.
- Nothing runs until you press Enter, and the commands in this wiki only act
  on the `iro` folder.
```

- [ ] **Step 2: Per-step time estimates**

Insert one italic line directly under each numbered section heading (no heading text changes — heading renames would break anchors):

| Under heading | Insert line |
|---|---|
| `## 1 — Get the iro tool` | `*Takes ~5 minutes.*` |
| `## 2 — Install the apps` | `*Takes ~5–10 minutes (downloads).*` |
| `## 3 — Install the command-line tools` | `*Takes ~5 minutes.*` |
| `## 4 — Add your secrets (.env)` | `*Takes ~2 minutes.*` |
| `## 5 — Import the OBS scenes` | `*Takes ~5 minutes.*` |
| `## 6 — Import the Companion buttons` | `*Takes ~5 minutes.*` |
| `## 7 — Let Companion control OBS` | `*Takes ~2 minutes.*` |
| `## 8 — Connect remote directors (Tailscale)` | `*Takes ~5 minutes.*` |
| `## 9 — Pre-flight check` | `*Takes ~1 minute.*` |

(Each as its own paragraph: heading line, blank line, the italic line, blank line, then the existing content.)

- [ ] **Step 3: Link the primer from the existing terminal mentions**

Line 27–28, old:
```markdown
working files (`.env`, `runtime/`) next to the binary. Open a terminal **in that
folder** and check it runs:
```
New:
```markdown
working files (`.env`, `runtime/`) next to the binary. Open a terminal **in that
folder** (first time? [Never used a terminal?](#never-used-a-terminal)) and
check it runs:
```

Line 116–117 (step 3), old:
```markdown
commentator's stream into OBS and pass YouTube's bot check. Afterwards **open a
new terminal** — installers update the PATH for new shells only (`iro preflight`
```
New:
```markdown
commentator's stream into OBS and pass YouTube's bot check. Afterwards **open a
new terminal** ([how?](#never-used-a-terminal)) — installers update the PATH for
new shells only (`iro preflight`
```

- [ ] **Step 4: Checkpoints (+ screenshot markers only where the spec's wish-list defines one)**

Insert each checkpoint at the **end of its step's section** (after the step's last paragraph/details block, before the next `##` heading):

**Step 1** — after line 35 (`step 4).`), before the SmartScreen blockquote stays where it is; place the checkpoint after the *whole* section's intro content, i.e. directly after the paragraph ending `step 4).`:
```markdown

**You should now see:** the version number printed in the terminal, and a new
`.env` file next to the binary.
<!-- screenshot: terminal open in the iro folder with ./iro --version output -->
```

**Step 2** — before `## 3 —`:
```markdown

**You should now see:** OBS Studio, Companion, Tailscale and Discord in your
applications / Start menu.
```

**Step 3** — before `## 4 —` (after the `</details>` block):
```markdown

**You should now see:** in a **new** terminal, `streamlink --version`,
`yt-dlp --version`, `ffmpeg -version` and `deno --version` each print a version.
```

**Step 4** — before `## 5 —`:
```markdown

**You should now see:** your `.env` containing a filled `IRO_SHEET_ID=…` line.
<!-- screenshot: .env open in an editor with IRO_SHEET_ID filled (value blurred) -->
```

**Step 5** — before `## 6 —`. First verify the scene names against `src/docs/wiki/OBS-Setup.md` (use the names that page lists; the set below comes from it — adjust if it differs):
```markdown

**You should now see:** OBS switched to the imported collection — the scene
list includes Standby, Stint, Splitscreen, Interview, Intro and Outro.
<!-- screenshot: OBS Scene Collection -> Import dialog with runtime/IRO_Endurance.import.json selected -->
<!-- screenshot: OBS after the import - scene list visible, Standby scene active -->
```

**Step 6** — before `## 7 —` (also see Step 5 of this task below for the import-dialog note inserted in the same section):
```markdown

**You should now see:** the IRO buttons in Companion's admin **Buttons** tab.
<!-- screenshot: Companion launcher with the Launch GUI button -->
<!-- screenshot: Companion Import/Export -> Import dialog showing the Reset/Replace choices -->
```

**Step 7** — before `## 8 —`:
```markdown

**You should now see:** the OBS connection **green** under Companion →
**Connections**.
<!-- screenshot: Companion Connections tab with the OBS connection green -->
<!-- screenshot: OBS WebSocket Server Settings dialog (enabled, port 4455, authentication on) -->
```

**Step 8** — before `## 9 —`:
```markdown

**You should now see:** this machine's `100.x.y.z` address in the Tailscale
menu, and your invited directors listed in the Tailscale admin console.
<!-- screenshot: Tailscale menu showing this machine's 100.x.y.z IP -->
```

**Step 9** — at the end of the file (after `Fix anything it flags. Then you're ready → [Run an event](Run-an-event).`):
```markdown

**You should now see:** every check green — or only warnings you understand
(e.g. Companion not running yet).
<!-- screenshot: iro preflight output with everything green -->
```

- [ ] **Step 5: Companion import-dialog guidance in step 6**

In section 6, old (lines 171–174):
```markdown
The first run just launches Companion (it creates its config on startup). In the
launcher press **Launch GUI**, then import the provided button config in the admin
(**Import/Export → Import** — `iro export companion` writes it to
`runtime/iro-buttons.companionconfig`). Finally bind the board to the tailnet:
```
New:
```markdown
The first run just launches Companion (it creates its config on startup). In the
launcher press **Launch GUI**, then import the provided button config in the admin
(**Import/Export → Import** — `iro export companion` writes it to
`runtime/iro-buttons.companionconfig`). In the import dialog: a **first import**
on a fresh machine → confirm **"Replace current configuration"**; **updating an
existing board** later → choose **"Import, Resetting only Selected Components"**
with the default checkboxes — that keeps Companion's settings, including the
stored OBS WebSocket password (details: [Companion](Companion#import-the-button-board)).
Finally bind the board to the tailnet:
```

- [ ] **Step 6: Point step 8 at Director-Setup too**

Old (line 195): `the show. More: [Director guide](Director).`
New: `the show. More: [Director setup](Director-Setup) (the page to send your directors) and the [Director guide](Director).`

- [ ] **Step 7: Verify and commit**

Run: `python3 tests/test_wiki.py` → `ALL PASS` (new `#never-used-a-terminal` anchor + all links resolve; `Companion#import-the-button-board` must match `Companion.md`'s heading).

```bash
git add src/docs/wiki/Set-up-the-broadcast-PC.md
git commit -m "docs(wiki): setup page — terminal primer, per-step checkpoints + time estimates, Companion import guidance"
```

---

### Task 7: Companion import cases + Run-an-event touch-ups

**Files:**
- Modify: `src/docs/wiki/Companion.md` (lines 11–24)
- Modify: `src/docs/wiki/Run-an-event.md` (lines 40, 67–72, 153–156)

- [ ] **Step 1: Companion.md — two import cases**

Old (lines 13–24):
```markdown
2. In the admin: **Import/Export → Import** → the file `iro export companion` writes
   (`runtime/iro-buttons.companionconfig`). This is a **full config** → confirm
   **"Replace current configuration"**.
3. Bind the board to the tailnet: `iro companion restart` — sets Companion's bind
   address to this machine's Tailscale IP. (Linux: set the launcher's **GUI
   Interface** to the Tailscale IP manually.)

> ⚠️ This **replaces the entire Companion configuration** on this station. Fine for a
> fresh/dedicated producer station; **back up first** if this Companion holds other
> content.
```
New:
```markdown
2. In the admin: **Import/Export → Import** → the file `iro export companion` writes
   (`runtime/iro-buttons.companionconfig`). The import dialog offers two paths:
   - **First import on a fresh machine:** confirm **"Replace current
     configuration"**. Afterwards enter the OBS WebSocket password once (next
     section) — the shipped config is password-stripped.
   - **Re-import (button update):** choose **"Import, Resetting only Selected
     Components"** and keep the **default checkboxes** — this preserves
     Companion's settings, **including the stored OBS WebSocket password**;
     nothing needs re-typing.
3. Bind the board to the tailnet: `iro companion restart` — sets Companion's bind
   address to this machine's Tailscale IP. (Linux: set the launcher's **GUI
   Interface** to the Tailscale IP manually.)

> ⚠️ **"Replace current configuration"** replaces the **entire** Companion
> configuration on this station. Fine for a fresh/dedicated producer station;
> **back up first** if this Companion holds other content.
```

- [ ] **Step 2: Companion.md — scope the password note to first imports**

In the "Connect to OBS" section (lines 28–31), old:
```markdown
The **OBS connection** (`127.0.0.1:4455`) comes with the config — **but without the
password** (removed for security). → **Connections** → open the OBS entry → **enter your
OBS WebSocket password** (the one you set in [Set up the broadcast PC](Set-up-the-broadcast-PC)) → the
connection turns green.
```
New:
```markdown
The **OBS connection** (`127.0.0.1:4455`) comes with the config — **but without the
password** (removed for security). After a **first import**: → **Connections** → open
the OBS entry → **enter your OBS WebSocket password** (the one you set in
[Set up the broadcast PC](Set-up-the-broadcast-PC)) → the connection turns green.
(A re-import via **"Resetting only Selected Components"** keeps the stored
password — nothing to do.)
```

- [ ] **Step 3: Run-an-event.md — lead-time line**

After the `## Before you go live` heading (line 40), insert:
```markdown

Plan **about 30 minutes** for these steps before the broadcast slot.
```

- [ ] **Step 4: Run-an-event.md — go-live checkpoint**

After the "Go live" paragraph (ends line 72, `…cut into the race look (**STINT A** / **Splitscreen**).`), insert:
```markdown

**You should now see:** OBS sitting on **Standby** with the stream running —
the **Start Streaming** button now reads **Stop Streaming**.
<!-- screenshot: OBS on Standby with the stream running (button reads Stop Streaming) -->
```

- [ ] **Step 5: Run-an-event.md — where the stint number comes from**

Old (lines 153–156):
```markdown
1. Incoming producer: `iro event start --stint <N>` — N is the stint **on air
   right now** (1-based, from the schedule sheet / Discord). Taking over right
   at a stint change (e.g. a part boundary like "end of stint 3"): pass the
   stint that is starting.
```
New:
```markdown
1. Incoming producer: `iro event start --stint <N>` — N is the stint **on air
   right now** (1-based, from the schedule sheet / Discord). The **outgoing
   producer's** panel status strip (or their `/status`) shows the stint each
   feed carries and which is on air — anyone with that panel open can read
   N off it. Taking over right at a stint change (e.g. a part boundary like
   "end of stint 3"): pass the stint that is starting.
```

- [ ] **Step 6: Verify and commit**

Run: `python3 tests/test_wiki.py` → `ALL PASS`.
Cross-check: the refreshed cheat-sheet Producer card (Task 4) and this page's "Before you go live" list must agree (they do: update → reboot → cookies → preflight → event start).

```bash
git add src/docs/wiki/Companion.md src/docs/wiki/Run-an-event.md
git commit -m "docs(wiki): Companion import cases (password-preserving re-import), handover stint source, go-live checkpoint + lead time"
```

---

### Task 8: Full gates

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `python3 tools/run-tests.py`
Expected: `ALL TEST FILES PASS` (26 files — the 25 existing + `test_wiki.py`).

- [ ] **Step 2: Lint**

Run: `python3 tools/lint.py`
Expected: `All checks passed!`

- [ ] **Step 3: Build + self-verify**

Run: `python3 tools/build.py`
Expected: build succeeds; verify step passes; `dist/IRO_Broadcast_Package/` contains the two stubs and the refreshed `IRO_cheat_sheets.html`.

- [ ] **Step 4: Checker standalone run**

Run: `python3 tools/check-wiki-links.py`
Expected: `wiki links OK (src/docs/wiki)`.

- [ ] **Step 5: Wiki dry-run**

Run: `python3 tools/sync-wiki.py --dry-run`
Expected: link check passes, the changed pages are listed as `updated`, nothing is pushed.

No commit (nothing changed). If any gate fails, fix in the task that owns the file and re-run all gates.

---

## Spec coverage map

| Spec section | Task |
|---|---|
| 1. Wiki link checker (tool, tests, CI via suite) | Task 1 |
| 1. sync-wiki gate | Task 2 |
| 2. Legacy docs → stubs | Task 3 |
| 3. Cheat sheets refresh | Task 4 |
| 4. tailnet de-jargoning | Task 4 |
| 5. Glossary on Home | Task 5 |
| 6. Terminal in 60 seconds | Task 6 |
| 7. Checkpoints + screenshot markers (setup page + go-live) | Tasks 6, 7 |
| 8. Companion import guidance (both pages) | Tasks 6, 7 |
| 9. Handover detail + time estimates | Tasks 6 (per-step), 7 (lead time, stint source) |
| Testing (suite/lint/build/render) | Tasks 1–8 (gates in Task 8; render check in Task 4) |
