#!/usr/bin/env python3
"""Flag-status graphics (parallel to the flag-text chip): pure value->OBS-source
mapping + mutual-exclusion intents + a small persisted store. No relay imports —
the relay wires obs_ws in as the store's apply_fn (mirrors cue_admin / chat).

Canonical keys are the slugified flag conditions; the OBS source name equals the
Sheet Assets label equals the PNG basename (e.g. key 'safety-car' -> 'Flag Safety
Car' -> 'Flag Safety Car.png'). Flags are mutually exclusive: at most one graphic
is visible, in BOTH the Stint and Splitscreen scenes, or none."""

# Scenes that carry the flag-graphic scene items (both get all five, kept in
# sync so a scene switch preserves the shown flag). Mirrors the OBS collection.
FLAG_GRAPHIC_SCENES = ("Stint", "Splitscreen")

# Canonical key -> OBS source name (== Sheet Assets label == PNG basename).
FLAG_GRAPHIC_SOURCES = {
    "green": "Flag Green",
    "yellow": "Flag Yellow",
    "red": "Flag Red",
    "safety-car": "Flag Safety Car",
    "virtual-safety-car": "Flag Virtual Safety Car",
}

# Input aliases accepted by normalize_flag_value (parity with the HUD flag chip).
FLAG_GRAPHIC_ALIASES = {"sc": "safety-car", "vsc": "virtual-safety-car"}


def normalize_flag_value(raw):
    """Canonical key for *raw*, or '' for empty/clear, or None for an unknown
    non-empty value. Lowercases, trims, and slugifies spaces to dashes, then
    applies the alias map — so 'Safety Car', 'safety-car', and 'sc' all map to
    'safety-car'."""
    if raw is None:
        return ""
    slug = "-".join(str(raw).strip().lower().split())
    if not slug:
        return ""
    slug = FLAG_GRAPHIC_ALIASES.get(slug, slug)
    return slug if slug in FLAG_GRAPHIC_SOURCES else None


def flag_graphic_intents(active):
    """[(scene, source, enabled), …] for every flag source in every flag scene;
    enabled is True only for *active*'s source. active '' / None / unknown -> all
    hidden. Deterministic order (scenes outer, sources inner)."""
    shown = FLAG_GRAPHIC_SOURCES.get(active)
    out = []
    for scene in FLAG_GRAPHIC_SCENES:
        for source in FLAG_GRAPHIC_SOURCES.values():
            out.append((scene, source, source == shown))
    return out
