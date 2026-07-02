# Cloud-Producer Spike — Execution Runbook (Issue #395)

**Date:** 2026-07-02
**Status:** Runbook approved, ready to execute — this document IS the deliverable-methodology
for the #395 spike; the spike itself produces a **findings write-up** (go/no-go per stage).
**Scope:** A staged, abort-fast investigation to decide **GO / NO-GO** on moving the producer
station (relay + OBS + broadcast encode/upload) to an **on-demand cloud GPU instance** spun up
per event, so the home machine only runs the operator's own commentary stream + directing in
the browser.

> This runbook refines the plan in issue #395. It changes two things from the original issue
> and locks the provider choice — see **Decisions** below. Everything else (motivation, the
> load table, the staged abort structure) stands as written in #395.

## Decisions locked in brainstorming (2026-07-02)

1. **Headless OBS is removed entirely.** The original issue assumed a headless OBS bring-up
   (Xvfb/EGL). Rejected: too much uncertainty for almost no real value in a spike whose whole
   job is to *observe and validate*. We run OBS on a **GPU VM with a real graphical desktop**
   reached over remote access (NICE DCV / VNC / NoMachine), exactly like a local OBS. The
   desktop **replaces Xvfb** (OBS renders to the real X session), so it is *less* setup, not
   more — and every render/encode/audio check is done with eyes on the screen.
   - Headless is a *production* cost-optimization, not a spike requirement. It is **deferred
     to Post-GO follow-ups and may never be needed** — in production you start OBS and detach;
     an idle desktop session costs almost nothing on a T4.
2. **No Docker image for the spike.** Per the issue's own note, a baked image is a *Post-GO*
   investment. For the CPU IP-test (Stage 1) a container adds only friction; for the GPU/OBS
   stages Docker is actively painful (nvidia-container-toolkit + OBS + browser-source +
   PulseAudio in a container). Reproducibility across the Stage-1 providers comes from a small
   **throwaway Python bootstrap** (the "no `.sh`" rule applies only to *shipped* tooling — a
   scratch spike script is fine) or simply the copy-pasteable commands in this runbook.
   - **If GO, the image is a provider VM snapshot, not Docker** — precisely because of
     OBS/NVENC/desktop-audio.
3. **Provider selection (locked):**
   - **Stage 1 (CPU, IP-reputation test) → three deliberately different AS characters:**
     **Hetzner CX22** (EU, AS24940, budget VPS, ~€0.007/h, seconds to provision) +
     **DigitalOcean droplet** (US, AS14061, mid-tier, different reputation pool) +
     **the Stage-2 GPU provider's IP itself** (the only one that ultimately matters).
   - **Stage 2–4 (GPU, one provider) → Paperspace** (GPU **with desktop templates**,
     on-demand, least friction for a GUI-first spike). **AWS `g4dn.xlarge`** (T4, ~$0.53/h,
     NICE DCV, "production-like") is the documented alternative — **but its GPU quota needs
     days of lead time, so if we switch to AWS the quota request is step 0.**

## The coupling that the original issue under-specified

**Stage 1 must test the IP of the exact provider Stage 2+ will run on.** Otherwise we validate
the datacenter-IP feed pull on Hetzner, then build the OBS station on Paperspace — and
Paperspace's IP is the one that gets bot-blocked. The GPU provider's IP is therefore a
first-class Stage-1 test target, alongside Hetzner and DigitalOcean.

---

## Stage 0 — Prerequisites (local, ~30 min, €0)

**Cookies (headless has no interactive browser login → export locally, upload):**

1. Locally, sign in to YouTube in **Firefox** using a **dedicated throwaway Google account**
   (not your main — the cookies are a live session uploaded to a rented box; a throwaway
   account limits blast radius).
2. `racecast cookies firefox` → writes `runtime/yt-cookies.txt` (Netscape format, never
   hand-edit). Twitch only if the league uses gated feeds: `racecast cookies twitch firefox`.
3. Copy to each test box over **scp/SFTP** (encrypted):
   `scp runtime/yt-cookies.txt user@server:~/racecast/runtime/yt-cookies.txt`.
