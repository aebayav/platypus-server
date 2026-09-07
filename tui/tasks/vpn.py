"""Tasks: Tailscale and WireGuard for secure remote access."""

from .base import Step, Task

TAILSCALE_TASK = Task(
    id="tailscale",
    title="Tailscale (secure remote access)",
    description=(
        "Installs Tailscale and connects this machine to your tailnet. After "
        "`tailscale up`, open the printed URL in a browser to authenticate."
    ),
    steps=(
        Step(
            "Download the Tailscale install script",
            "curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale.sh",
            privileged=False,
        ),
        Step("Install Tailscale", "sh /tmp/tailscale.sh"),
        Step("Enable and start tailscaled", "systemctl enable --now tailscaled"),
        Step("Connect to your tailnet (prints an auth URL)", "tailscale up"),
        Step("Show Tailscale status", "tailscale status", privileged=False),
    ),
)

WIREGUARD_TASK = Task(
    id="wireguard",
    title="WireGuard VPN (secure remote access)",
    description=(
        "Installs WireGuard, generates server keys and starts a `wg0` interface "
        "on `10.13.13.1/24` (UDP 51820). Add peers by editing "
        "`/etc/wireguard/wg0.conf` and reloading with "
        "`wg-quick down wg0 && wg-quick up wg0`."
    ),
    steps=(
        Step("Install WireGuard", "apt-get update && apt-get install -y wireguard"),
        Step(
            "Generate the server key pair",
            "umask 077; wg genkey | tee /etc/wireguard/server_private.key | "
            "wg pubkey > /etc/wireguard/server_public.key",
        ),
        Step(
            "Create the wg0 server config",
            'PRIV=$(cat /etc/wireguard/server_private.key); '
            'printf "[Interface]\\nAddress = 10.13.13.1/24\\nListenPort = 51820\\n'
            'PrivateKey = %s\\nSaveConfig = true\\n" "$PRIV" > /etc/wireguard/wg0.conf',
        ),
        Step(
            "Enable IP forwarding",
            'sysctl -w net.ipv4.ip_forward=1 && '
            'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wireguard.conf',
        ),
        Step("Enable and start wg-quick@wg0", "systemctl enable --now wg-quick@wg0"),
        Step(
            "Open the WireGuard port in UFW (if UFW is active)",
            "ufw allow 51820/udp 2>/dev/null || echo 'UFW not active, skipped'",
        ),
        Step(
            "Show the server public key (share with peers)",
            "cat /etc/wireguard/server_public.key",
            privileged=False,
        ),
    ),
)
