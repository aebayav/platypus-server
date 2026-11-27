"""Multi-node fleet orchestration and VPS-to-Home Tailscale tunnel generator (`platypus fleet`)."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


class FleetError(Exception):
    """Raised when a fleet inventory is invalid or an SSH operation fails."""


def load_fleet(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FleetError(f"Fleet file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FleetError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise FleetError("Fleet file must define a top-level 'nodes' mapping")
    return data


def _ssh_base_cmd(node: dict[str, Any]) -> list[str]:
    host = str(node.get("host") or "").strip()
    if not host:
        raise FleetError("Node entry is missing 'host'")
    user = str(node.get("user") or "root").strip()
    port = int(node.get("port") or 22)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-p",
        str(port),
        f"{user}@{host}",
    ]


def _select_nodes(
    fleet_data: dict[str, Any],
    node_filter: str | None = None,
    tag_filter: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    nodes: dict[str, Any] = fleet_data.get("nodes") or {}
    if node_filter:
        if node_filter not in nodes:
            raise FleetError(f"Unknown node {node_filter!r} in fleet inventory")
        return [(node_filter, nodes[node_filter])]

    selected: list[tuple[str, dict[str, Any]]] = []
    for name, cfg in sorted(nodes.items()):
        if not isinstance(cfg, dict):
            continue
        if tag_filter:
            tags = [str(t) for t in (cfg.get("tags") or [])]
            if tag_filter not in tags:
                continue
        selected.append((name, cfg))
    return selected


def render_tunnels(fleet_data: dict[str, Any]) -> dict[str, str]:
    """Render per-edge-node Caddyfile snippets routing public domains over Tailscale."""
    nodes = fleet_data.get("nodes") or {}
    tunnels = fleet_data.get("tunnels") or []
    grouped: dict[str, list[str]] = {}

    for entry in tunnels:
        if not isinstance(entry, dict):
            raise FleetError("Each tunnel entry must be a mapping")
        domain = str(entry.get("domain") or "").strip()
        edge_name = str(entry.get("edge_node") or "").strip()
        origin_name = str(entry.get("origin_node") or "").strip()
        origin_port = entry.get("origin_port")

        if not (domain and edge_name and origin_name and origin_port):
            raise FleetError(f"Incomplete tunnel definition: {entry!r}")
        if edge_name not in nodes:
            raise FleetError(f"Tunnel references unknown edge_node {edge_name!r}")
        if origin_name not in nodes:
            raise FleetError(f"Tunnel references unknown origin_node {origin_name!r}")

        origin_cfg = nodes[origin_name]
        upstream_ip = str(
            origin_cfg.get("tailscale_ip") or origin_cfg.get("host") or ""
        ).strip()
        if not upstream_ip:
            raise FleetError(f"Origin node {origin_name!r} has neither tailscale_ip nor host")

        block = (
            f"# platypus-fleet tunnel: {domain} -> {origin_name} ({upstream_ip}:{origin_port})\n"
            f"{domain} {{\n"
            f"    reverse_proxy {upstream_ip}:{int(origin_port)}\n"
            f"}}\n"
        )
        grouped.setdefault(edge_name, []).append(block)

    return {edge: "\n".join(blocks) for edge, blocks in grouped.items()}


def _cmd_status(args: argparse.Namespace) -> int:
    fleet_data = load_fleet(Path(args.file))
    targets = _select_nodes(fleet_data, node_filter=args.node, tag_filter=args.tag)
    if not targets:
        print("No matching nodes found.")
        return 0

    failures = 0
    for name, cfg in targets:
        cmd = _ssh_base_cmd(cfg) + ["platypus status"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        status_tag = "ONLINE" if res.returncode == 0 else "UNREACHABLE"
        print(f"── {name} ({cfg.get('host')}) [{status_tag}] ──")
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                print(f"  {line}")
        else:
            failures += 1
            err = (res.stderr or "").strip() or f"ssh exited {res.returncode}"
            print(f"  ! {err}")
    return 1 if failures else 0


def _cmd_apply(args: argparse.Namespace) -> int:
    fleet_data = load_fleet(Path(args.file))
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        raise FleetError(f"Spec file not found: {spec_path}")
    spec_content = spec_path.read_text(encoding="utf-8")

    targets = _select_nodes(fleet_data, node_filter=args.node, tag_filter=args.tag)
    if not targets:
        raise FleetError("No matching nodes selected for apply")

    remote_script = (
        "tmp=$(mktemp /tmp/platypus-spec.XXXXXX.yml) && "
        "trap 'rm -f \"$tmp\"' EXIT && "
        "cat > \"$tmp\" && "
        "platypus apply -f \"$tmp\""
    )
    for name, cfg in targets:
        print(f"Applying {spec_path.name} -> {name}...")
        cmd = _ssh_base_cmd(cfg) + [f"sh -c {shlex.quote(remote_script)}"]
        res = subprocess.run(cmd, input=spec_content, capture_output=True, text=True)
        if res.stdout.strip():
            print(res.stdout.strip())
        if res.returncode != 0:
            raise FleetError(
                f"Remote apply failed on {name!r}: {(res.stderr or '').strip()}"
            )
    return 0


def _cmd_tunnel(args: argparse.Namespace) -> int:
    fleet_data = load_fleet(Path(args.file))
    snippets = render_tunnels(fleet_data)
    if not snippets:
        print("No tunnels declared in fleet file.")
        return 0

    nodes = fleet_data["nodes"]
    for edge_name, caddy_text in sorted(snippets.items()):
        print(f"# === Edge node: {edge_name} ===")
        print(caddy_text)
        if args.apply:
            remote_cmd = (
                "sudo mkdir -p /opt/platypus/Caddyfile.d && "
                "sudo tee /opt/platypus/Caddyfile.d/fleet-tunnels.conf >/dev/null && "
                "(sudo caddy reload || sudo systemctl reload caddy || true)"
            )
            cmd = _ssh_base_cmd(nodes[edge_name]) + [f"sh -c {shlex.quote(remote_cmd)}"]
            res = subprocess.run(cmd, input=caddy_text, capture_output=True, text=True)
            if res.returncode != 0:
                raise FleetError(
                    f"Failed to apply tunnel config on {edge_name!r}: {(res.stderr or '').strip()}"
                )
            print(f"Applied tunnel routes on {edge_name}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus fleet",
        description="Multi-node fleet status, remote GitOps apply, and Tailscale Caddy tunnels.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    def _add_common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("-f", "--file", default="fleet.yml", help="Path to fleet.yml inventory")
        p.add_argument("--node", help="Target a single named node")
        p.add_argument("--tag", help="Filter nodes by tag")
        return p

    p_status = _add_common(sub.add_parser("status", help="Query module status across fleet nodes"))
    p_status.set_defaults(func=_cmd_status)

    p_apply = _add_common(sub.add_parser("apply", help="Stream and apply a server.yml on nodes"))
    p_apply.add_argument("--spec", required=True, help="Declarative server.yml to apply")
    p_apply.set_defaults(func=_cmd_apply)

    p_tunnel = sub.add_parser(
        "tunnel",
        help="Render or apply Caddy reverse-proxy tunnels from VPS edge nodes to home nodes",
    )
    p_tunnel.add_argument("-f", "--file", default="fleet.yml", help="Path to fleet.yml inventory")
    p_tunnel.add_argument("--apply", action="store_true", help="Push Caddy config to edge nodes")
    p_tunnel.set_defaults(func=_cmd_tunnel)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FleetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
