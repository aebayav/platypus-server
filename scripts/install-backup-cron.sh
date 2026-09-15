#!/usr/bin/env bash
# =============================================================================
# install-backup-cron.sh — Install a cron job for the Platypus backup script
# =============================================================================
# Usage:
#   sudo bash install-backup-cron.sh [OPTIONS]
#
# Options:
#   --schedule <daily|weekly|custom>   Cron schedule (prompted if omitted)
#   --script   <path>                  Path to backup.sh (auto-detected)
#   --dest     <dir>                   BACKUP_DEST override
#   --s3       <bucket>                S3_BUCKET override
#   --help                             Show this help message
# =============================================================================
set -euo pipefail

CRON_FILE="/etc/cron.d/platypus-backup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  → $*"; }

usage() {
    sed -n '2,15p' "$0" | sed 's/^# //'
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SCHEDULE=""
DEST_OVERRIDE=""
S3_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --schedule) SCHEDULE="$2"; shift 2 ;;
        --script)   BACKUP_SCRIPT="$2"; shift 2 ;;
        --dest)     DEST_OVERRIDE="$2"; shift 2 ;;
        --s3)       S3_OVERRIDE="$2"; shift 2 ;;
        --help|-h)  usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Root check
# ---------------------------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
    die "This script must be run as root (or with sudo)."
fi

# ---------------------------------------------------------------------------
# Verify backup script exists and is executable
# ---------------------------------------------------------------------------
if [[ ! -f "$BACKUP_SCRIPT" ]]; then
    die "backup.sh not found at: $BACKUP_SCRIPT  (use --script to specify path)"
fi

chmod +x "$BACKUP_SCRIPT"
info "Backup script  : $BACKUP_SCRIPT"

# ---------------------------------------------------------------------------
# Choose schedule interactively if not provided
# ---------------------------------------------------------------------------
if [[ -z "$SCHEDULE" ]]; then
    echo ""
    echo "Select backup frequency:"
    echo "  1) Daily   — runs every day at 02:00"
    echo "  2) Weekly  — runs every Sunday at 02:00"
    echo "  3) Custom  — enter a cron expression"
    echo ""
    read -rp "Choice [1/2/3]: " choice
    case "$choice" in
        1|daily)   SCHEDULE="daily" ;;
        2|weekly)  SCHEDULE="weekly" ;;
        3|custom)  SCHEDULE="custom" ;;
        *)         SCHEDULE="daily"; echo "  (defaulting to daily)" ;;
    esac
fi

case "$SCHEDULE" in
    daily)  CRON_EXPR="0 2 * * *" ;;
    weekly) CRON_EXPR="0 2 * * 0" ;;
    custom)
        read -rp "Enter cron expression (e.g. '0 3 * * 1'): " CRON_EXPR
        [[ -z "$CRON_EXPR" ]] && die "Cron expression cannot be empty."
        ;;
    *)
        # Accept a raw cron expression passed via --schedule
        CRON_EXPR="$SCHEDULE"
        ;;
esac

info "Schedule       : $CRON_EXPR"

# ---------------------------------------------------------------------------
# Build the env line for the cron job
# ---------------------------------------------------------------------------
ENV_LINE=""
[[ -n "$DEST_OVERRIDE" ]] && ENV_LINE+="BACKUP_DEST=${DEST_OVERRIDE} "
[[ -n "$S3_OVERRIDE"   ]] && ENV_LINE+="S3_BUCKET=${S3_OVERRIDE} "

CRON_CMD="${ENV_LINE}bash ${BACKUP_SCRIPT}"

# ---------------------------------------------------------------------------
# Write /etc/cron.d file
# ---------------------------------------------------------------------------
cat > "$CRON_FILE" <<EOF
# Platypus automated backup — managed by install-backup-cron.sh
# To edit: sudo nano $CRON_FILE
# To remove: sudo rm $CRON_FILE

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

$CRON_EXPR root $CRON_CMD
EOF

chmod 644 "$CRON_FILE"

echo ""
echo "✓ Cron job installed at: $CRON_FILE"
echo "  Schedule : $CRON_EXPR"
echo "  Command  : $CRON_CMD"
echo ""
echo "To test immediately:"
echo "  sudo bash $BACKUP_SCRIPT"
echo ""
echo "To remove the cron job:"
echo "  sudo rm $CRON_FILE"

