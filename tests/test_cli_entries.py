"""Entry-point refactors: every tool main() accepts argv."""

import pytest

from dashboard.app import parse_dashboard_args
from recipe import cli as recipe_cli
from zero2server import cli as z2s_cli


def test_dashboard_parse_args_flags():
    ns = parse_dashboard_args(["--host", "127.0.0.1", "--port", "6000"])
    assert ns.host == "127.0.0.1"
    assert ns.port == 6000


def test_dashboard_parse_args_env_defaults(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOST", "10.0.0.5")
    monkeypatch.setenv("DASHBOARD_PORT", "6060")
    ns = parse_dashboard_args([])
    assert ns.host == "10.0.0.5"
    assert ns.port == 6060


def test_dashboard_parse_args_hard_defaults(monkeypatch):
    monkeypatch.delenv("DASHBOARD_HOST", raising=False)
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    ns = parse_dashboard_args([])
    assert ns.host == "0.0.0.0"
    assert ns.port == 5050


def test_recipe_main_status_returns_zero(capsys):
    assert recipe_cli.main(["status"]) == 0
    assert "mounted" in capsys.readouterr().out.lower()


def test_recipe_main_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        recipe_cli.main(["--help"])
    assert exc.value.code == 0


def test_recipe_main_unknown_command_exits_two():
    with pytest.raises(SystemExit) as exc:
        recipe_cli.main(["bogus"])
    assert exc.value.code == 2


def test_zero2server_main_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        z2s_cli.main(["--help"])
    assert exc.value.code == 0


def test_recipe_switch_accepts_force_unlock(monkeypatch):
    recorded = {}

    def fake_switch(role, answers=None, log=print, force_unlock=False):
        recorded["role"] = role
        recorded["force_unlock"] = force_unlock
        return 0

    monkeypatch.setattr(recipe_cli, "switch", fake_switch)
    # Saved answers exist: _cmd_switch must take the reuse path and never
    # fall into the interactive question form (stdin is captured in CI).
    monkeypatch.setattr(recipe_cli, "load_answers", lambda role: {"a": 1})
    assert recipe_cli.main(["switch", "minecraft-server", "--force-unlock"]) == 0
    assert recorded == {"role": "minecraft-server", "force_unlock": True}


def test_recipe_switch_ctrl_c_prints_clean_message(monkeypatch, capsys):
    def fake_switch(role, answers=None, log=print, force_unlock=False):
        raise KeyboardInterrupt()

    monkeypatch.setattr(recipe_cli, "switch", fake_switch)
    monkeypatch.setattr(recipe_cli, "load_answers", lambda role: {"a": 1})
    assert recipe_cli.main(["switch", "syncthing"]) == 130
    err = capsys.readouterr().err
    assert "Interrupted" in err
    assert "Traceback" not in err
