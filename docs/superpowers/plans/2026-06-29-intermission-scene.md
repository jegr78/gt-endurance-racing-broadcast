# Intermission Scene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a producer-controllable OBS **Intermission** scene — a league background graphic, looping music, and a fixed always-visible read-only broadcast-chat box — operable from the Director Panel and Companion.

**Architecture:** A dedicated OBS scene with three sources (image graphic + transparent relay-served chat browser overlay + looping audio source). The chat overlay is a new relay page `/intermission` that reuses the existing `GET /broadcast-chat/data`. The graphic follows the Sheet→`get-graphics.py` pattern; the music is a new Sheet asset downloaded by `get-media.py` (Drive direct **or** yt-dlp), with a synthesized ambient-loop placeholder as the default. Control reuses the relay-mediated `/obs/*` macros (panel) and native OBS actions (Companion).

**Tech Stack:** Pure Python 3 stdlib (relay, scripts, tools), HTML/CSS/vanilla JS (overlay page), ffmpeg (placeholder synth + yt-dlp audio), OBS scene-collection JSON.

## Global Constraints

- **Edit only under `src/`** for shipped code; `dist/` and `runtime/` are generated/gitignored — never hand-edit. `tools/` are maintainer scripts (allowed to edit: `make-placeholders.py`, new `add_intermission_scene.py`, `e2e_checks.py`).
- **All scripts and docs are English only.**
- **Never hardcode secrets or machine paths.** No real IPs/paths in tests (Tailscale test constants are `100.64.0.0/10`).
- **Python stdlib only; no new dependencies; never reintroduce `.sh`/`.bat`.**
- **Outbound HTTP** goes through `src/scripts/http_util.py` for the covered side (`racecast.py`, `ui_server.py`, `src/scripts/*`). The self-contained relay scripts `src/relay/get-graphics.py` / `get-media.py` are **exempt** and must set their **own** `User-Agent`. The Drive helpers duplicated into `get-media.py` set their own UA — do NOT move them into `src/scripts/` (that would fall under the `tests/test_http_util.py` guard).
- **Cross-platform (Windows is in the CI matrix):** build a fixed-OS absolute path with explicit forward slashes, NOT `os.path.join`; use `os.path.join` only for current-machine paths.
- **Tests are stdlib runnable scripts — no pytest.** Each test file defines `t_*` functions and ends with:
  ```python
  if __name__ == "__main__":
      for name, fn in sorted(globals().items()):
          if name.startswith("t_") and callable(fn):
              fn(); print("ok", name)
      print("ALL PASS")
  ```
  Run one file: `python3 tests/test_X.py`. Run the whole suite (what CI runs): `python3 tools/run-tests.py`.
- **Lint:** run `python3 tools/lint.py` after changing any Python file (mirrors the CI lint job; `--fix` auto-corrects).
- **Build verify before shipping:** `python3 tools/build.py` (token/secret/shell-script checks).
- **Changed a UI surface → refresh its wiki screenshot in the SAME change.** Director Panel → `src/docs/wiki/images/director-panel.png` (skill `wiki-screenshots`); Companion → `companion-page<N>-*.png` (skill `companion-screenshots`).
- **`racecast` IS released (v1.1.0) — backward-compat matters.** Do NOT break the `racecast media` / `get-media.py --which` CLI contract; keep `--which both` meaning intro+outro. Never rename/drop a flag without grepping `tools/` + `.github/`.
- **Commits** end with the trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **Branching:** one PR per Part (A, B, C). Branch from `main`; the existing `feat/intermission-scene` branch already carries the spec commit — Part A continues on it; Parts B and C branch fresh from `main` after their predecessor merges (or stack if executing back-to-back). Up-to-date branch required before merge.
- **Naming (verbatim):** OBS scene `Intermission`; image source `Intermission` → file token `__RACECAST_GRAPHICS__/Intermission.png`; browser source `Intermission Chat` → url `http://127.0.0.1:8088/intermission`; audio source `Intermission Music` → file token `__RACECAST_MEDIA__/intermission.mp3`; Sheet Assets labels `Intermission` and `Intermission Music`; overlay page key `intermission`; env override `RACECAST_INTERMISSION_MUSIC_URL`.

---

## File Structure

**Part A — relay overlay page (PR1)**
- Create `src/obs/intermission.html` — the chat-box overlay (polls `/broadcast-chat/data`, fixed-height auto-scroll box).
- Modify `src/relay/racecast-feeds.py` — `OVERLAY_PAGES`, the `/intermission` + `/intermission/override.css` routes, `OBS_PAGE_PATHS`.
- Modify `tests/test_overlay.py` — page wiring + overlay-page + override.css + OBS_PAGE_PATHS checks.
- Modify `tools/e2e_checks.py` — synthetic check `/intermission` serves 200.

**Part B — asset pipeline (PR2)**
- Modify `tools/make-placeholders.py` — synthesize `neutral-ambient-loop.mp3`.
- Create `src/assets/placeholders/neutral-ambient-loop.mp3` — committed synthetic loop (generated, then committed).
- Modify `src/scripts/placeholders.py` — `MUSIC_PLACEHOLDER`, `music_placeholder_path()`, `expected_media_from_template()`, `media_placeholder_for()`.
- Modify `src/relay/get-media.py` — `Intermission Music` resolution + Drive-or-yt-dlp download → `intermission.mp3`; duplicated Drive helpers.
- Modify `src/setup-assets.py` — fill a missing `intermission.mp3` with the music placeholder.
- Modify `src/docs/sheet-template/Assets.csv` — two new rows.
- Create `tests/test_placeholders.py` — placeholder selectors + committed-file existence.
- Create `tests/test_media.py` — music URL parse, download routing, output name, Drive-helper drift cross-check.

**Part C — OBS scene + control + demo + docs (PR3)**
- Create `tools/add_intermission_scene.py` — idempotent inserter for the scene + 3 sources.
- Modify `src/obs/GT_Endurance.json` — generated by running the tool; commit the result.
- Create `tools/intermission-demo.html` — committed demo background template (GT DEMO look).
- Modify `src/director/director-panel.html` — `INTERMISSION` macro + `Intermission Music` fader.
- Modify `src/companion/racecast-buttons.companionconfig` — `Intermission` scene button.
- Create `tests/test_intermission_scene.py` — tool idempotency + structure.
- Create/extend `tests/test_intermission.py` — panel macro + companion button content checks.
- Modify wiki pages under `src/docs/wiki/` + regenerate `director-panel.png` and `companion-page<N>-*.png`.

---

# Part A — Relay `/intermission` overlay page (PR1)

### Task A1: The chat-box overlay page + relay wiring

