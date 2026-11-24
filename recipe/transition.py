"""Switch flow: stop current role → start new role.

Stop mechanism
--------------
``docker compose down`` (no ``--volumes`` flag).

- Bind-mounted ``./data`` directories are **never** touched by compose down.
- For game servers the ``pre_remove`` hooks in template.yml should call
  ``rcon-cli save-all`` and ``rcon-cli stop`` *before* compose down runs,
  so the server process flushes world data cleanly.

New role startup
----------------
- If ``answers.yml`` exists → reuse it (no TUI prompt needed).
- If missing → caller must supply an *answers* dict (collected by the TUI).
  Passing ``answers=None`` with no existing file raises ``TransitionError``.

Full flow
---------
Phase 1  Stop current role
  pre_remove hooks  →  docker compose down  →  post_remove hooks

Phase 2  Prepare new role
  ensure data/ exists  →  save answers.yml  →  render docker-compose.yml

Phase 3  Start new role
  pre_apply hooks  →  docker compose up -d  →  Caddy update  →  post_apply hooks

Phase 4  Persist state
  update state.yml (active, activated_at, history)  →  release lock
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from . import caddy as caddy_mod
from . import lock as lock_mod
from . import state as state_mod
from .model import (
    PLATYPUS_ROLES_DIR,
    HistoryEntry,
    State,
    role_dir,
)
from .renderer import load_answers, render_compose, save_answers, write_compose

Log = Callable[[str], None]


class TransitionError(Exception):
    """Raised when a role switch cannot be completed."""


class TransitionInterrupted(BaseException):
    """A SIGTERM arrived mid-transition — roll back and re-raise."""


@contextlib.contextmanager
def _interruptible():
    """Turn SIGTERM into TransitionInterrupted for the duration."""
    def handler(signum, frame):
        raise TransitionInterrupted("SIGTERM received during transition")

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_template(role_name: str) -> dict:
    try:
        path = role_dir(role_name) / "template.yml"
    except FileNotFoundError:
        raise TransitionError(f"Role {role_name!r} not found") from None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _run_hooks(
    commands: list[str],
    log: Log,
    answers: dict[str, Any] | None = None,
) -> None:
    """Run each hook command, optionally substituting {answers[key]} placeholders."""
    for cmd in commands:
        if answers:
            try:
                cmd = cmd.format_map({"answers": answers})
            except (KeyError, ValueError):
                pass  # Leave command as-is if substitution fails
        log(f"  $ {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        for line in result.stdout.strip().splitlines():
            log(f"    {line}")
        if result.returncode != 0:
            log(f"  ! hook exited {result.returncode}: {result.stderr.strip()}")


def _compose_down(role_name: str, log: Log, strict: bool = False) -> None:
    """
    Stop and remove containers for *role_name*.

    ``--volumes`` flag is intentionally omitted so Docker named volumes
    are preserved.  Bind-mounted ``./data`` dirs are unaffected regardless.

    With ``strict=True`` a failing down raises (used in Phase 1 so a
    stuck old stack aborts the switch); the default is best-effort
    (used by rollback).
    """
    compose_file = PLATYPUS_ROLES_DIR / role_name / "docker-compose.yml"
    if not compose_file.exists():
        log(f"  No compose file found for {role_name!r} — skipping down.")
        return
    log(f"  docker compose down  ({compose_file})")
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "down"],
        capture_output=True,
        text=True,
    )
    for line in (result.stdout + result.stderr).strip().splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        if strict:
            raise TransitionError(
                f"docker compose down failed for {role_name!r} "
                f"(exit {result.returncode}) — aborting before the new role "
                "is prepared."
            )
        log(f"  ! compose down exited {result.returncode} — continuing anyway.")


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _single(state: State) -> str | None:
    """The last-mounted module (v1 transitional helper; Task 6 removes it)."""
    return state.mounted[-1] if state.mounted else None


def switch(
    new_role_name: str,
    answers: dict[str, Any] | None = None,
    log: Log = print,
    force_unlock: bool = False,
) -> None:
    """
    Switch the server to *new_role_name*.

    Parameters
    ----------
    new_role_name:
        Target role (must have a template.yml in the packaged roles dir).
    answers:
        User-provided answers dict (from TUI form).  If ``None``, the
        existing ``answers.yml`` for the role is loaded.  If neither
        exists, ``TransitionError`` is raised.
    log:
        Callable used for progress output (default: print).
    force_unlock:
        Steal a live transition lock held by another process.
    """
    state = state_mod.load()
    prev_active = _single(state)

    if new_role_name in state.mounted:
        log(f"Module {new_role_name!r} is already mounted — nothing to do.")
        return

    # ------------------------------------------------------------------
    # Validate new role + resolve answers before touching anything
    # ------------------------------------------------------------------
    log(f"\nLoading template: {new_role_name!r}")
    new_template = _load_template(new_role_name)

    if answers is None:
        answers = load_answers(new_role_name)
        if answers is None:
            raise TransitionError(
                f"No answers.yml found for {new_role_name!r} and no answers were "
                "provided. Run the setup form first."
            )
        log(f"  Using existing answers.yml for {new_role_name!r}.")
    else:
        log(f"  Using newly collected answers for {new_role_name!r}.")

    # ------------------------------------------------------------------
    # Acquire the atomic transition lock (file-based, O_EXCL)
    # ------------------------------------------------------------------
    try:
        lock_info = lock_mod.acquire(new_role_name, force=force_unlock)
    except lock_mod.LockError as exc:
        raise TransitionError(str(exc)) from exc
    if lock_info.get("stole_from") is not None:
        log(f"  Recovered stale lock (was PID {lock_info['stole_from']}).")
    log(f"Lock acquired (PID {lock_info['pid']})")

    try:
        with _interruptible():
            _execute(state, new_role_name, new_template, answers, log)
    except BaseException as exc:
        log(f"\n[ERROR] {type(exc).__name__}: {exc}")
        log("Rolling back to previous role…")
        # prev_active, not state.active: _execute may have mutated state
        # before failing, and the wrong target would "restore" the NEW role.
        with _interruptible():
            _rollback(state, prev_active, new_role_name, log)
        raise (TransitionError(str(exc)) if isinstance(exc, Exception) else exc) from exc
    finally:
        lock_mod.release()


# ---------------------------------------------------------------------------
# Execution phases
# ---------------------------------------------------------------------------

def _execute(
    state: State,
    new_role: str,
    new_template: dict,
    answers: dict[str, Any],
    log: Log,
) -> None:
    now = datetime.now(timezone.utc)
    _hr = "─" * 52

    # ==================================================================
    # PHASE 1 — Stop current module (transitional: the single mounted one)
    # ==================================================================
    if prev := _single(state):
        cur = prev
        log(f"\n{_hr}")
        log(f"  Phase 1  Stopping: {cur!r}")
        log(_hr)

        cur_template = _load_template(cur)

        # Load current role's answers for pre_remove hook interpolation
        cur_answers = load_answers(cur)

        pre_remove = cur_template.get("hooks", {}).get("pre_remove", [])
        if pre_remove:
            log("  pre_remove hooks:")
            _run_hooks(pre_remove, log, answers=cur_answers)

        _compose_down(cur, log, strict=True)

        post_remove = cur_template.get("hooks", {}).get("post_remove", [])
        if post_remove:
            log("  post_remove hooks:")
            _run_hooks(post_remove, log, answers=cur_answers)

        # Record deactivation in history
        for entry in state.history:
            if entry.role == cur and entry.deactivated_at is None:
                entry.deactivated_at = now
                break

    # ==================================================================
    # PHASE 2 — Prepare new role
    # ==================================================================
    log(f"\n{_hr}")
    log(f"  Phase 2  Preparing: {new_role!r}")
    log(_hr)

    # data/ bind-mount dir — never deleted
    data_dir = PLATYPUS_ROLES_DIR / new_role / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"  data dir  {data_dir}  ✓")

    # Render compose from the in-memory answers.  answers.yml is only
    # persisted in Phase 4, so a failed switch never freezes a bad input.
    compose_file = write_compose(new_role, answers)
    log(f"  compose   {compose_file}  ✓")

    # ==================================================================
    # PHASE 3 — Start new role
    # ==================================================================
    log(f"\n{_hr}")
    log(f"  Phase 3  Starting: {new_role!r}")
    log(_hr)

    pre_apply = new_template.get("hooks", {}).get("pre_apply", [])
    if pre_apply:
        log("  pre_apply hooks:")
        _run_hooks(pre_apply, log, answers=answers)

    _compose_up(new_role, log)

    # Caddy — add the new module's route section
    log("  Caddy config update:")
    caddy_mod.upsert_route(new_role, answers, log)

    post_apply = new_template.get("hooks", {}).get("post_apply", [])
    if post_apply:
        log("  post_apply hooks:")
        _run_hooks(post_apply, log, answers=answers)

    # ==================================================================
    # PHASE 4 — Persist state
    # ==================================================================
    save_answers(new_role, answers)   # only now: the switch succeeded
    state.history.append(
        HistoryEntry(role=new_role, activated_at=now, deactivated_at=None)
    )
    state.mounted = [new_role]  # transitional single-module semantics
    state_mod.save(state)

    log(f"\n{'═' * 52}")
    log(f"  ✓ Active role: {new_role!r}")
    log(
        f"    Switched from {state.history[-2].role!r}"
        if len(state.history) >= 2
        else f"    First activation at {now.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    log(f"{'═' * 52}")


def _rollback(state: State, prev_active: str | None, new_role: str, log: Log) -> None:
    """Undo a failed or interrupted switch as far as it got.

    *prev_active* is the role that was active before the switch (captured
    by the caller — never the possibly-mutated ``state.active``).

    Order: remove the partially started new stack, restore the old
    role's Caddy route, run the old role's ``rollback`` hooks (undoing
    damage its ``pre_remove`` did, e.g. Nextcloud's maintenance mode),
    and restart the old stack.  Every step is guarded: a second Ctrl-C,
    a SIGTERM, or a broken dependency inside rollback is logged and the
    NEXT step still runs — rollback itself never raises.
    """
    try:
        _compose_down(new_role, log)
    except BaseException as exc:
        log(f"  ! rollback: compose down of {new_role!r} failed: {exc}")

    if not prev_active:
        log("  No previous role to restore.")
        return
    old = prev_active

    try:
        old_answers = load_answers(old)
    except Exception as exc:
        log(f"  ! rollback: could not load answers for {old!r}: {exc}")
        old_answers = None

    try:
        caddy_mod.upsert_route(old, old_answers or {}, log)
    except BaseException as exc:
        log(f"  ! Caddy route restore failed: {exc}")

    try:
        rollback_cmds = _load_template(old).get("hooks", {}).get("rollback", [])
    except Exception as exc:
        log(f"  ! Could not load rollback hooks for {old!r}: {exc}")
        rollback_cmds = []
    log("  rollback hooks:")
    try:
        _run_hooks(rollback_cmds, log, answers=old_answers)
    except BaseException as exc:
        log(f"  ! rollback hooks failed: {exc}")

    try:
        _compose_up(old, log)
        log(f"  ✓ {old!r} restored.")
    except BaseException as exc:
        log(f"  ! Rollback failed to restart {old!r}: {exc}")
