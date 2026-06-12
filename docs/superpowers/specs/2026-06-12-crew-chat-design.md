# Crew Chat — Design

**Date:** 2026-06-12
**Status:** Approved

## Problem

During an event the active crew (producer + directors) coordinates over Discord,
where everyone — including streamers and off-duty producers/directors who are not
currently on shift — sits in the same channels. A quick "are you ready for the
handover?" reaches the whole group instead of just the people actively running the
broadcast. The crew wants a small, in-context chat scoped to whoever is actually on
the relay/panel right now, so coordination is fast and only the active participants
are involved.

The relay already hosts the shared surface for this: an unauthenticated
`ThreadingHTTPServer` on port `8088` serving `/panel`, reachable by directors over
the tailnet and by the producer locally. It already holds in-memory state served via
2 s polling (HUD, timer, setup, schedule) and persists state to `runtime/` JSON
files (`timer.json`). A crew chat slots into exactly these patterns — no new
infrastructure, no external service.

Tailscale itself provides **no** chat (only Taildrop file transfer); it is purely the
secure transport that lets the crew reach the relay. The chat must therefore live on
the relay.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Identity | Self-declared display name, stored per browser in `localStorage` (`racecast.chat.name`), editable any time, sent as `user` on each message. No identity proof — names are spoofable, which is acceptable inside the trusted tailnet and is documented. Tailscale-derived identity and fixed role dropdowns were rejected (the former breaks for the local producer on `127.0.0.1`; the latter cannot distinguish multiple directors). |
| Persistence | Messages persist to `runtime/chat.json` (best-effort, like `timer.json`) and are loaded on relay start, so the history survives a relay restart mid-event. |
| History size | In-memory ring buffer of the last `MAX_MESSAGES` (200) messages; older messages drop off. |
| Clearing | Producer-only, via CLI (`racecast chat clear`) and a "Clear chat" button in the Control Center. The panel has **no** clear control — clearing is producer authority. |
| Unread indication | An unread-count badge on the collapsed/blurred chat section header. No sound (would risk disturbing the producer-machine audio). |
| Producer surface | The chat (read + write) lives **only** in `/panel`; the producer opens `/panel` too. The Control Center gets only the clear button, not a chat widget. |
| Transport | 2 s polling of `/chat/data`, identical to the existing HUD/timer/setup/schedule polling. SSE was rejected as overkill for low-volume crew chat. |
| Ordering / unread key | Server-set timestamp `ts` (epoch seconds, like `timer.json`). Messages sort by `ts`; the unread badge compares against a browser-stored "last seen `ts`". A monotonic per-relay sequence counter was rejected because it breaks across a producer handover (two relays = two counter spaces → missed or duplicate "unread"). |
| Producer handover | Explicit `racecast chat pull <tailscale-ip>` only — no automatic pull folded into `event start`. |

## Architecture

The chat is server-authoritative in-memory state on the relay, persisted to a local
JSON file, mutated remotely only by appending one bounded message, and replaced
wholesale only through a **local file write + reload** (never via an HTTP payload).

```
Panel (every 2 s)            GET  /chat/data   → {messages:[{ts,user,text}], ...}
Panel "send"                 POST /chat/send   → {user,text}  (validate, append, save)
Producer (local file op)     write runtime/chat.json  +  GET /chat/reload
```

### 1. `ChatStore` (server — `src/relay/racecast-feeds.py`)

A small class analogous to `TimerStore`:

- In-memory list of messages, each `{"ts": <float>, "user": <str>, "text": <str>}`,
  kept in append order (which is `ts` order). Capped at `MAX_MESSAGES = 200`
  (oldest dropped on overflow).
- Lock-protected for concurrent requests (`with self.lock:`).
- Persists to `runtime/chat.json` (best-effort; `OSError` caught and ignored, same as
  `TimerStore._save_file`). Loaded on construction; a corrupt/partial file falls back
  to an empty buffer without crashing (defensive parse, like `TimerStore._load_file`).
- File writes are **atomic**: write to a temp file in the same directory, then
  `os.replace()` onto `chat.json`, so a crash mid-write never corrupts the history.

Methods:

| Method | Behavior |
|---|---|
| `add(user, text, now)` | Validate (see Validation); set `ts = now` (server clock, never client); append; enforce ring cap; save file. Returns `{"ok": True, "message": {...}}` or `{"error": "..."}`. |
| `data()` | Returns `{"messages": [...]}` — the current buffer. |
| `reload()` | Re-read `runtime/chat.json` into the in-memory buffer. On success replaces the buffer and returns `{"ok": True, "count": N}`. On a parse failure it **keeps the current buffer** and returns `{"error": "..."}` (a bad reload must not wipe live state). |

