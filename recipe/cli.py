"""platypus-server CLI — server role management.

Usage
-----
  platypus-server switch <role>   Switch to a different server role
  platypus-server status          Show active role and transition history
"""

from __future__ import annotations

import argparse
import sys

from . import state as state_mod
from .transition import TransitionError, switch


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def _cmd_switch(args: argparse.Namespace) -> int:
    role = args.role
    print(f"platypus-server switch → {role!r}\n")
    try:
        switch(role, log=print)
        return 0
    except TransitionError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1


def _cmd_status(args: argparse.Namespace) -> int:
    state = state_mod.load()

    if state.active:
        since = (
            state.activated_at.strftime("%Y-%m-%d %H:%M UTC")
            if state.activated_at
            else "unknown"
        )
        print(f"Active role : {state.active}")
        print(f"Since       : {since}")
    else:
        print("No active role.")

    if state.transition_lock:
        lock = state.transition_lock
        print(
            f"\n⚠  Transition lock  role={lock.get('role')!r}  "
            f"PID={lock.get('pid')}  started={lock.get('started_at')}"
        )

    if state.history:
        print(f"\n{'Role':<24}  {'Activated':>16}  {'Deactivated':>16}")
        print("─" * 60)
        for h in reversed(state.history):
            act  = h.activated_at.strftime("%Y-%m-%d %H:%M")
            deac = h.deactivated_at.strftime("%Y-%m-%d %H:%M") if h.deactivated_at else "active"
            print(f"{h.role:<24}  {act:>16}  {deac:>16}")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="platypus-server",
        description="Platypus server role management",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # switch
    p_switch = sub.add_parser("switch", help="Switch to a different server role")
    p_switch.add_argument("role", help="Target role name, e.g. minecraft-server")
    p_switch.set_defaults(func=_cmd_switch)

    # status
    p_status = sub.add_parser("status", help="Show current role and transition history")
    p_status.set_defaults(func=_cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
