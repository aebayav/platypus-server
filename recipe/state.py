"""Read and write /opt/platypus/state.yml atomically."""

from __future__ import annotations

import os
import shutil
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

    The tmp file is written and fsynced first, so the primary never
    disappears before the new content exists on disk; the previous
    generation is kept (copied, not moved) as a one-file ``.bak``
    backup, and the final replace is atomic — a crash can never leave
    a zero-length, half-written, or missing primary file.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        try:
            shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass  # best-effort: the fsync'd primary write matters more
    tmp.replace(path)


SCHEMA_VERSION = "2"  # v1 (single active role) migrates automatically on load


def _blank_state() -> State:
    return State(schema_version=SCHEMA_VERSION, mounted=[], history=[])


def load() -> State:
    """Load state from STATE_FILE. Returns a blank State if the file is absent.

    A missing primary with an existing backup is restored from it rather
    than silently reset to blank; a corrupt primary falls back to the
    backup generation instead of crashing every command.
    """
    if not STATE_FILE.exists():
        if STATE_BACKUP.exists():
            print(
                f"WARNING: {STATE_FILE} missing — restoring from "
                f"{STATE_BACKUP}.",
                file=sys.stderr,
            )
            st = _load_from(STATE_BACKUP)
            try:
                save(st)
            except OSError:
                pass  # read-only mounts: the next save will persist it
            return st
        return _load_from(STATE_FILE)

    try:
        return _load_from(STATE_FILE)
    except (yaml.YAMLError, KeyError, ValueError, AttributeError, TypeError):
        print(
            f"WARNING: {STATE_FILE} is corrupt — trying the backup "
            f"{STATE_BACKUP}.",
            file=sys.stderr,
        )
        return _load_from(STATE_BACKUP)


def _load_from(path: Path) -> State:
    if not path.exists():
        return _blank_state()

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

    if raw.get("schema_version") != SCHEMA_VERSION:
        # v1 (or legacy): a single `active` role becomes the mounted set.
        active = raw.get("active")
        st = State(
            schema_version=SCHEMA_VERSION,
            mounted=[active] if active else [],
            history=history,
        )
        print(
            f"Upgraded {path.name} to state schema v2 "
            "(active role -> mounted set); previous file kept as .bak.",
            file=sys.stderr,
        )
        try:
            atomic_write(
                STATE_FILE,
                yaml.safe_dump(
                    {
                        "schema_version": st.schema_version,
                        "mounted": st.mounted,
                        "history": [
                            {
                                "role": h.role,
                                "activated_at": h.activated_at.isoformat(),
                                "deactivated_at": (
                                    h.deactivated_at.isoformat()
                                    if h.deactivated_at
                                    else None
                                ),
                            }
                            for h in st.history
                        ],
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
            )
        except OSError:
            pass  # read-only mounts: the next save persists the migration
        return st

    return State(
        schema_version=SCHEMA_VERSION,
        mounted=list(raw.get("mounted", [])),
        history=history,
    )


def save(state: State) -> None:
    """Persist *state* to STATE_FILE via an atomic temp-file write."""
    PLATYPUS_DIR.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "schema_version": state.schema_version,
        "mounted": list(state.mounted),
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
