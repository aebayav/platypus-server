"""Enforce the ``validate`` ranges declared in questions.yml.

Historically the ``validate`` field (``"1024-65535"``) was declared by
every port question but never read.  This module gives it teeth at two
points: interactively in the question form, and as a pre-flight check
on the effective answer set before a mount starts stopping anything.
"""

from __future__ import annotations

from typing import Any


def parse_range(spec: str) -> tuple[int, int]:
    """Parse an integer range spec like ``"1024-65535"``.

    Raises ``ValueError`` for anything else — the syntax in existing
    templates is ranges only, so no other form is accepted (YAGNI).
    """
    try:
        low_s, _, high_s = spec.partition("-")
        low, high = int(low_s), int(high_s)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"invalid validate spec: {spec!r}") from exc
    if low > high:
        raise ValueError(f"invalid validate spec: {spec!r} (low > high)")
    return low, high


def check_answer(question: dict, value: Any) -> str | None:
    """Return an error message for an invalid *value*, or None.

    Only integer-type questions with a ``validate`` range are checked;
    every other question type passes (nothing else declares validate).
    """
    if question.get("type") != "integer":
        return None
    spec = question.get("validate")
    if not spec:
        return None
    qid = question.get("id", "?")

    if isinstance(value, bool) or not isinstance(value, int):
        return f"{qid}: please enter a whole number."
    try:
        low, high = parse_range(str(spec))
    except ValueError as exc:
        return f"{qid}: {exc}"  # a broken template spec is not the user's fault
    if not (low <= value <= high):
        return f"{qid}: value must be in the range {low}-{high}."
    return None


def validate_answers(questions: list[dict], answers: dict) -> list[str]:
    """Return error messages for every answered question that violates
    its declared range.  Unknown ids inside *answers* are ignored —
    templates evolve, stale keys are not user errors."""
    by_id = {q.get("id"): q for q in questions if isinstance(q, dict)}
    messages: list[str] = []
    for qid, value in answers.items():
        question = by_id.get(qid)
        if question is None:
            continue
        msg = check_answer(question, value)
        if msg:
            messages.append(msg)
    return messages
