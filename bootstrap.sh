#!/usr/bin/env bash
# platypus-server bootstrap — one-line installer for the server itself.
#
# Downloads the repository, sets up a virtual environment and runs the
# Ansible playbook locally on this machine (ansible_connection: local).
#
# Usage:
#
#   curl -fsSL https://raw.githubusercontent.com/aebayav/platypus-server/main/bootstrap.sh | sudo bash
#
# Environment variables:
#   PLATYPUS_ENV=dev|prod        Ansible environment to run (default: prod)
#   PLATYPUS_TARGET=home|vps     Server type: home server behind NAT or public
#                                VPS. Changes which installation steps run
#                                (default: home).
#   PLATYPUS_REPO_DIR=/path      Where to clone the repository (default: /opt/platypus-server)
#
# Extra arguments after `--` are passed through to ansible-playbook:
#   curl -fsSL .../bootstrap.sh | sudo bash -s -- --check

set -euo pipefail

REPO_URL="https://github.com/aebayav/platypus-server.git"
ENV_NAME="${PLATYPUS_ENV:-prod}"
TARGET="${PLATYPUS_TARGET:-home}"
REPO_DIR="${PLATYPUS_REPO_DIR:-/opt/platypus-server}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo $0" >&2
    exit 1
fi

case "$TARGET" in
    home|vps) ;;
    *)
        echo "Unknown target '$TARGET'. Use PLATYPUS_TARGET=home or PLATYPUS_TARGET=vps." >&2
        exit 1
        ;;
esac

echo "== platypus-server bootstrap =="
echo ">> environment : $ENV_NAME"
echo ">> target      : $TARGET"
echo ">> repo dir    : $REPO_DIR"

# ---------------------------------------------------------------------------
# Pre-flight: run the doctor checks before touching anything.
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    DOCTOR_URL="https://raw.githubusercontent.com/aebayav/platypus-server/main/doctor.py"
    echo ">> Running pre-flight checks (doctor, target: $TARGET)..."
    if curl -fsSL "$DOCTOR_URL" -o /tmp/platypus-doctor.py; then
        if ! PLATYPUS_TARGET="$TARGET" python3 /tmp/platypus-doctor.py; then
            echo "Pre-flight checks failed — fix the issues above and re-run." >&2
            rm -f /tmp/platypus-doctor.py
            exit 1
        fi
        rm -f /tmp/platypus-doctor.py
    else
        echo "WARNING: could not download the doctor checks; continuing without pre-flight." >&2
    fi
else
    echo "ERROR: python3 is not installed. The setup requires Python 3.10+." >&2
    echo "  Install it first, e.g.:  apt-get update && apt-get install -y python3" >&2
    exit 1
fi

install_system_packages() {
    echo ">> Installing system packages (python3, git, curl, sudo)..."
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y
        apt-get install -y python3 python3-venv python3-pip git curl ca-certificates sudo
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip git curl ca-certificates sudo
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip git curl ca-certificates sudo
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm python python-pip git curl ca-certificates sudo
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install python3 python3-pip git curl ca-certificates sudo
    else
        echo "Unsupported package manager. Install python3, python3-pip, git and curl manually." >&2
        exit 1
    fi
}

install_system_packages

# Locate or fetch the repository.
if [ -d "playbooks" ] && [ -f "playbooks/site.yml" ]; then
    REPO_DIR="$(pwd)"
    echo ">> Using the existing checkout: $REPO_DIR"
elif [ -d "$REPO_DIR/.git" ]; then
    echo ">> Updating the existing checkout: $REPO_DIR"
    (cd "$REPO_DIR" && git pull --ff-only) || true
else
    echo ">> Cloning $REPO_URL..."
    git clone --depth 1 "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

if [ ! -f "inventory/$ENV_NAME/hosts.yml" ]; then
    echo "Unknown environment '$ENV_NAME'. Use PLATYPUS_ENV=dev or PLATYPUS_ENV=prod." >&2
    exit 1
fi

VENV="$REPO_DIR/.venv"

echo ">> Creating the virtual environment (if missing)..."
[ -d "$VENV" ] || python3 -m venv "$VENV"

echo ">> Installing Ansible..."
"$VENV/bin/pip" install --upgrade pip
ANSIBLE_REQ="$(grep -E '^ansible-core' requirements.txt | head -n1 || true)"
if [ -n "$ANSIBLE_REQ" ]; then
    "$VENV/bin/pip" install "$ANSIBLE_REQ"
else
    "$VENV/bin/pip" install "ansible-core>=2.16,<2.19"
fi

echo ">> Installing Ansible collections..."
"$VENV/bin/ansible-galaxy" collection install -r requirements.yml -p collections

echo ">> Running the playbook (environment: $ENV_NAME, target: $TARGET)..."
"$VENV/bin/ansible-playbook" playbooks/site.yml -i "inventory/$ENV_NAME" \
    -e "platypus_target=$TARGET" "$@"

echo ""
echo "== Done. The server is configured ($TARGET target). =="
