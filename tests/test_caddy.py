"""Tests for recipe.caddy — the Caddy snippet manager."""

import subprocess
from types import SimpleNamespace

from recipe import caddy


def _fake_run(monkeypatch, returncode=0, stderr=""):
    """Replace subprocess.run and return the list of captured commands."""
    calls: list = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


# ---------------------------------------------------------------------------
# Reload command shape
# ---------------------------------------------------------------------------


def test_reload_uses_bare_caddy_command(monkeypatch):
    calls = _fake_run(monkeypatch)
    caddy._reload(lambda m: None)
    # --config must NOT be passed: the snippet is not Caddy's main config
    # and a comment-only snippet breaks Caddy's JSON parsing.
    assert calls == [["caddy", "reload"]]


def test_reload_container_path(monkeypatch):
    monkeypatch.setattr(caddy, "CADDY_CONTAINER", "caddy1")
    calls = _fake_run(monkeypatch)
    caddy._reload(lambda m: None)
    assert calls == [["docker", "exec", "caddy1", "caddy", "reload"]]



# ---------------------------------------------------------------------------
# upsert_route() / remove_route() behavior
# ---------------------------------------------------------------------------


def test_upsert_then_remove_roundtrip(tmp_path, monkeypatch):
    snippet = tmp_path / "platypus.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    _fake_run(monkeypatch)
    route = "{answers[domain]} {{\n    reverse_proxy localhost:{answers[p]}\n}}"
    monkeypatch.setattr(caddy, "_caddy_section",
                        lambda name: {"enabled": True, "route": route})
    caddy.upsert_route("jellyfin", {"domain": "jf.x.com", "p": 8096}, lambda m: None)
    caddy.upsert_route("pihole", {"domain": "pi.x.com", "p": 8080}, lambda m: None)
    content = snippet.read_text(encoding="utf-8")
    assert "# begin module: jellyfin" in content and "jf.x.com" in content
    assert "# begin module: pihole" in content and "pi.x.com" in content

    caddy.remove_route("jellyfin", lambda m: None)
    content = snippet.read_text(encoding="utf-8")
    assert "jellyfin" not in content and "pi.x.com" in content


def test_upsert_without_route_is_absent_not_clearing(tmp_path, monkeypatch):
    snippet = tmp_path / "platypus.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    _fake_run(monkeypatch)
    monkeypatch.setattr(caddy, "_caddy_section", lambda name: None)
    caddy.upsert_route("minecraft-server", {}, lambda m: None)
    assert snippet.read_text(encoding="utf-8") == "# platypus \u2014 no active HTTP route\n"


def test_reload_failure_logs_but_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", tmp_path / "platypus.conf")
    _fake_run(monkeypatch, returncode=1, stderr="boom")
    logs: list[str] = []
    caddy.upsert_route("anything", {}, logs.append)  # section-less; still fine
    assert any("Caddy reload skipped" in m for m in logs)
