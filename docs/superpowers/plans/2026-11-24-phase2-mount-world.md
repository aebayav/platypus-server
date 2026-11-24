# Phase 2 — The Mount/Dismount World (0.3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The server becomes a mounted set of modules: `platypus mount`, `platypus dismount`, `platypus reconfigure` with declared port claims, mount-time conflict detection, enforced validation, state schema v2, and the recipe/roles → recipe/modules rename — released as 0.3.0.

**Architecture:** Every module declares `ports:` and `weight:` in `template.yml`; new `recipe/claims.py` resolves claims (placeholder-aware) and detects conflicts against the mounted set before anything is stopped. `recipe/validate.py` enforces the existing (currently dead) `"N-M"` question ranges at form time and at mount time on the effective answer set. `state.yml` moves to schema v2 (`mounted: [names]`, auto-migrating from v1 with a backup). The caddy snippet becomes a multi-section managed file (upsert/remove per module). `transition.py` grows three engine operations — `mount` (additive, switch becomes its deprecated alias), `dismount` (stop+freeze exactly one), `reconfigure` (form+validate+conflict-recheck; live-apply when mounted, answers-only when dormant). The dashboard's module-state reader learns v2 (v1 fallback). Packaged templates move to `recipe/modules/`; runtime dirs stay `/opt/platypus/roles/`.

**Tech Stack:** Python 3.10+ stdlib + PyYAML; pytest with the established subprocess-monkeypatch + `tests/conftest.py` runtime-path isolation; yamllint for template hygiene.

**Spec:** `docs/superpowers/specs/2026-11-23-modular-mount-system-design.md` — Phase 2 section + the switch=alias-of-mount ruling + state-v2/dashboard-reader/reconfigure/validate/claims rulings recorded in the approved doc.

## Global Constraints

- **Preconditions met:** v0.2.0 published, wave-2 merged (both done — this plan builds on main `83a1c78`).
- **Vocabulary:** user-facing words become module/mount/dismount. `platypus switch <m>` is a **pure alias of mount** (additive; documented as deprecated spelling) — the user explicitly overruled replace-semantics.
- **State v2 shape:** `{schema_version: "2", mounted: [names], history: [...]}` — no `active`, no top-level `activated_at`, no `transition_lock`; loader migrates v1 (`active` → `mounted: [active]`) automatically with the one-generation `.bak` backup and writes the migrated file back. Per-module activation time comes from `history` (last entry without `deactivated_at`).
- **Port claims:** `template.yml` gains `ports:` — a list of strings `"<port>[/tcp|/udp]"` where `<port>` is an integer or a `{answers[key]}` placeholder; default protocol `tcp`. Two modules conflict only on same port + same protocol. Claims carry a `weight: main|companion` label (recommendation only, engine ignores it).
- **Validate syntax:** integer ranges `"N-M"` only (the sole form existing templates use). Enforcement points: interactive form AND mount/reconfigure pre-flight against the effective answer set; refusal text points at `platypus reconfigure <module>`.
- **Runtime layout unchanged:** `/opt/platypus/roles/<name>/` and answers.yml keep their paths; the packaged source dir becomes `recipe/modules/`.
- **Caddy file:** one managed multi-section file; each section marked `# begin module: <name>` / `# end module: <name>`; an empty managed file keeps the `# platypus — no active HTTP route` header; reload failures log, never abort.
- Old alias `platypus-server` and `--force-unlock` keep working; Python 3.10–3.13; CI must stay green; engine tests never touch Docker or the real `/opt` (conftest fixture already provides isolation).
- Version **0.3.0**. YAML template edits must stay yamllint-clean (warnings for missing `---` are accepted, as today).

## Review Focus

