# Centralized outbound-HTTP helper with a guaranteed User-Agent

**Date:** 2026-06-21
**Status:** Design approved

## Problem

racecast makes outbound HTTP with stdlib `urllib` scattered across many modules.
Cloudflare-fronted hosts (Discord webhooks, Google Fonts, some GitHub/vendor
endpoints) reject the default `Python-urllib/x.y` User-Agent with **HTTP 403**, so
the request silently fails. We have hit this repeatedly — most recently the
`/console` Discord link post (PR #249). Almost every caller *does* set a UA, but
each does so by hand, so a new caller can forget (e.g. `install_apps._http_fetch`,
`funnel_setup` ride the default UA today). The CLAUDE.md hard rule added in #249 is
a manual backstop; there is no structural guarantee.

## Goal

One canonical outbound-HTTP helper that **always** sends a racecast User-Agent, plus
a **guard test** that makes it structurally impossible for a covered module to issue
a bare `urllib` request. After this, "set the User-Agent" is no longer something a
future caller can forget on the covered side.

## Scope

**Covered (must route through the helper; guard enforces it):**
`src/racecast.py`, `src/ui/ui_server.py`, and every `src/scripts/*.py` that does
HTTP — `installer_common.py`, `install_tools.py`, `install_apps.py`,
`funnel_setup.py`, `obs_browser_linux.py`, `preflight.py`. Both external and
loopback/tailnet calls migrate (loopback needs no UA, but routing it through the
helper too lets the guard be absolute).

**Explicitly NOT covered (allowlisted in the guard, with reasons):**
- `src/scripts/update.py` — builds a custom HTTPS-only redirect opener
  (`_HttpsOnlyRedirect` + `urllib.request.build_opener`) as a security control and
  exposes a test-injection seam; it inherently needs `urllib.request` and already
  sets a UA (`racecast-update`). Contorting the helper to absorb it would violate
  YAGNI.
- The self-contained, dependency-light scripts — the relay
  `src/relay/racecast-feeds.py`, `src/relay/get-graphics.py`,
  `src/relay/get-media.py`, `src/setup-assets.py`. CLAUDE.md mandates they not
  import shared modules; they already set consistent UAs (`racecast-feeds/1.0`,
  `racecast-graphics/1.0`, …). Out of scope.
- `tools/*` — maintainer-only, never shipped.

## Design

### 1. New module `src/scripts/http_util.py` (stdlib only)

The single place `urllib.request` is used on the covered side.

```python
RACECAST_UA = "racecast/1.0"      # one canonical UA for the covered side
DEFAULT_TIMEOUT = 10

HTTPError = urllib.error.HTTPError  # re-export so callers never import urllib to catch

def open_url(url, *, data=None, headers=None, method=None, timeout=DEFAULT_TIMEOUT):
    """urllib response context manager with RACECAST_UA always set (caller headers
    merged on top, but the UA is always present). Raises HTTPError on 4xx/5xx like
    urllib. Use in a `with`. Covers streaming, range, status/header reads."""

def get_bytes(url, *, headers=None, timeout=DEFAULT_TIMEOUT) -> bytes
def get_json(url, *, headers=None, timeout=DEFAULT_TIMEOUT)        # parses JSON
def post_json(url, obj, *, headers=None, timeout=DEFAULT_TIMEOUT) -> bytes
    # sets Content-Type: application/json + JSON-encodes obj
```

- `open_url` is the low-level primitive every existing shape maps onto: streaming
  download (`with open_url(...) as r: shutil.copyfileobj(r, f)`), range requests
  (`headers={"Range": …}`), status/header reads (`r.status, dict(r.headers)`),
  checksum-chunked reads, and JSON POST/GET via the conveniences.
- UA injection: the helper seeds `{"User-Agent": RACECAST_UA}` then merges caller
  `headers`; a caller cannot end up with the default urllib UA.
- The `# noqa: S310` urllib-audit suppression centralizes here (one place instead
  of scattered).

### 2. Migration (per covered file)

Replace each `urllib.request`/`urlopen` site with the matching helper call. Behavior
is preserved per call: same timeouts, same extra headers, `HTTPError` still raised.
After migration each covered file contains neither `urllib.request` nor `urlopen`
(`urllib.parse`/`urllib.error` remain allowed).

- `racecast.py` — `_fetch_relay_page` (loopback GET → `open_url`/`get_bytes`),
  the `_u.urlopen` GET (~1046), `_post_chat_message` (loopback POST → `post_json`),
  the cockpit/versions pull (~1257, `X-Console-Secret` header → `open_url`+`get_json`),
  the `/status` ping (~1433), `_relay_fetch_json` (~1442 → `get_json`),
  `_takeover_get` (~1470, needs `HTTPError` to propagate → `open_url`/`get_json`,
  catch `http_util.HTTPError`), `_relay_post_json` (~1480 → `post_json`+parse), and
  the Google-fonts GET (~4047 → `open_url`/`get_bytes`). The `import urllib.error`
  at ~3413 becomes `http_util.HTTPError`.
- `ui_server.py` — the `/api/ping` loopback GET (~51 → `open_url`/`get_bytes`).
- `installer_common.py` — `_fetch` delegates to `http_util.get_bytes`; drop the
  local `INSTALLER_UA` (callers move to the canonical UA).
- `install_tools.py` — the two checksum-verified streaming downloads → `open_url`.
- `install_apps.py` — `_http_fetch` range GET → `open_url(headers={"Range": …})`.
- `funnel_setup.py` — the Tailscale-API request → `open_url`; keep `urllib.parse`
  and `urllib.error` imports (still allowed).
- `obs_browser_linux.py` — the streaming download → `open_url` + `copyfileobj`.
- `preflight.py` — the GET → `open_url`/`get_bytes`.

Loading: `http_util` lives in `src/scripts/` alongside the modules that already
sibling-import (`config`, `services`, `logsetup`); `racecast.py` and `ui_server.py`
already add `src/scripts` to `sys.path`. In the frozen binary it ships as data under
`_MEIPASS/src/scripts` and is importlib-loadable like its siblings.

### 3. Guard test `tests/test_http_util.py`

- **Helper unit tests** (no network — monkeypatch `urllib.request.urlopen` to
  capture the `Request`): `RACECAST_UA` is non-default and always present;
  caller headers merge without dropping the UA; `post_json` sets `Content-Type` and
  JSON-encodes the body; `get_json` parses; `HTTPError` propagates from `open_url`.
- **Enforcement scan:** read each covered file's source and assert it contains
  neither the substring `urlopen` nor `urllib.request`. The allowlist is exactly
  `http_util.py` (the one legitimate user) plus the documented exceptions
  (`update.py`). `urllib.parse`/`urllib.error` are not banned. Because every covered
  HTTP call now flows through one helper, this guard is non-flaky (unlike a blanket
  "every request needs a UA" scan, which false-positives on intentional no-UA
  internal calls).

### 4. Docs

- Update the CLAUDE.md hard rule added in #249: covered modules MUST use
  `http_util` (the guard enforces it); the relay/self-contained scripts and
  `update.py` keep their own UA. Note `update.py` is the allowlisted exception.
- Add `python3 tests/test_http_util.py` to the Commands test list.

## Error handling

`open_url` raises `HTTPError`/`URLError` exactly as urllib does today, so callers
that distinguish auth rejection (takeover 401/403) or treat any failure as "unknown"
keep their current control flow. No call site changes its timeout or its
success/failure semantics.

## Testing

`tests/test_http_util.py` (helper + guard). Run the full suite
(`python3 tools/run-tests.py`) and `python3 tools/lint.py`; the lint rules mirror
the CodeQL alert classes, so the centralized `# noqa: S310` must satisfy them. No
behavior-change tests are needed for the migrated call sites (semantics preserved),
but the existing tests over those modules must stay green.

## Risks

- Broad mechanical migration (~18 call sites). The guard test guarantees
  completeness — anything missed fails the scan.
- A migrated loopback/tailnet call now sends a UA where it sent none; harmless.
- `update.py` remains a manual-UA module by design; the allowlist documents why so
  it is not mistaken for a gap.
