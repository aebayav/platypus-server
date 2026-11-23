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
