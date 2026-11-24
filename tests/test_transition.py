"""Mount/dismount engine tests — no Docker, subprocess calls are faked."""

import subprocess
from types import SimpleNamespace

import pytest

from recipe import lock, transition
from recipe.transition import TransitionError


def _fake_procs(monkeypatch, results=None):
    """Fake subprocess.run; returns list of (cmd, returncode) pairs seen."""
    seen = []
    defaults = {"docker": 0, "caddy": 0}

    def run(cmd, **kwargs):
        seen.append(list(cmd))
        rc = (results or {}).get(cmd[0], defaults.get(cmd[0], 0))
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return seen


def _state(mounted):
    return transition.state_mod.State(
        schema_version="2", mounted=list(mounted), history=[])


def _no_save(monkeypatch):
    saves = []
    monkeypatch.setattr(transition.state_mod, "save", lambda st: saves.append(1))
    return saves


# ---------------------------------------------------------------------------
# mount — additive, pre-flighted, locked
# ---------------------------------------------------------------------------

def test_mount_is_additive(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    monkeypatch.setattr(
        transition, "load_answers",
        lambda name: {"pihole": {"web_port": 8080},
                      "syncthing": {"web_port": 8384}}[name],
    )
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: None)
    monkeypatch.setattr(transition, "_run_hooks", lambda c, l, answers=None: None)
    monkeypatch.setattr(transition, "_compose_up", lambda role, log: None)
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: None)
    saved_states = []
    monkeypatch.setattr(
        transition.state_mod, "save", lambda st: saved_states.append(st)
    )

    transition.mount("syncthing", log=lambda m: None)

    assert saved_states[0].mounted == ["pihole", "syncthing"]


def test_mount_lock_error_becomes_transition_error(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    lock.acquire("other-role")
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state([]))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"port": 25565})
    with pytest.raises(TransitionError) as exc:
        transition.mount("minecraft-server", log=lambda m: None)
    assert "--force-unlock" in str(exc.value)


def test_mount_releases_lock_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state([]))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"port": 25565})
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: None)
    monkeypatch.setattr(transition, "_run_hooks", lambda c, l, answers=None: None)
    monkeypatch.setattr(transition, "_compose_up", lambda role, log: None)
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: None)
    monkeypatch.setattr(transition.state_mod, "save", lambda st: None)

    transition.mount("minecraft-server", log=lambda m: None)

    assert not lock.LOCK_PATH.exists()


def test_mount_conflict_refuses_before_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))

    TEMPLATES = {
        "pihole": {"ports": ["53/tcp"]},
        "jellyfin": {"ports": ["53/tcp"]},  # collides with mounted pihole
    }
    monkeypatch.setattr(transition, "_load_template",
                        lambda name: TEMPLATES[name])
    monkeypatch.setattr(transition, "load_answers", lambda name: {"a": 1})

    with pytest.raises(TransitionError) as exc:
        transition.mount("jellyfin", log=lambda m: None)

    assert "pihole" in str(exc.value)
    assert "reconfigure" in str(exc.value)
    assert not lock.LOCK_PATH.exists()  # refused BEFORE the lock


def test_mount_invalid_answers_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state([]))
    template = {
        "questions": [
            {"id": "web_port", "type": "integer", "validate": "1024-65535"}
        ]
    }
    monkeypatch.setattr(transition, "_load_template", lambda name: template)

    with pytest.raises(TransitionError) as exc:
        transition.mount("jellyfin", answers={"web_port": 53}, log=lambda m: None)

    assert "web_port" in str(exc.value)
    assert "reconfigure" in str(exc.value)
    assert not lock.LOCK_PATH.exists()


def test_mount_failure_rolls_back_partial_only(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    monkeypatch.setattr(
        transition, "load_answers",
        lambda name: {"pihole": {"web_port": 8080},
                      "syncthing": {"web_port": 8384}}[name],
    )
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: None)
    monkeypatch.setattr(transition, "_run_hooks", lambda c, l, answers=None: None)
    downs = []
    monkeypatch.setattr(
        transition, "_compose_down",
        lambda role, log, strict=False: downs.append(role),
    )
    removes = []
    monkeypatch.setattr(transition.caddy_mod, "remove_route",
                        lambda m, log: removes.append(m))
    monkeypatch.setattr(
        transition, "_compose_up",
        lambda role, log: (_ for _ in ()).throw(TransitionError("up failed")),
    )
    saves = _no_save(monkeypatch)

    with pytest.raises(TransitionError):
        transition.mount("syncthing", log=lambda m: None)

    assert downs == ["syncthing"]        # the PARTIAL new stack downed
    assert removes == ["syncthing"]      # its caddy section removed
    assert saves == []                   # mounted set never persisted


