"""Bootstrap script guards.

The pipx package name varies per distro and some releases do not ship it
at all; a wrong name must never kill the one-liner (apt/dnf/apk abort the
whole transaction on an unknown package, and `set -euo pipefail` would
stop the script before the pip fallback can run).
"""

from pathlib import Path

BOOTSTRAP = Path("bootstrap.sh").read_text(encoding="utf-8")


def test_apt_branch_does_not_use_python3_pipx():
    # 'python3-pipx' does not exist in Debian/Ubuntu archives; the binary
    # package there is 'pipx'.
    apt_lines = [
        line.strip()
        for line in BOOTSTRAP.splitlines()
        if line.strip().startswith("apt-get install")
    ]
    assert apt_lines, "apt-get install line missing from bootstrap.sh"
    assert all("python3-pipx" not in line for line in apt_lines)
    assert any(line.endswith("pipx || true") for line in apt_lines)


def test_apt_pipx_install_is_nonfatal():
    # A distro release without a pipx package must fall through to the
    # `pip install pipx` fallback instead of aborting.
    assert "apt-get install -y pipx || true" in BOOTSTRAP


def test_every_distro_pipx_attempt_is_nonfatal():
    install_lines = [
        line.strip()
        for line in BOOTSTRAP.splitlines()
        if line.strip().startswith(
            ("apt-get install", "dnf install", "apk add", "pacman -Sy", "zypper")
        )
    ]
    assert install_lines, "no distro install lines found"
    for line in install_lines:
        if "pipx" in line:
            assert line.endswith("|| true"), line
