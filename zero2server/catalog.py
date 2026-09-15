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
    # ------------------------------------------------------------------
    # Databases
    # ------------------------------------------------------------------
    {
        "key": "postgresql",
        "title": "PostgreSQL",
        "description": "Relational database (v16, Alpine)",
        "image": "postgres:16-alpine",
        "volumes": ["postgresql_data:/var/lib/postgresql/data"],
        "internal_port": 5432,
        "host_ports": ["5432:5432"],
        "web": False,
        # Template env vars — users should override via .env file
        "env": {
            "POSTGRES_USER": "platypus",
            "POSTGRES_PASSWORD": "changeme",
            "POSTGRES_DB": "platypus",
        },
        "healthcheck": {
            "test": ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER:-platypus}"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    },
    {
        "key": "redis",
        "title": "Redis",
        "description": "In-memory data store (v7, Alpine) with persistence",
        "image": "redis:7-alpine",
        "volumes": ["redis_data:/data"],
        "internal_port": 6379,
        "host_ports": ["6379:6379"],
        "web": False,
        # Persistence: append-only file + RDB snapshot every 60 s if ≥ 1 key changed
        "command": "redis-server --appendonly yes --save 60 1",
        "healthcheck": {
            "test": ["CMD", "redis-cli", "ping"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5,
        },
    },
]

CATALOG_BY_KEY = {item["key"]: item for item in CATALOG}