**Files:**
- Create: `src/obs/intermission.html`
- Modify: `src/relay/racecast-feeds.py` (`OVERLAY_PAGES`, page routes near the `splitscreen` block, `OBS_PAGE_PATHS`)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Consumes: existing `read_overlay_css(overlay_dir, page)`, `OVERLAY_PAGES`, `OBS_PAGE_PATHS`, the existing `/broadcast-chat/data` endpoint and its `{messages:[{ts,user,text,source[,tokens]}]}` shape.
- Produces: served `GET /intermission` (HTML), `GET /intermission/override.css` (per-league CSS); `"intermission"` ∈ `OVERLAY_PAGES`; `"/intermission"`, `"/intermission/override.css"` ∈ `OBS_PAGE_PATHS`.

- [ ] **Step 1: Create the overlay page**

Create `src/obs/intermission.html` with exactly this content:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Intermission — Broadcast Chat</title>
<style>
  :root {
    --ichat-w: 460px;
    --ichat-h: 640px;
    --ichat-right: 64px;
    --ichat-bottom: 96px;
    --ichat-bg: rgba(12, 16, 22, 0.55);
    --ichat-fg: #eef2f6;
    --ichat-author: #f0a868;
    --ichat-meta: #9aa3ad;
    --ichat-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  }
  html, body {
    margin: 0; padding: 0; width: 1920px; height: 1080px;
    background: transparent; overflow: hidden;
    font-family: var(--ichat-font);
  }
  /* Fixed-height, no-scrollbar chat box. Older messages scroll up and clip out. */
  #ichat {
    position: absolute;
    right: var(--ichat-right);
    bottom: var(--ichat-bottom);
    width: var(--ichat-w);
    height: var(--ichat-h);
    box-sizing: border-box;
    padding: 14px 18px;
    background: var(--ichat-bg);
    border-radius: 14px;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    color: var(--ichat-fg);
    overflow: hidden;                 /* never a scrollbar */
    display: flex;
    flex-direction: column;
  }
  #ichat-head {
    flex: 0 0 auto;
    margin-bottom: 8px;
    font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
    color: var(--ichat-meta);
  }
  /* Log fills remaining height and bottom-aligns, so new lines push older ones up. */
  #ichat-log {
    flex: 1 1 auto;
    display: flex; flex-direction: column; justify-content: flex-end;
    overflow: hidden;
  }
  #ichat-log .msg { margin-top: 6px; line-height: 1.32; font-size: 19px; overflow-wrap: anywhere; }
  #ichat-log .ts  { color: var(--ichat-meta); font-size: 12px; margin-right: 6px; }
  #ichat-log .u   { font-weight: 700; color: var(--ichat-author); margin-right: 6px; }
  #ichat-log .src { color: var(--ichat-meta); font-size: 12px; margin-left: 6px; }
  #ichat-log .emote { height: 1.2em; width: auto; vertical-align: -0.2em; }
</style>
<link rel="stylesheet" href="/intermission/override.css">
</head>
<body>
  <div id="ichat">
    <div id="ichat-head">Live Chat</div>
    <div id="ichat-log"></div>
  </div>
