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
    """Full contents of /opt/platypus/state.yml (schema v2)."""

    schema_version:  str
    mounted:          list[str]
    history:          list[HistoryEntry]


# ---------------------------------------------------------------------------
# Well-known paths
# ---------------------------------------------------------------------------

PLATYPUS_DIR:       Path = Path("/opt/platypus")
PLATYPUS_ROLES_DIR: Path = PLATYPUS_DIR / "roles"
STATE_FILE:         Path = PLATYPUS_DIR / "state.yml"

# Built-in role templates. PACKAGED_ROLES_DIR ships inside the wheel
# (recipe/roles/); REPO_ROLES_DIR is the repo-root roles/ directory, used as
# a fallback in editable checkouts.
PACKAGED_ROLES_DIR: Path = Path(__file__).parent / "roles"
REPO_ROLES_DIR: Path = Path(__file__).parent.parent / "roles"


def role_dir(role_name: str) -> Path:
    """Return the directory defining *role_name*'s template.yml.

    The packaged directory wins; the repo-root fallback is checked second.
    """
    for base in (PACKAGED_ROLES_DIR, REPO_ROLES_DIR):
        candidate = base / role_name
        if (candidate / "template.yml").is_file():
            return candidate
    raise FileNotFoundError(f"no template.yml found for role {role_name!r}")


def builtin_roles() -> list[str]:
    """Sorted names of all built-in roles found in either source dir."""
    names: set[str] = set()
    for base in (PACKAGED_ROLES_DIR, REPO_ROLES_DIR):
        if base.is_dir():
            names |= {
                entry.name
                for entry in base.iterdir()
                if (entry / "template.yml").is_file()
            }
    return sorted(names)

