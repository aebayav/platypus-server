"""Security tests for the Platypus web dashboard."""

from pathlib import Path

from werkzeug.security import generate_password_hash

from dashboard import app as dash_app, auth


def test_secret_key_is_never_static_hardcoded_default():
    assert dash_app.app.secret_key != "platypus-dashboard-secret-change-me"
    assert len(str(dash_app.app.secret_key)) >= 32


def test_hashed_password_and_constant_time_check(monkeypatch):
    pw_hash = generate_password_hash("s3cr3t-pass!")
    monkeypatch.setenv("DASHBOARD_USER", "opsadmin")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", pw_hash)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    assert auth.check_credentials("opsadmin", "s3cr3t-pass!") is True
    assert auth.check_credentials("opsadmin", "wrong") is False
    assert auth.check_credentials("wronguser", "s3cr3t-pass!") is False
    assert auth.using_default_credentials() is False


def test_login_rate_limiting_blocks_brute_force(monkeypatch):
    auth.reset_rate_limiter()
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "platypus")
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)

    client = dash_app.app.test_client()
    for _ in range(5):
        resp = client.post("/api/login", json={"username": "admin", "password": "bad"})
        assert resp.status_code == 401

    blocked = client.post("/api/login", json={"username": "admin", "password": "bad"})
    assert blocked.status_code == 429


def test_csrf_enforced_on_mutating_api_endpoints(monkeypatch):
    auth.reset_rate_limiter()
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "platypus")
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)

    client = dash_app.app.test_client()
    login_res = client.post("/api/login", json={"username": "admin", "password": "platypus"})
    assert login_res.status_code == 200
    token = login_res.get_json().get("csrf_token")
    assert token

    # Mutating POST without X-CSRF-Token must be rejected with 403
    no_csrf = client.post("/api/containers", json={"image": ""})
    assert no_csrf.status_code == 403

    # Mutating POST with valid X-CSRF-Token passes CSRF gate (reaches handler -> 400 empty image)
    with_csrf = client.post(
        "/api/containers",
        json={"image": ""},
        headers={"X-CSRF-Token": token},
    )
    assert with_csrf.status_code == 400


def test_systemd_installer_uses_hardening_and_loopback_default():
    script = Path("scripts/install-dashboard-service.sh").read_text(encoding="utf-8")
    assert "NoNewPrivileges=true" in script
    assert "PrivateTmp=true" in script
    assert "127.0.0.1" in script
    assert "DASHBOARD_SECRET_KEY" in script
