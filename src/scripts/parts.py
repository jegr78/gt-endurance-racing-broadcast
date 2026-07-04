"""Pure helpers for Director-Panel broadcast Part control (#395 follow-up).

Broadcast Parts (from the Sheet `Producer` tab) are the coarse segments a long
race is split into — each a separate YouTube broadcast with its own stream key.
This module holds the side-effect-free logic behind the panel's Part control:
the typed-confirmation phrase, the /parts/data view model, and the request
validators. All I/O (Sheet fetch, obs-websocket, the get_stream_key webhook)
lives in the relay; nothing here touches the network, disk, or a stream key."""


def normalize_intent(text):
    """Collapse whitespace and uppercase, so '  end  part 2 ' == 'END PART 2'."""
    return " ".join((text or "").split()).upper()


def parts_intent_phrase(action, index):
    """The exact confirmation phrase for an action on a 1-based Part index —
    ('start', 2) -> 'START PART 2'. The panel shows it and the relay
    re-validates the typed value against it."""
    return "{} PART {}".format(str(action).upper(), int(index))


def stream_active_param(raw):
    """Map a /parts/data `?stream_active=` query value to True/False/None.

    The panel already polls OBS's stream state (via /obs/state) every cycle, so it
    passes that truth here and /parts/data need not open a second obs-websocket
    connection. Absent or unrecognised -> None, and the relay falls back to reading
    OBS itself (a bare `/parts/data` call keeps its original self-reconciling
    behaviour). Pure."""
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return None


def parts_view_model(producer_rows, state, stream_active=None):
    """Build the /parts/data payload from the parsed Producer rows, the persisted
    part state ({"index","live"}), and the OBS live truth (stream_active; None ->
    trust the stored flag). Pure. Never returns a stream key or ref.

    Semantics of {index, live}: `index` is 1-based into the Producer order and is
    the Part to act on — the currently-live Part while live, or the next Part to
    start while offline. The End action advances `index`; Start marks it live."""
    rows = producer_rows or []
    count = len(rows)
    index = int(state.get("index", 1))
    live = bool(state.get("live", False)) if stream_active is None else bool(stream_active)
    parts = [{"index": i + 1,
              "label": (r.get("part") or "Part {}".format(i + 1)),
              "producer": r.get("producer") or ""}
             for i, r in enumerate(rows)]
    vm = {"enabled": count > 0, "count": count, "index": index, "live": live,
          "parts": parts, "platform": None, "complete": False,
          "current_label": "", "producer": "",
          "action": None, "confirm_phrase": None, "next_index": None}
    if count == 0:
        return vm
    if live:
        li = index if 1 <= index <= count else count
        vm["index"] = li
        vm["current_label"] = parts[li - 1]["label"]
        vm["producer"] = parts[li - 1]["producer"]
        vm["action"] = "end"
        vm["confirm_phrase"] = parts_intent_phrase("end", li)
    elif index > count:
        vm["complete"] = True
    else:
        vm["current_label"] = parts[index - 1]["label"]
        vm["producer"] = parts[index - 1]["producer"]
        vm["action"] = "start"
        vm["confirm_phrase"] = parts_intent_phrase("start", index)
        vm["next_index"] = index + 1 if index + 1 <= count else None
    return vm


def validate_start(body, state, count):
    """Validate a /parts/start request. Pure. Returns (True, index) or
    (False, (error, http_status)). The intent phrase is the anti-accident gate;
    the index must equal the expected next Part (stale-tablet guard)."""
    try:
        idx = int(body.get("index"))
    except (TypeError, ValueError):
        return False, ("index must be a number", 400)
    if normalize_intent(body.get("intent")) != parts_intent_phrase("start", idx):
        return False, ("confirmation phrase mismatch", 403)
    if idx != int(state.get("index", 1)) or not (1 <= idx <= count):
        return False, ("Part {} is not the next Part to start".format(idx), 409)
    return True, idx


def validate_end(body, state):
    """Validate a /parts/end request against the currently-focused Part. Pure."""
    idx = int(state.get("index", 1))
    if normalize_intent(body.get("intent")) != parts_intent_phrase("end", idx):
        return False, ("confirmation phrase mismatch", 403)
    return True, idx
