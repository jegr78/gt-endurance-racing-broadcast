"""Pure overlay-layout compiler for the Control Center's visual overlay builder
(issue #114). Turns a layout model (per-slot position + style overrides, uploaded
fonts, and a verbatim customCss escape hatch) into the override CSS the relay
already serves at /<page>/override.css. No I/O, no dependencies — unit-tested in
tests/test_overlay.py. Spec: docs/superpowers/specs/2026-06-13-visual-overlay-builder-design.md.

The editable slots are NOT hardcoded here: extract_slots() reads the data-edit
markers from the base page (src/obs/hud.html / timer.html), so the markup stays
the single source of truth — a new marked element becomes editable automatically.
"""
import re

# Font name + type whitelist — DUPLICATED from src/relay/racecast-feeds.py and
# pinned byte-identical by a cross-check in tests/test_overlay.py (the repo's
# anti-drift pattern, like the load_dotenv copies). Keep the two in sync.
FONT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FONT_CTYPES = {"woff2": "font/woff2", "woff": "font/woff",
               "ttf": "font/ttf", "otf": "font/otf"}
FONT_EXTS = tuple(FONT_CTYPES)

# Property key -> CSS property name. The single canonical map; the builder's live
# canvas applies the same standard properties inline, so nothing drifts.
_PX_PROPS = {
    "left": "left", "top": "top", "width": "width", "height": "height",
    "fontSize": "font-size", "borderWidth": "border-width",
    "teamNameMax": "--team-name-max", "teamNameMin": "--team-name-min",
}
_TEXT_PROPS = {"color": "color", "background": "background",
               "borderColor": "border-color", "borderStyle": "border-style"}
_ALIGN = {"left": "flex-start", "center": "center", "right": "flex-end"}

# The default property set offered for a text slot (no data-edit-props attr).
DEFAULT_PROPS = ("left", "top", "width", "height", "fontSize",
                 "fontFamily", "color", "background", "align")

# Stable emit order within a slot rule (independent of dict insertion order).
PROP_ORDER = ("left", "top", "width", "height", "fontSize", "borderWidth",
              "teamNameMax", "teamNameMin", "fontFamily", "color",
              "background", "borderColor", "borderStyle", "align")

# A structured value must never close the rule or inject extra CSS; the only
# verbatim path is customCss. Reject anything carrying CSS-structural characters.
_UNSAFE_VALUE = re.compile(r"[;{}<>]|/\*|\*/")

# Sample content for the same-origin builder canvas (so the operator positions
# slots against realistic text). Each team is three slots now (logo/number/name,
# issue #136): the number + name carry text; the logo is an image (no sample text).
SAMPLE = {
    "hud": {
        "stint": "STINT 3", "session": "Race",
        "streamer": "twitch.tv/commentary",
        "round-top": "Round 4", "round-country": "Belgium",
        "team1-num": "7", "team1-name": "Team Redline",
        "team2-num": "23", "team2-name": "Apex Racing",
        "team3-num": "99", "team3-name": "Night Shift Motorsport",
        "race-control": "FCY — Full Course Yellow",
        "clock": "1:23:45",
    },
}


# Curated free Google Fonts offered in the builder. Single source for the UI
# list AND the server-side download allow-list (the SSRF gate — only these names
# are ever fetched). Self-hosted on pick: the .woff2 is downloaded once into
# overlay/fonts/, so the live overlay stays offline and the canvas can preview it.
# Broadcast-friendly families (condensed / display weights) lead the list.
GOOGLE_FONTS = (
    "Oswald", "Teko", "Rajdhani", "Saira", "Saira Condensed", "Barlow",
    "Barlow Condensed", "Anton", "Bebas Neue", "Montserrat", "Roboto",
    "Roboto Condensed", "Inter", "Poppins", "Orbitron", "Exo 2",
    "Titillium Web", "Archivo", "Archivo Narrow", "Chakra Petch",
    "Russo One", "Michroma",
)


def font_family(filename):
    """The @font-face family name for an uploaded font = its file stem."""
    return filename.rsplit(".", 1)[0]


def google_font_filename(name):
    """Local filename for a self-hosted Google font: spaces/punctuation stripped
    + .woff2 (FONT_NAME_RE forbids spaces). The CSS family is font_family() of it,
    e.g. 'Saira Condensed' -> 'SairaCondensed.woff2' (family 'SairaCondensed')."""
    return re.sub(r"[^A-Za-z0-9]", "", name) + ".woff2"


# A plausible Google font family name: letters/digits + single spaces, 1..50 long,
# no leading/trailing space. This is the gate for fetching ANY Google font (the
# curated GOOGLE_FONTS is just the UI quick-pick) — together with the fixed
# googleapis host and the gstatic-only woff2 check it keeps the fetch SSRF-safe.
GOOGLE_FONT_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 ]{0,48}[A-Za-z0-9])?$")


def is_google_font_name(name):
    """True for a syntactically valid Google font family name (no host/path tricks)."""
    return isinstance(name, str) and bool(GOOGLE_FONT_NAME_RE.match(name))


