"""Read and write /opt/platypus/state.yml atomically."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .model import PLATYPUS_DIR, STATE_FILE, HistoryEntry, State

# One-generation backup used when state.yml is found corrupt.
STATE_BACKUP: Path = PLATYPUS_DIR / "state.yml.bak"


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

def atomic_write(path: Path, data: str) -> None:
    """Durably write *data* to *path*.

    Keeps the previous generation as a one-file ``.bak`` backup, writes
    through a tmp file, fsyncs it, then atomically replaces the target —
    a crash can never leave a zero-length or half-written primary file.
    """
    if path.exists():
        try:
            path.replace(path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass  # best-effort: the fsync'd primary write matters more
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def load() -> State:
    """Load state from STATE_FILE. Returns a blank State if the file is absent."""
    try:
        return _load_from(STATE_FILE)
    except (yaml.YAMLError, KeyError, ValueError):
        print(
            f"WARNING: {STATE_FILE} is corrupt — trying the backup "
            f"{STATE_BACKUP}.",
            file=sys.stderr,
        )
        return _load_from(STATE_BACKUP)


def _load_from(path: Path) -> State:
    if not path.exists():
        return State(
            schema_version="1",
            active=None,
            activated_at=None,
            transition_lock=None,
            history=[],
        )

    with path.open(encoding="utf-8") as fh:
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

    atomic_write(
        STATE_FILE,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    )
