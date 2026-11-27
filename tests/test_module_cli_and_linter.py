"""Tests for Phase 3 module linter and `platypus module` CLI."""

from pathlib import Path

import pytest
import yaml

from recipe import linter, module_cli


def test_all_builtin_modules_pass_linter():
    report = linter.lint_all_modules()
    assert report, "expected built-in modules to be discovered"
    failures = {name: errs for name, errs in report.items() if errs}
    assert failures == {}


def test_linter_catches_undeclared_compose_port(tmp_path):
    mod = tmp_path / "demo-app"
    mod.mkdir()
    (mod / "template.yml").write_text(
        yaml.safe_dump(
            {
                "role": "demo-app",
                "version": "1.0",
                "description": "Demo",
                "weight": "companion",
                "ports": ["8080/tcp"],
                "compose_template": (
                    "services:\n"
                    "  app:\n"
                    "    image: nginx:alpine\n"
                    "    ports:\n"
                    '      - "8080:80"\n'
                    '      - "9090:90/udp"\n'
                ),
            }
        ),
        encoding="utf-8",
    )
    (mod / "questions.yml").write_text(
        yaml.safe_dump({"role": "demo-app", "title": "Demo", "questions": []}),
        encoding="utf-8",
    )
    errs = linter.lint_module_dir(mod)
    assert any("9090/udp" in e for e in errs)


def test_linter_catches_duplicate_question_id_and_bad_validate(tmp_path):
    mod = tmp_path / "bad-q"
    mod.mkdir()
    (mod / "template.yml").write_text(
        yaml.safe_dump(
            {
                "role": "bad-q",
                "version": "1.0",
                "description": "Bad questions",
                "weight": "main",
                "ports": ["{answers[port]}/tcp"],
                "compose_template": (
                    "services:\n"
                    "  app:\n"
                    "    image: alpine:3.20\n"
                    "    ports:\n"
                    '      - "{answers[port]}:80"\n'
                    "    environment:\n"
                    '      EXTRA: "{answers[missing_id]}"\n'
                ),
            }
        ),
        encoding="utf-8",
    )
    (mod / "questions.yml").write_text(
        yaml.safe_dump(
            {
                "role": "bad-q",
                "title": "Bad",
                "questions": [
                    {"id": "port", "label": "Port", "type": "integer", "validate": "9000-1000"},
                    {"id": "port", "label": "Dup", "type": "text"},
                ],
            }
        ),
        encoding="utf-8",
    )
    errs = linter.lint_module_dir(mod)
    assert any("duplicate" in e.lower() for e in errs)
    assert any("validate" in e.lower() for e in errs)
    assert any("missing_id" in e for e in errs)


def test_module_init_scaffolds_valid_module_and_lint_cli_passes(tmp_path, capsys):
    rc = module_cli.main(["init", "my-service", "--dir", str(tmp_path)])
    assert rc == 0
    target = tmp_path / "my-service"
    assert (target / "template.yml").is_file()
    assert (target / "questions.yml").is_file()
    assert linter.lint_module_dir(target) == []

    # Refuses overwrite without --force
    assert module_cli.main(["init", "my-service", "--dir", str(tmp_path)]) == 1
    assert module_cli.main(["init", "my-service", "--dir", str(tmp_path), "--force"]) == 0

    # CLI lint on scaffolded directory returns 0
    assert module_cli.main(["lint", str(target)]) == 0
    assert "OK" in capsys.readouterr().out


def test_module_init_rejects_invalid_name(tmp_path):
    assert module_cli.main(["init", "Bad_Name!", "--dir", str(tmp_path)]) == 1


def test_community_docs_exist():
    for rel in ("docs/modules.md", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md"):
        assert Path(rel).is_file(), f"missing {rel}"
