"""Packaging guarantees: name, version, deps, extras, entry points."""

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import dashboard
import tui
import zero2server

with open("pyproject.toml", "rb") as fh:
    PYPROJECT = tomllib.load(fh)


def test_distribution_name_and_version():
    assert PYPROJECT["project"]["name"] == "platypus-server"
    assert PYPROJECT["project"]["version"] == "0.2.1"


def test_core_dependencies_are_honest():
    deps = " ".join(PYPROJECT["project"]["dependencies"])
    assert "textual>=0.77.0" in deps
    assert "pyyaml>=6.0" in deps
    assert "flask>=3.0" in deps
    assert "psutil>=5.9" in deps


def test_removed_noop_and_dashboard_extras():
    extras = PYPROJECT["project"]["optional-dependencies"]
    assert "dashboard" not in extras
    assert "zero2server" not in extras
    assert "dev" in extras


def test_license_and_urls_metadata():
    assert PYPROJECT["project"]["license"] == "MIT"
    urls = " ".join(PYPROJECT["project"]["urls"].values())
    assert "github.com/aebayav/platypus-server" in urls


def test_init_versions_come_from_metadata():
    from importlib.metadata import version

    expected = version("platypus-server")
    assert dashboard.__version__ == expected
    assert tui.__version__ == expected
    assert zero2server.__version__ == expected


def test_console_scripts_keep_aliases_and_new_dispatcher():
    scripts = PYPROJECT["project"]["scripts"]
    assert scripts["platypus"] == "platypus_cli.cli:main"
    assert scripts["platypus-doctor"] == "doctor:main"
    assert scripts["platypus-tui"] == "tui.app:main"
    assert scripts["platypus-dashboard"] == "dashboard.app:main"
    assert scripts["platypus-server"] == "recipe.cli:main"
    assert scripts["zero-to-server"] == "zero2server.cli:main"


def test_dashboard_health_version_comes_from_metadata():
    from dashboard.app import _DASHBOARD_VERSION
    from importlib.metadata import version

    assert _DASHBOARD_VERSION == version("platypus-server")
