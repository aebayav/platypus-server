"""Task: install Caddy as a reverse proxy."""

from .base import Step, Task

CADDY_TASK = Task(
    id="caddy",
    title="Caddy Reverse Proxy",
    description=(
        "Installs Caddy from the official apt repository and enables it as a "
        "systemd service. Edit `/etc/caddy/Caddyfile` to define your sites."
    ),
    steps=(
        Step(
            "Install prerequisites (curl, gnupg, apt-transport-https)",
            "apt-get update && apt-get install -y curl gnupg apt-transport-https",
        ),
        Step(
            "Add the Caddy signing key",
            "curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | "
            "gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg",
        ),
        Step(
            "Add the Caddy apt repository",
            'echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] '
            'https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" '
            "| tee /etc/apt/sources.list.d/caddy-stable.list",
        ),
        Step("Update package lists", "apt-get update"),
        Step("Install Caddy", "apt-get install -y caddy"),
        Step("Enable and start the Caddy service", "systemctl enable --now caddy"),
        Step(
            "Show Caddy service status",
            "systemctl status caddy --no-pager -n 20",
            privileged=False,
        ),
    ),
)
