# Phase 1 — Trustworthy Transition Engine (0.2.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the recipe transition engine safe — atomic file lock, real rollback, interruption recovery, durable state/answers — released as 0.2.1.

**Architecture:** A new `recipe/lock.py` owns an `O_EXCL` lock file at `/opt/platypus/transition.lock`, replacing the racy in-`state.yml` lock. `transition.switch()` is restructured: acquire lock → validate → Phase 1 stop (down failures now fatal) → Phase 2 prepare (compose rendered from in-memory answers; answers no longer saved before success) → Phase 3 start → Phase 4 persist (answers + state) → release lock. All error paths — including `KeyboardInterrupt` and SIGTERM — run the new rollback: down the partial new stack, restore the old Caddy route, run the old module's `rollback:` hooks, re-up the old stack. `state.yml` writes gain fsync + a one-generation backup with loader fallback.

**Tech Stack:** Python 3.10+ stdlib (fcntl-free `os.open` O_EXCL, `signal`, `os.fsync`), pytest with the subprocess-monkeypatch style of `tests/test_caddy.py`.

**Spec:** `docs/superpowers/specs/2026-11-23-modular-mount-system-design.md` — Phase 1 section + Release shape ruling. Phases 2–3 (mount vocabulary, state v2, community) are OUT of scope here.

## Global Constraints

- **No vocabulary/schema change in this release:** user-facing words stay `role`/`switch`; `state.yml` keeps `active` + `history`; the `transition_lock` key is simply no longer *written* and is ignored when found in old files. `mounted:` lists are phase 2.
- Version: bump to **0.2.1** (last task only); pure bugfix release.
- Runtime layout unchanged (`/opt/platypus/roles/<name>/`); every alias keeps working; Python 3.10–3.13; CI must stay green (lint, matrix, wheel smoke).
- All engine tests run without Docker: subprocess calls are monkeypatched (`SimpleNamespace` fakes, `tmp_path` state, style of `tests/test_caddy.py`).
- Lock constants: file `/opt/platypus/transition.lock` (module constant `LOCK_PATH`, monkeypatched in tests), content a single JSON line `{"pid", "target", "started_at"}` (UTC ISO), stale after `LOCK_STALE_SECONDS = 3600`.
- State backup: one generation at `/opt/platypus/state.yml.bak` (constant `STATE_BACKUP`, monkeypatched in tests).
- Precondition note: implementation may start on current `main` now; **tagging v0.2.1 waits for the author's v0.2.0 publish** (already scheduled).

## Review Focus

1. **Two concurrent switches:** the second must fail cleanly with an actionable message, not interleave (Task 1 `test_second_acquire_raises`, Task 2 `test_switch_lock_error_becomes_transition_error`).
2. **A crashed switch leaves the lock:** the next run must recover a dead-PID or over-age lock automatically, and refuse a live one with instructions (Task 1 stale tests, Task 2 stale-recovery path).
3. **Ctrl-C mid-transition:** rollback runs, the lock is released, and `KeyboardInterrupt` still propagates (Task 3 `test_keyboard_interrupt_rolls_back_and_releases`).
4. **New stack fails to start:** the partial new stack is brought down, the old Caddy route restored, old-role `rollback:` hooks run, old stack re-upped (Task 3 `test_rollback_composition`).
5. **Corrupt `state.yml`:** commands must not crash forever — the loader falls back to the `.bak` generation (Task 4 `test_load_falls_back_to_backup`).

---

### Task 1: Atomic lock module (`recipe/lock.py`)

**Files:**
- Create: `recipe/lock.py`
- Test: `tests/test_lock.py` (new)

**Interfaces:**
- Consumes: `recipe.model.PLATYPUS_DIR`.
- Produces:
  - `LOCK_PATH: Path = PLATYPUS_DIR / "transition.lock"`, `LOCK_STALE_SECONDS: int = 3600`
  - `class LockError(Exception)` — message must name the holder PID, target, and the recovery flag
  - `acquire(target: str, force: bool = False) -> dict` — `os.open(LOCK_PATH, O_CREAT | O_EXCL | O_WRONLY)`; on `FileExistsError` read the existing lock: `force` steals it; stale (dead PID or age > `LOCK_STALE_SECONDS`) steals it with a warning passed back; otherwise raises `LockError`. Returns the lock dict.
  - `release() -> None` — `LOCK_PATH.unlink(missing_ok=True)` (idempotent)
  - `read() -> dict | None` — parsed lock or `None` if absent/malformed
  - `_pid_alive(pid: int) -> bool` — `os.kill(pid, 0)`; `PermissionError` → True, other `OSError` → False

