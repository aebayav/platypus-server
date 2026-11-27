"""Schema and consistency linter for Platypus module definitions.

Validates a module directory containing ``template.yml`` and ``questions.yml``:
- Valid YAML mappings with matching ``role`` names
- Required keys (``role``, ``version``, ``description``, ``weight``, ``ports``,
  ``compose_template``)
- Legal ``weight`` (``main`` or ``companion``)
- Well-formed ``ports`` claims via :func:`recipe.claims.parse_ports_entry`
- Valid ``questions.yml`` entries (unique ``id``s, valid ``type``, valid
  ``validate`` integer ranges, non-empty ``choices`` for ``select``)
- Placeholder coverage: every ``{answers[key]}`` referenced in ``template.yml``
  exists in ``questions.yml``
- Compose port coverage: every host port published by ``compose_template`` is
  declared in ``template.yml``'s ``ports`` list
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .claims import parse_ports_entry
from .model import PACKAGED_MODULES_DIR
from .validate import parse_range

VALID_WEIGHTS = {"main", "companion"}
VALID_QUESTION_TYPES = {"text", "integer", "select", "confirm"}
_PLACEHOLDER_RE = re.compile(r"\{answers\[([^\]]+)\]\}")
_SENTINEL_RE = re.compile(r"__PLATYPUS_ANS_([A-Za-z0-9_-]+)__")


def _extract_placeholders(obj: object) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, str):
        found.update(_PLACEHOLDER_RE.findall(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.update(_extract_placeholders(v))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_extract_placeholders(item))
    return found


def _extract_compose_published_ports(compose_template: str) -> tuple[set[str], list[str]]:
    """Return ``(canonical_ports, parse_errors)`` from *compose_template*."""
    sanitized = _PLACEHOLDER_RE.sub(r"__PLATYPUS_ANS_\1__", compose_template)
    try:
        parsed = yaml.safe_load(sanitized)
    except yaml.YAMLError as exc:
        return set(), [f"compose_template is not valid YAML: {exc}"]

    if not isinstance(parsed, dict) or not isinstance(parsed.get("services"), dict):
        return set(), ["compose_template must define a top-level 'services' mapping"]

    published: set[str] = set()
    errors: list[str] = []
    for svc_name, svc in parsed["services"].items():
        if not isinstance(svc, dict):
            continue
        for raw_port in svc.get("ports") or []:
            if isinstance(raw_port, dict):
                target_p = raw_port.get("published")
                proto = str(raw_port.get("protocol", "tcp")).lower()
                if target_p is not None:
                    restored = _SENTINEL_RE.sub(r"{answers[\1]}", str(target_p))
                    published.add(f"{restored}/{proto}")
                continue
            entry = _SENTINEL_RE.sub(r"{answers[\1]}", str(raw_port).strip())
            if "/" in entry:
                mapping, proto = entry.rsplit("/", 1)
                proto = proto.lower()
            else:
                mapping, proto = entry, "tcp"
            parts = mapping.split(":")
            if len(parts) < 2:
                continue  # container-only port exposure, not bound on host
            host_port = parts[-2].strip()
            if not host_port:
                errors.append(f"service {svc_name!r} has empty host port in {entry!r}")
                continue
            published.add(f"{host_port}/{proto}")
    return published, errors


def lint_module_dir(module_dir: Path) -> list[str]:
    """Validate *module_dir* and return a list of error strings (empty if valid)."""
    errors: list[str] = []
    tmpl_path = module_dir / "template.yml"
    quest_path = module_dir / "questions.yml"

    if not tmpl_path.is_file():
        errors.append(f"missing {tmpl_path.name}")
    if not quest_path.is_file():
        errors.append(f"missing {quest_path.name}")
    if errors:
        return errors

    try:
        tmpl = yaml.safe_load(tmpl_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"template.yml YAML error: {exc}"]
    try:
        quest = yaml.safe_load(quest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"questions.yml YAML error: {exc}"]

    if not isinstance(tmpl, dict):
        errors.append("template.yml must be a YAML mapping")
        return errors
    if not isinstance(quest, dict):
        errors.append("questions.yml must be a YAML mapping")
        return errors

    mod_name = module_dir.name
    role_key = tmpl.get("role") or tmpl.get("name")
    if role_key != mod_name:
        errors.append(
            f"template.yml role {role_key!r} does not match directory name {mod_name!r}"
        )
    q_role = quest.get("role") or quest.get("name")
    if q_role != mod_name:
        errors.append(
            f"questions.yml role {q_role!r} does not match directory name {mod_name!r}"
        )

    for req in ("version", "description", "weight", "compose_template"):
        if not tmpl.get(req):
            errors.append(f"template.yml missing required field {req!r}")

    weight = tmpl.get("weight")
    if weight not in VALID_WEIGHTS:
        errors.append(f"template.yml weight {weight!r} must be one of {sorted(VALID_WEIGHTS)}")

    raw_ports = tmpl.get("ports")
    declared_ports: set[str] = set()
    if not isinstance(raw_ports, list):
        errors.append("template.yml 'ports' must be a list")
    else:
        for entry in raw_ports:
            try:
                parsed = parse_ports_entry(entry)
                declared_ports.add(f"{parsed['port']}/{parsed['proto']}")
            except ValueError as exc:
                errors.append(f"template.yml invalid port claim {entry!r}: {exc}")

    # Validate questions.yml
    questions = quest.get("questions")
    question_ids: set[str] = set()
    if not isinstance(questions, list):
        errors.append("questions.yml 'questions' must be a list")
    else:
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                errors.append(f"questions[{idx}] must be a mapping")
                continue
            qid = q.get("id")
            if not isinstance(qid, str) or not qid.strip():
                errors.append(f"questions[{idx}] missing string 'id'")
                continue
            if qid in question_ids:
                errors.append(f"questions.yml duplicate question id {qid!r}")
            question_ids.add(qid)

            qtype = q.get("type")
            if qtype not in VALID_QUESTION_TYPES:
                errors.append(
                    f"question {qid!r} has invalid type {qtype!r} "
                    f"(expected one of {sorted(VALID_QUESTION_TYPES)})"
                )
            if qtype == "select":
                choices = q.get("choices")
                if not isinstance(choices, list) or not choices:
                    errors.append(f"select question {qid!r} must declare non-empty 'choices'")
            if q.get("validate") is not None:
                try:
                    parse_range(str(q["validate"]))
                except ValueError as exc:
                    errors.append(f"question {qid!r} invalid validate field: {exc}")

    # Placeholder coverage
    referenced = _extract_placeholders(tmpl)
    missing_qids = sorted(referenced - question_ids)
    for mq in missing_qids:
        errors.append(
            f"template.yml references '{{answers[{mq}]}}' which is not defined in questions.yml"
        )

    # Compose port coverage
    compose_str = tmpl.get("compose_template")
    if isinstance(compose_str, str) and compose_str.strip():
        published, compose_errs = _extract_compose_published_ports(compose_str)
        errors.extend(compose_errs)
        undeclared = sorted(published - declared_ports)
        for p in undeclared:
            errors.append(
                f"compose_template publishes host port {p!r} not declared in template.yml ports"
            )

    return errors


def lint_all_modules(base_dir: Path | None = None) -> dict[str, list[str]]:
    """Lint every module subdirectory under *base_dir* (defaults to packaged modules)."""
    root = base_dir if base_dir is not None else PACKAGED_MODULES_DIR
    results: dict[str, list[str]] = {}
    if not root.is_dir():
        return results
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            results[entry.name] = lint_module_dir(entry)
    return results
