# Broadcast-chat compose popup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Write in chat ↗" button to the broadcast-chat card on the three console pages that opens the native YouTube/Twitch popout chat in a small window, so crew can post under their own account — with no relay write path.

**Architecture:** Reading stays anonymous/read-only. The only backend change is one read-only `target` field (`{platform, url}`) added to the existing `BroadcastChatStore.data()` payload, computed each supervisor cycle from the already-resolved live set. The front-end renders a conditional button that `window.open`s the native popout. No new endpoint, no new public surface.

**Tech Stack:** Pure Python stdlib (relay + pure helpers in `src/scripts/broadcast_chat.py`); vanilla JS in the three console HTML pages. Tests are stdlib runnable scripts (no pytest).

## Global Constraints

- Edit only under `src/` (plus `tests/`, `docs/`, `CLAUDE.md`, and `src/docs/wiki/images/`). Never touch `dist/`/`runtime/`.
- All scripts and docs are English only.
- Pure Python stdlib — no new dependencies.
- **No new outbound HTTP** is introduced (the popup is client-side navigation; the relay change is pure/in-memory) — the `http_util` UA guard is not implicated.
- **No new HTTP endpoint and no new public/Funnel surface** — `target` rides the existing `/broadcast-chat/data` (tailnet) and `/console/broadcast-chat/data` (Funnel) readers of `broadcast_chat_store.data()`.
- The relay's broadcast chat stays read-only/ephemeral — the compose happens entirely in the crew member's own browser.
- Tests run on any machine and in CI — no real IPs, no machine paths.
- Server-built URLs use validated inputs only (videoId regex, twitch login regex).
- Changed UI surfaces → refresh the matching wiki screenshots in this same change (Task 4).
- Run `python3 tools/lint.py` after changing any Python file; `python3 tools/run-tests.py` is the full suite.

---

### Task 1: Pure compose-target helpers

**Files:**
- Modify: `src/scripts/broadcast_chat.py` (add three pure helpers near the existing URL builders / `twitch_login`)
- Test: `tests/test_broadcast_chat.py` (pure-helpers section, alongside `t_live_chat_page_url` / `t_twitch_login_*`)

**Interfaces:**
- Consumes: existing `live_chat_page_url(video_id)` and `twitch_login(channel)` in the same module.
- Produces:
  - `youtube_video_id(value) -> str|None` — `value` validated to `[A-Za-z0-9_-]{11}`, else `None`.
  - `twitch_popout_chat_url(login) -> str` — `"https://www.twitch.tv/popout/<login>/chat"`.
  - `primary_chat_target(keys) -> dict|None` — `keys` is an ordered list of supervisor reader keys (a YouTube videoId, or `"twitch:<login>"`); returns `{"platform": "youtube"|"twitch", "url": str}` for the first valid one, or `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_broadcast_chat.py` (in the pure section, e.g. after `t_api_url_includes_key`):

```python
# --- compose targets (popup) ------------------------------------------------

def t_youtube_video_id_valid():
    assert bc.youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def t_youtube_video_id_rejects_wrong_length():
    assert bc.youtube_video_id("short") is None
    assert bc.youtube_video_id("a" * 12) is None


def t_youtube_video_id_rejects_illegal_chars_and_nonstr():
    assert bc.youtube_video_id("abc/def?xss") is None
    assert bc.youtube_video_id(None) is None


def t_twitch_popout_chat_url():
    assert bc.twitch_popout_chat_url("gtmaster") == \
        "https://www.twitch.tv/popout/gtmaster/chat"


def t_primary_chat_target_youtube_first():
    t = bc.primary_chat_target(["dQw4w9WgXcQ", "twitch:gtmaster"])
    assert t["platform"] == "youtube"
    assert "v=dQw4w9WgXcQ" in t["url"]


def t_primary_chat_target_twitch():
    assert bc.primary_chat_target(["twitch:gtmaster"]) == {
        "platform": "twitch",
        "url": "https://www.twitch.tv/popout/gtmaster/chat"}


def t_primary_chat_target_empty_is_none():
    assert bc.primary_chat_target([]) is None
    assert bc.primary_chat_target(None) is None


def t_primary_chat_target_skips_invalid_then_picks_next():
    # a malformed first key (not 11-char videoId, not twitch:) is skipped
    t = bc.primary_chat_target(["bad/key", "twitch:gtmaster"])
    assert t["platform"] == "twitch"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_broadcast_chat.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'youtube_video_id'` (reported per test by the harness).

