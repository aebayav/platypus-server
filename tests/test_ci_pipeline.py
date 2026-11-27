"""Tests verifying CI/CD quality gates and DevSecOps pipeline configuration."""

from pathlib import Path
import yaml


def test_ci_workflow_runs_module_lint_shellcheck_ruff_molecule_and_trivy():
    ci_raw = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci = yaml.safe_load(ci_raw)

    assert "platypus module lint" in ci_raw
    assert "shellcheck" in ci_raw
    assert "ruff" in ci_raw

    jobs = ci["jobs"]
    assert "molecule" in jobs
    assert set(jobs["molecule"]["strategy"]["matrix"]["role"]) == {
        "common",
        "security",
        "platypus",
    }
    assert "security_scan" in jobs
    assert "trivy" in ci_raw.lower()


def test_dependabot_config_is_valid_yaml():
    dep_path = Path(".github/dependabot.yml")
    assert dep_path.is_file()
    dep = yaml.safe_load(dep_path.read_text(encoding="utf-8"))
    assert dep["version"] == 2
    ecosystems = {u["package-ecosystem"] for u in dep["updates"]}
    assert {"pip", "github-actions"} <= ecosystems
