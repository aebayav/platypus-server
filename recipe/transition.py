"""Switch flow: gracefully stop the current role, start the new one.

Entry point: transition.switch(new_role_name)

Phase 1 — Stop current role
  • pre_remove hooks  (e.g. custom pre-shutdown scripts)
  • graceful_shutdown (RCON save-all → stop, or SIGTERM)
  • post_remove hooks

Phase 2 — Prepare new role
  • Ensure /opt/platypus/roles/<new>/data/ exists  (never deleted)
  • pre_apply hooks

Phase 3 — Start new role
  • docker compose -f <new>/docker-compose.yml up -d
  • post_apply hooks

Phase 4 — Persist state
  • Update state.yml (active, history, release lock)

On any error → rollback (restart previous role's compose stack).
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from . import state as state_mod
from .model import (
    PLATYPUS_ROLES_DIR,
    ROLES_SOURCE_DIR,
    HistoryEntry,
    ShutdownConfig,
    ShutdownStrategy,
    State,
)
from .shutdown import ShutdownError, graceful_shutdown

Log = Callable[[str], None]


class TransitionError(Exception):
    """Raised when a role switch cannot be completed."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_template(role_name: str) -> dict:
    """Load and parse template.yml for *role_name* from the source roles/ dir."""
    path = ROLES_SOURCE_DIR / role_name / "template.yml"
    if not path.exists():
        raise TransitionError(
            f"Role {role_name!r} not found — expected template at {path}"
        )
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _shutdown_cfg(template: dict) -> ShutdownConfig:
    """Build a ShutdownConfig from a parsed template dict."""
    sd = template.get("shutdown", {})
    strategy_str = sd.get("strategy", "signal").lower()
    try:
        strategy = ShutdownStrategy(strategy_str)
    except ValueError:
        strategy = ShutdownStrategy.SIGNAL

    return ShutdownConfig(
        strategy=strategy,
        container=sd.get("container", ""),
        save_commands=tuple(sd.get("save_commands", [])),
        stop_commands=tuple(sd.get("stop_commands", [])),
        timeout=int(sd.get("timeout", 30)),
    )


def _run_hooks(commands: list[str], log: Log) -> None:
    """Execute each hook command in a shell, logging output."""
    for cmd in commands:
        log(f"  $ {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                log(f"    {line}")
        if result.returncode != 0:
            log(
                f"  ! Hook exited {result.returncode}: "
                f"{result.stderr.strip()}"
            )


def _compose_up(role_name: str, log: Log) -> None:
    compose_file = PLATYPUS_ROLES_DIR / role_name / "docker-compose.yml"
    if not compose_file.exists():
        raise TransitionError(
            f"docker-compose.yml not found for {role_name!r}: {compose_file}"
        )
    log(f"  docker compose up -d  ({compose_file})")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )
    for line in (result.stdout + result.stderr).strip().splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        raise TransitionError(
            f"docker compose up failed (exit {result.returncode})"
        )


def _compose_down_safe(role_name: str, log: Log) -> None:
    """
    Emergency fallback only — stop containers without removing volumes.
    Prefer graceful_shutdown over this wherever possible.
    """
    compose_file = PLATYPUS_ROLES_DIR / role_name / "docker-compose.yml"
    if not compose_file.exists():
        return
    log(f"  docker compose down --volumes=false  (emergency fallback)")
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "down", "--volumes=false"],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def switch(new_role_name: str, log: Log = print) -> None:
    """
    Switch the server from its current role to *new_role_name*.

    Expects:
    • /opt/platypus/roles/<new_role_name>/docker-compose.yml  already rendered
    • roles/<new_role_name>/template.yml  present in the repo
    """
    state = state_mod.load()

    # ------------------------------------------------------------------
    # Guard: transition lock
    # ------------------------------------------------------------------
    if state.transition_lock:
        lock = state.transition_lock
        if state_mod.is_lock_stale(lock):
            log(f"Stale transition lock (PID {lock.get('pid')}) — clearing.")
            state_mod.release_lock(state)
            state = state_mod.load()
        else:
            raise TransitionError(
                f"Transition to {lock.get('role')!r} already in progress "
                f"(PID {lock.get('pid')}). "
                "If this is stale, remove transition_lock from "
                "/opt/platypus/state.yml manually."
            )

    if new_role_name == state.active:
        log(f"Role {new_role_name!r} is already active — nothing to do.")
        return

    # ------------------------------------------------------------------
    # Validate new role before touching anything
    # ------------------------------------------------------------------
    log(f"\nLoading role template: {new_role_name!r}")
    new_template = _load_template(new_role_name)

    # ------------------------------------------------------------------
    # Acquire lock
    # ------------------------------------------------------------------
    state_mod.set_lock(state, new_role_name)
    log(f"Transition lock acquired (PID {os.getpid()})")

    try:
        _execute_switch(state, new_role_name, new_template, log)
    except Exception as exc:
        log(f"\n[ERROR] {exc}")
        log("Rolling back to previous role…")
        _rollback(state, log)
        state_mod.release_lock(state)
        raise TransitionError(str(exc)) from exc


