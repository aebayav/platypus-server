"""Render docker-compose.yml from a role template + user answers.

Also handles reading/writing answers.yml to the runtime role directory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .model import PLATYPUS_ROLES_DIR, ROLES_SOURCE_DIR


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_compose(role_name: str, answers: dict[str, Any]) -> str:
    """
    Load ``compose_template`` from template.yml and substitute
    ``{answers[key]}`` placeholders with the provided *answers* dict.
    """
    template_path = ROLES_SOURCE_DIR / role_name / "template.yml"
    with template_path.open(encoding="utf-8") as fh:
        tmpl = yaml.safe_load(fh) or {}

    compose_template: str = tmpl.get("compose_template", "")
    if not compose_template:
        raise ValueError(
            f"Role {role_name!r} has no compose_template in template.yml"
        )
    # {answers[key]} substitution — only answers dict is exposed (safe)
    return compose_template.format_map({"answers": answers})


def write_compose(role_name: str, answers: dict[str, Any]) -> Path:
    """Render and write docker-compose.yml to the runtime role directory."""
    role_dir = PLATYPUS_ROLES_DIR / role_name
    role_dir.mkdir(parents=True, exist_ok=True)

    content = render_compose(role_name, answers)
    compose_file = role_dir / "docker-compose.yml"
    tmp = compose_file.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(compose_file)
    return compose_file


# ---------------------------------------------------------------------------
# Answers persistence
# ---------------------------------------------------------------------------

def load_answers(role_name: str) -> dict[str, Any] | None:
    """
    Load answers from ``/opt/platypus/roles/<role>/answers.yml``.
    Returns the inner ``answers`` mapping, or ``None`` if the file is absent.
    """
    answers_file = PLATYPUS_ROLES_DIR / role_name / "answers.yml"
    if not answers_file.exists():
        return None

    with answers_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("answers") or None


def save_answers(role_name: str, answers: dict[str, Any]) -> Path:
    """Persist *answers* to answers.yml atomically."""
    role_dir = PLATYPUS_ROLES_DIR / role_name
    role_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "role": role_name,
        "answered_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
    }
    answers_file = role_dir / "answers.yml"
    tmp = answers_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    tmp.replace(answers_file)
    return answers_file

