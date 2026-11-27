"""Tests for state-aware `platypus backup` and `platypus restore`."""

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipe import backup, state as state_mod


def _seed_runtime(platypus_dir: Path) -> None:
    roles_dir = platypus_dir / "roles" / "minecraft-server"
    (roles_dir / "data").mkdir(parents=True, exist_ok=True)
    (roles_dir / "answers.yml").write_text("port: 25565\n", encoding="utf-8")
    (roles_dir / "data" / "level.dat").write_bytes(b"world-bytes-123")
    st = state_mod.State(schema_version="2", mounted=["minecraft-server"], history=[])
    state_mod.save(st)


def test_backup_and_restore_roundtrip_runs_hooks_and_verifies_checksums(tmp_path, monkeypatch):
    platypus_dir = tmp_path / "platypus"
    dest_dir = tmp_path / "backups"
    monkeypatch.setattr(backup, "PLATYPUS_DIR", platypus_dir)
    monkeypatch.setattr(backup, "DEFAULT_BACKUP_DEST", dest_dir)
    _seed_runtime(platypus_dir)

    hooks_called = []
    monkeypatch.setattr(
        backup,
        "_load_module_hooks",
        lambda name: {
            "pre_backup": ["save-all {answers[port]}"],
            "post_backup": ["save-on"],
        },
    )
    monkeypatch.setattr(
        backup,
        "_exec_shell",
        lambda cmd: hooks_called.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    archive = backup.create_backup(dest=dest_dir)
    assert archive.is_file()
    assert hooks_called == ["save-all 25565", "save-on"]
    assert (platypus_dir / "last_backup.json").is_file()

    # Wipe runtime data and restore into a clean target
    restore_target = tmp_path / "restored_platypus"
    monkeypatch.setattr(backup, "PLATYPUS_DIR", restore_target)
    restored = backup.restore_backup(archive)
    assert "minecraft-server" in restored["modules"]
    assert (restore_target / "roles" / "minecraft-server" / "data" / "level.dat").read_bytes() == b"world-bytes-123"
    assert (restore_target / "state.yml").is_file()


def test_post_backup_hook_still_runs_when_archive_fails(tmp_path, monkeypatch):
    platypus_dir = tmp_path / "platypus"
    monkeypatch.setattr(backup, "PLATYPUS_DIR", platypus_dir)
    _seed_runtime(platypus_dir)

    hooks_called = []
    monkeypatch.setattr(
        backup,
        "_load_module_hooks",
        lambda name: {"pre_backup": ["maint-on"], "post_backup": ["maint-off"]},
    )
    monkeypatch.setattr(
        backup,
        "_exec_shell",
        lambda cmd: hooks_called.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        backup,
        "_write_tar_archive",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(backup.BackupError):
        backup.create_backup(dest=tmp_path / "out")

    assert hooks_called == ["maint-on", "maint-off"]


def test_restore_rejects_corrupted_checksum_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "PLATYPUS_DIR", tmp_path / "target")

    # 1. Path traversal tar member must be rejected
    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tf:
        payload = b"pwned"
        ti = tarfile.TarInfo(name="../outside.txt")
        ti.size = len(payload)
        tf.addfile(ti, io.BytesIO(payload))

    with pytest.raises(backup.BackupError, match="Unsafe path"):
        backup.restore_backup(evil_tar)

    # 2. Tampered file hash mismatch must be rejected
    tampered = tmp_path / "tampered.tar.gz"
    manifest = {
        "schema_version": "1",
        "created_at": "2026-11-27T00:00:00+00:00",
        "modules": ["pihole"],
        "files": {"roles/pihole/answers.yml": "0" * 64},
    }
    with tarfile.open(tampered, "w:gz") as tf:
        m_bytes = json.dumps(manifest).encode("utf-8")
        mi = tarfile.TarInfo(name="manifest.json")
        mi.size = len(m_bytes)
        tf.addfile(mi, io.BytesIO(m_bytes))

        f_bytes = b"real-content"
        fi = tarfile.TarInfo(name="roles/pihole/answers.yml")
        fi.size = len(f_bytes)
        tf.addfile(fi, io.BytesIO(f_bytes))

    with pytest.raises(backup.BackupError, match="checksum"):
        backup.restore_backup(tampered)


def test_restic_backend_invokes_restic_cli(tmp_path, monkeypatch):
    platypus_dir = tmp_path / "platypus"
    monkeypatch.setattr(backup, "PLATYPUS_DIR", platypus_dir)
    _seed_runtime(platypus_dir)
    monkeypatch.setattr(backup, "_load_module_hooks", lambda name: {})

    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="snapshot abc123 saved\n", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    monkeypatch.setenv("RESTIC_PASSWORD", "secret")

    rc = backup.main_backup(
        ["--backend", "restic", "--repo", str(tmp_path / "restic-repo"), "--keep", "5"]
    )
    assert rc == 0
    assert any(c[0] == "restic" and "backup" in c for c in cmds)
    assert any(c[0] == "restic" and "forget" in c for c in cmds)


def test_backup_sh_includes_opt_platypus_by_default():
    text = Path("scripts/backup.sh").read_text(encoding="utf-8")
    assert "/opt/platypus" in text
