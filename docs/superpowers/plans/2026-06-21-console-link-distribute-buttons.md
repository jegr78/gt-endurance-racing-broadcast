# Crew Console link-distribute buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **Copy Link** and **Post to Discord** buttons to the Crew Console view's Funnel section that distribute the shared `https://<magicdns>/console` landing-page link, posting to Discord with an `@here` ping.

**Architecture:** A pure payload builder in `console_admin.py`; a best-effort handler + helpers in `racecast.py` that POST to the league's existing `DISCORD_WEBHOOK_URL`; a new `POST /api/console/post-link` route in the Control Center server wired to that handler; one extra `console_url` field on the console-status payload; two front-end buttons in `control-center.html`. The server always computes the link itself — never trusts a client URL.

**Tech Stack:** Python 3 stdlib only (no framework, no deps); vanilla JS in `control-center.html`; Discord incoming-webhook JSON; `urllib` for the POST.

## Global Constraints

- Edit only under `src/` (plus `tests/` and `docs/`). Never hand-edit `dist/`/`runtime/`.
- All scripts and docs are **English only**.
- No hardcoded secrets or machine paths. The webhook URL stays server-side and is read from the active profile's `profile.env` via `pcfg.resolve_config`.
- stdlib only; no new runtime dependencies.
- Tests must run on any machine and in CI — no real IPs, no machine paths, no network. Use monkeypatching for `_tailscale_magicdns`, the webhook resolver, and the HTTP POST.
- Each test file is a runnable script (no pytest). `python3 tools/run-tests.py` auto-discovers `tests/test_*.py`.
- Run `python3 tools/lint.py` after changing any Python file.
- **CLAUDE.md hard rule:** a changed Control Center view means its `cc-*.png` wiki screenshot is stale and MUST be regenerated from a **local dev build** (no `VERSION` stamped) in this same change (Task 5).

---

### Task 1: Pure Discord payload builder

**Files:**
- Modify: `src/scripts/console_admin.py` (append a new function)
- Test: `tests/test_cockpit.py` (already loads `console_admin` as `cad` at line 21)

**Interfaces:**
- Produces: `console_link_discord_payload(console_url, league_name) -> dict` — returns the Discord incoming-webhook JSON body. Always includes an `@here` ping in `content`, the `console_url`, and `allowed_mentions={"parse": ["everyone"]}` so `@here` actually pings. `league_name` is woven in only when non-empty.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cockpit.py` (after the existing `console_admin`/`cad` tests, e.g. near `t_apply_pulled_validates`):

```python
def t_console_link_discord_payload_basics():
    p = cad.console_link_discord_payload("https://h.ts.net/console", "")
    assert "@here" in p["content"]
    assert "https://h.ts.net/console" in p["content"]
    # @here only pings when allowed_mentions opts into the "everyone" parse type
    assert p["allowed_mentions"] == {"parse": ["everyone"]}


