#!/usr/bin/env python3
"""Pure helpers for the Sheet-driven OBS stream target (service + key per Producer
Part). No I/O: the CLI / Control Center fetch the Producer + Channel CSVs, call the
`get_stream_key` webhook, and drive OBS. Keeping resolution + response parsing here
makes them unit-testable and keeps the key out of any log/print path.

Security: the stream key only ever appears as the return of parse_stream_key_response
(handed straight to obs_ws.set_stream_service). It is never rendered by callers."""
import json


def resolve_part_ref(producer_rows, part):
    """The stream-key reference for a Part label from parsed Producer rows
    (dicts with 'part' + 'stream_key'). Case-insensitive exact match on the
    trimmed Part. Returns the ref, or "" when no row matches or the row has no
    reference. Pure."""
    want = (part or "").strip().lower()
    for r in producer_rows or []:
        if (r.get("part") or "").strip().lower() == want:
            return (r.get("stream_key") or "").strip()
    return ""


def event_platform(channel_rows):
    """The single event platform from parsed Channel rows [(platform, channel)]:
    the first non-empty platform, lowercased, or "". Pure (KISS: one channel per
    event)."""
    for platform, _chan in channel_rows or []:
        p = (platform or "").strip().lower()
        if p:
            return p
    return ""


def parse_stream_key_response(body):
    """Parse an Apps Script `get_stream_key` response (bytes or str) -> (key, error).
    Success {"ok":true,"action":"get_stream_key","key":"..."} -> (key, "").
    ok:false -> ("", <error>). Missing action echo -> ("", outdated-script msg).
    Malformed / non-JSON -> ("", msg). Never raises."""
    try:
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
        d = json.loads(text)
    except (ValueError, AttributeError, TypeError):
        return "", "webhook returned a non-JSON response"
    if not isinstance(d, dict):
        return "", "webhook returned an unexpected response"
    if not d.get("ok"):
        return "", str(d.get("error") or "webhook rejected the request")
    if d.get("action") != "get_stream_key":
        return "", ("webhook script outdated (no get_stream_key action) — redeploy "
                    "the Apps Script")
    key = d.get("key")
    if not key:
        return "", "webhook returned no key for that reference"
    return str(key), ""
