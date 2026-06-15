"""Linux companion-pi control for the `racecast companion` adapter.

companion-pi runs Bitfocus Companion as a systemd service (user `companion`,
launched by /usr/local/src/companionpi/launch.sh, which passes no bind flag so
Companion binds 0.0.0.0). Companion 3.x headless takes the bind only as the CLI
flag `--admin-address`; config.json is ignored. To enforce the toolkit's
"never 0.0.0.0 — Tailscale IP or 127.0.0.1" rule we override the service's
ExecStart via a systemd drop-in that reads the address from an EnvironmentFile,
and set that file (per start) through a narrow root helper. enable_control()
installs the drop-in, the helper, and a visudo-validated NOPASSWD sudoers rule.

Pure logic (content builders, validation, idempotency) is unit-tested; the I/O
in enable_control() takes injected `run`/`read_text`/`write_temp` seams so the
command sequence is testable without root.

This module ships NO shell-script file — bind_helper_content() is a string
written to /usr/local/sbin at enable_control() time on the target machine.
"""
import ipaddress

UNIT = "companion"
DROPIN_DIR = "/etc/systemd/system/companion.service.d"
DROPIN_CONF = DROPIN_DIR + "/racecast-bind.conf"
BIND_ENV = DROPIN_DIR + "/racecast-bind.env"
HELPER_PATH = "/usr/local/sbin/racecast-companion-bind"
SUDOERS_PATH = "/etc/sudoers.d/racecast-companion"
SERVICE_UNIT_FILE = "/etc/systemd/system/companion.service"
LEGACY_2X_DIR = "/usr/local/src/companion"   # companion-pi 2.x layout (headless_ip.js)


def is_valid_bind_ip(ip):
    """True iff `ip` is a literal IPv4/IPv6 address (defends the helper's argv)."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def bind_env_content(ip):
    """EnvironmentFile body pinning the admin bind address. Raises on a bad ip."""
    if not is_valid_bind_ip(ip):
        raise ValueError(f"invalid bind ip: {ip!r}")
    return f"RACECAST_ADMIN_ADDRESS={ip}\n"


def bind_dropin_content():
    """systemd drop-in: reset the vendor ExecStart, relaunch with --admin-address
    from the EnvironmentFile (default 127.0.0.1). Node-path detection mirrors
    companion-pi's launch.sh."""
    return (
        "[Service]\n"
        f"EnvironmentFile=-{BIND_ENV}\n"
        "ExecStart=\n"
        "ExecStart=/bin/bash -c 'cd /opt/companion && "
        "NODE=$([ -d /opt/companion/node-runtime ] && "
        "echo /opt/companion/node-runtime/bin/node || "
        "echo /opt/companion/node-runtimes/main/bin/node); "
        "exec \"$NODE\" /opt/companion/main.js "
        "--admin-address \"${RACECAST_ADMIN_ADDRESS:-127.0.0.1}\" "
        "--extra-module-path /opt/companion-module-dev'\n"
    )


def bind_helper_content():
    """Root helper (written to HELPER_PATH): validate an IP arg, pin it in the
    EnvironmentFile, restart Companion. The single privileged action behind the
    NOPASSWD rule — it cannot do anything but set a validated bind + restart."""
    return (
        "#!/bin/bash\n"
        "# Managed by racecast (companion enable-control). Sets the Companion admin\n"
        "# bind address and restarts the service. Do not edit by hand.\n"
        "set -euo pipefail\n"
        'ip="${1:-}"\n'
        'if ! printf "%s" "$ip" | grep -Eq '
        "'^([0-9]{1,3}\\.){3}[0-9]{1,3}$|^[0-9A-Fa-f:]+$'; then\n"
        '  echo "racecast-companion-bind: invalid ip: $ip" >&2\n'
        "  exit 2\n"
        "fi\n"
        f'printf "RACECAST_ADMIN_ADDRESS=%s\\n" "$ip" > {BIND_ENV}\n'
        f"exec systemctl restart {UNIT}\n"
    )


def sudoers_dropin_content(user, systemctl_path):
    """NOPASSWD for exactly the bind helper (start path) + `systemctl stop`."""
    return (
        "# Managed by racecast (companion enable-control). Passwordless start (via\n"
        "# the bind helper) + stop of the Companion service for the operator.\n"
        f"{user} ALL=(root) NOPASSWD: {HELPER_PATH}, {systemctl_path} stop {UNIT}\n"
    )
