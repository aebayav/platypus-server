"""Task: update all system packages across Linux distributions."""

from .base import Step, Task

SYSUPDATE_TASK = Task(
    id="sysupdate",
    title="System Update",
    description=(
        "Runs a full system package update across Debian/Ubuntu (apt), "
        "RHEL/Fedora (dnf), Arch (pacman), openSUSE (zypper), and Alpine (apk)."
    ),
    warning=(
        "This will upgrade **all installed packages** to their latest versions. "
        "On production systems, test in a staging environment first and make sure "
        "you have a rollback plan."
    ),
    steps=(
        Step(
            "Refresh and upgrade installed packages",
            "if command -v apt-get >/dev/null 2>&1; then "
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y && "
            "apt-get autoremove -y && apt-get autoclean; "
            "elif command -v dnf >/dev/null 2>&1; then dnf upgrade -y && dnf autoremove -y; "
            "elif command -v pacman >/dev/null 2>&1; then pacman -Syu --noconfirm; "
            "elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive update; "
            "elif command -v apk >/dev/null 2>&1; then apk update && apk upgrade; fi",
        ),
        Step(
            "Show pending reboot status",
            "test -f /var/run/reboot-required "
            "&& echo 'REBOOT REQUIRED — run: reboot' "
            "|| echo 'No reboot required.'",
            privileged=False,
        ),
    ),
)