def google_font_css_url(name, weight=700):
    """The Google Fonts css2 URL for `name`. `weight` requests that weight (700 =
    the overlay's bold default); pass None to omit it and take the family's default
    face — the fallback for display fonts that have no 700 (a `:wght@700` request
    for a weight the family lacks 400s). `name` is whitespace-only-and-alphanumeric
    (validated upstream), so space->'+' is already URL-safe."""
    spec = (":wght@%d" % weight) if weight else ""
    return ("https://fonts.googleapis.com/css2?family="
            + name.strip().replace(" ", "+") + spec + "&display=swap")


def empty_layout(page):
    """A fresh, no-override layout for `page` (base look preserved)."""
    return {"version": 1, "page": page, "slots": {}, "fonts": [], "customCss": ""}


def migrate_layout(page, existing_css):
    """First-use layout for a profile that already has a hand-written <page>.css:
    the CSS is preserved VERBATIM in customCss (never reverse-parsed) so nothing
    is lost; the slot map starts empty for the operator to build on top."""
    layout = empty_layout(page)
    layout["customCss"] = existing_css or ""
    return layout


def extract_slots(html):
    """Editable slots from a base page's data-edit markers, in document order.
    Each: {id, label, props}. props = the data-edit-props comma list, or the
    default text-slot set when the attribute is absent. The markup is the single
    source of truth — no hardcoded slot list to drift."""
    slots = []
    for tag in re.finditer(r"<[^>]*\bdata-edit=\"[^\"]*\"[^>]*>", html):
        text = tag.group(0)
        mid = re.search(r"\bid=\"([^\"]+)\"", text)
        if not mid:
            continue
        label = re.search(r"\bdata-edit=\"([^\"]*)\"", text).group(1)
        mp = re.search(r"\bdata-edit-props=\"([^\"]*)\"", text)
        if mp:
            props = [p.strip() for p in mp.group(1).split(",") if p.strip()]
        else:
            props = list(DEFAULT_PROPS)
        slots.append({"id": mid.group(1), "label": label, "props": props})
    return slots


def base_style(html):
    """Contents of the base page's first <style> block (for the canvas), or ''."""
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.S)
    return m.group(1).strip() if m else ""


def base_body(html):
    """The static slot markup: the <body> content up to the first <script>
    (or </body>). Carries the slot elements the canvas renders; no page JS."""
    m = re.search(r"<body[^>]*>(.*?)(?:<script|</body>)", html, re.S)
    return m.group(1).strip() if m else ""


def _safe_value(value):
    """A style value safe to drop into a generated rule, else None."""
    if isinstance(value, bool):                 # bool is an int subclass — reject
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        v = value.strip()
        return v if v and not _UNSAFE_VALUE.search(v) else None
    return None


def _declaration(prop, value):
    """CSS 'name: value' for one (prop, value), or None when unsupported/unsafe."""
    value = _safe_value(value)
    if value is None:
        return None
    if prop in _PX_PROPS:
        if not isinstance(value, (int, float)):
            return None                         # px props take numbers only
        num = int(value) if float(value).is_integer() else value
        return f"{_PX_PROPS[prop]}: {num}px"
    if prop in _TEXT_PROPS:
        return f"{_TEXT_PROPS[prop]}: {value}" if isinstance(value, str) else None
    if prop == "fontFamily":
        return f'font-family: "{value}"' if isinstance(value, str) else None
    if prop == "align":
        mapped = _ALIGN.get(value) if isinstance(value, str) else None
        return f"justify-content: {mapped}" if mapped else None
    return None


def _slot_rule(slot_id, overrides, allowed):
    """A '#id { ... }' rule for one slot's overrides, gated by its allowed props."""
    decls = []
    for prop in PROP_ORDER:
        if prop not in allowed or prop not in overrides:
            continue
        decl = _declaration(prop, overrides[prop])
        if decl:
            decls.append(decl)
    if not decls:
        return ""
    return f"#{slot_id} {{ {'; '.join(decls)}; }}\n"


def _font_faces(fonts):
    """@font-face blocks for the valid uploaded fonts the layout references."""
    out = []
    for name in fonts or []:
        if not isinstance(name, str) or not FONT_NAME_RE.match(name) or "." not in name:
            continue
        if name.rsplit(".", 1)[1].lower() not in FONT_EXTS:
            continue
        out.append(f'@font-face {{ font-family: "{font_family(name)}"; '
                   f"src: url(/overlay/fonts/{name}); }}\n")
    return out


def compile_overlay_css(layout, slots):
    """Compile a layout model into override CSS for `slots` (the authoritative
    list from the base page). Order: @font-face, optional global body font,
    per-slot rules in document order, then customCss appended verbatim last.
    Defensive: unknown slot ids, disallowed props, and bad fonts are dropped —
    only the customCss escape hatch is passed through unfiltered."""
    layout = layout or {}
    allowed = {s["id"]: set(s.get("props") or ()) for s in slots}
    overrides = layout.get("slots") or {}
    out = _font_faces(layout.get("fonts"))

    body_font = _safe_value(layout.get("bodyFont"))
    if isinstance(body_font, str):
        out.append(f'html, body {{ font-family: "{body_font}"; }}\n')

    for slot in slots:                          # document order, not dict order
        sid = slot["id"]
        if sid in overrides and isinstance(overrides[sid], dict):
            rule = _slot_rule(sid, overrides[sid], allowed.get(sid, set()))
            if rule:
                out.append(rule)

    custom = layout.get("customCss")
    if isinstance(custom, str) and custom.strip():
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(custom)
    return "".join(out)
