"""The mount/dismount engine: manage the server's mounted module set.

Stop mechanism
--------------
``docker compose down`` (no ``--volumes`` flag).

- Bind-mounted ``./data`` directories are **never** touched by compose down.
- For game servers the ``pre_remove`` hooks in template.yml should call
  ``rcon-cli save-all`` and ``rcon-cli stop`` *before* compose down runs,
  so the server process flushes world data cleanly.

Semantics (0.3.0)
-----------------
- ``mount`` is ADDITIVE: it starts exactly one module and never stops
  the others.  Pre-flight validates the effective answers (declared
  ranges) and the module's declared port claims against the mounted
  set — a conflict refuses BEFORE anything is stopped.
- ``dismount`` stops and freezes exactly one module (hooks, compose
  down, its Caddy section); data and answers stay.
- ``reconfigure`` applies new answers: live (down/up + Caddy section)
  for a mounted module, answers-file-only for a dormant one.
- ``switch`` is a deprecated alias of ``mount``.

Answers are saved only after a successful mount, so a failed run never
freezes a typo'd input.  All engine operations run under the atomic
transition lock; Ctrl-C and SIGTERM roll the operation back.
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
from .claims import find_conflicts, resolve_claims
from .model import (
    PLATYPUS_ROLES_DIR,
    HistoryEntry,
    State,
    role_dir,
)
from .renderer import load_answers, save_answers, write_compose
from .validate import validate_answers

Log = Callable[[str], None]


class TransitionError(Exception):
    """Raised when an engine operation cannot be completed."""


class TransitionInterrupted(BaseException):
    """A SIGTERM arrived mid-operation — roll back and re-raise."""


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

def _load_template(module_name: str) -> dict:
    try:
        path = role_dir(module_name) / "template.yml"
    except FileNotFoundError:
        raise TransitionError(f"Module {module_name!r} not found") from None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


_ACTIVE_HOOK_CWD: Path | None = None


@contextlib.contextmanager
def _module_hook_cwd(module_name: str):
    """Ensure hooks run with cwd set to the module's runtime directory."""
    global _ACTIVE_HOOK_CWD
    prev = _ACTIVE_HOOK_CWD
    target_dir = PLATYPUS_ROLES_DIR / module_name
    target_dir.mkdir(parents=True, exist_ok=True)
    _ACTIVE_HOOK_CWD = target_dir
    try:
        yield target_dir
    finally:
        _ACTIVE_HOOK_CWD = prev


def _run_hooks(
    commands: list[str],
    log: Log,
    answers: dict[str, Any] | None = None,
) -> None:
    """Run each hook command, optionally substituting {answers[key]} placeholders."""
    run_cwd = str(_ACTIVE_HOOK_CWD) if _ACTIVE_HOOK_CWD is not None else None
    for cmd in commands:
        if answers:
            try:
                cmd = cmd.format_map({"answers": answers})
            except (KeyError, ValueError):
                pass  # Leave command as-is if substitution fails
        log(f"  $ {cmd}")
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=run_cwd,
        )
        for line in result.stdout.strip().splitlines():
            log(f"    {line}")
        if result.returncode != 0:
            log(f"  ! hook exited {result.returncode}: {result.stderr.strip()}")


def _compose_down(module_name: str, log: Log, strict: bool = False) -> None:
    """
    Stop and remove containers for *module_name*.

    ``--volumes`` flag is intentionally omitted so Docker named volumes
    are preserved.  Bind-mounted ``./data`` dirs are unaffected regardless.

    With ``strict=True`` a failing down raises (used in dismount and
    reconfigure so a stuck stack aborts instead of lying); the default
    is best-effort (used by rollback).
    """
    compose_file = PLATYPUS_ROLES_DIR / module_name / "docker-compose.yml"
    if not compose_file.exists():
        log(f"  No compose file found for {module_name!r} — skipping down.")
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
                f"docker compose down failed for {module_name!r} "
                f"(exit {result.returncode})."
            )
        log(f"  ! compose down exited {result.returncode} — continuing anyway.")


