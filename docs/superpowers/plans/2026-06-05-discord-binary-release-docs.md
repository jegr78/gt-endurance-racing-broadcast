# Discord install + first binary release + operator docs on `iro` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `iro install-apps` also installs Discord; release assets become archives (`iro` + `.env.example`, auto-copied to `.env` on first run); first `v0.1.0` release; all operator docs use the binary.

**Architecture:** Three independent parts executed in order: (1) Discord support in `src/scripts/install_apps.py` + a `.deb` helper in `installer_common.py`; (2) `release.yml` packages archives and `src/iro.py` self-creates `.env`; (3) docs rework — wiki + shipped docs swap `python3 src/iro.py …` → `iro …`, the setup page is restructured around the binary download. Code lands first, then the `v0.1.0` tag (so release URLs are real), then docs, then wiki publish.

**Tech Stack:** Pure Python stdlib (no pytest — test files are runnable scripts), GitHub Actions, GitHub-flavored Markdown wiki.

**Spec:** `docs/superpowers/specs/2026-06-05-discord-install-binary-docs-design.md`

**Conventions for every task:** repo root is `/Users/jegr/Downloads/IRO_Broadcast_Setup`; run all commands from there. English-only code/docs. Never edit `dist/` or `runtime/`.

---

### Task 1: Discord package data + presence detection

**Files:**
- Modify: `src/scripts/install_apps.py` (APPS, WINGET_APP_IDS, BREW_CASKS, `_WINDOWS_APP_PATHS`, `_DARWIN_APP_PATHS`, `_LINUX_APP_PATHS`)
- Test: `tests/test_install_apps.py`

- [ ] **Step 1: Update/add the failing tests**

In `tests/test_install_apps.py`, replace `t_app_ids` with:

```python
def t_app_ids():
    assert m.WINGET_APP_IDS == {"obs": "OBSProject.OBSStudio",
                                "companion": "Bitfocus.Companion",
                                "tailscale": "Tailscale.Tailscale",
                                "discord": "Discord.Discord"}
    assert m.BREW_CASKS == {"obs": "obs", "companion": "companion",
                            "tailscale": "tailscale-app", "discord": "discord"}
```

Add after `t_app_present_linux_companion_service`:

```python
def t_app_present_discord_paths():
    # Windows: Squirrel per-user install — Update.exe is the version-stable path
    env = {"ProgramFiles": r"C:\Program Files",
           "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    hit = r"C:\Users\x\AppData\Local\Discord\Update.exe"
    assert m.app_present("discord", "win32", env=env, exists=lambda p: p == hit,
                         which=lambda n: None)
    assert m.app_present("discord", "darwin",
                         exists=lambda p: p == "/Applications/Discord.app",
                         which=lambda n: None)
    assert m.app_present("discord", "linux",
                         exists=lambda p: p == "/usr/bin/discord",
                         which=lambda n: None)
    assert not m.app_present("discord", "linux", exists=lambda p: False,
                             which=lambda n: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_install_apps.py`
Expected: FAIL — `AssertionError` in `t_app_ids` (no discord key).

- [ ] **Step 3: Implement the data**

In `src/scripts/install_apps.py`:

```python
APPS = ("obs", "companion", "tailscale", "discord")

WINGET_APP_IDS = {"obs": "OBSProject.OBSStudio",
                  "companion": "Bitfocus.Companion",
                  "tailscale": "Tailscale.Tailscale",
                  "discord": "Discord.Discord"}
# The tailscale-app CASK is the GUI app; the plain `tailscale` formula is the
# bare daemon — producers need the app.
BREW_CASKS = {"obs": "obs", "companion": "companion",
              "tailscale": "tailscale-app", "discord": "discord"}
```

Add to `_WINDOWS_APP_PATHS` (Discord is a Squirrel per-user install — the
versioned `app-x.y.z\Discord.exe` folders move on every update, `Update.exe`
is stable):