1. **Mounting a port-conflicting module must refuse BEFORE stopping anything** — resolve claims against effective answers and the mounted set pre-lock, with an actionable refusal naming the conflicting module (Task 2 conflict tests + Task 6 pre-flight order test).
2. **Dismount freezes exactly one module** — others keep running; its Caddy section disappears, its data and answers stay (Task 6 `test_dismount_freezes_exactly_one`).
3. **A 0.2 state.yml upgrades silently and losslessly** — v1 `active: minecraft-server` becomes `mounted: [minecraft-server]`, `.bak` keeps the original, every command works before and after (Task 3 migration tests).
4. **A hand-edited invalid answer refuses at mount, not mid-switch** — e.g. `web_port: 53` on a validate `1024-65535` question (Task 1 effective-set test + Task 6 pre-flight).
5. **The dashboard must not lie after upgrade** — `/api/recipe` reports the mounted set from v2 (and still works on a v1 file) (Task 4 tests).

---

### Task 1: Validation engine (`recipe/validate.py`)

**Files:**
- Create: `recipe/validate.py`
- Modify: `recipe/cli.py` (`_collect_answers` — enforce ranges in the form loop)
- Test: `tests/test_validate.py` (new)

**Interfaces:**
- Produces:
  - `parse_range(spec: str) -> tuple[int, int]` — `"1024-65535"` → `(1024, 65535)`; raises `ValueError` on malformed specs
  - `check_answer(question: dict, value) -> str | None` — returns an error message or `None`; integer-type questions with `validate` reject non-int or out-of-range values; other types pass (YAGNI: no regex support — no template uses it)
  - `validate_answers(questions: list[dict], answers: dict) -> list[str]` — messages for every violated question; unknown question ids in `answers` are ignored
- `recipe.cli._collect_answers` now calls `check_answer` in its retry loop with the same "✗" UX.

- [ ] **Step 1: Write the failing test `tests/test_validate.py`**

```python
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
```

- [ ] **Step 2: Run to verify it fails** — Run: `pytest tests/test_validate.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `recipe/validate.py` per Interfaces; wire `check_answer` into `recipe/cli._collect_answers`** (retry loop prints the returned message instead of only the int-coercion error).
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite.
- [ ] **Step 5: Commit** — `feat: enforce questions.yml validate ranges (form + pre-flight API)`

---

### Task 2: Claims and conflicts (`recipe/claims.py`)

**Files:**
- Create: `recipe/claims.py`
- Test: `tests/test_claims.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Claim = tuple[int, str]`  # (port, "tcp" | "udp")
  - `parse_ports_entry(entry: str) -> dict` — `"53/udp"`, `"8080"`, `"{answers[web_port]}/tcp"` → `{"port": str, "proto": "tcp"|"udp"}`; malformed → `ValueError`
  - `resolve_claims(template: dict, answers: dict) -> set[Claim]` — resolves `{answers[key]}` placeholders against *answers* (missing key → `KeyError`); rendered port must be a positive int; returns the set of (port, proto)
  - `find_conflicts(new_name: str, new_claims: set[Claim], mounted: dict[str, set[Claim]]) -> list[str]` — sorted human messages `"port 53/tcp is already used by 'pihole'"`; a module mounting over its own claims never conflicts

- [ ] **Step 1: Write the failing test `tests/test_claims.py`**

```python
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
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module missing).
- [ ] **Step 3: Implement `recipe/claims.py` per Interfaces.**
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite.
- [ ] **Step 5: Commit** — `feat: port claims with placeholder resolution and conflict detection`

---

### Task 3: State schema v2 (`recipe/state.py`)

**Files:**
- Modify: `recipe/state.py`, `recipe/model.py` (State dataclass)
- Test: extend `tests/test_state_durability.py`

**Interfaces:**
- Produces:
  - `State` gains `mounted: list[str]` (default `[]`); `active`/`activated_at`/`transition_lock` fields REMOVED from the dataclass
  - `SCHEMA_VERSION = "2"`; `save()` serializes `{schema_version, mounted, history}` only
  - `load()`/`_load_from()`: v2 file → direct; v1 file (`schema_version` `"1"` or an `active` key) → migrate: `mounted = [active] if active else []`, print a one-line notice, persist the migrated file (through `atomic_write`, which keeps the old file as `.bak`), return
  - `State.mounted` is the source of truth everywhere (cli status, engine, dashboard)

