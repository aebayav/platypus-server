"""Dashboard module-state reader: v2 mounted set, v1 fallback, robustness."""

import yaml

from dashboard import recipe_state


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_reads_v2_mounted(tmp_path):
    _write(tmp_path / "state.yml",
           {"schema_version": "2", "mounted": ["pihole", "syncthing"], "history": []})
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [m["name"] for m in out["mounted"]] == ["pihole", "syncthing"]
    assert out["dormant"] == []


def test_v1_fallback_active_becomes_single_mounted(tmp_path):
    _write(tmp_path / "state.yml",
           {"schema_version": "1", "active": "jellyfin", "history": []})
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [m["name"] for m in out["mounted"]] == ["jellyfin"]


def test_missing_and_corrupt_files_do_not_raise(tmp_path):
    assert recipe_state.read(tmp_path / "nope.yml", tmp_path / "roles")["mounted"] == []
    (tmp_path / "state.yml").write_text("{corrupt", encoding="utf-8")
    assert recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")["mounted"] == []


def test_dormant_lists_unmounted_runtime_dirs(tmp_path):
    _write(tmp_path / "state.yml", {"schema_version": "2", "mounted": ["pihole"], "history": []})
    rdir = tmp_path / "roles" / "minecraft-server"
    (rdir / "data").mkdir(parents=True)
    (rdir / "answers.yml").write_text("role: minecraft-server\n", encoding="utf-8")
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [d["name"] for d in out["dormant"]] == ["minecraft-server"]
    assert out["dormant"][0]["configured"] is True
