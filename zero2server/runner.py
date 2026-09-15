"""Runner helpers for zero-to-server: execute docker compose after generation."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class RunnerError(Exception):
    """Raised when a compose command fails."""


def compose_available() -> bool:
    """Return True if `docker compose` (v2 plugin) is available."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "compose", "version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def run_compose(out_dir: str, *, detach: bool = True) -> None:
    """Run `docker compose up` in *out_dir*, streaming output to stdout.

    Args:
        out_dir: Directory containing the generated ``docker-compose.yml``.
        detach:  If True (default), run with ``-d`` (detached mode).

    Raises:
        RunnerError: If docker compose is not available or exits with a non-zero
                     return code.
    """
    target = Path(out_dir).resolve()
    compose_file = target / "docker-compose.yml"

    if not compose_file.exists():
        raise RunnerError(
            f"docker-compose.yml not found in {target}. "
            "Generate the stack first."
        )

    if not compose_available():
        raise RunnerError(
            "docker compose is not available. "
            "Install Docker Engine with the Compose plugin and try again."
        )

    cmd = ["docker", "compose", "-f", str(compose_file), "up"]
    if detach:
        cmd.append("-d")

    print(f"\n→ Running: {' '.join(cmd)}\n", flush=True)

    proc = subprocess.Popen(
        cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    proc.wait()

    if proc.returncode != 0:
        raise RunnerError(
            f"`docker compose up` exited with code {proc.returncode}."
        )


def install_watchtower_cron(out_dir: str) -> None:
    """Add a daily cron entry that restarts the Watchtower container.

    This keeps the container schedule aligned with system cron (midnight),
    supplementing Watchtower's own ``--interval`` setting.

    Args:
        out_dir: Directory containing the generated ``docker-compose.yml``.

    Raises:
        RunnerError: If writing to ``/etc/cron.d`` fails.
    """
    target = Path(out_dir).resolve()
    compose_file = target / "docker-compose.yml"

    cron_path = Path("/etc/cron.d/platypus-watchtower")
    cron_content = (
        "# Platypus — restart watchtower daily at 03:00 to pick up new images\n"
        f"0 3 * * * root docker compose -f {compose_file} restart watchtower\n"
    )

    try:
        cron_path.write_text(cron_content, encoding="utf-8")
        cron_path.chmod(0o644)
        print(f"  ✓ Cron job written to {cron_path}")
    except PermissionError as exc:
        raise RunnerError(
            f"Cannot write to {cron_path} — run as root or with sudo."
        ) from exc

