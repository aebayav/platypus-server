"""Unified `platypus` command: one entry point for every tool."""

from __future__ import annotations

import importlib
import sys

SUBCOMMANDS: dict[str, tuple[str, str, str | None]] = {
    "doctor":      ("doctor",          "main", None),
    "setup":       ("tui.app",         "main", None),
    "dashboard":   ("dashboard.app",   "main", None),
    "mount":       ("recipe.cli",     "main", "mount"),
    "dismount":    ("recipe.cli",     "main", "dismount"),
    "reconfigure": ("recipe.cli",     "main", "reconfigure"),
    "switch":      ("recipe.cli",     "main", "switch"),
    "status":      ("recipe.cli",     "main", "status"),
    "module":      ("recipe.module_cli", "main", None),
    "backup":      ("recipe.backup",  "main_backup", None),
    "restore":     ("recipe.backup",  "main_restore", None),
    "plan":        ("recipe.gitops",  "main_plan", None),
    "apply":       ("recipe.gitops",  "main_apply", None),
    "generate":    ("zero2server.cli", "main", None),
}

USAGE = (
    "usage: platypus [--version] <command> [args...]\n\n"
    "Commands:\n"
    "  doctor      pre-flight checks for a fresh install\n"
    "  setup       interactive server setup (TUI)\n"
    "  dashboard   web dashboard\n"
    "  mount       mount a module (additive; others keep running)\n"
    "  dismount    stop and freeze a mounted module\n"
    "  reconfigure re-answer a module's questions and apply\n"
    "  switch      deprecated alias of mount\n"
    "  status      show mounted and dormant modules\n"
    "  module      scaffold, lint, and list modules\n"
    "  backup      create a state-aware backup (tar or restic)\n"
    "  restore     verify and restore a backup archive\n"
    "  plan        preview declarative GitOps changes from server.yml\n"
    "  apply       reconcile mounted modules to match server.yml\n"
    "  generate    generate docker-compose.yml + Caddyfile\n"
)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("platypus-server")
    except PackageNotFoundError:
        return "unknown"


def _run(module_name: str, func_name: str, prefix: str | None, rest: list[str]) -> int:
    module = importlib.import_module(module_name)
    argv = ([prefix] + rest) if prefix else rest
    result = getattr(module, func_name)(argv)
    return 0 if result is None else int(result)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if argv[0] == "--version":
        print(f"platypus {_version()}")
        return 0
    command, rest = argv[0], argv[1:]
    if command not in SUBCOMMANDS:
        print(f"platypus: unknown command {command!r}\n", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2
    module_name, func_name, prefix = SUBCOMMANDS[command]
    return _run(module_name, func_name, prefix, rest)
