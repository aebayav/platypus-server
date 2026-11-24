"""platypus-server CLI — server role management.

Usage
-----
  platypus-server switch <role>   Switch to a different server role
  platypus-server status          Show active role, dormant roles, history
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from . import state as state_mod
from . import lock as lock_mod
from .model import PLATYPUS_ROLES_DIR, role_dir
from .renderer import load_answers, save_answers
from .transition import (
    TransitionError,
    TransitionInterrupted,
    dismount,
    mount,
    reconfigure,
    switch,
)
from .validate import check_answer


# ---------------------------------------------------------------------------
# TUI form (simple terminal fallback — full Textual form added later)
# ---------------------------------------------------------------------------

def _collect_answers(role_name: str, defaults: dict | None = None) -> dict[str, Any]:
    """Prompt the user for each question defined in questions.yml.

    *defaults* (the module's current answers) take precedence over the
    question spec's own defaults — used by reconfigure so the form is
    pre-filled.
    """
    try:
        questions_file = role_dir(role_name) / "questions.yml"
    except FileNotFoundError as exc:
        raise SystemExit(f"Error: {exc}") from None
    if not questions_file.exists():
        raise SystemExit(
            f"Error: questions.yml not found for role {role_name!r}"
        )

    with questions_file.open(encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}

    print(f"\n── Setup: {spec.get('title', role_name)} ──")
    print(spec.get("description", ""))
    print()

    answers: dict[str, Any] = {}
    for q in spec.get("questions", []):
        qid      = q["id"]
        label    = q["label"]
        qtype    = q["type"]
        default  = (defaults or {}).get(qid, q.get("default"))
        choices  = q.get("choices", [])
        required = q.get("required", False)

        while True:
            if choices:
                opts = "/".join(str(c) for c in choices)
                prompt = f"  {label} [{opts}] (default: {default}): "
            elif default is not None:
                prompt = f"  {label} (default: {default}): "
            else:
                prompt = f"  {label}: "

            raw = input(prompt).strip()

            if not raw and default is not None:
                value: Any = default
            elif not raw and required:
                print("    ✗ This field is required.")
                continue
            elif not raw:
                value = ""
            else:
                value = raw

            # Type coercion
            if qtype == "integer":
                try:
                    value = int(value)
                except ValueError:
                    print("    ✗ Please enter a whole number.")
                    continue
                # Enforce the declared validate range (previously dead).
                check_msg = check_answer(
                    {"id": qid, "type": qtype, "validate": q.get("validate")},
                    value,
                )
                if check_msg:
                    print(f"    ✗ {check_msg}")
                    continue
            elif qtype == "confirm":
                if isinstance(value, bool):
                    pass
                elif str(value).lower() in ("y", "yes", "true", "1"):
                    value = True
                elif str(value).lower() in ("n", "no", "false", "0"):
                    value = False
                else:
                    print("    ✗ Please answer y or n.")
                    continue
                if required and value is False:
                    print("    ✗ You must accept this to continue.")
                    continue
            elif qtype == "select" and choices and str(value) not in [str(c) for c in choices]:
                print(f"    ✗ Choose one of: {', '.join(str(c) for c in choices)}")
                continue

            answers[qid] = value
            break

    print()
    return answers


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def _collect_with_form(role: str, defaults: dict | None = None) -> dict | int:
    """Run the question form; returns answers or an exit code on cancel."""
    print(f"Module {role!r}: first-time setup — please answer the following questions.")
    try:
        return _collect_answers(role, defaults=defaults)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        return 1


def _cmd_mount(args: argparse.Namespace) -> int:
    module = args.module

    existing = load_answers(module)
    if existing is not None:
        print(f"Module {module!r}: existing config found — reusing without prompting.")
        answers = existing
    else:
        answers = _collect_with_form(module)
        if isinstance(answers, int):
            return answers

    print(f"\nplatypus mount → {module!r}\n")
    try:
        mount(module, answers=answers, log=print, force_unlock=args.force_unlock)
        return 0
    except (KeyboardInterrupt, TransitionInterrupted):
        # The engine already rolled back (or nothing had started yet) —
        # show one clean line instead of a raw traceback.
        print(
            "\nInterrupted — the server is in its pre-mount state "
            "(rollback details above, if any).",
            file=sys.stderr,
        )
        return 130
    except TransitionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


#: Deprecated spelling of mount — the alias is deliberate (additive).
_cmd_switch = _cmd_mount


def _cmd_dismount(args: argparse.Namespace) -> int:
    module = args.module
    print(f"\nplatypus dismount → {module!r}\n")
    try:
        dismount(module, log=print, force_unlock=args.force_unlock)
        return 0
    except (KeyboardInterrupt, TransitionInterrupted):
        print(
            "\nInterrupted — the module was left mounted "
            "(details above, if any).",
            file=sys.stderr,
        )
        return 130
    except TransitionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


def _cmd_reconfigure(args: argparse.Namespace) -> int:
    module = args.module

    # Always re-run the form, pre-filled with the current answers.
    current = load_answers(module) or {}
    print(f"Module {module!r}: re-answering the questions "
          "(current values are the defaults).")
    try:
        answers = _collect_answers(module, defaults=current)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        return 1

    print(f"\nplatypus reconfigure → {module!r}\n")
    try:
        reconfigure(module, answers=answers, log=print,
                    force_unlock=args.force_unlock)
        return 0
    except (KeyboardInterrupt, TransitionInterrupted):
        print(
            "\nInterrupted — the previous configuration still applies "
            "(rollback details above, if any).",
            file=sys.stderr,
        )
        return 130
    except TransitionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


def _cmd_status(args: argparse.Namespace) -> int:
    state = state_mod.load()

    # Mounted modules
    if state.mounted:
        for name in state.mounted:
            print(f"Mounted    : {name}")
    else:
        print("No modules mounted.")

    file_lock = lock_mod.read()
    if file_lock:
        print(
            f"\n⚠  Transition lock  target={file_lock.get('target')!r}  "
            f"PID={file_lock.get('pid')}  started={file_lock.get('started_at')}"
        )
        print("   If no transition is running, recover with:  platypus mount <module> --force-unlock")

    # Dormant roles — scan /opt/platypus/roles/
    dormant = []
    if PLATYPUS_ROLES_DIR.exists():
        for d in sorted(PLATYPUS_ROLES_DIR.iterdir()):
            if d.is_dir() and d.name not in state.mounted:
                answers_file = d / "answers.yml"
                data_dir = d / "data"
                dormant.append({
                    "name": d.name,
                    "configured": answers_file.exists(),
                    "has_data": data_dir.exists() and any(data_dir.iterdir()),
                })

    if dormant:
        print(f"\n{'Dormant modules'}")
        print("─" * 44)
        for r in dormant:
            cfg  = "configured" if r["configured"] else "not configured"
            data = "data preserved" if r["has_data"] else "no data"
            print(f"  {r['name']:<28}  {cfg}, {data}")

    # Transition history
    if state.history:
        print(f"\n{'Role':<26}  {'Activated':>16}  {'Deactivated':>16}")
        print("─" * 62)
        for h in reversed(state.history):
            act  = h.activated_at.strftime("%Y-%m-%d %H:%M")
            deac = (
                h.deactivated_at.strftime("%Y-%m-%d %H:%M")
                if h.deactivated_at else "active"
            )
            print(f"  {h.role:<24}  {act:>16}  {deac:>16}")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus-server",
        description="Platypus server module management",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p):
        p.add_argument(
            "--force-unlock",
            action="store_true",
            help="steal a live transition lock held by another process",
        )
        return p

    p_mount = _add_common(
        sub.add_parser("mount", help="Mount a module (additive; others keep running)")
    )
    p_mount.add_argument("module", help="Target module, e.g. minecraft-server")
    p_mount.set_defaults(func=_cmd_mount)

    p_dismount = _add_common(
        sub.add_parser("dismount", help="Dismount a module (stop and freeze it)")
    )
    p_dismount.add_argument("module", help="Mounted module to dismount")
    p_dismount.set_defaults(func=_cmd_dismount)

    p_reconfigure = _add_common(
        sub.add_parser("reconfigure", help="Re-answer a module's questions and apply")
    )
    p_reconfigure.add_argument("module", help="Module to reconfigure")
    p_reconfigure.set_defaults(func=_cmd_reconfigure)

    p_switch = _add_common(
        sub.add_parser(
            "switch",
            help="Deprecated alias of mount (additive, not replacing)",
        )
    )
    p_switch.add_argument("module", help="Target module, e.g. minecraft-server")
    p_switch.set_defaults(func=_cmd_switch)

    p_status = sub.add_parser("status", help="Show mounted, dormant modules, history")
    p_status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
