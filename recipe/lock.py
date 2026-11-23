"""Atomic transition lock.

A single ``transition.lock`` file under ``/opt/platypus`` guards role
switches. Acquisition uses ``O_CREAT | O_EXCL`` so two concurrent
switches can never both win. A lock left behind by a crashed process is
detected (dead PID or over-age timestamp) and recovered automatically;
a lock held by a live process is refused with a recovery hint.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .model import PLATYPUS_DIR

LOCK_PATH: Path = PLATYPUS_DIR / "transition.lock"
LOCK_STALE_SECONDS: int = 3600


class LockError(Exception):
    """A live transition lock is held by another process."""


def _pid_alive(pid: int) -> bool:
    """Return True when *pid* names a running process."""
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # exists, we just cannot signal it
    except OSError:
        return False
    return True


def _lock_age_seconds(info: dict) -> float:
    started = info.get("started_at")
    if not isinstance(started, str):
        return float(LOCK_STALE_SECONDS + 1)  # unreadable age: treat as stale
    try:
        started_dt = datetime.fromisoformat(started)
    except ValueError:
        return float(LOCK_STALE_SECONDS + 1)
    if started_dt.tzinfo is None:
        started_dt = started_dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started_dt).total_seconds()


def read() -> dict | None:
    """Return the parsed lock dict, or None when absent/malformed."""
    try:
        raw = LOCK_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        info = json.loads(raw)
    except ValueError:
        return None
    return info if isinstance(info, dict) else None


def _open_exclusive() -> None:
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)


def acquire(target: str, force: bool = False) -> dict:
    """Atomically acquire the transition lock for *target*.

    Raises LockError when a live, fresh lock is held by another process.
    A stale lock (dead holder PID or age over LOCK_STALE_SECONDS) is
    recovered; ``force=True`` steals any lock.
    """
    info = {
        "pid": os.getpid(),
        "target": target,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _open_exclusive()
    except FileExistsError:
        existing = read()
        if existing is None:
            # Unreadable lock file: nothing to negotiate with.
            raise LockError(
                f"transition lock exists but is unreadable: {LOCK_PATH}. "
                "If no switch is running, remove the file or pass --force-unlock."
            )
        pid = existing.get("pid")
        stale = (
            not isinstance(pid, int)
            or not _pid_alive(pid)
            or _lock_age_seconds(existing) > LOCK_STALE_SECONDS
        )
        if not force and not stale:
            raise LockError(
                f"a transition to {existing.get('target')!r} is already in "
                f"progress (PID {pid}). If that process is stuck, re-run with "
                "--force-unlock."
            )
        LOCK_PATH.unlink(missing_ok=True)
        _open_exclusive()
        info["stole_from"] = pid

    LOCK_PATH.write_text(json.dumps(info) + "\n", encoding="utf-8")
    return info


def release() -> None:
    """Release the lock; missing file is fine (idempotent)."""
    LOCK_PATH.unlink(missing_ok=True)
