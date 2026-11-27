"""`platypus module` CLI — scaffold, lint, and list community modules."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from .linter import lint_all_modules, lint_module_dir
from .model import PACKAGED_MODULES_DIR, builtin_roles, role_dir

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

_TEMPLATE_SKELETON = """\
---
# {name} — Platypus module template
role: {name}
weight: {weight}
ports:
  - "{{answers[web_port]}}/tcp"
version: "1.0"
description: "{title} service module"

hooks:
  pre_remove: []
  post_remove: []
  pre_apply: []
  post_apply:
    - "echo '{title} listening on port {{answers[web_port]}}'"

caddy:
  enabled: true
  route: |
    {{answers[domain]}} {{{{
        reverse_proxy localhost:{{answers[web_port]}}
    }}}}

compose_template: |
  services:
    {service_key}:
      image: nginx:alpine
      container_name: platypus-{name}
      restart: unless-stopped
      ports:
        - "{{answers[web_port]}}:80"
      environment:
        TZ: "{{answers[timezone]}}"
      volumes:
        - ./data:/usr/share/nginx/html
"""

_QUESTIONS_SKELETON = """\
---
# Questions prompted on first `platypus mount {name}`
role: {name}
title: "{title}"
description: "{title} configuration"

questions:
  - id: domain
    label: "Domain name for Caddy HTTPS (e.g. {name}.example.com)"
    type: text
    default: "{name}.example.com"

  - id: web_port
    label: "Host HTTP port"
    type: integer
    default: 8085
    validate: "1024-65535"

  - id: timezone
    label: "Server timezone"
    type: text
    default: "UTC"
"""


def _default_modules_dir() -> Path:
    repo_candidate = Path.cwd() / "recipe" / "modules"
    if repo_candidate.is_dir():
        return repo_candidate
    return Path.cwd() / "modules"


def _cmd_init(args: argparse.Namespace) -> int:
    name: str = args.name.strip()
    if not _NAME_RE.match(name):
        print(
            f"Error: invalid module name {name!r}. Use lowercase letters, digits, and hyphens.",
            file=sys.stderr,
        )
        return 1

    base_dir = Path(args.dir) if args.dir else _default_modules_dir()
    target = base_dir / name
    if target.exists() and not args.force:
        print(
            f"Error: {target} already exists (pass --force to overwrite).",
            file=sys.stderr,
        )
        return 1

    target.mkdir(parents=True, exist_ok=True)
    title = name.replace("-", " ").title()
    service_key = name.replace("-", "_")

    (target / "template.yml").write_text(
        _TEMPLATE_SKELETON.format(
            name=name,
            weight=args.weight,
            title=title,
            service_key=service_key,
        ),
        encoding="utf-8",
    )
    (target / "questions.yml").write_text(
        _QUESTIONS_SKELETON.format(name=name, title=title),
        encoding="utf-8",
    )
    print(f"Scaffolded module {name!r} at {target}")
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    targets: list[Path] = [Path(p) for p in args.paths]
    if not targets:
        report = lint_all_modules()
    else:
        report = {}
        for path in targets:
            if (path / "template.yml").is_file() or (path / "questions.yml").is_file():
                report[path.name] = lint_module_dir(path)
            elif path.is_dir():
                report.update(lint_all_modules(path))
            else:
                report[str(path)] = [f"path does not exist: {path}"]

    if not report:
        print("No modules found to lint.", file=sys.stderr)
        return 1

    failed = 0
    for name, errs in sorted(report.items()):
        if errs:
            failed += 1
            print(f"FAIL  {name}")
            for err in errs:
                print(f"  - {err}")
        else:
            print(f"OK    {name}")
    return 1 if failed else 0


def _cmd_list(args: argparse.Namespace) -> int:
    names = builtin_roles()
    if not names:
        print("No built-in modules found.")
        return 0
    print(f"{'Module':<22}  {'Weight':<10}  {'Ports':<28}  Description")
    print("─" * 84)
    for name in names:
        d = role_dir(name)
        tmpl = yaml.safe_load((d / "template.yml").read_text(encoding="utf-8")) or {}
        weight = tmpl.get("weight", "-")
        ports = ", ".join(tmpl.get("ports") or [])
        desc = tmpl.get("description", "")
        print(f"{name:<22}  {weight:<10}  {ports:<28}  {desc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus module",
        description="Scaffold, lint, and inspect Platypus modules.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_init = sub.add_parser("init", help="Scaffold a new module directory")
    p_init.add_argument("name", help="Kebab-case module name (e.g. vaultwarden)")
    p_init.add_argument("--dir", help="Parent directory (default: recipe/modules or ./modules)")
    p_init.add_argument(
        "--weight",
        choices=["main", "companion"],
        default="companion",
        help="Module weight classification (default: companion)",
    )
    p_init.add_argument("--force", action="store_true", help="Overwrite existing files")
    p_init.set_defaults(func=_cmd_init)

    p_lint = sub.add_parser("lint", help="Validate module YAML schemas and port claims")
    p_lint.add_argument("paths", nargs="*", help="Module directories to check (default: built-in)")
    p_lint.set_defaults(func=_cmd_lint)

    p_list = sub.add_parser("list", help="List available built-in modules")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
