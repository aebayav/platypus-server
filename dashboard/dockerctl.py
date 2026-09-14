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


def get_container_logs(container_id: str, tail: int = 200) -> list[str]:
    """Return the last *tail* log lines for a container."""
    result = _run(["logs", "--tail", str(tail), container_id])
    if result.returncode != 0:
        raise DockerError((result.stderr or "docker logs failed").strip())
    combined = (result.stdout + result.stderr).splitlines()
    return combined


def get_container_stats(container_id: str) -> dict:
    """Return a snapshot of a single container's resource usage."""
    result = _run(
        ["stats", "--no-stream", "--format", "{{json .}}", container_id],
        timeout=10,
    )
    if result.returncode != 0:
        raise DockerError((result.stderr or "docker stats failed").strip())
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        return {
            "cpu_percent": raw.get("CPUPerc", "0%").rstrip("%"),
            "mem_usage": raw.get("MemUsage", "0B / 0B"),
            "mem_percent": raw.get("MemPerc", "0%").rstrip("%"),
            "net_io": raw.get("NetIO", "0B / 0B"),
            "block_io": raw.get("BlockIO", "0B / 0B"),
        }
    raise DockerError("no stats output")


def pull_image(name: str) -> str:
    """Pull an image from a registry. Returns the last line of output."""
    result = _run(["pull", name], timeout=300)
    _require_ok(result, "pull")
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else "done"


def remove_image(image_id: str, force: bool = False) -> None:
    """Remove a local image."""
    args = ["rmi"]
    if force:
        args.append("-f")
    args.append(image_id)
    _require_ok(_run(args), "rmi")

