"""Tests for the doctor pre-flight checks (platypus doctor)."""

import re
import sys

import pytest

import doctor


def test_parse_ports():
    assert doctor.parse_ports("80, 443,5050") == [80, 443, 5050]


def test_parse_ports_empty():
    assert doctor.parse_ports("") == []


def test_default_ports_per_target():
    assert doctor.default_ports("home") == (5050, 8080)
    assert doctor.default_ports("vps") == (80, 443, 5050, 8080)
    assert doctor.default_ports("bogus") == (5050, 8080)


def test_main_vps_target_checks_public_ports(capsys, monkeypatch):
    monkeypatch.delenv("PLATYPUS_TARGET", raising=False)
    doctor.main(["--target", "vps"])
    out = capsys.readouterr().out
    assert "Target: vps" in out
    assert re.search(r"port 80\s", out)
    assert re.search(r"port 443\s", out)


def test_main_env_target_selects_ports(capsys, monkeypatch):
    monkeypatch.setenv("PLATYPUS_TARGET", "vps")
    doctor.main([])
    out = capsys.readouterr().out
    assert re.search(r"port 80\s", out)
    assert re.search(r"port 443\s", out)


def test_main_home_target_skips_public_ports(capsys, monkeypatch):
    monkeypatch.delenv("PLATYPUS_TARGET", raising=False)
    doctor.main(["--target", "home"])
    out = capsys.readouterr().out
    assert "Target: home" in out
    assert not re.search(r"port 80\s", out)
    assert not re.search(r"port 443\s", out)


def test_parse_ports_out_of_range():
    with pytest.raises(ValueError):
        doctor.parse_ports("70000")


def test_check_os_returns_result():
    result = doctor.check_os()
    assert result.label == "OS"
    assert result.status in (doctor.OK, doctor.WARN)


def test_check_python_is_ok():
    result = doctor.check_python()
    assert result.status == doctor.OK
    assert result.label == "Python"


def test_run_checks_covers_all_labels():
    results = doctor.run_checks([12345])
    labels = [result.label for result in results]
    assert labels == [
        "OS",
        "sudo",
        "Python",
        "Disk",
        "RAM",
        "Internet",
        "port 12345",
    ]


def test_report_all_ok_returns_zero(capsys):
    results = [
        doctor.Result("a", doctor.OK, "x"),
        doctor.Result("b", doctor.WARN, "y"),
    ]
    assert doctor.print_report(results) == 0
    assert "all checks passed" in capsys.readouterr().out


def test_report_failure_returns_one(capsys):
    results = [
        doctor.Result("a", doctor.OK, "x"),
        doctor.Result("b", doctor.FAIL, "y"),
    ]
    assert doctor.print_report(results) == 1
    assert "problem(s)" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "linux", reason="port bind semantics differ")
def test_port_in_use_then_free():
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert doctor.check_port(port).status == doctor.FAIL
    finally:
        listener.close()
    assert doctor.check_port(port).status == doctor.OK
