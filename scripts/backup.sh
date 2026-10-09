#!/usr/bin/env bash
# =============================================================================
# backup.sh — Platypus Server automated backup script
# =============================================================================
# Configuration can be overridden via environment variables:
#
#   BACKUP_DIRS        Space-separated list of directories to archive
#                      (default: /etc /var/www /home)
#   BACKUP_DEST        Local destination directory
#                      (default: /var/backups/platypus)
#   BACKUP_RETENTION   How many days of local backups to keep (default: 7)
#   S3_BUCKET          S3 bucket name to upload to; leave empty to skip
#   LOG_FILE           Path to the log file
#                      (default: /var/log/platypus-backup.log)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via env)
# ---------------------------------------------------------------------------
BACKUP_DIRS="${BACKUP_DIRS:-/etc /var/www /home}"
BACKUP_DEST="${BACKUP_DEST:-/var/backups/platypus}"
BACKUP_RETENTION="${BACKUP_RETENTION:-7}"
S3_BUCKET="${S3_BUCKET:-}"
LOG_FILE="${LOG_FILE:-/var/log/platypus-backup.log}"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
_log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [$level] $msg" | tee -a "$LOG_FILE"
}

info()  { _log "INFO " "$@"; }
warn()  { _log "WARN " "$@"; }
error() { _log "ERROR" "$@"; }

# ---------------------------------------------------------------------------
# Rotate log file when it exceeds 10 MB
# ---------------------------------------------------------------------------
_rotate_log() {
    if [[ -f "$LOG_FILE" ]] && [[ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt 10485760 ]]; then
        mv "$LOG_FILE" "${LOG_FILE}.1"
        info "Log rotated to ${LOG_FILE}.1"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    _rotate_log

    info "=========================================="
    info "Platypus backup started"
    info "  Dirs      : $BACKUP_DIRS"
    info "  Dest      : $BACKUP_DEST"
    info "  Retention : ${BACKUP_RETENTION} days"
    info "  S3 bucket : ${S3_BUCKET:-<none>}"
    info "=========================================="

    # Ensure destination directory exists
    mkdir -p "$BACKUP_DEST"

    # Build timestamped archive filename
    local timestamp
    timestamp="$(date '+%Y-%m-%d-%H%M%S')"
    local archive="${BACKUP_DEST}/backup-${timestamp}.tar.gz"

    # Create the archive
    info "Creating archive: $archive"
    # shellcheck disable=SC2086
    if tar -czf "$archive" $BACKUP_DIRS 2>>"$LOG_FILE"; then
        local size
        size="$(du -sh "$archive" | cut -f1)"
        info "Archive created successfully (size: $size)"
    else
        error "tar failed — archive may be incomplete: $archive"
        exit 1
    fi

    # Upload to S3 (optional)
    if [[ -n "$S3_BUCKET" ]]; then
        local bucket="${S3_BUCKET%/}"
        if command -v aws &>/dev/null; then
            info "Uploading to s3://${bucket}/ ..."
            if aws s3 cp "$archive" "s3://${bucket}/" >>"$LOG_FILE" 2>&1; then
                info "S3 upload succeeded: s3://${bucket}/$(basename "$archive")"
            else
                error "S3 upload failed — check AWS credentials and bucket name"
                # Do not exit; local backup is still valid
            fi
        else
            warn "aws CLI not found — skipping S3 upload (install awscli to enable)"
        fi
    fi

    # Prune old local backups
    info "Pruning backups older than ${BACKUP_RETENTION} days in ${BACKUP_DEST} ..."
    local pruned=0
    while IFS= read -r -d '' old_file; do
        rm -f "$old_file"
        info "  Deleted: $old_file"
        (( pruned++ )) || true
    done < <(find "$BACKUP_DEST" -maxdepth 1 -name 'backup-*.tar.gz' \
                 -mtime +"$BACKUP_RETENTION" -print0)
    info "Pruned $pruned file(s)"

    # Summary
    local remaining
    remaining="$(find "$BACKUP_DEST" -maxdepth 1 -name 'backup-*.tar.gz' | wc -l)"
    info "Local backups in ${BACKUP_DEST}: $remaining file(s)"
    info "Backup complete: $archive"
    info "=========================================="
}

main "$@"

