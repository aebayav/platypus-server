"""Manage the multi-section Caddy reverse-proxy snippet.

Each module template may declare an optional ``caddy`` block.  The
managed file (default ``/opt/platypus/Caddyfile.d/platypus.conf``) holds
one marked section per mounted module::

    # platypus — auto-managed, do not edit manually
    # begin module: pihole
    pi.example.com {
        reverse_proxy localhost:8080
    }
    # end module: pihole

``upsert_route`` renders and (re)writes one module's section; modules
without an enabled caddy block are simply absent — mounting them never
touches the other sections.  ``remove_route`` deletes one section.
Because routes go through ``str.format_map``, Caddy block delimiters
must be doubled (``{{`` / ``}}``) in templates.

Environment variables
---------------------
PLATYPUS_CADDYFILE
    Path to the managed Caddy snippet file.
    Default /opt/platypus/Caddyfile.d/platypus.conf

PLATYPUS_CADDY_CONTAINER
    If set, Caddy reload is run via  docker exec <name> caddy reload.
    If empty, caddy reload is invoked directly as a subprocess.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .model import role_dir

CADDYFILE_PATH = Path(
    os.environ.get(
        "PLATYPUS_CADDYFILE",
        "/opt/platypus/Caddyfile.d/platypus.conf",
    )
)
CADDY_CONTAINER = os.environ.get("PLATYPUS_CADDY_CONTAINER", "")

HEADER = "# platypus — auto-managed, do not edit manually"
EMPTY_HEADER = "# platypus — no active HTTP route"

Log = Any  # Callable[[str], None]


class CaddyError(Exception):
    """Raised when Caddy reload fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _caddy_section(role_name: str) -> dict | None:
    try:
        path = role_dir(role_name) / "template.yml"
    except FileNotFoundError:
        return None
    with path.open(encoding="utf-8") as fh:
        tmpl = yaml.safe_load(fh) or {}
    return tmpl.get("caddy") or None


def _render_route(route_template: str, answers: dict[str, Any]) -> str:
    return route_template.format_map({"answers": answers})


def _section_re(module: str) -> re.Pattern:
    return re.compile(
        rf"^# begin module: {re.escape(module)}\n.*?^# end module: {re.escape(module)}\n",
        re.MULTILINE | re.DOTALL,
    )


def _read_content() -> str:
    try:
        return CADDYFILE_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_snippet(content: str) -> None:
    CADDYFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CADDYFILE_PATH.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(CADDYFILE_PATH)


def _reload(log: Log) -> None:
    if CADDY_CONTAINER:
        cmd = ["docker", "exec", CADDY_CONTAINER, "caddy", "reload"]
    else:
        # Bare `caddy reload` signals the running instance via its admin
        # API (localhost:2019). Do NOT pass --config: the managed snippet
        # (platypus.conf) is not Caddy's main config, and a comment-only
        # snippet is not even valid JSON — passing it as --config makes
        # Caddy fail with a JSON parse error.
        cmd = ["caddy", "reload"]

    log(f"  caddy reload  ({' '.join(cmd)})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise CaddyError(
            f"caddy reload failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    log("  ✓ Caddy reloaded.")


def _reload_safe(log: Log) -> None:
    try:
        _reload(log)
    except (CaddyError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log(f"  ! Caddy reload skipped: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upsert_route(module: str, answers: dict[str, Any], log: Log) -> None:
    """Render *module*'s route and (re)write its marked section.

    A module without an enabled caddy block is absent from the file —
    other sections are never touched.  Reload failures are logged, never
    raised.
    """
    section = _caddy_section(module)
    block: str | None = None

    if section and section.get("enabled", False):
        route_tmpl: str = section.get("route", "")
        if route_tmpl.strip():
            rendered = _render_route(route_tmpl, answers)
            log(f"  Writing Caddy route for {module!r}…")
            block = (
                f"# begin module: {module}\n{rendered}\n"
                f"# end module: {module}\n"
            )
        else:
            log("  caddy.enabled=true but route is empty — skipping.")
    else:
        log(f"  No Caddy route for {module!r} — section absent.")

    content = _read_content()
    content = _section_re(module).sub("", content)  # drop any old section
    if block is not None:
        content = content.replace(f"{HEADER}\n", "", 1)
        content = content.replace(f"{EMPTY_HEADER}\n", "", 1)
        content = f"{HEADER}\n{content}{block}"
    elif not content.strip():
        content = f"{EMPTY_HEADER}\n"
    if not content.endswith("\n"):
        content += "\n"
    _write_snippet(content)
    _reload_safe(log)


def remove_route(module: str, log: Log) -> None:
    """Delete *module*'s section; a missing section is a no-op."""
    content = _read_content()
    new_content = _section_re(module).sub("", content)
    if new_content == content:
        log(f"  No Caddy section for {module!r} — nothing to remove.")
        return
    if not new_content.strip() or new_content.strip() == HEADER:
        new_content = f"{EMPTY_HEADER}\n"
    _write_snippet(new_content)
    _reload_safe(log)
