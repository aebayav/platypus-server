"""Tests for Prometheus `/metrics` endpoint and built-in `monitoring` module."""

import json

from dashboard import app as dash_app
from recipe import linter
from recipe.model import builtin_roles, role_dir


def test_metrics_endpoint_renders_prometheus_text_format(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_METRICS_TOKEN", raising=False)
    platypus_root = tmp_path / "platypus"
    platypus_root.mkdir(parents=True, exist_ok=True)
    (platypus_root / "state.yml").write_text(
        "schema_version: '2'\nmounted:\n  - pihole\nhistory: []\n",
        encoding="utf-8",
    )
    (platypus_root / "last_backup.json").write_text(
        json.dumps({"timestamp": 1700000123.5}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dash_app, "_PLATYPUS_RUNTIME_DIR", platypus_root, raising=False)
    monkeypatch.setattr(
        dash_app,
        "_snapshot",
        lambda: {
            "metrics": {
                "cpu_percent": 12.5,
                "memory": {"percent": 45.0},
                "disk": {"percent": 33.2},
            },
            "services": [{"name": "Portainer", "status": "up"}],
        },
    )

    client = dash_app.app.test_client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "platypus_cpu_percent 12.5" in body
    assert 'platypus_module_mounted{module="pihole"} 1' in body
    assert 'platypus_service_up{service="Portainer"} 1' in body
    assert "platypus_last_backup_timestamp_seconds 1700000123.5" in body


def test_metrics_endpoint_respects_optional_bearer_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_METRICS_TOKEN", "prom-secret-token")
    client = dash_app.app.test_client()
    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer prom-secret-token"}).status_code
        == 200
    )


def test_monitoring_module_ships_and_passes_linter():
    assert "monitoring" in builtin_roles()
    mod_dir = role_dir("monitoring")
    assert linter.lint_module_dir(mod_dir) == []
