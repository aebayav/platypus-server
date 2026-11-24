"""Validation engine: the previously-dead questions.yml ranges."""

import pytest

from recipe.validate import check_answer, parse_range, validate_answers

Q_PORT = {"id": "web_port", "type": "integer", "validate": "1024-65535"}
Q_PLAIN = {"id": "name", "type": "text"}


def test_parse_range():
    assert parse_range("1024-65535") == (1024, 65535)
    with pytest.raises(ValueError):
        parse_range("nope")


def test_check_answer_in_range():
    assert check_answer(Q_PORT, 8080) is None


def test_check_answer_out_of_range():
    msg = check_answer(Q_PORT, 53)
    assert msg and "1024-65535" in msg


def test_check_answer_non_integer():
    msg = check_answer(Q_PORT, "eighty")
    assert msg and "whole number" in msg


def test_validate_answers_collects_all_messages():
    msgs = validate_answers([Q_PORT, Q_PLAIN], {"web_port": 53, "name": "x"})
    assert len(msgs) == 1 and "web_port" in msgs[0]
