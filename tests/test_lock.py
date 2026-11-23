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


def test_acquire_creates_missing_parent_dir(tmp_path, monkeypatch):
    # A truly fresh server has no /opt/platypus yet — the first lock
    # acquisition must create it, not fail with ENOENT.
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "fresh" / "transition.lock")
    assert lock.acquire("minecraft-server")["target"] == "minecraft-server"


def test_release_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "missing.lock")
    lock.release()  # must not raise


def test_age_alone_does_not_steal_live_lock(tmp_path, monkeypatch):
    # Ruling from review: only a DEAD holder is auto-recovered.  A live
    # transition that is merely old (slow image pull) must not be stolen
    # by an ordinary second switch — --force-unlock is the override.
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "target": "jellyfin",
                    "started_at": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    with pytest.raises(lock.LockError) as exc:
        lock.acquire("pihole")
    assert "--force-unlock" in str(exc.value)


def test_force_recovers_unreadable_lock(tmp_path, monkeypatch):
    # Crash window: process died between O_EXCL create and the JSON write.
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text("", encoding="utf-8")
    assert lock.acquire("pihole", force=True)["target"] == "pihole"


def test_unreadable_lock_without_force_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(lock, "LOCK_REREAD_SECONDS", 0)
    lock.LOCK_PATH.write_text("", encoding="utf-8")
    with pytest.raises(lock.LockError) as exc:
        lock.acquire("pihole")
    assert "unreadable" in str(exc.value)
    assert "--force-unlock" in str(exc.value)


def test_racing_retry_becomes_lock_error(tmp_path, monkeypatch):
    # A rival steals the lock between our read and our create: the raw
    # FileExistsError must surface as LockError naming the rival, never
    # as an unhandled traceback.
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")

    def rival(info):
        lock.LOCK_PATH.write_text(
            json.dumps({"pid": os.getpid(), "target": "rival",
                        "started_at": "2999-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        raise FileExistsError(str(lock.LOCK_PATH))

    monkeypatch.setattr(lock, "_write_locked_file", rival)
    with pytest.raises(lock.LockError) as exc:
        lock.acquire("pihole")
    assert "rival" in str(exc.value)


def test_release_skips_foreign_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid() + 1, "target": "other",
                    "started_at": "2999-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    lock.release()
    assert lock.LOCK_PATH.exists()  # not ours: left alone

    lock.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "target": "mine",
                    "started_at": "2999-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    lock.release()
    assert not lock.LOCK_PATH.exists()  # ours: removed
