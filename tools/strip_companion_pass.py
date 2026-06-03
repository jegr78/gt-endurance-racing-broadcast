#!/usr/bin/env python3
"""Import a Companion full-config export into the repo, blanking the OBS password.

Default round-trip (no args):
  reads   incoming/iro-buttons.companionconfig   (gitignored inbox)
  writes  src/companion/iro-buttons.companionconfig  (password stripped)

Drop your Companion 'Export -> Full Configuration' into the incoming/ folder, then run:
  python3 tools/strip_companion_pass.py
Explicit paths still work:  python3 tools/strip_companion_pass.py IN OUT
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(ROOT, "incoming", "iro-buttons.companionconfig")
DEFAULT_OUT = os.path.join(ROOT, "src", "companion", "iro-buttons.companionconfig")


def blank(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("pass", "password") and isinstance(v, str):
                o[k] = ""
            else:
                blank(v)
    elif isinstance(o, list):
        for x in o:
            blank(x)


def main(src, dst):
    if not os.path.exists(src):
        os.makedirs(os.path.dirname(src), exist_ok=True)
        sys.exit(f"ERROR: no Companion export found at:\n  {src}\n"
                 f"Drop your Companion 'Export -> Full Configuration' there, then re-run.")
    cfg = json.load(open(src, encoding="utf-8"))
    blank(cfg)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(cfg, open(dst, "w", encoding="utf-8"), indent=1)
    print(f"stripped {src}\n      -> {dst}")


if __name__ == "__main__":
    args = sys.argv[1:]
    src = args[0] if len(args) >= 1 else DEFAULT_IN
    dst = args[1] if len(args) >= 2 else DEFAULT_OUT
    main(src, dst)