- [ ] **Step 1: Write the failing test `tests/test_lock.py`**

```python
"""Atomic transition lock: exclusivity, staleness, force, release."""

import json
import os

import pytest

from recipe import lock


def test_acquire_creates_lockfile(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    info = lock.acquire("minecraft-server")
    assert info["target"] == "minecraft-server"
    assert info["pid"] == os.getpid()
    data = json.loads(lock.LOCK_PATH.read_text(encoding="utf-8"))
    assert data["target"] == "minecraft-server"


def test_second_acquire_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.acquire("minecraft-server")
    with pytest.raises(lock.LockError):
        lock.acquire("pihole")


def test_stale_dead_pid_is_recovered(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text(
        json.dumps({"pid": 999999999, "target": "jellyfin", "started_at": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    info = lock.acquire("pihole")  # dead PID + ancient timestamp: must not raise
    assert info["target"] == "pihole"


def test_live_foreign_pid_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "target": "jellyfin",
                    "started_at": "2999-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    with pytest.raises(lock.LockError) as exc:
        lock.acquire("pihole")
    assert "jellyfin" in str(exc.value)  # names the holder and the flag
    assert "--force-unlock" in str(exc.value)


def test_force_steals_live_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "target": "jellyfin",
                    "started_at": "2999-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    assert lock.acquire("pihole", force=True)["target"] == "pihole"


def test_release_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "missing.lock")
    lock.release()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lock.py -v`
Expected: FAIL — `No module named 'recipe.lock'` at import.

- [ ] **Step 3: Implement `recipe/lock.py` per the Interfaces block**

Stale-steal ordering: check `_pid_alive(pid)` first (a dead holder cannot come back), then age. Steal = unlink + retry the `O_EXCL` open once. The stale recovery note ("stole stale lock from PID N") is returned in the lock dict under `"stole_from"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lock.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add recipe/lock.py tests/test_lock.py
git commit -m "recipe: atomic O_EXCL transition lock with stale recovery"
```

---

### Task 2: `switch()` adopts the file lock; state.yml lock removed

**Files:**
- Modify: `recipe/transition.py:159-211` (switch: stale-lock block + set_lock/release_lock calls)
- Modify: `recipe/state.py` (delete `set_lock`, `release_lock`, `is_lock_stale`; loader ignores a legacy `transition_lock` key; keep the `State.transition_lock` field for old-file tolerance but stop writing it)
- Modify: `recipe/cli.py` (status shows the file lock; `switch` gains `--force-unlock`)
- Test: `tests/test_transition.py` (new), extend `tests/test_cli_entries.py`

**Interfaces:**
- Consumes: Task 1's `lock.acquire/release/read/LockError/LOCK_PATH`.
- Produces: `switch(new_role_name: str, answers: dict | None = None, log: Log = print, force_unlock: bool = False) -> None`; `LockError` surfaces to the caller as `TransitionError` (existing message contract: one actionable line). `recipe.cli.main` accepts `--force-unlock` on the `switch` subcommand and passes it through.

- [ ] **Step 1: Write the failing tests**

`tests/test_transition.py` (engine harness used by Tasks 2–3):

