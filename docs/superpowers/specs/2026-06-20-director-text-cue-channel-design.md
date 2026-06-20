# Director→Talent Text-Cue Channel (IFB-lite) — Design

- **Issue:** #243 (follow-up from #192 VDO.Ninja gap analysis)
- **Date:** 2026-06-20
- **Status:** Approved design, ready for implementation plan

## Summary

A **directed, text-only cue channel** from the director to the talent cockpit — a
lightweight stand-in for an IFB/talkback earpiece. The director sends a short cue
("Wrap up", "Throw to pit", "2 min to handover", "You're hot — mic live") that appears
**prominently and unmissably** in a specific commentator's cockpit, broadcast to all
talent, or routed to whoever is currently on air. No audio, no WebRTC — text only.

This closes the text-cue subset of the IFB gap explicitly flagged as a possible follow-up
in #192 ("~80% of the IFB need without audio infra"). It reuses the proven relay patterns
shipped for crew chat (#191) and self-service submissions (#193): a thread-safe ring-buffer
store persisted to `runtime/<profile>/`, token-gated endpoints, and `console_policy`
role checks. **Audio talkback and one-off guest ingest remain deliberate non-goals.**

## Decisions (locked during brainstorming)

| Question | Decision |
|---|---|
| Cue lifetime | **Two tiers.** `info` cues auto-expire after a TTL; `critical` cues stay sticky until acknowledged. |
| Targeting | A specific commentator **·** all talent (`"all"`) **·** "on air" shortcut (resolved server-side to the on-air streamer's key at send time). |
| Input | Sheet-managed **presets** (read-only in the panel) **+** free text. |
| Acknowledgement | Director sees **✓ seen** with a timestamp for critical cues (ack receipt). |
| State model | **Append-only cue log** (mirrors `ChatStore`/`SubmissionStore`), client-side active-set filtering. |
| Preset source | A **`Cue Preset` column in the existing Configuration tab**, read via the already-polling `HudSource`. No per-preset level. |

## Non-goals

- Native audio talkback / IFB.
- WebRTC / SRT / RTMP ingest of any kind.
- Server-configurable presets beyond the Sheet column; per-preset level; cue management CLI.
- Carrying cues across a producer takeover (#189) — cues are ephemeral "for now" commands.
- SSE/push delivery — the relay is poll-based everywhere; cues poll like chat.

## Architecture

The feature mirrors the crew-chat architecture one-to-one. Three layers:

1. **Pure logic module `src/scripts/cue_admin.py`** (new, stdlib only) — modeled on
   `chat_admin.py` + `cockpit_submissions.py`:
   - `sanitize_cue(entry)` — validate/normalize: numeric `ts`, `level ∈ {info, critical}`,
     `target` shape (`<streamer_key>` or `"all"`), `text` capped (~200 chars), control-chars
     stripped, Unicode line-breaks collapsed. Invalid → `None` (rejected). Applied on send
     **and** on reload (dual gate, like chat).
   - `load_cues(path)` / `write_cues(path, cues)` — atomic JSON read/write.
   - `resolve_target(raw_target, on_air_key)` — pure: maps the panel's `"on-air"` selection
     to the concrete on-air `streamer_key` (or returns `<key>`/`"all"` unchanged). Returns
     `None`/empty when on-air is requested but nobody is on air (caller surfaces an error).
   - `active_cues_for(cues, streamer_key, now, info_ttl)` — pure: returns the cues whose
     `target` is `streamer_key` or `"all"` that are still **active** — `info` while
     `now < ts + info_ttl`, `critical` while `ack is None`. The core unit-tested helper.
   - `prune(cues, now, info_ttl)` — drop expired `info` and acked `critical` entries; applied
     on load (a relay restart carries no stale cues) and bounded to `MAX_CUES`.
   - Monotonic `id` allocation (like `cockpit_submissions` entry ids).

2. **`CueStore`** in `src/relay/racecast-feeds.py` (next to `ChatStore`) — thread-safe
   wrapper: `add(target, level, text, from_name, on_air_key)`, `list()`, `ack(cue_id, key)`,
   `reload()`. Persists to `runtime/<profile>/cues.json`, cap `MAX_CUES = 100`, prunes on
   load. `ack(cue_id, key)` only sets `ack` when the cue's `target` is `key` or `"all"`
   (server-side scope enforcement, mirroring `own_submission_target`).

3. **Preset source** — `HudSource` already fetches & polls the Configuration tab. Add a pure
   `parse_cue_presets(text)` (header-located via `CUE_PRESET_HEADERS = ("cue preset",
   "cue presets", "cue")`, exactly like `parse_config_vocab` / `BRAND_TEXT_HEADERS`), store
   the list in `HudSource._cue_presets`, expose `hud_source.cue_presets()`. No second fetch
   of the same tab. When HUD is disabled (`--no-hud`), there is no preset source → the panel
   shows free-text only (graceful degradation); cues themselves are unaffected.

### Cue entry shape (`runtime/<profile>/cues.json`)

```json
{
  "id": 7,
  "ts": 1718900000.0,
  "target": "max-mustermann",
  "level": "critical",
  "text": "You're hot — mic live",
  "from": "Director Name",
  "ack": { "ts": 1718900005.0 }
}
```

`target` is `"all"` for a broadcast; the `"on air"` shortcut is resolved to a concrete
`streamer_key` **at send time** (a cue is for whoever was on air when sent). `ack` is `null`
until acknowledged and is only meaningful for `critical` cues.

## Endpoints & authorization

Same split as crew chat (talent, identity-forced) vs. director ops (`/next`, `/reload`).
All four reach the public surface only through the **existing `/console` mount** — no new
funnelled path.

| Endpoint | Role | Funnel path | Purpose |
|---|---|---|---|
| `POST /cues/send` | **director** | `/console/cues/send` | Send a cue: `{target, level, text}` |
| `GET /cues/data` | **director** | `/console/cues/data` | Full list + ack status (panel) |
| `GET /cues/presets` | **director** | `/console/cues/presets` | Sheet-managed preset list (read-only) |
| `GET /cues/reload` | **director** | — | Re-read `cues.json` |
| `GET /cockpit/cues` | any-auth, **identity-scoped** | `/console/cockpit/cues` | Only *my* active cues |
| `POST /cockpit/cues/ack` | any-auth, **identity-scoped** | `/console/cockpit/cues/ack` | Acknowledge a critical cue addressed to me |

- **Root vs. `/console` (same model as `/next`/`/chat/send`):** the endpoints are registered
  at the root paths (`/cues/*`, `/cockpit/cues*`). Reached at the tailnet root (the local
  `/panel`), they are unauthenticated — the tailnet is the trust boundary, exactly like
  today's `/next` and root `/chat/send`. Reached via the public Funnel, `_console_gate`
  routes `/console/cues/*` to the same handlers **with** the policy check below. So the
  "Role" column applies to the funnelled (`/console/…`) path; the root path inherits the
  existing unauthenticated-relay model.
- Director routes require the `director` role via `console_policy.decide(...)`. New policy
  entries: segment `cues` → director (GET + POST); `cockpit/cues` → any authenticated
  (read + ack). Covered by `tests/test_console.py` additions.
- Talent routes are identity-forced (like `/cockpit/chat/*`): `GET /cockpit/cues` scopes to
  the token's `streamer_key`; `POST /cockpit/cues/ack` can only ack a cue whose `target` is
  that key or `"all"`.
- **Rate limits** per identity (not IP — Funnel-safe), via `console_auth.RateLimiter`:
  send 30/60 s, ack 30/60 s.
- `POST /cues/send` resolves `target == "on-air"` server-side from the on-air feed (reusing
  the `cockpit_tally` on-air→streamer mapping). If nobody is on air, the send returns an
  error and writes nothing.

## UI

### Director Panel (`src/director/director-panel.html`) — new "Cues" section
- **Preset buttons** rendered from `GET /cues/presets` (read-only; no hardcoded list).
  Clicking a preset fills the **free-text field** (still editable) — free text is always
  available in addition.
- **Target** dropdown: each commentator (from the schedule/crew) · `All` · `On Air`.
- **Level** toggle: `Info` / `Critical` (chosen at send time; presets carry no level).
- **Recent cues** list (from `GET /cues/data`): shows each sent cue with its target, level,
  text, and **✓ seen + timestamp** for acknowledged critical cues.

### Commentator Cockpit (`src/cockpit/cockpit.html`) — new cue receiver
- A 4th poller `pollCues()` (~3 s) on `GET /cockpit/cues` (alongside tally/program/timer/chat).
- **Critical** cue → a large, persistent banner with an **Acknowledge** button; it stays
  until the ack POST succeeds.
- **Info** cue → a lighter toast that auto-fades after the TTL.
- All cue text rendered via `textContent` (XSS-safe).

Both surfaces change visibly → per the repo's hard rule, the wiki screenshots
`src/docs/wiki/images/director-panel.png` and the cockpit image are regenerated from a local
dev build **in the same change**.

## Constants

- `INFO_CUE_TTL_S = 30` — info-cue auto-expiry window.
- `MAX_CUES = 100` — ring-buffer cap.
- Rate limits: send 30/60 s, ack 30/60 s.
- `CUE_PRESET_HEADERS = ("cue preset", "cue presets", "cue")` — Configuration-tab column.

## Error handling & edge cases

- **Fetch/parse failures** of the preset column degrade like every other sheet source:
  last-good cache, then empty → panel shows free-text only.
- **On-air send with nobody on air** → error response, nothing written.
- **Ack of a foreign cue** (target is neither my key nor `"all"`) → rejected server-side.
- **Sanitization rejects** (bad level/target/over-long text) → `{"error": ...}`, no write.
- **Relay restart** → `load_cues` prunes expired/acked entries; an unacked `critical` cue
  survives a restart (it is still "for now"), expired `info` cues do not.
- **Funnel boundary unchanged** — feed URLs, `/status`, OBS-WebSocket stay tailnet-only.

## Testing

- **`tests/test_cues.py`** (new, stdlib-runnable, house style): `sanitize_cue`
  (caps/control-chars/level+target validation/reject), `resolve_target` (on-air→key, none
  on-air), `active_cues_for` (info TTL expiry, critical sticky-until-ack, target match
  me/`all`, scope isolation from other keys), `prune` + `MAX_CUES`, monotonic id, `ack` sets
  the ack and respects scope.
- **`tests/test_console.py`**: extend the policy matrix for `cues` (director) and
  `cockpit/cues` (any-auth read+ack).
- **CLI flag grep:** no flag is removed; a new `--cues-tab` is **not** added (presets live in
  the Configuration tab, read via `--config-tab`). If a flag is later introduced, grep
  `tools/` + `.github/` per the repo rule.
- Optional: a synthetic e2e check could assert `POST /cues/send` → `GET /cockpit/cues`
  round-trip, but the unit suite is the primary guard.

## Files touched

- `src/scripts/cue_admin.py` — **new** pure module.
- `src/relay/racecast-feeds.py` — `CueStore`, the 6 endpoints, policy wiring, `parse_cue_presets`
  + `HudSource._cue_presets` / `cue_presets()`.
- `src/scripts/console_policy.py` — `cues` + `cockpit/cues` policy entries.
- `src/director/director-panel.html` — Cues section (presets + free text + target/level + recent/ack).
- `src/cockpit/cockpit.html` — cue receiver banner/toast + `pollCues()` + ack.
- `tests/test_cues.py` — **new**; `tests/test_console.py` — extended.
- `src/docs/wiki/images/director-panel.png` + cockpit image — regenerated.
- Docs: a short note in the relevant wiki page / `CLAUDE.md` relay section describing the
  cue channel and the `Cue Preset` Configuration column.
