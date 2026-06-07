#!/usr/bin/env python3
"""Stdlib checks for the Control Center job manager.
Run: python3 tests/test_ui_jobs.py"""
import io, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "ui"))
import ui_jobs


class FakeProc:
    """Minimal Popen stand-in: canned stdout, fixed exit code."""
    def __init__(self, out=b"line1\nline2\n", code=0):
        self.stdout = io.BytesIO(out)
        self._code = code
        self.returncode = None
    def wait(self):
        self.returncode = self._code
        return self._code


def _wait_done(jm, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = jm.snapshot(job_id)
        if snap and snap["exit_code"] is not None:
            return snap
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def t_start_collects_lines_and_exit():
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: FakeProc())
    job_id, err = jm.start("echo", ["x"])
    assert err is None and job_id
    snap = _wait_done(jm, job_id)
    assert snap["op"] == "echo" and snap["exit_code"] == 0
    lines, nxt, code = jm.lines_since(job_id, 0)
    assert lines == ["line1", "line2"] and nxt == 2 and code == 0


def t_lines_since_resumes_at_index():
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: FakeProc())
    job_id, _ = jm.start("echo", [])
    _wait_done(jm, job_id)
    lines, nxt, _ = jm.lines_since(job_id, 1)
    assert lines == ["line2"] and nxt == 2
    lines, nxt, _ = jm.lines_since(job_id, 2)
    assert lines == [] and nxt == 2


def t_duplicate_op_refused_while_running():
    class NeverEnds(FakeProc):
        def __init__(self):
            super().__init__()
            self.stdout = io.BufferedReader(io.BytesIO(b""))  # immediate EOF...
        def wait(self):
            time.sleep(0.3)                                    # ...but slow exit
            self.returncode = 0
            return 0
    jm = ui_jobs.JobManager(lambda a: ["ignored"], spawn=lambda argv: NeverEnds())
    job_id, err = jm.start("slow", [])
    assert err is None
    _id2, err2 = jm.start("slow", [])
    assert _id2 is None and "already running" in err2
    _wait_done(jm, job_id)
    job_id3, err3 = jm.start("slow", [])      # finished -> may run again
    assert err3 is None and job_id3 != job_id


def t_trim_keeps_since_semantics():
    out = b"".join(b"l%d\n" % i for i in range(10))
    jm = ui_jobs.JobManager(lambda a: ["ignored"],
                            spawn=lambda argv: FakeProc(out=out), max_lines=4)
    job_id, _ = jm.start("big", [])
    _wait_done(jm, job_id)
    lines, nxt, _ = jm.lines_since(job_id, 0)
    assert lines == ["l6", "l7", "l8", "l9"] and nxt == 10   # head trimmed, indices stable


def t_unknown_job_id():
    jm = ui_jobs.JobManager(lambda a: ["ignored"])
    assert jm.snapshot("nope") is None
    assert jm.lines_since("nope", 0) == (None, 0, None)


def t_real_subprocess_lifecycle():
    code = "print('hello'); import sys; sys.exit(3)"
    jm = ui_jobs.JobManager(lambda a: [sys.executable, "-c", code])
    job_id, err = jm.start("real", ["unused"])
    assert err is None
    snap = _wait_done(jm, job_id, timeout=15)
    assert snap["exit_code"] == 3
    lines, _, _ = jm.lines_since(job_id, 0)
    assert lines == ["hello"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