- [ ] **Step 1: Write the failing tests (append to `tests/test_state_durability.py`)**

```python
def test_save_writes_schema_v2_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    st = state_mod.State(schema_version="2", mounted=["pihole"], history=[])
    state_mod.save(st)
    data = yaml.safe_load((tmp_path / "state.yml").read_text(encoding="utf-8"))
    assert set(data) == {"schema_version", "mounted", "history"}
    assert data["mounted"] == ["pihole"]


def test_load_migrates_v1_with_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    monkeypatch.setattr(state_mod, "STATE_BACKUP", tmp_path / "state.yml.bak")
    v1 = {"schema_version": "1", "active": "minecraft-server",
          "activated_at": None, "transition_lock": None, "history": []}
    (tmp_path / "state.yml").write_text(yaml.safe_dump(v1), encoding="utf-8")
    st = state_mod.load()
    assert st.mounted == ["minecraft-server"]
    assert (tmp_path / "state.yml.bak").read_text(encoding="utf-8") == yaml.safe_dump(v1)
    data = yaml.safe_load((tmp_path / "state.yml").read_text(encoding="utf-8"))
    assert data["schema_version"] == "2"


def test_load_v1_without_active_is_empty_mounted(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.yml")
    (tmp_path / "state.yml").write_text(
        yaml.safe_dump({"schema_version": "1", "active": None, "history": []}),
        encoding="utf-8",
    )
    assert state_mod.load().mounted == []
```

