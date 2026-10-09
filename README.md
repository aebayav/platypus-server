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

## One-line server bootstrap

On the server itself, run a single command — it installs the system packages,
clones the repository to `/opt/platypus-server`, creates a virtual environment,
installs Ansible and the required collections, and runs the playbook locally
(`ansible_connection: local`):

```bash
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo bash
```

Supported distros: Debian/Ubuntu, Fedora/RHEL, Alpine, Arch and openSUSE.

The installation steps adapt to the kind of server with `PLATYPUS_TARGET`:

```bash
# Home server behind NAT (default): Tailscale firewall rule, no fail2ban
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo bash

# Public VPS: fail2ban for SSH, HTTP/HTTPS opened for the reverse proxy
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo env PLATYPUS_TARGET=vps bash
```

Options:

```bash
# Development environment instead of production
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo env PLATYPUS_ENV=dev bash

# Dry run (extra arguments after `--` go to ansible-playbook)
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo bash -s -- --check
```

Re-running is safe: the script updates the existing checkout, reuses the
virtual environment and re-applies the idempotent playbook.

### Pre-flight checks (`platypus doctor`)

Before touching anything, run the pre-flight checks — they verify the OS,
sudo rights, Python version, free disk and RAM, internet access, and that
the ports the stack needs (80, 443, 5050, 8080) are free:

```bash
# standalone — no installation needed
curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/doctor.py | python3 -

# or, once the repository is installed
platypus doctor
```

The bootstrap above runs the same checks automatically, so a missing sudo
right or a blocked port fails **before** the installation starts instead of
halfway through. The default port list depends on the target — a VPS checks
`80,443,5050,8080`, a home server `5050,8080` (`--target` or the
`PLATYPUS_TARGET` environment variable selects it). Custom port list:

```bash
platypus doctor --ports 80,443,5050,8080,25565
```

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

## Profiles and settings

Two settings keep the interfaces from getting overwhelming. Both are
changeable in the TUI itself (**Settings**, the last entry of the main menu)
and persist in `~/.config/platypus/config.yml` (relocatable with
`PLATYPUS_CONFIG`):

| Setting | Values | Effect |
|---|---|---|
| `mode` | `simple`, `full` | `simple` shows the essentials only and hides advanced tasks (WireGuard, PostgreSQL, Redis, Nginx, Certbot, Backup) |
| `target` | `home`, `vps` | picks the relevant tasks and installation steps for a home server behind NAT or a public VPS |

Target differences at a glance:

- **home** — VPN stage (Tailscale/WireGuard) in Sequential Setup, Tailscale
  firewall rule, ports `5050,8080` checked by the doctor
- **vps** — no VPN stage (public IP already), Nginx/Certbot tasks instead of
  Tailscale, fail2ban + open HTTP/HTTPS in the Ansible run, ports
  `80,443,5050,8080` checked by the doctor

Values resolve with this precedence: **command-line flags > environment
variables (`PLATYPUS_MODE`, `PLATYPUS_TARGET`) > config file > defaults
(`full`, `home`)**. Examples:

```bash
platypus-tui --mode simple --target vps
PLATYPUS_TARGET=vps platypus doctor
sudo env PLATYPUS_TARGET=vps bash bootstrap.sh
```

## Directory Structure

```
platypus-server/
├── tui/                     # Textual TUI (server setup)
│   └── settings.py          # mode (simple/full) + target (home/vps) settings
├── dashboard/               # Flask web dashboard
├── recipe/                  # Server-role switch system
├── zero2server/             # docker-compose + Caddyfile generator
├── roles/
│   ├── common/              # Ansible role: base server configuration
│   │   └── molecule/        # Ansible role tests
│   ├── platypus/            # Ansible role: application deployment
│   ├── security/            # Ansible role: SSH hardening, UFW, target steps
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
├── scripts/                 # Backup and service install scripts
├── tests/                   # pytest suite
├── doctor.py                # Pre-flight checks (platypus doctor)
├── bootstrap.sh             # One-line server installer
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
provide a ready-to-use configuration management environment. Ansible runs
directly on the server itself with `ansible_connection: local` — no SSH
needed. The one-line bootstrap above is the quickest way to set a server up;
the commands below are the manual equivalent for development.

The playbook applies `common`, `security` and `platypus`. The `security`
role hardens SSH and configures UFW for every target, then diverges:
fail2ban and open HTTP/HTTPS ports on a VPS (`-e platypus_target=vps`),
a Tailscale firewall rule on a home server (the default).

### Check the environment

```bash
ansible --version
```

### Ping the local environment

```bash
ansible localhost -i inventory/dev -m ping
```

### Run the playbook

Use `-i inventory/dev` on a development box or `-i inventory/prod` on the
production server:

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
WireGuard, or skip the VPN stage entirely. On a VPS there is no VPN stage
(the server already has a public IP); the exact task list follows the
`target`/`mode` settings — see [Profiles and settings](#profiles-and-settings).

### Install and run

```bash
# inside the project virtual environment
pip install -e .
platypus-tui
# or, with explicit settings (flags > env vars > saved config)
platypus-tui --mode simple --target vps
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
| `bootstrap.sh` | One-line installer: system packages + repo + venv + Ansible + playbook |
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

- Ansible runs on the server itself via `ansible_connection: local` — there is no SSH or remote inventory to configure.
- Pick environment variables with `-i inventory/dev` (development) or `-i inventory/prod` (production).
- Collections are installed into `./collections` and are not committed to git (see `.gitignore`).
- The `roles/` directory holds both Ansible roles (`common`, `security`, `platypus`) and recipe role templates (the ones with `template.yml` and `questions.yml`).
