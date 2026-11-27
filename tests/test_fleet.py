"""Tests for multi-node `platypus fleet` orchestration and Tailscale tunnel generator."""

from types import SimpleNamespace

import pytest
import yaml

from recipe import fleet


def _sample_fleet(tmp_path):
    path = tmp_path / "fleet.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "platypus/v1",
                "nodes": {
                    "edge-vps": {
                        "host": "203.0.113.10",
                        "tailscale_ip": "100.64.0.1",
                        "user": "ops",
                        "port": 2222,
                        "target": "vps",
                        "tags": ["edge"],
                    },
                    "home-box": {
                        "host": "100.64.0.2",
                        "tailscale_ip": "100.64.0.2",
                        "user": "homeadmin",
                        "port": 22,
                        "target": "home",
                        "tags": ["home", "media"],
                    },
                },
                "tunnels": [
                    {
                        "domain": "jellyfin.example.com",
                        "edge_node": "edge-vps",
                        "origin_node": "home-box",
                        "origin_port": 8096,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fleet_status_queries_filtered_nodes_over_ssh(tmp_path, monkeypatch, capsys):
    inv = _sample_fleet(tmp_path)
    seen_cmds = []

    def fake_run(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="Mounted    : jellyfin\n", stderr="")

    monkeypatch.setattr(fleet.subprocess, "run", fake_run)
    rc = fleet.main(["status", "-f", str(inv), "--tag", "media"])
    assert rc == 0
    assert len(seen_cmds) == 1
    assert "homeadmin@100.64.0.2" in seen_cmds[0]
    out = capsys.readouterr().out
    assert "home-box" in out
    assert "jellyfin" in out


def test_fleet_tunnel_renders_caddyfile_routing_vps_to_tailscale_origin(tmp_path):
    inv = _sample_fleet(tmp_path)
    loaded = fleet.load_fleet(inv)
    snippets = fleet.render_tunnels(loaded)
    assert "edge-vps" in snippets
    caddy_cfg = snippets["edge-vps"]
    assert "jellyfin.example.com {" in caddy_cfg
    assert "reverse_proxy 100.64.0.2:8096" in caddy_cfg


def test_fleet_apply_streams_spec_over_ssh_to_target_node(tmp_path, monkeypatch):
    inv = _sample_fleet(tmp_path)
    spec = tmp_path / "server.yml"
    spec.write_text("modules:\n  pihole:\n    mounted: true\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("input", "")))
        return SimpleNamespace(returncode=0, stdout="Apply complete.\n", stderr="")

    monkeypatch.setattr(fleet.subprocess, "run", fake_run)
    rc = fleet.main(["apply", "-f", str(inv), "--node", "edge-vps", "--spec", str(spec)])
    assert rc == 0
    assert len(calls) == 1
    cmd, stdin_data = calls[0]
    assert "-p" in cmd and "2222" in cmd
    assert "ops@203.0.113.10" in cmd
    assert "pihole" in stdin_data


def test_fleet_tunnel_rejects_unknown_node(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text(
        yaml.safe_dump(
            {
                "nodes": {"edge": {"host": "1.2.3.4"}},
                "tunnels": [
                    {
                        "domain": "a.example.com",
                        "edge_node": "edge",
                        "origin_node": "missing-node",
                        "origin_port": 8080,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(fleet.FleetError, match="missing-node"):
        fleet.render_tunnels(fleet.load_fleet(bad))