def test_keyboard_interrupt_rolls_back_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state([]))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"port": 25565})
    rolled = []
    monkeypatch.setattr(transition, "_rollback_partial",
                        lambda m, log: rolled.append(m))
    monkeypatch.setattr(
        transition, "_execute_mount",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        transition.mount("minecraft-server", log=lambda m: None)

    assert rolled == ["minecraft-server"]
    assert not lock.LOCK_PATH.exists()


def test_switch_is_alias_of_mount():
    assert transition.switch is transition.mount


def test_mount_reloads_state_after_lock(tmp_path, monkeypatch):
    # Mount A runs long (docker up takes minutes).  Mount B's PRE-lock
    # snapshot was stale; after winning the lock it must re-read the set
    # or it would save A away.
    loads = [
        _state([]),                       # B's pre-lock read (A not saved yet)
        _state(["minecraft-server"]),     # B's post-lock read (A already saved)
    ]
    monkeypatch.setattr(transition.state_mod, "load", lambda: loads.pop(0))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"a": 1})
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: None)
    monkeypatch.setattr(transition, "_run_hooks", lambda c, l, answers=None: None)
    monkeypatch.setattr(transition, "_compose_up", lambda role, log: None)
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: None)
    saved = []
    monkeypatch.setattr(transition.state_mod, "save", lambda st: saved.append(st))

    transition.mount("syncthing", answers={"web_port": 8384}, log=lambda m: None)

    assert saved[0].mounted == ["minecraft-server", "syncthing"]  # A survived


def test_mount_already_mounted_after_lock_releases_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    loads = [
        _state([]),                    # pre-lock: not mounted yet
        _state(["syncthing"]),         # post-lock: another op mounted it first
    ]
    monkeypatch.setattr(transition.state_mod, "load", lambda: loads.pop(0))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"a": 1})
    executed = []
    monkeypatch.setattr(transition, "_execute_mount",
                        lambda *a, **k: executed.append(True))

    transition.mount("syncthing", answers={"web_port": 8384}, log=lambda m: None)

    assert executed == []
    assert not lock.LOCK_PATH.exists()


def test_dismount_reloads_state_after_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    loads = [
        _state(["pihole"]),   # pre-lock: still mounted
        _state([]),           # post-lock: another op dismounted it first
    ]
    monkeypatch.setattr(transition.state_mod, "load", lambda: loads.pop(0))

    with pytest.raises(TransitionError) as exc:
        transition.dismount("pihole", log=lambda m: None)

    assert "not mounted" in str(exc.value)
    assert not lock.LOCK_PATH.exists()


# ---------------------------------------------------------------------------
# dismount — freezes exactly one module
# ---------------------------------------------------------------------------

def test_dismount_freezes_exactly_one(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load",
                        lambda: _state(["pihole", "syncthing"]))
    monkeypatch.setattr(transition, "load_answers", lambda name: {"n": name})
    monkeypatch.setattr(transition, "_run_hooks", lambda c, l, answers=None: None)
    downs = []
    monkeypatch.setattr(
        transition, "_compose_down",
        lambda role, log, strict=False: downs.append((role, strict)),
    )
    removes = []
    monkeypatch.setattr(transition.caddy_mod, "remove_route",
                        lambda m, log: removes.append(m))
    saved_states = []
    monkeypatch.setattr(
        transition.state_mod, "save", lambda st: saved_states.append(st)
    )

    transition.dismount("pihole", log=lambda m: None)

    assert downs == [("pihole", True)]     # strict stop of exactly this one
    assert removes == ["pihole"]           # only its caddy section
    assert saved_states[0].mounted == ["syncthing"]


def test_dismount_refuses_unmounted(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    with pytest.raises(TransitionError):
        transition.dismount("jellyfin", log=lambda m: None)


# ---------------------------------------------------------------------------
# reconfigure — live-apply mounted, answers-only dormant
# ---------------------------------------------------------------------------

def test_reconfigure_dormant_rewrites_answers_only(tmp_path, monkeypatch):
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "transition.lock")
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state([]))
    template = {"questions": []}
    monkeypatch.setattr(transition, "_load_template", lambda name: template)
    saved = []
    monkeypatch.setattr(transition, "save_answers",
                        lambda role, answers: saved.append((role, answers)))

    transition.reconfigure("syncthing", answers={"web_port": 8300},
                           log=lambda m: None)

    assert saved == [("syncthing", {"web_port": 8300})]
    assert not lock.LOCK_PATH.exists()  # dormant: no lock, nothing started


def test_reconfigure_mounted_recreates_stack(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    template = {"questions": []}
    monkeypatch.setattr(transition, "_load_template", lambda name: template)
    monkeypatch.setattr(transition, "load_answers", lambda name: {"web_port": 8080})
    ops = []
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: ops.append(("write", role, answers)) or tmp_path / "c.yml")
    monkeypatch.setattr(
        transition, "_compose_down",
        lambda role, log, strict=False: ops.append(("down", role)),
    )
    monkeypatch.setattr(transition, "_compose_up",
                        lambda role, log: ops.append(("up", role)))
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: ops.append(("caddy", m, a)))
    monkeypatch.setattr(transition, "save_answers",
                        lambda role, answers: ops.append(("answers", role, answers)))

    transition.reconfigure("pihole", answers={"web_port": 8081}, log=lambda m: None)

    assert ops == [("write", "pihole", {"web_port": 8081}), ("down", "pihole"),
                   ("up", "pihole"), ("caddy", "pihole", {"web_port": 8081}),
                   ("answers", "pihole", {"web_port": 8081})]
    assert not lock.LOCK_PATH.exists()


