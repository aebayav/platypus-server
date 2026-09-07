"""Core data structures shared by all tasks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """A single shell command executed as part of a task."""

    title: str
    cmd: str
    privileged: bool = True


@dataclass(frozen=True)
class Task:
    """A setup task shown in the main menu."""

    id: str
    title: str
    description: str
    steps: tuple[Step, ...]
    warning: str | None = None