def t_console_link_discord_payload_weaves_league_name():
    p = cad.console_link_discord_payload("https://h.ts.net/console", "GT Masters")
    assert "GT Masters" in p["content"]
    # an empty league name must NOT leak surrounding punctuation/placeholder
    p2 = cad.console_link_discord_payload("https://h.ts.net/console", "")
    assert "None" not in p2["content"] and "()" not in p2["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_cockpit.py`
Expected: FAIL with `AttributeError: module 'console_admin' has no attribute 'console_link_discord_payload'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/scripts/console_admin.py`:

```python
def console_link_discord_payload(console_url, league_name=""):
    """Discord incoming-webhook JSON body announcing the shared /console
    landing-page link. Includes an @here ping (allowed_mentions opts the
    'everyone' parse type in so the ping fires). `league_name` is woven in
    only when non-empty. Pure — no I/O."""
    league = (league_name or "").strip()
    suffix = f" — {league}" if league else ""
    content = (f"@here \U0001F399️ **Crew Console{suffix}** — open the "
               f"launcher and sign in with Discord or your personal link: "
               f"<{console_url}>")
    return {"content": content, "allowed_mentions": {"parse": ["everyone"]}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_cockpit.py`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add src/scripts/console_admin.py tests/test_cockpit.py
git commit -m "feat(console): pure Discord payload builder for the shared console link"
```

---

### Task 2: `console_url` field on the console-status payload

**Files:**
- Modify: `src/racecast.py` — `console_status_data()` (lines ~3570-3616)
- Test: `tests/test_racecast.py` — extend `t_console_status_links_union_crew` (line ~2350)

**Interfaces:**
- Produces: `console_status_data()` return dict now carries `"console_url"`: `https://<magic>/console` when MagicDNS resolves, else `""`. Consumed by the front-end (Task 4) and surfaced through `/api/console/status` (Task 3 uses the mock).

- [ ] **Step 1: Write the failing test**

Edit `tests/test_racecast.py` — in `t_console_status_links_union_crew`, monkeypatch MagicDNS and assert the new field. Replace the body so it also pins `_tailscale_magicdns`:

```python
def t_console_status_links_union_crew():
    # console_status_data() must union _crew_roster_safe() into the link list,
    # deduped by streamer_key. Both rosters contribute; dedup removes same-key dupes.
    orig_sched = m._console_roster_safe
    orig_crew = m._crew_roster_safe
    orig_secret = m._ensure_active_console_secret
    orig_magic = m._tailscale_magicdns
    try:
        m._console_roster_safe = lambda: ["Alice"]
        m._crew_roster_safe = lambda: ["Dana the Director"]
        m._ensure_active_console_secret = lambda: "s" * 64
        m._tailscale_magicdns = lambda: "host.tail.ts.net"
        data = m.console_status_data()
        names = [l["name"] for l in data["links"]]
        assert names == ["Alice", "Dana the Director"], names
        assert all("/console?t=" in l["internal"] for l in data["links"])
        # the shared (token-free) landing-page link the distribute buttons use
        assert data["console_url"] == "https://host.tail.ts.net/console"
    finally:
        m._console_roster_safe = orig_sched
        m._crew_roster_safe = orig_crew
        m._ensure_active_console_secret = orig_secret
        m._tailscale_magicdns = orig_magic


def t_console_status_console_url_empty_without_magicdns():
    orig_secret = m._ensure_active_console_secret
    orig_magic = m._tailscale_magicdns
    try:
        m._ensure_active_console_secret = lambda: "s" * 64
        m._tailscale_magicdns = lambda: ""
        assert m.console_status_data()["console_url"] == ""
    finally:
        m._ensure_active_console_secret = orig_secret
        m._tailscale_magicdns = orig_magic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_racecast.py`
Expected: FAIL with `KeyError: 'console_url'`

- [ ] **Step 3: Write minimal implementation**

In `src/racecast.py` `console_status_data()`, hoist the MagicDNS lookup so it is computed once and reused for both links and the shared URL, then add the field to the return.

Change the `if secret:` block so `magic` is resolved before it (replace the existing `host = ...` / `magic = _tailscale_magicdns()` lines):

```python
        secret = _ensure_active_console_secret() or ""
        magic = _tailscale_magicdns()
        links = []
        if secret:
            host = _console_internal_host(_tailscale_ip())
            versions = cpadm.load_versions(_console_versions_path())
```

(Delete the now-duplicate `magic = _tailscale_magicdns()` line that was inside the `if secret:` block; the per-member link code below it keeps using `magic` unchanged.)

Then extend the return dict:

```python
        return {"ok": True, "has_secret": bool(secret),
                "funnel_auto": funnel_auto, "funnel_capable": funnel_capable,
                "funnel_on": funnel_on, "links": links,
                "console_url": (f"https://{magic}/console" if magic else "")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_racecast.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py tests/test_racecast.py
git commit -m "feat(console): expose shared console_url in console status"
```

---

### Task 3: Post-link handler + `/api/console/post-link` route

**Files:**
- Modify: `src/racecast.py` — add `_active_discord_webhook()`, `_post_discord_webhook()`, `console_post_link_data()`; register `"console_post_link"` in the ctx dict (lines ~4877-4880)
- Modify: `src/ui/ui_server.py` — add the POST route next to the other `/api/console/*` POST routes (after line ~705)
- Test: `tests/test_racecast.py` (handler branches) and `tests/test_ui_server.py` (route dispatch)

**Interfaces:**
- Consumes: `cpadm.console_link_discord_payload` (Task 1); `_tailscale_magicdns` (existing).
- Produces:
  - `_active_discord_webhook() -> (webhook_url:str, league_name:str)` — `("","")` on any failure.
  - `_post_discord_webhook(url, payload) -> None` — best-effort HTTP POST; raises on HTTP/network error (caller catches).
  - `console_post_link_data() -> dict` — `{"ok": True}` on success; `{"ok": False, "error": <str>}` when MagicDNS is down, no webhook is configured, or the POST fails. Never raises.
  - ctx key `"console_post_link"` → `console_post_link_data`.
  - Route `POST /api/console/post-link` (no body) → dispatches to `ctx["console_post_link"]()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_racecast.py` (near the other console tests):

```python
def t_console_post_link_errors_without_magicdns():
    orig = m._tailscale_magicdns
    try:
        m._tailscale_magicdns = lambda: ""
        r = m.console_post_link_data()
        assert r["ok"] is False and "MagicDNS" in r["error"]
    finally:
        m._tailscale_magicdns = orig


def t_console_post_link_errors_without_webhook():
    orig_magic = m._tailscale_magicdns
    orig_hook = m._active_discord_webhook
    try:
        m._tailscale_magicdns = lambda: "h.ts.net"
        m._active_discord_webhook = lambda: ("", "")
        r = m.console_post_link_data()
        assert r["ok"] is False and "DISCORD_WEBHOOK_URL" in r["error"]
    finally:
        m._tailscale_magicdns = orig_magic
        m._active_discord_webhook = orig_hook


def t_console_post_link_posts_payload_to_webhook():
    sent = {}
    orig_magic = m._tailscale_magicdns
    orig_hook = m._active_discord_webhook
    orig_post = m._post_discord_webhook
    try:
        m._tailscale_magicdns = lambda: "h.ts.net"
        m._active_discord_webhook = lambda: ("https://discord/webhook", "GT Masters")
        m._post_discord_webhook = lambda url, payload: sent.update(url=url, payload=payload)
        r = m.console_post_link_data()
        assert r["ok"] is True
        assert sent["url"] == "https://discord/webhook"
        assert "https://h.ts.net/console" in sent["payload"]["content"]
        assert "@here" in sent["payload"]["content"]
    finally:
        m._tailscale_magicdns = orig_magic
        m._active_discord_webhook = orig_hook
        m._post_discord_webhook = orig_post


def t_console_post_link_reports_post_failure():
    orig_magic = m._tailscale_magicdns
    orig_hook = m._active_discord_webhook
    orig_post = m._post_discord_webhook
    def boom(url, payload):
        raise RuntimeError("HTTP 404")
    try:
        m._tailscale_magicdns = lambda: "h.ts.net"
        m._active_discord_webhook = lambda: ("https://discord/webhook", "")
        m._post_discord_webhook = boom
        r = m.console_post_link_data()
        assert r["ok"] is False and "404" in r["error"]
    finally:
        m._tailscale_magicdns = orig_magic
        m._active_discord_webhook = orig_hook
        m._post_discord_webhook = orig_post
```

Add to `tests/test_ui_server.py` — extend `t_console_post_routes_pass_args` (line ~1164) to also cover the new route:

```python
def t_console_post_routes_pass_args():
    seen = {}
    ctx = _ctx()
    ctx["console_funnel"] = lambda on: seen.update(fn=on) or {"ok": True}
    ctx["console_revoke"] = lambda streamer: seen.update(rv=streamer) or {"ok": True}
    ctx["console_post_link"] = lambda: seen.update(post=True) or {"ok": True}
    httpd, port = _serve(ctx)
    try:
        assert _post_json(port, "/api/console/funnel", {"on": True})[0] == 200
        assert _post_json(port, "/api/console/revoke", {"streamer": "Alpha"})[0] == 200
        assert _post_json(port, "/api/console/post-link", {})[0] == 200
        assert seen == {"fn": True, "rv": "Alpha", "post": True}
    finally:
        httpd.shutdown()
```

Also add `"console_post_link"` to the `_ctx()` mock in `tests/test_ui_server.py` (next to `"console_revoke"` at line ~183) so other tests serving the default ctx don't 500 on the route if hit:

```python
            "console_revoke": lambda streamer: {"ok": True, "_got": streamer},
            "console_post_link": lambda: {"ok": True},
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_racecast.py` then `python3 tests/test_ui_server.py`
Expected: racecast FAILs with `AttributeError: module 'racecast' has no attribute 'console_post_link_data'`; ui_server FAILs because `/api/console/post-link` returns 404 (no route) — `_post_json(...)[0]` is `404`, not `200`.

- [ ] **Step 3: Write the implementation**

In `src/racecast.py`, add the three functions next to `console_revoke_data` (after line ~3643):

```python
def _active_discord_webhook():
    """(webhook_url, league_name) for the active profile; ("","") on any
    failure. Best-effort — the webhook stays server-side, never in the browser."""
    try:
        root = _env_base(IS_FROZEN, _real_executable(), HERE)
        rc = pcfg.resolve_config(root, runtime_root=_runtime_base_dir())
        return rc.discord_webhook_url or "", rc.name or ""
    except Exception:  # noqa: BLE001 — best effort
        return "", ""


def _post_discord_webhook(url, payload):
    """POST a Discord incoming-webhook JSON body. Raises on HTTP/network error
    (callers catch and report)."""
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def console_post_link_data():
    """Post the shared /console landing-page link to the league's Discord
    webhook (with an @here ping). The link is computed server-side from MagicDNS
    — never supplied by the client. {ok}|{ok:false,error}; never raises."""
    try:
        magic = _tailscale_magicdns()
        if not magic:
            return {"ok": False, "error": "MagicDNS unavailable — is Tailscale up?"}
        webhook, league = _active_discord_webhook()
        if not webhook:
            return {"ok": False,
                    "error": "No DISCORD_WEBHOOK_URL configured for this league"}
        payload = cpadm.console_link_discord_payload(f"https://{magic}/console", league)
        _post_discord_webhook(webhook, payload)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — best effort, surface the message
        return {"ok": False, "error": str(exc)}
```

Register it in the ctx dict (after the `"console_revoke"` line, ~4880):

```python
        "console_revoke": console_revoke_data,
        "console_post_link": console_post_link_data,
```

In `src/ui/ui_server.py`, add the route after the `/api/console/revoke` block (after line ~705). It takes no body, so dispatch directly:

```python
            if path == "/api/console/post-link":
                result = ctx["console_post_link"]()
                return self._json(result, code=200 if result.get("ok") else 400)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_racecast.py` then `python3 tests/test_ui_server.py`
Expected: PASS (both files)

- [ ] **Step 5: Commit**

```bash
git add src/racecast.py src/ui/ui_server.py tests/test_racecast.py tests/test_ui_server.py
git commit -m "feat(console): POST /api/console/post-link posts the shared link to Discord"
```

---

### Task 4: Front-end Copy / Post buttons

**Files:**
- Modify: `src/ui/control-center.html` — Funnel section markup (lines ~898-905) + `loadConsole()` (lines ~2308-2351) + add two handler functions near `consoleFunnel` (line ~2352)

**Interfaces:**
- Consumes: `GET /api/console/status` → `console_url` (Task 2); `POST /api/console/post-link` (Task 3).

- [ ] **Step 1: Add the buttons to the Funnel section markup**

In the `Public access (Tailscale Funnel)` `<section>`, add a button row after the `cp-funnel-auto` label (before the closing `<p class="sub">`):

```html
          <div class="cprow" style="margin-top:8px">
            <button id="cp-copy-link" onclick="copyConsoleLink(this)" disabled>Copy Link</button>
            <button id="cp-post-link" onclick="postConsoleLink(this)" disabled>Post to Discord</button>
            <span id="cp-link-hint" class="sub" style="margin-left:8px">MagicDNS not available (is Tailscale up?)</span>
          </div>
```

- [ ] **Step 2: Wire `loadConsole()` to enable the buttons from `console_url`**

In `loadConsole()`, right after the funnel pill block (after `$('cp-funnel-auto').checked = !!d.funnel_auto;`), add:

```javascript
  window._consoleUrl = d.console_url || '';
  const hasUrl = !!window._consoleUrl;
  $('cp-copy-link').disabled = !hasUrl;
  $('cp-post-link').disabled = !hasUrl;
  $('cp-link-hint').hidden = hasUrl;
```

- [ ] **Step 3: Add the two handler functions**

After the `consoleFunnel` function (line ~2358), add:

```javascript
async function copyConsoleLink(btn) {
  if (!window._consoleUrl) return;
  await navigator.clipboard.writeText(window._consoleUrl);
  const old = btn.textContent;
  btn.textContent = 'Copied ✓';
  setTimeout(() => { btn.textContent = old; }, 1500);
}
async function postConsoleLink(btn) {
  $('cp-err').hidden = true;
  btn.disabled = true;
  const old = btn.textContent;
  try {
    const r = await (await fetch('/api/console/post-link', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: '{}'})).json();
    if (!r.ok) { showProfileErr('cp-err', r.error || 'could not post the link'); }
    else { btn.textContent = 'Posted ✓'; setTimeout(() => { btn.textContent = old; }, 1500); }
  } catch (e) {
    showProfileErr('cp-err', 'Control Center not reachable.');
  } finally {
    btn.disabled = false;
  }
}
```

- [ ] **Step 4: Manual smoke test**

Run the Control Center from source:

```bash
python3 src/racecast.py ui
```

Open `http://127.0.0.1:8089`, go to the **Crew Console** view. Expected: with Tailscale down the two new buttons are disabled and the "MagicDNS not available" hint shows; with MagicDNS up they enable, **Copy Link** flashes "Copied ✓", and **Post to Discord** shows the "No DISCORD_WEBHOOK_URL configured" error inline when the active profile has no webhook (or "Posted ✓" when it does). Stop with Ctrl-C.

- [ ] **Step 5: Commit**

```bash
git add src/ui/control-center.html
git commit -m "feat(console): Copy Link + Post to Discord buttons in Crew Console"
```

---

### Task 5: Regenerate the Crew Console wiki screenshot

**Files:**
- Modify: the Crew Console Control Center image under `src/docs/wiki/images/` (the `cc-*.png` matching the `console` view)

**Interfaces:** none (asset refresh mandated by CLAUDE.md).

- [ ] **Step 1: Identify the exact image filename**

Run:

```bash
ls src/docs/wiki/images/ | grep -i -E 'console|cockpit|crew'
```

Expected: one `cc-*.png` for the Crew Console view (e.g. `cc-console.png`). Note the exact name; the refreshed file MUST overwrite that same path.

- [ ] **Step 2: Capture from a local dev build (no VERSION)**

Confirm no `VERSION` file is stamped (so the badge reads "dev build", matching every other `cc-*.png` per the project memory):

```bash
ls VERSION 2>/dev/null && echo "REMOVE/!ignore VERSION before capturing" || echo "ok: dev build"
```

Start the Control Center from `src/`:

```bash
python3 src/racecast.py ui
```

Drive it with the Playwright MCP: navigate to `http://127.0.0.1:8089`, click the **Crew Console** nav item (`[data-nav="console"]`), then take an **element** screenshot of the view container `[data-view="console"]` (an element grab, not a full-window capture, so the framing matches the existing `cc-*.png`). Save over the exact filename from Step 1. Stop the server with Ctrl-C.

- [ ] **Step 3: Verify the image changed and looks right**

Run:

```bash
git status --porcelain src/docs/wiki/images/
```

Expected: the identified `cc-*.png` shows as modified. Open it and confirm the two new buttons (**Copy Link**, **Post to Discord**) are visible in the Funnel section and the badge reads "dev build".

- [ ] **Step 4: Commit**

```bash
git add src/docs/wiki/images/
git commit -m "docs(wiki): refresh Crew Console screenshot for link-distribute buttons"
```

---

### Final verification

- [ ] **Run the full suite (what CI runs):**

```bash
python3 tools/run-tests.py
```
Expected: all test files PASS.

- [ ] **Lint:**

```bash
python3 tools/lint.py
```
Expected: no findings.

- [ ] **Build self-verify (closest thing to CI for shipped artifacts):**

```bash
python3 tools/build.py
```
Expected: build + verify succeed (tokenization, blanked password, no secrets, no shell scripts).

## Self-Review notes

- **Spec coverage:** §1 console_url → Task 2; §2 endpoint → Task 3; §3 handler → Task 3; §4 pure payload helper → Task 1; §5 front-end → Task 4; §6 wiki screenshot → Task 5; testing section → Tasks 1-3 + Final. All covered.
- **Type consistency:** `console_link_discord_payload(console_url, league_name)` defined in Task 1 and called identically in Task 3; `console_post_link_data` / ctx key `"console_post_link"` / route `/api/console/post-link` consistent across Tasks 3-4; `console_url` field consistent across Tasks 2-4.
- **No network in tests:** every handler test monkeypatches `_tailscale_magicdns`, `_active_discord_webhook`, and `_post_discord_webhook`; route tests use ctx mocks.
