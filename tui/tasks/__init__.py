"""Task registry: the ordered list shown in the main menu."""

from .caddy import CADDY_TASK
from .docker import DOCKER_TASK
from .firewall import UFW_TASK
from .ssh import SSH_TASK
from .vpn import TAILSCALE_TASK, WIREGUARD_TASK

TASKS = [
    DOCKER_TASK,
    CADDY_TASK,
    SSH_TASK,
    UFW_TASK,
    TAILSCALE_TASK,
    WIREGUARD_TASK,
]

# Ordered phases for the step-by-step "Sequential Setup" wizard.
# VPN is handled separately in the wizard (user picks Tailscale or WireGuard).
SETUP_ORDER = [DOCKER_TASK, CADDY_TASK, SSH_TASK, UFW_TASK]

__all__ = ["TASKS", "SETUP_ORDER"]
