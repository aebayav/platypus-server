# Ease of Install & Use — Design

Date: 2026-11-20
Status: awaiting approval
Phase: 1 of 2 (phase 2 = audit-driven bug/security fixes, out of scope here)

## Intent

A stranger on GitHub must be able to install and use platypus-server
comfortably, on their own, with no help from the author. Today that is
impossible: the only working install path is `curl | bash bootstrap.sh`;
`pip install -e .` produces a `platypus-dashboard` command that crashes
(missing extras), and a non-editable/wheel install produces a
`platypus-server switch` that always fails (role templates are not
packaged). Usability suffers too: five separate commands
(`platypus-tui`, `platypus-dashboard`, `platypus-server`,
`zero-to-server`, `platypus doctor`) with no single discoverable entry
point, and README claims that overstate reality (six distro families,
"re-running is safe").

The chosen fix: publish a real PyPI package with one unified `platypus`
command, and make `bootstrap.sh` a thin wrapper around it.

## Goals

1. `pipx install platypus-server` (or `pip install --user`) works on
   Linux, and every console script it installs runs without extra steps.
2. One discoverable command: `platypus --help` shows everything;
   subcommands cover all five tools. Old command names keep working as
   aliases.
3. `curl | bash bootstrap.sh` remains a working one-liner for the full
   Linux server setup, and becomes re-run-safe (re-running with the
   stack already up no longer aborts).
4. The README install/usage sections tell the truth: quickstart with
   pipx first, honest per-distro support table, one command reference.

## Non-goals (phase 2, separately scheduled)

All robustness/security audit fixes: dashboard secret key/XSS/root
service, recipe transition lock/rollback, TUI fail-fast semantics and
the unwired backup task, the Debian-only Ansible security role,
dedicated test suites for recipe/dashboard/zero2server, Windows
`setup.ps1` hardening, doctor's IPv6/socket handling. The only audit
items in scope here are the ones that block a working pip install or
make the bootstrap flow fail (listed under Design).

## Anti-goals

- No new features in TUI/dashboard/recipe/zero2server behavior.
- No breaking changes to `/opt/platypus` runtime state or saved
  answers.
- Do not bundle Ansible into the PyPI package (heavy, server-only;
  the bootstrap keeps installing it on the server).
- Do not remove the `curl | bash` path.

## Constraints

- Dev machine is Windows; Linux-only behavior (TUI task execution,
  docker) is verified via CI and import/smoke tests, not locally.
- Python floor stays `>=3.10`.
- Existing alias commands must keep their current argument surfaces.
- The PyPI name `platypus-server` is unverified for availability; if
  taken, fall back to `platypus-toolkit` (author decides at first
  publish).

## Approaches considered

1. **PyPI package + unified `platypus` CLI (chosen).** Standard,
   most trustworthy install for strangers (`pipx install` + one
   discoverable command). Cost: packaging work, release workflow, and
   ongoing per-release publish effort — accepted because the stated
   goal is exactly "a stranger can install it comfortably".
2. **Bootstrap-first, no PyPI (rejected).** Less maintenance, but
   `pip install git+URL` is impractical for strangers and
   `curl | bash` is a trust barrier; leaves the goal half-met.
3. **Container image distribution (dropped).** The tool's job is to
   install Docker on the host; running it from a container creates a
   privilege chicken-and-egg not worth solving here.

## Design

### A. Distribution & packaging

- **A1. PyPI distribution name:** `platypus-server` (fallback
  `platypus-toolkit`; author confirms at first publish). Import
  package names stay as-is (`tui`, `dashboard`, `recipe`,
  `zero2server`, `doctor`).
- **A2. Dependencies become real:** move `flask>=3.0` and
  `psutil>=5.9` from the `dashboard` extra into core dependencies.
  Delete the `zero2server` extra (its only dep, `pyyaml`, is already
  core — the extra is a no-op) and delete the `dashboard` extra (now
  core). Keep the `dev` extra (pytest). Raise the Textual floor from
  `>=0.60.0` to `>=0.77.0` (the code uses `RadioSet(compact=True)`,
  `push_screen(..., wait_for_dismiss=True)` and `App.notify`; at the
  current declared floor the TUI crashes at compose time).
