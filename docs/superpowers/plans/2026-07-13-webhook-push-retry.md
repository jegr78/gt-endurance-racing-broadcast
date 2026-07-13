# Webhook Push Retry (#490) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb a single transient sheet-webhook failure with bounded retry + backoff, so a blip during a feed switch no longer instantly raises "SHEET SYNC FAILED".

**Architecture:** One shared `push_webhook_retrying` helper (bounded backoff+jitter, wall-clock budget, lower per-attempt timeout) that both `TimerStore._push` and `SetupControl._push` route through; a pure `webhook_error_permanent` predicate keeps the permanent "script outdated" error from being retried. Seams (`post`/`sleep`/`rand`/`now`) make the loop deterministic in tests.

**Tech Stack:** Python 3 stdlib only. Tests are runnable scripts (no pytest) under `tests/`, loaded via `importlib` as `m`; existing webhook tests seam by monkeypatching the module global `m.post_webhook`.

## Global Constraints

- **Edit only under `src/`** (`dist/`/`runtime/` generated). Tests under `tests/`.
- **English only** in code/comments/log lines/docs.
- **Python stdlib only** — `random` is NOT yet imported in `racecast-feeds.py`; add `import random` (Task 2).
- **The helper must resolve `post_webhook` at CALL time** (`post = post or post_webhook`), NOT capture it as a default argument — the existing tests monkeypatch `m.post_webhook` and `_push` must pick up the patched global. Same call-time pattern for `sleep`/`rand`/`now`.
- **Control-plane only** — no change to the live feeds or the schedule read. No caller signature changes; each `_push` caller's sync/async nature is unchanged.
- **Retry policy:** retry a network exception AND a transient "did not confirm" body; NEVER retry the permanent "script outdated" error (surface it immediately). `push_status="failed"` (banner) only after retries/budget are exhausted.
- After a relay change run `python3 tests/test_timer.py` + `python3 tests/test_setup.py`; before finishing run `python3 tools/run-tests.py` + `python3 tools/lint.py`.
- No secrets/machine-paths/real-IPs in tests.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Spec: `docs/superpowers/specs/2026-07-13-webhook-push-retry-design.md`. Issue #490.

---

### Task 1: `webhook_error_permanent` predicate + `push_webhook_retrying` helper

**Files:**
- Modify: `src/relay/racecast-feeds.py` — extract the outdated-script message to a constant, reference it in `check_webhook_response` (~line 1550), add `webhook_error_permanent` + `push_webhook_retrying` + retry constants right after `check_webhook_response` (~line 1553).
- Test: `tests/test_setup.py` (it already loads the module as `m` and has the `post_webhook` seam pattern).

**Interfaces:**
- Consumes: existing `post_webhook(url, payload, timeout=10)`, `check_webhook_response(body, expected_action=None) -> (ok, err)`.
- Produces:
  - `WEBHOOK_OUTDATED_ERROR` (str constant); `WEBHOOK_RETRY_ATTEMPTS=3`, `WEBHOOK_RETRY_BASE_S=0.5`, `WEBHOOK_RETRY_BUDGET_S=10.0`, `WEBHOOK_RETRY_TIMEOUT_S=5`.
  - `webhook_error_permanent(err) -> bool`.
  - `push_webhook_retrying(url, payload, expected_action=None, *, post=None, sleep=None, rand=None, now=None, attempts=…, base_delay=…, budget_s=…, timeout=…) -> (ok: bool, err: str|None, body: bytes|None)` — `err` is UNPREFIXED (no `"push: "`), so each caller applies its own prefix as today.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup.py` (auto-discovered `t_*`; module `m`):

```python
def t_webhook_error_permanent_predicate():
    assert m.webhook_error_permanent(m.WEBHOOK_OUTDATED_ERROR) is True
    assert m.webhook_error_permanent("webhook did not confirm: 'oops'") is False
    assert m.webhook_error_permanent(None) is False


def t_push_retry_succeeds_after_transient():
    # Two transient failures (a raise, then a 'did not confirm' body), then ok.
    calls = []
    ok_body = b'{"ok": true, "action": "setup"}'
    seq = [Exception("timeout"), b'{"ok": false}', ok_body]
    def fake_post(url, payload, timeout=10):
        calls.append(timeout)
        v = seq[len(calls) - 1]
        if isinstance(v, Exception):
            raise v
        return v
    ok, err, body = m.push_webhook_retrying(
        "http://push", {"action": "setup"}, "setup",
        post=fake_post, sleep=lambda d: None, rand=lambda: 0.0, now=lambda: 0.0)
    assert ok is True and err is None and body == ok_body
    assert len(calls) == 3
    assert calls[0] == m.WEBHOOK_RETRY_TIMEOUT_S    # lower per-attempt timeout used


def t_push_retry_exhausts_then_fails():
    def fake_post(url, payload, timeout=10):
        raise OSError("egress congested")
    slept = []
    ok, err, body = m.push_webhook_retrying(
        "http://push", {"a": 1}, None,
        post=fake_post, sleep=lambda d: slept.append(d), rand=lambda: 0.0, now=lambda: 0.0)
    assert ok is False and body is None
    assert "OSError" in err and "push:" not in err   # UNPREFIXED
    assert slept == [0.5, 1.0]                        # base*2^n, 2 sleeps for 3 attempts


