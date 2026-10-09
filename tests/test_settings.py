"""Tests for tui.settings: resolution, persistence and validation."""

import pytest

from tui.settings import Settings, load_config, resolve, save_config
from tui.tasks import SIMPLE_HIDDEN, setup_order, visible_tasks


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.mode == "full"
    assert settings.target == "home"
    assert settings.simple is False


def test_settings_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        Settings(mode="chaos")
    with pytest.raises(ValueError):
        Settings(target="cloud")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "nested" / "config.yml"
    saved = save_config(Settings(mode="simple", target="vps"), path=path)
    assert saved == path
    assert load_config(path) == {"mode": "simple", "target": "vps"}


def test_load_missing_file_returns_empty(tmp_path) -> None:
    assert load_config(tmp_path / "missing.yml") == {}


# ---------------------------------------------------------------------------
# Resolution precedence: explicit args > env vars > config file > defaults
# ---------------------------------------------------------------------------


def test_resolve_uses_config_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PLATYPUS_MODE", raising=False)
    monkeypatch.delenv("PLATYPUS_TARGET", raising=False)
    path = tmp_path / "config.yml"
    save_config(Settings(mode="simple", target="home"), path=path)
    assert resolve(path=path) == Settings(mode="simple", target="home")


def test_resolve_env_beats_config_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PLATYPUS_MODE", raising=False)
    monkeypatch.delenv("PLATYPUS_TARGET", raising=False)
    path = tmp_path / "config.yml"
    save_config(Settings(mode="simple", target="home"), path=path)
    monkeypatch.setenv("PLATYPUS_MODE", "full")
    monkeypatch.setenv("PLATYPUS_TARGET", "vps")
    assert resolve(path=path) == Settings(mode="full", target="vps")


def test_resolve_explicit_args_beat_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PLATYPUS_MODE", "full")
    monkeypatch.setenv("PLATYPUS_TARGET", "vps")
    assert resolve(mode="simple", target="home", path=tmp_path / "none.yml") == (
        Settings(mode="simple", target="home")
    )


def test_resolve_defaults_without_any_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PLATYPUS_MODE", raising=False)
    monkeypatch.delenv("PLATYPUS_TARGET", raising=False)
    assert resolve(path=tmp_path / "none.yml") == Settings()


# ---------------------------------------------------------------------------
# Task filtering by target and mode
# ---------------------------------------------------------------------------


def test_visible_tasks_full_home_shows_home_relevant() -> None:
    ids = {task.id for task in visible_tasks("home", "full")}
    assert "tailscale" in ids  # home-server remote access
    assert "nginx" not in ids  # vps-only
    assert "certbot" not in ids  # vps-only
    assert "wireguard" in ids  # advanced, but visible in full mode


def test_visible_tasks_simple_hides_advanced() -> None:
    ids = {task.id for task in visible_tasks("vps", "simple")}
    for hidden in SIMPLE_HIDDEN:
        assert hidden not in ids
    for core in ("docker", "caddy", "ssh", "ufw", "sysupdate"):
        assert core in ids
    assert "tailscale" not in ids  # home-only


def test_setup_order_excludes_vpn_and_backup() -> None:
    ids = {task.id for task in setup_order("home", "full")}
    assert "tailscale" not in ids
    assert "wireguard" not in ids
    assert "backup" not in ids
    assert "docker" in ids


def test_setup_order_simple_is_shorter() -> None:
    assert len(setup_order("home", "simple")) < len(setup_order("home", "full"))
    assert len(setup_order("vps", "simple")) < len(setup_order("vps", "full"))
