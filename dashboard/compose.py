"""Docker Compose stack management."""
from __future__ import annotations

import json
import os
import subprocess

COMPOSE_DIR = os.environ.get("COMPOSE_DIR", "/opt/stacks")
_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


class ComposeError(RuntimeError):
    """Raised when a docker compose command fails."""


def _find_stacks() -> list[str]:
    """Return paths of directories under COMPOSE_DIR that have a compose file."""
    paths: list[str] = []
    try:
        for entry in sorted(os.scandir(COMPOSE_DIR), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            if any(
                os.path.exists(os.path.join(entry.path, f)) for f in _COMPOSE_FILES
            ):
                paths.append(entry.path)
    except (FileNotFoundError, PermissionError):
        pass
    return paths


def _run(cwd: str, args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", "compose", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ComposeError("docker compose not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposeError("docker compose timed out") from exc


def list_stacks() -> list[dict]:
    """Return all discovered stacks with container counts and run status."""
    result: list[dict] = []
    for path in _find_stacks():
        name = os.path.basename(path)
        ps = _run(path, ["ps", "--format", "json"], timeout=10)
        containers: list[dict] = []
        if ps.returncode == 0:
            for line in ps.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        running = sum(
            1 for c in containers
            if (c.get("State") or c.get("status") or "").lower() == "running"
        )
        result.append(
            {
                "name": name,
                "path": path,
                "containers": len(containers),
                "running": running,
            }
        )
    return result


def stack_action(name: str, action: str) -> str:
    """Execute up / down / pull on a named stack."""
    allowed = {"up", "down", "pull"}
    if action not in allowed:
        raise ComposeError(f"Unknown action: {action}")
    stacks_map = {os.path.basename(p): p for p in _find_stacks()}
    if name not in stacks_map:
        raise ComposeError(f"Stack '{name}' not found in {COMPOSE_DIR}")
    path = stacks_map[name]
    cmd_map: dict[str, list[str]] = {
        "up": ["up", "-d"],
        "down": ["down"],
        "pull": ["pull"],
    }
    result = _run(path, cmd_map[action], timeout=300)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"compose {action} failed").strip()
        raise ComposeError(detail)
    lines = (result.stdout + result.stderr).strip().splitlines()
    return lines[-1] if lines else "done"