def t_push_retry_permanent_error_not_retried():
    calls = []
    def fake_post(url, payload, timeout=10):
        calls.append(1)
        return b'{"ok": true}'                        # ok:true but NO action echo
    ok, err, _ = m.push_webhook_retrying(
        "http://push", {"action": "setup"}, "setup",
        post=fake_post, sleep=lambda d: None, rand=lambda: 0.0, now=lambda: 0.0)
    assert ok is False
    assert err == m.WEBHOOK_OUTDATED_ERROR
    assert len(calls) == 1                            # permanent -> no retry


def t_push_retry_budget_cap_stops_early():
    calls = []
    def fake_post(url, payload, timeout=10):
        calls.append(1)
        raise OSError("slow")
    # now() jumps past the budget after the first attempt -> no 2nd attempt.
    ticks = iter([0.0, 999.0, 999.0, 999.0])
    ok, err, _ = m.push_webhook_retrying(
        "http://push", {"a": 1}, None, attempts=3,
        post=fake_post, sleep=lambda d: None, rand=lambda: 0.0, now=lambda: next(ticks))
    assert ok is False
    assert len(calls) == 1                            # budget cap stopped further attempts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_setup.py`
Expected: FAIL — `AttributeError: module '…' has no attribute 'webhook_error_permanent'`.

- [ ] **Step 3: Write minimal implementation**

In `src/relay/racecast-feeds.py`, add the constant BEFORE `check_webhook_response` (~line 1537):

```python
WEBHOOK_OUTDATED_ERROR = ("webhook script outdated (no action echo) — redeploy "
                          "the v2 script (wiki: Sheet-Webhook)")
```

In `check_webhook_response`, replace the inline outdated message with the constant:

```python
    if expected_action and d.get("action") != expected_action:
        return False, WEBHOOK_OUTDATED_ERROR
```

Add, right after `check_webhook_response` (~line 1553):

```python
WEBHOOK_RETRY_ATTEMPTS = 3
WEBHOOK_RETRY_BASE_S = 0.5
WEBHOOK_RETRY_BUDGET_S = 10.0
WEBHOOK_RETRY_TIMEOUT_S = 5   # per-attempt; lower than the direct 10 s so a hung try fails fast


def webhook_error_permanent(err):
    """True iff *err* is the permanent 'script outdated' config error (never retry).
    Any other non-ok error (a transient 'did not confirm') is retryable. Pure."""
    return err == WEBHOOK_OUTDATED_ERROR


def push_webhook_retrying(url, payload, expected_action=None, *,
                          post=None, sleep=None, rand=None, now=None,
                          attempts=WEBHOOK_RETRY_ATTEMPTS,
                          base_delay=WEBHOOK_RETRY_BASE_S,
                          budget_s=WEBHOOK_RETRY_BUDGET_S,
                          timeout=WEBHOOK_RETRY_TIMEOUT_S):
    """POST with bounded backoff+jitter until the Apps Script confirms {"ok":true},
    a PERMANENT error is hit, or attempts/budget are exhausted. Returns
    (ok, err, body); *err* is UNPREFIXED (caller adds its own 'push:' prefix as
    today). Retries a network exception and a transient 'did not confirm' body; a
    permanent 'script outdated' error is returned immediately. `post`/`sleep`/`rand`/
    `now` resolve at CALL time (default the module globals) so the existing
    m.post_webhook monkeypatch seam keeps working; injectable for deterministic
    tests."""
    post = post or post_webhook
    sleep = sleep or time.sleep
    rand = rand or random.random
    now = now or time.monotonic
    start = now()
    err = "not attempted"
    body = None
    for i in range(max(1, attempts)):
        if i > 0 and (now() - start) >= budget_s:
            break
        try:
            body = post(url, payload, timeout=timeout)
        except Exception as e:            # noqa: BLE001 — network/timeout is retryable
            err = f"{type(e).__name__}: {e}"
            body = None
        else:
            ok, cerr = check_webhook_response(body, expected_action)
            if ok:
                return True, None, body
            err = cerr
            if webhook_error_permanent(cerr):
                return False, err, body      # permanent config error -> no retry
        if i + 1 >= attempts:
            break
        delay = base_delay * (2 ** i) + rand() * base_delay
        if (now() - start) + delay >= budget_s:
            break
        sleep(delay)
    return False, err, body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_setup.py`
Expected: PASS (all `t_*`).

- [ ] **Step 5: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_setup.py
git commit -m "feat(relay): push_webhook_retrying helper + permanent-error predicate (#490)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire both `_push` paths through the helper + full suite + lint

**Files:**
- Modify: `src/relay/racecast-feeds.py` — add `import random` (top, with the other stdlib imports); rewrite `TimerStore._push` (~line 1801) and `SetupControl._push` (~line 4617) to call `push_webhook_retrying`.
- Test: `tests/test_timer.py`, `tests/test_setup.py` — update the failing-push tests to set a zero backoff so they stay fast (the retry now makes multiple `post` calls).