- **A3. Ship the recipe role templates.** Move the seven recipe role
  definitions from `roles/<name>/{template.yml,questions.yml}` to
  `recipe/roles/<name>/` and declare them as `recipe` package data
  (`recipe/roles/*/template.yml`, `recipe/roles/*/questions.yml`).
  `recipe/model.py` role-source resolution becomes: packaged
  `recipe/roles/` first, repo-root `roles/` as fallback. The fallback
  serves editable checkouts only (transitional); it is not an
  advertised extension point — a custom-role search path for pipx/wheel
  users is deferred to phase 2 (anti-goal: no new features here).
  The three Ansible roles (`common`, `security`, `platypus`) stay in
  `roles/` untouched. This also removes the README's current apology
  that `roles/` holds two different kinds of things.
- **A4. Metadata completion:** MIT license wired up, authors, project
  URLs, README as readme, Python classifiers, and version **0.2.0**
  (the packaging redesign is breaking for the `platypus` command, see
  B3). The version lives once, in `pyproject.toml`; all three
  hand-kept `__version__` strings (`dashboard/__init__.py`,
  `tui/__init__.py`, `zero2server/__init__.py`) read it via
  `importlib.metadata.version` so no `0.1.0` strings linger inside a
  0.2.0 package.
- **A5. `scripts/install-dashboard-service.sh` minimal alignment.**
  A2 deletes the `dashboard` extra, and this script currently runs
  `pip install -e ".[dashboard]"`. In scope: drop the dead extra
  reference so the documented script runs without a pip warning.
  Out of scope (phase 2 audit work): the service's root-user/dev-server
  design and any switch of its `ExecStart` to the pipx venv.

### B. Unified CLI

- **B1. New top-level package `platypus_cli/` with `cli.py`.** Console
  script `platypus` → `platypus_cli.cli:main`. It is an argparse
  dispatcher with one subcommand per tool; unrecognized flags inside a
  subcommand are forwarded to that tool's own parser:

  | Subcommand | Forwards to | Today's signature |
  |---|---|---|
  | `platypus doctor [...]` | `doctor.main(argv)` | already `main(argv)` |
  | `platypus setup [--mode M] [--target T]` | `tui.app.main(argv)` | already `main(argv)` |
  | `platypus dashboard` | `dashboard.app.main(argv)` | needs `argv` param added |
  | `platypus switch <role>` / `platypus status` | `recipe.cli.main(argv)` | needs `argv` param added |
  | `platypus generate [--run] [--install-cron] [--out-dir D]` | `zero2server.cli.main(argv)` | needs `argv` param added |

  The `main(argv=None)` refactor in the three modules is mechanical
  (pass argv slice into their existing argparse call).
- **B2. Aliases preserved:** `platypus-tui`, `platypus-dashboard`,
  `platypus-server`, `zero-to-server`, `platypus-doctor` keep
  installing and behave exactly as today.
- **B3. Breaking change, documented:** the `platypus` command itself
  currently runs the doctor directly (`platypus --ports ...`). After
  this change it is the dispatcher and the doctor moves under
  `platypus doctor`. `platypus-doctor` remains a direct alias, and the
  standalone `curl ... doctor.py | python3 -` flow is untouched.
- **B4. `platypus --version`** reports the package version.

### C. Bootstrap

- **C1. Thin wrapper:** `bootstrap.sh` becomes: detect distro →
  install pipx (distro package name varies; fall back to
  `python3 -m pip install --user pipx` where needed) →
  `pipx install platypus-server` (or `pipx upgrade` on re-run) → run
  `platypus doctor` (see C2 for when `--allow-busy` is passed) →
  clone the repo and run the Ansible layer exactly as today (venv,
  `requirements.txt`, playbook) for the full-server mode. Extra args
  after `--` still pass to ansible-playbook;
  `PLATYPUS_TARGET`/`PLATYPUS_ENV` still honored.
- **C1a. Bootstrap installs the package to a shared location.** The
  bootstrap runs as root, so a naive `pipx install` would land in
  `/root/.local`, invisible to the admin user and to `sudo`. It
  therefore sets `PIPX_HOME=/opt/platypus/pipx` and
  `PIPX_BIN_DIR=/usr/local/bin` before invoking pipx: one shared
  install, `platypus` on every PATH, no root-HOME or secure_path
  problems. The PyPI distribution name appears once, as a variable
  at the top of the script, so a fallback rename (see Constraints)
  is a one-line change.
