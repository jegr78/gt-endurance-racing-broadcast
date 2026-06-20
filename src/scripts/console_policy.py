#!/usr/bin/env python3
"""Pure authorization policy for the funnelled /console namespace (#216 phase 2).

Identity != authorization (locked decision #3): a verified token proves *who*
(see console_auth), the live roster resolves *roles* (see resolve_roles in the
relay), and THIS module decides whether a given role set may reach a given
/console subpath. No I/O, no token/crypto logic, no routes -- the Phase 3
_console_auth handler wires identity -> roles -> decide().

The matrix mirrors the relay's real segment-list routes (do_GET/do_POST in
src/relay/racecast-feeds.py); keep the two in sync. Spec: the
role-based-funnel-access design, sections C (matrix) and D (step-up).
"""

import collections

# Capabilities. A resolved role set is a subset of {COMMENTATOR, DIRECTOR,
# PRODUCER}. ANY is the policy keyword meaning "any authenticated identity,
# regardless of roles" -- it is never a member of a role set.
COMMENTATOR = "commentator"
DIRECTOR = "director"
PRODUCER = "producer"
ANY = "any"

# Decision outcomes returned by decide().
ALLOW = "allow"
FORBIDDEN = "forbidden"
STEP_UP_REQUIRED = "step_up_required"
NOT_FOUND = "not_found"

Requirement = collections.namedtuple("Requirement", ("capability", "step_up"))


def min_capability(segments, method="GET"):
    """Map a /console request to its minimum Requirement, or None if the route is
    not a recognized console route. *segments* is the path AFTER the /console
    prefix (e.g. /console/set/stint/4 -> ["set","stint","4"]). Ordering is
    most-specific-first, matching the relay's own dispatch."""
    p = list(segments)

    # --- producer + step-up: irreversible broadcast-control ops (spec D) ---
    if len(p) == 3 and p[:2] == ["set", "stint"]:
        return Requirement(PRODUCER, True)
    if len(p) == 2 and p[0] == "mode":
        return Requirement(PRODUCER, True)
    # NOTE: takeover/* are the Phase 7 producer-takeover PULL endpoints
    # (/console/takeover/*, spec section H) -- console-only, not current relay
    # routes (the live takeover today is /set/stint/<n>, mapped below).
    if p and p[0] == "takeover" and len(p) >= 2:
        return Requirement(PRODUCER, True)
    if p == ["cockpit", "versions"]:
        return Requirement(PRODUCER, True)

    # --- producer view (no step-up to merely open the page) ---
    if p == ["prod"]:
        return Requirement(PRODUCER, False)

    # --- director: feed / schedule / timer / setup / pov control ---
    if p == ["next"]:
        return Requirement(DIRECTOR, False)
    if len(p) == 2 and p[0] == "next":
        return Requirement(DIRECTOR, False)
    if len(p) == 2 and p[0] == "prev":
        return Requirement(DIRECTOR, False)
    if p == ["reload"] or (len(p) == 2 and p[0] == "reload"):
        return Requirement(DIRECTOR, False)
    if len(p) == 3 and p[0] == "set":          # ["set", A|B, n]; stint handled above
        return Requirement(DIRECTOR, False)
    if p == ["panel"]:
        return Requirement(DIRECTOR, False)
    if p and p[0] == "pov":                     # all /pov/* are control
        return Requirement(DIRECTOR, False)
    if p and p[0] == "obs":                     # relay-mediated OBS control (scene/source/audio/state)
        return Requirement(DIRECTOR, False)
    if p and p[0] == "buttons":                 # /console/buttons/* -> Companion proxy (#236)
        return Requirement(DIRECTOR, False)
    if p and p[0] == "setup" and p != ["setup", "data"]:
        return Requirement(DIRECTOR, False)
    if len(p) >= 2 and p[0] == "timer" and p[1] != "data":
        return Requirement(DIRECTOR, False)
    if p == ["schedule", "set"] or p == ["qualifying", "set"]:
        return Requirement(DIRECTOR, False)
    if p == ["schedule", "data"] or p == ["qualifying", "data"]:
        # These carry per-stint stream URLs; director-only (the panel's sole
        # consumer) so a commentator can't read every feed's URL over the Funnel.
        return Requirement(DIRECTOR, False)
    if p == ["event", "title"]:
        return Requirement(DIRECTOR, False)
    if p == ["submissions"] or (len(p) == 2 and p[0] == "submissions"):
        return Requirement(DIRECTOR, False)
    if p and p[0] == "cues":                    # /cues/send|data|presets|reload
        return Requirement(DIRECTOR, False)

    # --- commentator: own-row stream-link submission ---
    if p == ["submit"] or p == ["cockpit", "submit"]:
        return Requirement(COMMENTATOR, False)

    # --- any authenticated: read-only monitors + identity-forced chat ---
    # ["console"], ["data"], ["program"] are console-only shell/landing pages (Phase 3),
    # not relay-route mirrors.
    if p == ["logo"]:
        return Requirement(ANY, False)
    if p in ([], ["status"], ["console"], ["data"], ["program"]):
        return Requirement(ANY, False)
    if p and p[0] in ("hud", "preview", "splitscreen"):
        return Requirement(ANY, False)
    if len(p) == 3 and p[:2] == ["overlay", "fonts"]:
        return Requirement(ANY, False)
    if p in (["timer", "data"], ["setup", "data"]):
        return Requirement(ANY, False)
    if p in (["chat", "data"], ["chat", "reload"], ["chat", "send"]):
        return Requirement(ANY, False)
    if p in (["cockpit"], ["cockpit", "data"], ["cockpit", "program"],
             ["cockpit", "timer"], ["cockpit", "chat", "data"],
             ["cockpit", "chat", "send"],
             ["cockpit", "cues"], ["cockpit", "cues", "ack"]):
        return Requirement(ANY, False)

    return None


def decide(roles, segments, method="GET", has_step_up=False):
    """Policy decision for a /console request. Identity is assumed already
    verified by the caller; *roles* is the resolved capability set (possibly
    empty), *has_step_up* the caller's shared-producer-secret check result.
    Returns ALLOW / FORBIDDEN / STEP_UP_REQUIRED / NOT_FOUND."""
    req = min_capability(segments, method)
    if req is None:
        return NOT_FOUND
    if req.capability != ANY and req.capability not in roles:
        return FORBIDDEN
    if req.step_up and not has_step_up:
        return STEP_UP_REQUIRED
    return ALLOW
