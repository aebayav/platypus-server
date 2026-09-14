"""System metrics collection for the dashboard."""

import os
import threading
import time
from collections import deque

import psutil

# ---------------------------------------------------------------------------
# Metrics history (ringbuffer)
# ---------------------------------------------------------------------------

_HISTORY_MAXLEN = 600  # 600 × 3 s = 30 minutes


class MetricsHistory:
    """Thread-safe ringbuffer for CPU and memory percentages."""

    def __init__(self, maxlen: int = _HISTORY_MAXLEN) -> None:
        self._lock = threading.Lock()
        self._cpu: deque[float] = deque(maxlen=maxlen)
        self._mem: deque[float] = deque(maxlen=maxlen)
        self._ts: deque[float] = deque(maxlen=maxlen)

    def record(self, cpu_percent: float, mem_percent: float) -> None:
        with self._lock:
            self._cpu.append(cpu_percent)
            self._mem.append(mem_percent)
            self._ts.append(time.time())

    def snapshot(self, points: int = 200) -> dict:
        with self._lock:
            ts = list(self._ts)[-points:]
            cpu = list(self._cpu)[-points:]
            mem = list(self._mem)[-points:]
        return {"timestamps": ts, "cpu": cpu, "memory": mem}


#: Global history instance — populated by the background recorder in app.py.
history = MetricsHistory()



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
    net: dict = {}
    try:
        nio = psutil.net_io_counters()
        net = {
            "bytes_sent": nio.bytes_sent,
            "bytes_recv": nio.bytes_recv,
            "packets_sent": nio.packets_sent,
            "packets_recv": nio.packets_recv,
        }
    except Exception:  # noqa: BLE001
        pass
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
        "network": net,
    }


def get_processes(limit: int = 20) -> list[dict]:
    """Return the top *limit* processes sorted by CPU usage."""
    procs: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            info = p.info
            procs.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "cpu_percent": round(info["cpu_percent"] or 0.0, 1),
                    "memory_percent": round(info["memory_percent"] or 0.0, 1),
                    "status": info["status"] or "",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda p: p["cpu_percent"], reverse=True)
    return procs[:limit]

