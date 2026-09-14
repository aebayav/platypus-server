"""Systemd service management via systemctl."""
from __future__ import annotations

import subprocess


class SystemdError(RuntimeError):
    """Raised when a systemctl command fails."""


def _run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemdError("systemctl timed out") from exc
    except FileNotFoundError as exc:
        raise SystemdError("systemctl not found") from exc


def get_service_status(unit: str) -> dict:
    """Return structured status for a systemd unit."""
    result = _run([
        "show", unit,
        "--property=ActiveState,SubState,LoadState,UnitFileState,Description",
    ])
    props: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    active = props.get("ActiveState", "unknown")
    return {
        "unit": unit,
        "active": active,
        "sub_state": props.get("SubState", ""),
        "load": props.get("LoadState", ""),
        "enabled": props.get("UnitFileState", ""),
        "description": props.get("Description", unit),
        "running": active == "active",
    }


def service_action(unit: str, action: str) -> None:
    """Start, stop, or restart a systemd unit.

    Tries ``sudo -n systemctl`` first (passwordless sudo), then plain
    ``systemctl`` for root processes.
    """
    allowed = {"start", "stop", "restart"}
    if action not in allowed:
        raise SystemdError(f"Unknown action: {action}")
    last_result = None
    for cmd in (
        ["sudo", "-n", "systemctl", action, unit],
        ["systemctl", action, unit],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return
            last_result = result
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    detail = ""
    if last_result is not None:
        detail = (last_result.stderr or last_result.stdout or "").strip()
    raise SystemdError(detail or f"systemctl {action} {unit} failed")
