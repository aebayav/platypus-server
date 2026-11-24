"""Declared port claims: parsing, placeholder resolution, conflicts."""

import pytest

from recipe.claims import find_conflicts, parse_ports_entry, resolve_claims

TMPL = {"ports": ["53/udp", "{answers[web_port]}/tcp"]}


def test_parse_ports_entry_variants():
    assert parse_ports_entry("53/udp") == {"port": "53", "proto": "udp"}
    assert parse_ports_entry("8080") == {"port": "8080", "proto": "tcp"}
    assert parse_ports_entry("{answers[p]}/tcp") == {"port": "{answers[p]}", "proto": "tcp"}
    with pytest.raises(ValueError):
        parse_ports_entry("nope")


def test_resolve_claims_placeholders():
    claims = resolve_claims(TMPL, {"web_port": 8080})
    assert claims == {(53, "udp"), (8080, "tcp")}


def test_resolve_claims_missing_answer():
    with pytest.raises(KeyError):
        resolve_claims(TMPL, {})


def test_find_conflicts():
    mine = {(8080, "tcp")}
    mounted = {"pihole": {(53, "udp"), (8080, "tcp")}, "syncthing": {(22000, "tcp")}}
    msgs = find_conflicts("jellyfin", mine, mounted)
    assert msgs == ["port 8080/tcp is already used by 'pihole'"]


def test_self_conflict_ignored():
    mine = {(8080, "tcp")}
    assert find_conflicts("jellyfin", mine, {"jellyfin": {(8080, "tcp")}}) == []
