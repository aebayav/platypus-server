"""Pre-flight checks for platypus-server (the `platypus doctor` command).

Stdlib-only, so it can run before anything is installed:

    curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/doctor.py | python3 -

Installed entry points:

    platypus doctor            # as a subcommand
    platypus-doctor            # direct
    python -m doctor
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Ports the stack is expected to use, per target:
#   vps  — public server: HTTP/HTTPS for the reverse proxy + dashboard + app
#   home — LAN device: dashboard + app only (80/443 are usually blocked by
#          the ISP and not needed without a public reverse proxy)
DEFAULT_PORTS_VPS = (80, 443, 5050, 8080)
DEFAULT_PORTS_HOME = (5050, 8080)

TARGETS = ("home", "vps")


def default_ports(target: str = "home") -> tuple[int, ...]:
    """Return the default port list for the given target."""
    return DEFAULT_PORTS_VPS if target == "vps" else DEFAULT_PORTS_HOME

# Resource thresholds.
MIN_DISK_GB = 5.0
CRITICAL_DISK_GB = 1.0
MIN_RAM_GB = 1.0
CRITICAL_RAM_GB = 0.5

REQUIRED_PYTHON = (3, 10)

# Endpoints probed by the connectivity check.
NET_PROBES = (("pypi.org", 443), ("github.com", 443))

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class Result:
    """Outcome of a single pre-flight check."""

    label: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_os() -> Result:
    if sys.platform != "linux":
        return Result(
            "OS",
            WARN,
            f"{platform.system()} {platform.release()} — platypus targets Linux",
        )
    try:
        info: dict[str, str] = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                info[key] = value.strip().strip('"')
    except OSError:
        return Result("OS", OK, platform.platform())
    name = info.get("NAME", "Linux")
    version = info.get("VERSION_ID", info.get("VERSION", ""))
    return Result("OS", OK, f"{name} {version}".strip())


def check_sudo() -> Result:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return Result("sudo", OK, "running as root — no sudo needed")
    if shutil.which("sudo") is None:
        return Result(
            "sudo",
            FAIL,
            "sudo is not installed — run: apt-get install -y sudo",
        )
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return Result("sudo", FAIL, "could not run `sudo -n true`")
    if result.returncode == 0:
        return Result("sudo", OK, "passwordless sudo works")
    return Result(
        "sudo",
        FAIL,
        "sudo needs a password or is not allowed for this user — "
        "run the installer with `curl -fsSL .../bootstrap.sh | sudo bash`",
    )


def check_python() -> Result:
    current = sys.version_info[:2]
    if current >= REQUIRED_PYTHON:
        return Result(
            "Python",
            OK,
            f"{platform.python_version()} "
            f"(>= {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} required)",
        )
    return Result(
        "Python",
        FAIL,
        f"{platform.python_version()} found, but "
        f"Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ is required",
    )


def check_disk() -> Result:
    usage = shutil.disk_usage("/")
    free_gb = usage.free / 2**30
    if free_gb < CRITICAL_DISK_GB:
        status = FAIL
    elif free_gb < MIN_DISK_GB:
        status = WARN
    else:
        status = OK
    return Result(
        "Disk",
        status,
        f"/ has {free_gb:.1f} GiB free "
        f"(warn below {MIN_DISK_GB:.0f} GiB, fail below {CRITICAL_DISK_GB:.0f} GiB)",
    )


def _linux_available_ram_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                return float(parts[1]) / 1_048_576  # kB -> GiB
    except OSError:
        pass
    return None


def check_ram() -> Result:
    available_gb = _linux_available_ram_gb()
    if available_gb is not None:
        detail = f"{available_gb:.1f} GiB available"
    elif hasattr(os, "sysconf"):
        total_gb = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
        available_gb = total_gb
        detail = f"{total_gb:.1f} GiB total (available unknown on this platform)"
    else:
        return Result("RAM", WARN, "could not determine available memory")
    if available_gb < CRITICAL_RAM_GB:
        status = FAIL
    elif available_gb < MIN_RAM_GB:
        status = WARN
    else:
        status = OK
    return Result(
        "RAM",
        status,
        f"{detail} (warn below {MIN_RAM_GB:.0f} GiB, fail below {CRITICAL_RAM_GB:.1f} GiB)",
    )


def check_internet() -> Result:
    failures: list[str] = []
    for host, port in NET_PROBES:
        try:
            socket.create_connection((host, port), timeout=5).close()
        except OSError:
            failures.append(f"{host}:{port}")
    if not failures:
        return Result("Internet", OK, "download endpoints reachable")
    if len(failures) == len(NET_PROBES):
        return Result(
            "Internet",
            FAIL,
            f"cannot reach {', '.join(failures)} — package and repository "
            "downloads will fail",
        )
    return Result("Internet", WARN, f"cannot reach {', '.join(failures)}")


def check_port(port: int) -> Result:
    label = f"port {port}"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.close()
    except PermissionError:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return Result(label, FAIL, "could not bind (permission denied)")
        return Result(label, WARN, "privileged port — run doctor as root to verify")
    except OSError:
        return Result(label, FAIL, "already in use by another process")
    return Result(label, OK, "free")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_ports(raw: str) -> list[int]:
    """Parse a comma-separated port list like '80,443,5050'."""
    ports: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        port = int(part)
        if not 1 <= port <= 65535:
            raise ValueError(f"port {port} out of range (1-65535)")
        ports.append(port)
    return ports


def run_checks(ports: list[int]) -> list[Result]:
    return [
        check_os(),
        check_sudo(),
        check_python(),
        check_disk(),
        check_ram(),
        check_internet(),
        *(check_port(port) for port in ports),
    ]


def print_report(results: list[Result]) -> int:
    """Print the report and return the process exit code (0 ok, 1 failed)."""
    symbols = {OK: "[OK]   ", WARN: "[WARN] ", FAIL: "[FAIL] "}
    print("\nplatypus doctor — pre-flight checks\n")
    for result in results:
        print(f"{symbols[result.status]} {result.label:<10} {result.detail}")
    failures = sum(1 for result in results if result.failed)
    warnings = sum(1 for result in results if result.status == WARN)
    print()
    if failures:
        print(f"Result: {failures} problem(s) found — fix them before installing.")
        return 1
    if warnings:
        print(f"Result: all checks passed ({warnings} warning(s)).")
    else:
        print("Result: all checks passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Allow both `platypus doctor ...` and `platypus-doctor ...`.
    if argv and argv[0] == "doctor":
        argv = argv[1:]

    parser = argparse.ArgumentParser(
        prog="platypus doctor",
        description="Pre-flight checks for the platypus-server setup.",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default=None,
        help=(
            "server target: 'home' or 'vps' — picks the default port list "
            "(default: PLATYPUS_TARGET, then 'home')"
        ),
    )
    parser.add_argument(
        "--ports",
        metavar="PORTS",
        default=None,
        help=(
            "comma-separated TCP ports to check "
            "(default depends on the target: vps "
            f"{','.join(str(p) for p in DEFAULT_PORTS_VPS)}, home "
            f"{','.join(str(p) for p in DEFAULT_PORTS_HOME)})"
        ),
    )
    args = parser.parse_args(argv)

    target = args.target or os.environ.get("PLATYPUS_TARGET") or "home"
    ports_raw = (
        args.ports
        if args.ports is not None
        else ",".join(str(port) for port in default_ports(target))
    )

    try:
        ports = parse_ports(ports_raw)
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover — parser.error exits

    print(f"Target: {target}")
    return print_report(run_checks(ports))


if __name__ == "__main__":
    sys.exit(main())
