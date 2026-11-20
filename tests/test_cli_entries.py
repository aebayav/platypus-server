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
    assert "role" in capsys.readouterr().out.lower()


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