**Interfaces:**
- Consumes: `push_webhook_retrying(...)` (Task 1). No public signature changes to `_push`.

- [ ] **Step 1: Add `import random`**

At the top of `src/relay/racecast-feeds.py`, add `import random` alongside the existing stdlib imports (e.g. right after `import os` / near `import time`). Run `python3 -c "import ast,sys; ast.parse(open('src/relay/racecast-feeds.py').read()); print('ok')"` → `ok`.

- [ ] **Step 2: Rewrite `TimerStore._push`**

Replace the body of `TimerStore._push` (the `try/except` + `check_webhook_response` block) with:

```python
    def _push(self, payload):
        """Success = the Apps Script's own {"ok": true} (see check_webhook_response).
        Retries a transient failure with bounded backoff (#490); timer pushes carry
        no expected_action (a v1 script keeps working)."""
        ok, err, _body = push_webhook_retrying(self.push_url, payload)
        if ok:
            self.push_status = "ok"  # diagnostics: single ref assignments, no lock needed
        else:
            self.push_status = "failed"
            self.last_error = f"push: {err}"
```

- [ ] **Step 3: Rewrite `SetupControl._push`**

Replace the body of `SetupControl._push`:

```python
    def _push(self, payload, expected_action):
        ok, err, _body = push_webhook_retrying(self.push_url, payload, expected_action)
        # diagnostics: single ref assignments, no lock needed
        self.push_status = "ok" if ok else "failed"
        self.last_error = None if ok else err
        return ok, err
```

- [ ] **Step 4: Keep the failing-push tests fast (they now retry)**

The retry makes a FAILING post run `WEBHOOK_RETRY_ATTEMPTS` times with real backoff sleeps. In each existing test that monkeypatches `m.post_webhook` to raise or return a non-ok body and asserts `push_status == "failed"`, set the backoff to zero so it stays fast. Known tests: `tests/test_timer.py::t_timerstore_push_payload_and_status` (the `fail` branch) and `t_timerstore_push_unconfirmed_is_failed`; plus any equivalent failing-push test in `tests/test_setup.py`. At the top of each such test add (restoring in the existing `finally`, or add one):

```python
    _base, m.WEBHOOK_RETRY_BASE_S = m.WEBHOOK_RETRY_BASE_S, 0.0
    try:
        ... existing test body ...
    finally:
        m.WEBHOOK_RETRY_BASE_S = _base
```

If any such test asserts the number of `post` calls, update the expected count to `m.WEBHOOK_RETRY_ATTEMPTS` (a raising/unconfirmed post is retried). The OK-path tests (post returns a confirmed body on the first call) need NO change — no retry, no sleep.

- [ ] **Step 5: Run the covering test files**

Run: `python3 tests/test_timer.py`  → ALL PASS
Run: `python3 tests/test_setup.py`  → ALL PASS

- [ ] **Step 6: Full suite + lint**

Run: `python3 tools/run-tests.py`
Expected: all test files pass (exit 0).
Run: `python3 tools/lint.py`
Expected: `All checks passed`.

- [ ] **Step 7: Commit**

```bash
git add src/relay/racecast-feeds.py tests/test_timer.py tests/test_setup.py
git commit -m "feat(relay): route TimerStore/SetupControl pushes through the retry helper (#490)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §1 shared retry helper (bounded backoff+jitter, budget, permanent-vs-transient) → Task 1 (`push_webhook_retrying`).
- §2 permanent-error predicate + shared constant → Task 1 (`webhook_error_permanent`, `WEBHOOK_OUTDATED_ERROR`, referenced by `check_webhook_response`).
- §3 both `_push` paths wired; `push_status="failed"` only after exhaustion → Task 2.
- §3 lower per-attempt timeout → `WEBHOOK_RETRY_TIMEOUT_S=5` (Task 1), asserted in `t_push_retry_succeeds_after_transient`.
- §4 latency trade-off → bounded by `budget_s` + the budget-cap loop check (Task 1), tested in `t_push_retry_budget_cap_stops_early`.
- Testing §: predicate, transient-then-ok, exhausted, permanent-no-retry, budget cap, backoff schedule → Task 1; caller wiring + fast failing-path tests → Task 2.
- Out of scope (egress decoupling) → not built; noted.

**Placeholder scan:** none. Task 2 Step 4 names the known affected tests and the exact wrap to apply; "any equivalent in test_setup" is a locate-and-apply of the same concrete pattern, not a logic placeholder.

**Type consistency:** `push_webhook_retrying(...) -> (ok, err, body)` with UNPREFIXED `err` used consistently — `TimerStore._push` applies `f"push: {err}"`, `SetupControl._push` uses `err` raw (matching each caller's pre-existing `last_error` format). `webhook_error_permanent(err) -> bool`. Constants `WEBHOOK_RETRY_*` referenced by name in both the helper defaults and the tests.
