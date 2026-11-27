"""Task: configure the host firewall (UFW or firewalld across Linux distros)."""

from .base import Step, Task

UFW_TASK = Task(
    id="ufw",
    title="Firewall (UFW / firewalld)",
    description=(
        "Configures firewalld on RHEL/Fedora or UFW on Debian/Ubuntu/Arch/openSUSE/Alpine, "
        "sets deny-by-default incoming rules, and allows SSH (22), HTTP (80) and HTTPS (443)."
    ),
    warning=(
        "Enabling the firewall drops all incoming connections except SSH (22), HTTP (80) "
        "and HTTPS (443). If your SSH runs on a custom port, allow it first."
    ),
    steps=(
        Step(
            "Install firewall package",
            "if command -v dnf >/dev/null 2>&1; then dnf install -y firewalld; "
            "elif command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y ufw; "
            "elif command -v pacman >/dev/null 2>&1; then pacman -Sy --noconfirm ufw; "
            "elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install ufw; "
            "elif command -v apk >/dev/null 2>&1; then apk add --no-cache ufw; fi",
        ),
        Step(
            "Configure and enable firewall rules",
            "if command -v firewall-cmd >/dev/null 2>&1; then "
            "systemctl enable --now firewalld && "
            "firewall-cmd --permanent --add-service=ssh && "
            "firewall-cmd --permanent --add-service=http && "
            "firewall-cmd --permanent --add-service=https && "
            "(firewall-cmd --permanent --zone=trusted --add-interface=tailscale0 2>/dev/null || true) && "
            "firewall-cmd --reload && firewall-cmd --list-all; "
            "else "
            "ufw default deny incoming && "
            "ufw default allow outgoing && "
            "ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && "
            "(ufw allow in on tailscale0 2>/dev/null || echo 'tailscale0 not present, skipped') && "
            "ufw --force enable && ufw status verbose; fi",
        ),
    ),
)
