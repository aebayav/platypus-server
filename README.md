# platypus-server

Tools for setting up and operating a Linux home server: an interactive TUI,
a web dashboard, a swappable server-role system, a docker-compose generator,
and an Ansible configuration layer.

## Components

| Component | Command | Purpose |
|---|---|---|
| TUI | `platypus-tui` | Interactive Linux server setup (Textual) |
| Web dashboard | `platypus-dashboard` | Services, metrics and container management (Flask) |
| Server roles | `platypus-server` | Switch the server between pre-built roles |
| Compose generator | `zero-to-server` | Generate docker-compose.yml and Caddyfile |
| Ansible layer | playbooks, inventory | Configuration management for dev/prod |

## Requirements

- Python 3.10+
- Docker (optional: dashboard container controls, Molecule role tests)

## Installation

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Then activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Linux / macOS / WSL

```bash
make setup
source .venv/bin/activate
```

### Install the package

```bash
pip install -e .
```

Optional extras: `.[dashboard]` (Flask, psutil) and `.[zero2server]` (PyYAML).
Textual, the TUI dependency, is installed by default.

## Directory Structure

```
platypus-server/
├── tui/                     # Textual TUI (server setup)
├── dashboard/               # Flask web dashboard
├── recipe/                  # Server-role switch system
├── zero2server/             # docker-compose + Caddyfile generator
├── roles/
│   ├── common/              # Ansible role: base server configuration
│   │   └── molecule/        # Ansible role tests
│   ├── platypus/            # Ansible role: application deployment
│   ├── minecraft-server/    # Recipe role: template.yml + questions.yml
│   ├── storage-nextcloud/   # Recipe role
│   ├── storage-samba/       # Recipe role
│   ├── pihole/              # Recipe role
│   ├── syncthing/           # Recipe role
│   ├── jellyfin/            # Recipe role
│   └── assetto-corsa/       # Recipe role
├── playbooks/
│   └── site.yml             # Main playbook
├── inventory/
│   ├── dev/                 # Development environment
│   │   ├── hosts.yml
│   │   └── group_vars/
│   └── prod/                # Production environment
│       ├── hosts.yml
│       └── group_vars/
├── group_vars/
│   └── all/                 # Environment-agnostic variables
├── scripts/                 # Backup and service install scripts
├── tests/                   # pytest suite
├── ansible.cfg              # Ansible configuration
├── requirements.txt         # Ansible/testing Python dependencies
├── requirements.yml         # Ansible collections
├── Makefile                 # Helper commands
├── setup.ps1                # Windows setup script
├── .ansible-lint.yml
└── .yamllint.yml
```

## Ansible

The `ansible.cfg`, `playbooks/`, `inventory/` and Ansible role directories
provide a ready-to-use configuration management environment for dev and prod.

### Check the environment

```bash
ansible --version
```

### Ping the dev environment

```bash
ansible platypus -i inventory/dev -m ping
```

### Run the playbook

```bash
# Syntax check
ansible-playbook --syntax-check playbooks/site.yml -i inventory/dev

# Dry run
ansible-playbook playbooks/site.yml -i inventory/dev --check

# Real run
ansible-playbook playbooks/site.yml -i inventory/dev
```

### Lint

```bash
ansible-lint
```

### Role testing (Molecule)

```bash
cd roles/common
molecule test
```

## Creating a New Ansible Role

```bash
ansible-galaxy role init roles/new-role
```

Add the generated role to the `roles:` list in `playbooks/site.yml`.

## Secrets (Vault)

To encrypt sensitive variables:

```bash
ansible-vault encrypt_string 'secret-value' --name 'db_password'
```

Add the encrypted value to the relevant `group_vars` file and run with:

```bash
ansible-playbook playbooks/site.yml -i inventory/dev --ask-vault-pass
```

## TUI (Text User Interface)

A Textual-based TUI is included for configuring a Linux server interactively. It covers:

- **Docker + Docker Compose** — installation via the official convenience script
- **Caddy Reverse Proxy** — installation from the official apt repository
- **SSH Hardening** — disable password/root login via a drop-in config
- **UFW Firewall** — safe defaults with SSH/HTTP/HTTPS allowed
- **Tailscale / WireGuard** — secure remote access

The first menu entry, **Sequential Setup (step-by-step)**, runs the full setup
in a safe order — Docker → Caddy → SSH hardening → UFW → VPN. It asks for
confirmation before the SSH and UFW stages and lets you pick Tailscale,
WireGuard, or skip the VPN stage entirely.

### Install and run

```bash
# inside the project virtual environment
pip install -e .
platypus-tui
```

Or without installing:

```bash
python -m tui
```

Run with sudo for the best experience (otherwise privileged steps use `sudo -n`):

```bash
sudo -E .venv/bin/platypus-tui
```

> The TUI performs **real system changes**. Run it directly on the Linux server
> you want to configure — it is not intended for Windows hosts.

## Web Dashboard

A web dashboard (Flask + psutil) for the local server, behind a simple login
(default `admin` / `platypus`; override with the `DASHBOARD_USER` and
`DASHBOARD_PASSWORD` environment variables):

