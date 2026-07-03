# Ad-hoc stream substitution — capture, notify, report

**Status:** Design — approved direction, pre-implementation.
**Date:** 2026-07-03
**Area:** relay (`src/relay/racecast-feeds.py`), `src/scripts/notify.py`, `src/scripts/health_store.py`, `src/scripts/report_build.py`, `src/director/director-panel.html`.

## Problem

A commentator's stream can break mid-stint. The producer handles it *ad-hoc* — they find an
alternative stream, put its URL on the on-air feed, and force-reload. **The feed mechanism
already covers this** (edit the on-air feed URL + `/reload`); the schedule is NOT adjusted.

What is missing is a *record* of the substitution. Today the post-event report
(`report_build.py`) derives incident bands from the sampled Health data, so the **outage**
already shows up — but the **recovery action** (the producer swapping to an alternative
stream) is invisible. A league owner reviewing the report cannot see that Feed A's stream
was substituted at HH:MM, nor why. This scenario should be captured for the report **and**
announced live on Discord like the other broadcast-health events.

## Scope

- Auto-detect an ad-hoc substitution and record it as a discrete Health-DB event.
- Post a Discord notification on capture (best-effort, like the OBS-stream / failover posts).
- Let the producer attach an optional free-text **reason** to the most recent substitution
  from the Director Panel.
- Surface substitutions in the post-event report.

Out of scope (YAGNI): no per-event note picker (only the latest substitution is annotatable);
no raw-URL storage or display; no POV-feed substitution (POV is the driver PiP, not a
commentator); no automatic reason inference; no Sheet/Companion change; no re-post to Discord
when a reason is added later (the reason is a report/Panel annotation).

## Definitions

- **Commentator feed:** Feed A or Feed B. The POV feed is excluded.
- **On-air feed:** `relay.live_feed()`.
- **Substitution:** the on-air commentator feed begins serving a *different, non-empty* URL at
  the *same* stint index, triggered by an operator `/reload` or `/set` — NOT by a `next_auto`
  handover/continuation, and NOT a self-healing reconnect to the *same* URL.

The discriminator is the **URL change at an unchanged stint**. A stream that drops and
recovers on the same URL is not a substitution (the outage already shows as an incident band
from samples); a handover to the next stint is not a substitution (different stint / the
`next_auto` path).

## Design

### 1. Detection (pure) + capture (relay)

Pure predicate (unit-testable, no I/O):

```
def is_substitution(served_url, served_idx, new_url, new_idx):
    """True when the on-air feed swaps to a different non-empty URL at the same stint
    (operator reload/set), i.e. an ad-hoc stream substitution. Pure."""
    return bool(new_url) and bool(served_url) and new_idx == served_idx and new_url != served_url
```

Each commentator `Feed` tracks the URL it is actively serving (`served_url`) and the index it
belongs to (`served_idx`), set when the feed (re)connects. The relay's **operator reconnect
paths** — `Relay.reload(...)` and `Relay.set_index(...)/set(...)` — evaluate `is_substitution`
for the **on-air feed** using its tracked `served_url`/`served_idx` versus the freshly
resolved URL/index. `next_auto` (handover/continuation) does NOT call it. On a True result the
relay records a discrete event and fires Discord:

```
self.health_store.record_event(now, "feed_substitution", producer=self.producer_name,
                               metadata={"feed": live, "stint": served_idx + 1})
self._discord_post(notify.substitution_discord_payload(
    live, served_idx + 1, self.producer_name, self._event_title()), "feed-substitution")
```

Best-effort, mirroring `_on_stream_transition`: a missing `health_store` or webhook is a
silent no-op; nothing here can raise into the reload path.

**No raw URLs are stored** — metadata carries only `feed` + `stint`. The streamer name is
resolved at report time via the existing `name_for_stint` join (matching the report's
name-attribution decision), so an unlisted alternate link never enters the DB or a shareable
Discord report.

### 2. Discord notification (`notify.py`)

A pure payload builder alongside `obs_stream_discord_payload`:

```
def substitution_discord_payload(feed, stint, producer, event_title=""):
    """Discord embed announcing an ad-hoc on-air stream substitution (feed A/B, 1-based
    stint). Yellow, no @here — it is an informational recovery marker, not an outage alarm
    (the outage itself already pings). Pure."""
    title = "Stream substituted"
    desc = f"The on-air stream on Feed {feed} was substituted mid-stint (stint {stint})."
    return _payload(title, desc, color=0xF9A825, ping=False,
                    event_title=event_title, producer=producer)
```

`ping=False`: the outage that prompted the swap already fired the `@here` DEGRADED/red alarm;
the substitution is a follow-up marker, so it must not double-ping. Color reuses the health
yellow.