- [ ] **Step 2: Run to verify they fail** — FAIL (State has no `mounted`).
- [ ] **Step 3: Implement** per Interfaces (migration lives in `_load_from`; keep corrupt-file/backup fallback from 0.2.1 intact — v1-shape check happens inside the same try). Update every in-repo constructor of `State(...)` (tests, engine) to the new field set in their own tasks; this task updates only `recipe/` call sites: `transition.py`, `cli.py` via later tasks — for now adapt minimally so the module imports and existing `from recipe import state` users still run (grep `State(` and fix).
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite (other tasks' tests updated in their own steps; engine/cli tests adapted here only where compilation requires).
- [ ] **Step 5: Commit** — `feat!: state schema v2 (mounted set) with automatic v1 migration`

---

### Task 4: Dashboard module-state reader (v2 with v1 fallback)

**Files:**
- Create: `dashboard/recipe_state.py`
- Modify: `dashboard/app.py:392-465` (`api_recipe` becomes a thin wrapper)
- Test: `tests/test_dashboard_recipe_state.py` (new)

**Interfaces:**
- Produces: `dashboard.recipe_state.read(state_file: Path, roles_dir: Path) -> dict` — returns `{"mounted": [{"name", "activated_at", "data_size_mb"}], "dormant": [{"name", "configured", "last_active", "data_size_mb"}], "history": [...]}`; reads v2 `mounted`, falls back to v1 `active` (single-entry list); missing/corrupt file → empty values; never raises.
- `api_recipe` calls it and returns `jsonify(...)`; the response keeps `history[-10:]`.

- [ ] **Step 1: Write the failing test `tests/test_dashboard_recipe_state.py`**

```python
"""Dashboard module-state reader: v2 mounted set, v1 fallback, robustness."""

import yaml

from dashboard import recipe_state


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_reads_v2_mounted(tmp_path):
    _write(tmp_path / "state.yml",
           {"schema_version": "2", "mounted": ["pihole", "syncthing"], "history": []})
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [m["name"] for m in out["mounted"]] == ["pihole", "syncthing"]
    assert out["dormant"] == []


def test_v1_fallback_active_becomes_single_mounted(tmp_path):
    _write(tmp_path / "state.yml",
           {"schema_version": "1", "active": "jellyfin", "history": []})
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [m["name"] for m in out["mounted"]] == ["jellyfin"]


def test_missing_and_corrupt_files_do_not_raise(tmp_path):
    assert recipe_state.read(tmp_path / "nope.yml", tmp_path / "roles")["mounted"] == []
    (tmp_path / "state.yml").write_text("{corrupt", encoding="utf-8")
    assert recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")["mounted"] == []


def test_dormant_lists_unmounted_runtime_dirs(tmp_path):
    _write(tmp_path / "state.yml", {"schema_version": "2", "mounted": ["pihole"], "history": []})
    rdir = tmp_path / "roles" / "minecraft-server"
    (rdir / "data").mkdir(parents=True)
    (rdir / "answers.yml").write_text("role: minecraft-server\n", encoding="utf-8")
    out = recipe_state.read(tmp_path / "state.yml", tmp_path / "roles")
    assert [d["name"] for d in out["dormant"]] == ["minecraft-server"]
    assert out["dormant"][0]["configured"] is True
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module missing).
- [ ] **Step 3: Implement `dashboard/recipe_state.py`; rewrite `api_recipe` as the wrapper.**
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite.
- [ ] **Step 5: Commit** — `feat: dashboard module-state reader for schema v2 (v1 fallback)`

---

### Task 5: Caddy multi-section manager

**Files:**
- Modify: `recipe/caddy.py`
- Test: extend `tests/test_caddy.py`

**Interfaces:**
- Produces:
  - `upsert_route(module: str, answers: dict, log) -> None` — renders the module's route and (re)writes its marked section; module without enabled caddy → its section is *absent* (others untouched); reload once
  - `remove_route(module: str, log) -> None` — deletes the module's section (missing section: no-op); writes back; reload once
  - Managed file layout: header `# platypus — auto-managed, do not edit manually`, then per module `# begin module: <name>` … `# end module: <name>`; no sections → header only (`# platypus — no active HTTP route` line)
  - `update(role_name, answers, log)` is DELETED (call sites move in Tasks 6-7)
  - `_reload` and its failure-logging behavior unchanged
- Existing tests referencing `update()` are rewritten in this task to the new API.

- [ ] **Step 1: Write the failing tests (replace the `update()`-era tests in `tests/test_caddy.py`)**

```python
def test_upsert_then_remove_roundtrip(tmp_path, monkeypatch):
    snippet = tmp_path / "platypus.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    _fake_run(monkeypatch)
    monkeypatch.setattr(
        caddy, "_caddy_section",
        lambda name: {"enabled": True, "route": "{answers[domain]} {{\n    reverse_proxy localhost:{answers[p]}\n}}"},
    )
    caddy.upsert_route("jellyfin", {"domain": "jf.x.com", "p": 8096}, lambda m: None)
    caddy.upsert_route("pihole", {"domain": "pi.x.com", "p": 8080}, lambda m: None)
    content = snippet.read_text(encoding="utf-8")
    assert "# begin module: jellyfin" in content and "jf.x.com" in content
    assert "# begin module: pihole" in content and "pi.x.com" in content

    caddy.remove_route("jellyfin", lambda m: None)
    content = snippet.read_text(encoding="utf-8")
    assert "jellyfin" not in content and "pi.x.com" in content


def test_upsert_without_route_is_absent_not_clearing(tmp_path, monkeypatch):
    snippet = tmp_path / "platypus.conf"
    monkeypatch.setattr(caddy, "CADDYFILE_PATH", snippet)
    _fake_run(monkeypatch)
    monkeypatch.setattr(caddy, "_caddy_section", lambda name: None)
    caddy.upsert_route("minecraft-server", {}, lambda m: None)
    assert snippet.read_text(encoding="utf-8") == "# platypus — no active HTTP route\n"
```

- [ ] **Step 2: Run to verify they fail** — FAIL (functions missing).
- [ ] **Step 3: Implement `upsert_route`/`remove_route`** — read current file, splice the marked section (regex-tolerant parsing), atomic write, one reload; delete `update()`.
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite (transition.py's `update` call sites are fixed in Task 6; until then the suite must be adapted: this task also applies the minimal mechanical edit to `transition.py`/`cli.py` so the suite imports — replacing `caddy_mod.update(...)` calls with `caddy_mod.upsert_route(...)` keeps behavior for the single-module era and lets Task 6 own the real restructure).
- [ ] **Step 5: Commit** — `feat: caddy snippet becomes a multi-section managed file`

---

### Task 6: Engine — `mount()` (additive) and rollback-as-partial-dismount

**Files:**
- Modify: `recipe/transition.py`
- Test: extend `tests/test_transition.py`

**Interfaces:**
- Consumes: Tasks 1-3, 5 (`validate_answers`, `resolve_claims`/`find_conflicts`, `State.mounted`, `upsert_route`).
- Produces:
  - `mount(new_module: str, answers: dict | None = None, log=print, force_unlock: bool = False) -> None`
    1. `state = load()`; template via `_load_template`
    2. answers: given, or `load_answers`, or `TransitionError` (form runs at CLI layer, as today)
    3. **Pre-flight before lock:** `validate_answers(template questions, answers)` → refuse listing violations (point at `platypus reconfigure`); `resolve_claims` → `find_conflicts` against `mounted` → refuse naming module+port
    4. lock acquire (as 0.2.1) → phases: data dir, compose render, `pre_apply`, `_compose_up`, `upsert_route`, `post_apply`, `save_answers`, `state.mounted.append`, history append, save → finally release
    5. Failure of ANY step → `_rollback_partial(new_module, log)`: best-effort `_compose_down(new_module)` + `remove_route(new_module)` + guarded steps, never raises; lock released in `finally`
  - `dismount(module: str, log=print, force_unlock: bool = False) -> None` — module not mounted → `TransitionError`; lock → `pre_remove` hooks (current answers), strict `_compose_down`, `remove_route`, history deactivate, `state.mounted.remove`, save → release. Failure before state save leaves the module mounted.
  - `reconfigure(module: str, log=print, force_unlock: bool = False) -> None`
    - dormant: `save_answers` (new answers come from the CLI form) after `validate_answers`; nothing started
    - mounted: pre-flight validate + conflict-check against mounted-minus-self → lock → strict `_compose_down(module)` → compose up (fresh answers) → `upsert_route` → `save_answers` → release; failure → `_rollback_partial` + state unchanged
  - `switch = mount` (module-level alias; docstring marks it deprecated)
- Existing engine tests are updated in this task to the new call shapes (same hermetic style).

- [ ] **Step 1: Write the failing tests (rewrite the engine-era sections of `tests/test_transition.py` to v2)** — key cases:

```python
def test_mount_is_additive(tmp_path, monkeypatch): ...
    # two modules end up mounted; the first never stopped
def test_mount_conflict_refuses_before_lock(tmp_path, monkeypatch): ...
    # mounted pihole claims 53; mounting a fake claiming 53 raises
    # TransitionError naming pihole; lock never created
def test_mount_invalid_answers_refused(tmp_path, monkeypatch): ...
    # web_port 53 against range question -> TransitionError, nothing touched
def test_mount_failure_rolls_back_partial_only(tmp_path, monkeypatch): ...
    # up fails -> new module downed + route removed; mounted set unchanged
def test_dismount_freezes_exactly_one(tmp_path, monkeypatch): ...
    # mounted [pihole, syncthing]; dismount pihole -> [syncthing];
    # pihole pre_remove hooks ran with pihole answers; caddy lost only pihole
def test_reconfigure_dormant_rewrites_answers_only(tmp_path, monkeypatch): ...
def test_reconfigure_mounted_recreates_stack(tmp_path, monkeypatch): ...
def test_switch_is_alias_of_mount(): assert transition.switch is transition.mount
```

*(The implementer writes full bodies in the established `_fake_procs`/monkeypatch style; the case list above is the contract.)*
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `mount`/`dismount`/`reconfigure`/`_rollback_partial` per Interfaces; delete the v1 `_execute`/`_rollback` switch flow.**
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite.
- [ ] **Step 5: Commit** — `feat!: engine becomes mount/dismount/reconfigure over the mounted set`

---

### Task 7: CLI — mount/dismount/reconfigure subcommands; status v2

**Files:**
- Modify: `recipe/cli.py`
- Modify: `platypus_cli/cli.py` (SUBCOMMANDS)
- Test: extend `tests/test_cli_entries.py`, `tests/test_platypus_cli.py`

**Interfaces:**
- Produces:
  - `recipe.cli.main` subcommands: `mount <module> [--force-unlock]`, `dismount <module> [--force-unlock]`, `reconfigure <module> [--force-unlock]`, `switch <module> [--force-unlock]` (help text marks it as the deprecated alias of mount), `status`
  - `mount`/`reconfigure` run `_collect_answers` (validate-enforced) when no saved answers exist; `mount` reuses saved answers silently; `reconfigure` ALWAYS re-runs the form pre-filled with defaults from the current answers (simplest deterministic UX: defaults = current saved values)
  - `_cmd_status` prints: mounted set (with per-module activation time from history), dormant runtime dirs (configured/data state), lock line as today, history tail
  - `platypus_cli.SUBCOMMANDS` gains `"mount"`, `"dismount"`, `"reconfigure"` → `recipe.cli` with prefix injection like switch/status
  - `USAGE` text updated; `--version` regex bump happens in Task 11

- [ ] **Step 1: Write the failing tests** — routing cases for the three new subcommands in `test_platypus_cli` (parametrized forwards), plus `recipe_cli.main(["mount", ...])` with a faked `transition.mount` asserting form-vs-reuse behavior, `dismount` non-mounted refusal text, and a status smoke on an empty v2 state.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement per Interfaces.**
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite.
- [ ] **Step 5: Commit** — `feat: platypus mount/dismount/reconfigure CLI`

---

### Task 8: Template migrations — ports, weight, fixed Caddy routes

**Files:**
- Modify: all seven `recipe/roles/<name>/template.yml`
- Test: `tests/test_module_templates.py` (new)

**Interfaces:**
- Consumes: Task 2 (`resolve_claims`).
- Produces (the migration table — every module gains these blocks):

| module | `ports:` | `weight:` |
|---|---|---|
| minecraft-server | `["{answers[port]}/tcp"]` | `main` |
| pihole | `["53/tcp", "53/udp", "{answers[web_port]}/tcp"]` | `companion` |
| syncthing | `["{answers[web_port]}/tcp", "22000/tcp", "22000/udp", "21027/udp"]` | `companion` |
| jellyfin | `["{answers[web_port]}/tcp"]` | `main` |
| storage-nextcloud | `["{answers[http_port]}/tcp"]` | `main` |
| storage-samba | `["139/tcp", "445/tcp"]` | `companion` |
| assetto-corsa | `["{answers[tcp_port]}/tcp", "{answers[udp_port]}/udp", "{answers[http_port]}/tcp", "50041/tcp", "50042/tcp"]` | `main` |

- Caddy route targets switch from container hostnames to host ports (the audit's unreachable routes):
  - pihole/syncthing/jellyfin: `reverse_proxy localhost:{answers[web_port]}`
  - storage-nextcloud: `reverse_proxy localhost:{answers[http_port]} {{` (header_up block unchanged)

- [ ] **Step 1: Write the failing test `tests/test_module_templates.py`**

```python
"""All packaged templates carry claims and weight; routes target host ports."""

from recipe.claims import resolve_claims
from recipe.model import builtin_roles

SAMPLE_ANSWERS = {
    "port": 25565, "web_port": 8080, "http_port": 8081,
    "tcp_port": 9600, "udp_port": 9600,
}


def test_every_template_has_ports_and_weight():
    from recipe.transition import _load_template
    for name in builtin_roles():
        tmpl = _load_template(name)
        assert isinstance(tmpl.get("ports"), list) and tmpl["ports"], name
        assert tmpl.get("weight") in ("main", "companion"), name
        resolve_claims(tmpl, SAMPLE_ANSWERS)  # placeholder-resolvable


def test_http_routes_target_host_ports_not_containers():
    from recipe.transition import _load_template
    for name in ("pihole", "syncthing", "jellyfin", "storage-nextcloud"):
        route = _load_template(name)["caddy"]["route"]
        assert "localhost:" in route
        assert "platypus-" not in route.replace("platypus —", "")
```

- [ ] **Step 2: Run to verify they fail** (templates lack the fields; routes still use container names).
- [ ] **Step 3: Apply the migration table to the seven templates** (+ yamllint stays clean).
- [ ] **Step 4: Run tests to verify they pass** — targeted + full suite + `python -m yamllint recipe/roles/`.
- [ ] **Step 5: Commit** — `feat: module templates declare ports/weight; caddy routes target host ports`

---

### Task 9: Source rename `recipe/roles/` → `recipe/modules/`

**Files:**
- Move: `recipe/roles/<name>/` → `recipe/modules/<name>/` (git mv, seven dirs)
- Modify: `recipe/model.py` (`PACKAGED_ROLES_DIR` → `PACKAGED_MODULES_DIR = Path(__file__).parent / "modules"`; keep `REPO_ROLES_DIR` fallback name), `pyproject.toml` package-data globs, `tests/test_recipe_roles.py` (rename file to `tests/test_modules.py`), README directory tree
- Test: renamed suite

**Interfaces:**
- Produces: `recipe.model.PACKAGED_MODULES_DIR`; `role_dir()`/`builtin_roles()` semantics unchanged (lookup order packaged → repo fallback); runtime paths untouched.
- `grep -rn "recipe/roles"` after the move must return only `REPO_ROLES_DIR`-fallback comments and the runtime-dir references.

- [ ] **Step 1: Update the test file paths** (`tests/test_recipe_roles.py` imports read `PACKAGED_ROLES_DIR` — rename the test file to `tests/test_modules.py` and point its monkeypatches at `PACKAGED_MODULES_DIR`). Run — FAIL (constants missing).
- [ ] **Step 2: git mv the seven dirs; update model.py + pyproject globs + README tree.**
- [ ] **Step 3: Run the full suite + yamllint on `recipe/modules/`** — PASS.
- [ ] **Step 4: Commit** — `refactor: packaged templates move to recipe/modules (runtime dirs unchanged)`

---

### Task 10: README — mount/dismount vocabulary

**Files:**
- Modify: `README.md` (Components table, recipe section, command examples, tree already updated in Task 9)
- Test: grep asserts

**Interfaces:**
- Produces: docs say **module**, `platypus mount/dismount/reconfigure`; `switch` marked deprecated alias (additive); support matrix gains one line: "multiple modules may be mounted simultaneously — mount refuses port conflicts and points at reconfigure".

- [ ] **Step 1: Apply the wording changes** (quickstart example switches to `platypus mount minecraft-server`; "Server Roles" section becomes "Modules"; alias note updated).
- [ ] **Step 2: Verify** — `Select-String README.md "platypus mount"` ≥2; `Select-String README.md "deprecated"` present; `Select-String README.md "recipe/modules"` present; full suite still green.
- [ ] **Step 3: Commit** — `docs: mount/dismount vocabulary and multi-module semantics`

---

### Task 11: Release prep — 0.3.0

**Files:**
- Modify: `pyproject.toml` (version 0.3.0), `tests/test_packaging.py`, `tests/test_platypus_cli.py`
- Test: existing suites

- [ ] **Step 1: Bump the two version assertions to 0.3.0 + pyproject.**
- [ ] **Step 2: Re-install editable, full suite, `platypus --version` → 0.3.0.**
- [ ] **Step 3: Commit** — `release: 0.3.0 (the mount/dismount world)`
- [ ] **Step 4: Push + CI green (lint incl. bash -n, 3.10–3.13, wheel smoke).**

## Rollout

CI green → review with the author → tag `v0.3.0` (author's go, as established) → PyPI publish → VM smoke (multi-mount: pihole + syncthing companions + minecraft main; conflict refusal; reconfigure; v1-state migration on the existing VM is a real-user upgrade test). Phase 3 (community: module spec, `module init`, CI module checks, CONTRIBUTING/CHANGELOG/SECURITY) follows as its own plan.
