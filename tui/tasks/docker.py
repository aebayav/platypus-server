"""Task: install Docker Engine + the Compose plugin."""

from .base import Step, Task

DOCKER_TASK = Task(
    id="docker",
    title="Docker + Docker Compose",
    description=(
        "Installs Docker Engine and the Compose plugin using the official "
        "`get.docker.com` convenience script."
    ),
    steps=(
        Step(
            "Check for an existing Docker installation",
            "command -v docker && docker --version || echo 'Docker is not installed'",
            privileged=False,
        ),
        Step(
            "Download the official Docker install script",
            "curl -fsSL https://get.docker.com -o /tmp/get-docker.sh",
            privileged=False,
        ),
        Step("Run the Docker install script", "sh /tmp/get-docker.sh"),
        Step("Enable and start the Docker service", "systemctl enable --now docker"),
        Step(
            "Add the current user to the docker group",
            'usermod -aG docker "${SUDO_USER:-$USER}"',
        ),
        Step(
            "Verify Docker and Compose",
            "docker --version && docker compose version",
            privileged=False,
        ),
    ),
)
