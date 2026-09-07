"""Task: harden the SSH daemon."""

from .base import Step, Task

SSH_TASK = Task(
    id="ssh",
    title="SSH Hardening",
    description=(
        "Disables root login and password authentication, and tightens a few "
        "SSH options via a drop-in config at `/etc/ssh/sshd_config.d/99-hardening.conf`."
    ),
    warning=(
        "This disables **password login** and **root login**. Make sure your SSH "
        "public key is already authorized (or you have another way in) — otherwise "
        "you may lock yourself out. Keep a separate SSH session open as a safety net."
    ),
    steps=(
        Step(
            "Back up the current sshd_config",
            'cp -n /etc/ssh/sshd_config "/etc/ssh/sshd_config.backup.$(date +%F)"',
        ),
        Step(
            "Write the hardening drop-in config",
            "printf '%s\\n' 'PermitRootLogin no' 'PasswordAuthentication no' "
            "'PubkeyAuthentication yes' 'KbdInteractiveAuthentication no' "
            "'X11Forwarding no' 'MaxAuthTries 3' 'ClientAliveInterval 300' "
            "'ClientAliveCountMax 2' > /etc/ssh/sshd_config.d/99-hardening.conf",
        ),
        Step("Validate the SSH configuration", "sshd -t"),
        Step(
            "Restart the SSH service",
            "systemctl restart sshd 2>/dev/null || systemctl restart ssh",
        ),
    ),
)
