"""The unified `platypus` dispatcher: routing, usage, version."""

import re

import pytest

import platypus_cli.cli as cli


def test_subcommand_table():
    assert set(cli.SUBCOMMANDS) == {
        "doctor", "setup", "dashboard", "switch", "status", "generate",
    }


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["doctor", "--target", "vps"], ("doctor", "main", None, ["--target", "vps"])),
        (["setup", "--mode", "simple"], ("tui.app", "main", None, ["--mode", "simple"])),
        (["dashboard", "--port", "6000"], ("dashboard.app", "main", None, ["--port", "6000"])),
        (["switch", "minecraft-server"], ("recipe.cli", "main", "switch", ["minecraft-server"])),
        (["status"], ("recipe.cli", "main", "status", [])),
        (["generate", "--run"], ("zero2server.cli", "main", None, ["--run"])),
    ],
)
def test_forwards_argv_to_tool(argv, expected, monkeypatch):
    recorded = []

    def fake_run(module_name, func_name, prefix, rest):
        recorded.append((module_name, func_name, prefix, rest))
        return 0

    monkeypatch.setattr(cli, "_run", fake_run)
    assert cli.main(argv) == 0
    assert recorded == [expected]


def test_no_args_prints_usage(capsys):
    assert cli.main([]) == 0
    assert "usage: platypus" in capsys.readouterr().out


def test_unknown_command_returns_two(capsys):
    assert cli.main(["frobnicate"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert re.match(r"platypus (0\.2\.1|unknown)\b", capsys.readouterr().out)


def test_help_lists_every_subcommand(capsys):
    cli.main(["--help"])
    out = capsys.readouterr().out
    for name in cli.SUBCOMMANDS:
        assert name in out