- **Services** — Portainer, Uptime Kuma, and your own projects (up/down status)
- **System** — CPU, memory, disk usage, temperatures and metric history
- **Containers** — list, run, start/stop/restart, remove, logs, stats, images
- **Compose** — manage docker compose stacks
- **Systemd** — service status and control
- **Firewall** — UFW rule overview
- **Roles** — active and dormant server roles

A public `/health` endpoint reports `ok` / `degraded` for monitoring tools.

### Configure services

Edit `dashboard/services.py` to list your services:

```python
SERVICES = [
    {"name": "Portainer", "url": "http://localhost:9000"},
    {"name": "Uptime Kuma", "url": "http://localhost:3001"},
    {"name": "My App", "url": "http://localhost:8080"},
]
```

### Run

```bash
pip install -e ".[dashboard]"
python -m dashboard
# or
platypus-dashboard
```

Then open http://localhost:5050. Override the host/port with `DASHBOARD_HOST`
and `DASHBOARD_PORT` environment variables.

### Run as a systemd service (auto-start on boot)

```bash
sudo ./scripts/install-dashboard-service.sh
```

This creates a `platypus-dashboard.service` that starts the dashboard
automatically on boot and restarts it if it crashes:

```bash
systemctl status platypus-dashboard
```

## Server Roles (recipe system)

`platypus-server` switches the whole server between pre-built roles. Each role
is defined by two files under `roles/<name>/`:

- `template.yml` — docker-compose template, hooks and an optional Caddy route
- `questions.yml` — questions asked during first-time setup

### Built-in roles

| Role | Image | Description |
|---|---|---|
| `minecraft-server` | itzg/minecraft-server | Minecraft Java Edition with RCON-safe shutdown |
| `storage-nextcloud` | nextcloud:28-apache + mariadb:10.11 | Personal cloud storage |
| `storage-samba` | dperson/samba | SMB/CIFS file sharing |
| `pihole` | pihole/pihole | Network-wide ad blocking (DNS sinkhole) |
| `syncthing` | syncthing/syncthing | File synchronization between devices |
| `jellyfin` | jellyfin/jellyfin | Media server (movies, TV, music) |
| `assetto-corsa` | germanrcuriel/assetto-corsa-server | Assetto Corsa dedicated racing server |

### Usage

```bash
# Switch to a role (prompts for answers on first run)
platypus-server switch minecraft-server

# Show active role, dormant roles and transition history
platypus-server status
```

During a switch, the current role is stopped (including its `pre_remove`
hooks, e.g. RCON save for Minecraft), the new role's `docker-compose.yml` is
rendered from the template and answers, the stack is started, the Caddy route
is updated, and the state is recorded in `/opt/platypus/state.yml`. Existing
answers are reused on later switches, and a transition lock with rollback
protects against interrupted switches.

Runtime data lives under `/opt/platypus/roles/<role>/` (`answers.yml`,
`docker-compose.yml`, bind-mounted `./data`). The role system targets Linux
hosts.

## zero-to-server CLI

An interactive CLI that generates a personalized `docker-compose.yml` plus a
`Caddyfile` by asking which services you want, your domain, and whether to
enable HTTPS. Available services in the catalog: Portainer, Uptime Kuma,
Caddy, Watchtower, PostgreSQL and Redis.

### Run

```bash
pip install -e ".[zero2server]"
zero-to-server
# or
python -m zero2server
```

Answer the prompts — it writes `docker-compose.yml` and, when Caddy is
selected, a `Caddyfile` with subdomain routes (e.g. `portainer.example.com`)
and automatic Let's Encrypt HTTPS.

Useful flags: `--run` starts the stack right away with `docker compose up -d`,
`--install-cron` installs a daily cron job that restarts Watchtower, and
`--out-dir DIR` sets the output directory.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/backup.sh` | Archives `BACKUP_DIRS` to `BACKUP_DEST`, keeps `BACKUP_RETENTION` days of backups, optional S3 upload (`S3_BUCKET`) |
| `scripts/install-backup-cron.sh` | Installs the `/etc/cron.d/platypus-backup` cron job |
| `scripts/install-dashboard-service.sh` | Registers `platypus-dashboard.service` (starts on boot) |

Run a backup directly:

```bash
sudo ./scripts/backup.sh
```

## Testing & CI

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push and
pull request:

- `ansible-playbook --syntax-check`
- `ansible-lint` and `yamllint`
- Headless TUI smoke tests (`pytest`)

To run the same checks locally:

```bash
pip install -r requirements.txt
pip install -e ".[dev]"
ansible-galaxy collection install -r requirements.yml -p collections
ansible-playbook --syntax-check playbooks/site.yml -i inventory/dev
ansible-lint
yamllint .
pytest -q
```

Molecule role tests require Docker and are run on demand (e.g. on a Linux VM):

```bash
cd roles/common
molecule test
```

## Notes

- Update the SSH details in `inventory/dev/hosts.yml` to match your development environment.
- For production, fill `inventory/prod/hosts.yml` with real servers.
- Collections are installed into `./collections` and are not committed to git (see `.gitignore`).
- The `roles/` directory holds both Ansible roles (`common`, `platypus`) and recipe role templates (the ones with `template.yml` and `questions.yml`).
