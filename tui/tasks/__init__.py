"""Task registry: the ordered list shown in the main menu."""

from .backup import BACKUP_TASK
from .caddy import CADDY_TASK
from .docker import DOCKER_TASK
from .firewall import UFW_TASK
from .packages import CERTBOT_TASK, NGINX_TASK, POSTGRESQL_TASK, REDIS_TASK
from .ssh import SSH_TASK
from .sysupdate import SYSUPDATE_TASK
from .vpn import TAILSCALE_TASK, WIREGUARD_TASK

TASKS = [
    DOCKER_TASK,
    CADDY_TASK,
    SSH_TASK,
    UFW_TASK,
    TAILSCALE_TASK,
    WIREGUARD_TASK,
    POSTGRESQL_TASK,
    REDIS_TASK,
    NGINX_TASK,
    CERTBOT_TASK,
    SYSUPDATE_TASK,
    BACKUP_TASK,
]

# Ordered phases for the step-by-step "Sequential Setup" wizard.
# VPN is handled separately in the wizard (user picks Tailscale or WireGuard).
# BACKUP_TASK is intentionally excluded — it requires interactive parameters
# (dirs, S3 bucket) that must be collected via BackupConfigModal before running.
SETUP_ORDER = [
    DOCKER_TASK,
    CADDY_TASK,
    SSH_TASK,
    UFW_TASK,
    POSTGRESQL_TASK,
    REDIS_TASK,
    NGINX_TASK,
    CERTBOT_TASK,
    SYSUPDATE_TASK,
]

__all__ = ["TASKS", "SETUP_ORDER"]
