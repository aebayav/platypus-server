"""All packaged templates carry claims and weight; routes target host ports."""

from recipe.claims import resolve_claims
from recipe.model import builtin_roles

SAMPLE_ANSWERS = {
    "port": 25565, "web_port": 8080, "http_port": 8081,
    "tcp_port": 9600, "udp_port": 9600, "prometheus_port": 9090,
}


def test_every_template_has_ports_and_weight():
    from recipe.transition import _load_template
    for name in builtin_roles():
        tmpl = _load_template(name)
        assert isinstance(tmpl.get("ports"), list) and tmpl["ports"], name
        assert tmpl.get("weight") in ("main", "companion"), name
        resolve_claims(tmpl, SAMPLE_ANSWERS)  # placeholder-resolvable


def test_http_routes_target_host_ports_not_containers():
    from recipe.transition import _load_template
    for name in ("pihole", "syncthing", "jellyfin", "storage-nextcloud"):
        route = _load_template(name)["caddy"]["route"]
        assert "localhost:" in route
        assert "platypus-" not in route.replace("platypus —", "")