- [ ] **Step 3: Implement the helpers**

In `src/scripts/broadcast_chat.py`, add a `_YT_VIDEO_ID_RE` next to `_TWITCH_LOGIN_RE` (in the Twitch section near line 486):

```python
# A YouTube videoId is interpolated into the popout URL handed to the browser,
# so it is validated to YouTube's own 11-char id charset (defense vs. URL
# injection, mirroring _TWITCH_LOGIN_RE).
_YT_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
```

Then add, in the "URL builders" section (after `get_live_chat_api_url`, near line 425):

```python
def youtube_video_id(value):
    """A YouTube videoId validated to `[A-Za-z0-9_-]{11}`, else None.
    SECURITY: the id is interpolated into the popout URL handed to the browser."""
    return value if isinstance(value, str) and _YT_VIDEO_ID_RE.match(value) else None


def twitch_popout_chat_url(login):
    """A validated Twitch login -> its popout chat URL (carries a compose box for
    a signed-in user). `login` is constrained by twitch_login()."""
    return f"https://www.twitch.tv/popout/{login}/chat"


def primary_chat_target(keys):
    """The first compose target from an ordered list of supervisor reader keys
    (a YouTube videoId, or "twitch:<login>"), as {"platform", "url"}, or None.

    KISS: a broadcast stays on one channel/platform; during an A->B producer
    handover two YouTube videoIds are briefly live and the FIRST is used. Pure;
    mirrors the key convention of BroadcastChatSupervisor._desired()."""
    for key in keys or []:
        if not isinstance(key, str):
            continue
        if key.startswith("twitch:"):
            login = twitch_login(key[len("twitch:"):])
            if login:
                return {"platform": "twitch", "url": twitch_popout_chat_url(login)}
        else:
            vid = youtube_video_id(key)
            if vid:
                return {"platform": "youtube", "url": live_chat_page_url(vid)}
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 tests/test_broadcast_chat.py`
Expected: `broadcast_chat: all tests passed`

- [ ] **Step 5: Lint + commit**

```bash
python3 tools/lint.py
git add src/scripts/broadcast_chat.py tests/test_broadcast_chat.py
git commit -m "feat(broadcast-chat): pure compose-target helpers (popup)"
```

---

### Task 2: Store `target` field + supervisor wiring + endpoint

**Files:**
- Modify: `src/relay/racecast-feeds.py` — `BroadcastChatStore` (around lines 1569–1622) and `BroadcastChatSupervisor._cycle` (around lines 1867–1882)
- Test: `tests/test_broadcast_chat.py` (relay section, after the module is loaded as `m` near line 568)

**Interfaces:**
- Consumes: `broadcast_chat.primary_chat_target(keys)` from Task 1; the existing `make_handler(..., broadcast_chat_store=...)` and `_bc_client(store)` test fixture.
- Produces:
  - `BroadcastChatStore.set_target(target)` — stores a `{platform, url}` dict or `None`.
  - `BroadcastChatStore.data()` now returns `{"messages": [...], "target": dict|None}` (default `None`).
  - `BroadcastChatSupervisor._cycle()` calls `self.store.set_target(...)` each cycle.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_broadcast_chat.py` in the relay section (after the existing `BroadcastChatStore` tests, e.g. near line 610):

```python
def t_store_target_default_none():
    s = m.BroadcastChatStore()
    assert s.data().get("target") is None


