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


def _blank_state():
    return transition.state_mod.State(
        schema_version="1", active=None, activated_at=None,
        transition_lock=None, history=[])


def test_switch_lock_error_becomes_transition_error(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.acquire("other-role")
    monkeypatch.setattr(transition.state_mod, "load", _blank_state)
    monkeypatch.setattr(transition, "_execute", lambda *a, **k: None)
    with pytest.raises(TransitionError) as exc:
        transition.switch("minecraft-server", answers={"a": 1})
    assert "--force-unlock" in str(exc.value)


def test_switch_releases_lock_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "STATE_FILE", tmp_path / "state.yml")
    saves = []
    monkeypatch.setattr(transition.state_mod, "save", lambda st: saves.append(1))
    seen = _fake_procs(monkeypatch)
    monkeypatch.setattr(transition.state_mod, "load", _blank_state)
    monkeypatch.setattr(transition, "_execute", lambda *a, **k: None)
    transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)
    assert not lock.LOCK_PATH.exists()
    assert saves == []  # no state.yml lock writes while _execute is faked
    assert seen == []  # _execute faked: no docker touched


def test_rollback_composition(tmp_path, monkeypatch):
    state = transition.state_mod.State(
        schema_version="1", active="pihole", activated_at=None,
        transition_lock=None, history=[])
    order = []
    monkeypatch.setattr(transition, "load_answers", lambda r: {"x": 1})
    monkeypatch.setattr(transition, "_compose_down",
                        lambda role, log, strict=False: order.append(("down", role)))
    monkeypatch.setattr(transition.caddy_mod, "update",
                        lambda role, answers, log: order.append(("caddy", role)))
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: order.append(("up", role)))
    monkeypatch.setattr(transition, "_run_hooks",
                        lambda cmds, log, answers=None: order.append(("hooks", list(cmds))))

    transition._rollback(state, "pihole", "minecraft-server", lambda m: None)

    assert order == [
        ("down", "minecraft-server"),   # partial new stack removed
        ("caddy", "pihole"),             # old route restored
        ("hooks", transition._load_template("pihole").get("hooks", {}).get("rollback", [])),
        ("up", "pihole"),                # old stack restored
    ]


def test_rollback_step_failure_continues(tmp_path, monkeypatch):
    state = transition.state_mod.State(
        schema_version="1", active="pihole", activated_at=None,
        transition_lock=None, history=[])
    order = []
    monkeypatch.setattr(transition, "load_answers", lambda r: {"x": 1})
    monkeypatch.setattr(transition, "_compose_down",
                        lambda role, log, strict=False: order.append(("down", role)))
    monkeypatch.setattr(transition.caddy_mod, "update",
                        lambda role, answers, log: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(transition, "_run_hooks",
                        lambda cmds, log, answers=None: order.append(("hooks", list(cmds))))
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: order.append(("up", role)))

    transition._rollback(state, "pihole", "minecraft-server", lambda m: None)

    # A second Ctrl-C during rollback must not abort the remaining steps.
    assert order == [("down", "minecraft-server"), ("hooks", []), ("up", "pihole")]


def test_rollback_targets_previous_role_when_save_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition, "PLATYPUS_ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(transition.state_mod, "load", lambda: transition.state_mod.State(
        schema_version="1", active="jellyfin", activated_at=None,
        transition_lock=None, history=[]))
    calls = []
    monkeypatch.setattr(transition, "_rollback",
                        lambda s, prev, new, log: calls.append((prev, new)))
    monkeypatch.setattr(transition, "write_compose", lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: tmp_path / "a.yml")
    monkeypatch.setattr(transition, "_compose_up", lambda role, log: None)
    monkeypatch.setattr(transition.caddy_mod, "update", lambda role, answers, log: None)

    def explode(state):
        raise RuntimeError("disk full")

    monkeypatch.setattr(transition.state_mod, "save", explode)

    with pytest.raises(TransitionError):
        transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)

    # Rollback must restore the role active BEFORE the switch mutated state.
    assert calls == [("jellyfin", "minecraft-server")]


def test_keyboard_interrupt_rolls_back_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", _blank_state)
    rolled = []
    monkeypatch.setattr(transition, "_execute",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(transition, "_rollback", lambda s, prev, r, log: rolled.append(r))

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


def test_answers_saved_only_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", _blank_state)
    saved = []
    ups = []
    monkeypatch.setattr(transition, "save_answers",
                        lambda role, answers: saved.append(role) or tmp_path / "answers.yml")
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "docker-compose.yml")
    monkeypatch.setattr(transition, "_run_hooks",
                        lambda cmds, log, answers=None: None)
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: ups.append(role)
                        or (_ for _ in ()).throw(transition.TransitionError("up failed")))

    with pytest.raises(transition.TransitionError):
        transition.switch("minecraft-server", answers={"a": 1}, log=lambda m: None)

    assert ups == ["minecraft-server"]  # Phase 3 was actually reached
    assert saved == []  # typo'd answers from a failed switch are NOT persisted
