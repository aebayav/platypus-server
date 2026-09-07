"""Docker container operations via the docker CLI."""

from __future__ import annotations

import json
import subprocess


class DockerError(RuntimeError):
    """Raised when a docker command fails."""


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise DockerError("docker CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError("docker command timed out") from exc


def _require_ok(result: subprocess.CompletedProcess, action: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DockerError(f"{action} failed: {detail}")


def list_containers() -> list[dict]:
    result = _run(["ps", "-a", "--format", "{{json .}}"])
    if result.returncode != 0:
        raise DockerError((result.stderr or "docker ps failed").strip())
    containers: list[dict] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        containers.append({
            "id": raw.get("ID", ""),
            "name": raw.get("Names", "").lstrip("/"),
            "image": raw.get("Image", ""),
            "state": raw.get("State", ""),
            "status": raw.get("Status", ""),
            "ports": raw.get("Ports", ""),
        })
    return containers


def list_images() -> list[dict]:
    result = _run(["images", "--format", "{{json .}}"])
    if result.returncode != 0:
        raise DockerError((result.stderr or "docker images failed").strip())
    images: list[dict] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        repo = raw.get("Repository", "")
        tag = raw.get("Tag", "")
        images.append({
            "id": raw.get("ID", ""),
            "name": f"{repo}:{tag}" if repo != "<none>" else raw.get("ID", "")[:12],
            "size": raw.get("Size", ""),
        })
    return images


def start_container(container_id: str) -> None:
    _require_ok(_run(["start", container_id]), "start")


def stop_container(container_id: str) -> None:
    _require_ok(_run(["stop", container_id]), "stop")


def restart_container(container_id: str) -> None:
    _require_ok(_run(["restart", container_id]), "restart")


def remove_container(container_id: str) -> None:
    _require_ok(_run(["rm", "-f", container_id]), "remove")


def run_container(image: str, name: str | None = None, ports: str | None = None) -> str:
    args = ["run", "-d"]
    if name:
        args += ["--name", name]
    if ports:
        for mapping in ports.split(","):
            mapping = mapping.strip()
            if mapping:
                args += ["-p", mapping]
    args.append(image)
    result = _run(args, timeout=180)
    _require_ok(result, "run")
    return result.stdout.strip()