```python
"""Transition engine tests — no Docker, subprocess calls are faked."""

import subprocess
from types import SimpleNamespace

import pytest

from recipe import lock, transition
from recipe.transition import TransitionError


def _fake_procs(monkeypatch, results=None):
    """Fake subprocess.run; returns list of (cmd, returncode) pairs seen."""
    seen = []
    defaults = {"docker": 0, "caddy": 0}

    def run(cmd, **kwargs):
        seen.append(list(cmd))
        rc = (results or {}).get(cmd[0], defaults.get(cmd[0], 0))
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return seen


def test_switch_lock_error_becomes_transition_error(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.acquire("other-role")
    monkeypatch.setattr(transition.state_mod, "load", lambda: transition.state_mod.State(
        schema_version="1", active=None, activated_at=None,
        transition_lock=None, history=[]))
    with pytest.raises(TransitionError) as exc:
        transition.switch("minecraft-server", answers={"a": 1})
    assert "--force-unlock" in str(exc.value)


def test_switch_releases_lock_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    seen = _fake_procs(monkeypatch)
    monkeypatch.setattr(transition.state_mod, "load", lambda: transition.state_mod.State(
        schema_version="1", active=None, activated_at=None,
        transition_lock=None, history=[]))
    monkeypatch.setattr(transition, "_execute", lambda *a, **k: None)
    transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)
    assert not lock.LOCK_PATH.exists()
    assert seen == []  # _execute faked: no docker touched
```

Append to `tests/test_cli_entries.py`:

```python
def test_recipe_switch_accepts_force_unlock(monkeypatch):
    recorded = {}

    def fake_switch(role, answers=None, log=print, force_unlock=False):
        recorded["role"] = role
        recorded["force_unlock"] = force_unlock
        return 0

    monkeypatch.setattr(recipe_cli, "switch", fake_switch)
    assert recipe_cli.main(["switch", "minecraft-server", "--force-unlock"]) == 0
    assert recorded == {"role": "minecraft-server", "force_unlock": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_transition.py tests/test_cli_entries.py -v`
Expected: FAIL — `switch()` still uses the state.yml lock (`set_lock`), and cli has no `--force-unlock`.

- [ ] **Step 3: Implement**

`transition.switch()`: replace the stale-lock block and `set_lock`/`release_lock` calls with `lock.acquire(new_role_name, force=force_unlock)` (wrap `lock.LockError` into `TransitionError(str(exc))`); `finally: lock.release()`. Delete `state_mod.set_lock/release_lock/is_lock_stale` and their call sites; `Phase 4` persists state via the existing save path only. `cli.py`: add `--force-unlock` to `p_switch`, pass `force_unlock=args.force_unlock`; `_cmd_status` prints the file lock via `lock.read()` (holder PID, target, age, and `--force-unlock` hint) instead of `state.transition_lock`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transition.py tests/test_cli_entries.py -v` then the full suite `python -m pytest -q`
Expected: PASS; no test anywhere still references `set_lock`.

- [ ] **Step 5: Commit**

```bash
git add recipe/transition.py recipe/state.py recipe/cli.py tests/test_transition.py tests/test_cli_entries.py
git commit -m "recipe: switch uses the file lock; --force-unlock flag"
```

---

### Task 3: Real rollback + interruption recovery

**Files:**
- Modify: `recipe/transition.py` (`_rollback` rewrite, `switch()` error paths, `_compose_down` strictness, SIGTERM context)
- Modify: `recipe/roles/storage-nextcloud/template.yml` (add `rollback:` hook mirroring its `pre_remove` maintenance:mode --on with `--off`)
- Test: `tests/test_transition.py` (extend)

**Interfaces:**
- Consumes: Task 2's switch shape; existing `caddy_mod.update(role, answers, log)`, `_run_hooks(commands, log, answers)`, `_compose_down`, `_compose_up`.
- Produces:
  - `_rollback(state: State, new_role: str, log: Log) -> None` — order pinned: (1) best-effort `_compose_down(new_role)` if its compose file exists, (2) `caddy_mod.update(state.active, old_answers, log)` restoring the old route, (3) old template's `hooks.rollback` run with old answers, (4) `_compose_up(state.active)`. Rollback failures log and continue to the next step; nothing in rollback raises.
  - `_interruptible()` context manager — installs `signal.signal(SIGTERM, handler)` where `handler` raises `TransitionInterrupted` (a `BaseException` subclass defined in `transition.py`); restores the previous handler on exit; on platforms without SIGTERM delivery (Windows) it still installs harmlessly.
  - `_compose_down(role, log, strict: bool = False)` — with `strict=True` a nonzero exit raises `TransitionError` (Phase 1 stop becomes strict); rollback's own down stays best-effort.

- [ ] **Step 1: Write the failing tests (append to `tests/test_transition.py`)**

```python
def test_rollback_composition(tmp_path, monkeypatch):
    state = transition.state_mod.State(
        schema_version="1", active="pihole", activated_at=None,
        transition_lock=None, history=[])
    order = []
    monkeypatch.setattr(transition, "_compose_down",
                        lambda role, log, strict=False: order.append(("down", role)))
    monkeypatch.setattr(transition.caddy_mod, "update",
                        lambda role, answers, log: order.append(("caddy", role)))
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: order.append(("up", role)))
    monkeypatch.setattr(transition, "_run_hooks",
                        lambda cmds, log, answers=None: order.append(("hooks", list(cmds))))

    transition._rollback(state, "minecraft-server", lambda m: None)

    assert order == [
        ("down", "minecraft-server"),   # partial new stack removed
        ("caddy", "pihole"),             # old route restored
        ("hooks", transition._load_template("pihole").get("hooks", {}).get("rollback", [])),
        ("up", "pihole"),                # old stack restored
    ]


