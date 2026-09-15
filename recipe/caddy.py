"""Manage the Caddy reverse-proxy snippet for the active role.

Each role template may declare an optional ``caddy`` block:

    caddy:
      enabled: true
      route: |
        {answers[domain]} {
            reverse_proxy localhost:{answers[port]}
        }

When a role becomes active:
  1. Render the route block with user answers.
  2. Write it to PLATYPUS_CADDYFILE (default /opt/platypus/Caddyfile.d/platypus.conf).
  3. Reload Caddy.

When the incoming role has no caddy section (e.g. Minecraft), the snippet
is cleared so the previous route is removed.

Environment variables
---------------------
PLATYPUS_CADDYFILE
    Path to the managed Caddy snippet file.
    Default: /opt/platypus/Caddyfile.d/platypus.conf

PLATYPUS_CADDY_CONTAINER
    If set, Caddy reload is run via  docker exec <name> caddy reload.
    If empty, caddy reload is invoked directly as a subprocess.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .model import ROLES_SOURCE_DIR

CADDYFILE_PATH = Path(
    os.environ.get(
        "PLATYPUS_CADDYFILE",
        "/opt/platypus/Caddyfile.d/platypus.conf",
    )
)
CADDY_CONTAINER = os.environ.get("PLATYPUS_CADDY_CONTAINER", "")

Log = Any  # Callable[[str], None]


class CaddyError(Exception):
    """Raised when Caddy reload fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _caddy_section(role_name: str) -> dict | None:
    path = ROLES_SOURCE_DIR / role_name / "template.yml"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        tmpl = yaml.safe_load(fh) or {}
    return tmpl.get("caddy") or None


def _render_route(route_template: str, answers: dict[str, Any]) -> str:
    return route_template.format_map({"answers": answers})


def _write_snippet(content: str) -> None:
    CADDYFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CADDYFILE_PATH.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(CADDYFILE_PATH)


def _reload(log: Log) -> None:
    if CADDY_CONTAINER:
        cmd = [
            "docker", "exec", CADDY_CONTAINER,
            "caddy", "reload", "--config", "/etc/caddy/Caddyfile",
        ]
    else:
        cmd = ["caddy", "reload", "--config", str(CADDYFILE_PATH)]

    log(f"  caddy reload  ({' '.join(cmd)})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise CaddyError(
            f"caddy reload failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    log("  ✓ Caddy reloaded.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(role_name: str, answers: dict[str, Any], log: Log) -> None:
    """
    Write the Caddy snippet for *role_name* and reload Caddy.

    If the role has no ``caddy`` section, or ``caddy.enabled`` is false,
    the snippet is cleared (removing any previous route).
    Reload failures are logged but do not abort the transition.
    """
    section = _caddy_section(role_name)

    if not section or not section.get("enabled", False):
        log(f"  No Caddy route for {role_name!r} — clearing snippet.")
        _write_snippet("# platypus — no active HTTP route\n")
    else:
        route_tmpl: str = section.get("route", "")
        if not route_tmpl.strip():
            log("  caddy.enabled=true but route is empty — skipping.")
            return
        rendered = _render_route(route_tmpl, answers)
        log(f"  Writing Caddy route for {role_name!r}…")
        _write_snippet(
            "# platypus — auto-managed, do not edit manually\n"
            f"{rendered}\n"
        )

    try:
        _reload(log)
    except (CaddyError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log(f"  ! Caddy reload skipped: {exc}")
