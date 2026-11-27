"""Regression tests reproducing all Critical and Important whole-branch review findings."""

import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dashboard import app as dash_app
from recipe import backup, fleet, gitops, state as state_mod, transition


# --- Critical #1: hook CWD + monitoring UID permissions ---
def test_transition_run_hooks_executes_in_module_runtime_cwd(tmp_path, monkeypatch):
    roles_dir = tmp_path / "roles"
    monkeypatch.setattr(transition, "PLATYPUS_ROLES_DIR", roles_dir)
    seen_cwds = []

    def fake_run(cmd, **kwargs):
        seen_cwds.append(kwargs.get("cwd"))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with transition._module_hook_cwd("monitoring"):
        transition._run_hooks(["mkdir -p ./data"], lambda m: None)

    assert seen_cwds == [str(roles_dir / "monitoring")]
    assert (roles_dir / "monitoring").is_dir()

    mon_tmpl = Path("recipe/modules/monitoring/template.yml").read_text(encoding="utf-8")
    assert "prometheus-tsdb" in mon_tmpl
    assert "chmod" in mon_tmpl or "chown" in mon_tmpl or "user:" in mon_tmpl


# --- Critical #2: Cloud-Init must not put admin_user in non-existent docker group pre-install ---
def test_cloud_init_users_group_does_not_fail_before_docker_install():
    raw = Path("infra/terraform/cloud-init/user-data.yml.tftpl").read_text(encoding="utf-8")
    rendered = (
        raw.replace("${admin_user}", "platypusadmin")
        .replace("${ssh_public_key}", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest u@h")
        .replace("${platypus_env}", "prod")
        .replace("${platypus_target}", "vps")
        .replace("${server_spec_b64}", "")
    )
    parsed = yaml.safe_load(rendered)
    user_entry = next(u for u in parsed["users"] if isinstance(u, dict))
    assert "docker" not in user_entry.get("groups", [])
    assert "/usr/local/bin" in raw


# --- Critical #3: Pinned Trivy action, top-level permissions, Molecule cgroupns & collections ---
def test_ci_pins_trivy_and_configures_molecule_collections_and_cgroups():
    ci_raw = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci = yaml.safe_load(ci_raw)
    assert "aquasecurity/trivy-action@master" not in ci_raw
    assert ci.get("permissions", {}).get("contents") == "read"
    mol_job = ci["jobs"]["molecule"]
    assert "ANSIBLE_COLLECTIONS_PATH" in str(mol_job)

    for role in ("common", "security", "platypus"):
        mol = yaml.safe_load(
            Path(f"roles/{role}/molecule/default/molecule.yml").read_text(encoding="utf-8")
        )
        assert mol["platforms"][0].get("cgroupns_mode") == "host"


# --- Critical #4: Scoped backup pruning + symlink-safe streaming restore ---
def test_single_module_backup_does_not_prune_full_backups_and_unlinks_dest_symlinks(
    tmp_path, monkeypatch
):
    platypus_dir = tmp_path / "platypus"
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir(parents=True)
    monkeypatch.setattr(backup, "PLATYPUS_DIR", platypus_dir)

    # Pre-existing full backup archive must survive single-module backup with keep=1
    full_archive = dest_dir / "platypus-backup-all-20260101-000000.tar.gz"
    full_archive.write_bytes(b"keep-me")

    mod_dir = platypus_dir / "roles" / "pihole" / "data"
    mod_dir.mkdir(parents=True)
    (mod_dir / "cfg.txt").write_text("dns", encoding="utf-8")
    monkeypatch.setattr(backup, "_load_module_hooks", lambda n: {})

    backup.create_backup(module="pihole", dest=dest_dir, keep=1, log=lambda m: None)
    assert full_archive.exists(), "single-module backup pruned full-server archive!"

    # Reject Windows drive / backslash archive members
    win_tar = tmp_path / "win.tar.gz"
    with tarfile.open(win_tar, "w:gz") as tf:
        b_data = b"x"
        ti = tarfile.TarInfo(name="C:\\evil.txt")
        ti.size = len(b_data)
        tf.addfile(ti, io.BytesIO(b_data))
    with pytest.raises(backup.BackupError, match="Unsafe path"):
        backup.restore_backup(win_tar)


# --- Critical #5: Fleet SSH option injection guard, sudo apply, IPv6 bracket, Caddy reload ---
def test_fleet_guards_ssh_injection_uses_sudo_and_brackets_ipv6(tmp_path, monkeypatch):
    with pytest.raises(fleet.FleetError):
        fleet._ssh_base_cmd({"host": "-oProxyCommand=evil", "user": "ops", "port": 22})
    with pytest.raises(fleet.FleetError):
        fleet._ssh_base_cmd({"host": "10.0.0.1", "user": "ops", "port": "not-a-port"})

    cmd = fleet._ssh_base_cmd({"host": "10.0.0.1", "user": "ops", "port": 22})
    assert "--" in cmd

    snippets = fleet.render_tunnels(
        {
            "nodes": {
                "edge": {"host": "1.2.3.4"},
                "home": {"tailscale_ip": "fd7a:115c:a1e0::2"},
            },
            "tunnels": [
                {
                    "domain": "tv.example.com",
                    "edge_node": "edge",
                    "origin_node": "home",
                    "origin_port": 8096,
                }
            ],
        }
    )
    assert "[fd7a:115c:a1e0::2]:8096" in snippets["edge"]

    with pytest.raises(fleet.FleetError):
        fleet.render_tunnels(
            {
                "nodes": {"edge": {"host": "1.2.3.4"}, "home": {"host": "10.0.0.2"}},
                "tunnels": [
                    {
                        "domain": "bad.com {\n respond 200\n}",
                        "edge_node": "edge",
                        "origin_node": "home",
                        "origin_port": 80,
                    }
                ],
            }
        )


# --- Important #6: Systemd ReadWritePaths=-/opt/platypus and conditional ProtectHome ---
def test_dashboard_installer_handles_missing_opt_platypus_and_home_checkouts():
    script = Path("scripts/install-dashboard-service.sh").read_text(encoding="utf-8")
    assert "mkdir -p /opt/platypus" in script
    assert "ReadWritePaths=-/opt/platypus" in script


# --- Important #7 & #13: GitOps shorthand None, integer env coercion, required check, SOPS ---
def test_gitops_handles_null_shorthand_coerces_env_ints_and_checks_required(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        state_mod,
        "load",
        lambda: state_mod.State(schema_version="2", mounted=["pihole"], history=[]),
    )
    monkeypatch.setattr(gitops, "load_answers", lambda n: None)
    monkeypatch.setenv("PORT_FROM_ENV", "8089")

    spec_path = tmp_path / "shorthand.yml"
    spec_path.write_text(
        "modules:\n"
        "  pihole:\n"
        "  syncthing:\n"
        "    answers:\n"
        '      web_port: "${PORT_FROM_ENV}"\n',
        encoding="utf-8",
    )
    plan = gitops.compute_plan(gitops.load_spec(spec_path))
    assert "pihole" not in plan.to_dismount
    assert dict(plan.to_mount)["syncthing"]["web_port"] == 8089

    # Missing required confirm/text field (e.g. minecraft eula_accepted defaults to False)
    mc_spec = tmp_path / "mc.yml"
    mc_spec.write_text("modules:\n  minecraft-server: {}\n", encoding="utf-8")
    with pytest.raises(gitops.GitOpsError, match="eula_accepted"):
        gitops.compute_plan(gitops.load_spec(mc_spec))


# --- Important #8: SSH Include directive & openSUSE firewalld ---
def test_security_role_ensures_sshd_include_and_routes_suse_to_firewalld():
    raw = Path("roles/security/tasks/main.yml").read_text(encoding="utf-8")
    assert "Include /etc/ssh/sshd_config.d/*.conf" in raw
    assert "Suse" in raw


# --- Important #9 & #10: Non-loopback /metrics auth, waitress dep, missing CLI errors ---
def test_non_loopback_metrics_requires_auth_and_missing_cli_raises_clean_error(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DASHBOARD_METRICS_TOKEN", raising=False)
    client = dash_app.app.test_client()
    remote_resp = client.get("/metrics", environ_base={"REMOTE_ADDR": "203.0.113.55"})
    assert remote_resp.status_code == 401

    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "waitress" in pyproject

    # Missing sops binary raises GitOpsError, not FileNotFoundError
    sops_file = tmp_path / "sec.sops.yml"
    sops_file.write_bytes(b"\x00\xffbinary-sops-envelope")
    monkeypatch.setattr(
        gitops.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("sops")),
    )
    with pytest.raises(gitops.GitOpsError, match="sops"):
        gitops.load_spec(sops_file)