def test_keyboard_interrupt_rolls_back_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: transition.state_mod.State(
        schema_version="1", active=None, activated_at=None,
        transition_lock=None, history=[]))
    rolled = []
    monkeypatch.setattr(transition, "_execute",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(transition, "_rollback", lambda s, r, log: rolled.append(r))

    with pytest.raises(KeyboardInterrupt):
        transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)

    assert rolled == ["minecraft-server"]
    assert not lock.LOCK_PATH.exists()


def test_compose_down_strict_raises(tmp_path, monkeypatch):
    import subprocess as sp
    from types import SimpleNamespace

    monkeypatch.setattr(transition, "PLATYPUS_ROLES_DIR", tmp_path)
    compose = tmp_path / "minecraft-server" / "docker-compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n", encoding="utf-8")

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="docker: boom")

    monkeypatch.setattr(sp, "run", run)

    logs: list[str] = []
    with pytest.raises(TransitionError):
        transition._compose_down("minecraft-server", logs.append, strict=True)
    transition._compose_down("minecraft-server", logs.append, strict=False)  # no raise

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_transition.py -v`
Expected: FAIL — `_rollback` still only re-ups the old stack; `KeyboardInterrupt` bypasses the handler.

- [ ] **Step 3: Implement**

`switch()` error paths become:

```python
lock_info = lock.acquire(new_role_name, force=force_unlock)
try:
    with _interruptible():
        _execute(state, new_role_name, new_template, answers, log)
except BaseException as exc:
    log(f"\n[ERROR] {type(exc).__name__}: {exc}")
    log("Rolling back…")
    _rollback(state, new_role_name, log)
    raise (TransitionError(str(exc)) if isinstance(exc, Exception) else exc) from exc
finally:
    lock.release()
```

`_execute` Phase 1 calls `_compose_down(cur, log, strict=True)`. In `recipe/roles/storage-nextcloud/template.yml`, add the `rollback:` hook mirroring the existing `pre_remove` `occ maintenance:mode --on` command with `--off`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transition.py -v` then `python -m pytest -q`
Expected: PASS; yamllint clean on the edited template (`python -m yamllint recipe/roles/storage-nextcloud/`).

- [ ] **Step 5: Commit**

```bash
git add recipe/transition.py recipe/roles/storage-nextcloud/template.yml tests/test_transition.py
git commit -m "recipe: real rollback with interruption recovery; strict phase-1 stop"
```

---

### Task 4: Durable state and answers

**Files:**
- Modify: `recipe/state.py` (save: fsync + backup; load: `.bak` fallback)
- Modify: `recipe/renderer.py` (`save_answers` gains the same fsync+tmp+replace discipline — atomic helper shared with state)
- Modify: `recipe/transition.py` (`_execute`: move `save_answers` from Phase 2 to Phase 4, after `_compose_up` and caddy succeed)
- Test: `tests/test_transition.py`, new `tests/test_state_durability.py`

**Interfaces:**
- Consumes: `STATE_FILE`, `save/load` signatures (unchanged).
- Produces: `recipe/state.py` gains `STATE_BACKUP: Path` and `atomic_write(path: Path, data: str) -> None` (tmp file + `flush` + `os.fsync` + `replace`, copying the previous generation to `path.with_suffix(path.suffix + ".bak")` when it exists); `renderer.save_answers` uses the same discipline. `save_answers` stays callable where Phase 4 calls it.