- **C2. Doctor gains `--allow-busy`:** occupied stack ports are
  reported as warnings (exit 0) instead of failures. Contract: the
  bootstrap passes the flag **only when `/opt/platypus/state.yml`
  exists** — i.e. a platypus role has been activated before, so busy
  stack ports are expected on a re-run. First runs stay strict, so a
  stranger whose unrelated service occupies 5050/8080 still gets a
  hard pre-flight failure rather than a silently broken install.
  This is the single audit fix pulled into scope because the current
  behavior blocks the install path. (Port-ownership introspection
  stays phase 2.)
- **C3. Sequencing: no public breakage window.** The rewritten
  `bootstrap.sh` lands on `main` only **after** 0.2.0 is actually
  published on PyPI (author prerequisite, see below). Until then the
  current bootstrap stays live. The bootstrap pins
  `platypus-server>=0.2` so a half-published state cannot silently
  fall back to an older package. If publishing slips indefinitely,
  the old bootstrap remains the public path — the one-liner never
  404s or pip-errors for a stranger.

### D. Release & CI

- **D1. Release workflow** `.github/workflows/release.yml`: on tag
  `v*` → build sdist+wheel (`python -m build`) → publish to PyPI via
  trusted publishing. Prerequisite (author, one-time): PyPI account,
  create the project, configure the trusted publisher for this repo.
  Until configured, the workflow builds artifacts and a manual
  `twine upload` fallback is documented.
- **D2. CI additions (install-focused only):** a job step that builds
  the wheel, `pip install`s it into a clean venv, imports all
  entry-point modules (`platypus_cli`, `tui.app`, `dashboard.app`,
  `recipe.cli`, `zero2server.cli`, `doctor`) and runs
  `platypus --help` plus a packaged-data probe (e.g. `platypus
  status` resolving the seven built-in role templates from inside the
  installed wheel) — closing both the gap where ~2500 lines were
  never imported in CI and the sdist/wheel data-file risk an
  import-only check cannot see; plus a Python 3.10–3.13 test matrix
  and pip caching. No other CI expansion here (phase 2).
- **D3. Dispatcher unit tests:** the routing table (subcommand →
  module) and `--version` get small unit tests; nothing deeper.

### E. Documentation

- **E1. README restructure:** a Quickstart at the top —
  `pipx install platypus-server`, then `platypus doctor` →
  `platypus setup` → `platypus dashboard`. The setup command runs
  **unprivileged**: the TUI already escalates its privileged steps
  via `sudo -n` and the doctor enforces passwordless sudo, so
  `sudo platypus setup` is not the documented path (running under
  `sudo` would drop `$HOME` and the user's saved
  `~/.config/platypus` settings). The curl|bash one-liner stays as
  the "full server in one command" alternative; one unified command
  reference table replaces the five per-tool sections; directory
  tree updated for `recipe/roles/`.
- **E2. Honest support matrix:** Debian/Ubuntu — supported. Other
  claimed distros — toolkit installs and runs, but the Ansible
  security layer is Debian-family-only *for now* (phase 2 will either
  extend or further narrow this). The README's current blanket claims
  are removed.

## Prerequisites on the author (human steps)

- Confirm the PyPI distribution name at first publish (availability).
- One-time PyPI trusted-publisher setup for the repo.

## What's left to the builder

- Exact argparse forwarding mechanics in `platypus_cli.cli` (error
  messages, `--help` layout, exit codes).
- Mechanical `main(argv=None)` refactors in `dashboard/app.py`,
  `recipe/cli.py`, `zero2server/cli.py` (and adjusting their
  `argparse.parse_args(argv)` calls).
- `doctor.py --allow-busy` implementation detail (per-port verdict
  mapping, message wording).
- `bootstrap.sh` per-distro pipx bootstrapping details and fallbacks.
- `release.yml` trigger/permissions details; build job config.
- Final README wording; whether `platypus dashboard` gains
  `--host/--port` flags or stays env-var-only (builder's call; env
  vars are the current surface — changing it is optional).
- Unit test style for the dispatcher (mirroring `tests/test_settings.py`
  conventions is the default).
