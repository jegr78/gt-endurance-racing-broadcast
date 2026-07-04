# Discord voice-channel join (RPC) — design

**Status:** validated live (2026-07-04). Feasibility proven end-to-end on macOS against a
real Discord desktop client — see the spike scripts under the session scratchpad and the
memory `discord-rpc-voice-join-proven`.

## Goal

One command / one Control-Center button that makes the **local Discord desktop client**
join a league's **voice channel**, so OBS's `obs-pipewire-audio-capture` picks up that audio
for the broadcast. This unblocks a fully SSH-only cloud producer (#395) — the box no longer
needs a RustDesk session just to click "Join Voice" — and is equally useful to a **local
producer** (one-click join from the Control Center on Windows/macOS/Linux).

## Why the desktop client (not a bot)

The broadcast audio path is: **desktop Discord → machine audio device → OBS PipeWire
capture**. Only the desktop client puts voice audio on that device. A bot or a self-bot
joins in a *separate* process, so its audio never reaches OBS; a self-bot additionally
violates Discord's ToS. Therefore the automation must drive the **desktop client itself**,
which Discord exposes locally through its **RPC IPC socket**.

## Proven mechanism (do not re-derive)

All over the local IPC socket (`$XDG_RUNTIME_DIR|$TMPDIR|/tmp/discord-ipc-{0..9}`, incl.
snap/flatpak subdirs; Windows named pipe `\\?\pipe\discord-ipc-{0..9}`). Frame =
`<int32-LE opcode><int32-LE length><json>`.

1. **handshake** `{v:1, client_id}` → READY.
2. **AUTHORIZE** `{client_id, scopes:["rpc"]}` → `code`. The `rpc` scope is allow-list-gated
   by Discord **but the application OWNER (and team members) bypass the allow-list** — this
   is why no Discord approval is needed. The one-time consent popup appears in the desktop
   client.
3. **token exchange** `POST https://discord.com/api/oauth2/token` (through `http_util`) with
   `client_id` + `client_secret` + `grant_type=authorization_code` + `code` +
   `redirect_uri=http://localhost`. Returns `access_token`, `expires_in≈604800` (7 d), and a
   **`refresh_token`**.
4. **AUTHENTICATE** `{access_token}` → authed.
5. **SELECT_VOICE_CHANNEL** `{channel_id, force:true}` → the desktop client joins (or moves);
   `{channel:null}` leaves. The response carries the channel `name` (for status display).

**Consequence:** the consent is a **one-time** action. We cache `access_token` +
`refresh_token` + expiry and refresh silently, so every later join is non-interactive
(hands-free). On the headless box the single consent is clicked once over RustDesk, then
never again.

## Configuration

Reuses the per-league Discord app already used for `/console` OAuth:
`DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` (in `profile.env`, already surfaced by
`config.py`). The app needs **`http://localhost` registered as an OAuth redirect** (one-time,
documented setup step).

**Voice-channel target — Sheet override, profile.env fallback** (the user's choice):

- **Sheet override:** the **Configuration** tab, header **`Discord Voice`** (value is a
  `https://discord.com/channels/<guild>/<channel>` link). Read via the public gviz CSV
  endpoint, the same mechanism the relay/`get-graphics` already use — so the league owner can
  change the channel without a file edit. Header located like the existing `Cue Preset` /
  brand-text columns.
- **Fallback:** `profile.env` `DISCORD_VOICE_URL` (same link form). Travels with
  `profile export`; surfaced by `config.py` as `discord_voice_url` and injected as
  `RACECAST_DISCORD_VOICE_URL`.
- Resolution: Sheet value wins when non-empty, else the env fallback. The link is parsed to
  `(guild_id, channel_id)`; a malformed/blank target means "no voice configured" (the
  command reports it cleanly, the CC button is disabled).

## Surface

- **CLI:** `racecast discord join` (resolve target → ensure token → SELECT_VOICE_CHANNEL),
  `racecast discord leave`, `racecast discord status` (cached-token + current-channel view).
- **Control Center:** a **Join / Leave voice** control showing the resolved channel and
  connection state, backed by structured op/data providers + routes (mirrors the existing
  `racecast app launch|quit` buttons).
- **Auto-join on `event start`: default ON.** Best-effort — if a voice target resolves and a
  cached token exists, attempt the join (never fatal; a missing token just prints "run
  `racecast discord join` once to consent"). Kill-switch `RACECAST_DISCORD_AUTOJOIN=0`
  (machine `.env`) disables it. This is what makes the cloud producer fully hands-free.

## Architecture / files

- **`src/scripts/discord_rpc.py` (new, pure + seams):** socket-path resolution
  (cross-platform), frame encode/decode, the message builders (handshake/authorize/
  authenticate/select-voice), the channel-link parser, the token-cache load/expiry/refresh
  logic, and the Sheet-override→env-fallback target resolver. All pure and unit-tested; the
  actual socket connect, the `http_util` token calls, and the gviz fetch are injected seams
  (the established pattern, e.g. `tool_version`/`obs_ws`).
- **Token cache:** `runtime/<profile>/discord-rpc-token.json` (lock-guarded JSON like the
  other stores; contains tokens — gitignored runtime, never logged/printed).
- **`src/racecast.py`:** `discord` verb dispatch + the optional `event start` hook; reads
  `RACECAST_DISCORD_CLIENT_ID/SECRET/VOICE_URL` from the active-profile env.
- **`src/scripts/config.py`:** add `discord_voice_url` (from `DISCORD_VOICE_URL`).
- **Control Center (`src/ui/…`, `src/racecast_ui.py`):** op + data provider + button.

**Security/consistency:** the client_secret stays on the producer machine, used only for the
token exchange, never logged. All outbound HTTP goes through `http_util` (UA guard) — the
throwaway spike used bare urllib; shipped code must not. The RPC IPC socket is local-only
(no network surface).

## Testing

Pure unit tests (`tests/test_discord_rpc.py`, stdlib, Windows-safe): socket-path candidate
ordering (POSIX vs `nt`, with explicit `/` for any fixed-OS path), frame encode/decode round
trip, channel-link parser (valid / malformed / blank), target resolver (sheet override vs env
fallback vs none), token-cache expiry + refresh decision. The IPC/HTTP/Sheet I/O is exercised
through seams with fakes — no real Discord, no network, runs in CI.

## Out of scope

- Capturing/mixing the audio itself (that is OBS + the PipeWire plugin, already provisioned;
  confirmed at the #421 box test).
- Non-NVIDIA / non-Discord audio routing.
- Any bot / self-bot path (rejected above).
