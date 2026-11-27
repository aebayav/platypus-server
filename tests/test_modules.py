"""Packaged module templates: discovery, packaged-first resolution, fallback."""

import pytest

import recipe.model as model

EXPECTED_ROLES = [
    "assetto-corsa",
    "jellyfin",
    "minecraft-server",
    "monitoring",
    "pihole",
    "storage-nextcloud",
    "storage-samba",
    "syncthing",
]


def test_builtin_roles_match_readme():
    assert model.builtin_roles() == EXPECTED_ROLES


def test_every_builtin_role_ships_both_files():
    for name in model.builtin_roles():
        d = model.role_dir(name)
        assert (d / "template.yml").is_file(), name
        assert (d / "questions.yml").is_file(), name


def test_role_dir_prefers_packaged_dir(tmp_path, monkeypatch):
    packaged = tmp_path / "packaged"
    (packaged / "demo").mkdir(parents=True)
    (packaged / "demo" / "template.yml").write_text("a: 1\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "template.yml").write_text("a: 2\n", encoding="utf-8")
    monkeypatch.setattr(model, "PACKAGED_MODULES_DIR", packaged)
    monkeypatch.setattr(model, "REPO_ROLES_DIR", repo)
    assert model.role_dir("demo") == packaged / "demo"


def test_role_dir_falls_back_to_repo_dir(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "template.yml").write_text("a: 1\n", encoding="utf-8")
    monkeypatch.setattr(model, "PACKAGED_MODULES_DIR", tmp_path / "empty")
    monkeypatch.setattr(model, "REPO_ROLES_DIR", repo)
    assert model.role_dir("demo") == repo / "demo"


def test_role_dir_unknown_role_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "PACKAGED_MODULES_DIR", tmp_path / "a")
    monkeypatch.setattr(model, "REPO_ROLES_DIR", tmp_path / "b")
    with pytest.raises(FileNotFoundError):
        model.role_dir("nope")
