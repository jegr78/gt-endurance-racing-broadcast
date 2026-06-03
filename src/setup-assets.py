#!/usr/bin/env python3
"""Localize the tokenized OBS collection for THIS machine: replace __IRO_ASSETS__
with the absolute path to the local assets/ folder and write an importable collection.
Works from the repo (src/) or the distributed package — same ./obs ./assets layout.

Usage: python3 setup-assets.py [--out PATH] [--assets DIR] [--template FILE]
"""
import argparse, json, os, sys

ASSETS_TOKEN = "__IRO_ASSETS__"
SHEET_TOKEN = "__IRO_SHEET__"
TIMER_TOKEN = "__IRO_TIMER__"


def load_dotenv(start):
    """Load KEY=VALUE pairs from a .env at the script dir or the project root
    into os.environ. Real environment variables win (setdefault). No dependency.

    SECURITY: bounded to the project (nearest ancestor with a .git/.env.example
    marker) so a stray .env in an unrelated parent dir is never loaded."""
    candidates, d = [start], start
    for _ in range(4):
        if any(os.path.exists(os.path.join(d, m)) for m in (".git", ".env.example")):
            candidates.append(d)
            break
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for c in candidates:
        p = os.path.join(c, ".env")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return p
    return None


def replace_tokens(obj, mapping):
    """Recursively replace each token->value in every string value.
    Done on the parsed JSON (not raw text) so backslashes/quotes in a path —
    e.g. Windows 'C:\\Users\\...' — are escaped correctly on re-serialization."""
    if isinstance(obj, dict):
        return {k: replace_tokens(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_tokens(v, mapping) for v in obj]
    if isinstance(obj, str):
        for tok, val in mapping.items():
            obj = obj.replace(tok, val)
        return obj
    return obj


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(base)  # picks up IRO_SHEET_ID from a gitignored .env at repo/package root
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(base, "assets"))
    ap.add_argument("--template", default=None)
    ap.add_argument("--out", default=os.path.join(base, "obs", "IRO_Endurance.import.json"))
    ap.add_argument("--sheet-id", default=os.environ.get("IRO_SHEET_ID"),
                    help="Google Sheet ID injected into the HUD browser source. "
                         "Default: env IRO_SHEET_ID (or .env). See .env.example.")
    ap.add_argument("--timer-url", default=os.environ.get("IRO_TIMER_URL"),
                    help="Full stagetimer.io output URL (incl. signature) injected into "
                         "the timer browser source. Default: env IRO_TIMER_URL (or .env).")
    a = ap.parse_args()

    tpl = a.template
    if tpl is None:
        for cand in ("IRO_Endurance.template.json", "IRO_Endurance.json"):
            p = os.path.join(base, "obs", cand)
            if os.path.exists(p):
                tpl = p
                break
    if not tpl or not os.path.exists(tpl):
        sys.exit(f"ERROR: OBS template not found under {os.path.join(base, 'obs')}")
    if not os.path.isdir(a.assets):
        sys.exit(f"ERROR: assets folder missing: {a.assets}")

    try:
        collection = json.load(open(tpl, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"ERROR: could not read OBS template {tpl}: {e}")

    raw = json.dumps(collection)
    mapping = {ASSETS_TOKEN: a.assets}
    if SHEET_TOKEN in raw:
        if not a.sheet_id:
            sys.exit(f"ERROR: the collection references the HUD sheet ({SHEET_TOKEN}) but no "
                     "Sheet ID is set. Add IRO_SHEET_ID to .env at the repo/package root "
                     "(see .env.example) or pass --sheet-id.")
        mapping[SHEET_TOKEN] = a.sheet_id
    if TIMER_TOKEN in raw:
        if not a.timer_url:
            sys.exit(f"ERROR: the collection references the race timer ({TIMER_TOKEN}) but no "
                     "timer URL is set. Add IRO_TIMER_URL to .env at the repo/package root "
                     "(see .env.example) or pass --timer-url.")
        mapping[TIMER_TOKEN] = a.timer_url

    localized = replace_tokens(collection, mapping)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(localized, fh, ensure_ascii=False, indent=4)
    print(f"OK -> {a.out}")
    print(f"  Image paths now point to: {a.assets}")
    if SHEET_TOKEN in mapping:
        print(f"  HUD sheet ID injected: {a.sheet_id}")
    if TIMER_TOKEN in mapping:
        print("  Race-timer URL injected.")
    print(f"OBS: Scene Collection -> Import -> {a.out}")
    print("IMPORTANT: do NOT move this folder afterwards (OBS stores absolute paths).")


if __name__ == "__main__":
    main()
