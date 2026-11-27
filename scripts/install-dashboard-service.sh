#!/usr/bin/env bash
set -euo pipefail

# Install the Platypus dashboard as a hardened systemd service.
#
#   sudo ./scripts/install-dashboard-service.sh [REPO_DIR]
#
# Creates a virtual environment, installs Waitress + dashboard dependencies,
# provisions a persistent random secret key in /etc/platypus/dashboard.env,
# and binds to 127.0.0.1:5050 by default (use Caddy or Tailscale for remote access).

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo $0" >&2
    exit 1
fi

REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
VENV="$REPO_DIR/.venv"
UNIT="/etc/systemd/system/platypus-dashboard.service"
ENV_DIR="/etc/platypus"
ENV_FILE="$ENV_DIR/dashboard.env"
SERVICE_USER="${DASHBOARD_SERVICE_USER:-platypus-dash}"
BIND_HOST="${DASHBOARD_HOST:-127.0.0.1}"
BIND_PORT="${DASHBOARD_PORT:-5050}"

echo ">> Repo dir : $REPO_DIR"
echo ">> venv      : $VENV"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install it first: apt install -y python3 python3-venv python3-pip" >&2
    exit 1
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if getent group docker >/dev/null 2>&1; then
    usermod -aG docker "$SERVICE_USER" || true
fi

echo ">> Creating virtual environment (if missing)..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV" || {
        echo "Failed to create venv. Install: apt install -y python3-venv" >&2
        exit 1
    }
fi

echo ">> Installing dashboard and production WSGI server (waitress)..."
"$VENV/bin/pip" install --upgrade pip >/dev/null
(cd "$REPO_DIR" && "$VENV/bin/pip" install -e "." waitress)

mkdir -p "$ENV_DIR"
chmod 750 "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "$ENV_FILE" <<ENVEOF
DASHBOARD_HOST=$BIND_HOST
DASHBOARD_PORT=$BIND_PORT
DASHBOARD_SECRET_KEY=$SECRET_KEY
ENVEOF
    chown root:"$SERVICE_USER" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
fi

echo ">> Writing hardened systemd unit -> $UNIT"
cat > "$UNIT" <<EOF
[Unit]
Description=Platypus web dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/python -m dashboard
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/platypus

[Install]
WantedBy=multi-user.target
EOF

echo ">> Enabling and starting the service..."
systemctl daemon-reload
systemctl enable --now platypus-dashboard

echo ""
echo ">> Done. Status:"
systemctl status platypus-dashboard --no-pager -l || true
echo ""
echo "Dashboard listening on: http://$BIND_HOST:$BIND_PORT"
