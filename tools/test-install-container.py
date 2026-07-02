#!/usr/bin/env python3
"""Maintainer tool: run the REAL `racecast install-tools` path inside a fresh
`ubuntu:24.04` container and assert every feed tool ends up runnable. This is the
check the e2e harness cannot do — it stubs the tools; here they are really
downloaded/installed and probed with `<tool> --version`.

Network-heavy (real apt + GitHub downloads) and needs Docker or Podman, so it is
opt-in and NOT part of CI. The command builder below is pure and unit-tested
(tests/test_install_container.py); only main() touches Docker."""
import os
import shutil
import subprocess
import sys

IMAGE = "ubuntu:24.04"


def build_container_command(engine, image, repo_dir, runtime_dir="/tmp/rc-rt"):
    """The `<engine> run` argv that installs the toolchain from source inside the
    container and asserts each tool is runnable. Pure — no Docker touched here.
    Root in the container => install-tools' apt steps take no sudo (correct: the
    base image has no sudo binary), and yt-dlp/deno land in <runtime_dir>/bin."""
    script = (
        "set -euo pipefail; "
        "apt-get update && apt-get install -y python3 curl ca-certificates; "
        f"cd /repo && python3 src/racecast.py install-tools --runtime-dir {runtime_dir}; "
        f"export PATH={runtime_dir}/bin:$PATH; "
        "yt-dlp --version && deno --version && "
        "streamlink --version && ffmpeg -version"
    )
    return [engine, "run", "--rm", "-v", f"{repo_dir}:/repo", image,
            "bash", "-lc", script]


def _pick_engine(which=shutil.which):
    for engine in ("docker", "podman"):
        if which(engine):
            return engine
    return None


def main():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    engine = _pick_engine()
    if engine is None:
        sys.exit("Needs Docker or Podman on PATH — neither found.")
    cmd = build_container_command(engine, IMAGE, repo_dir)
    print("Running:", " ".join(cmd[:6]), "...")
    rc = subprocess.call(cmd)
    if rc == 0:
        print("PASS: all tools installed and runnable in", IMAGE)
    else:
        print("FAIL: container install test exited", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
