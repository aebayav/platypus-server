# Changelog

All notable changes to `platypus-server` are documented in this file.

## [Unreleased]

- Added `platypus module init|lint|list` CLI and module schema validator.
- Added state-aware `platypus backup` and `platypus restore` (tar.gz + Restic + S3).
- Hardened web dashboard authentication (password hashing, constant-time checks, CSRF protection, login rate limiting, WSGI runner, unprivileged systemd unit).
- Extended Ansible `security` role and TUI tasks with multi-distro support (Debian/Ubuntu, RHEL/Fedora, Arch, openSUSE, Alpine) and Molecule suites.
- Added declarative GitOps reconciliation (`platypus plan` / `platypus apply`) with SOPS secret support.
- Added OpenTofu/Terraform + Cloud-Init IaC templates (`infra/terraform/`).
- Added Prometheus `/metrics` endpoint and built-in `monitoring` companion module.
- Added `platypus fleet` multi-node orchestration and Tailscale tunnel generator.

## [0.3.0] - 2026-11-24

- Replaced single-active role switching with additive `platypus mount`, `platypus dismount`, and `platypus reconfigure`.
- Added declared port claims, mount-time conflict detection, and `questions.yml` range validation.
- Migrated `state.yml` to schema v2 (`mounted` list) with automatic v1 backup and migration.
- Moved packaged module templates to `recipe/modules/` and updated Caddy snippet management to multi-section blocks.

## [0.2.1] - 2026-11-23

- Replaced racy state-file lock with atomic `O_EXCL` `/opt/platypus/transition.lock` and dead-PID recovery.
- Added SIGTERM/Ctrl-C rollback handling, `rollback:` module hooks, and `fsync` + `.bak` durability on state writes.

## [0.2.0] - 2026-11-21

- Introduced unified `platypus` CLI dispatcher (`doctor`, `setup`, `dashboard`, `generate`, `status`).
- Added one-line `bootstrap.sh` installer and `home` / `vps` target profiles.
