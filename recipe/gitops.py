"""GitOps declarative reconciliation engine (`platypus plan` / `platypus apply`)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from . import state as state_mod, transition
from .claims import Claim, find_conflicts, resolve_claims
from .linter import _extract_placeholders
from .model import role_dir
from .renderer import load_answers
from .validate import validate_answers

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class GitOpsError(Exception):
    """Raised when a declarative server spec is invalid or cannot be applied."""


@dataclass
class ReconcilePlan:
    to_dismount: list[str] = field(default_factory=list)
    to_reconfigure: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    to_mount: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.to_dismount or self.to_reconfigure or self.to_mount)


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        def _repl(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            val = os.environ.get(var)
            if val is not None:
                return val
            return default if default is not None else ""

        return _ENV_RE.sub(_repl, obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _decrypt_sops(path: Path) -> Any:
    try:
        res = subprocess.run(["sops", "-d", str(path)], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise GitOpsError("'sops' CLI not found on PATH — install sops to decrypt specs.") from exc
    if res.returncode != 0:
        raise GitOpsError(
            f"sops decryption failed for {path}: {(res.stderr or '').strip()}"
        )
    try:
        return yaml.safe_load(res.stdout)
    except yaml.YAMLError as exc:
        raise GitOpsError(f"Decrypted SOPS content is not valid YAML: {exc}") from exc


def load_spec(path: Path) -> dict[str, Any]:
    """Load a declarative YAML spec, decrypting via ``sops -d`` if encrypted."""
    if not path.is_file():
        raise GitOpsError(f"Spec file not found: {path}")

    if path.name.endswith((".sops.yml", ".sops.yaml")):
        initial = _decrypt_sops(path)
    else:
        try:
            raw_text = path.read_text(encoding="utf-8")
            initial = yaml.safe_load(raw_text)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise GitOpsError(f"Invalid YAML in {path}: {exc}") from exc
        if isinstance(initial, dict) and "sops" in initial:
            initial = _decrypt_sops(path)

    if not isinstance(initial, dict):
        raise GitOpsError("Declarative spec must be a YAML mapping")

    expanded = _expand_env(initial)
    if not isinstance(expanded.get("modules"), dict):
        raise GitOpsError("Declarative spec must contain a 'modules' mapping")
    return expanded


def _load_module_meta(module_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        mod_path = role_dir(module_name)
    except FileNotFoundError:
        raise GitOpsError(f"Unknown module {module_name!r} in declarative spec") from None
    tmpl = yaml.safe_load((mod_path / "template.yml").read_text(encoding="utf-8")) or {}
    quest_file = mod_path / "questions.yml"
    quest = (
        yaml.safe_load(quest_file.read_text(encoding="utf-8")) or {}
        if quest_file.is_file()
        else {}
    )
    return tmpl, list(quest.get("questions") or [])


def _coerce_and_validate_answers(
    mod_name: str,
    tmpl: dict[str, Any],
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
) -> dict[str, Any]:
    coerced = dict(answers)
    for q in questions:
        qid = q.get("id")
        if not qid:
            continue
        qtype = q.get("type")
        required = bool(q.get("required", False))
        val = coerced.get(qid)

        if qtype == "integer" and isinstance(val, str) and val.strip():
            try:
                val = int(val.strip())
                coerced[qid] = val
            except ValueError:
                pass  # Caught by validate_answers below
        elif qtype == "confirm" and isinstance(val, str):
            low = val.strip().lower()
            if low in ("true", "yes", "y", "1"):
                val = True
                coerced[qid] = True
            elif low in ("false", "no", "n", "0"):
                val = False
                coerced[qid] = False

        if required:
            if val is None or val == "" or (qtype == "confirm" and val is not True):
                raise GitOpsError(
                    f"Module {mod_name!r} requires answer {qid!r} to be set/accepted."
                )

        if qtype == "select" and val is not None:
            choices = [str(c) for c in (q.get("choices") or [])]
            if choices and str(val) not in choices:
                raise GitOpsError(
                    f"Module {mod_name!r} answer {qid!r}={val!r} must be one of {choices}"
                )

    for ph in sorted(_extract_placeholders(tmpl)):
        if ph not in coerced or coerced[ph] is None:
            raise GitOpsError(
                f"Module {mod_name!r} missing required placeholder answer {ph!r}"
            )

    val_errors = validate_answers(questions, coerced)
    if val_errors:
        raise GitOpsError(
            f"Invalid answers for {mod_name!r}: " + "; ".join(val_errors)
        )
    return coerced


def _effective_answers(
    questions: list[dict[str, Any]],
    existing: dict[str, Any] | None,
    declared: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for q in questions:
        qid = q.get("id")
        if qid and q.get("default") is not None:
            merged[qid] = q["default"]
    if existing:
        merged.update(existing)
    merged.update(declared)
    return merged


def _normalize_module_entry(mod_name: str, raw_entry: Any) -> dict[str, Any]:
    if raw_entry is None:
        return {}
    if not isinstance(raw_entry, dict):
        raise GitOpsError(
            f"modules.{mod_name} must be a mapping or empty (got {type(raw_entry).__name__})"
        )
    return raw_entry


def compute_plan(spec: dict[str, Any]) -> ReconcilePlan:
    """Compute and validate a conflict-free reconciliation plan."""
    prune = bool(spec.get("prune", True))
    raw_modules: dict[str, Any] = spec.get("modules") or {}
    modules_spec = {
        name: _normalize_module_entry(name, val) for name, val in raw_modules.items()
    }

    current_state = state_mod.load()
    currently_mounted = set(current_state.mounted)

    plan = ReconcilePlan()
    desired_mounted_claims: dict[str, set[Claim]] = {}

    if prune:
        for active_mod in sorted(currently_mounted):
            if active_mod not in modules_spec or not bool(
                modules_spec[active_mod].get("mounted", True)
            ):
                plan.to_dismount.append(active_mod)
    else:
        for mod_name, entry in sorted(modules_spec.items()):
            if entry.get("mounted") is False and mod_name in currently_mounted:
                plan.to_dismount.append(mod_name)

        for active_mod in sorted(currently_mounted):
            if active_mod not in modules_spec and active_mod not in plan.to_dismount:
                tmpl, questions = _load_module_meta(active_mod)
                ans = _effective_answers(questions, load_answers(active_mod), {})
                desired_mounted_claims[active_mod] = resolve_claims(tmpl, ans)

    for mod_name, entry in sorted(modules_spec.items()):
        want_mounted = bool(entry.get("mounted", True))
        declared_answers = entry.get("answers") or {}
        if not isinstance(declared_answers, dict):
            raise GitOpsError(f"modules.{mod_name}.answers must be a mapping")

        tmpl, questions = _load_module_meta(mod_name)
        existing_answers = load_answers(mod_name)
        effective = _coerce_and_validate_answers(
            mod_name,
            tmpl,
            questions,
            _effective_answers(questions, existing_answers, declared_answers),
        )

        if want_mounted:
            try:
                claims = resolve_claims(tmpl, effective)
            except (KeyError, ValueError) as exc:
                raise GitOpsError(f"Invalid port claims for {mod_name!r}: {exc}") from exc

            conflicts = find_conflicts(mod_name, claims, desired_mounted_claims)
            if conflicts:
                raise GitOpsError(
                    f"Port conflict for {mod_name!r}: " + "; ".join(conflicts)
                )
            desired_mounted_claims[mod_name] = claims

            if mod_name in currently_mounted:
                if existing_answers != effective:
                    plan.to_reconfigure.append((mod_name, effective))
                else:
                    plan.unchanged.append(mod_name)
            else:
                plan.to_mount.append((mod_name, effective))
        else:
            if mod_name not in plan.to_dismount:
                if declared_answers and existing_answers != effective:
                    plan.to_reconfigure.append((mod_name, effective))
                else:
                    plan.unchanged.append(mod_name)

    return plan


def format_plan(plan: ReconcilePlan) -> str:
    lines: list[str] = ["Platypus declarative execution plan:"]
    if not plan.has_changes:
        lines.append("  No changes. Server matches declarative specification.")
        return "\n".join(lines)

    for m in plan.to_dismount:
        lines.append(f"  - dismount    {m}")
    for m, _ in plan.to_reconfigure:
        lines.append(f"  ~ reconfigure {m}")
    for m, _ in plan.to_mount:
        lines.append(f"  + mount       {m}")
    for m in plan.unchanged:
        lines.append(f"  = unchanged   {m}")
    lines.append(
        f"\nPlan: {len(plan.to_mount)} to mount, "
        f"{len(plan.to_reconfigure)} to reconfigure, "
        f"{len(plan.to_dismount)} to dismount."
    )
    return "\n".join(lines)


def apply_plan(
    plan: ReconcilePlan,
    force_unlock: bool = False,
    log: Callable[[str], None] = print,
) -> None:
    """Execute *plan* in safe order: dismount -> reconfigure -> mount."""
    for mod_name in plan.to_dismount:
        log(f"\n[-] Dismounting {mod_name!r}...")
        transition.dismount(mod_name, log=log, force_unlock=force_unlock)

    for mod_name, answers in plan.to_reconfigure:
        log(f"\n[~] Reconfiguring {mod_name!r}...")
        transition.reconfigure(mod_name, answers=answers, log=log, force_unlock=force_unlock)

    for mod_name, answers in plan.to_mount:
        log(f"\n[+] Mounting {mod_name!r}...")
        transition.mount(mod_name, answers=answers, log=log, force_unlock=force_unlock)


def main_plan(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus plan",
        description="Preview changes required to match a declarative server.yml.",
    )
    parser.add_argument("-f", "--file", default="server.yml", help="Path to server.yml")
    parser.add_argument(
        "--detailed-exitcode",
        action="store_true",
        help="Return exit code 2 when changes are present, 0 when clean, 1 on error",
    )
    args = parser.parse_args(argv)

    try:
        spec = load_spec(Path(args.file))
        plan = compute_plan(spec)
        print(format_plan(plan))
        if args.detailed_exitcode and plan.has_changes:
            return 2
        return 0
    except GitOpsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main_apply(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="platypus apply",
        description="Reconcile server modules to match a declarative server.yml.",
    )
    parser.add_argument("-f", "--file", default="server.yml", help="Path to server.yml")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without applying")
    parser.add_argument("--force-unlock", action="store_true", help="Steal a stale transition lock")
    args = parser.parse_args(argv)

    try:
        spec = load_spec(Path(args.file))
        plan = compute_plan(spec)
        print(format_plan(plan))
        if args.dry_run or not plan.has_changes:
            return 0
        apply_plan(plan, force_unlock=args.force_unlock)
        print("\nApply complete.")
        return 0
    except (GitOpsError, transition.TransitionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
