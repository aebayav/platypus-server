"""Atomic transition lock.

A single ``transition.lock`` file under ``/opt/platypus`` guards role
switches. Acquisition uses ``O_CREAT | O_EXCL`` so two concurrent
switches can never both win. A lock left behind by a crashed process is
recovered automatically — but only when the holder PID is dead: age
alone never steals from a live process, because a legitimately slow
transition (an hour-long image pull on home broadband) must not be
interrupted by an ordinary second switch. ``--force-unlock`` overrides
anything, including unreadable crash-window leftovers.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .model import PLATYPUS_DIR

LOCK_PATH: Path = PLATYPUS_DIR / "transition.lock"
LOCK_STALE_SECONDS: int = 3600  # reported in messages; never auto-steals
LOCK_REREAD_SECONDS: float = 0.2  # crash-window re-read pause
_ACQUIRE_ATTEMPTS: int = 5


class LockError(Exception):
    """The transition lock cannot be acquired."""


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
        return float(LOCK_STALE_SECONDS + 1)  # unreadable age: treat as old
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


def _write_locked_file(info: dict) -> None:
    """Create the lock file exclusively and write the JSON through the
    already-open descriptor — the empty-file crash window is minimized
    to the interval between open and write."""
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, (json.dumps(info) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def acquire(target: str, force: bool = False) -> dict:
    """Atomically acquire the transition lock for *target*.

    Raises LockError when a live lock is held by another process, when
    the lock is unreadable (crash window) without ``force``, or when a
    racing process keeps winning the acquisition. A lock whose holder
    PID is dead is recovered automatically; ``force=True`` steals any
    lock, including unreadable ones.
    """
    info: dict = {
        "pid": os.getpid(),
        "target": target,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    stolen = False

    # A truly fresh server may not have /opt/platypus yet — the first
    # lock acquisition creates it rather than failing with ENOENT.
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LockError(
            f"cannot create the lock directory {LOCK_PATH.parent}: {exc}. "
            "Check permissions on /opt/platypus."
        ) from exc

    for _ in range(_ACQUIRE_ATTEMPTS):
        try:
            _write_locked_file(info)
            return info
        except FileExistsError:
            pass  # fall through to negotiation
        except OSError as exc:
            raise LockError(
                f"cannot create the transition lock {LOCK_PATH}: {exc}. "
                "Check permissions on /opt/platypus."
            ) from exc

        existing = read()
        if existing is None:
            # Empty or malformed: either a crash window (the holder died
            # between create and write) or another process mid-write.
            if force:
                LOCK_PATH.unlink(missing_ok=True)
                continue
            time.sleep(LOCK_REREAD_SECONDS)
            if read() is None:
                raise LockError(
                    f"the transition lock exists but is unreadable: {LOCK_PATH}. "
                    "If no switch is running, remove the file or pass "
                    "--force-unlock."
                )
            continue  # a holder appeared between the two reads: negotiate

        pid = existing.get("pid")
        holder_dead = not isinstance(pid, int) or not _pid_alive(pid)

        if force or holder_dead:
            # Claim atomically via rename: if two processes both decide
            # to steal, only the one whose rename succeeds proceeds; the
            # loser re-reads and negotiates with whatever is there now.
            claim = LOCK_PATH.with_name(
                f"{LOCK_PATH.name}.stale-{pid}-{os.getpid()}"
            )
            try:
                LOCK_PATH.rename(claim)
            except OSError:
                continue  # someone else claimed or removed it first
            try:
                claim.unlink(missing_ok=True)
            except OSError:
                pass
            if not stolen:
                info["stole_from"] = pid
                stolen = True
            continue

        age = _lock_age_seconds(existing)
        raise LockError(
            f"a transition to {existing.get('target')!r} is already in "
            f"progress (PID {pid}, started {int(age)}s ago). If that "
            "process is stuck, re-run with --force-unlock."
        )

    raise LockError(
        "could not acquire the transition lock after "
        f"{_ACQUIRE_ATTEMPTS} attempts — another process is racing for it."
    )


def release() -> None:
    """Release the lock if this process holds it.

    Ownership-aware: a live thief's lock (or any foreign PID's) is left
    alone, so a stolen-from process finishing its cleanup cannot unlock
    somebody else's in-flight transition. An unreadable or missing file
    is unlinked best-effort.
    """
    info = read()
    if (
        info is not None
        and isinstance(info.get("pid"), int)
        and info["pid"] != os.getpid()
    ):
        return
    LOCK_PATH.unlink(missing_ok=True)