def t_store_set_target_reflected_in_data():
    s = m.BroadcastChatStore()
    s.set_target({"platform": "youtube", "url": "https://x/live_chat?v=vid1"})
    assert s.data()["target"]["platform"] == "youtube"


def t_store_reset_clears_target():
    s = m.BroadcastChatStore()
    s.set_target({"platform": "twitch", "url": "https://x/popout/y/chat"})
    s.reset()
    assert s.data()["target"] is None


def t_bc_endpoint_includes_target():
    s = m.BroadcastChatStore()
    s.set_target({"platform": "twitch", "url": "https://www.twitch.tv/popout/x/chat"})
    srv, get = _bc_client(s)
    try:
        code, body = get("/broadcast-chat/data")
        assert code == 200
        assert body["target"]["platform"] == "twitch"
    finally:
        srv.shutdown()


def t_supervisor_sets_primary_target():
    class _StubReader:
        ended = False
        def start(self): return self
        def alive(self): return True
        def stop(self): pass
    s = m.BroadcastChatStore()
    sup = m.BroadcastChatSupervisor(s, None, None)
    sup.channel_source = type("C", (), {"refresh": lambda self: True})()
    sup._desired = lambda: {"vidAAAAAAAAA": (lambda: _StubReader()),
                            "twitch:foo": (lambda: _StubReader())}
    sup._cycle()
    assert s.data()["target"]["platform"] == "youtube"   # YouTube key is first
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 tests/test_broadcast_chat.py`
Expected: FAIL — `t_store_target_default_none` (no `"target"` key → `.get` returns None but `t_store_set_target_reflected_in_data` fails with `AttributeError: 'BroadcastChatStore' object has no attribute 'set_target'`), plus the endpoint/supervisor tests.

- [ ] **Step 3: Implement the store changes**

In `src/relay/racecast-feeds.py`, `BroadcastChatStore.__init__` (after `self._seen_order = []`, line ~1585):

```python
        self._target = None         # {platform, url} compose popup target, or None
```

Replace `data()` (lines ~1614–1616):

```python
    def set_target(self, target):
        with self.lock:
            self._target = target

    def data(self):
        with self.lock:
            return {"messages": list(self.messages), "target": self._target}
```

In `reset()` (lines ~1618–1622), add `self._target = None` after the existing clears:

```python
    def reset(self):
        with self.lock:
            self.messages = []
            self._seen.clear()
            self._seen_order.clear()
            self._target = None
```

- [ ] **Step 4: Implement the supervisor wiring**

In `BroadcastChatSupervisor._cycle()` (line ~1867), right after `desired = self._desired()`:

```python
    def _cycle(self):
        self.channel_source.refresh()
        desired = self._desired()
        # Publish the primary compose-popup target (KISS: first live source).
        self.store.set_target(broadcast_chat.primary_chat_target(list(desired)))
        # Stop readers that are no longer desired (stream gone / channel removed).
        for key in list(self._readers):
            ...
```

(Leave the rest of `_cycle` unchanged.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 tests/test_broadcast_chat.py`
Expected: `broadcast_chat: all tests passed`

- [ ] **Step 6: Lint + commit**

```bash
python3 tools/lint.py
git add src/relay/racecast-feeds.py tests/test_broadcast_chat.py
git commit -m "feat(broadcast-chat): expose primary compose target in data()"
```

---

### Task 3: Front-end compose button (all three console cards)

**Files:**
- Modify: `src/cockpit/cockpit.html` (card header line ~223; CSS near line ~114; poll fn `pollBroadcastChat` line ~573)
- Modify: `src/racecontrol/race-control.html` (card header line ~150; CSS near line ~83; poll fn `pollBroadcastChat` line ~336)
- Modify: `src/director/director-panel.html` (card `<summary>` line ~566; CSS near line ~285; poll fn `bchatPoll` line ~1294)

**Interfaces:**
- Consumes: the `target` field added to `/broadcast-chat/data` in Task 2.
- Produces: a `bchatTarget(target)` helper in each page that shows/updates/hides a `#bchatCompose` button.