<script>
  "use strict";
  const POLL_MS = 4000;
  const MAX_ROWS = 50;                  // trim DOM so older lines scroll up and out
  const log = document.getElementById('ichat-log');

  function fmtTs(ts) {
    const n = Number(ts);
    if (!n) return '';
    const d = new Date(n < 1e12 ? n * 1000 : n);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  function srcBadge(source) {
    if (!source) return '';
    if (source.indexOf('twitch:') === 0) return 'TW:' + source.slice(7);
    return 'YT:' + String(source).slice(-4);
  }
  // Render one message body: text nodes + <img> emotes, never innerHTML (XSS-safe).
  function body(row, msg) {
    const toks = Array.isArray(msg.tokens) ? msg.tokens : null;
    if (!toks) { row.appendChild(document.createTextNode(msg.text || '')); return; }
    toks.forEach(function (tk) {
      if (tk && tk.t === 'emote' && typeof tk.url === 'string') {
        const img = document.createElement('img');
        img.className = 'emote'; img.src = tk.url; img.alt = tk.alt || ''; img.loading = 'lazy';
        img.onerror = function () { img.replaceWith(document.createTextNode(tk.alt || '')); };
        row.appendChild(img);
      } else if (tk && tk.t === 'text') {
        row.appendChild(document.createTextNode(tk.v || ''));
      }
    });
  }
  function render(msgs) {
    const multi = new Set(msgs.map(function (m) { return m.source; }).filter(Boolean)).size > 1;
    log.textContent = '';
    msgs.slice(-MAX_ROWS).forEach(function (msg) {
      const r = document.createElement('div'); r.className = 'msg';
      const t = document.createElement('span'); t.className = 'ts'; t.textContent = fmtTs(msg.ts);
      const u = document.createElement('span'); u.className = 'u'; u.textContent = (msg.user || 'Viewer') + ':';
      r.appendChild(t); r.appendChild(u); body(r, msg);
      if (multi && msg.source) {
        const s = document.createElement('span'); s.className = 'src'; s.textContent = srcBadge(msg.source);
        r.appendChild(s);
      }
      log.appendChild(r);
    });
  }
  async function poll() {
    try {
      const res = await fetch('/broadcast-chat/data', { cache: 'no-store' });
      if (res.ok) {
        const d = await res.json();
        render(Array.isArray(d.messages) ? d.messages : []);
      }
      // 404 (reader disabled) -> leave the box empty; NO auto-hide.
    } catch (e) { /* transient — keep the last render */ }
    setTimeout(poll, POLL_MS);
  }
  poll();
</script>
</body>
</html>
```

- [ ] **Step 2: Read the existing splitscreen wiring (learn exact helper names)**

In `src/relay/racecast-feeds.py`, locate three things and note the exact local names/helpers used:
1. `OVERLAY_PAGES = ("hud", "splitscreen")` (≈ line 612).
2. `OBS_PAGE_PATHS = (...)` (the tuple listing `/hud`, `/hud/override.css`, `/splitscreen`, `/splitscreen/override.css`).
3. The request-routing block that serves `["splitscreen"]` (the HTML file) and `["splitscreen", "override.css"]` (≈ lines 5687–5694), including how the `splitscreen.html` file path is resolved and which send helper is used (`self._send_file(...)` / a `_send_css(...)` / etc.).

Run: `grep -n "OVERLAY_PAGES\|OBS_PAGE_PATHS\|splitscreen" src/relay/racecast-feeds.py | head -40`

- [ ] **Step 3: Write the failing tests**

Append to `tests/test_overlay.py` (the `feeds` module is already loaded at the top of that file):

```python
def t_intermission_is_an_overlay_page():
    assert "intermission" in feeds.OVERLAY_PAGES


def t_intermission_in_obs_page_paths():
    assert "/intermission" in feeds.OBS_PAGE_PATHS
    assert "/intermission/override.css" in feeds.OBS_PAGE_PATHS


def t_read_overlay_css_intermission_present():
    import tempfile, os
    with tempfile.TemporaryDirectory() as od:
        with open(os.path.join(od, "intermission.css"), "w") as fh:
            fh.write("#ichat{right:0}")
        assert feeds.read_overlay_css(od, "intermission") == b"#ichat{right:0}"


def t_intermission_page_polls_broadcast_chat_and_links_override():
    import os
    path = os.path.join(ROOT, "src", "obs", "intermission.html")
    assert os.path.exists(path), "src/obs/intermission.html missing"
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert "/broadcast-chat/data" in html         # reuses the existing endpoint
    assert "/intermission/override.css" in html   # per-league override link
    assert 'id="ichat"' in html and 'id="ichat-log"' in html
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 tests/test_overlay.py`
Expected: FAIL — `AttributeError`/`AssertionError` on `intermission not in OVERLAY_PAGES` (the page-file test passes once Step 1 is done; the OVERLAY_PAGES/OBS_PAGE_PATHS tests fail until Step 5).

- [ ] **Step 5: Wire the relay**

In `src/relay/racecast-feeds.py`, mirroring the `splitscreen` patterns you read in Step 2:
1. Add `"intermission"` to `OVERLAY_PAGES`: `OVERLAY_PAGES = ("hud", "splitscreen", "intermission")`.
2. Add `"/intermission"` and `"/intermission/override.css"` to `OBS_PAGE_PATHS` (alongside the splitscreen entries).
3. In the routing block, add — directly after the `["splitscreen", "override.css"]` handler — an intermission pair using the **same** file-path resolution and send helpers the splitscreen block uses (resolve `intermission.html` the same way `splitscreen.html` is resolved):
   ```python
   if p == ["intermission"]:
       return self._send_file(<intermission_html_path>, "text/html; charset=utf-8")
   if p == ["intermission", "override.css"]:
       return self._send_css(read_overlay_css(overlay_dir, "intermission"))
   ```
   Replace `<intermission_html_path>` / `self._send_css` with the exact local variable and helper names used by the adjacent splitscreen block. (There is **no** `/intermission/data` route — the page polls `/broadcast-chat/data`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 tests/test_overlay.py`
Expected: `ALL PASS`.

- [ ] **Step 7: Lint**

Run: `python3 tools/lint.py`
Expected: no findings.

- [ ] **Step 8: Commit**

```bash
git add src/obs/intermission.html src/relay/racecast-feeds.py tests/test_overlay.py
git commit -m "feat(relay): /intermission overlay page (fixed auto-scroll broadcast-chat box)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task A2: e2e synthetic check — `/intermission` serves

**Files:**
- Modify: `tools/e2e_checks.py` (add `check_intermission_page`, register in `SYNTHETIC_CHECKS`)
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: the existing `http_request(...)` helper and `CheckResult`/`run_checks` registry in `tools/e2e_checks.py`; the enabled-relay base URL the harness already provides to synthetic checks.
- Produces: a `check_intermission_page(ctx)` callable in `SYNTHETIC_CHECKS`.

- [ ] **Step 1: Read the check pattern**

Run: `grep -n "SYNTHETIC_CHECKS\|def check_\|http_request\|CheckResult" tools/e2e_checks.py | head -40`
Note the signature of a `check_*` callable and how it returns a `CheckResult`, and how a check reaches the enabled relay base URL (mirror an existing GET check such as the HUD/status one).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_e2e.py`:

```python
def t_intermission_check_registered():
    import tools.e2e_checks as ec  # adjust import to match how test_e2e loads e2e_checks
    names = [c.__name__ for c in ec.SYNTHETIC_CHECKS]
    assert "check_intermission_page" in names
```
(Match the existing module-loading idiom already used at the top of `tests/test_e2e.py` — reuse its loader rather than a bare import if that is what the file does.)

- [ ] **Step 3: Run to verify it fails**

Run: `python3 tests/test_e2e.py`
Expected: FAIL — `check_intermission_page` not in the registry.

- [ ] **Step 4: Implement the check**

In `tools/e2e_checks.py`, add (mirroring an existing GET check exactly for arguments/return):

```python
def check_intermission_page(ctx):
    """GET /intermission serves the chat-box overlay page."""
    status, body = http_request(ctx.base_url + "/intermission")
    ok = status == 200 and 'id="ichat"' in body
    return CheckResult("intermission_page", ok,
                       f"status={status}" if not ok else "served")
```
Adapt `ctx.base_url`, `http_request`'s return shape, and the `CheckResult` constructor to the real signatures from Step 1. Then add `check_intermission_page` to the `SYNTHETIC_CHECKS` list.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 tests/test_e2e.py`
Expected: `ALL PASS`.

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add tools/e2e_checks.py tests/test_e2e.py
git commit -m "test(e2e): assert /intermission overlay page serves 200

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Full suite + open PR1**

Run: `python3 tools/run-tests.py` → all green.
Open PR1 from `feat/intermission-scene` (`feat(relay): intermission overlay page`). Body ends with:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

# Part B — Asset pipeline: music + ambient placeholder (PR2)

> Branch fresh from `main`: `git checkout main && git pull && git checkout -b feat/intermission-music`.

### Task B1: Synthesize the ambient-loop placeholder

**Files:**
- Modify: `tools/make-placeholders.py`
- Create (generated, then committed): `src/assets/placeholders/neutral-ambient-loop.mp3`

**Interfaces:**
- Produces: a committed `src/assets/placeholders/neutral-ambient-loop.mp3` (seamless ~24 s synthetic loop, low volume).

- [ ] **Step 1: Add the synth function + call it from `main`**

In `tools/make-placeholders.py`, add after `write_mp4`:

```python
def write_music_loop(path, seconds=24):
    """A seamless, low-volume synthetic ambient loop (royalty-free because
    generated). Integer-Hz partials over an integer duration loop click-free."""
    fc = (f"sine=frequency=110:duration={seconds},"
          f"sine=frequency=164:duration={seconds},"
          f"sine=frequency=220:duration={seconds}")
    cmd = ["ffmpeg", "-y",
           "-f", "lavfi", "-i", f"sine=frequency=110:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=164:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
           "-filter_complex",
           "[0][1][2]amix=inputs=3:normalize=0,volume=0.10,lowpass=f=800[a]",
           "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", path]
    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("ERROR: ffmpeg not found (brew install ffmpeg).")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: ffmpeg failed: {e}")
    print(f"OK -> {path} ({os.path.getsize(path)} bytes)")
```
(The unused `fc` line is not needed — delete it; the three explicit `-i` inputs are what the command uses.)

In `main()`, after the `write_mp4(...)` call, add:

```python
    write_music_loop(os.path.join(OUT_DIR, "neutral-ambient-loop.mp3"), a.seconds if a.seconds >= 8 else 24)
```
Leave `--seconds` default at 5 for the video clip but pass a sane loop length (≥8 s) for the music.

- [ ] **Step 2: Generate the asset**

Run: `python3 tools/make-placeholders.py`
Expected: writes `src/assets/placeholders/transparent-1080p.png`, `neutral-5s-1080p.mp4`, and `neutral-ambient-loop.mp3`.

- [ ] **Step 3: Sanity-check the file**

Run: `file src/assets/placeholders/neutral-ambient-loop.mp3 && ls -l src/assets/placeholders/neutral-ambient-loop.mp3`
Expected: an `Audio file ... MPEG ... layer III` of a few hundred KB.

- [ ] **Step 4: Commit**

```bash
git add tools/make-placeholders.py src/assets/placeholders/neutral-ambient-loop.mp3
git commit -m "feat(assets): synthesize neutral ambient-loop music placeholder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task B2: Placeholder selectors for media

**Files:**
- Modify: `src/scripts/placeholders.py`
- Create: `tests/test_placeholders.py`

**Interfaces:**
- Consumes: existing `_placeholders_dir()`, `media_placeholder_path()`, `fill_missing(...)`.
- Produces: `MUSIC_PLACEHOLDER`, `music_placeholder_path()`, `expected_media_from_template(text) -> [name]`, `media_placeholder_for(name) -> path|None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_placeholders.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for the neutral-placeholder selectors. Run: python3 tests/test_placeholders.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import placeholders as ph


def t_music_placeholder_file_committed():
    p = ph.music_placeholder_path()
    assert p and os.path.isfile(p), "neutral-ambient-loop.mp3 not committed under src/assets/placeholders/"
    assert os.path.getsize(p) > 1000


def t_media_placeholder_for_selects_by_extension():
    music = ph.music_placeholder_path()
    video = ph.media_placeholder_path()
    assert ph.media_placeholder_for("intermission.mp3") == music
    assert ph.media_placeholder_for("intro.mp4") == video
    assert ph.media_placeholder_for("outro.mp4") == video


def t_expected_media_from_template_finds_all():
    raw = ('"file":"__RACECAST_MEDIA__/intro.mp4" ... '
           '"file":"__RACECAST_MEDIA__/outro.mp4" ... '
           '"file":"__RACECAST_MEDIA__/intermission.mp3"')
    assert ph.expected_media_from_template(raw) == ["intermission.mp3", "intro.mp4", "outro.mp4"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_placeholders.py`
Expected: FAIL — `module 'placeholders' has no attribute 'music_placeholder_path'`.

- [ ] **Step 3: Implement the selectors**

In `src/scripts/placeholders.py`:
- After `MEDIA_PLACEHOLDER = "neutral-5s-1080p.mp4"` add:
  ```python
  MUSIC_PLACEHOLDER = "neutral-ambient-loop.mp3"
  ```
- After `_GRAPHICS_REF_RE = ...` add:
  ```python
  _MEDIA_REF_RE = re.compile(r"__RACECAST_MEDIA__/([^\"\\]+\.(?:mp4|mp3|m4a|wav|ogg))")
  ```
- After `media_placeholder_path()` add:
  ```python
  def music_placeholder_path():
      """Absolute path of the bundled synthetic ambient loop, or None when absent."""
      p = os.path.join(_placeholders_dir(), MUSIC_PLACEHOLDER)
      return p if os.path.isfile(p) else None


  def media_placeholder_for(name):
      """Pick the right bundled placeholder for a media filename: the ambient loop
      for an audio (.mp3) file, the neutral clip for everything else."""
      return music_placeholder_path() if name.lower().endswith(".mp3") else media_placeholder_path()
  ```
- After `expected_graphics_from_template(text)` add:
  ```python
  def expected_media_from_template(text):
      """Sorted unique '<name>' from every __RACECAST_MEDIA__/<name> reference in
      the (raw JSON) collection text (intro.mp4 / outro.mp4 / intermission.mp3 / …)."""
      return sorted(set(_MEDIA_REF_RE.findall(text)))
  ```

- [ ] **Step 4: Run to verify pass**

Run: `python3 tests/test_placeholders.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/placeholders.py tests/test_placeholders.py
git commit -m "feat(placeholders): music placeholder + media-template selectors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task B3: `get-media.py` — download the intermission music (Drive or yt-dlp)

**Files:**
- Modify: `src/relay/get-media.py`
- Test: `tests/test_media.py` (create)

**Interfaces:**
- Consumes: existing `resolve_urls`, `run_download`, `external_tool_env`, `media_dir`, `placeholders`.
- Produces: pure helpers `is_drive_url(url)`, `drive_id(url)`, `to_download_url(file_id)`, `music_download_kind(url) -> "drive"|"ytdlp"|"invalid"`, `build_music_cmd(url, out_path, cookies=None) -> argv`, `music_url_from_csv(rows) -> url|None`; behavior: `racecast media` (default `--which all`) also writes `intermission.mp3`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_media.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for get-media intermission-music handling. Run: python3 tests/test_media.py"""
import importlib.util, inspect, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))  # services, placeholders


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


media = _load("get_media", os.path.join("src", "relay", "get-media.py"))
graphics = _load("get_graphics", os.path.join("src", "relay", "get-graphics.py"))

DRIVE = "https://drive.google.com/file/d/ABC123def456/view?usp=sharing"
YT = "https://www.youtube.com/watch?v=abc12345"


def t_music_url_from_csv_picks_value():
    rows = [["Overlay", "https://drive.google.com/file/d/x/view"],
            ["Intermission Music", DRIVE],
            ["Intro Video", YT]]
    assert media.music_url_from_csv(rows) == DRIVE


def t_music_download_kind():
    assert media.music_download_kind(DRIVE) == "drive"
    assert media.music_download_kind(YT) == "ytdlp"
    assert media.music_download_kind("file:///etc/passwd") == "invalid"
    assert media.music_download_kind("ftp://x/y") == "invalid"


def t_build_music_cmd_is_audio_extract_and_guarded():
    argv = media.build_music_cmd(YT, "/out/intermission.mp3")
    assert argv[0] == "yt-dlp"
    assert "-x" in argv
    i = argv.index("--audio-format"); assert argv[i + 1] == "mp3"
    assert "--" in argv and argv.index("--") < argv.index(YT)   # flag-injection guard
    assert argv[-1] == YT


def t_build_music_cmd_output_stem_is_intermission():
    argv = media.build_music_cmd(YT, "/out/intermission.mp3")
    o = argv.index("-o")
    assert os.path.basename(argv[o + 1]).startswith("intermission.")


def t_drive_helpers_match_get_graphics():
    for fn in ("is_drive_url", "drive_id", "to_download_url"):
        assert inspect.getsource(getattr(media, fn)) == inspect.getsource(getattr(graphics, fn)), \
            f"{fn} drifted between get-media and get-graphics"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 tests/test_media.py`
Expected: FAIL — `module 'get_media' has no attribute 'music_url_from_csv'`.

- [ ] **Step 3: Implement in `src/relay/get-media.py`**

a) Copy the Drive helpers **verbatim** from `src/relay/get-graphics.py` (so the drift cross-check passes) — `is_drive_url`, `drive_id`, `to_download_url` — and add `from urllib.parse import urlparse` to the existing import line. Place them after `MEDIA_LABELS`.

b) Add the music constants + pure helpers:

```python
MUSIC_LABEL = "intermission music"   # Assets-tab label
MUSIC_KEY = "intermission"           # output basename stem -> intermission.mp3


def music_url_from_csv(rows):
    """Assets-tab rows -> the Intermission-Music URL (Drive link OR YouTube/URL),
    located by a label cell == MUSIC_LABEL (trimmed, case-insensitive); value is
    the next non-empty cell. None if absent."""
    for row in rows:
        for i, cell in enumerate(row):
            if (cell or "").strip().lower() != MUSIC_LABEL:
                continue
            for nxt in row[i + 1:]:
                v = (nxt or "").strip()
                if v:
                    return v
    return None


def music_download_kind(url):
    """'drive' (direct download), 'ytdlp' (audio extract), or 'invalid'."""
    if not (url or "").startswith(("http://", "https://")):
        return "invalid"
    return "drive" if (is_drive_url(url) and drive_id(url)) else "ytdlp"


def build_music_cmd(url, out_path, cookies=None):
    """Argv to extract audio to an mp3 at out_path's dir, stem 'intermission'.
    `--` precedes the URL so a sheet cell starting with '-' cannot be a flag."""
    stem = os.path.join(os.path.dirname(out_path), "intermission.%(ext)s")
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--no-warnings", "-o", stem]
    if cookies and os.path.exists(cookies):
        cmd += ["--cookies", cookies]
    cmd += ["--", url]
    return cmd
```

c) Add a binary Drive download + the music dispatcher (next to `download`):

```python
def download_drive_file(url, out_path, timeout=120):
    """GET a Drive file to out_path (binary). Handles the large-file confirm
    interstitial. Atomic write. (Music variant of get-graphics.download — no PNG check.)"""
    req = Request(url, headers={"User-Agent": "racecast-media/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read()
    if ctype.startswith("text/html"):
        import re as _re
        m = _re.search(rb"confirm=([0-9A-Za-z_-]+)", data)
        if not m:
            raise RuntimeError("Drive returned an HTML interstitial with no confirm token")
        req2 = Request(url + "&confirm=" + m.group(1).decode(),
                       headers={"User-Agent": "racecast-media/1.0"})
        with urlopen(req2, timeout=timeout) as resp2:
            data = resp2.read()
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)


def download_music(url, out_path, cookies=None):
    """Download intermission music to out_path (intermission.mp3). Drive link ->
    direct download; otherwise yt-dlp audio extraction. Retries the transient
    yt-dlp failure like the video path."""
    kind = music_download_kind(url)
    if kind == "invalid":
        raise ValueError(f"refusing non-http(s) music URL: {url!r}")
    if kind == "drive":
        download_drive_file(to_download_url(drive_id(url)), out_path)
    else:
        run_download(build_music_cmd(url, out_path, cookies), env=external_tool_env())
```

d) Wire it into `main()` so `racecast media` fetches it:
- Change `--which` choices to `["intro", "outro", "music", "both", "all"]` with `default="all"`. Map: `both` → `{intro, outro}` (unchanged back-compat); `all` → `{intro, outro}` + music; `music` → music only; `intro`/`outro` → that clip only. Keep the video set in `which` and a separate boolean `want_music = a.which in ("all", "music")`.
- Resolve the music URL after the video URLs: `music_url = a.music_url or os.environ.get("RACECAST_INTERMISSION_MUSIC_URL") or (music_url_from_csv(list(csv.reader(io.StringIO(csv_text)))) if csv_text else None)`. Add CLI flag `--music-url` and include music in the `need_sheet` decision.
- In the download section, when `want_music`: `out_music = os.path.join(a.out, "intermission.mp3")`, then try `download_music(music_url, out_music, cookies)` with the same `FileNotFoundError`/`TimeoutExpired`/`Exception` handling pattern as the clips; if no `music_url`, print a WARNING and let the placeholder seed it (do NOT add it to `failed`, since the ambient placeholder is an acceptable default).

e) Update `seed_missing_media` to use the per-file selector so `intermission.mp3` gets the music placeholder:

```python
def seed_missing_media(out_dir, which, want_music=False):
    """Drop the right neutral placeholder for any missing intro.mp4/outro.mp4 (in
    `which`) and intermission.mp3 (when want_music). Returns sorted names written."""
    written = []
    for k in sorted(which):
        written += placeholders.fill_missing([f"{k}.mp4"], out_dir, placeholders.media_placeholder_for(f"{k}.mp4"))
    if want_music:
        written += placeholders.fill_missing(["intermission.mp3"], out_dir,
                                             placeholders.media_placeholder_for("intermission.mp3"))
    return sorted(written)
```
Update the `seed_missing_media(a.out, which)` call in `main()` to pass `want_music`.

f) Update the module docstring to mention the `Intermission Music` label and `intermission.mp3`.

- [ ] **Step 4: Run the tests to verify pass**

Run: `python3 tests/test_media.py`
Expected: `ALL PASS`. (If the drift cross-check fails, the copied Drive helpers differ from `get-graphics.py` — copy them character-for-character.)

- [ ] **Step 5: Verify the CLI contract is intact**

Run: `python3 src/relay/get-media.py --help`
Expected: `--which` lists `intro, outro, music, both, all`, default `all`; `--music-url` present. Confirm `--which both` still means intro+outro.

Run: `grep -rn "\-\-which" tools/ .github/` — confirm no caller passes a value you removed (none should; you only added choices).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/get-media.py tests/test_media.py
git commit -m "feat(media): download Intermission Music (Drive or yt-dlp) -> intermission.mp3

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task B4: `setup-assets.py` fills a missing `intermission.mp3`; Assets template

**Files:**
- Modify: `src/setup-assets.py`
- Modify: `src/docs/sheet-template/Assets.csv`
- Test: `tests/test_setup.py` (extend) **or** `tests/test_placeholders.py` — see Step 2.

**Interfaces:**
- Consumes: `placeholders.expected_media_from_template`, `placeholders.media_placeholder_for`, `placeholders.fill_missing`.
- Produces: localized collections seed `intermission.mp3` with the ambient placeholder when the file is absent.

- [ ] **Step 1: Read the current media-fill block**

Run: `grep -n "MEDIA_TOKEN\|media\|placeholder\|intro\|outro" src/setup-assets.py | head -40`
Find where, when `MEDIA_TOKEN` is present, it fills missing `intro.mp4`/`outro.mp4` (the `placeholders.fill_missing(...)` call for media).

- [ ] **Step 2: Write the failing test**

The cleanest seam is the pure `expected_media_from_template` already tested in B2. Add a focused check that the **template collection references `intermission.mp3`** (it will, after Part C regenerates the JSON — but Part B merges first, so guard with a skip): instead, assert the setup-assets media fill is driven by the template scan. Add to `tests/test_setup.py` (match its module-loading idiom):

```python
def t_setup_media_fill_uses_template_scan():
    import placeholders as ph
    raw = '"file":"__RACECAST_MEDIA__/intermission.mp3"'
    assert "intermission.mp3" in ph.expected_media_from_template(raw)
    assert ph.media_placeholder_for("intermission.mp3") == ph.music_placeholder_path()
```
(This locks the contract setup-assets relies on without needing the regenerated collection in this PR.)

- [ ] **Step 3: Run to verify it passes or fails appropriately**

Run: `python3 tests/test_setup.py`
Expected: PASS for the new assertion only if B2 is merged/available; it exercises `placeholders`, which Part B provides. If `tests/test_setup.py` cannot import `placeholders`, add `sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))` near its top (match the existing pattern).

- [ ] **Step 4: Implement the media fill change**

In `src/setup-assets.py`, in the `MEDIA_TOKEN`-present branch, replace the hardcoded intro/outro fill with a template-driven fill so any referenced media (incl. `intermission.mp3`) is seeded with the correct placeholder:

```python
        for name in placeholders.expected_media_from_template(raw):
            filled = placeholders.fill_missing([name], a.media, placeholders.media_placeholder_for(name))
            if filled:
                print(f"  NOTE: wrote neutral placeholder for missing media in {a.media}: {', '.join(filled)}")
```
(Keep the existing intro/outro behavior intact — this generalizes it. `raw` is the already-read collection text used for the graphics scan; reuse it.)

- [ ] **Step 5: Add the Assets template rows**

In `src/docs/sheet-template/Assets.csv`, insert before the `Intro Video` row:

```
Intermission,<paste a Google Drive share link>
Intermission Music,<paste a Google Drive share link OR a YouTube/URL>
```

- [ ] **Step 6: Run tests + lint + commit**

```bash
python3 tests/test_setup.py
python3 tools/lint.py
git add src/setup-assets.py src/docs/sheet-template/Assets.csv tests/test_setup.py
git commit -m "feat(setup): seed intermission.mp3 placeholder + Assets template rows

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Full suite + PR2**

Run: `python3 tools/run-tests.py` → green. Run `python3 tools/build.py` → verify passes.
Open PR2 (`feat(media): intermission music asset pipeline`).

---

# Part C — OBS scene, control surfaces, demo, docs (PR3)

> Branch fresh from `main` after PR1+PR2 merge: `git checkout main && git pull && git checkout -b feat/intermission-scene-obs`. Part C is functionally complete only with A (the `/intermission` page) and B (`intermission.mp3` + placeholder) present.

### Task C1: `add_intermission_scene.py` + regenerate the OBS collection

**Files:**
- Create: `tools/add_intermission_scene.py`
- Modify (generated): `src/obs/GT_Endurance.json`
- Test: `tests/test_intermission_scene.py`

**Interfaces:**
- Consumes: the existing `src/obs/GT_Endurance.json` (templates: `Intro` scene, the HUD `browser_source`, the `Intro Video` `ffmpeg_source`, the `Thumbnail` `image_source`).
- Produces: `add_intermission_scene(d) -> bool` (idempotent), and the regenerated collection containing scene `Intermission` with sources `Intermission`, `Intermission Chat`, `Intermission Music`.

- [ ] **Step 1: Read the existing OBS structure**

Run:
```
grep -n '"name": "Intro"\|"name": "Intro Video"\|"name": "Thumbnail"\|browser_source\|"id": "scene"\|scene_collection\|"current_scene"\|"order"\|"127.0.0.1:8088/hud"' src/obs/GT_Endurance.json | head -60
```
Identify: the `Intro` scene object (skeleton + its `settings.items`), the `Intro Video` `ffmpeg_source` (loop/audio settings to copy), the HUD `browser_source` (the `127.0.0.1:8088/hud` template), the `Thumbnail` `image_source`, and **how scenes are registered in the collection** (the top-level scene list / order array that makes a scene appear in OBS — note its exact key, e.g. `"order"` / `"scene_order"`). Also study `tools/add_standby_cover.py` for the deep-copy idiom.

- [ ] **Step 2: Write the failing test**

Create `tests/test_intermission_scene.py`:

```python
#!/usr/bin/env python3
"""Stdlib checks for tools/add_intermission_scene.py. Run: python3 tests/test_intermission_scene.py"""
import copy, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load("add_intermission_scene", os.path.join("tools", "add_intermission_scene.py"))


def _collection():
    with open(os.path.join(ROOT, "src", "obs", "GT_Endurance.json"), encoding="utf-8") as fh:
        return json.load(fh)


def t_adds_scene_and_three_sources():
    d = copy.deepcopy(_collection())
    # start from a collection WITHOUT the scene to prove the tool creates it
    d["sources"] = [s for s in d["sources"]
                    if s.get("name") not in ("Intermission", "Intermission Chat", "Intermission Music")]
    changed = tool.add_intermission_scene(d)
    assert changed is True
    names = {s.get("name") for s in d["sources"]}
    assert {"Intermission", "Intermission Chat", "Intermission Music"} <= names
    scene = next(s for s in d["sources"] if s.get("name") == "Intermission" and s.get("id") == "scene")
    item_names = {it.get("name") for it in scene["settings"]["items"]}
    assert {"Intermission", "Intermission Chat", "Intermission Music"} <= item_names


def t_tokens_and_url_are_correct():
    d = copy.deepcopy(_collection())
    tool.add_intermission_scene(d)
    img = next(s for s in d["sources"] if s.get("name") == "Intermission" and s.get("id") != "scene")
    assert img["settings"]["file"] == "__RACECAST_GRAPHICS__/Intermission.png"
    music = next(s for s in d["sources"] if s.get("name") == "Intermission Music")
    assert music["settings"]["file"] == "__RACECAST_MEDIA__/intermission.mp3"
    assert music["settings"].get("looping") is True
    chat = next(s for s in d["sources"] if s.get("name") == "Intermission Chat")
    assert chat["settings"]["url"] == "http://127.0.0.1:8088/intermission"


def t_idempotent():
    d = copy.deepcopy(_collection())
    tool.add_intermission_scene(d)
    assert tool.add_intermission_scene(d) is False


def t_committed_collection_already_has_scene():
    # after Step 4 regenerates + commits, the shipped template must contain it
    names = {s.get("name") for s in _collection()["sources"]}
    assert {"Intermission", "Intermission Chat", "Intermission Music"} <= names


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 tests/test_intermission_scene.py`
Expected: FAIL — `tools/add_intermission_scene.py` does not exist.

- [ ] **Step 4: Implement the tool**

Create `tools/add_intermission_scene.py`. Model the deep-copy approach on `tools/add_standby_cover.py`. It must:
1. Return `False` if a source named `Intermission` (the scene) already exists.
2. Deep-copy the `Intro` scene object as the scene skeleton; rename to `Intermission`, new uuid `cccccccc-0000-4000-8000-000000000001`, and empty its `settings.items`, then append three items.
3. Deep-copy the `Thumbnail` image source → name `Intermission` (uuid `cccccccc-0000-4000-8000-000000000002`), `settings.file = "__RACECAST_GRAPHICS__/Intermission.png"`.
4. Deep-copy the HUD `browser_source` → name `Intermission Chat` (uuid `cccccccc-0000-4000-8000-000000000003`), `settings.url = "http://127.0.0.1:8088/intermission"`, width 1920 / height 1080, transparent.
5. Deep-copy the `Intro Video` `ffmpeg_source` → name `Intermission Music` (uuid `cccccccc-0000-4000-8000-000000000004`), `settings.file = "__RACECAST_MEDIA__/intermission.mp3"`, keep `looping/restart_on_activate/close_when_inactive` and the audio mixers.
6. Append the three matching **scene items** to the `Intermission` scene's `settings.items` (bottom→top: image, chat, music), the image full-screen (`pos {0,0}`, `bounds_type 2`, `bounds {1920,1080}`), each with a fresh `id` (`max(existing id)+1`).
7. Register the new scene in the collection's scene order/list (the key you identified in Step 1) so OBS shows it.
8. Provide a `main(path)` that loads, calls `add_intermission_scene`, and writes back with `json.dump(d, fh, ensure_ascii=False, indent=4)` — mirroring `add_standby_cover.py`'s `main`.

Use the exact source-object/scene-item key names you observed in the real JSON (do not invent keys). The header docstring must follow `add_standby_cover.py`'s style.

- [ ] **Step 5: Run the unit tests (pre-regeneration)**

Run: `python3 tests/test_intermission_scene.py`
Expected: the first three tests PASS; `t_committed_collection_already_has_scene` FAILS (the shipped JSON not yet regenerated).

- [ ] **Step 6: Regenerate the committed collection**

Run: `python3 tools/add_intermission_scene.py src/obs/GT_Endurance.json`
Expected: prints that it added `Intermission`. Re-run once → prints "already present — skip" (idempotency proof).

- [ ] **Step 7: Run the full test again**

Run: `python3 tests/test_intermission_scene.py`
Expected: `ALL PASS`.

- [ ] **Step 8: Lint + build verify + commit**

```bash
python3 tools/lint.py
python3 tools/build.py          # tokenization / no-secrets verify over the regenerated collection
git add tools/add_intermission_scene.py src/obs/GT_Endurance.json tests/test_intermission_scene.py
git commit -m "feat(obs): add Intermission scene (graphic + chat overlay + looping music)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C2: Demo background graphic + Sheet handoff

**Files:**
- Create: `tools/intermission-demo.html`
- Produce (local, gitignored): `runtime/demo/graphics/Intermission.png`

**Interfaces:**
- Produces: a committed, reproducible demo background template and a locally-rendered PNG for UAT + wiki screenshots.

- [ ] **Step 1: Author the demo template**

Create `tools/intermission-demo.html` — a 1920×1080 page in the GT DEMO look matching `Standby Cover.png` (dark `#11161d` background, teal `#2aa7c7` top/bottom accent bars, the demo logo glyph, a large italic `INTERMISSION` headline, and a smaller `WE'LL BE RIGHT BACK` subline in teal). Inline CSS only; no external assets (embed the logo as inline SVG so the capture is self-contained). Keep it visually consistent with the existing demo graphics.

- [ ] **Step 2: Render to the demo runtime graphics dir**

Capture it at exactly 1920×1080 to `runtime/demo/graphics/Intermission.png`. Use the Playwright MCP the `wiki-screenshots` skill already uses: open `tools/intermission-demo.html`, set viewport 1920×1080, full-page screenshot → save as `runtime/demo/graphics/Intermission.png`. (This file lives under gitignored `runtime/` — it is NOT committed.)

- [ ] **Step 3: Verify**

Run: `file "runtime/demo/graphics/Intermission.png"`
Expected: `PNG image data, 1920 x 1080`.

- [ ] **Step 4: Commit the template + record the handoff**

```bash
git add tools/intermission-demo.html
git commit -m "chore(demo): committed Intermission background template (GT DEMO look)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**HANDOFF (manual, maintainer-owned — cannot be automated):** upload the rendered PNG to the **demo Google Sheet's Drive** and add two `Assets` tab rows — `Intermission` → that Drive link, and `Intermission Music` → a Drive MP3 or a royalty-free YouTube link. Until then, the demo Intermission scene shows the transparent graphic placeholder + the ambient-loop music placeholder. Surface this in the PR description as a checkbox.

### Task C3: Director Panel — INTERMISSION macro + music fader

**Files:**
- Modify: `src/director/director-panel.html` (`CONFIG.macros`, `CONFIG.audio`)
- Test: `tests/test_intermission.py` (create)

**Interfaces:**
- Consumes: the existing `CONFIG.macros` (scene/mute step shape) and `CONFIG.audio` (label/input shape) and `runMacro`/`obsStatePoll`.
- Produces: a macro labelled `INTERMISSION` (scene `Intermission`, mutes the feeds) and an audio fader for input `Intermission Music`.

- [ ] **Step 1: Read the existing INTRO/OUTRO macro + an audio entry**

Run: `grep -n "macros\|INTRO\|OUTRO\|STANDBY\|audio:\|Discord Audio Capture\|Feed A" src/director/director-panel.html | head -40`
Note the exact object shape of the `INTRO` macro (keys for scene + mute list + optional rc label) and an `audio` entry (`{label, input}`).

- [ ] **Step 2: Write the failing test**

Create `tests/test_intermission.py`:

```python
#!/usr/bin/env python3
"""Content checks for the Intermission control surfaces. Run: python3 tests/test_intermission.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def t_panel_has_intermission_macro():
    html = _read(os.path.join("src", "director", "director-panel.html"))
    assert "INTERMISSION" in html
    assert "Intermission" in html            # scene name in the macro
    assert "Intermission Music" in html      # audio fader input


def t_companion_has_intermission_button():
    raw = _read(os.path.join("src", "companion", "racecast-buttons.companionconfig"))
    cfg = json.loads(raw)                     # must stay valid JSON
    assert "Intermission" in raw              # a button/action references the scene


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 tests/test_intermission.py`
Expected: FAIL — `INTERMISSION` not in the panel HTML.

- [ ] **Step 4: Implement the panel changes**

In `src/director/director-panel.html`:
- Add to `CONFIG.macros` an entry mirroring `INTRO`'s exact shape, e.g.:
  ```js
  {label:"INTERMISSION", scene:"Intermission", show:[], hide:[],
   mute:["Feed A","Feed B","Discord Audio Capture"]},
  ```
  (Match the real key names from Step 1 — if `INTRO` uses `unmute`/`rc`, include the same keys with appropriate values; leave `rc` unset/empty.)
- Add to `CONFIG.audio` a fader entry: `{label:"Intermission", input:"Intermission Music"}` (match the real entry shape).

- [ ] **Step 5: Run the panel test (companion test still fails — that is Task C4)**

Run: `python3 tests/test_intermission.py`
Expected: `t_panel_has_intermission_macro` PASS; `t_companion_has_intermission_button` FAIL (until C4).

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/director/director-panel.html tests/test_intermission.py
git commit -m "feat(panel): INTERMISSION scene macro + music fader

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C4: Companion — Intermission scene button

**Files:**
- Modify: `src/companion/racecast-buttons.companionconfig`
- Test: `tests/test_intermission.py` (the companion assertion from C3)

**Interfaces:**
- Consumes: the existing `Intro` button object (native OBS `set_scene` + `set_source_mute` actions + the program-scene feedback) as the template.
- Produces: an `Intermission` button switching to the `Intermission` scene and muting the feeds.

- [ ] **Step 1: Locate the Intro button object**

Run: `grep -n '"Intro"\|set_scene\|set_source_mute\|"text":' src/companion/racecast-buttons.companionconfig | head -40`
Find the Intro button (its `set_scene` → `Intro` action, the mute actions, the scene-program feedback) and an empty button slot to place the new one (or a free position on the same page as Intro/Outro).

- [ ] **Step 2: Confirm the test currently fails**

Run: `python3 tests/test_intermission.py`
Expected: `t_companion_has_intermission_button` FAIL.

- [ ] **Step 3: Add the button**

Deep-copy the `Intro` button object into a free slot and change only: the `set_scene` target → `Intermission`; the button `text` → `Intermission`; the program-scene feedback's scene → `Intermission`. Keep the `set_source_mute` actions on `Feed A`/`Feed B`/`Discord Audio Capture` as-is. Preserve valid JSON (no trailing commas; unique button coordinates/id).

- [ ] **Step 4: Run the test to verify pass + JSON validity**

Run: `python3 tests/test_intermission.py`
Expected: `ALL PASS` (the `json.loads` guard proves the config is still valid).

- [ ] **Step 5: Commit**

```bash
git add src/companion/racecast-buttons.companionconfig tests/test_intermission.py
git commit -m "feat(companion): Intermission scene button (mirrors Intro/Outro)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C5: Refresh wiki screenshots (hard rule — same change)

**Files:**
- Modify: `src/docs/wiki/images/director-panel.png`
- Modify: `src/docs/wiki/images/companion-page<N>-*.png` (the page holding the new button)

- [ ] **Step 1: Regenerate the Director Panel screenshot**

Invoke the `wiki-screenshots` skill. Stand up a local dev build (the `demo` profile + `tools/obs-sim.py` OBS stand-in, per the skill's reproducible recipe), open the Director Panel, and capture the element matching the existing `director-panel.png` framing so the new `INTERMISSION` macro + `Intermission Music` fader are visible. Save over `src/docs/wiki/images/director-panel.png`.

- [ ] **Step 2: Regenerate the Companion page screenshot**

Invoke the `companion-screenshots` skill to recapture the page that now holds the `Intermission` button. Save over the matching `companion-page<N>-*.png`.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/images/director-panel.png src/docs/wiki/images/companion-page*-*.png
git commit -m "docs(wiki): refresh panel + companion screenshots for Intermission

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C6: Docs — wiki text + Assets

**Files:**
- Modify: `src/docs/wiki/OBS-Setup.md`, `Configuration.md`, `Director.md`, `Companion.md`, `Sheet-Template.md`, `Relay-Mode.md` (only those that describe scenes/assets/controls)
- Test: `tests/test_wiki.py`

**Interfaces:**
- Produces: documentation of the Intermission scene, its two Sheet assets (`Intermission`, `Intermission Music`), and the panel/Companion controls. The mechanism only — do NOT invent broadcast procedure (who goes on air when); state that the team decides usage.

- [ ] **Step 1: Add the documentation**

In each relevant wiki page, add a short section describing: the `Intermission` scene (background graphic + looping music + read-only broadcast-chat box), the two `Assets` rows (`Intermission` graphic; `Intermission Music` accepting a Drive link or a YouTube/URL), the Director Panel `INTERMISSION` macro + music fader, and the Companion `Intermission` button. Keep operator-first ordering (Control Center / panel before raw CLI). Do not assert when to use it — that is the team's call.

- [ ] **Step 2: Validate wiki links/anchors**

Run: `python3 tests/test_wiki.py`
Expected: `ALL PASS` (no broken links/anchors introduced).

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/*.md
git commit -m "docs(wiki): document the Intermission scene + assets + controls

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Full suite + build + PR3**

Run: `python3 tools/run-tests.py` → all green. Run `python3 tools/build.py` → verify passes.
Open PR3 (`feat(obs): Intermission scene + Director Panel/Companion control`), with the C2 Sheet-handoff checkbox in the body. Body ends with:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Spec §1 OBS scene → Task C1 (+ demo graphic C2). ✓
- Spec §2 relay `/intermission` page + box behavior + override.css + OBS_PAGE_PATHS → Task A1. ✓
- Spec §3 music (Drive+yt-dlp) + ambient placeholder + placeholders mapping + setup-assets → Tasks B1–B4. ✓
- Spec §4 demo graphic + Sheet handoff → Task C2. ✓
- Spec §5 Director Panel macro + Companion button → Tasks C3, C4. ✓
- Spec §6 Assets.csv + wiki + screenshots + tests → Tasks B4, C5, C6 + per-task tests. ✓
- Spec "no new data endpoint / no new public surface" → A1 reuses `/broadcast-chat/data` (no new route besides the loopback page + override.css). ✓

**Placeholder scan:** No "TBD/TODO". Two deliberate "read the existing pattern" steps (A1.2, C1.1, C4.1) are required because the exact local helper/JSON-key names live in 6000-line files the engineer must match; each is paired with concrete code to add. Acceptable — this is "follow established patterns", not a missing spec.

**Type consistency:** Names are consistent across tasks — `expected_media_from_template`/`media_placeholder_for`/`music_placeholder_path` (B2) are consumed verbatim in B3/B4; `add_intermission_scene(d)->bool` (C1) matches its tests; the verbatim-copied Drive helpers are drift-checked (B3.t_drive_helpers_match_get_graphics).