4. Use **fresh, valid** cookies so a Stage-1 failure is unambiguously **IP-based**, not
   cookie-based. Cookies expire/rotate → in production expect to **re-export fresh before each
   event**. Never commit (already gitignored).

**Throwaway league profile:** create a profile with a *real* schedule (real unlisted/live
commentator URLs) so the feed pull hits a real bot-check. `racecast profile new spike-395`.

**Compounding-risk note (record it, don't fight it yet):** cookies exported on a home IP but
used from a datacenter IP (session origin ≠ usage IP) can trip the bot-check *harder* than
either alone. Stage 1 measures the real combined behavior — that is the point.

## Stage 1 — Datacenter-IP feed pull ⚠️ THE K.-O. RISK, TEST FIRST (~30–45 min/provider, < €1 total)

**Question:** Does the relay's feed pull work from a datacenter IP, or does YouTube
throttle/block it?

Run **on each of the three Stage-1 boxes** (Hetzner, DigitalOcean, the GPU provider):

1. Install the toolchain: `racecast install-tools` (yt-dlp/streamlink/ffmpeg/deno). Ubuntu LTS.
2. **Raw probe:** `yt-dlp -g --cookies runtime/yt-cookies.txt <real unlisted/live URL>` → must
   resolve an HLS URL. Feed it to `streamlink` and confirm **bytes flow**.
3. **Relay-level:** `racecast --profile spike-395 relay run` (foreground/debug). Watch
   `feed_A/B` logs for a **stable pull with no 403/429 churn for ≥ 15 min**.
4. Repeat for a **Twitch** source (streamlink Twitch-plugin path) **if the league uses Twitch**.

**ABORT if:** feeds 403/429 or drop repeatedly from *any* datacenter IP — most critically the
GPU provider's. Then the whole cloud-feed path is dead regardless of server power → record
findings, stop, and evaluate alternatives (residential proxy, or "relay stays home, only OBS
moves to cloud") **before** spending on GPU.

**Record per provider:** pass/fail, 403/429 count over 15 min, any throttle/reconnect pattern,
resolved-URL latency. → *Stage-1 findings table* (template at the end).

## Stage 2 — OBS on a GPU desktop VM (Paperspace) (~half to full day first time, ~$3–5)

> Rewritten from the issue's "headless OBS PoC". No Xvfb, no EGL. OBS runs on a **real desktop**
> you connect to and operate normally.

1. Spin up a **Paperspace GPU VM with a desktop template** (T4). Connect via its remote desktop
   (Parsec/VNC/NoMachine, or NICE DCV on AWS).
2. `racecast install-tools` + `racecast install-apps` (OBS). **On x86-64 Linux the OBS PPA
   ships the Browser Source plugin — `racecast obs-browser` is only needed on aarch64, which we
   avoid by choosing an x86-64 GPU VM.** On a no-GPU/VM host also disable Browser-Source
   Hardware Acceleration (already documented) — verify whether it's needed on the real GPU.
3. Localize + import the scene collection: `racecast setup` → import into OBS (normal GUI).
4. **Verify with eyes on the screen:**
   - The relay-served **HUD browser source** renders in OBS.
   - **NVENC encodes 1080p60** (T4 datacenter GPU → unlimited NVENC sessions; encode + remote
     desktop coexist fine).
   - Push a short test encode to a **private/unlisted RTMP target** and confirm it arrives.
5. **Virtual audio:** confirm a **PulseAudio/PipeWire null-sink** works for any OBS audio input
   the broadcast needs. **Open question to settle here (do not assume):** is **Discord audio**
   actually in our broadcast path, or does commentary audio arrive **via the pulled feed
   itself**? If commentary rides the pulled feed (normal for commentator feeds), the virtual
   audio need shrinks dramatically. Settle this against the crew's real setup.

**ABORT if:** NVENC or the browser source can't be made reliable for a multi-hour run, or the
desktop GPU VM is unstable.

**Record:** boot-to-desktop time, OBS stability over a multi-hour idle+encode soak, NVENC
1080p60 CPU/GPU headroom, whether virtual audio was needed at all, Discord-audio answer.

## Stage 3 — Remote operation over the tailnet (~1–2 h)

1. Join the box to Tailscale (`racecast tailscale up`); reach the **Control Center** at
   `http://<vps-tailscale-ip>:8089` from the operator's laptop (**Tailscale = the auth**; the
   CC stays localhost-bound, no new auth built — `RACECAST_UI_PASSWORD` stays reserved).
2. **Direct from the laptop via `/console/panel`** (Funnel or tailnet): scene switches, source
   toggles, audio, transitions, cues, feed handover — all **relay-mediated** — and confirm they
   drive the **cloud** OBS. (The Director Panel needs no OBS IP/port/password — it works fully
   over Funnel with just the per-person token. This is already the case; Stage 3 confirms it
   end-to-end against a remote OBS.)
3. **Trust boundary:** confirm the relay control port **8088 is NOT publicly exposed** (tailnet
   only); only `/console` may be public via Funnel, as today. OBS-WebSocket is never funnelled.

**ABORT if:** the panel can't reliably drive the cloud OBS, or the trust boundary can't be kept.

**Record:** panel→cloud-OBS action reliability, any control latency, confirmation that 8088 is
tailnet-only.

## Stage 4 — Cost / latency / decision (~1–2 h, ~$1–2)

1. **Non-live dry run, end-to-end:** operator commentary (home) → YouTube → cloud relay pull →
   cloud OBS → broadcast out (unlisted target). Measure **added end-to-end latency** and confirm
   it's acceptable for the relay's ping-pong design.
2. Record **actual instance cost for a ~6 h event** and **boot-to-ready time** (Stage 2's
   boot-to-desktop + toolchain + scene import + cookie upload).
3. **Decide GO / NO-GO** using the findings tables.

---

## Duration & cost summary (verify current pricing at run time)

| Stage | What | Instance | Wall-time | Cost |
|---|---|---|---|---|
| 0 | Cookies, throwaway account, profile | local | ~30 min | €0 |
| 1 | Datacenter-IP feed pull, **×3 providers** | CPU VPS (Hetzner ~€0.007/h, DO ~$0.009/h) | ~30–45 min each → ~2–3 h | **< €1** |
| 2 | OBS on GPU desktop VM (**the real time sink**) | T4 GPU ~$0.20–0.55/h | ½–1 day first time | ~$3–5 |
| 3 | Panel drives cloud OBS over tailnet | same GPU VM | ~1–2 h | in Stage-2 cost |
| 4 | End-to-end dry run, latency, decision | same GPU VM | ~1–2 h | ~$1–2 |
| **Total spike** | | | | **< ~$15** |

**Production running cost (post-GO, for context):** T4 on-demand ~$0.20–0.55/h → a 6 h event
≈ **$2–4**; 2 events/month ≈ **~$5–10/month**, billed only while running. Bandwidth (~10 GB/h,
~60 GB/event) is a non-issue. **On-demand, never spot** for a live run (spot can be reclaimed
mid-event).

**The real cost driver is not the instance (< $15 for the whole spike) — it's engineering hours
on Stage 2.** And the whole thing can die at Stage 1 in ~1 h for < €1. That ordering is the
entire value of the staged structure: buy the cheapest information first.

## Risks & open questions

- **Datacenter IP vs. YouTube bot-check (Stage 1) — the dominant risk.** Compounded by the
  cookie session-origin ≠ usage-IP factor above.
- **Headless cookie refresh is impractical** → export locally, upload; re-upload fresh before
  each event.
- **Discord audio in the broadcast path?** — unresolved; drives the virtual-audio need. Settle
  in Stage 2.
- **Platform ToS** for relaying third-party streams from a datacenter — note and respect.

## Deliverable & Post-GO follow-ups

**Deliverable of the spike:** a findings write-up (go/no-go with evidence per stage). **No
`src/` changes are expected from the spike itself beyond documentation.**

**If GO**, follow-up issues:
1. **Bake the cloud image** — a **provider VM snapshot** (OBS + desktop + virtual audio + scene
   collection pre-imported) for "boot → event-ready in minutes". **Not Docker.**
2. **GPU-desktop + virtual-audio setup docs.**
3. **Operator runbook:** "spin up → run event → tear down."
4. *(De-prioritized / maybe never)* Headless hardening as a cost optimization — only if the
   idle-desktop cost ever proves to matter.

---

## Session log — 2026-07-02 (Stage 0 + Stage 1 core)

**Result: Stage 0 + the Stage-1 K.-o. gate PASS on GCP, for ~€0.** The dominant risk
(datacenter IP vs. YouTube bot-check) **did not fire** — see the table below.

- **amd64 software (never confirmed since pre-v1.0.0):** racecast v1.4.0 amd64 binary runs
  on Ubuntu 24.04 (glibc 2.38 ok); deno 2.8.3 installs + runs on amd64/24.04.
- **GCP datacenter IP `35.202.91.202` (us-central1) resolves YouTube via `yt-dlp -g` +
  cookies + deno for BOTH a VOD and a real LIVE stream** (`source/yt_live_broadcast`,
  `live/1`) → HLS `index.m3u8`. No 403 / no "not a bot" / no "only images". Cookies were
  exported on a home IP and used from the datacenter IP (the session-origin-mismatch factor)
  and it still worked. **This contradicts the "all cloud IPs are blocked" web-research
  assumption** — GCP + cookies + deno works. The earlier "only images" failure was purely
  **missing deno on PATH**, not the IP.
- **Provider pivots:** Hetzner = new-account ID verification (declined). Paperspace Core =
  stock templates only Ubuntu 20.04 / CentOS 7 → too old (Python 3.8, glibc 2.31); the amd64
  binary needs glibc 2.38, deno needs ≥2.35, current yt-dlp needs Python ≥3.10. Not viable.
  → GCP is the working provider.
- **Product bug found:** `racecast install-tools` runs `apt-get install` with **no preceding
  `apt-get update`** → "Unable to locate package" on a fresh cloud image. Filed as an issue.
- **GCP free-tier gotchas:** the create-instance estimator shows gross list price (never the
  free-tier credit); the default "Balanced" boot disk is not free → pick **Standard pd ≤30 GB**.

**Still open to close Stage 1 fully (next session, needs a live stream up):** the **≥15-min
sustained pull** (throttle/403-churn over time, via streamlink — the relay's real client),
an **unlisted** commentator URL (identical mechanism; unlisted is a cookie-access, not IP,
question), and the **Twitch** streamlink path.

## Findings tables (fill during the run)

### Stage 1 — Datacenter-IP feed pull
| Provider / region | ASN | Raw `yt-dlp -g` | streamlink bytes | Relay ≥15 min | 403/429 count | Twitch (if used) | Verdict |
|---|---|---|---|---|---|---|---|
| **GCP e2-micro / us-central1** | 15169 | **PASS** (VOD + LIVE) | pending (Stage-1B) | pending | 0 so far | pending | **PASS (core)** |
| Hetzner CX22 / EU | 24940 | — (ID-verify blocked signup) | | | | | n/a |
| Paperspace Core | — | — (OS templates too old: 20.04/CentOS7) | | | | | n/a |

### Stage 2 — OBS on GPU desktop VM
| Check | Result | Notes |
|---|---|---|
| Boot → desktop time | | |
| HUD browser source renders | | |
| NVENC 1080p60 headroom | | |
| Multi-hour soak stable | | |
| Virtual audio needed? | | |
| **Discord audio in broadcast path?** | | settle here |

### Stage 3 — Remote operation
| Check | Result | Notes |
|---|---|---|
| CC reachable over tailnet | | |
| `/console/panel` drives cloud OBS | | |
| Control latency | | |
| 8088 tailnet-only confirmed | | |

### Stage 4 — Cost / latency / decision
| Metric | Value |
|---|---|
| Added end-to-end latency | |
| Actual 6 h event cost | |
| Boot-to-ready time | |
| **GO / NO-GO** | |