### 2. Endpoints (same dispatch pattern as today)

Added to `do_GET`/`do_POST` in the relay handler (path-split routing, `self._send`
JSON responses, the existing 65 KB POST-body cap):

| Endpoint | Method | Action |
|---|---|---|
| `/chat/data` | GET | `chat_store.data()` — polled by the panel every 2 s. |
| `/chat/send` | POST | Body `{user, text}` → `chat_store.add(...)`. The **only** remote write path; bounded and validated. |
| `/chat/reload` | GET | `chat_store.reload()` — re-reads the local `chat.json` into memory. Non-destructive by itself: triggering it from the tailnet only re-reads the local file. |

There is deliberately **no** destructive HTTP endpoint (no `/chat/clear`,
no `/chat/import`). Clearing/importing/pulling all funnel through a **local file
write** followed by `/chat/reload`. Consequence: the only way to overwrite or wipe the
history requires local filesystem access on the producer machine; a tailnet peer can
only append one bounded message at a time.

### 3. Validation (server-side, in `ChatStore.add` and on every import)

- `text`: required, non-empty after trim, truncated to `MAX_TEXT = 500` chars,
  control characters stripped (keep normal whitespace).
- `user`: optional, truncated to `MAX_NAME = 40` chars, control characters stripped;
  empty falls back to a default label (`"Crew"`).
- `ts`: always set by the server; any client-supplied `ts` is ignored on `send`.
  On import, each message's `ts` is coerced to a float; missing/invalid → dropped.

### 4. Panel UI (`src/director/director-panel.html`)

- A new collapsible **Chat** section (bus row, like Timer/Setup/Schedule).
- **Name:** first use shows an inline name input; the value is stored in
  `localStorage` (`racecast.chat.name`) and is editable any time. It is sent as
  `user` on each `POST /chat/send`.
- **History:** scrollable list, newest at the bottom, auto-scrolled to bottom on new
  messages when already at the bottom. Each line shows `time · name · text`.
  **Rendering uses `textContent` only** (never `innerHTML`) → no HTML/script
  injection from message content.
- **Input:** text field + send button; Enter sends.
- **Unread badge:** the client stores the highest `ts` it has displayed while the
  section was open/focused (`localStorage: racecast.chat.lastSeenTs`). When the
  section is collapsed or not focused and `/chat/data` returns messages with
  `ts > lastSeenTs`, a count badge appears on the section header. Opening/scrolling to
  the bottom marks all as seen (updates `lastSeenTs`) and clears the badge. No sound.
- **Polling:** `chatPoll()` on the existing 2 s cadence (`setInterval(chatPoll, 2000)`),
  alongside the other pollers.

### 5. Producer actions — clear / pull / import / export

All are **CLI** actions under a new `racecast chat` command group (`src/racecast.py`),
with pure, testable logic in a new `src/scripts/chat_admin.py` (mirrors
`profile_admin.py`). The Control Center exposes **only** clear.

| Command | Behavior |
|---|---|
| `racecast chat clear` | Atomically write an empty history to `runtime/chat.json`; if the local relay is running, `GET http://127.0.0.1:8088/chat/reload` so memory matches. Control Center "Clear chat" button calls the same logic. |
| `racecast chat pull <tailscale-ip> [--port 8088]` | Take over another producer's history. See Handover below. Works whether or not the local relay is already running. |
| `racecast chat import <file>` | Validate a `chat.json`-shaped file, atomically write it to `runtime/chat.json`, reload if the relay is running. |
| `racecast chat export [--out <file>]` | Read the live history (local relay `/chat/data` if running, else `runtime/chat.json`) and write it to a file for offline handoff (Taildrop/USB). |

### 6. Producer handover — `chat pull`

A producer change moves the relay to another machine; the new producer prepares
everything in advance (their relay may already be running) and, at a coordinated,
freely chosen moment, pulls the in-flight chat from the old, still-running relay over
the tailnet. The pull **overwrites** the local history.

Flow (`racecast chat pull <ip>` on the new machine):

1. `GET http://<ip>:<port>/chat/data` with a short timeout.
2. **Success gate** — proceed only if the response is HTTP 200, parses as JSON, and
   has the expected shape (top-level object with a `messages` list of
   `{ts, user, text}` entries). Sanitize every entry (same Validation rules). A
   well-formed but **empty** `messages` list is valid and allowed (e.g. pulling
   before anyone has written) — it overwrites the local history with an empty one;
   only a malformed shape is a failure.
3. Atomically write the validated history to local `runtime/chat.json`.
4. If the local relay is running, `GET http://127.0.0.1:<localport>/chat/reload` so
   the running relay adopts the new history immediately. If the relay is not running,
   skip — it loads the file on next start.

