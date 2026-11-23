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


def test_load_survives_list_shaped_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    monkeypatch.setattr(state_mod, "STATE_BACKUP", tmp_path / "state.yml.bak")
    good = {"schema_version": "1", "active": "jellyfin", "activated_at": None,
            "transition_lock": None, "history": []}
    state_mod.atomic_write(tmp_path / "state.yml.bak", yaml.safe_dump(good))
    (tmp_path / "state.yml").write_text("- just\n- a list\n", encoding="utf-8")
    st = state_mod.load()
    assert st.active == "jellyfin"  # non-dict YAML must not crash every command


def test_load_uses_backup_when_primary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    monkeypatch.setattr(state_mod, "STATE_BACKUP", tmp_path / "state.yml.bak")
    good = {"schema_version": "1", "active": "jellyfin", "activated_at": None,
            "transition_lock": None, "history": []}
    state_mod.atomic_write(tmp_path / "state.yml.bak", yaml.safe_dump(good))
    st = state_mod.load()
    assert st.active == "jellyfin"  # not a silent blank: the backup generation
    assert (tmp_path / "state.yml").exists()  # primary restored from backup


def test_save_no_longer_writes_transition_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    st = state_mod.State(
        schema_version="1", active="pihole", activated_at=None,
        transition_lock={"pid": 123, "role": "old"}, history=[])
    state_mod.save(st)
    data = yaml.safe_load((tmp_path / "state.yml").read_text(encoding="utf-8"))
    assert "transition_lock" not in data  # the file lock owns locking now