The button behaviour is identical across the three pages. The only differences: the `$` selector helper takes a **bare id** in `cockpit.html` / `race-control.html` but a **CSS selector** in `director-panel.html`, and the button lives in an `<h2>` (cockpit/race-control) vs a `<summary>` (director — hence the `preventDefault/stopPropagation` so the click does not toggle the `<details>`; harmless in the `<h2>` case too).

- [ ] **Step 1: Add the shared CSS to each page**

Add this block once per file, next to the existing broadcast-chat CSS (cockpit ~line 114, race-control ~line 83, director ~line 285):

```css
  .bcompose { float: right; font: inherit; font-size: 11px; line-height: 1.4;
    padding: 2px 8px; border: 1px solid #3a4250; border-radius: 5px;
    background: #1f2630; color: #cdd3da; cursor: pointer; }
  .bcompose:hover { background: #2a323d; }
  .bcompose[hidden] { display: none; }
```

- [ ] **Step 2: Add the button to each card header**

`src/cockpit/cockpit.html` — change the `<h2>` (line ~223) to:

```html
          <h2>Broadcast chat <span class="ro">read-only</span><button id="bchatCompose" class="bcompose" hidden></button></h2>
```

`src/racecontrol/race-control.html` — change the `<h2>` (line ~150) to:

```html
      <h2>Broadcast chat <span class="ro">read-only</span><button id="bchatCompose" class="bcompose" hidden></button></h2>
```

`src/director/director-panel.html` — change the `<summary>` (line ~566) to:

```html
    <summary>Broadcast chat <span class="robadge">read-only</span><button id="bchatCompose" class="bcompose" hidden></button></summary>
```

- [ ] **Step 3: Add the `bchatTarget` helper to each page**

In `cockpit.html` and `race-control.html` (bare-id `$`), add near the broadcast-chat JS:

```js
function bchatTarget(target) {
  const btn = $('bchatCompose'); if (!btn) return;
  if (!target || !target.url) { btn.hidden = true; return; }
  const plat = target.platform === 'twitch' ? 'Twitch' : 'YouTube';
  btn.textContent = '✍ Write in ' + plat + ' chat ↗';
  btn.hidden = false;
  btn.onclick = (e) => {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    const w = window.open(target.url, 'rc_broadcast_chat',
      'popup=yes,width=400,height=560,scrollbars=yes,resizable=yes');
    if (w) { try { w.opener = null; } catch (_) {} }
  };
}
```

In `director-panel.html` (selector `$`), add the same helper but with the selector form on the first line:

```js
function bchatTarget(target) {
  const btn = $("#bchatCompose"); if (!btn) return;
  if (!target || !target.url) { btn.hidden = true; return; }
  const plat = target.platform === 'twitch' ? 'Twitch' : 'YouTube';
  btn.textContent = '✍ Write in ' + plat + ' chat ↗';
  btn.hidden = false;
  btn.onclick = (e) => {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    const w = window.open(target.url, 'rc_broadcast_chat',
      'popup=yes,width=400,height=560,scrollbars=yes,resizable=yes');
    if (w) { try { w.opener = null; } catch (_) {} }
  };
}
```

- [ ] **Step 4: Call `bchatTarget` from each poll function**

`src/cockpit/cockpit.html` — in `pollBroadcastChat` (line ~573), after `renderBroadcastChat(d.messages || []);` add:

```js
    renderBroadcastChat(d.messages || []);
    bchatTarget(d.target);
```

`src/racecontrol/race-control.html` — in `pollBroadcastChat` (line ~336), right after `const d = await j('/broadcast-chat/data');` add:

```js
    const d = await j('/broadcast-chat/data');
    bchatTarget(d.target);
```

`src/director/director-panel.html` — in `bchatPoll` (line ~1303), after `if (!d.error) bchatRender(d.messages || []);` add:

```js
    if (!d.error) bchatRender(d.messages || []);
    bchatTarget(d.target);
```

- [ ] **Step 5: Manual visual check**

