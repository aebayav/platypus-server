"""Task: configure the UFW firewall."""

from .base import Step, Task

UFW_TASK = Task(
    id="ufw",
    title="UFW Firewall",
    description=(
        "Installs UFW, sets safe defaults, and allows SSH (22), HTTP (80) and "
        "HTTPS (443) before enabling it."
    ),
    warning=(
        "Enabling UFW drops all incoming connections except SSH (22), HTTP (80) "
        "and HTTPS (443). If your SSH runs on a custom port, allow it first."
    ),
    steps=(
        Step("Install UFW", "apt-get update && apt-get install -y ufw"),
        Step("Deny incoming by default", "ufw default deny incoming"),
        Step("Allow outgoing by default", "ufw default allow outgoing"),
        Step("Allow SSH (22/tcp)", "ufw allow 22/tcp"),
        Step("Allow HTTP (80/tcp)", "ufw allow 80/tcp"),
        Step("Allow HTTPS (443/tcp)", "ufw allow 443/tcp"),
        Step(
            "Allow the Tailscale interface (if present)",
            "ufw allow in on tailscale0 2>/dev/null || echo 'tailscale0 not present, skipped'",
        ),
        Step("Enable UFW", "ufw --force enable"),
        Step("Show UFW status", "ufw status verbose"),
    ),
)
