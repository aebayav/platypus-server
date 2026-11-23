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
