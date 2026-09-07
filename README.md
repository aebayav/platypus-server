# platypus-server — Ansible Development Environment

This repository contains a ready-to-use Ansible development environment for the
`platypus-server` project. Everything needed for configuration management, role
development, and testing is in place.

## Requirements

- Python 3.10+
- Docker (optional, for role testing with Molecule)

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

## Directory Structure

```
platypus-server/
├── ansible.cfg              # Ansible configuration
├── requirements.txt         # Python dependencies
├── requirements.yml         # Collections and roles
├── Makefile                 # Helper commands
├── setup.ps1                # Windows setup script
├── inventory/
│   ├── dev/                 # Development environment
│   │   ├── hosts.yml
│   │   └── group_vars/
│   └── prod/                # Production environment
│       ├── hosts.yml
│       └── group_vars/
├── group_vars/
│   └── all/                 # Environment-agnostic variables
├── playbooks/
│   └── site.yml             # Main playbook
├── roles/
│   ├── common/              # Base server configuration
│   │   └── molecule/        # Role tests
│   └── platypus/            # Application deployment (scaffold)
├── .ansible-lint.yml
└── .yamllint.yml
```

## Usage

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

## Creating a New Role

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

A small web dashboard (Flask + psutil) shows local services and system metrics
on a single page:

- **Services** — Portainer, Uptime Kuma, and your own projects (up/down status)
- **System** — CPU, memory, disk usage and temperatures

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
