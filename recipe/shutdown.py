"""Graceful shutdown strategies for role containers.

.. deprecated::
    This module is no longer used.  The switch flow now relies on
    ``pre_remove`` hooks in each role's ``template.yml`` to flush state
    (e.g. ``rcon-cli save-all``), followed by ``docker compose down``
    which sends SIGTERM and waits for the container to exit.
    See ``recipe/transition.py`` → ``_compose_down()``.

    This file is kept for historical reference only.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

from .model import ShutdownConfig, ShutdownStrategy

Log = Callable[[str], None]


class ShutdownError(Exception):
    """Raised when a container cannot be stopped gracefully."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _is_running(container: str) -> bool:
    """Return True if the named Docker container is currently running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _exec_rcon(container: str, command: str, log: Log) -> bool:
    """
    Execute  rcon-cli <command>  inside *container*.
    Returns True on success.  Failure is non-fatal — logged as a warning.
    """
    log(f"  rcon › {command!r}")
    try:
        result = subprocess.run(
            ["docker", "exec", container, "rcon-cli", command],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            log(f"  ✓ {out}" if out else "  ✓ ok")
            return True
        log(f"  ! rcon-cli failed (exit {result.returncode}): {result.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        log("  ! rcon-cli timed out after 15 s")
        return False
    except FileNotFoundError:
        log("  ! 'docker' binary not found")
        return False


def _poll_until_stopped(container: str, timeout: int, log: Log) -> bool:
    """
    Poll every 2 s until the container is no longer running.
    Returns True if it stopped within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_running(container):
            return True
        remaining = int(deadline - time.monotonic())
        log(f"  Waiting for {container!r} to exit… ({remaining}s remaining)")
        time.sleep(2)
    return False


def _docker_stop(container: str, grace: int, log: Log) -> None:
    """Send SIGTERM to container; Docker escalates to SIGKILL after *grace* seconds."""
    log(f"  docker stop -t {grace} {container!r}")
    subprocess.run(
        ["docker", "stop", "-t", str(grace), container],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def graceful_shutdown(config: ShutdownConfig, log: Log) -> None:
    """
    Gracefully stop a container according to *config*.

    Raises ShutdownError if the container is still running after all
    shutdown attempts have been exhausted.
    """
    container = config.container

    if not container:
        raise ShutdownError("ShutdownConfig.container is empty — cannot stop.")

    if not _is_running(container):
        log(f"  {container!r} is not running — skipping shutdown.")
        return

    if config.strategy == ShutdownStrategy.RCON:
        _rcon_shutdown(config, log)
    else:
        _signal_shutdown(config, log)

    # Final verification
    if _is_running(container):
        raise ShutdownError(
            f"Container {container!r} is still running after all shutdown attempts."
        )
    log(f"  ✓ {container!r} stopped cleanly.")


def _rcon_shutdown(config: ShutdownConfig, log: Log) -> None:
    """
    RCON shutdown sequence for game servers.

    Steps
    -----
    1. Execute save_commands (e.g. "save-all") to flush world data.
    2. Execute stop_commands (e.g. "stop") to request a clean server exit.
    3. Wait up to `timeout` seconds for the container to exit on its own.
    4. If still running: fall back to `docker stop` (SIGTERM).
    """
    container = config.container
    log(f"[RCON shutdown] container: {container!r}")

    # Step 1 — Save
    if config.save_commands:
        log("  Saving world data…")
        for cmd in config.save_commands:
            _exec_rcon(container, cmd, log)
            time.sleep(1)   # Brief pause so the server can flush

    # Step 2 — Stop via RCON
    if config.stop_commands:
        log("  Sending stop command via RCON…")
        for cmd in config.stop_commands:
            _exec_rcon(container, cmd, log)

    # Step 3 — Wait for natural container exit
    log(f"  Waiting up to {config.timeout}s for {container!r} to exit naturally…")
    if _poll_until_stopped(container, config.timeout, log):
        return   # Clean exit — done

    # Step 4 — Fallback: SIGTERM → SIGKILL
    log("  Timeout reached — escalating to docker stop (SIGTERM)…")
    _docker_stop(container, grace=30, log=log)


def _signal_shutdown(config: ShutdownConfig, log: Log) -> None:
    """Regular SIGTERM shutdown via `docker stop`."""
    container = config.container
    log(f"[SIGTERM shutdown] container: {container!r} (grace: {config.timeout}s)")
    _docker_stop(container, grace=config.timeout, log=log)

