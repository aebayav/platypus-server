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
from .transition import TransitionError, TransitionInterrupted, switch
from .validate import check_answer


# ---------------------------------------------------------------------------
# TUI form (simple terminal fallback — full Textual form added later)
# ---------------------------------------------------------------------------

def _collect_answers(role_name: str) -> dict[str, Any]:
    """Prompt the user for each question defined in questions.yml."""
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
        default  = q.get("default")
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

def _cmd_switch(args: argparse.Namespace) -> int:
    role = args.role

    # Check for existing answers
    existing = load_answers(role)
    if existing is not None:
        print(f"Role {role!r}: existing config found — reusing without prompting.")
        answers = existing
    else:
        print(f"Role {role!r}: first-time setup — please answer the following questions.")
        try:
            answers = _collect_answers(role)
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            return 1

    print(f"\nplatypus-server switch → {role!r}\n")
    try:
        switch(role, answers=answers, log=print, force_unlock=args.force_unlock)
        return 0
    except (KeyboardInterrupt, TransitionInterrupted):
        # The engine already rolled back (or nothing had started yet) —
        # show one clean line instead of a raw traceback.
        print(
            "\nInterrupted — the server is in its pre-switch state "
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
        print("   If no switch is running, recover with:  platypus-server switch <role> --force-unlock")

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
        print(f"\n{'Dormant roles'}")
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
        description="Platypus server role management",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_switch = sub.add_parser("switch", help="Switch to a different server role")
    p_switch.add_argument("role", help="Target role name, e.g. minecraft-server")
    p_switch.add_argument(
        "--force-unlock",
        action="store_true",
        help="steal a live transition lock held by another process",
    )
    p_switch.set_defaults(func=_cmd_switch)

    p_status = sub.add_parser("status", help="Show active role, dormant roles, history")
    p_status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
