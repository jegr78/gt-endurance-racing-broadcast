# Repo Structure & Build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure IRO_Broadcast_Setup into a self-contained single-source repo: `src/` is the only edited tree, `tools/build.py` generates `dist/` (gitignored), `runtime/` holds runtime data (gitignored), all scripts are Python, and there are no references outside the repo.

**Architecture:** Move every source file into `src/`; port all `.sh`/`.bat` to Python; make the OBS collection self-contained (assets in `src/assets/`, paths tokenized as `__IRO_ASSETS__`); add `--runtime-dir` to the relay so cookies/logs/caches live in `runtime/`; write a build script that assembles the distributable from `src/`.

**Tech Stack:** Python 3 stdlib (relay + all tooling), OBS scene-collection JSON, Companion config JSON, Google Sheets (gviz CSV), zip.

**Spec:** `docs/superpowers/specs/2026-06-03-repo-structure-design.md`

**Project reality notes:**
- Working dir is **not a git repo** (user inits it himself after this migration). "Checkpoint" steps are manual save points — the `git` lines are optional/no-op until the repo exists.
- No pytest; the relay has `tests/test_pov.py` (stdlib) and is otherwise verified functionally (launch + curl).
- **Deviation from spec:** `run-relay.py` lives in **`tools/`** (not `src/relay/`), because its runtime-dir resolution is repo-specific; colleagues in the dist package run `python3 relay/iro-feeds.py` directly. The spec layout is otherwise followed.
- Source-of-truth picks: relay/OBS/director/cheat-sheets/guide come from the **working-dir** copies (current, incl. POV); the **companion config** comes from the **package** copy (current full, password-stripped — the root `iro-buttons.companionconfig` is the stale page export and is discarded); the **7 PNGs** come from `IRO_Broadcast_Package/assets/`; **README_SETUP.md** from the package.
- All team-facing files are **English only**.

---

## Task 1: Scaffold directories, move static source files, .gitignore

**Files:**
- Create dirs: `src/{relay,obs,companion,director,assets,scripts,docs}`, `tools/`, `runtime/logs/`, `dist/`
- Move/copy: director panel, docs, cheat sheets, companion config, 7 PNGs
- Create: `.gitignore`

- [ ] **Step 1: Create the directory skeleton**

```bash
cd <repo>
mkdir -p src/relay src/obs src/companion src/director src/assets src/scripts src/docs tools runtime/logs dist
echo "scaffold:"; ls -d src/* tools runtime dist
```

