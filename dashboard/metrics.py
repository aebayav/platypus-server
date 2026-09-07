"""System metrics collection for the dashboard."""

import os
import time

import psutil


def _temperatures() -> dict[str, float]:
    """Read temperatures via psutil, falling back to /sys/class/thermal."""
    temps: dict[str, float] = {}
    try:
        sensors = psutil.sensors_temperatures()
        if sensors:
            for name, entries in sensors.items():
                for entry in entries:
                    if entry.current is not None:
                        key = f"{name} {entry.label}".strip()
                        temps[key or name] = round(entry.current, 1)
    except Exception:
        pass

    if not temps:
        base = "/sys/class/thermal"
        try:
            for zone in sorted(os.listdir(base)):
                if not zone.startswith("thermal_zone"):
                    continue
                with open(os.path.join(base, zone, "temp"), encoding="utf-8") as fh:
                    millis = int(fh.read().strip())
                temps[zone] = round(millis / 1000.0, 1)
        except Exception:
            pass
    return temps


def get_metrics() -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    try:
        load = [round(x, 2) for x in psutil.getloadavg()]
    except (AttributeError, OSError):
        load = None
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "cpu_count": psutil.cpu_count(),
        "load_avg": load,
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "temperatures": _temperatures(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
    }
