# Platform-dependent Discord audio capture source — design

**Date:** 2026-06-05
**Status:** approved (producer play-test follow-up)

## Problem

The OBS collection captures the Discord interview audio with one source,
`Discord Audio Capture` (uuid `0085d4f3-bf43-4aef-9fe4-28cfd3270c7d`). That
source is macOS-only (`sck_audio_capture`, ScreenCaptureKit App Audio
Capture). On Windows the equivalent is a different source type
(`wasapi_process_output_capture`, "Application Audio Capture"), on Linux a
third (the PipeWire app-audio plugin). One committed source cannot serve all
three platforms — importing the collection on Windows yields a dead audio
source (observed in the Windows producer play-test).

A manual Windows export further showed that OBS stores the **live window
title** in the window spec (`"Interviews | … - Discord:Chrome_WidgetWin_1:
Discord.exe"`); the title embeds the current Discord channel name and goes
stale on every channel switch — a hand-configured source is fragile even on
one machine.

## Decision (approach B: platform swap in place)

Keep **one** logical source in git and localize it per platform, exactly like
the asset tokens: `setup-assets.py` already runs on the target machine, so
the platform is known at localize time.

- **Canonical form (committed):** the existing macOS source, unchanged. The
  template stays a real OBS export from a Mac.
- **`src/setup-assets.py`:** new constant table `DISCORD_AUDIO_VARIANTS` and
  a step `localize_discord_audio(collection, platform)` that finds the source
  by uuid and replaces `id`, `versioned_id`, and `settings`:

  | platform | `id` | `settings` |
  |---|---|---|
  | `darwin` | `sck_audio_capture` | `{"application": "com.hnc.Discord", "type": 1}` (no-op) |
  | `win32` | `wasapi_process_output_capture` | `{"window": "Discord:Chrome_WidgetWin_1:Discord.exe", "priority": 2}` |
  | `linux` | `pipewire_audio_application_capture` | `{"TargetName": "Discord", "MatchPriorty": 0}` |

  Windows `priority: 2` is `WINDOW_PRIORITY_EXE` (verified in obs-studio
  `libobs/util/windows/window-helpers.h`: CLASS=0, TITLE=1, EXE=2) — the
  source matches any window of `Discord.exe`, channel titles never matter.
  Linux uses the dimtpap `obs-pipewire-audio-capture` plugin (source id and
  the `MatchPriorty` settings-key TYPO verified in the plugin source;
  `MatchPriorty: 0` = match by binary name). The plugin ships separately from
  OBS; Linux stays documented as untested.

- **`tools/tokenize-obs.py`:** the reverse normalization. A source with the
  known uuid — whatever platform variant the export contains — is folded back
  to the canonical macOS form. Round-trips from Mac AND Windows produce the
  identical committed template; volatile hand-configured window strings are
  deliberately replaced by the generated generic form.

- Scene items are untouched (same uuid, same name) — no structural surgery,
  no dead twin sources, no item-id bookkeeping.

## Error handling

- Source uuid not found in the collection: print a warning, continue
  (same pattern as missing graphics — never fail the localize).
- Unknown platform: leave the canonical macOS form, print a note.

## Testing

Stdlib tests (new `tests/test_discord_audio.py`, auto-discovered by
`tools/run-tests.py`), against minimal collection dicts:

- per-platform swap produces the exact id/settings from the table
- localize is idempotent (running twice = running once)
- missing uuid → unchanged collection + warning, no exception
- tokenize direction: a Windows/Linux variant folds back to canonical;
  canonical input is a no-op
- the localized OBS collection keeps scene items untouched

Real-data check: the producer's Windows export
(`IRO_Endurance.json`, both variants) provided the settings shapes.

## Docs

- Wiki `OBS-Setup` + `README_SETUP.md` Discord-audio paragraphs: `iro setup`
  generates the platform-correct source; Linux needs the PipeWire app-audio
  plugin (untested).

## Out of scope

- Auto-installing the Linux PipeWire plugin.
- Migrating other sources to platform variants (none needed today).
