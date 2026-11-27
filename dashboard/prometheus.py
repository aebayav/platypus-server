"""Prometheus text exposition format (0.0.4) exporter for Platypus metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import recipe_state


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_prometheus_metrics(
    snapshot: dict[str, Any],
    uptime_seconds: float,
    platypus_dir: Path,
) -> str:
    """Format system, service, module, and backup telemetry as Prometheus text."""
    m = snapshot.get("metrics") or {}
    cpu = float(m.get("cpu_percent", 0.0))
    mem = float((m.get("memory") or {}).get("percent", 0.0))
    disk = float((m.get("disk") or {}).get("percent", 0.0))
    services = snapshot.get("services") or []

    rstate = recipe_state.read(
        platypus_dir / "state.yml",
        platypus_dir / "roles",
    )
    mounted = rstate.get("mounted") or []
    dormant = rstate.get("dormant") or []

    last_backup_ts = 0.0
    marker = platypus_dir / "last_backup.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            last_backup_ts = float(data.get("timestamp", 0.0))
        except (OSError, ValueError, TypeError):
            last_backup_ts = 0.0

    lines: list[str] = [
        "# HELP platypus_cpu_percent Host CPU utilization percentage.",
        "# TYPE platypus_cpu_percent gauge",
        f"platypus_cpu_percent {cpu}",
        "# HELP platypus_memory_percent Host memory utilization percentage.",
        "# TYPE platypus_memory_percent gauge",
        f"platypus_memory_percent {mem}",
        "# HELP platypus_disk_percent Root filesystem utilization percentage.",
        "# TYPE platypus_disk_percent gauge",
        f"platypus_disk_percent {disk}",
        "# HELP platypus_uptime_seconds Dashboard process uptime in seconds.",
        "# TYPE platypus_uptime_seconds gauge",
        f"platypus_uptime_seconds {round(uptime_seconds, 1)}",
        "# HELP platypus_mounted_modules_total Number of currently mounted Platypus modules.",
        "# TYPE platypus_mounted_modules_total gauge",
        f"platypus_mounted_modules_total {len(mounted)}",
        "# HELP platypus_module_mounted Module state (1 = mounted, 0 = dormant).",
        "# TYPE platypus_module_mounted gauge",
    ]

    for mod in mounted:
        lbl = _escape_label(str(mod.get("name", "")))
        lines.append(f'platypus_module_mounted{{module="{lbl}"}} 1')
    for mod in dormant:
        lbl = _escape_label(str(mod.get("name", "")))
        lines.append(f'platypus_module_mounted{{module="{lbl}"}} 0')

    lines.extend(
        [
            "# HELP platypus_service_up Monitored HTTP/TCP service status (1 = up, 0 = down).",
            "# TYPE platypus_service_up gauge",
        ]
    )
    for svc in services:
        lbl = _escape_label(str(svc.get("name", "")))
        val = 1 if svc.get("status") == "up" else 0
        lines.append(f'platypus_service_up{{service="{lbl}"}} {val}')

    lines.extend(
        [
            "# HELP platypus_last_backup_timestamp_seconds Unix timestamp of last completed backup.",
            "# TYPE platypus_last_backup_timestamp_seconds gauge",
            f"platypus_last_backup_timestamp_seconds {last_backup_ts}",
            "",
        ]
    )
    return "\n".join(lines)
