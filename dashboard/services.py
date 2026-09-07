"""Service registry for the dashboard.

Add your own services here. Each entry supports:

    {"name": "Label", "url": "http://host:port"}   -> HTTP check
    {"name": "Label", "host": "host", "port": N}   -> TCP check
"""

SERVICES: list[dict] = [
    {"name": "Portainer", "url": "http://localhost:9000"},
    {"name": "Uptime Kuma", "url": "http://localhost:3001"},
    # {"name": "My App", "url": "http://localhost:8080"},
    # {"name": "SSH", "host": "localhost", "port": 22},
]


def get_services() -> list[dict]:
    return SERVICES
