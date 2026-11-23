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
