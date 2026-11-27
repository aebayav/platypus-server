"""Tests for unified TUI/Ansible security policy, multi-distro tasks, and Molecule suites."""

from pathlib import Path
import yaml

from tui.tasks.firewall import UFW_TASK
from tui.tasks.ssh import SSH_HARDENING_LINES, SSH_TASK
from tui.tasks.sysupdate import SYSUPDATE_TASK


def test_ssh_hardening_single_source_of_truth_matches_ansible():
    sec_tasks = yaml.safe_load(
        Path("roles/security/tasks/main.yml").read_text(encoding="utf-8")
    )
    copy_task = next(
        t for t in sec_tasks if "99-hardening.conf" in str(t.get("ansible.builtin.copy", {}))
    )
    ansible_lines = [
        line.strip()
        for line in copy_task["ansible.builtin.copy"]["content"].splitlines()
        if line.strip()
    ]
    assert list(SSH_HARDENING_LINES) == ansible_lines
    assert all(line in " ".join(s.cmd for s in SSH_TASK.steps) for line in SSH_HARDENING_LINES)


def test_ansible_security_role_supports_non_debian_distros():
    raw_tasks = Path("roles/security/tasks/main.yml").read_text(encoding="utf-8")
    sec_tasks = yaml.safe_load(raw_tasks)
    copy_task = next(
        t for t in sec_tasks if "99-hardening.conf" in str(t.get("ansible.builtin.copy", {}))
    )
    # SSH hardening must not be gated exclusively to Debian anymore
    assert copy_task.get("when") != 'ansible_os_family == "Debian"'
    # RedHat firewalld path exists
    assert "firewalld" in raw_tasks

    vars_data = yaml.safe_load(
        Path("roles/security/vars/main.yml").read_text(encoding="utf-8")
    )
    assert "Debian" in vars_data["ssh_service_name"]


def test_tui_sysupdate_and_firewall_support_multiple_package_managers():
    sysupdate_cmds = " ".join(s.cmd for s in SYSUPDATE_TASK.steps)
    for pm in ("apt-get", "dnf", "pacman", "zypper", "apk"):
        assert pm in sysupdate_cmds

    fw_cmds = " ".join(s.cmd for s in UFW_TASK.steps)
    assert "firewall-cmd" in fw_cmds


def test_molecule_suites_exist_for_all_ansible_roles():
    for role in ("common", "security", "platypus"):
        base = Path("roles") / role / "molecule" / "default"
        for fname in ("molecule.yml", "converge.yml", "verify.yml"):
            assert (base / fname).is_file(), f"missing {base / fname}"
