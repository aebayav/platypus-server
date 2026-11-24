"""Port claims declared by module templates.

Every module's ``template.yml`` carries a ``ports:`` list — the host
ports it will bind, with optional ``/tcp`` or ``/udp`` suffixes (tcp is
the default) and ``{answers[key]}`` placeholders resolved at mount time.
The engine resolves claims against the *effective* answer set BEFORE
touching anything and refuses a mount whose claims collide with the
mounted set.  ``weight: main|companion`` is a recommendation label
only; the engine ignores it.
"""

from __future__ import annotations

import re
from typing import Any

Claim = tuple[int, str]  # (port, "tcp" | "udp")

_PROTO_RE = re.compile(r"^(tcp|udp)$", re.IGNORECASE)


def parse_ports_entry(entry: str) -> dict:
    """Parse one ``ports:`` entry into ``{"port", "proto"}``.

    ``"53/udp"``, ``"8080"`` (tcp default), ``"{answers[p]}/tcp"``.
    Malformed entries raise ``ValueError``.
    """
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f"invalid ports entry: {entry!r}")
    parts = entry.strip().rsplit("/", 1)
    if len(parts) == 2:
        port_s, proto_s = parts
        if not _PROTO_RE.match(proto_s):
            raise ValueError(f"invalid ports entry: {entry!r}")
        proto = proto_s.lower()
    else:
        port_s, proto = parts[0], "tcp"
    if not port_s:
        raise ValueError(f"invalid ports entry: {entry!r}")
    if not (port_s.isdigit() or port_s.startswith("{")):
        raise ValueError(f"invalid ports entry: {entry!r}")
    return {"port": port_s, "proto": proto}


def _resolve_port(port_s: str, answers: dict[str, Any]) -> int:
    rendered = port_s
    if "{" in port_s:
        try:
            rendered = port_s.format_map({"answers": answers})
        except (KeyError, ValueError) as exc:
            raise KeyError(
                f"cannot resolve port claim {port_s!r} against the answers"
            ) from exc
    try:
        port = int(rendered)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"resolved port claim {port_s!r} -> {rendered!r} is not an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"resolved port {port} out of range (1-65535)")
    return port


def resolve_claims(template: dict, answers: dict[str, Any]) -> set[Claim]:
    """Resolve a template's declared ``ports:`` to concrete claims.

    Raises ``KeyError`` when a placeholder has no answer and ``ValueError``
    when a resolved port is not a positive integer — both BEFORE the
    engine stops anything.
    """
    claims: set[Claim] = set()
    for entry in template.get("ports", []):
        parsed = parse_ports_entry(entry)
        port = _resolve_port(parsed["port"], answers)
        claims.add((port, parsed["proto"]))
    return claims


def find_conflicts(
    new_name: str,
    new_claims: set[Claim],
    mounted: dict[str, set[Claim]],
) -> list[str]:
    """Return sorted human-readable conflicts between *new_claims* and
    the claims of OTHER mounted modules.  A module never conflicts with
    its own existing claims (re-mount/reconfigure keeps its ports)."""
    messages: list[str] = []
    for other_name, other_claims in sorted(mounted.items()):
        if other_name == new_name:
            continue
        for claim in sorted(new_claims & other_claims):
            port, proto = claim
            messages.append(
                f"port {port}/{proto} is already used by {other_name!r}"
            )
    return messages