def _compose_up(module_name: str, log: Log) -> None:
    compose_file = PLATYPUS_ROLES_DIR / module_name / "docker-compose.yml"
    if not compose_file.exists():
        raise TransitionError(
            f"docker-compose.yml not found for {module_name!r}: {compose_file}"
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


def _load_questions(module: str) -> list[dict]:
    """Read the module's questions spec (questions.yml); missing → []."""
    try:
        path = role_dir(module) / "questions.yml"
    except FileNotFoundError:
        return []
    try:
        with path.open(encoding="utf-8") as fh:
            spec = yaml.safe_load(fh) or {}
    except OSError:
        return []
    questions = spec.get("questions") or []
    return [q for q in questions if isinstance(q, dict)]


def _pre_flight(
    module: str,
    template: dict,
    answers: dict[str, Any],
    state: State,
    log: Log,
    skip_self: bool = False,
) -> None:
    """Validate answers and claims against the mounted set, BEFORE the
    lock and before anything is stopped.  Raises TransitionError with an
    actionable message pointing at ``platypus reconfigure``."""
    questions = _load_questions(module)
    problems = validate_answers(questions, answers)
    if problems:
        raise TransitionError(
            "invalid answers for "
            f"{module!r} — " + "; ".join(problems)
            + ".  Fix them with: platypus reconfigure " + module
        )

    try:
        new_claims = resolve_claims(template, answers)
    except (KeyError, ValueError) as exc:
        raise TransitionError(
            f"cannot resolve the port claims of {module!r}: {exc}"
        ) from exc

    mounted_claims: dict[str, set] = {}
    for name in state.mounted:
        if skip_self and name == module:
            continue
        try:
            other_template = _load_template(name)
            mounted_claims[name] = resolve_claims(
                other_template, load_answers(name) or {}
            )
        except (TransitionError, KeyError, ValueError, TypeError,
                yaml.YAMLError, OSError) as exc:
            log(
                f"  ⚠ mounted module {name!r} has unresolvable "
                f"answers/claims — its conflict check was skipped ({exc})"
            )

    conflicts = find_conflicts(module, new_claims, mounted_claims)
    if conflicts:
        raise TransitionError(
            f"cannot mount {module!r} — " + "; ".join(conflicts)
            + ".  Free the port (platypus dismount) or pick another with: "
            "platypus reconfigure " + module
        )


def _acquire(module: str, force_unlock: bool, log: Log) -> None:
    try:
        lock_info = lock_mod.acquire(module, force=force_unlock)
    except lock_mod.LockError as exc:
        raise TransitionError(str(exc)) from exc
    if lock_info.get("stole_from") is not None:
        log(f"  Recovered stale lock (was PID {lock_info['stole_from']}).")
    log(f"Lock acquired (PID {lock_info['pid']})")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mount(
    new_module: str,
    answers: dict[str, Any] | None = None,
    log: Log = print,
    force_unlock: bool = False,
) -> None:
    """Start exactly *new_module* additively; mounted modules keep running."""
    state = state_mod.load()

    if new_module in state.mounted:
        log(f"Module {new_module!r} is already mounted — nothing to do.")
        return

    log(f"\nLoading template: {new_module!r}")
    new_template = _load_template(new_module)

    if answers is None:
        answers = load_answers(new_module)
        if answers is None:
            raise TransitionError(
                f"No answers.yml found for {new_module!r} and no answers were "
                "provided. Run the setup form first."
            )
        log(f"  Using existing answers.yml for {new_module!r}.")
    else:
        log(f"  Using newly collected answers for {new_module!r}.")

    _pre_flight(new_module, new_template, answers, state, log)
    _acquire(new_module, force_unlock, log)

    # The mounted set may have changed while we waited for the lock:
    # re-read it and re-check before mutating anything.
    state = state_mod.load()
    if new_module in state.mounted:
        log(f"Module {new_module!r} is already mounted — nothing to do.")
        lock_mod.release()
        return
    try:
        _pre_flight(new_module, new_template, answers, state, log)
    except TransitionError:
        lock_mod.release()
        raise

    try:
        with _interruptible():
            _execute_mount(state, new_module, new_template, answers, log)
    except BaseException as exc:
        log(f"\n[ERROR] {type(exc).__name__}: {exc}")
        log("Rolling back the partial mount…")
        _rollback_partial(new_module, log)
        raise (TransitionError(str(exc)) if isinstance(exc, Exception) else exc) from exc
    finally:
        lock_mod.release()


def _restore_module(
    module: str,
    old_answers: dict[str, Any] | None,
    state: State,
    log: Log,
) -> None:
    """Best-effort restore of the previously running configuration.

    Phase-1 parity: re-render with the OLD answers, restart the stack,
    re-add its Caddy section.  If the restore itself fails, the module
    is de facto dismounted — reflect that in the state (so status tells
    the truth) and name the recovery command.  Never raises.
    """
    try:
        write_compose(module, old_answers or {})
        _compose_up(module, log)
        caddy_mod.upsert_route(module, old_answers or {}, log)
        log(f"  ✓ {module!r} restored to its previous configuration.")
        return
    except BaseException as exc:
        log(f"  ! could not restore {module!r}: {exc}")

    try:
        state.mounted.remove(module)
        state_mod.save(state)
    except Exception as exc:
        log(f"  ! could not persist the dismounted state: {exc}")
    log(
        f"  ⚠ {module!r} left DISMOUNTED (its previous stack could not be "
        f"restored).  Remount it with: platypus mount {module}"
    )


def dismount(
    module: str,
    log: Log = print,
    force_unlock: bool = False,
) -> None:
    """Stop and freeze exactly *module*; other mounted modules keep running."""
    state = state_mod.load()

    if module not in state.mounted:
        raise TransitionError(f"Module {module!r} is not mounted.")

    template = _load_template(module)
    answers = load_answers(module)

    _acquire(module, force_unlock, log)
    # Another operation may have changed the set while we waited.
    state = state_mod.load()
    now = datetime.now(timezone.utc)
    try:
        with _interruptible():
            if module not in state.mounted:
                raise TransitionError(f"Module {module!r} is not mounted.")
            pre_remove = template.get("hooks", {}).get("pre_remove", [])
            if pre_remove:
                log("  pre_remove hooks:")
                with _module_hook_cwd(module):
                    _run_hooks(pre_remove, log, answers=answers)

            _compose_down(module, log, strict=True)

            log("  Caddy config update:")
            caddy_mod.remove_route(module, log)

            post_remove = template.get("hooks", {}).get("post_remove", [])
            if post_remove:
                log("  post_remove hooks:")
                with _module_hook_cwd(module):
                    _run_hooks(post_remove, log, answers=answers)

            for entry in state.history:
                if entry.role == module and entry.deactivated_at is None:
                    entry.deactivated_at = now
                    break
            state.mounted.remove(module)
            state_mod.save(state)
            log(f"\n  ✓ Dismounted and frozen: {module!r}")
    except BaseException as exc:
        # The module's pre_remove may have done damage (e.g. Nextcloud's
        # maintenance:mode --on); its rollback: hooks undo it, best-effort.
        try:
            rollback_cmds = template.get("hooks", {}).get("rollback", [])
            if rollback_cmds:
                log("  rollback hooks:")
                with _module_hook_cwd(module):
                    _run_hooks(rollback_cmds, log, answers=answers)
        except BaseException as hook_exc:
            log(f"  ! rollback hooks failed: {hook_exc}")
        raise (TransitionError(str(exc)) if isinstance(exc, Exception) else exc) from exc
    finally:
        lock_mod.release()


def reconfigure(
    module: str,
    answers: dict[str, Any] | None = None,
    log: Log = print,
    force_unlock: bool = False,
) -> None:
    """Apply new answers for *module*.

    Mounted: validate (conflict-checked against the OTHER mounted
    modules), then recreate the stack through the locked path — compose
    re-render, down, up, Caddy section refresh.  Dormant: validate and
    rewrite answers.yml only; nothing is started.
    """
    if answers is None:
        raise TransitionError(
            f"reconfigure {module!r} needs the form's answers — run it via "
            "the CLI so the questions are collected first."
        )

    state = state_mod.load()
    template = _load_template(module)
    mounted = module in state.mounted

    if not mounted:
        _pre_flight(module, template, answers, state, log)
        save_answers(module, answers)
        log(f"  ✓ {module!r} is dormant — answers saved; applied at next mount.")
        return

    _pre_flight(module, template, answers, state, log, skip_self=True)
    _acquire(module, force_unlock, log)
    # Another operation may have changed the set while we waited.
    state = state_mod.load()
    if module not in state.mounted:
        lock_mod.release()
        raise TransitionError(
            f"Module {module!r} is no longer mounted — nothing to "
            "reconfigure.  Mount it first: platypus mount {module}"
        )
    old_answers = load_answers(module)  # the configuration to restore on failure
    try:
        with _interruptible():
            write_compose(module, answers)
            _compose_down(module, log, strict=True)
            _compose_up(module, log)
            log("  Caddy config update:")
            caddy_mod.upsert_route(module, answers, log)
            save_answers(module, answers)
            log(f"\n  ✓ {module!r} reconfigured and restarted.")
    except BaseException as exc:
        log(f"\n[ERROR] {type(exc).__name__}: {exc}")
        log("Rolling back to the previous configuration…")
        _restore_module(module, old_answers, state, log)
        raise (TransitionError(str(exc)) if isinstance(exc, Exception) else exc) from exc
    finally:
        lock_mod.release()


#: Deprecated spelling of :func:`mount` — kept as a plain alias.
switch = mount


# ---------------------------------------------------------------------------
# Execution / rollback
# ---------------------------------------------------------------------------

def _execute_mount(
    state: State,
    new_module: str,
    new_template: dict,
    answers: dict[str, Any],
    log: Log,
) -> None:
    now = datetime.now(timezone.utc)
    _hr = "─" * 52

    log(f"\n{_hr}")
    log(f"  Mounting: {new_module!r}")
    log(_hr)

    # data/ bind-mount dir — never deleted
    data_dir = PLATYPUS_ROLES_DIR / new_module / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"  data dir  {data_dir}  ✓")

    # Render compose from the in-memory answers.  answers.yml is only
    # persisted at the end, so a failed mount never freezes a bad input.
    compose_file = write_compose(new_module, answers)
    log(f"  compose   {compose_file}  ✓")

    pre_apply = new_template.get("hooks", {}).get("pre_apply", [])
    if pre_apply:
        log("  pre_apply hooks:")
        with _module_hook_cwd(new_module):
            _run_hooks(pre_apply, log, answers=answers)

    _compose_up(new_module, log)

    log("  Caddy config update:")
    caddy_mod.upsert_route(new_module, answers, log)

    post_apply = new_template.get("hooks", {}).get("post_apply", [])
    if post_apply:
        log("  post_apply hooks:")
        with _module_hook_cwd(new_module):
            _run_hooks(post_apply, log, answers=answers)

    save_answers(new_module, answers)   # only now: the mount succeeded
    state.history.append(
        HistoryEntry(role=new_module, activated_at=now, deactivated_at=None)
    )
    state.mounted.append(new_module)
    state_mod.save(state)

    log(f"\n{'═' * 52}")
    log(f"  ✓ Mounted: {new_module!r}   ({len(state.mounted)} module(s) mounted)")
    log(f"{'═' * 52}")


def _rollback_partial(new_module: str, log: Log) -> None:
    """Remove the partially started stack and its Caddy section.

    Every step is guarded: a second Ctrl-C, a SIGTERM, or a broken
    dependency is logged and the NEXT step still runs — the rollback
    itself never raises.  Mounted modules are never touched.
    """
    for step in (
        lambda: _compose_down(new_module, log),
        lambda: caddy_mod.remove_route(new_module, log),
    ):
        try:
            step()
        except BaseException as exc:
            log(f"  ! rollback step failed: {exc}")