### 3. Reason nachtragbar (Director Panel + relay)

A new director-gated endpoint `POST /substitution/note` sets a free-text `reason` on the
**most recent** `feed_substitution` event. This needs one small `health_store` addition:

```
def annotate_latest_event(conn, event_type, patch, now=None):
    """Merge `patch` into the metadata of the most recent event of `event_type`; return the
    updated row or None when none exists. Used to attach a reason to the latest substitution."""
```

The relay wraps it (`HealthStore.annotate_latest_event`) and the endpoint sanitizes the reason
(length cap ~200 chars, control-char strip — a small pure `sanitize_reason`, same model as the
chat/cue sanitizers) before storing `{"reason": <clean>}`.

**Director Panel section (styling — verify carefully).** Add a compact section that MATCHES the
existing Panel section pattern exactly: a `<section class="bus">` with a `<div class="cap">…</div>`
label header, identical to the Feeds / HUD / Scn·Vis sections (`src/director/director-panel.html`).
It shows the most recent substitution (`Feed A · HH:MM · Stint N`), a single-line reason input,
and a Save button; it **self-hides** when there is no substitution (like the broadcast-chat card
self-hiding). Reason renders via `textContent` (XSS-safe, like chat/cues). Data comes from a
read side — either a small `GET /substitution/latest` or a field folded into an existing panel
poll (`/status`); reuse an existing poll if one already carries per-event data to avoid a new
timer. **The `director-panel.png` wiki screenshot is refreshed in the same change**, and the
change is validated with the `ui-visual-verification` skill before completion (blocking Stop
hook). Styling parity — spacing, cap label, input/button — is an explicit acceptance criterion,
not a "later" polish.

### 4. Report rendering (`report_build.py`)

Mirror the `takeover` handling in `build_report`: collect `feed_substitution` events into a
`substitutions` list and add it to the report dict.

```
substitutions = []
for e in events:
    if e.get("type") == "feed_substitution":
        md = e.get("metadata") or {}
        substitutions.append({"ts": e.get("ts"), "feed": md.get("feed") or "",
                              "stint": md.get("stint"),
                              "streamer": name_for_stint(md.get("stint")),
                              "reason": md.get("reason") or ""})
# report["substitutions"] = substitutions
```

`render_html` gains a "Stream substitutions" section (a table: Time · Feed · Stint · Commentator
· Reason), rendered only when non-empty, and the count is surfaced in the KPI/incident area next
to the existing incident count. Names are resolved at report time (the report's existing
caveat about name attribution already covers this). Substitution events ride the same Health DB,
so `event takeover`'s health pull/merge carries them across producer machines (dedup by `ts`) —
no special handling.

## Testing

Pure unit tests (stdlib, runnable-script style):
- `is_substitution`: URL-change-same-stint → True; same URL → False; different stint → False;
  empty new/served URL → False.
- `substitution_discord_payload`: title/desc/color/`ping=False`, event_title + producer wired.
- `sanitize_reason`: length cap, control-char strip, empty passthrough.
- `health_store.annotate_latest_event`: patches only the latest matching event; None when absent;
  leaves other events untouched.
- `report_build.build_report`: collects substitutions, resolves the name via `name_for_stint`,
  carries the reason; `render_html` emits the section only when non-empty and escapes the reason.
- Relay capture: an on-air `reload`/`set` that changes the served URL at the same stint records
  exactly one `feed_substitution` (and a same-URL reload / a `next_auto` handover records none).
- Endpoint: `POST /substitution/note` is director-gated and annotates the latest event; the panel
  read side returns the latest substitution (or none).

Docs/visual: refresh `src/docs/wiki/images/director-panel.png`; run `ui-visual-verification` on the
Panel section; add `feed_substitution` to any report doc that enumerates event types.

## Files touched

- `src/scripts/notify.py` — `substitution_discord_payload`.
- `src/scripts/health_store.py` — `annotate_latest_event`.
- `src/relay/racecast-feeds.py` — `Feed.served_url/served_idx` tracking; `is_substitution`;
  capture in the reload/set paths; `HealthStore.annotate_latest_event` wrapper;
  `POST /substitution/note` + the panel read side; `sanitize_reason`.
- `src/scripts/report_build.py` — collect + render substitutions.
- `src/director/director-panel.html` — the "Stream substitutions" section (styling parity).
- `tests/` — `test_notify.py`/`test_report.py`/`test_health_store.py`/`test_setup.py` (or the
  nearest existing files) per the cases above.
- `src/docs/wiki/images/director-panel.png` — refreshed screenshot.
