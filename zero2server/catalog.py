"""Catalog of available services for the zero-to-server generator."""

CATALOG: list[dict] = [
    {
        "key": "portainer",
        "title": "Portainer",
        "description": "Docker management UI",
        "image": "portainer/portainer-ce:latest",
        "volumes": [
            "portainer_data:/data",
            "/var/run/docker.sock:/var/run/docker.sock",
        ],
        "internal_port": 9000,
        "host_ports": ["9000:9000"],
        "web": True,
    },
    {
        "key": "uptime-kuma",
        "title": "Uptime Kuma",
        "description": "Self-hosted uptime monitoring",
        "image": "louislam/uptime-kuma:1",
        "volumes": ["uptime_kuma_data:/app/data"],
        "internal_port": 3001,
        "host_ports": ["3001:3001"],
        "web": True,
    },
    {
        "key": "caddy",
        "title": "Caddy",
        "description": "Reverse proxy with automatic HTTPS",
        "image": "caddy:2",
        "volumes": [
            "./Caddyfile:/etc/caddy/Caddyfile:ro",
            "caddy_data:/data",
            "caddy_config:/config",
        ],
        "ports": ["80:80", "443:443", "443:443/udp"],
        "web": False,
        "special": "caddy",
    },
    {
        "key": "watchtower",
        "title": "Watchtower",
        "description": "Auto-update containers",
        "image": "containrrr/watchtower",
        "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
        "command": "--interval 86400 --cleanup",
        "web": False,
    },
]

CATALOG_BY_KEY = {item["key"]: item for item in CATALOG}
