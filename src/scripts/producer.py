#!/usr/bin/env python3
"""Pure parser for the league Sheet's read-only `Producer` tab
(`Part | Producer | MagicDNS`) — the per-event producer handover schedule shown
on the Control Center Home view. No I/O: the Control Center provider fetches the
gviz CSV and tags each row with `self` after parsing.

Header row is REQUIRED — unlike Schedule/Crew there is no positional fallback:
this is a new, documented tab, so an unrecognized header yields an empty list
(the Home card then hides itself) rather than a silent column mis-read."""
import csv
import io

PRODUCER_PART_HEADERS = ("part",)
PRODUCER_PRODUCER_HEADERS = ("producer",)
PRODUCER_MAGICDNS_HEADERS = ("magicdns", "magic-dns", "magicdns name", "magic dns")


def _find(header, names):
    """Index of the first cell in `header` (already lowercased/stripped) that
    matches any of `names`, or None."""
    for i, cell in enumerate(header):
        if cell in names:
            return i
    return None


def _cell(row, i):
    return row[i].strip() if (0 <= i < len(row) and row[i]) else ""


def parse_producer_rows(text):
    """Parse the `Producer` tab CSV into [{"part","producer","magicdns"}, ...].

    Header REQUIRED: returns [] unless all three columns are located in row 1 by
    case-insensitive header match. Order and duplicate rows are preserved (one
    producer may do consecutive parts). Cells are trimmed; a row whose Producer
    AND MagicDNS are both blank is dropped (spacer rows), but a present Producer
    with an empty MagicDNS is kept (the UI renders it with a disabled action)."""
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    header = [(c or "").strip().lower() for c in rows[0]]
    pi = _find(header, PRODUCER_PART_HEADERS)
    ri = _find(header, PRODUCER_PRODUCER_HEADERS)
    mi = _find(header, PRODUCER_MAGICDNS_HEADERS)
    if pi is None or ri is None or mi is None:
        return []
    out = []
    for row in rows[1:]:
        part, prod, magic = _cell(row, pi), _cell(row, ri), _cell(row, mi)
        if not prod and not magic:
            continue
        out.append({"part": part, "producer": prod, "magicdns": magic})
    return out
