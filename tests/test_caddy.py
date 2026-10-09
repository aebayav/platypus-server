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
# update() behavior
# ---------------------------------------------------------------------------


def test_no_route_clears_snippet_and_reloads(tmp_path, monkeypatch):
    snippet = tmp_path / "snippet.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    calls = _fake_run(monkeypatch)
    logs: list[str] = []

    caddy.update("minecraft-server", {}, logs.append)  # must not raise

    assert snippet.read_text(encoding="utf-8") == (
        "# platypus — no active HTTP route\n"
    )
    assert calls == [["caddy", "reload"]]
    assert any("No Caddy route" in m for m in logs)


def test_reload_failure_logs_but_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", tmp_path / "snippet.conf")
    _fake_run(monkeypatch, returncode=1, stderr="boom")
    logs: list[str] = []

    caddy.update("minecraft-server", {}, logs.append)  # must not raise

    assert any("Caddy reload skipped" in m for m in logs)


def test_enabled_route_renders_doubled_braces(tmp_path, monkeypatch):
    snippet = tmp_path / "snippet.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    _fake_run(monkeypatch)
    # Same shape as a real template.yml caddy.route: placeholders in single
    # braces, Caddy block delimiters doubled so they survive format_map.
    template = "{answers[domain]} {{\n    reverse_proxy localhost:{answers[port]}\n}}"
    monkeypatch.setattr(
        caddy,
        "_caddy_section",
        lambda name: {"enabled": True, "route": template},
    )

    caddy.update("fake-role", {"domain": "x.com", "port": 8096}, lambda m: None)

    content = snippet.read_text(encoding="utf-8")
    assert "x.com {" in content
    assert "reverse_proxy localhost:8096" in content
    assert content.endswith("}\n")