**Hard error rule:** any failure in steps 1–2 (connection refused, timeout, non-200,
malformed JSON, wrong shape) **aborts the pull and leaves the local `runtime/chat.json`
untouched.** (A valid, empty history is not a failure — see step 2.) The local state is overwritten only when a
complete, valid response is in hand. The command reports a clear error and exits
non-zero. A step-4 reload failure is **not** fatal to the file (the file is already
updated; the next start loads it) but is reported.

Because `ts` is wall-clock and preserved across the pull, the directors' unread state
stays correct after they reconnect to the new relay: pulled messages keep their old
`ts`, and any message typed on the new relay gets `ts = now`, always greater than
anything pulled.

`event start` integration (`--from-host`) is explicitly **out of scope** — the pull is
a separate, explicit, freely-timed command.

## Error states (summary)

| Condition | Behavior |
|---|---|
| `POST /chat/send` empty/oversized/invalid | Rejected with `{"error": ...}`; panel surfaces it via the existing `d.error` toast/log path. Text is truncated, not rejected, when only too long. |
| `chat.json` corrupt at startup | Defensive parse → empty buffer, relay starts normally. |
| `/chat/reload` on a corrupt file | Current in-memory buffer kept; `{"error": ...}` returned; live chat unaffected. |
| `chat.json` write fails (OSError) on `add` | Best-effort: in-memory append still succeeds; failure logged, not fatal. |
| `chat pull` fetch/validate failure | Abort; local `chat.json` untouched; non-zero exit with a clear message. |
| `chat pull` reload failure (relay down/unreachable) | File already updated; reload skipped/reported; loads on next start. |
| `chat import` malformed file | Validation fails before any write; local `chat.json` untouched. |

## Security / trust boundary

- The relay stays **unauthenticated**; the **tailnet is the trust boundary** (same as
  `/panel`, `/status`, and every existing endpoint). Documented, not changed.
- Display names are self-declared and spoofable — acceptable for a trusted crew, and
  stated explicitly.
- Chat content is visible to anyone on the tailnet (exactly like `/panel` today) — the
  chat does not widen the existing boundary.
- The remote attack surface is intentionally minimal: `POST /chat/send` (one bounded,
  validated message) and `GET /chat/reload` (re-reads the local file only).
  Destructive operations (clear/import/pull-overwrite) require local filesystem access
  on the producer machine.
- Message rendering in the panel uses `textContent` only → no stored-XSS from chat
  content.

## Testing (`tests/test_chat.py`, stdlib style, no network, no real IPs)

- `ChatStore.add`: appends; sets `ts` from the `now` parameter (not client); truncates
  `text`/`user` to caps; strips control characters; rejects empty text; enforces the
  ring-buffer cap (oldest dropped); default name fallback.
- `ChatStore` persistence: `save → load` round-trip; corrupt/partial file → empty
  buffer, no crash.
- `ChatStore.reload`: replaces the buffer from a valid file; a corrupt file keeps the
  current buffer and signals an error.
- `ChatStore.data`: returns the current messages.
- `chat_admin` validation/sanitization (the `pull`/`import` gate): rejects a payload
  that is not a dict, whose `messages` is not a list, or whose entries miss/invalid
  fields; sanitizes lengths and control characters; drops entries with invalid `ts`.
- "Only on success" guarantee: given a payload that fails validation, the existing
  `chat.json` fixture is left byte-for-byte unchanged (the write never happens).
- Atomic write helper: writes a temp file then replaces the target.

The network fetch in `chat pull` is a thin, separated shell; the validate → write →
reload-decision logic is pure and fully unit-tested without any real IP or socket
(per the repo rule: tests run on any machine and in CI).

## Files touched

- `src/relay/racecast-feeds.py` — `ChatStore` class; `/chat/data`, `/chat/send`,
  `/chat/reload` endpoints; store construction + `runtime/chat.json` path wiring.
- `src/director/director-panel.html` — chat section UI, polling, name handling,
  unread badge.
- `src/racecast.py` — `chat` command group (`clear`, `pull`, `import`, `export`).
- `src/scripts/chat_admin.py` — new: pure pull/import/export/clear logic + atomic
  write + payload validation.
- `src/racecast_ui.py` + `src/ui/` — "Clear chat" op (registry + button), calling the
  same `chat_admin` clear logic.
- `tests/test_chat.py` — new test file.
- Docs: `CLAUDE.md` relay/architecture note, wiki Director-Panel page, README command
  list (`racecast chat …`).

## Out of scope (YAGNI)

No @-mentions, no direct messages, no typing indicators, no sound, no identity proof,
no per-message edit/delete, no Control Center chat widget (clear button only), no
Sheet-backed chat, no `event start --from-host` auto-pull, no SSE/real-time push.