def _execute_switch(
    state: State,
    new_role_name: str,
    new_template: dict,
    log: Log,
) -> None:
    now = datetime.now(timezone.utc)

    # ==================================================================
    # PHASE 1 — Stop current role
    # ==================================================================
    if state.active:
        current = state.active
        log(f"\n{'─'*50}")
        log(f"Phase 1 — Stopping: {current!r}")
        log(f"{'─'*50}")

        current_template = _load_template(current)
        sd_cfg = _shutdown_cfg(current_template)

        # pre_remove hooks
        pre_remove = current_template.get("hooks", {}).get("pre_remove", [])
        if pre_remove:
            log("pre_remove hooks:")
            _run_hooks(pre_remove, log)

        # Graceful shutdown (RCON or SIGTERM — never compose down)
        try:
            graceful_shutdown(sd_cfg, log)
        except ShutdownError as exc:
            log(f"  ! {exc}")
            log("  Falling back to compose down --volumes=false")
            _compose_down_safe(current, log)

        # post_remove hooks
        post_remove = current_template.get("hooks", {}).get("post_remove", [])
        if post_remove:
            log("post_remove hooks:")
            _run_hooks(post_remove, log)

        # Record deactivation time in history
        for entry in state.history:
            if entry.role == current and entry.deactivated_at is None:
                entry.deactivated_at = now
                break

    # ==================================================================
    # PHASE 2 — Prepare new role
    # ==================================================================
    log(f"\n{'─'*50}")
    log(f"Phase 2 — Preparing: {new_role_name!r}")
    log(f"{'─'*50}")

    data_dir = PLATYPUS_ROLES_DIR / new_role_name / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"  data dir : {data_dir}  ✓")

    # pre_apply hooks
    pre_apply = new_template.get("hooks", {}).get("pre_apply", [])
    if pre_apply:
        log("pre_apply hooks:")
        _run_hooks(pre_apply, log)

    # ==================================================================
    # PHASE 3 — Start new role
    # ==================================================================
    log(f"\n{'─'*50}")
    log(f"Phase 3 — Starting: {new_role_name!r}")
    log(f"{'─'*50}")

    _compose_up(new_role_name, log)

    # post_apply hooks
    post_apply = new_template.get("hooks", {}).get("post_apply", [])
    if post_apply:
        log("post_apply hooks:")
        _run_hooks(post_apply, log)

    # ==================================================================
    # PHASE 4 — Persist state
    # ==================================================================
    state.history.append(
        HistoryEntry(role=new_role_name, activated_at=now, deactivated_at=None)
    )
    state.active = new_role_name
    state.activated_at = now
    state_mod.release_lock(state)   # saves state.yml

    log(f"\n{'═'*50}")
    log(f"✓ Active role: {new_role_name!r}")
    log(f"{'═'*50}")


def _rollback(state: State, log: Log) -> None:
    """Best-effort: restart the previous role if its compose file still exists."""
    if not state.active:
        log("  No previous role to restore.")
        return
    compose_file = PLATYPUS_ROLES_DIR / state.active / "docker-compose.yml"
    if not compose_file.exists():
        log(f"  Cannot rollback — compose file not found: {compose_file}")
        return
    log(f"  Restarting {state.active!r}…")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log(f"  ✓ {state.active!r} restored.")
    else:
        log(f"  ! Rollback failed: {result.stderr.strip()}")
