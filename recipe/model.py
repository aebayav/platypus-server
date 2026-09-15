"""Core data models for the recipe / role system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class ShutdownStrategy(str, Enum):
    """How to gracefully stop a role's containers."""
    RCON   = "rcon"    # Game servers with RCON support (Minecraft, etc.)
    SIGNAL = "signal"  # docker stop — SIGTERM then SIGKILL


@dataclass(frozen=True)
class ShutdownConfig:
    """Describes how to gracefully stop the containers for a role."""
    strategy:      ShutdownStrategy   = ShutdownStrategy.SIGNAL
    container:     str                = ""   # Docker container name
    save_commands: tuple[str, ...]    = ()   # e.g. ("save-all",)
    stop_commands: tuple[str, ...]    = ()   # e.g. ("stop",)
    timeout:       int                = 30   # Seconds before forced kill


# ---------------------------------------------------------------------------
# Role definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    """A single TUI prompt inside a role's questions.yml."""
    id:       str
    label:    str
    type:     str            # "text" | "integer" | "select" | "confirm"
    default:  Any  = None
    choices:  tuple[str, ...] = ()
    validate: str | None = None
    required: bool = False


@dataclass(frozen=True)
class Role:
    """Parsed representation of a role template (template.yml + questions.yml)."""
    name:             str
    version:          str
    description:      str
    questions:        tuple[Question, ...]
    shutdown:         ShutdownConfig
    hooks:            dict[str, tuple[str, ...]]
    compose_template: str
    source_path:      Path    # Absolute path to the template.yml file


# ---------------------------------------------------------------------------
# Runtime answers & state
# ---------------------------------------------------------------------------

@dataclass
class Answers:
    """User responses collected by the TUI, saved to answers.yml."""
    role:        str
    answered_at: datetime
    answers:     dict[str, Any]


@dataclass
class HistoryEntry:
    """One row in state.yml → history list."""
    role:           str
    activated_at:   datetime
    deactivated_at: datetime | None = None


@dataclass
class State:
    """Full contents of /opt/platypus/state.yml."""
    schema_version:  str
    active:          str | None
    activated_at:    datetime | None
    transition_lock: dict | None
    history:         list[HistoryEntry]

    # ----------------------------------------------------------------
    # Convenience helpers (not persisted)
    # ----------------------------------------------------------------
    @property
    def active_role_dir(self) -> Path | None:
        if not self.active:
            return None
        return PLATYPUS_ROLES_DIR / self.active

    @property
    def active_compose(self) -> Path | None:
        d = self.active_role_dir
        return (d / "docker-compose.yml") if d else None


# ---------------------------------------------------------------------------
# Well-known paths
# ---------------------------------------------------------------------------

PLATYPUS_DIR:       Path = Path("/opt/platypus")
PLATYPUS_ROLES_DIR: Path = PLATYPUS_DIR / "roles"
STATE_FILE:         Path = PLATYPUS_DIR / "state.yml"

# Built-in role templates (shipped with the repo)
ROLES_SOURCE_DIR: Path = Path(__file__).parent.parent / "roles"