def test_reconfigure_failure_restores_previous_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    monkeypatch.setattr(transition, "_load_template", lambda name: {"questions": []})
    monkeypatch.setattr(transition, "load_answers", lambda name: {"web_port": 8080})
    ops = []
    ups = {"count": 0}

    def write(role, answers):
        ops.append(("write", dict(answers)))

    def up(role, log):
        ups["count"] += 1
        if ups["count"] == 1:
            raise TransitionError("up failed")   # the NEW stack fails
        ops.append(("up",))                       # the restore succeeds

    monkeypatch.setattr(transition, "write_compose", write)
    monkeypatch.setattr(transition, "_compose_down",
                        lambda role, log, strict=False: ops.append(("down", role)))
    monkeypatch.setattr(transition, "_compose_up", up)
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: ops.append(("caddy", dict(a))))
    saved_answers = []
    monkeypatch.setattr(transition, "save_answers",
                        lambda role, answers: saved_answers.append(dict(answers)))
    saved_states = []
    monkeypatch.setattr(transition.state_mod, "save",
                        lambda st: saved_states.append(st))
    logs: list[str] = []

    with pytest.raises(TransitionError):
        transition.reconfigure(
            "pihole", answers={"web_port": 8081}, log=logs.append)

    # The OLD configuration was rendered, restarted, and re-routed.
    assert ("write", {"web_port": 8080}) in ops
    assert ("up",) in ops
    assert ("caddy", {"web_port": 8080}) in ops
    # The NEW answers were never persisted; the set still says mounted.
    assert saved_answers == []
    assert saved_states == []
    assert any("restored" in m for m in logs)


def test_reconfigure_failure_restore_fails_leaves_dismounted(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["pihole"]))
    monkeypatch.setattr(transition, "_load_template", lambda name: {"questions": []})
    monkeypatch.setattr(transition, "load_answers", lambda name: {"web_port": 8080})
    monkeypatch.setattr(transition, "write_compose",
                        lambda role, answers: tmp_path / "c.yml")
    monkeypatch.setattr(transition, "_compose_down",
                        lambda role, log, strict=False: None)

    def always_fail(role, log):
        raise TransitionError("docker is gone")

    monkeypatch.setattr(transition, "_compose_up", always_fail)
    monkeypatch.setattr(transition.caddy_mod, "upsert_route",
                        lambda m, a, log: None)
    monkeypatch.setattr(transition, "save_answers", lambda role, answers: None)
    saved_states = []
    monkeypatch.setattr(transition.state_mod, "save",
                        lambda st: saved_states.append(st))
    logs: list[str] = []

    with pytest.raises(TransitionError):
        transition.reconfigure(
            "pihole", answers={"web_port": 8081}, log=logs.append)

    # Restore failed: the module is de facto dismounted — say so, and
    # make status tell the truth.
    assert saved_states and saved_states[0].mounted == []
    assert any("DISMOUNTED" in m for m in logs)


def test_dismount_failure_runs_rollback_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(transition.state_mod, "load", lambda: _state(["nextcloud"]))
    template = {
        "hooks": {
            "pre_remove": ["maintenance:mode --on"],
            "rollback": ["maintenance:mode --off"],
        }
    }
    monkeypatch.setattr(transition, "_load_template", lambda name: template)
    monkeypatch.setattr(transition, "load_answers", lambda name: {"domain": "x"})
    hooks_seen = []
    monkeypatch.setattr(
        transition, "_run_hooks",
        lambda cmds, log, answers=None: hooks_seen.append(list(cmds)),
    )

    def strict_down_fails(role, log, strict=False):
        raise TransitionError("compose down failed")

    monkeypatch.setattr(transition, "_compose_down", strict_down_fails)
    monkeypatch.setattr(transition.caddy_mod, "remove_route",
                        lambda m, log: None)
    monkeypatch.setattr(transition.state_mod, "save", lambda st: None)

    with pytest.raises(TransitionError):
        transition.dismount("nextcloud", log=lambda m: None)

    # pre_remove ran, then — because the stop failed — the rollback:
    # hooks undid its damage (Nextcloud's maintenance:mode --off).
    assert hooks_seen == [["maintenance:mode --on"], ["maintenance:mode --off"]]


# ---------------------------------------------------------------------------
# compose helpers
# ---------------------------------------------------------------------------

def test_compose_down_strict_raises(tmp_path, monkeypatch):
    import subprocess as sp
    from types import SimpleNamespace

    monkeypatch.setattr(transition, "PLATYPUS_ROLES_DIR", tmp_path)
    compose = tmp_path / "minecraft-server" / "docker-compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services: {}\n", encoding="utf-8")

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="docker: boom")

    monkeypatch.setattr(sp, "run", run)

    logs: list[str] = []
    with pytest.raises(TransitionError):
        transition._compose_down("minecraft-server", logs.append, strict=True)
    transition._compose_down("minecraft-server", logs.append, strict=False)  # no raise
