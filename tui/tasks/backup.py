"""Task: back up directories to tar.gz with an optional S3 upload."""

from .base import Step, Task

# ---------------------------------------------------------------------------
# Sentinel task shown in the menu.
# The real steps are built dynamically by build_backup_steps() once the
# user fills in the BackupConfigModal in app.py.
# ---------------------------------------------------------------------------

BACKUP_TASK = Task(
    id="backup",
    title="Backup",
    description=(
        "Archives one or more directories into a timestamped `.tar.gz` file and "
        "optionally uploads it to an S3 bucket using the AWS CLI.  "
        "You will be prompted for the directories to back up and an S3 bucket name "
        "before the task starts."
    ),
    # Steps are intentionally empty — app.py replaces them via build_backup_steps().
    steps=(),
)


def build_backup_steps(dirs: str, s3_bucket: str) -> tuple[Step, ...]:
    """Return a concrete tuple of Steps for the given backup parameters.

    Args:
        dirs:      Space-separated list of directories to archive
                   (e.g. ``"/etc /var/www /home"``).
        s3_bucket: S3 bucket name to upload to, or an empty string to skip
                   the upload step.
    """
    dirs = dirs.strip() or "/etc /var/www /home"
    timestamp_cmd = "$(date +%Y-%m-%d-%H%M%S)"
    archive = f"/tmp/backup-{timestamp_cmd}.tar.gz"

    steps: list[Step] = [
        Step(
            "Check available disk space",
            "df -h /tmp",
            privileged=False,
        ),
        Step(
            f"Create archive of: {dirs}",
            f"tar -czf {archive} {dirs}",
        ),
        Step(
            "Show archive size",
            f"ls -lh {archive}",
            privileged=False,
        ),
    ]

    if s3_bucket.strip():
        bucket = s3_bucket.strip().rstrip("/")
        steps += [
            Step(
                "Check AWS CLI is available",
                "command -v aws || (echo 'aws CLI not found — install awscli first' && exit 1)",
                privileged=False,
            ),
            Step(
                f"Upload archive to s3://{bucket}/",
                f"aws s3 cp {archive} s3://{bucket}/",
                privileged=False,
            ),
            Step(
                "Confirm S3 object",
                f"aws s3 ls s3://{bucket}/ | tail -5",
                privileged=False,
            ),
        ]

    steps.append(
        Step(
            "List recent backups in /tmp",
            "ls -lht /tmp/backup-*.tar.gz 2>/dev/null | head -10",
            privileged=False,
        )
    )

    return tuple(steps)

