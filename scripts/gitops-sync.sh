#!/usr/bin/env bash
set -euo pipefail

# Pull a Git repository containing a declarative Platypus manifest and reconcile.
# Ideal for a systemd timer or webhook-driven GitOps loop.

GITOPS_DIR="${PLATYPUS_GITOPS_DIR:-/etc/platypus/gitops}"
SPEC_FILE="${PLATYPUS_SPEC_FILE:-$GITOPS_DIR/server.yml}"

if [ -d "$GITOPS_DIR/.git" ]; then
    git -C "$GITOPS_DIR" pull --ff-only
fi

platypus apply -f "$SPEC_FILE"
