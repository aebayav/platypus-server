"""Tasks: install PostgreSQL, Redis, Nginx, and Certbot (Let's Encrypt)."""

from .base import Step, Task

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

POSTGRESQL_TASK = Task(
    id="postgresql",
    title="PostgreSQL",
    description=(
        "Installs PostgreSQL and the contrib extensions from the distribution's "
        "default repository, then enables and starts the service."
    ),
    steps=(
        Step("Update package index", "apt-get update"),
        Step(
            "Install PostgreSQL",
            "apt-get install -y postgresql postgresql-contrib",
        ),
        Step(
            "Enable and start the PostgreSQL service",
            "systemctl enable --now postgresql",
        ),
        Step(
            "Verify installation",
            "psql --version",
            privileged=False,
        ),
        Step(
            "Show service status",
            "systemctl is-active postgresql",
            privileged=False,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

REDIS_TASK = Task(
    id="redis",
    title="Redis",
    description=(
        "Installs Redis from the distribution's default repository, enables the "
        "service, and runs a quick `PING` test to confirm it is responding."
    ),
    steps=(
        Step("Update package index", "apt-get update"),
        Step("Install Redis", "apt-get install -y redis-server"),
        Step(
            "Enable and start the Redis service",
            "systemctl enable --now redis-server",
        ),
        Step(
            "Verify Redis responds to PING",
            "redis-cli ping",
            privileged=False,
        ),
        Step(
            "Show service status",
            "systemctl is-active redis-server",
            privileged=False,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Nginx
# ---------------------------------------------------------------------------

NGINX_TASK = Task(
    id="nginx",
    title="Nginx",
    description=(
        "Installs Nginx from the distribution's default repository, enables the "
        "service at boot, and verifies the configuration."
    ),
    steps=(
        Step("Update package index", "apt-get update"),
        Step("Install Nginx", "apt-get install -y nginx"),
        Step(
            "Enable and start the Nginx service",
            "systemctl enable --now nginx",
        ),
        Step(
            "Test Nginx configuration",
            "nginx -t",
        ),
        Step(
            "Show Nginx version",
            "nginx -v",
            privileged=False,
        ),
        Step(
            "Show service status",
            "systemctl is-active nginx",
            privileged=False,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Certbot (Let's Encrypt)
# ---------------------------------------------------------------------------

CERTBOT_TASK = Task(
    id="certbot",
    title="Certbot (Let's Encrypt)",
    description=(
        "Installs Certbot and the Nginx plugin so you can obtain and auto-renew "
        "TLS certificates from Let's Encrypt.  After installation, run "
        "`certbot --nginx -d yourdomain.com` to issue your first certificate."
    ),
    steps=(
        Step("Update package index", "apt-get update"),
        Step(
            "Install Certbot and the Nginx plugin",
            "apt-get install -y certbot python3-certbot-nginx",
        ),
        Step(
            "Verify Certbot version",
            "certbot --version",
            privileged=False,
        ),
        Step(
            "Enable the Certbot renewal timer",
            "systemctl enable --now certbot.timer",
        ),
        Step(
            "Dry-run renewal check",
            "certbot renew --dry-run",
        ),
    ),
)