```python
    "discord": (r"%LOCALAPPDATA%\Discord\Update.exe",),
```

Add to `_DARWIN_APP_PATHS`:

```python
    "discord": ("/Applications/Discord.app",),
```

Add to `_LINUX_APP_PATHS` (what the official .deb installs):

```python
    "discord": ("/usr/share/discord", "/usr/bin/discord"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_apps.py`
Expected: `ALL PASS` (including the winget/brew command tests, which derive from the dicts).

- [ ] **Step 5: Commit**

```bash
git add src/scripts/install_apps.py tests/test_install_apps.py
git commit -m "feat(install-apps): Discord package ids + presence detection (winget/brew/paths)"
```

---

### Task 2: Linux `.deb` install step for Discord

**Files:**
- Modify: `src/scripts/installer_common.py` (new `install_remote_deb`)
- Modify: `src/scripts/install_apps.py` (`DISCORD_DEB`, `linux_install_steps`, `_install_linux`, `apps_manual_guide`, first-run notes in `main`)
- Test: `tests/test_install_apps.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_install_apps.py`, add after `t_linux_plan_scripts`:

```python
def t_linux_plan_discord_deb():
    steps = m.linux_install_steps(["discord"], which=lambda n: "/usr/bin/" + n)
    assert steps == [("deb", m.DISCORD_DEB)]
    assert m.DISCORD_DEB.startswith("https://discord.com/")
```

In `t_manual_guide_has_urls_per_os`, add one line inside the loop:

```python
        assert "discord.com" in guide
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_install_apps.py`
Expected: FAIL — `AttributeError: ... has no attribute 'DISCORD_DEB'`.

- [ ] **Step 3: Implement**

In `src/scripts/installer_common.py`, add after `run_remote_script`:

```python
def install_remote_deb(url):
    """Download a vendor .deb (HTTPS, cert-verified) to a temp file and install
    it visibly with apt-get — no shell pipes, the operator saw the URL and
    confirmed beforehand. World-readable so apt's sandboxed fetcher can read it."""
    import tempfile, urllib.request
    print("Downloading:", url)
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".deb")
    try:
        tmp.write(body)
        tmp.close()
        os.chmod(tmp.name, 0o644)
        cmd = ["sudo", "apt-get", "install", "-y", tmp.name]
        print("Running:", " ".join(cmd))
        return subprocess.call(cmd)
    finally:
        os.unlink(tmp.name)
```

In `src/scripts/install_apps.py`:

After the `COMPANION_INSTALLER` constant add:

```python
# Discord's official Linux .deb (the snap is community-maintained, not Discord Inc.)
DISCORD_DEB = "https://discord.com/api/download?platform=linux&format=deb"
```

In `linux_install_steps`, extend the docstring's step-kind list with
`('deb', url) downloads url and installs it with apt-get` and append after the
companion block:

```python
    if "discord" in apps:
        steps.append(("deb", DISCORD_DEB))
```

In `_install_linux`, the **print** loop becomes:

```python
    for step in steps:
        if step[0] == "run":
            print("  $", " ".join(step[1]))
        elif step[0] == "deb":
            print("  $ sudo apt-get install -y <downloaded .deb>   #", step[1])
        else:
            print("  $", " ".join(step[2]), "<", step[1])
```

and the **execute** loop becomes:

```python
    for step in steps:
        if step[0] == "run":
            print("Running:", " ".join(step[1]))
            rc = subprocess.call(step[1])
        elif step[0] == "deb":
            rc = _common().install_remote_deb(step[1])
        else:
            rc = _run_remote_script(step[1], step[2])
        if rc != 0:
            failed.append(step[1])  # argv for 'run' steps, URL for 'script'/'deb' steps
```

In `apps_manual_guide`, Linux branch — add after the Companion lines:

