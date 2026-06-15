#!/usr/bin/env python3
"""Stdlib unit checks for the Linux companion-pi control helpers.
Run: python3 tests/test_companion_linux.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import companion_linux as cl


# --- is_valid_bind_ip --------------------------------------------------------
def t_valid_ipv4():
    assert cl.is_valid_bind_ip("100.64.10.20") is True
    assert cl.is_valid_bind_ip("127.0.0.1") is True
    assert cl.is_valid_bind_ip("0.0.0.0") is True   # explicit operator override is allowed


def t_valid_ipv6():
    assert cl.is_valid_bind_ip("::1") is True


def t_invalid_ip_rejected():
    assert cl.is_valid_bind_ip("not-an-ip") is False
    assert cl.is_valid_bind_ip("100.64.10.20; rm -rf /") is False
    assert cl.is_valid_bind_ip("") is False


# --- bind_env_content --------------------------------------------------------
def t_bind_env_content_writes_var():
    assert cl.bind_env_content("100.64.10.20") == "RACECAST_ADMIN_ADDRESS=100.64.10.20\n"


def t_bind_env_content_rejects_bad_ip():
    raised = False
    try:
        cl.bind_env_content("$(reboot)")
    except ValueError:
        raised = True
    assert raised


# --- bind_dropin_content -----------------------------------------------------
def t_dropin_resets_and_sets_execstart_with_admin_address():
    c = cl.bind_dropin_content()
    assert "[Service]\n" in c
    assert f"EnvironmentFile=-{cl.BIND_ENV}\n" in c
    assert "ExecStart=\n" in c                       # reset the vendor ExecStart first
    assert "--admin-address \"${RACECAST_ADMIN_ADDRESS:-127.0.0.1}\"" in c
    assert "/opt/companion/main.js" in c
    assert "--extra-module-path /opt/companion-module-dev" in c


# --- sudoers_dropin_content --------------------------------------------------
def t_sudoers_content_narrow_nopasswd():
    c = cl.sudoers_dropin_content("jegr", "/usr/bin/systemctl")
    assert c.endswith(
        "jegr ALL=(root) NOPASSWD: /usr/local/sbin/racecast-companion-bind, "
        "/usr/bin/systemctl stop companion\n")


# --- bind_helper_content -----------------------------------------------------
def t_helper_validates_and_restarts():
    c = cl.bind_helper_content()
    assert c.startswith("#!/bin/bash\n")
    assert "systemctl restart companion" in c
    assert cl.BIND_ENV in c
    assert "exit 2" in c                             # rejects a bad ip argument
    assert "set -euo pipefail" in c
    assert "grep -Eq" in c


def t_helper_ipv6_branch_requires_colon():
    # The bash IPv6 alternative must require at least one ':' so colon-less hex
    # (e.g. "deadbeef") is rejected, matching the Python ipaddress check.
    c = cl.bind_helper_content()
    assert "[0-9A-Fa-f:]+$" not in c        # the loose pattern must be gone
    assert ":[0-9A-Fa-f:]" in c             # a colon is now required in the IPv6 branch


# --- control_commands --------------------------------------------------------
def t_control_commands_shape():
    c = cl.control_commands("companion")
    assert c["start"] == ["sudo", "-n", cl.HELPER_PATH]      # caller appends the ip
    assert c["quit"] == ["sudo", "-n", "systemctl", "stop", "companion"]
    assert c["running"] == ["systemctl", "is-active", "companion"]


# --- detect_unit -------------------------------------------------------------
def t_detect_unit_none_on_windows_or_macos():
    assert cl.detect_unit(platform="win32") is None
    assert cl.detect_unit(platform="darwin") is None


def t_detect_unit_none_without_systemctl():
    assert cl.detect_unit(platform="linux", which=lambda n: None) is None


def t_detect_unit_via_systemctl_cat():
    class P:
        returncode = 0
    got = cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                         run=lambda *a, **k: P(), exists=lambda p: False)
    assert got == "companion"


def t_detect_unit_via_unit_file_when_cat_fails():
    class P:
        returncode = 1
    got = cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                         run=lambda *a, **k: P(),
                         exists=lambda p: p == cl.SERVICE_UNIT_FILE)
    assert got == "companion"


def t_detect_unit_none_when_absent():
    class P:
        returncode = 1
    assert cl.detect_unit(platform="linux", which=lambda n: "/usr/bin/" + n,
                          run=lambda *a, **k: P(), exists=lambda p: False) is None


# --- is_enabled (idempotency) ------------------------------------------------
def _reader_for(files):
    return lambda path: files.get(path)


def t_is_enabled_true_when_all_match():
    files = {
        cl.DROPIN_CONF: cl.bind_dropin_content(),
        cl.HELPER_PATH: cl.bind_helper_content(),
        cl.SUDOERS_PATH: cl.sudoers_dropin_content("jegr", "/usr/bin/systemctl"),
    }
    assert cl.is_enabled(_reader_for(files), "jegr", "/usr/bin/systemctl") is True


def t_is_enabled_false_when_missing():
    assert cl.is_enabled(_reader_for({}), "jegr", "/usr/bin/systemctl") is False


def t_is_enabled_false_when_sudoers_user_differs():
    files = {
        cl.DROPIN_CONF: cl.bind_dropin_content(),
        cl.HELPER_PATH: cl.bind_helper_content(),
        cl.SUDOERS_PATH: cl.sudoers_dropin_content("other", "/usr/bin/systemctl"),
    }
    assert cl.is_enabled(_reader_for(files), "jegr", "/usr/bin/systemctl") is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
