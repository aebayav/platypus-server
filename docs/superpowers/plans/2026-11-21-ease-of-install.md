# Ease of Install & Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger on GitHub can `pipx install platypus-server` and drive every tool through one `platypus` command, while the `curl | bash` bootstrap becomes a thin, re-run-safe wrapper around the PyPI package.

**Architecture:** The existing five tools keep their module layouts; a new `platypus_cli` package becomes the single console entry point and lazily forwards argv to each tool's `main()`. Role templates move inside the `recipe` package so wheels ship them. PyPI distribution is rebuilt around honest core dependencies; release automation publishes on tags; bootstrap installs the package via pipx into shared paths and keeps only the Ansible layer as a git clone.

**Tech Stack:** Python 3.10+, setuptools/pyproject packaging, pipx, GitHub Actions (build/publish via `pypa/gh-action-pypi-publish` trusted publishing), pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-ease-of-install-design.md` (approved 2026-11-20; read it alongside this plan — every value below traces to it).

## Global Constraints

- Distribution name: `platypus-server` (fallback `platypus-toolkit` is decided by the author at first publish only — do not design for it elsewhere).
- Version: `0.2.0`, single-sourced in `pyproject.toml`.
- Core dependencies after this plan: `textual>=0.77.0`, `pyyaml>=6.0`, `flask>=3.0`, `psutil>=5.9`. The only extra is `dev` (pytest + `tomli; python_version < "3.11"`). Ansible is never a package dependency.
- Recipe role templates live at `recipe/roles/<name>/{template.yml,questions.yml}`; resolution: packaged dir first, repo-root `roles/` fallback.
- All five old console scripts (`platypus-tui`, `platypus-dashboard`, `platypus-server`, `zero-to-server`, `platypus-doctor`) keep their exact current argument surfaces.
- `platypus` becomes the dispatcher; `platypus doctor` replaces bare `platypus <doctor-flags>` (the only breaking change, documented in README).
- Doctor `--allow-busy` downgrades ONLY port results whose detail contains "already in use"; every other FAIL stays a FAIL. Bootstrap passes it only when `/opt/platypus/state.yml` exists.
- Bootstrap constants: `PIPX_HOME=/opt/platypus/pipx`, `PIPX_BIN_DIR=/usr/local/bin`, package spec `"${PACKAGE_NAME}>=0.2"` with `PACKAGE_NAME="${PLATYPUS_PACKAGE:-platypus-server}"`.
- Python floor stays `>=3.10`; the full suite must pass on 3.10–3.13.
- No changes to `/opt/platypus` runtime state layout or `~/.config/platypus` config.
- Working directory is the repo root; the dev machine is Windows (use `.venv\Scripts\python` locally; CI runs Linux). After any `pyproject.toml` change, re-run the editable install before tests.

## Rollout order (spec C3 — affects when commits reach `main`, not how they are made)

1. **Wave 1 = Tasks 1–6** (package, dispatcher, doctor flag, CI/release). Merge to `main`.
2. Author completes one-time PyPI setup (confirm `platypus-server` name; configure trusted publisher for this repo).
3. Tag `v0.2.0` on `main`; the release workflow builds and publishes.
4. Author verifies: `pipx install platypus-server && platypus --version` on a clean machine.
5. **Wave 2 = Tasks 7–8** (bootstrap flip + README). Merge to `main` only after step 4 succeeds, so the public `curl | bash` one-liner is never broken.

## Review Focus

1. **Bare or unknown `platypus` invocation must print usage, not traceback** — `platypus` alone → usage + exit 0; `platypus frobnicate` → usage on stderr + exit 2. Pinned in Task 4 (`test_no_args_prints_usage`, `test_unknown_command_returns_two`).
2. **Old aliases must keep working after entry-point churn** — pyproject must retain all five scripts with unchanged targets, and `recipe.cli.main(["status"])` must return 0. Pinned in Task 1/Task 4 (`test_console_scripts_keep_aliases`) and Task 3 (`test_recipe_main_status_returns_zero`).
3. **A non-editable wheel must contain the role templates** — a wheel missing `recipe/roles/*/template.yml` would ship a `platypus switch` that always fails (today's bug). Pinned in Task 2 (`test_builtin_roles_match_readme`, fallback tests) and enforced end-to-end by the Task 6 package job probe.
4. **`--allow-busy` must not hide real problems** — non-port FAILs and port FAILs whose detail is NOT "already in use" (e.g. permission denied) still exit 1. Pinned in Task 5 (`test_allow_busy_keeps_other_failures`, `test_allow_busy_keeps_permission_failures`).
5. **Python 3.10 must still work** — 3.10 lacks `tomllib`; the packaging test imports `tomli` via the env-markered dev dependency, and the CI matrix includes 3.10. Pinned in Task 1 (`test_packaging_reads_pyproject` uses the markered import) and Task 6 (matrix).

---

### Task 1: Packaging metadata, honest dependencies, single-sourced version

**Files:**
- Modify: `pyproject.toml` (whole `[project]` + `[project.optional-dependencies]` + `[build-system]`)
- Modify: `dashboard/__init__.py:3`, `tui/__init__.py:3`, `zero2server/__init__.py:3`
- Modify: `scripts/install-dashboard-service.sh:40`
- Test: `tests/test_packaging.py` (new)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: dist name `platypus-server`, version `0.2.0`, core deps incl. `flask>=3.0` + `psutil>=5.9`, `textual>=0.77.0`; extras: `dev` only; every module exposes `__version__` read from installed metadata. Later tasks assume `importlib.metadata.version("platypus-server")` works after an editable install.

- [ ] **Step 1: Write the failing test `tests/test_packaging.py`**

```python
"""Packaging guarantees: name, version, deps, extras, entry points."""

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import dashboard
import tui
import zero2server

with open("pyproject.toml", "rb") as fh:
    PYPROJECT = tomllib.load(fh)


def test_distribution_name_and_version():
    assert PYPROJECT["project"]["name"] == "platypus-server"
    assert PYPROJECT["project"]["version"] == "0.2.0"


def test_core_dependencies_are_honest():
    deps = " ".join(PYPROJECT["project"]["dependencies"])
    assert "textual>=0.77.0" in deps
    assert "pyyaml>=6.0" in deps
    assert "flask>=3.0" in deps
    assert "psutil>=5.9" in deps


def test_removed_noop_and_dashboard_extras():
    extras = PYPROJECT["project"]["optional-dependencies"]
    assert "dashboard" not in extras
    assert "zero2server" not in extras
    assert "dev" in extras


def test_license_and_urls_metadata():
    assert PYPROJECT["project"]["license"] == "MIT"
    urls = " ".join(PYPROJECT["project"]["urls"].values())
    assert "github.com/aebayav/platypus-server" in urls


def test_init_versions_come_from_metadata():
    from importlib.metadata import version

    expected = version("platypus-server")
    assert dashboard.__version__ == expected
    assert tui.__version__ == expected
    assert zero2server.__version__ == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py -v` (venv python).
Expected: FAIL on name (`platypus-tui` ≠ `platypus-server`) and version.

- [ ] **Step 3: Rewrite `pyproject.toml` `[project]` sections; rewire the three `__version__` strings; drop the dead extra in `install-dashboard-service.sh`**

`pyproject.toml`: `name = "platypus-server"`, `version = "0.2.0"`,
`license = "MIT"` and `license-files = ["LICENSE"]`, `authors = [{ name = "aebayav" }]`,
`urls = { Homepage = "https://github.com/aebayav/platypus-server", Repository = ..., "Bug Tracker" = ... + "/issues" }`,
classifiers `Programming Language :: Python :: 3.10` … `:: 3.13` (no `License ::` classifier — PEP 639),
dependencies = `["textual>=0.77.0", "pyyaml>=6.0", "flask>=3.0", "psutil>=5.9"]`,
`[build-system] requires = ["setuptools>=77"]` (needed for the SPDX license field),
`optional-dependencies` = `dev = ["pytest>=8.0", 'tomli>=2.0; python_version < "3.11"']` (delete `dashboard`, `zero2server`). Leave `[project.scripts]` untouched in this task.

Each of the three `__init__.py` files gets:

```python
try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("platypus-server")
    except PackageNotFoundError:
        __version__ = "unknown"
except ImportError:  # pragma: no cover
    __version__ = "unknown"
```

`scripts/install-dashboard-service.sh:40`: `pip install -e ".[dashboard]"` → `pip install -e "."`.

- [ ] **Step 4: Re-install editable so entry points and metadata refresh**

Run: `python -m pip install -e .` (venv python; `.venv\Scripts\python` on Windows).
Expected: builds cleanly; `pip show platypus-server` reports 0.2.0.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: PASS (all 5).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (~45 tests; existing suites untouched).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml dashboard/__init__.py tui/__init__.py zero2server/__init__.py scripts/install-dashboard-service.sh tests/test_packaging.py
git commit -m "packaging: honest deps, platypus-server dist name, single-sourced version"
```

---

### Task 2: Ship recipe role templates inside the `recipe` package

**Files:**
- Move: `roles/<name>/{template.yml,questions.yml}` → `recipe/roles/<name>/` for the seven recipe roles (`minecraft-server`, `storage-nextcloud`, `storage-samba`, `pihole`, `syncthing`, `jellyfin`, `assetto-corsa`) — `git mv` each role dir
- Modify: `recipe/model.py:113-114`
- Modify consumers of the deleted constant: `recipe/cli.py:19,30`, `recipe/caddy.py:49,71`, `recipe/renderer.py:14,26`, `recipe/transition.py:45-50,64-71`
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]`)
- Test: `tests/test_recipe_roles.py` (new)

**Interfaces:**
- Produces in `recipe/model.py`:
  - `PACKAGED_ROLES_DIR: Path = Path(__file__).parent / "roles"` (ships in the wheel)
  - `REPO_ROLES_DIR: Path = Path(__file__).parent.parent / "roles"` (editable/dev fallback)
  - `role_dir(role_name: str) -> Path` — returns the first of the two dirs whose `<name>/template.yml` exists; raises `FileNotFoundError(f"no template.yml found for role {role_name!r}")` if neither does
  - `builtin_roles() -> list[str]` — sorted names of dirs containing `template.yml` across both bases
  - `ROLES_SOURCE_DIR` is deleted.
- Task 6's package job consumes `builtin_roles()`; Task 4's dispatcher relies on `recipe.cli` still working after the import change.

- [ ] **Step 1: Write the failing test `tests/test_recipe_roles.py`**

```python
"""Recipe role templates: discovery, packaged-first resolution, fallback."""

import pytest

import recipe.model as model

EXPECTED_ROLES = [
    "assetto-corsa",
    "jellyfin",
    "minecraft-server",
    "pihole",
    "storage-nextcloud",
    "storage-samba",
    "syncthing",
]


def test_builtin_roles_match_readme():
    assert model.builtin_roles() == EXPECTED_ROLES


def test_every_builtin_role_ships_both_files():
    for name in model.builtin_roles():
        d = model.role_dir(name)
        assert (d / "template.yml").is_file(), name
        assert (d / "questions.yml").is_file(), name


def _make_base(tmp_path, with_role: str | None) -> object:
    base = tmp_path / ("packaged" if with_role == "packaged" else "repo") / "roles"
    if with_role:
        (base / "demo").mkdir(parents=True)
        (base / "demo" / "template.yml").write_text("x: 1\n", encoding="utf-8")
    return base


def test_role_dir_prefers_packaged_dir(tmp_path, monkeypatch):
    packaged = tmp_path / "packaged"; (packaged / "demo").mkdir(parents=True)
    (packaged / "demo" / "template.yml").write_text("a: 1\n", encoding="utf-8")
    repo = tmp_path / "repo"; (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "template.yml").write_text("a: 2\n", encoding="utf-8")
    monkeypatch.setattr(model, "PACKAGED_ROLES_DIR", packaged)
    monkeypatch.setattr(model, "REPO_ROLES_DIR", repo)
    assert model.role_dir("demo") == packaged / "demo"


def test_role_dir_falls_back_to_repo_dir(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "template.yml").write_text("a: 1\n", encoding="utf-8")
    monkeypatch.setattr(model, "PACKAGED_ROLES_DIR", tmp_path / "empty")
    monkeypatch.setattr(model, "REPO_ROLES_DIR", repo)
    assert model.role_dir("demo") == repo / "demo"


def test_role_dir_unknown_role_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "PACKAGED_ROLES_DIR", tmp_path / "a")
    monkeypatch.setattr(model, "REPO_ROLES_DIR", tmp_path / "b")
    with pytest.raises(FileNotFoundError):
        model.role_dir("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recipe_roles.py -v`
Expected: FAIL — `model has no attribute builtin_roles`.

- [ ] **Step 3: Move the files and implement the resolution**

1. `mkdir recipe/roles` then for each of the seven roles: `git mv roles/<name> recipe/roles/<name>` (keeps history; `roles/` afterwards holds only the three Ansible roles).
2. In `recipe/model.py` replace lines 113-114 with `PACKAGED_ROLES_DIR`, `REPO_ROLES_DIR`, `role_dir()`, `builtin_roles()` per the Interfaces block.
3. Update consumers:
   - `recipe/cli.py`: import `role_dir` instead of `ROLES_SOURCE_DIR`; in `_collect_answers` wrap the lookup:
     ```python
     try:
         questions_file = role_dir(role_name) / "questions.yml"
     except FileNotFoundError as exc:
         raise SystemExit(f"Error: {exc}") from None
     ```
     (the existing `questions_file.exists()` guard below stays).
   - `recipe/transition.py` `_load_template`: `path = role_dir(role_name) / "template.yml"` inside `try/except FileNotFoundError: raise TransitionError(f"Role {role_name!r} not found") from None` (drops the old path-bearing message; keep raising `TransitionError`).
   - `recipe/caddy.py` `_caddy_section`: `try: path = role_dir(role_name) / "template.yml" except FileNotFoundError: return None` (preserves current missing→None semantics).
   - `recipe/renderer.py` `render_compose`: `template_path = role_dir(role_name) / "template.yml"` (called after transition validated the role; FileNotFoundError propagates as before).
4. `pyproject.toml`:
   ```toml
   [tool.setuptools.package-data]
   recipe = ["roles/*/template.yml", "roles/*/questions.yml"]
   dashboard = ["static/*"]
   ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recipe_roles.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Confirm nothing else used the old constant and the YAML still lints**

Run: `grep -rn "ROLES_SOURCE_DIR" --include="*.py" .` → only `recipe/model.py` definitions-free (no matches outside tests/mocks); `python -m yamllint recipe/roles/` → clean (if yamllint is not in the local venv, rely on the CI lint job).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add recipe/roles recipe/model.py recipe/cli.py recipe/caddy.py recipe/renderer.py recipe/transition.py pyproject.toml tests/test_recipe_roles.py
git commit -m "recipe: package role templates, packaged-first resolution with repo fallback"
```

---

### Task 3: `main(argv)` entry-point refactors

**Files:**
- Modify: `dashboard/app.py:470-475`
- Modify: `recipe/cli.py:190-213`
- Modify: `zero2server/cli.py:52-75`
- Test: `tests/test_cli_entries.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces (Task 4's dispatcher calls exactly these):
  - `dashboard.app.parse_dashboard_args(argv: list[str] | None = None) -> argparse.Namespace` with fields `host: str`, `port: int`; defaults from `DASHBOARD_HOST` / `DASHBOARD_PORT` env vars, else `"0.0.0.0"` / `5050`
  - `dashboard.app.main(argv: list[str] | None = None) -> None`
  - `recipe.cli.main(argv: list[str] | None = None) -> int` (returns `args.func(args)`; no internal `sys.exit`)
  - `zero2server.cli.main(argv: list[str] | None = None) -> None`
- Unchanged and already dispatcher-compatible: `doctor.main(argv) -> int`, `tui.app.main(argv) -> None`.

- [ ] **Step 1: Write the failing test `tests/test_cli_entries.py`**

```python
"""Entry-point refactors: every tool main() accepts argv."""

import pytest

from dashboard.app import parse_dashboard_args
from recipe import cli as recipe_cli
from zero2server import cli as z2s_cli


def test_dashboard_parse_args_flags():
    ns = parse_dashboard_args(["--host", "127.0.0.1", "--port", "6000"])
    assert ns.host == "127.0.0.1"
    assert ns.port == 6000


def test_dashboard_parse_args_env_defaults(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOST", "10.0.0.5")
    monkeypatch.setenv("DASHBOARD_PORT", "6060")
    ns = parse_dashboard_args([])
    assert ns.host == "10.0.0.5"
    assert ns.port == 6060


def test_dashboard_parse_args_hard_defaults(monkeypatch):
    monkeypatch.delenv("DASHBOARD_HOST", raising=False)
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    ns = parse_dashboard_args([])
    assert ns.host == "0.0.0.0"
    assert ns.port == 5050


def test_recipe_main_status_returns_zero(capsys):
    assert recipe_cli.main(["status"]) == 0
    assert "role" in capsys.readouterr().out.lower()


def test_recipe_main_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        recipe_cli.main(["--help"])
    assert exc.value.code == 0


def test_recipe_main_unknown_command_exits_two():
    with pytest.raises(SystemExit) as exc:
        recipe_cli.main(["bogus"])
    assert exc.value.code == 2


def test_zero2server_main_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        z2s_cli.main(["--help"])
    assert exc.value.code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_entries.py -v`
Expected: FAIL — `parse_dashboard_args` missing; `recipe.cli.main` rejects the argv arg.

- [ ] **Step 3: Implement the three refactors**

`dashboard/app.py` — replace `main()` (lines 472-475) with `parse_dashboard_args()` + a thin `main(argv=None)` that calls it and runs `app.run(host=..., port=..., debug=False)`; new argparse parser `prog="platypus dashboard"` with `--host` (str, env default) and `--port` (int, env default).

`recipe/cli.py` — `main(argv=None) -> int`; `args = parser.parse_args(argv)`; `return args.func(args)`; the `if __name__ == "__main__":` guard becomes `sys.exit(main())`.

`zero2server/cli.py` — `main(argv=None)`; `args = parser.parse_args(argv)`; rest of the function unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli_entries.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app.py recipe/cli.py zero2server/cli.py tests/test_cli_entries.py
git commit -m "cli: all tool mains accept argv; dashboard gains --host/--port flags"
```

---

### Task 4: Unified `platypus` dispatcher

**Files:**
- Create: `platypus_cli/__init__.py` (package docstring only)
- Create: `platypus_cli/cli.py`
- Modify: `pyproject.toml` (`[project.scripts]` `platypus` entry + `[tool.setuptools] packages`)
- Test: `tests/test_platypus_cli.py` (new); extend `tests/test_packaging.py`

**Interfaces:**
- Consumes: `doctor.main(argv) -> int`, `tui.app.main(argv) -> None`, `dashboard.app.main(argv) -> None`, `recipe.cli.main(argv) -> int`, `zero2server.cli.main(argv) -> None` (Tasks 1–3).
- Produces: `platypus_cli.cli.main(argv: list[str] | None = None) -> int`; module-level `SUBCOMMANDS: dict[str, tuple[str, str, str | None]]` mapping subcommand → (module, function, argv prefix); `_run(module_name: str, func_name: str, prefix: str | None, rest: list[str]) -> int` (the monkeypatch seam); `_version() -> str` (`"0.2.0"` from metadata, `"unknown"` if not installed).

- [ ] **Step 1: Write the failing test `tests/test_platypus_cli.py`**

```python
"""The unified `platypus` dispatcher: routing, usage, version."""

import re

import pytest

import platypus_cli.cli as cli


def test_subcommand_table():
    assert set(cli.SUBCOMMANDS) == {
        "doctor", "setup", "dashboard", "switch", "status", "generate",
    }


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["doctor", "--target", "vps"], ("doctor", "main", None, ["--target", "vps"])),
        (["setup", "--mode", "simple"], ("tui.app", "main", None, ["--mode", "simple"])),
        (["dashboard", "--port", "6000"], ("dashboard.app", "main", None, ["--port", "6000"])),
        (["switch", "minecraft-server"], ("recipe.cli", "main", "switch", ["minecraft-server"])),
        (["status"], ("recipe.cli", "main", "status", [])),
        (["generate", "--run"], ("zero2server.cli", "main", None, ["--run"])),
    ],
)
def test_forwards_argv_to_tool(argv, expected, monkeypatch):
    recorded = []

    def fake_run(module_name, func_name, prefix, rest):
        recorded.append((module_name, func_name, prefix, rest))
        return 0

    monkeypatch.setattr(cli, "_run", fake_run)
    assert cli.main(argv) == 0
    assert recorded == [expected]


def test_no_args_prints_usage(capsys):
    assert cli.main([]) == 0
    assert "usage: platypus" in capsys.readouterr().out


def test_unknown_command_returns_two(capsys):
    assert cli.main(["frobnicate"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert re.match(r"platypus (0\.2\.0|unknown)\b", capsys.readouterr().out)


def test_help_lists_every_subcommand(capsys):
    cli.main(["--help"])
    out = capsys.readouterr().out
    for name in cli.SUBCOMMANDS:
        assert name in out
```

Append to `tests/test_packaging.py`:

```python
def test_console_scripts_keep_aliases_and_new_dispatcher():
    scripts = PYPROJECT["project"]["scripts"]
    assert scripts["platypus"] == "platypus_cli.cli:main"
    assert scripts["platypus-doctor"] == "doctor:main"
    assert scripts["platypus-tui"] == "tui.app:main"
    assert scripts["platypus-dashboard"] == "dashboard.app:main"
    assert scripts["platypus-server"] == "recipe.cli:main"
    assert scripts["zero-to-server"] == "zero2server.cli:main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_platypus_cli.py tests/test_packaging.py -v`
Expected: FAIL — `platypus_cli` does not exist.

- [ ] **Step 3: Implement `platypus_cli/cli.py` and wire the entry point**

`platypus_cli/cli.py` — exact design:

```python
"""Unified `platypus` command: one entry point for every tool."""

from __future__ import annotations

import importlib
import sys

SUBCOMMANDS: dict[str, tuple[str, str, str | None]] = {
    "doctor":    ("doctor",          "main", None),
    "setup":     ("tui.app",         "main", None),
    "dashboard": ("dashboard.app",   "main", None),
    "switch":    ("recipe.cli",      "main", "switch"),
    "status":    ("recipe.cli",      "main", "status"),
    "generate":  ("zero2server.cli", "main", None),
}

USAGE = (
    "usage: platypus [--version] <command> [args...]\n\n"
    "Commands:\n"
    "  doctor     pre-flight checks for a fresh install\n"
    "  setup      interactive server setup (TUI)\n"
    "  dashboard  web dashboard\n"
    "  switch     switch the server to another role\n"
    "  status     show active and dormant roles\n"
    "  generate   generate docker-compose.yml + Caddyfile\n"
)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("platypus-server")
    except PackageNotFoundError:
        return "unknown"


def _run(module_name: str, func_name: str, prefix: str | None, rest: list[str]) -> int:
    module = importlib.import_module(module_name)
    argv = ([prefix] + rest) if prefix else rest
    result = getattr(module, func_name)(argv)
    return 0 if result is None else int(result)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if argv[0] == "--version":
        print(f"platypus {_version()}")
        return 0
    command, rest = argv[0], argv[1:]
    if command not in SUBCOMMANDS:
        print(f"platypus: unknown command {command!r}\n", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2
    module_name, func_name, prefix = SUBCOMMANDS[command]
    return _run(module_name, func_name, prefix, rest)
```

`pyproject.toml`: `[project.scripts]` — change `platypus = "doctor:main"` to `platypus = "platypus_cli.cli:main"` (the other five stay); `[tool.setuptools] packages` add `"platypus_cli"`.

- [ ] **Step 4: Re-install editable so the `platypus` script regenerates**

Run: `python -m pip install -e .`
Expected: `.venv` now has `platypus` → dispatcher (verify: `platypus --version` prints `platypus 0.2.0`; `platypus --help` lists six commands; `platypus-doctor --help` still works).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_platypus_cli.py tests/test_packaging.py -v`
Expected: PASS (all 11).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platypus_cli pyproject.toml tests/test_platypus_cli.py tests/test_packaging.py
git commit -m "cli: unified platypus dispatcher over six subcommands"
```

---

### Task 5: Doctor `--allow-busy`

**Files:**
- Modify: `doctor.py:273-320` (argparse + `main`) and add `downgrade_busy_ports` near `run_checks`
- Test: extend `tests/test_doctor.py`

**Interfaces:**
- Consumes: existing `Result`, `run_checks(ports) -> list[Result]`, `print_report`.
- Produces: `downgrade_busy_ports(result: Result) -> Result` — returns `Result(result.label, WARN, result.detail + " — allowed by --allow-busy")` iff `result.failed and result.label.startswith("port ") and "already in use" in result.detail`, else the input unchanged; `doctor.main` accepts `--allow-busy` (store_true) and applies the downgrade to every result before `print_report`. Task 7's bootstrap consumes this flag.

- [ ] **Step 1: Write the failing tests (append to `tests/test_doctor.py`)**

```python
def _fake_run_checks(results):
    def run_checks(ports, *args, **kwargs):  # signature-compatible stub
        return list(results)
    return run_checks


def test_allow_busy_downgrades_in_use_ports(monkeypatch, capsys):
    fake = _fake_run_checks([
        doctor.Result("OS", doctor.OK, "x"),
        doctor.Result("port 5050", doctor.FAIL, "already in use by another process"),
    ])
    monkeypatch.setattr(doctor, "run_checks", fake)
    assert doctor.main(["--allow-busy", "--ports", "5050"]) == 0
    out = capsys.readouterr().out
    assert "[WARN]  port 5050" in out
    assert "allowed by --allow-busy" in out


def test_busy_ports_still_fail_without_flag(monkeypatch, capsys):
    fake = _fake_run_checks([
        doctor.Result("port 5050", doctor.FAIL, "already in use by another process"),
    ])
    monkeypatch.setattr(doctor, "run_checks", fake)
    assert doctor.main(["--ports", "5050"]) == 1


def test_allow_busy_keeps_other_failures(monkeypatch):
    fake = _fake_run_checks([
        doctor.Result("sudo", doctor.FAIL, "sudo needs a password"),
        doctor.Result("port 5050", doctor.FAIL, "already in use by another process"),
    ])
    monkeypatch.setattr(doctor, "run_checks", fake)
    assert doctor.main(["--allow-busy", "--ports", "5050"]) == 1


def test_allow_busy_keeps_permission_failures(monkeypatch):
    fake = _fake_run_checks([
        doctor.Result("port 80", doctor.FAIL, "could not bind (permission denied)"),
    ])
    monkeypatch.setattr(doctor, "run_checks", fake)
    assert doctor.main(["--allow-busy", "--ports", "80"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: FAIL — unrecognized `--allow-busy` argument (argparse exits 2).

- [ ] **Step 3: Implement the flag and the downgrade**

In `doctor.py`: add `parser.add_argument("--allow-busy", action="store_true", help=...)` ("treat ports already in use as warnings, not failures (safe on re-runs where the stack is up)"). In `main`, after `run_checks(ports)`:

```python
if args.allow_busy:
    results = [downgrade_busy_ports(r) for r in results]
```

and add `downgrade_busy_ports` exactly per the Interfaces block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: PASS (existing + 4 new).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add doctor.py tests/test_doctor.py
git commit -m "doctor: --allow-busy downgrades only in-use port failures"
```

---

### Task 6: CI — wheel/install smoke job, Python matrix; Release workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `platypus_cli.cli` entry point + `recipe.model.builtin_roles` (Tasks 2 & 4); the buildable `pyproject.toml` (Task 1).
- Produces: CI guarantee that a built wheel installs, imports every tool, and contains the seven role templates; tag-triggered PyPI publishing.

- [ ] **Step 1: Rewrite `.github/workflows/ci.yml`**

Keep the `lint` job exactly as is, plus one added step at its end:

```yaml
      - name: Shell syntax check
        run: bash -n bootstrap.sh scripts/*.sh
```

Replace the `tui` job with a matrix job:

```yaml
  test:
    name: Tests (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: pyproject.toml
      - name: Install package and test dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Run tests
        run: pytest -q
```

Add a `package` job:

```yaml
  package:
    name: Build wheel & smoke-test install
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml
      - name: Build sdist and wheel
        run: |
          python -m pip install --upgrade pip build
          python -m build
      - name: Install the wheel into a clean venv
        run: |
          python -m venv /tmp/smoke
          /tmp/smoke/bin/pip install dist/*.whl
      - name: Import smoke + packaged-data probe
        run: |
          /tmp/smoke/bin/python - <<'EOF'
          import platypus_cli, tui.app, dashboard.app, recipe.cli, zero2server.cli, doctor
          from recipe.model import builtin_roles
          roles = set(builtin_roles())
          expected = {"minecraft-server", "storage-nextcloud", "storage-samba",
                      "pihole", "syncthing", "jellyfin", "assetto-corsa"}
          assert expected <= roles, f"wheel is missing role data: {expected - roles}"
          print("packaged roles OK:", sorted(roles))
          EOF
          /tmp/smoke/bin/platypus --version
          /tmp/smoke/bin/platypus --help > /dev/null
```

- [ ] **Step 2: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  pypi:
    name: Build and publish to PyPI
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build sdist and wheel
        run: |
          python -m pip install --upgrade pip build
          python -m build
      - name: Publish to PyPI (trusted publishing)
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 3: Verify the workflow files parse**

Run: `python -c "import yaml, glob; [yaml.safe_load(open(p, encoding='utf-8')) for p in glob.glob('.github/workflows/*.yml')]; print('workflows parse OK')"`
Expected: `workflows parse OK`.

- [ ] **Step 4: Push the branch and confirm CI is green**

Push all branch commits (wave 1 work so far). Open the Actions tab: `lint` (incl. the new shell syntax check), `test` (3.10–3.13), and `package` (wheel smoke) must all pass. Fix any failures before continuing — these jobs are exactly what a stranger's install experience depends on.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "ci: python matrix, wheel install smoke, release workflow"
```

---

### Task 7: `bootstrap.sh` — thin pipx wrapper (wave 2: merge only after 0.2.0 is live)

**Files:**
- Modify: `bootstrap.sh` (rewrite; header comment + pre-flight section replaced, Ansible section kept)

**Interfaces:**
- Consumes: `platypus doctor --allow-busy` (Task 5), the published `platypus-server` PyPI package (Rollout step 3), `PLATYPUS_TARGET` / `PLATYPUS_ENV` / `PLATYPUS_REPO_DIR` env vars (unchanged), `--` passthrough to ansible-playbook (unchanged).
- Produces: the public one-liner that installs via pipx instead of reimplementing the toolkit.

- [ ] **Step 1: Rewrite the script**

New structure (keep `set -euo pipefail`, the root check, the target validation block, and the existing repo-clone + venv + ansible section verbatim from the current lines 90–128):

```bash
PACKAGE_NAME="${PLATYPUS_PACKAGE:-platypus-server}"
PACKAGE_SPEC="${PACKAGE_NAME}>=0.2"
export PIPX_HOME="/opt/platypus/pipx"
export PIPX_BIN_DIR="/usr/local/bin"
```

1. `install_system_packages()` — extend each distro branch with its pipx package (`apt-get install -y python3 python3-venv python3-pip python3-pipx git curl ca-certificates sudo pipx`; dnf: `pipx`; apk: `py3-pipx`; pacman: `python-pipx`; zypper: `python3-pipx`); if no distro package matched pipx at all, fall back to `python3 -m pip install --break-system-packages pipx || python3 -m pip install pipx`.
2. Toolkit install/upgrade — one idempotent line (works on first install and every re-run):

```bash
pipx install --force "$PACKAGE_SPEC"
command -v platypus >/dev/null 2>&1 || { echo "platypus command not found after pipx install" >&2; exit 1; }
```

3. Pre-flight — replaces the current curl-doctor block:

```bash
ALLOW_BUSY=""
[ -f /opt/platypus/state.yml ] && ALLOW_BUSY="--allow-busy"
PLATYPUS_TARGET="$TARGET" platypus doctor $ALLOW_BUSY || {
    echo "Pre-flight checks failed — fix the issues above and re-run." >&2
    exit 1
}
```

4. Update the header comment: the script now installs the published `platypus-server` package via pipx into shared paths, runs `platypus doctor`, then applies the Ansible layer from the cloned repo.

- [ ] **Step 2: Verify syntax and required constructs**

Run: `bash -n bootstrap.sh` (Git Bash / WSL on Windows; CI lint job also runs it after merge).
Then verify presence: the file must contain `PIPX_HOME="/opt/platypus/pipx"`, `PIPX_BIN_DIR="/usr/local/bin"`, `PACKAGE_SPEC`, `pipx install --force`, `--allow-busy` guarded by `/opt/platypus/state.yml`, and the unchanged `ansible-playbook` invocation with `"$@"`.

- [ ] **Step 3: Commit (do not merge before the publish)**

```bash
git add bootstrap.sh
git commit -m "bootstrap: install published package via pipx, re-run-safe pre-flight"
```

This commit is wave 2 (see Rollout order): it may sit on the branch; it must reach `main` only after `v0.2.0` is verified on PyPI.

---

### Task 8: README — quickstart, unified command reference, honest support matrix

**Files:**
- Modify: `README.md` (top sections through "Installation", "Components" table, directory tree, Scripts table, testing section, new "Releases (maintainers)" note)

**Interfaces:**
- Consumes: everything shipped by Tasks 1–7 (commands, extras, bootstrap flow, CI jobs).
- Produces: the public documentation a stranger reads first.

- [ ] **Step 1: Restructure the README**

1. **Quickstart** (immediately after the intro): `pipx install platypus-server` → `platypus doctor` → `platypus setup` → `platypus dashboard`. Explicitly note `platypus setup` runs **unprivileged** and escalates each privileged step via `sudo -n` (running it under `sudo` would lose the user's saved settings). Keep the `curl | bash` one-liner as the "full server in one command" alternative, describing its pipx-based flow.
2. **Components** table: map each component to its subcommand (`platypus setup`, `platypus dashboard`, `platypus switch`, `platypus generate`, `platypus doctor`) with one line noting the old five commands remain as aliases.
3. **Breaking-change note**: `platypus` used to run the doctor directly; that is now `platypus doctor` (`platypus-doctor` still works standalone).
4. **Installation**: pipx as the primary path; `pip install -e ".[dev]"` for development; remove every `.[dashboard]` and `.[zero2server]` reference (the extras no longer exist).
5. **Support matrix**: Debian/Ubuntu — supported. Fedora/RHEL, Arch, Alpine, openSUSE — toolkit installs and the doctor runs, but the Ansible security layer currently applies Debian-family only (state plainly that this is a known limitation, not a silent claim).
6. **Directory tree**: show `recipe/roles/` under `recipe/`; delete the note that `roles/` holds two kinds of things (Ansible roles only now).
7. **Scripts** table: `install-dashboard-service.sh` description without the extra; **Testing & CI**: mention the Python matrix and the wheel smoke job; **Releases (maintainers)**: tag `v*` builds and publishes via trusted publishing, and until the trusted publisher is configured, `python -m build && twine upload dist/*` is the manual fallback.

- [ ] **Step 2: Verify content asserts**

Run (PowerShell or grep equivalents):
- `Select-String -Path README.md -Pattern "pipx install platypus-server"` → present
- `Select-String -Path README.md -Pattern "\.\[dashboard\]|\.\[zero2server\]"` → no matches
- `Select-String -Path README.md -Pattern "platypus doctor|platypus setup|platypus switch"` → present
- `Select-String -Path README.md -Pattern "recipe/roles"` → present (tree + role system section)

- [ ] **Step 3: Run the full suite (README must not drift from reality)**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit (wave 2)**

```bash
git add README.md
git commit -m "docs: pipx quickstart, unified command reference, honest support matrix"
```
