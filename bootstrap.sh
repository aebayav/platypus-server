#!/usr/bin/env bash
# platypus-server bootstrap — one-line installer for the server itself.
#
# Installs the published `platypus-server` Python package via pipx into
# shared paths, runs the pre-flight checks (`platypus doctor`), then
# clones this repository and applies the Ansible playbook locally
# (ansible_connection: local).
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
#   PLATYPUS_PACKAGE=name         PyPI distribution to install (default: platypus-server)
#
# Extra arguments after `--` are passed through to ansible-playbook:
#   curl -fsSL .../bootstrap.sh | sudo bash -s -- --check

set -euo pipefail

REPO_URL="https://github.com/aebayav/platypus-server.git"
ENV_NAME="${PLATYPUS_ENV:-prod}"
TARGET="${PLATYPUS_TARGET:-home}"
REPO_DIR="${PLATYPUS_REPO_DIR:-/opt/platypus-server}"
PACKAGE_NAME="${PLATYPUS_PACKAGE:-platypus-server}"
PACKAGE_SPEC="${PACKAGE_NAME}>=0.2"

# Shared pipx locations: one toolkit install for every user, with the
# `platypus` command on every PATH (root and admin alike).
export PIPX_HOME="/opt/platypus/pipx"
export PIPX_BIN_DIR="/usr/local/bin"

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
echo ">> package     : $PACKAGE_SPEC"

# ---------------------------------------------------------------------------
# System packages: python3, git, curl, sudo and pipx for the toolkit install.
# ---------------------------------------------------------------------------
install_system_packages() {
    echo ">> Installing system packages (python3, git, curl, sudo)..."
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y
        apt-get install -y python3 python3-venv python3-pip git curl ca-certificates sudo
        # Distro package names for pipx vary and some releases do not ship
        # it at all; every miss falls through to the pip fallback below.
        apt-get install -y pipx || true
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip git curl ca-certificates sudo
        dnf install -y pipx || true
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip git curl ca-certificates sudo
        apk add --no-cache py3-pipx || true
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm python python-pip git curl ca-certificates sudo
        pacman -Sy --noconfirm python-pipx || true
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive install python3 python3-pip git curl ca-certificates sudo
        zypper --non-interactive install python3-pipx || true
    else
        echo "Unsupported package manager. Install python3, python3-pip, git and curl manually." >&2
        exit 1
    fi
}

install_system_packages

# Not every distro ships a pipx package: fall back to pip for the tool itself.
if ! command -v pipx >/dev/null 2>&1; then
    echo ">> No distro pipx package - installing pipx via pip..."
    python3 -m pip install --break-system-packages pipx || python3 -m pip install pipx
fi

# ---------------------------------------------------------------------------
# Toolkit: install (or upgrade) the published platypus-server package.
# `--force` makes this idempotent: first install and every re-run alike.
# ---------------------------------------------------------------------------
echo ">> Installing/upgrading the toolkit ($PACKAGE_SPEC) via pipx..."
pipx install --force "$PACKAGE_SPEC"
command -v platypus >/dev/null 2>&1 || {
    echo "platypus command not found after pipx install" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Pre-flight: run the doctor checks before touching anything.
# On a re-run with the stack already up, busy stack ports are expected
# (/opt/platypus/state.yml exists), so --allow-busy downgrades them.
# ---------------------------------------------------------------------------
ALLOW_BUSY=""
[ -f /opt/platypus/state.yml ] && ALLOW_BUSY="--allow-busy"
echo ">> Running pre-flight checks (platypus doctor, target: $TARGET)..."
PLATYPUS_TARGET="$TARGET" platypus doctor $ALLOW_BUSY || {
    echo "Pre-flight checks failed - fix the issues above and re-run." >&2
    exit 1
}

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
