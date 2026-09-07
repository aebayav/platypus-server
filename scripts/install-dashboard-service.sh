#!/usr/bin/env bash
set -euo pipefail

# Install the Platypus dashboard as a systemd service.
#
#   sudo ./scripts/install-dashboard-service.sh [REPO_DIR]
#
# This creates a virtual environment, installs the dashboard dependencies and
# registers a `platypus-dashboard.service` that starts on boot and restarts on
# failure.

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo $0" >&2
    exit 1
fi

REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
VENV="$REPO_DIR/.venv"
UNIT="/etc/systemd/system/platypus-dashboard.service"

echo ">> Repo dir : $REPO_DIR"
echo ">> venv      : $VENV"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install it first: apt install -y python3 python3-venv python3-pip" >&2
    exit 1
fi

echo ">> Creating virtual environment (if missing)..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV" || {
        echo "Failed to create venv. Install: apt install -y python3-venv" >&2
        exit 1
    }
fi

echo ">> Installing dashboard dependencies..."
"$VENV/bin/pip" install --upgrade pip >/dev/null
(cd "$REPO_DIR" && "$VENV/bin/pip" install -e ".[dashboard]")

echo ">> Writing systemd unit -> $UNIT"
cat > "$UNIT" <<EOF
[Unit]
Description=Platypus web dashboard
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO_DIR
ExecStart=$VENV/bin/python -m dashboard
Environment=DASHBOARD_HOST=0.0.0.0
Environment=DASHBOARD_PORT=5050
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo ">> Enabling and starting the service..."
systemctl daemon-reload
systemctl enable --now platypus-dashboard

echo ""
echo ">> Done. Status:"
systemctl status platypus-dashboard --no-pager -l || true

IP="$(tailscale ip 2>/dev/null | head -n1 || true)"
[ -z "$IP" ] && IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "Dashboard URL: http://$IP:5050"