- [ ] **Step 2: Move the static (no-transform) source files into src/**

```bash
cd <repo>
mv director-panel.html                              src/director/director-panel.html
mv IRO_cheat_sheets.html                            src/docs/IRO_cheat_sheets.html
mv IRO_Broadcast_Setup_Guide.md                     src/docs/IRO_Broadcast_Setup_Guide.md
cp IRO_Broadcast_Package/README_SETUP.md            src/docs/README_SETUP.md
cp IRO_Broadcast_Package/companion/iro-buttons.companionconfig  src/companion/iro-buttons.companionconfig
cp IRO_Broadcast_Package/assets/*.png               src/assets/
echo "assets:"; ls -1 src/assets/ | wc -l   # expect 7
```

- [ ] **Step 3: Write `.gitignore`**

Create `<repo>/.gitignore`:

```gitignore
runtime/
dist/
__pycache__/
*.pyc
.DS_Store
*.bak
# safety: never commit secrets/caches even if misplaced
cookies.txt
*.cache.txt
*.import.json
```

- [ ] **Step 4: Verify**

```bash
cd <repo>
test $(ls src/assets/*.png | wc -l) -eq 7 && echo "7 assets OK"
test -f src/director/director-panel.html && test -f src/docs/README_SETUP.md && test -f src/companion/iro-buttons.companionconfig && echo "static files in place"
python3 -c "import json;json.load(open('src/companion/iro-buttons.companionconfig'));print('companion json OK')"
```
Expected: `7 assets OK`, `static files in place`, `companion json OK`.

- [ ] **Step 5: Checkpoint** — `git add -A && git commit -m "chore: scaffold src/ + move static files + gitignore"` (skip if no repo yet)

---

## Task 2: Relay — relocate + `--runtime-dir` + schedule template

**Files:**
- Move: `iro-feeds.py` → `src/relay/iro-feeds.py`
- Modify: `src/relay/iro-feeds.py` (SCHEDULE_TEMPLATE, `load_initial`, argparse, path block, panel candidate)
- Modify: `tests/test_pov.py` (import path)

- [ ] **Step 1: Move the relay + fix the test's import path**

```bash
cd <repo>
mv iro-feeds.py src/relay/iro-feeds.py
```

In `tests/test_pov.py`, change the path-resolution lines:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "iro-feeds.py"))
```

- [ ] **Step 2: Run the test to confirm it still passes after the move**

Run: `python3 tests/test_pov.py`
Expected: `ALL PASS` (the move + path fix only).

- [ ] **Step 3: Add the `SCHEDULE_TEMPLATE` constant**

In `src/relay/iro-feeds.py`, after the line `DEFAULT_POV_TAB = "POV"` add:

```python

SCHEDULE_TEMPLATE = (
    "# IRO relay offline fallback schedule — used ONLY if the Google Sheet AND the\n"
    "# last-good cache are both unavailable. One entry per stint, in order:\n"
    "#   a YouTube channel ID (UC...) OR a full watch URL (https://www.youtube.com/watch?v=...).\n"
    "# Lines starting with # are ignored. The real schedule lives in the Sheet tab 'Schedule'.\n"
    "# Example:\n"
    "#   https://www.youtube.com/watch?v=VIDEOID_STINT_1\n"
    "#   UCxxxxxxxxxxxxxxxxxxxxxx\n"
)
```

- [ ] **Step 4: Make `load_initial` write the template on cold-start failure**

Replace the whole `load_initial` method with:

```python
    def load_initial(self, template=None):
        if self.refresh():
            print(f"Schedule loaded from Google Sheet: {len(self.items)} stints.")
            return
        # Sheet unreachable -> cache, then a user-filled local fallback
        for path, label in ((self.cache_path, "cache"), (self.local_fallback, "local schedule.txt")):
            if path and os.path.exists(path):
                items = [l.split("#", 1)[0].strip() for l in open(path, encoding="utf-8")]
                items = [i for i in items if i]
                if items:
                    with self.lock:
                        self.items = items
                    print(f"WARN: sheet unreachable ({self.last_error}). "
                          f"Using {label}: {len(items)} stints.")
                    return
        # Nothing available: drop a commented template (if missing) and explain.
        if template and self.local_fallback and not os.path.exists(self.local_fallback):
            try:
                os.makedirs(os.path.dirname(self.local_fallback), exist_ok=True)
                with open(self.local_fallback, "w", encoding="utf-8") as fh:
                    fh.write(template)
                print(f"Wrote a fallback template to {self.local_fallback}")
            except OSError:
                pass
        sys.exit(f"ERROR: no schedule available. Sheet error: {self.last_error}\n"
                 f"Check tab '{DEFAULT_SHEET_TAB}', sharing (Anyone with the link: Viewer), "
                 f"or fill {self.local_fallback}.")
```

- [ ] **Step 5: Add the `--runtime-dir` argument**

In `main()`, right after the `--http-port` argument block, add:

```python
    ap.add_argument("--runtime-dir", default=None,
                    help="Directory for runtime data (cookies.txt, logs/, *.cache.txt). "
                         "Default: next to this script (keeps the distributed package "
                         "self-locating). The repo passes its runtime/ folder.")
```

- [ ] **Step 6: Route all runtime paths through the runtime dir**

In `main()`, replace the path-setup block (from `here = ...` down to `cache = ...`):

```python
    here = os.path.dirname(os.path.abspath(__file__))
    runtime = os.path.abspath(args.runtime_dir) if args.runtime_dir else here
    os.makedirs(runtime, exist_ok=True)
    logdir = args.logdir if os.path.isabs(args.logdir) else os.path.join(runtime, args.logdir)
    os.makedirs(logdir, exist_ok=True)
    local = args.schedule if os.path.isabs(args.schedule) else os.path.join(runtime, args.schedule)
    cache = os.path.join(runtime, "schedule.cache.txt")
    ports = [int(x) for x in args.ports.split(",")]
```

- [ ] **Step 7: Point cookies, pov-cache and the template call at the runtime dir**

In `main()`:

Replace the cookies auto-export + auto-detect lines that use `os.path.join(here, "cookies.txt")` with `os.path.join(runtime, "cookies.txt")` (two occurrences: the `export_cookies(...)` call and the `auto = ...` line).

Replace the POV cache line `pov_cache = os.path.join(here, "pov.cache.txt")` with:

```python
        pov_cache = os.path.join(runtime, "pov.cache.txt")
```

Replace `source.load_initial()` with:

```python
    source.load_initial(SCHEDULE_TEMPLATE)
```

- [ ] **Step 8: Add the new director-panel location to the panel search**

In `main()`, replace the panel-candidate tuple with:

```python
        for cand in (os.path.join(here, "director-panel.html"),
                     os.path.join(here, "..", "director-panel.html"),
                     os.path.join(here, "..", "director", "director-panel.html")):
```

- [ ] **Step 9: Unit test still green + syntax**

Run: `python3 -m py_compile src/relay/iro-feeds.py && python3 tests/test_pov.py | tail -1`
Expected: `ALL PASS`.

- [ ] **Step 10: Functional test — runtime dir + cold-start template**

```bash
cd <repo>
rm -rf /tmp/iro_rt && mkdir -p /tmp/iro_rt
# cold start with a non-existent sheet tab -> should write the template + exit
python3 src/relay/iro-feeds.py --runtime-dir /tmp/iro_rt --sheet-tab __NOPE__ --no-pov ; echo "exit=$?"
echo "--- template written? ---"; head -2 /tmp/iro_rt/schedule.txt
```
Expected: exits non-zero with the "no schedule available" message; `/tmp/iro_rt/schedule.txt` contains the commented template header.

- [ ] **Step 11: Functional test — real run routes runtime into runtime/**

```bash
cd <repo>
python3 src/relay/iro-feeds.py --runtime-dir runtime --no-panel > /tmp/rt_smoke.log 2>&1 &
sleep 5
ls runtime/ ; ls runtime/logs/ 2>/dev/null
curl -s http://127.0.0.1:8088/status | python3 -c "import sys,json;d=json.load(sys.stdin);print('schedule_len',d['schedule_len'])"
kill -TERM $(lsof -nP -iTCP:8088 -sTCP:LISTEN -t) 2>/dev/null; sleep 1
echo "cache in runtime?"; test -f runtime/schedule.cache.txt && echo yes || echo no
```
Expected: `runtime/` holds `schedule.cache.txt` + `logs/`, `/status` shows the real `schedule_len`, no files written next to the script.

- [ ] **Step 12: Checkpoint** — `git add -A && git commit -m "feat(relay): relocate to src/ + --runtime-dir + schedule template"`

---

## Task 3: OBS collection — tokenize to `__IRO_ASSETS__`

**Files:**
- Create: `tools/tokenize-obs.py`
- Produce: `src/obs/IRO_Endurance.json` (tokenized, from the working `IRO_Endurance.json`)

- [ ] **Step 1: Write the tokenizer**

Create `tools/tokenize-obs.py`:

```python
#!/usr/bin/env python3
"""Replace absolute asset paths in an OBS collection with the __IRO_ASSETS__ token.
Any source whose `file` basename is a known asset is rewritten to
`__IRO_ASSETS__/<basename>`. Idempotent.  Usage: tokenize-obs.py IN [OUT]
"""
import json, os, sys

ASSETS = {"Overlay.png", "Post Race Interviews.png", "Quali Results.png",
          "Race Results.png", "Season Schedule.png", "Standings.png", "YT-IRO-Race.png"}
TOKEN = "__IRO_ASSETS__"


def main(src, out):
    with open(src, encoding="utf-8") as fh:
        d = json.load(fh)
    n = 0
    for s in d.get("sources", []):
        st = s.get("settings") or {}
        f = st.get("file")
        if isinstance(f, str) and os.path.basename(f) in ASSETS:
            st["file"] = f"{TOKEN}/{os.path.basename(f)}"
            n += 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=4)
    print(f"tokenized {n} asset path(s) -> {out}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: tokenize-obs.py IN [OUT]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else sys.argv[1])
```

- [ ] **Step 2: Tokenize the working collection into src/obs/**

```bash
cd <repo>
python3 tools/tokenize-obs.py IRO_Endurance.json src/obs/IRO_Endurance.json
```
Expected: `tokenized 7 asset path(s) -> src/obs/IRO_Endurance.json`.

- [ ] **Step 3: Verify no external paths remain, Feed POV survived**

```bash
cd <repo>
python3 - <<'PY'
import json
d=json.load(open("src/obs/IRO_Endurance.json"))
files=[(s["name"],(s.get("settings") or {}).get("file")) for s in d["sources"] if (s.get("settings") or {}).get("file")]
assert all(f.startswith("__IRO_ASSETS__/") for _,f in files), files
assert not any("GoogleDrive" in f for _,f in files)
assert any(s.get("name")=="Feed POV" for s in d["sources"])
print("OK: 7 tokenized, no Drive paths, Feed POV present")
PY
```
Expected: `OK: 7 tokenized, no Drive paths, Feed POV present`.

- [ ] **Step 4: Checkpoint** — `git add -A && git commit -m "feat(obs): self-contained tokenized collection in src/obs"`

---

## Task 4: `setup-assets.py` (localize the collection)

**Files:**
- Create: `src/setup-assets.py`

- [ ] **Step 1: Write setup-assets.py**

Create `src/setup-assets.py`:

```python
#!/usr/bin/env python3
"""Localize the tokenized OBS collection for THIS machine: replace __IRO_ASSETS__
with the absolute path to the local assets/ folder and write an importable collection.
Works from the repo (src/) or the distributed package — same ./obs ./assets layout.

Usage: python3 setup-assets.py [--out PATH] [--assets DIR] [--template FILE]
"""
import argparse, os, sys

TOKEN = "__IRO_ASSETS__"


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(base, "assets"))
    ap.add_argument("--template", default=None)
    ap.add_argument("--out", default=os.path.join(base, "obs", "IRO_Endurance.import.json"))
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

    text = open(tpl, encoding="utf-8").read().replace(TOKEN, a.assets)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(text)
    print(f"OK -> {a.out}")
    print(f"  Image paths now point to: {a.assets}")
    print(f"OBS: Scene Collection -> Import -> {a.out}")
    print("IMPORTANT: do NOT move this folder afterwards (OBS stores absolute paths).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it for the repo (output into runtime/)**

```bash
cd <repo>
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json
```
Expected: prints `OK -> runtime/IRO_Endurance.import.json`.

- [ ] **Step 3: Verify the localized file has absolute asset paths + valid JSON**

```bash
cd <repo>
python3 - <<'PY'
import json,os
d=json.load(open("runtime/IRO_Endurance.import.json"))
files=[(s.get("settings") or {}).get("file") for s in d["sources"] if (s.get("settings") or {}).get("file")]
assert files and all(os.path.isabs(f) and "__IRO_ASSETS__" not in f for f in files), files
assert all(os.path.exists(f) for f in files), [f for f in files if not os.path.exists(f)]
print("OK: localized,", len(files), "asset files all exist on disk")
PY
```
Expected: `OK: localized, 7 asset files all exist on disk`.

- [ ] **Step 4: Checkpoint** — `git add -A && git commit -m "feat: setup-assets.py (localize tokenized collection)"`

---

## Task 5: Python launchers — get-cookies.py + run-relay.py

**Files:**
- Create: `src/relay/get-cookies.py`
- Create: `tools/run-relay.py`

- [ ] **Step 1: Write get-cookies.py**

Create `src/relay/get-cookies.py`:

```python
#!/usr/bin/env python3
"""Export YouTube cookies from a logged-in browser to <runtime>/cookies.txt via yt-dlp
(against YouTube's "Sign in to confirm you're not a bot" check).

Usage: python3 get-cookies.py [browser] [--runtime-dir DIR]
  browser: firefox | chrome | safari | edge | brave   (default: firefox)
Default runtime dir = next to this script (repo: pass --runtime-dir runtime).
"""
import argparse, os, re, subprocess, sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("browser", nargs="?", default="firefox")
    ap.add_argument("--runtime-dir", default=here)
    a = ap.parse_args()
    os.makedirs(a.runtime_dir, exist_ok=True)
    out = os.path.join(a.runtime_dir, "cookies.txt")
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    print(f"Exporting YouTube cookies from '{a.browser}' ...")
    try:
        subprocess.run(["yt-dlp", "--cookies-from-browser", a.browser, "--cookies", out,
                        "--skip-download", "--no-warnings", url],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except FileNotFoundError:
        sys.exit("ERROR: yt-dlp not found (brew install yt-dlp / pip install -U yt-dlp).")
    except subprocess.TimeoutExpired:
        sys.exit("ERROR: cookie export timed out (approve the Keychain prompt?).")
    if os.path.exists(out):
        txt = open(out, encoding="utf-8", errors="replace").read()
        if re.search(r"LOGIN_INFO|SAPISID|__Secure-[0-9]?PSID", txt):
            print(f"OK -> {out}  (logged-in session detected)")
        else:
            print(f"WARNING: cookies written but no login found — log into YouTube in "
                  f"'{a.browser}' and re-run.")
    else:
        sys.exit(f"FAILED to export from '{a.browser}'. Installed + logged into YouTube?")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write run-relay.py (repo launcher)**

Create `tools/run-relay.py`:

```python
#!/usr/bin/env python3
"""Repo launcher: run the relay with the repo's runtime/ directory.
Forwards extra args to iro-feeds.py.  Usage: python3 tools/run-relay.py [relay args...]
"""
import os, subprocess, sys


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runtime = os.path.join(root, "runtime")
    feeds = os.path.join(root, "src", "relay", "iro-feeds.py")
    cmd = [sys.executable, feeds, "--runtime-dir", runtime] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Syntax + a no-network behavior check**

```bash
cd <repo>
python3 -m py_compile src/relay/get-cookies.py tools/run-relay.py && echo "compile OK"
python3 tools/run-relay.py --help | head -1   # forwards to iro-feeds argparse
```
Expected: `compile OK`, and the relay's argparse usage line appears.

- [ ] **Step 4: Functional — run-relay starts the relay against runtime/**

```bash
cd <repo>
python3 tools/run-relay.py --no-panel > /tmp/rr.log 2>&1 &
sleep 5
grep -E "relay running|Driver-POV" /tmp/rr.log
curl -s http://127.0.0.1:8088/status >/dev/null && echo "status reachable"
kill -TERM $(lsof -nP -iTCP:8088 -sTCP:LISTEN -t) 2>/dev/null
```
Expected: relay-running + Driver-POV lines, `status reachable`.

- [ ] **Step 5: Checkpoint** — `git add -A && git commit -m "feat: python launchers get-cookies.py + run-relay.py"`

---

## Task 6: Static-mode scripts → Python

**Files:**
- Create: `src/scripts/loopstream.py`, `src/scripts/start-streams.py`, `src/scripts/stop-streams.py`

- [ ] **Step 1: loopstream.py**

Create `src/scripts/loopstream.py`:

```python
#!/usr/bin/env python3
"""Keep ONE streamlink server alive for one public YouTube channel (static mode).
Usage: python3 loopstream.py <CHANNEL_ID> <PORT>
Serves http://127.0.0.1:<PORT> for an OBS media source. Prefers 1080p, >=720p.
NOTE: PUBLIC channels only. The real (unlisted) flow is the relay (tools/run-relay.py).
"""
import subprocess, sys, time


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: loopstream.py <CHANNEL_ID> <PORT>")
    ch, port = sys.argv[1], sys.argv[2]
    url = f"https://www.youtube.com/channel/{ch}/live"
    while True:
        print(f">> [{port}] Connecting to {url}", flush=True)
        try:
            subprocess.call(["streamlink", url, "1080p60,1080p,720p60,720p",
                             "--player-external-http", "--player-external-http-port", port,
                             "--ringbuffer-size", "64M", "--hls-live-edge", "4",
                             "--retry-streams", "15", "--retry-open", "5"])
        except FileNotFoundError:
            sys.exit("ERROR: streamlink not found (brew install streamlink / pip install -U streamlink).")
        print(f">> [{port}] Stream ended or not live. Retrying in 10s...", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: start-streams.py**

Create `src/scripts/start-streams.py`:

```python
#!/usr/bin/env python3
"""Launch one streamlink server per channel (static/public mode), backgrounded,
each with a log + PID file so stop-streams.py can shut them down.
EDIT the FEEDS list: (CHANNEL_ID, PORT). Ports must match the OBS media sources.
NOTE: PUBLIC channels only. The real unlisted flow is the relay (tools/run-relay.py).
"""
import os, shutil, subprocess, sys

# ---- channels ----  (CHANNEL_ID, PORT)
FEEDS = [
    ("UCNye-wNBqNL5ZzHSJj3l8Bg", "53001"),   # Feed A - TEST: Al Jazeera English (24/7)
    ("UCknLrEdhRCp1aegoMqRaCZg", "53002"),   # Feed B - TEST: DW News (24/7)
    # Replace TEST IDs with the real streamer channel IDs before the event.
]
# ------------------


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    logdir = os.path.join(here, "logs")
    os.makedirs(logdir, exist_ok=True)
    if not shutil.which("streamlink"):
        sys.exit("streamlink not found (brew install streamlink / pip install -U streamlink).")
    loop = os.path.join(here, "loopstream.py")
    for i, (ch, port) in enumerate(FEEDS, 1):
        log = open(os.path.join(logdir, f"feed_{port}.log"), "ab")
        p = subprocess.Popen([sys.executable, loop, ch, port], stdout=log, stderr=subprocess.STDOUT)
        open(os.path.join(here, f"feed_{port}.pid"), "w").write(str(p.pid))
        print(f"Started Feed {i} -> channel {ch} on http://127.0.0.1:{port} (log: logs/feed_{port}.log)")
    print("\nAll feeds launched. Point each OBS media source at its http://127.0.0.1:PORT.")
    print("Stop everything with:  python3 stop-streams.py")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: stop-streams.py (cross-platform)**

Create `src/scripts/stop-streams.py`:

```python
#!/usr/bin/env python3
"""Stop every streamlink server started by start-streams.py (Mac/Linux + Windows)."""
import glob, os, signal, subprocess, sys


def kill_tree(pid):
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.call(["pkill", "-P", str(pid)], stderr=subprocess.DEVNULL)  # children first
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    pidfiles = glob.glob(os.path.join(here, "feed_*.pid"))
    for pf in pidfiles:
        try:
            pid = int(open(pf).read().strip())
        except ValueError:
            os.remove(pf); continue
        kill_tree(pid)
        print(f"Stopped {os.path.basename(pf)[:-4]} (PID {pid})")
        os.remove(pf)
    if os.name != "nt":
        subprocess.call(["pkill", "-f", "player-external-http"], stderr=subprocess.DEVNULL)
    if not pidfiles:
        print("No running feeds found.")
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Compile + behavior check (no streamlink needed)**

```bash
cd <repo>
python3 -m py_compile src/scripts/*.py && echo "compile OK"
python3 src/scripts/stop-streams.py   # no feeds running
python3 src/scripts/loopstream.py 2>&1 | head -1   # usage guard
```
Expected: `compile OK`, `No running feeds found.\nDone.`, and the loopstream `usage:` line.

- [ ] **Step 5: Checkpoint** — `git add -A && git commit -m "feat(scripts): port static-mode launchers to Python"`

---

## Task 7: Build script — `tools/build.py`

**Files:**
- Create: `tools/build.py`
- Modify: `tools/strip_companion_pass.py`, `tools/add_pov_source.py` stay as-is (already in tools/)

- [ ] **Step 1: Write build.py**

Create `tools/build.py`:

```python
#!/usr/bin/env python3
"""Build the distributable from src/ (single source of truth).
Produces dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip.
Usage: python3 tools/build.py
"""
import json, os, shutil, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
PKG = os.path.join(DIST, "IRO_Broadcast_Package")


def blank_pass(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("pass", "password") and isinstance(v, str):
                o[k] = ""
            else:
                blank_pass(v)
    elif isinstance(o, list):
        for x in o:
            blank_pass(x)


def cp(srcrel, dstrel):
    s = os.path.join(SRC, srcrel)
    d = os.path.join(PKG, dstrel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)


def main():
    if not os.path.isdir(SRC):
        sys.exit("ERROR: src/ not found")
    if os.path.exists(PKG):
        shutil.rmtree(PKG)
    os.makedirs(PKG)

    # top-level docs + director panel + setup-assets
    for f in ("IRO_Broadcast_Setup_Guide.md", "IRO_cheat_sheets.html", "README_SETUP.md"):
        cp(f"docs/{f}", f)
    cp("director/director-panel.html", "director-panel.html")
    cp("setup-assets.py", "setup-assets.py")
    cp("assets", "assets")
    cp("scripts", "scripts")
    cp("relay", "relay")  # iro-feeds.py + get-cookies.py

    # companion: copy + strip password (defense in depth)
    os.makedirs(os.path.join(PKG, "companion"))
    cfg = json.load(open(os.path.join(SRC, "companion", "iro-buttons.companionconfig"), encoding="utf-8"))
    blank_pass(cfg)
    json.dump(cfg, open(os.path.join(PKG, "companion", "iro-buttons.companionconfig"), "w", encoding="utf-8"), indent=1)

    # obs: ship the tokenized collection as .template.json (setup-assets localizes it)
    os.makedirs(os.path.join(PKG, "obs"))
    shutil.copy2(os.path.join(SRC, "obs", "IRO_Endurance.json"),
                 os.path.join(PKG, "obs", "IRO_Endurance.template.json"))

    # zip
    zip_path = os.path.join(DIST, "IRO_Broadcast_Package.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(PKG):
            for fn in files:
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, DIST))

    # verify
    def has_pw(o):
        if isinstance(o, dict):
            return any((k in ("pass", "password") and v) or has_pw(v) for k, v in o.items())
        if isinstance(o, list):
            return any(has_pw(x) for x in o)
        return False

    tpl = open(os.path.join(PKG, "obs", "IRO_Endurance.template.json"), encoding="utf-8").read()
    relay = open(os.path.join(PKG, "relay", "iro-feeds.py"), encoding="utf-8").read()
    blob = json.dumps(cfg)
    checks = {
        "companion pov buttons": "pov/reload" in blob,
        "companion password empty": not has_pw(cfg),
        "obs tokenized": "__IRO_ASSETS__/" in tpl and "GoogleDrive" not in tpl,
        "relay pov endpoint": "pov/reload" in relay,
        "no .sh/.bat shipped": not any(fn.endswith((".sh", ".bat")) for _, _, fs in os.walk(PKG) for fn in fs),
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"Built {PKG}")
    print(f"ZIP   {zip_path}  ({os.path.getsize(zip_path)//1024} KB)")
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
    if bad:
        sys.exit("BUILD VERIFY FAILED: " + ", ".join(bad))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the build**

```bash
cd <repo>
python3 tools/build.py
```
Expected: `Built …/dist/IRO_Broadcast_Package`, a ZIP size, and all checks `[OK]`.

- [ ] **Step 3: Independent verification of the dist contents**

```bash
cd <repo>
echo "tree:"; find dist/IRO_Broadcast_Package -maxdepth 2 -type f | sed 's|dist/IRO_Broadcast_Package/||' | sort
echo "--- companion password empty? ---"
python3 - <<'PY'
import json
cfg=json.load(open("dist/IRO_Broadcast_Package/companion/iro-buttons.companionconfig"))
bad=[]
def w(o):
    if isinstance(o,dict):
        for k,v in o.items():
            if k in ("pass","password") and v: bad.append(k)
            else: w(v)
    elif isinstance(o,list):
        for x in o: w(x)
w(cfg); print("non-empty passwords:", bad); assert not bad; print("OK")
PY
```
Expected: a clean tree (obs/IRO_Endurance.template.json, relay/iro-feeds.py + get-cookies.py, scripts/*.py, setup-assets.py, no `.sh`/`.bat`), `non-empty passwords: []`, `OK`.

- [ ] **Step 4: Smoke-test the built package's setup-assets + relay**

```bash
cd <repo>/dist/IRO_Broadcast_Package
python3 setup-assets.py    # writes obs/IRO_Endurance.import.json with local paths
python3 -c "import json,os;d=json.load(open('obs/IRO_Endurance.import.json'));fs=[(s.get('settings') or {}).get('file') for s in d['sources'] if (s.get('settings') or {}).get('file')];print('all abs+exist:', all(os.path.isabs(f) and os.path.exists(f) for f in fs))"
cd <repo>
```
Expected: setup-assets prints OK; `all abs+exist: True` (the dist ships the same local assets/).

- [ ] **Step 5: Checkpoint** — `git add -A && git commit -m "feat(build): tools/build.py generates dist from src"`

---

## Task 8: `sync-assets.py` + READMEs

**Files:**
- Create: `tools/sync-assets.py`
- Create/rewrite: `README.md` (repo root)
- Modify: `src/docs/README_SETUP.md` (Python commands + new package layout)

- [ ] **Step 1: Write sync-assets.py (Drive -> src/assets/)**

Create `tools/sync-assets.py`:

```python
#!/usr/bin/env python3
"""Refresh src/assets/ from the production Google-Drive folder (when graphics change).
Copies only the known asset filenames. Usage: python3 tools/sync-assets.py [--drive DIR]
"""
import argparse, os, shutil, sys

ASSETS = ["Overlay.png", "Post Race Interviews.png", "Quali Results.png",
          "Race Results.png", "Season Schedule.png", "Standings.png", "YT-IRO-Race.png"]
# NOTE: superseded during execution — the shipped tools/sync-assets.py takes the
# source per-user (--source / IRO_ASSETS_SOURCE / runtime/assets-source.txt), no
# hardcoded path. Placeholder kept here only to show the original plan shape:
DEFAULT_DRIVE = os.path.expanduser("~/path/to/your/graphics/folder")


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = os.path.join(root, "src", "assets")
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default=DEFAULT_DRIVE)
    a = ap.parse_args()
    if not os.path.isdir(a.drive):
        sys.exit(f"ERROR: Drive folder not found: {a.drive}")
    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in ASSETS:
        s = os.path.join(a.drive, name)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dst, name)); n += 1; print(f"  {name}")
        else:
            print(f"  MISSING in Drive: {name}")
    print(f"synced {n}/{len(ASSETS)} assets -> {dst}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Compile-check sync-assets.py**

Run: `python3 -m py_compile tools/sync-assets.py && echo OK`
Expected: `OK`.

- [ ] **Step 3: Rewrite the repo root README.md**

Replace `<repo>/README.md` with:

```markdown
# IRO Endurance Broadcast — Repository

Single-source repo for the IRO Endurance broadcast producer station.
**Edit only under `src/`.** `dist/` and `runtime/` are generated and gitignored.

## Layout
- `src/` — source of truth: `relay/`, `obs/`, `companion/`, `director/`, `assets/`, `scripts/`, `docs/`, `setup-assets.py`
- `tools/` — maintainer scripts (build, tokenize, sync, helpers) — not shipped
- `tests/` — `test_pov.py`
- `runtime/` — cookies/logs/caches (gitignored)
- `dist/` — built distributable + ZIP (gitignored)
- `docs/superpowers/` — specs & plans

## Run the relay (producer)
```bash
python3 src/setup-assets.py --out runtime/IRO_Endurance.import.json   # once: localize OBS assets
# OBS -> Scene Collection -> Import -> runtime/IRO_Endurance.import.json
python3 src/relay/get-cookies.py chrome --runtime-dir runtime         # before each event
python3 tools/run-relay.py                                            # start the relay
```

## Build the distributable
```bash
python3 tools/build.py     # -> dist/IRO_Broadcast_Package/ + dist/IRO_Broadcast_Package.zip
```

## After editing the OBS collection in OBS
Re-export from OBS, then fold the change back into the tokenized source:
```bash
python3 tools/tokenize-obs.py /path/to/exported.json src/obs/IRO_Endurance.json
```

## Refresh graphics from Google Drive
```bash
python3 tools/sync-assets.py
```
```

- [ ] **Step 4: Update README_SETUP.md (Python commands + new package layout)**

In `src/docs/README_SETUP.md`, apply these replacements:
- Replace `setup-assets.sh`/`setup-assets.bat` mentions with **`python3 setup-assets.py`** (it writes `obs/IRO_Endurance.import.json` — import that).
- Replace `./start-streams.sh` / `start-streams.bat` with **`python3 scripts/start-streams.py`**, stop with **`python3 scripts/stop-streams.py`**.
- Replace relay/cookies commands `./relay/get-cookies.sh chrome` with **`python3 relay/get-cookies.py chrome`** and `python3 relay/iro-feeds.py` stays.
- In the "Package contents" block, replace the `setup-assets.sh / .bat`, `scripts-mac-linux/ , scripts-windows/`, and `relay/get-cookies.sh / .bat` lines with:
  ```
  setup-assets.py              <- localize OBS asset paths (writes obs/IRO_Endurance.import.json)
  scripts/                     <- static-mode launchers (start/stop/loopstream, Python)
  relay/get-cookies.py         <- export YouTube cookies (Python)
  ```

(Make the edits with the Edit tool against the exact current strings; verify with the grep in Step 5.)

- [ ] **Step 5: Verify the docs**

```bash
cd <repo>
grep -c "tools/build.py" README.md
grep -c "setup-assets.py" src/docs/README_SETUP.md
! grep -nE "setup-assets\.sh|start-streams\.sh|get-cookies\.sh" src/docs/README_SETUP.md && echo "no .sh refs left"
```
Expected: `1`, ≥`1`, `no .sh refs left`.

- [ ] **Step 6: Checkpoint** — `git add -A && git commit -m "docs+tools: repo README, README_SETUP python commands, sync-assets"`

---

## Task 9: Remove the old tree, rebuild, final verification

**Files:**
- Delete: old root duplicates, the old package, the ZIP, old shell/batch scripts, stale caches
- Rebuild: `dist/` via `tools/build.py`
- Modify: memory file

- [ ] **Step 1: Delete the superseded files**

```bash
cd <repo>
rm -rf IRO_Broadcast_Package IRO_Broadcast_Package.zip
rm -rf scripts-mac-linux scripts-windows
rm -f get-cookies.sh get-cookies.bat
rm -f iro-buttons.companionconfig            # stale page export (current config is src/companion/)
rm -f IRO_Endurance.json                     # now tokenized in src/obs/
rm -f schedule.txt schedule.cache.txt pov.cache.txt
rm -rf logs
echo "remaining top-level:"; ls -1
```
Expected top-level: `README.md`, `cookies.txt` (until moved), `dist/`, `docs/`, `runtime/`, `src/`, `tests/`, `tools/`, `.gitignore` (hidden).

- [ ] **Step 2: Move the existing cookies into runtime/ (keep the logged-in session)**

```bash
cd <repo>
[ -f cookies.txt ] && mv cookies.txt runtime/cookies.txt && echo "cookies -> runtime/"
ls -1   # cookies.txt should be gone from root
```

- [ ] **Step 3: Rebuild dist from the cleaned src/**

```bash
cd <repo>
python3 tools/build.py
```
Expected: all checks `[OK]`.

- [ ] **Step 4: Full regression — tests + relay end-to-end from src/**

```bash
cd <repo>
python3 tests/test_pov.py | tail -1
python3 tools/run-relay.py --no-panel > /tmp/final.log 2>&1 &
sleep 5
curl -s http://127.0.0.1:8088/status | python3 -c "import sys,json;d=json.load(sys.stdin);print('schedule_len',d['schedule_len'],'| pov',d['pov']['state'])"
kill -TERM $(lsof -nP -iTCP:8088 -sTCP:LISTEN -t) 2>/dev/null
echo "runtime contents:"; ls runtime/
```
Expected: `ALL PASS`; `/status` shows the real `schedule_len` + `pov stopped`; `runtime/` holds cookies.txt + logs/ + caches; nothing written under `src/`.

- [ ] **Step 5: Self-containment audit**

```bash
cd <repo>
echo "external refs in src/ (expect none):"
grep -rIl "GoogleDrive\|<downloads>" src/ 2>/dev/null || echo "  none"
echo "shell/batch left (expect none):"
find src tools -name "*.sh" -o -name "*.bat" 2>/dev/null | grep . || echo "  none"
```
Expected: `none` for both.

- [ ] **Step 6: Update memory**

In `…/memory/iro-broadcast-setup.md`, add a note: repo restructured to single-source (`src/`) + build (`tools/build.py` → `dist/`, gitignored) + `runtime/` (gitignored); all scripts ported to Python; OBS collection self-contained (tokenized `__IRO_ASSETS__`, assets in `src/assets/`); relay gained `--runtime-dir`; `schedule.txt` dropped (auto-template on cold start); old `IRO_Broadcast_Package/` is now generated, not hand-maintained.

- [ ] **Step 7: Final checkpoint** — `git add -A && git commit -m "chore: remove legacy tree; dist is now built from src"`

---

## Done-when

- Everything edited lives under `src/`; `dist/` + `runtime/` are generated and gitignored.
- `python3 tools/build.py` reproduces the distributable (checks all `[OK]`), no `.sh`/`.bat` shipped.
- `python3 tests/test_pov.py` passes; `python3 tools/run-relay.py` runs the relay with runtime data in `runtime/`.
- OBS collection is tokenized (no Google-Drive paths); assets live in `src/assets/`.
- No references outside the repo; `cookies.txt` is in `runtime/` and gitignored.