- [ ] **Step 1: Write the failing tests**

New `tests/test_state_durability.py`:

```python
"""State/answers durability: fsync+backup writes, corrupt-file fallback."""

import yaml

from recipe import state as state_mod
from recipe import renderer


def test_atomic_write_creates_backup(tmp_path, monkeypatch):
    target = tmp_path / "state.yml"
    target.write_text("old: 1\n", encoding="utf-8")
    state_mod.atomic_write(target, "new: 2\n")
    assert target.read_text(encoding="utf-8") == "new: 2\n"
    assert (tmp_path / "state.yml.bak").read_text(encoding="utf-8") == "old: 1\n"


def test_load_falls_back_to_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    monkeypatch.setattr(state_mod, "STATE_BACKUP", tmp_path / "state.yml.bak")
    good = {"schema_version": "1", "active": None, "activated_at": None,
            "transition_lock": None, "history": []}
    state_mod.atomic_write(tmp_path / "state.yml.bak", yaml.safe_dump(good))
    (tmp_path / "state.yml").write_text("{corrupt: [", encoding="utf-8")
    st = state_mod.load()
    assert st.active is None  # loaded from the backup generation, no crash
```

Append to `tests/test_transition.py`:

```python
def test_answers_saved_only_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: transition.state_mod.State(
        schema_version="1", active=None, activated_at=None,
        transition_lock=None, history=[]))
    saved = []
    monkeypatch.setattr(transition.renderer, "save_answers",
                        lambda role, answers: saved.append(role) or tmp_path / "answers.yml")
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: (_ for _ in ()).throw(transition.TransitionError("up failed")))

    with pytest.raises(transition.TransitionError):
        transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)

    assert saved == []  # typo'd answers from a failed switch are NOT persisted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_state_durability.py tests/test_transition.py -v`
Expected: FAIL — no `atomic_write`; `save_answers` still called in Phase 2; loader has no fallback.

- [ ] **Step 3: Implement**

`state.py`: `atomic_write` per Interfaces; `save()` routes through it; `load()` catches `yaml.YAMLError` (and `KeyError`/`ValueError`) on the primary file, logs a warning to stderr, and retries once against `STATE_BACKUP` — if that is also broken, the original error propagates. `renderer.save_answers` uses the same tmp+fsync+replace discipline (no backup generation for answers — the in-memory dict is the source during a transition). `transition._execute`: Phase 2 renders the compose from the in-memory `answers` and no longer saves them; Phase 4 (after `caddy_mod.update`) calls `save_answers(new_role, answers)` before persisting state.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state_durability.py tests/test_transition.py -v` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add recipe/state.py recipe/renderer.py recipe/transition.py tests/test_state_durability.py tests/test_transition.py
git commit -m "recipe: fsync+backup state writes, answers only saved on success"
```

---

### Task 5: Release prep — 0.2.1

**Files:**
- Modify: `pyproject.toml:4` (`version = "0.2.1"`)
- Modify: `tests/test_packaging.py:18` (version assert) and the `--version` regex in `tests/test_platypus_cli.py:66`
- Test: existing suites

**Interfaces:**
- Consumes: all previous tasks (green suite).
- Produces: version 0.2.1 everywhere (metadata-sourced `__version__`s follow automatically).

- [ ] **Step 1: Update the two version assertions**

`tests/test_packaging.py`: `assert PYPROJECT["project"]["version"] == "0.2.1"`; `tests/test_platypus_cli.py`: `re.match(r"platypus (0\.2\.1|unknown)\b", ...)`.

- [ ] **Step 2: Re-install editable and run the full suite**

Run: `python -m pip install -e . && python -m pytest -q`
Expected: PASS (all ~85); `python -c "from platypus_cli.cli import _version; print(_version())"` → `0.2.1`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml tests/test_packaging.py tests/test_platypus_cli.py
git commit -m "release: 0.2.1 (trustworthy transition engine)"
```

- [ ] **Step 4: Push the branch and confirm CI green (lint incl. `bash -n`, 3.10–3.13 matrix, wheel smoke)**

Fix anything red before reporting done — the author tags `v0.2.1` only after `v0.2.0` is published, per the rollout note.
