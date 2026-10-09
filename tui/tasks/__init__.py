"""Task registry: the ordered list shown in the main menu."""

from .backup import BACKUP_TASK
from .caddy import CADDY_TASK
from .docker import DOCKER_TASK
from .firewall import UFW_TASK
from .packages import CERTBOT_TASK, NGINX_TASK, POSTGRESQL_TASK, REDIS_TASK
from .ssh import SSH_TASK
from .sysupdate import SYSUPDATE_TASK
from .vpn import TAILSCALE_TASK, WIREGUARD_TASK

# Full registry — every task the TUI knows about.
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

# Which targets each task is relevant for.
#   home — home server behind NAT: VPN for remote access, LAN-friendly tools
#   vps  — public VPS: reverse proxy + HTTPS, database/domain tooling
TASK_TARGETS: dict[str, frozenset[str]] = {
    "docker": frozenset({"home", "vps"}),
    "caddy": frozenset({"home", "vps"}),
    "ssh": frozenset({"home", "vps"}),
    "ufw": frozenset({"home", "vps"}),
    # A VPS already has a public IP — VPN is a home-server concern.
    "tailscale": frozenset({"home"}),
    "wireguard": frozenset({"home", "vps"}),
    "postgresql": frozenset({"home", "vps"}),
    "redis": frozenset({"home", "vps"}),
    # Domain / reverse-proxy tooling only makes sense on a public server.
    "nginx": frozenset({"vps"}),
    "certbot": frozenset({"vps"}),
    "sysupdate": frozenset({"home", "vps"}),
    "backup": frozenset({"home", "vps"}),
}

# Advanced/optional tasks hidden when the interface mode is "simple".
SIMPLE_HIDDEN = frozenset(
    {"wireguard", "postgresql", "redis", "nginx", "certbot", "backup"}
)

# Task ids handled by the dedicated VPN stage of the Sequential Setup wizard
# (the user picks Tailscale or WireGuard there) — never part of the plan.
_VPN_TASK_IDS = frozenset({"tailscale", "wireguard"})

# BACKUP_TASK is also excluded from the wizard: it requires interactive
# parameters (dirs, S3 bucket) collected via the backup config modal.


def visible_tasks(target: str = "home", mode: str = "full") -> list:
    """Return the tasks shown in the main menu for the given settings."""
    target_set = frozenset({target})
    return [
        task
        for task in TASKS
        if target_set <= TASK_TARGETS.get(task.id, frozenset())
        and not (mode == "simple" and task.id in SIMPLE_HIDDEN)
    ]


def setup_order(target: str = "home", mode: str = "full") -> list:
    """Return the ordered stages for the Sequential Setup wizard.

    VPN tasks are handled by the dedicated VPN stage and BACKUP_TASK needs
    interactive parameters, so both are excluded from the plan itself.
    """
    return [
        task
        for task in visible_tasks(target, mode)
        if task.id not in _VPN_TASK_IDS and task.id != "backup"
    ]


def has_vpn_stage(target: str = "home") -> bool:
    """Whether the Sequential Setup wizard asks for a VPN.

    A VPS already has a public IP, so there is no VPN stage; a home server
    behind NAT needs one for remote access.
    """
    return target == "home"


__all__ = [
    "TASKS",
    "TASK_TARGETS",
    "SIMPLE_HIDDEN",
    "visible_tasks",
    "setup_order",
    "has_vpn_stage",
]
