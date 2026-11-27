"""Tests for GitOps declarative reconciliation (`platypus plan` / `platypus apply`)."""

from types import SimpleNamespace

import pytest
import yaml

from recipe import gitops, state as state_mod


def _write_spec(path, data):
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_plan_computes_dismount_reconfigure_and_mount_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_mod,
        "load",
        lambda: state_mod.State(
            schema_version="2",
            mounted=["minecraft-server", "pihole"],
            history=[],
        ),
    )
    saved_answers = {
        "pihole": {
            "domain": "pi.example.com",
            "web_port": 8081,
            "local_ip": "192.168.1.10",
            "admin_password": "old",
            "timezone": "UTC",
        }
    }
    monkeypatch.setattr(gitops, "load_answers", lambda name: saved_answers.get(name))
    monkeypatch.setenv("PI_PASS", "new-secret")

    spec_file = _write_spec(
        tmp_path / "server.yml",
        {
            "apiVersion": "platypus/v1",
            "prune": True,
            "modules": {
                "pihole": {
                    "mounted": True,
                    "answers": {
                        "web_port": 8081,
                        "admin_password": "${PI_PASS}",
                        "timezone": "UTC",
                    },
                },
                "syncthing": {
                    "mounted": True,
                    "answers": {"web_port": 8384, "timezone": "UTC"},
                },
            },
        },
    )

    spec = gitops.load_spec(spec_file)
    plan = gitops.compute_plan(spec)
    assert plan.to_dismount == ["minecraft-server"]
    assert [m for m, _ in plan.to_reconfigure] == ["pihole"]
    assert plan.to_reconfigure[0][1]["admin_password"] == "new-secret"
    assert [m for m, _ in plan.to_mount] == ["syncthing"]
    assert plan.has_changes is True

    # Detailed exitcode returns 2 when changes exist
    assert gitops.main_plan(["-f", str(spec_file), "--detailed-exitcode"]) == 2


def test_plan_rejects_port_conflicts_across_desired_set(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_mod,
        "load",
        lambda: state_mod.State(schema_version="2", mounted=[], history=[]),
    )
    monkeypatch.setattr(gitops, "load_answers", lambda name: None)

    spec_file = _write_spec(
        tmp_path / "conflict.yml",
        {
            "modules": {
                "pihole": {"mounted": True, "answers": {"web_port": 8090}},
                "jellyfin": {"mounted": True, "answers": {"web_port": 8090}},
            }
        },
    )
    spec = gitops.load_spec(spec_file)
    with pytest.raises(gitops.GitOpsError, match="8090/tcp"):
        gitops.compute_plan(spec)


def test_apply_executes_dismount_before_reconfigure_and_mount(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_mod,
        "load",
        lambda: state_mod.State(
            schema_version="2",
            mounted=["minecraft-server", "pihole"],
            history=[],
        ),
    )
    monkeypatch.setattr(
        gitops,
        "load_answers",
        lambda name: {"web_port": 8081} if name == "pihole" else None,
    )

    ops = []
    monkeypatch.setattr(
        gitops.transition,
        "dismount",
        lambda m, log=print, force_unlock=False: ops.append(("dismount", m)),
    )
    monkeypatch.setattr(
        gitops.transition,
        "reconfigure",
        lambda m, answers, log=print, force_unlock=False: ops.append(("reconfigure", m)),
    )
    monkeypatch.setattr(
        gitops.transition,
        "mount",
        lambda m, answers=None, log=print, force_unlock=False: ops.append(("mount", m)),
    )

    spec_file = _write_spec(
        tmp_path / "server.yml",
        {
            "modules": {
                "pihole": {"mounted": True, "answers": {"web_port": 8082}},
                "syncthing": {"mounted": True, "answers": {"web_port": 8384}},
            }
        },
    )
    assert gitops.main_apply(["-f", str(spec_file)]) == 0
    assert ops == [
        ("dismount", "minecraft-server"),
        ("reconfigure", "pihole"),
        ("mount", "syncthing"),
    ]


def test_sops_encrypted_spec_calls_sops_decrypt(tmp_path, monkeypatch):
    sops_file = tmp_path / "server.sops.yml"
    sops_file.write_text("sops:\n  version: 3.8.1\n", encoding="utf-8")

    decrypted_yaml = yaml.safe_dump(
        {"modules": {"syncthing": {"mounted": True, "answers": {"web_port": 8384}}}}
    )
    monkeypatch.setattr(
        gitops.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=decrypted_yaml, stderr=""),
    )
    spec = gitops.load_spec(sops_file)
    assert spec["modules"]["syncthing"]["answers"]["web_port"] == 8384
