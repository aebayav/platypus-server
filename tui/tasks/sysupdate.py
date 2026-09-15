"""Task: update all system packages via apt."""

from .base import Step, Task

SYSUPDATE_TASK = Task(
    id="sysupdate",
    title="System Update",
    description=(
        "Runs a full system package update: refreshes the package index, upgrades "
        "all installed packages to their latest versions, and cleans up obsolete "
        "packages and cached archives."
    ),
    warning=(
        "This will upgrade **all installed packages** to their latest versions. "
        "On production systems, test in a staging environment first and make sure "
        "you have a rollback plan."
    ),
    steps=(
        Step(
            "Refresh the package index",
            "apt-get update",
        ),
        Step(
            "Upgrade all installed packages",
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
        ),
        Step(
            "Remove obsolete packages",
            "apt-get autoremove -y",
        ),
        Step(
            "Clean cached package archives",
            "apt-get autoclean",
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

