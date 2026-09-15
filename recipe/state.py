"""Read and write /opt/platypus/state.yml atomically."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import yaml

from .model import PLATYPUS_DIR, STATE_FILE, HistoryEntry, State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> State:
    """Load state from STATE_FILE. Returns a blank State if the file is absent."""
    if not STATE_FILE.exists():
        return State(
            schema_version="1",
            active=None,
            activated_at=None,
            transition_lock=None,
            history=[],
        )

    with STATE_FILE.open(encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh) or {}

    history = [
        HistoryEntry(
            role=h["role"],
            activated_at=_parse_dt(h["activated_at"]),
            deactivated_at=_parse_dt(h.get("deactivated_at")),
        )
        for h in raw.get("history", [])
    ]

    return State(
        schema_version=raw.get("schema_version", "1"),
        active=raw.get("active"),
        activated_at=_parse_dt(raw.get("activated_at")),
        transition_lock=raw.get("transition_lock"),
        history=history,
    )


def save(state: State) -> None:
    """Persist *state* to STATE_FILE via an atomic temp-file write."""
    PLATYPUS_DIR.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "schema_version": state.schema_version,
        "active": state.active,
        "activated_at": (
            state.activated_at.isoformat() if state.activated_at else None
        ),
        "transition_lock": state.transition_lock,
        "history": [
            {
                "role": h.role,
                "activated_at": h.activated_at.isoformat(),
                "deactivated_at": (
                    h.deactivated_at.isoformat() if h.deactivated_at else None
                ),
            }
            for h in state.history
        ],
    }

    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    tmp.replace(STATE_FILE)


def set_lock(state: State, target_role: str) -> None:
    """Acquire the transition lock and write it to disk immediately."""
    state.transition_lock = {
        "role": target_role,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    save(state)


def release_lock(state: State) -> None:
    """Release the transition lock and write to disk."""
    state.transition_lock = None
    save(state)


def is_lock_stale(lock: dict) -> bool:
    """Return True if the PID recorded in *lock* is no longer alive."""
    pid = lock.get("pid")
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)   # Signal 0 = existence check
        return False       # Process is alive
    except ProcessLookupError:
        return True        # Process is gone
    except PermissionError:
        return False       # Process exists, we just can't signal it