```python
        lines.append("  Discord  (https://discord.com/download):")
        lines.append("    curl -fsSL 'https://discord.com/api/download?platform=linux&format=deb' -o /tmp/discord.deb")
        lines.append("    sudo apt-get install -y /tmp/discord.deb")
```

macOS/Windows branch — add after the Tailscale line:

```python
        lines.append("  Discord    : https://discord.com/download")
```

In `main()`, first-run notes at the end — add after the OBS line:

```python
    print("  Discord: sign in — used for the interview audio (OBS app-audio capture).")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_install_apps.py && python3 tests/test_installer_common.py`
Expected: `ALL PASS` twice.

- [ ] **Step 5: Sanity-check the .deb URL resolves (one-off, not a test)**

Run: `curl -sIL -o /dev/null -w "%{http_code} %{url_effective}\n" "https://discord.com/api/download?platform=linux&format=deb"`
Expected: `200 https://dl.discordapp.net/...discord-....deb` (a redirect to the CDN .deb).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/installer_common.py src/scripts/install_apps.py tests/test_install_apps.py
git commit -m "feat(install-apps): install Discord on Linux via the official .deb"
```

---

### Task 3: Frozen binary self-creates `.env` from `.env.example`

**Files:**
- Modify: `src/iro.py` (new `ensure_env_file`, called at the top of `main()`)
- Test: `tests/test_iro.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_iro.py`, add next to `t_parse_env_text`:

```python
def t_ensure_env_file_creates_once():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, ".env.example"), "w", encoding="utf-8") as fh:
            fh.write("IRO_SHEET_ID=\n")
        # not frozen -> no-op
        assert m.ensure_env_file(d, frozen=False) is False
        assert not os.path.exists(os.path.join(d, ".env"))
        # frozen + template + no .env -> created from the template
        assert m.ensure_env_file(d, frozen=True) is True
        with open(os.path.join(d, ".env"), encoding="utf-8") as fh:
            assert fh.read() == "IRO_SHEET_ID=\n"
        # existing .env is never overwritten
        with open(os.path.join(d, ".env"), "w", encoding="utf-8") as fh:
            fh.write("IRO_SHEET_ID=real\n")
        assert m.ensure_env_file(d, frozen=True) is False
        with open(os.path.join(d, ".env"), encoding="utf-8") as fh:
            assert fh.read() == "IRO_SHEET_ID=real\n"