Start a local dev build from `src/` against a profile whose Sheet `Channel` tab points at a currently-live YouTube (or Twitch) channel, OR temporarily hard-code a target for the check, e.g. in the relay shell: open the page and confirm:
- the button appears in the broadcast-chat card header with the right platform label,
- clicking it opens a ~400×560 popup window (not a tab) on youtube.com/twitch.tv,
- a second click reuses the same window,
- with no live chat the button is hidden.

(There is no unit test for the HTML; this manual step is the gate. Revert any temporary hard-code before committing.)

- [ ] **Step 6: Commit**

```bash
git add src/cockpit/cockpit.html src/racecontrol/race-control.html src/director/director-panel.html
git commit -m "feat(broadcast-chat): compose-popup button in the three console cards"
```

---

### Task 4: Docs, wiki screenshots, and full-suite verification

**Files:**
- Modify: `CLAUDE.md` (the broadcast-chat reader paragraph in the Architecture/relay section)
- Modify (conditional): `src/docs/wiki/images/director-panel.png` and the cockpit / console / race-control images that show the broadcast-chat card
- Verify: whole test suite + build

- [ ] **Step 1: Update CLAUDE.md**

In the broadcast-chat reader paragraph, append one sentence noting the compose popup. Find the sentence ending "…the front-end card self-hides." and add after it:

```
A read-only `target` (`{platform, url}`) field on `/broadcast-chat/data` (and the
Funnel `/console/broadcast-chat/data`) carries the current primary live source so
each console card can show a **"Write in chat ↗"** button that `window.open`s the
native YouTube/Twitch popout chat — the crew posts under their own browser account;
the relay adds **no write path** and stays read-only/ephemeral (pure
`primary_chat_target` in `broadcast_chat.py`; popup button in the three cards).
```

- [ ] **Step 2: Refresh wiki screenshots (per the hard rule)**

The button is **conditional on a live broadcast target**. Use the `wiki-screenshots` skill to drive a running dev build (the `demo` profile + `tools/obs-sim.py`) for the Director Panel, cockpit, and Race Control surfaces:
- If the standard demo recipe surfaces a live broadcast-chat target (button visible), recapture the affected element screenshots (`director-panel.png` and the cockpit/console/race-control card images) and commit them.
- If the recipe has no live broadcast channel (button hidden → the surfaces are visually unchanged), state that explicitly in the commit message instead of recapturing.

Note (from project memory): running the `demo`-profile relay mutates committed `profiles/demo/profile.env` (writes `CONSOLE_SECRET`) — revert that file before committing.

- [ ] **Step 3: Run the full suite + build verify**

```bash
python3 tools/run-tests.py
python3 tools/lint.py
python3 tools/build.py
```
Expected: all tests pass; lint clean; build verify passes (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
# add any recaptured images under src/docs/wiki/images/ if Step 2 produced them
git commit -m "docs(broadcast-chat): document compose popup + refresh screenshots"
```

---

## Self-Review

**Spec coverage:**
- Approach A / native popout, no write path → Tasks 1–3.
- Pure helpers `youtube_video_id`, `twitch_popout_chat_url`, `primary_chat_target` → Task 1.
- Store `target` + supervisor wiring + endpoints (no new surface) → Task 2.
- Button on all three cards, conditional visibility, platform-aware label, 400×560 named popup → Task 3.
- Security (server-built validated URLs, no new surface, `opener=null`) → Tasks 1–3.
- Tests (pure helpers, store, endpoint) → Tasks 1–2.
- CLAUDE.md sentence + wiki screenshots → Task 4.

**Placeholder scan:** No TBD/TODO; all code shown inline; the only conditional is the wiki-screenshot recapture, which is explicitly branched (recapture vs. document-unchanged).

**Type consistency:** `primary_chat_target(keys)` (ordered key strings) is produced in Task 1 and consumed in Task 2 via `list(desired)`; `set_target`/`data()["target"]` names match across Tasks 2–3; `bchatTarget(d.target)` reads the same `{platform, url}` shape everywhere.
