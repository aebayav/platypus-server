"""Real-template pre-flight regressions (review Critical #1).

The fabricated-template tests elsewhere monkeypatch _load_template; these
pin the behavior against the SHIPPED templates, where questions live in
questions.yml — the path that was silently dead in the first pass.
"""

from recipe import transition
from recipe.transition import TransitionError


def _fresh(mounted):
    return transition.state_mod.State(
        schema_version="2", mounted=list(mounted), history=[])


def test_real_template_rejects_hand_edited_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _fresh([]))

    # A hand-edited answers.yml: pihole's web_port question declares
    # 1024-65535; 53 violates it.  No _load_template mock — real files.
    with pytest.raises(TransitionError) as exc:
        transition.mount(
            "pihole",
            answers={"web_port": 53, "timezone": "Europe/Istanbul"},
            log=lambda m: None,
        )
    assert "web_port" in str(exc.value)
    assert "reconfigure" in str(exc.value)


def test_real_template_conflict_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _fresh(["pihole"]))
    monkeypatch.setattr(transition, "load_answers",
                        lambda name: {"web_port": 8080,
                                      "timezone": "Europe/Istanbul"})

    # Both real templates declare {answers[web_port]}; same value collides.
    with pytest.raises(TransitionError) as exc:
        transition.mount("jellyfin", log=lambda m: None)
    assert "pihole" in str(exc.value)
    assert "reconfigure" in str(exc.value)


def test_real_template_valid_answers_pass_pre_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _fresh([]))
    # Full valid answer set for the real syncthing template.
    reached = []
    monkeypatch.setattr(transition, "_execute_mount",
                        lambda *a, **k: reached.append(True))
    transition.mount(
        "syncthing",
        answers={"web_port": 8384, "domain": "s.x.com",
                 "timezone": "Europe/Istanbul"},
        log=lambda m: None,
    )
    assert reached == [True]


def test_broken_other_module_is_warned_not_fatal(tmp_path, monkeypatch, capsys):
    import yaml as _yaml

    monkeypatch.setattr(transition.state_mod, "load", lambda: _fresh(["pihole"]))
    broken = tmp_path / "answers.yml"

    def broken_load(name):
        if name == "pihole":
            # A corrupt answers.yml for the MOUNTED module: pre-flight must
            # warn and continue, not crash or silently swallow.
            raise _yaml.YAMLError("bad answers.yml")
        return {"web_port": 8384, "domain": "s.x.com",
                "timezone": "Europe/Istanbul"}

    monkeypatch.setattr(transition, "load_answers", broken_load)
    monkeypatch.setattr(
        transition, "_execute_mount", lambda *a, **k: None)
    import recipe.lock as lock_mod
    monkeypatch.setattr(lock_mod, "release", lambda: None)

    lines: list[str] = []
    transition.mount("syncthing", log=lines.append)

    joined = "\n".join(lines)
    assert "pihole" in joined and "unresolvable" in joined


import pytest  # noqa: E402  (kept at the bottom for the header docstring)