def t_ensure_env_file_without_template():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert m.ensure_env_file(d, frozen=True) is False
        assert not os.path.exists(os.path.join(d, ".env"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_iro.py`
Expected: FAIL — `AttributeError: ... has no attribute 'ensure_env_file'`.

- [ ] **Step 3: Implement**

In `src/iro.py`, add directly above `_load_env_frozen` (uses the module's
existing `shutil` import — verify `import shutil` is at the top, it is used by
`export_companion`):

```python
def ensure_env_file(exe_dir, frozen=None):
    """First run of the frozen binary: the release archives ship .env.example
    next to the binary but never a real .env (an upgrade extract must not
    clobber filled-in secrets). Copy the template once so the operator only
    fills in values. Returns True iff .env was created."""
    frozen = IS_FROZEN if frozen is None else frozen
    if not frozen:
        return False
    env_path = os.path.join(exe_dir, ".env")
    example = os.path.join(exe_dir, ".env.example")
    if os.path.exists(env_path) or not os.path.exists(example):
        return False
    try:
        shutil.copyfile(example, env_path)
    except OSError:
        return False
    print("created .env next to the binary — fill in IRO_SHEET_ID and "
          "IRO_TIMER_URL (see the comments inside).")
    return True
```

In `main()` (currently starts with `_load_env_frozen()` at `src/iro.py:519`):

```python
def main(argv=None):
    ensure_env_file(os.path.dirname(sys.executable))
    _load_env_frozen()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_iro.py`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/iro.py tests/test_iro.py
git commit -m "feat(iro): frozen binary creates .env from the shipped .env.example on first run"
```

---

### Task 4: Release archives (binary + `.env.example`) + CLAUDE.md

**Files:**
- Modify: `.github/workflows/release.yml` (matrix + packaging step)
- Modify: `CLAUDE.md` (asset names in the "Standalone binary" section)

- [ ] **Step 1: Rewrite the matrix and upload steps in `release.yml`**

Replace the `matrix.include` block with:

```yaml
      matrix:
        include:
          - os: windows-latest
            asset: iro-windows.zip
            built: dist/bin/iro.exe
            binary: iro.exe
          - os: macos-latest
            asset: iro-macos.tar.gz
            built: dist/bin/iro
            binary: iro
          - os: ubuntu-latest
            asset: iro-linux.tar.gz
            built: dist/bin/iro
            binary: iro
```

Replace the final "Upload release asset" step with these two steps
(`defaults.run.shell: bash` already applies on all three OSes; `python` is on
PATH from `setup-python`; `python -m zipfile` keeps the packaging
stdlib-only — no `zip`/`7z` dependency on the Windows runner; tar preserves
the executable bit so operators never `chmod`):

```yaml
      - name: Package the release asset (binary + .env.example)
        run: |
          mkdir staging
          cp "${{ matrix.built }}" "staging/${{ matrix.binary }}"
          cp .env.example staging/
          cd staging
          case "${{ matrix.asset }}" in
            *.zip)    python -m zipfile -c "../${{ matrix.asset }}" "${{ matrix.binary }}" .env.example ;;
            *.tar.gz) tar czf "../${{ matrix.asset }}" "${{ matrix.binary }}" .env.example ;;
          esac
      - name: Upload release asset
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release upload "${{ github.ref_name }}" "${{ matrix.asset }}" --clobber
```

- [ ] **Step 2: Update `CLAUDE.md`**

In the "Standalone binary (PyInstaller)" section, replace the sentence

> Releases: push a `v*` tag — `.github/workflows/release.yml` tests, builds, smoke-tests and uploads `iro-windows.exe` / `iro-macos` / `iro-linux`.

with:

> Releases: push a `v*` tag — `.github/workflows/release.yml` tests, builds,
> smoke-tests and uploads `iro-windows.zip` / `iro-macos.tar.gz` /
> `iro-linux.tar.gz` (each contains the `iro` binary + `.env.example`; on
> first run the frozen binary copies it to `.env` — see `ensure_env_file`).

- [ ] **Step 3: Validate the workflow YAML parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml ok')" 2>/dev/null || python3 -c "print('pyyaml missing — visual check only')"`
Expected: `yaml ok` (or fall back to careful visual review of indentation).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml CLAUDE.md
git commit -m "feat(release): ship archives (iro + .env.example) on all OSes"
```

---

### Task 5: Full verification + push + CI

- [ ] **Step 1: Run the whole suite and the package build**

Run: `python3 tools/run-tests.py && python3 tools/build.py`
Expected: `ALL TEST FILES PASS`, then build self-verify OK (tokenization, blanked password, no secrets, no shell scripts).

- [ ] **Step 2: Push and watch CI**

```bash
git push
gh run list --branch main --limit 3        # grab the CI run id
gh run watch <CI-run-id> --exit-status
```

Expected: CI success on all 9 jobs (3 OSes × 3 Pythons). Fix any failure before continuing — Windows is the usual suspect for path-separator assumptions.

---

### Task 6: Tag `v0.1.0` and verify the release end-to-end

- [ ] **Step 1: Tag (only with green CI from Task 5)**

```bash
git tag v0.1.0 && git push origin v0.1.0
```

- [ ] **Step 2: Watch the release workflow**

```bash
gh run list --workflow release.yml --limit 1   # grab the run id
gh run watch <release-run-id> --exit-status
```

Expected: success; three jobs each upload one asset.

- [ ] **Step 3: Verify assets and smoke-test the macOS archive locally**

```bash
gh release view v0.1.0                  # lists iro-windows.zip, iro-macos.tar.gz, iro-linux.tar.gz
rm -rf /tmp/iro-rel && mkdir /tmp/iro-rel && cd /tmp/iro-rel
gh release download v0.1.0 -p iro-macos.tar.gz
tar xzf iro-macos.tar.gz && ls -la      # iro (executable) + .env.example
./iro --version
```

Expected: `ls` shows `iro` with `x` bits and `.env.example`; `./iro --version` prints
`created .env next to the binary — …` (first run, proves `ensure_env_file` works
frozen) followed by `iro v0.1.0`; a second `./iro --version` prints only the version.
(`gh release download` bypasses browser quarantine, so no Gatekeeper prompt here.)

- [ ] **Step 4: Return to the repo**

```bash
cd /Users/jegr/Downloads/IRO_Broadcast_Setup
```

---

### Task 7: Wiki — rewrite `Set-up-the-broadcast-PC.md`

**Files:**
- Modify: `src/docs/wiki/Set-up-the-broadcast-PC.md` (full replacement)

- [ ] **Step 1: Replace the page content**

Replace the entire file with (keeps the step count at 11; steps 5–11 are the
old steps with command swaps; `<details>` renders collapsed on GitHub wikis):

````markdown
# Set up the broadcast PC

Do this **once** per machine — about 30 minutes. When you're done, go to
[Run an event](Run-an-event).

> Tip: `iro preflight` checks your machine and tells you what's still missing.
> Run it whenever you're unsure.

## What you need

- A reasonably modern PC — **macOS, Windows, or Linux**. 16 GB RAM works but is tight, so
  reboot before events; 32 GB is comfortable. A wired internet connection.
- A **YouTube login** (for cookies), the **shared Google Sheet** link, and the
  **stagetimer** link from the team.

## 1 — Get the `iro` tool

Download the archive for your OS from the
[latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest):

| OS | File |
|---|---|
| Windows | `iro-windows.zip` |
| macOS | `iro-macos.tar.gz` |
| Linux | `iro-linux.tar.gz` |

Extract it into a folder of its own (e.g. `Documents/IRO/`) — the tool keeps its
working files (`.env`, `runtime/`) next to the binary. Open a terminal **in that
folder** and check it runs:

```bash
./iro --version          # Windows: iro --version   (PowerShell: .\iro)
```

The first run also creates a `.env` file next to the binary (you fill it in at
step 4).

> **One-time OS warning** (the binary is unsigned): **Windows** SmartScreen →
> "More info" → "Run anyway". **macOS**: if blocked, System Settings →
> Privacy & Security → "Open Anyway" (or right-click → Open).

All commands in this wiki are written as `iro …` — type them in a terminal in
this folder (macOS/Linux: `./iro …` unless you add the folder to your PATH).

<details>
<summary>Alternative: run from source (needs Python 3)</summary>

Clone or download this repository and install Python 3 (macOS: usually
preinstalled, else `brew install python`; Windows: [python.org](https://www.python.org/downloads/)
installer with **"Add python.exe to PATH"** ticked; Linux: `sudo apt install python3`).
Then use `python3 src/iro.py …` wherever the docs say `iro …`, and copy
`.env.example` to `.env` in the repo root yourself.
</details>

## 2 — Install the apps

```bash
iro install-apps
```

Installs whichever of these are missing — **OBS Studio** (the broadcast itself),
**Bitfocus Companion** (the director's button board), **Tailscale** (private
network so remote directors can connect), **Discord** (interview audio) — via
winget on Windows, Homebrew on macOS, apt + the official vendor installers on
Linux (it lists the steps and asks before running them).

<details>
<summary>Alternative: install them manually</summary>

| App | What it's for | Download |
|---|---|---|
| **OBS Studio** (v30+) | The broadcast itself | [obsproject.com/download](https://obsproject.com/download) |
| **Bitfocus Companion** | The director's button board | [bitfocus.io/companion](https://bitfocus.io/companion) |
| **Tailscale** | Private network so remote directors can connect | [tailscale.com/download](https://tailscale.com/download) |
| **Discord** | Interview audio | [discord.com/download](https://discord.com/download) |
</details>

## 3 — Install the command-line tools

```bash
iro install-tools
```

Installs `streamlink`, `yt-dlp`, `ffmpeg` and `deno` — they pull each
commentator's stream into OBS and pass YouTube's bot check.

> `deno` is required — without it feeds fail with *"Sign in to confirm you're not a bot."*
> Details: [Relay — how the feeds work](Relay-Mode).

<details>
<summary>Alternative: install them manually</summary>

- **macOS:** `brew install streamlink yt-dlp ffmpeg deno` (Homebrew first if needed: [brew.sh](https://brew.sh))
- **Windows:** `pip install -U streamlink yt-dlp` then `winget install Gyan.FFmpeg DenoLand.Deno`
- **Linux:** `brew install streamlink yt-dlp ffmpeg deno`, or your distro's packages
  (`apt`/`dnf`) plus `pip install -U streamlink yt-dlp`

Check them: `streamlink --version`, `yt-dlp --version`, `ffmpeg -version`, `deno --version`.
</details>

## 4 — Add your secrets (`.env`)

The first `iro` run created a `.env` file next to the binary. Open it in any
text editor and fill in two values from the team:

- `IRO_SHEET_ID` — the ID in the shared Google Sheet link.
- `IRO_TIMER_URL` — the stagetimer output link.

Keep `.env` private; never share it. Full detail: [Configuration & secrets](Configuration).

## 5 — Import the OBS scenes

```bash
iro setup --out runtime/IRO_Endurance.import.json
```

Then in OBS: **Scene Collection → Import →** pick that file, and switch to it. Don't move
the folder afterwards. Step-by-step: [OBS & scenes](OBS-Setup).

## 6 — Import the Companion buttons

Open Companion (launcher → **GUI Interface = All Interfaces**, port `8000` → **Launch
GUI**), then import the provided button config (`iro export companion` writes the
file). Details: [Companion](Companion).

## 7 — Let Companion control OBS

In OBS: **Tools → WebSocket Server Settings →** enable it (port `4455`), turn on
authentication, set a password — and enter the **same** password in Companion's OBS
connection.

## 8 — Connect remote directors (Tailscale)

Open Tailscale, sign in (free account — this owns your private network), then note this
machine's IP (`100.x.y.z`) from the Tailscale menu. Invite each director (free, up to 6
people) at [login.tailscale.com](https://login.tailscale.com/admin/users); they install
Tailscale and sign in too. A director can then open `http://100.x.y.z:8000/tablet` to drive
the show. More: [Director guide](Director).

## 9 — Get YouTube cookies

```bash
iro cookies chrome   # or firefox / safari / edge — any logged-in browser
```

This lets the feeds bypass YouTube's bot check. OS notes: on **macOS**, Chrome/Edge show a
Keychain prompt and Safari needs Full Disk Access; on **Windows** and **Linux** the browser
export usually runs without a prompt (Firefox needs none anywhere). Refresh before each
event — cookies expire.

## 10 — Discord audio (only the producer who runs interviews)

Interviews happen at the end over Discord voice. Add the Discord audio source in OBS:

- **macOS:** *App Audio Capture* bound to Discord — keep Discord **windowed** (not
  fullscreen) and grant OBS *Screen & System Audio Recording* permission.
- **Windows:** *Application Audio Capture (BETA)* → pick Discord.
- **Linux:** *Application Audio Capture* (PipeWire) or an *Audio Output Capture* monitor
  source — *should work, not yet tested on Linux.*

Don't also capture Discord via desktop audio, or you'll hear it twice.

## 11 — Pre-flight check

```bash
iro preflight
```

Fix anything it flags. Then you're ready → [Run an event](Run-an-event).
````

- [ ] **Step 2: Verify no stale command style remains on the page**

Run: `grep -n "python3" src/docs/wiki/Set-up-the-broadcast-PC.md`
Expected: matches only inside the two `<details>` "run from source / manual" blocks.

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/Set-up-the-broadcast-PC.md
git commit -m "docs(wiki): setup page on the iro release binary (manual paths as fallback)"
```

---

### Task 8: Wiki — command swaps on the remaining operator pages

**Files:**
- Modify: `src/docs/wiki/Run-an-event.md`, `src/docs/wiki/If-something-goes-wrong.md`, `src/docs/wiki/Relay-Mode.md`, `src/docs/wiki/OBS-Setup.md`, `src/docs/wiki/Configuration.md`, `src/docs/wiki/Static-Mode.md`, `src/docs/wiki/Home.md`

- [ ] **Step 1: Apply the mechanical rule**

In the six operator pages (NOT `Build-and-maintenance.md`), replace every
occurrence of `python3 src/iro.py ` and `python3 iro.py ` with `iro `.
Read each file first; besides the plain swap, apply these page-specific edits:

- **`Relay-Mode.md`** — the repo/package dual lines (currently lines 53–55)
  collapse to:

  ```
  iro relay start        # background
  iro relay run          # foreground/debug mode
  ```

  and the paragraph below keeps `iro relay stop`. Add one sentence at the end
  of that paragraph: `(Developers running from the repo: python3 src/iro.py
  works the same everywhere.)`

- **`Configuration.md`** — the block at lines 47–48 becomes a single line
  `iro setup --out runtime/IRO_Endurance.import.json` (drop the
  "in the distributed package" comment line — the binary made it obsolete).

- **`Static-Mode.md`** — the usage block (lines 43–44) becomes:

  ```
  iro streams start     # launches one streamlink server per feed
  iro streams stop      # stops them (validates each PID is really a feed)
  ```

  Leave the architecture references to `src/scripts/start-streams.py` /
  `stop-streams.py` (lines 24, 47) as they are — they describe internals, and
  the page already says the `iro` CLI is the operator entrypoint.

- **`Home.md`** — add one bullet to the top "start here" area (after the intro
  paragraph, before or within the first link list, wherever the page's existing
  structure fits):

  ```markdown
  - **Get the tool:** download the `iro` binary for your OS from the
    [latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest)
    — then follow [Set up the broadcast PC](Set-up-the-broadcast-PC).
  ```

- [ ] **Step 2: Verify**

Run: `grep -rn "python3 src/iro.py\|python3 iro.py" src/docs/wiki/`
Expected: matches only in `Set-up-the-broadcast-PC.md` (the run-from-source fallback) and `Relay-Mode.md` (the one developer note).

- [ ] **Step 3: Commit**

```bash
git add src/docs/wiki/
git commit -m "docs(wiki): operator pages use the iro binary"
```

---

### Task 9: Wiki — release process in `Build-and-maintenance.md`

**Files:**
- Modify: `src/docs/wiki/Build-and-maintenance.md` (this page keeps `python3` everywhere — it is the dev/build page)

- [ ] **Step 1: Add a release section**

Read the page; add this section after the existing build section, matching the
page's heading level:

````markdown
## Releases (standalone binaries)

Operators download `iro` from GitHub Releases and never need Python. Cutting a
release: make sure CI is green on `main`, then push a semver tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

`.github/workflows/release.yml` then tests on all three OSes, builds the
binaries with PyInstaller, stamps the tag into `iro --version`, creates the
GitHub release with generated notes, and uploads `iro-windows.zip` /
`iro-macos.tar.gz` / `iro-linux.tar.gz`. Each archive contains the `iro`
binary plus `.env.example`; on first run the binary copies it to `.env` next
to itself. The binaries are unsigned — operators see a one-time
SmartScreen/Gatekeeper warning (documented on the setup page).
````

- [ ] **Step 2: Commit**

```bash
git add src/docs/wiki/Build-and-maintenance.md
git commit -m "docs(wiki): document the tag-driven release process"
```

---

### Task 10: Shipped operator docs

**Files:**
- Modify: `src/docs/README_SETUP.md`, `src/docs/IRO_Broadcast_Setup_Guide.md`
- Check (likely no change): `src/docs/IRO_cheat_sheets.html`

- [ ] **Step 1: Swap commands in the two markdown docs**

Read both files. Apply the same rule as Task 8 (`python3 src/iro.py ` /
`python3 iro.py ` → `iro `). In `IRO_Broadcast_Setup_Guide.md`, find the
prerequisites/install section and replace any "install Python" instruction
with the binary download (mirror the wording of Task 7 step 1: latest-release
link, the three archive names, extract to its own folder, one-time unsigned-
binary warning, first run creates `.env`). Keep any explicitly dev-facing
notes on Python as a "run from source" alternative.

- [ ] **Step 2: Check the cheat sheets**

Run: `grep -n "python3\|src/iro.py" src/docs/IRO_cheat_sheets.html`
Expected: no matches (verified during planning) — if any appear, apply the same swap.

- [ ] **Step 3: Verify**

Run: `grep -rn "python3 src/iro.py\|python3 iro.py" src/docs/ --include="*.md" | grep -v wiki/`
Expected: no matches outside explicit run-from-source alternatives.

- [ ] **Step 4: Commit**

```bash
git add src/docs/
git commit -m "docs: shipped operator docs use the iro binary"
```

---

### Task 11: Root `README.md` operator quickstart

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rework the operator part**

Read `README.md`. In the operator/quickstart sections, swap commands to
`iro …` and lead with the binary download (one line + link to
`https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest` and to the
wiki setup page). Sections about **tests, tools/build.py, tokenize, sync-wiki,
or anything under `tools/`** keep `python3` — that is dev/build territory.

- [ ] **Step 2: Verify the split**

Run: `grep -n "python3" README.md`
Expected: remaining matches are only test/build/maintainer commands (`tests/`, `tools/`) or an explicit run-from-source note.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): operator quickstart on the iro release binary"
```

---

### Task 12: Final verification, push, wiki publish

- [ ] **Step 1: Full suite + build verify**

Run: `python3 tools/run-tests.py && python3 tools/build.py`
Expected: `ALL TEST FILES PASS` + build self-verify OK.

- [ ] **Step 2: Push and watch CI**

```bash
git push
gh run list --branch main --limit 3
gh run watch <CI-run-id> --exit-status
```

Expected: success.

- [ ] **Step 3: Publish the wiki**

```bash
python3 tools/sync-wiki.py --dry-run   # review the page list
python3 tools/sync-wiki.py
```

Expected: dry-run lists the changed pages from Tasks 7–9; the real run commits and pushes to `<origin>.wiki.git`.

- [ ] **Step 4: Visual check of the live wiki**

Use the `wiki-visual-test` skill to verify the changed pages render correctly
(focus: Set-up-the-broadcast-PC `<details>` blocks + tables, Home bullet,
Build-and-maintenance release section).

---

## Self-review notes (spec coverage)

- Spec Part 1 (Discord) → Tasks 1–2. Presence paths, winget/brew ids, deb step,
  manual guide, first-run note, tests: covered.
- Spec Part 2 (release) → Tasks 3–6. Archives + `.env.example`, `.env`
  auto-create + tests, CLAUDE.md, `v0.1.0` tag + end-to-end asset smoke test: covered.
- Spec Part 3 (docs) → Tasks 7–11; wiki publish + visual check → Task 12.
- Order matches the spec's "Order of execution" (code → CI → tag → docs → publish).
