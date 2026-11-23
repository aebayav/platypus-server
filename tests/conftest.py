"""Suite-wide isolation for the recipe runtime paths.

Every test gets a private /opt/platypus equivalent under pytest's
tmp_path, so engine tests can never read from — or worse, write to —
the real runtime directory of the machine running the suite.  The
0.2.1 whole-branch review caught exactly that leak: an early engine
test left a real C:/opt/platypus behind on a dev box and then masked
its own non-hermeticity.
"""

import pytest


@pytest.fixture(autouse=True)
def _recipe_runtime_paths(tmp_path, monkeypatch):
    from recipe import caddy, cli, lock, renderer, state, transition

    platypus = tmp_path / "platypus"
    platypus.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(state, "PLATYPUS_DIR", platypus)
    monkeypatch.setattr(state, "STATE_FILE", platypus / "state.yml")
    monkeypatch.setattr(state, "STATE_BACKUP", platypus / "state.yml.bak")
    monkeypatch.setattr(lock, "LOCK_PATH", platypus / "transition.lock")
    monkeypatch.setattr(
        caddy, "CADDYFILE_PATH", platypus / "Caddyfile.d" / "platypus.conf"
    )
    for module in (renderer, transition, cli):
        monkeypatch.setattr(module, "PLATYPUS_ROLES_DIR", platypus / "roles")
