"""Flask app serving the Platypus dashboard and its REST API."""

import os
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, redirect, request, send_from_directory, session, url_for

from . import compose, dockerctl, firewall, metrics, systemd
from .auth import (
    USING_DEFAULT_CREDENTIALS,
    check_credentials,
    is_authenticated,
    login_required,
)
from .services import get_services

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get(
    "DASHBOARD_SECRET_KEY", "platypus-dashboard-secret-change-me"
)

# Record the start time for the /health uptime field.
_APP_START: float = time.monotonic()
_APP_START_UTC: datetime = datetime.now(timezone.utc)

CHECK_TIMEOUT = 1.5

# ---------------------------------------------------------------------------
# Background metrics recorder
# ---------------------------------------------------------------------------

def _start_metrics_recorder() -> None:
    """Record CPU + memory into the history ringbuffer every 3 seconds."""
    def _loop() -> None:
        while True:
            try:
                m = metrics.get_metrics()
                metrics.history.record(
                    m["cpu_percent"],
                    m["memory"]["percent"],
                )
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)

    t = threading.Thread(target=_loop, daemon=True, name="metrics-recorder")
    t.start()


_start_metrics_recorder()

# ---------------------------------------------------------------------------
# Service health helpers
# ---------------------------------------------------------------------------

def _http_check(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=CHECK_TIMEOUT) as resp:
            return resp.status
    except Exception:  # noqa: BLE001
        return None


def _tcp_check(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CHECK_TIMEOUT):
            return True
    except OSError:
        return False


def _check_service(svc: dict) -> dict:
    if "url" in svc:
        code = _http_check(svc["url"])
        return {
            "name": svc["name"],
            "url": svc["url"],
            "status": "up" if code is not None else "down",
            "http_code": code,
        }
    host = svc.get("host", "localhost")
    port = svc.get("port")
    up = port is not None and _tcp_check(host, port)
    return {
        "name": svc["name"],
        "url": f"{host}:{port}" if port is not None else host,
        "status": "up" if up else ("down" if port is not None else "unknown"),
    }


def _snapshot() -> dict:
    items = get_services()
    with ThreadPoolExecutor(max_workers=len(items) or 1) as pool:
        services = list(pool.map(_check_service, items))
    return {"metrics": metrics.get_metrics(), "services": services}

# ---------------------------------------------------------------------------
# Public health endpoint — no auth required (for monitoring tools)
# ---------------------------------------------------------------------------

_DASHBOARD_VERSION = "0.1.0"


@app.get("/health")
def health():
    """Lightweight health check used by Uptime Kuma, Prometheus, etc.

    Always returns HTTP 200.  The ``status`` field signals application health:
    - ``"ok"``       — everything is within normal thresholds
    - ``"degraded"`` — CPU > 95 % or disk > 90 %
    """
    try:
        m = metrics.get_metrics()
        cpu: float = m.get("cpu_percent", 0.0)
        mem: float = m.get("memory", {}).get("percent", 0.0)
        disk: float = m.get("disk", {}).get("percent", 0.0)
    except Exception:  # noqa: BLE001
        cpu = mem = disk = 0.0

    degraded = cpu > 95.0 or disk > 90.0
    uptime_seconds = round(time.monotonic() - _APP_START)

    return jsonify(
        {
            "status": "degraded" if degraded else "ok",
            "version": _DASHBOARD_VERSION,
            "uptime_seconds": uptime_seconds,
            "started_at": _APP_START_UTC.isoformat(),
            "checks": {
                "cpu_percent": round(cpu, 1),
                "memory_percent": round(mem, 1),
                "disk_percent": round(disk, 1),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Auth routes (public)
# ---------------------------------------------------------------------------

@app.get("/login")
def login_page():
    if is_authenticated():
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "login.html")


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    if check_credentials(
        (data.get("username") or "").strip(),
        (data.get("password") or ""),
    ):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Invalid credentials"}), 401


@app.get("/api/logout")
@app.post("/api/logout")
def api_logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.get("/api/auth/info")
def api_auth_info():
    """Public endpoint — returns whether default credentials are active."""
    return jsonify({"default_credentials": USING_DEFAULT_CREDENTIALS})

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@app.get("/")
@login_required
def index():
    return send_from_directory(app.static_folder, "index.html")

# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

@app.get("/api/status")
@login_required
def status():
    return jsonify(_snapshot())


@app.get("/api/metrics/history")
@login_required
def api_metrics_history():
    points = request.args.get("points", 200, type=int)
    return jsonify(metrics.history.snapshot(points=points))


@app.get("/api/processes")
@login_required
def api_processes():
    limit = request.args.get("limit", 20, type=int)
    return jsonify({"processes": metrics.get_processes(limit=limit)})


@app.get("/api/firewall")
@login_required
def api_firewall():
    return jsonify(firewall.get_firewall_rules())

# ---------------------------------------------------------------------------
# Container management
# ---------------------------------------------------------------------------

@app.get("/api/containers")
@login_required
def api_containers():
    try:
        return jsonify({"containers": dockerctl.list_containers()})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/images")
@login_required
def api_images():
    try:
        return jsonify({"images": dockerctl.list_images()})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/containers")
@login_required
def api_run_container():
    payload = request.get_json(silent=True) or {}
    image = (payload.get("image") or "").strip()
    if not image:
        return jsonify({"error": "image is required"}), 400
    try:
        cid = dockerctl.run_container(
            image,
            name=(payload.get("name") or "").strip() or None,
            ports=(payload.get("ports") or "").strip() or None,
        )
        return jsonify({"ok": True, "id": cid})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/containers/<cid>/<action>")
@login_required
def api_container_action(cid: str, action: str):
    actions = {
        "start": dockerctl.start_container,
        "stop": dockerctl.stop_container,
        "restart": dockerctl.restart_container,
    }
    if action not in actions:
        return jsonify({"error": "unknown action"}), 400
    try:
        actions[action](cid)
        return jsonify({"ok": True})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.delete("/api/containers/<cid>")
@login_required
def api_remove_container(cid: str):
    try:
        dockerctl.remove_container(cid)
        return jsonify({"ok": True})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/containers/<cid>/logs")
@login_required
def api_container_logs(cid: str):
    tail = request.args.get("tail", 200, type=int)
    try:
        return jsonify({"lines": dockerctl.get_container_logs(cid, tail=tail)})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/containers/<cid>/stats")
@login_required
def api_container_stats(cid: str):
    try:
        return jsonify(dockerctl.get_container_stats(cid))
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/images/pull")
@login_required
def api_pull_image():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("image") or "").strip()
    if not name:
        return jsonify({"error": "image is required"}), 400
    try:
        msg = dockerctl.pull_image(name)
        return jsonify({"ok": True, "message": msg})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.delete("/api/images/<image_id>")
@login_required
def api_remove_image(image_id: str):
    force = request.args.get("force", "false").lower() == "true"
    try:
        dockerctl.remove_image(image_id, force=force)
        return jsonify({"ok": True})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Docker Compose stacks
# ---------------------------------------------------------------------------

@app.get("/api/compose")
@login_required
def api_compose_list():
    try:
        return jsonify({"stacks": compose.list_stacks()})
    except compose.ComposeError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/compose/<stack>/<action>")
@login_required
def api_compose_action(stack: str, action: str):
    try:
        msg = compose.stack_action(stack, action)
        return jsonify({"ok": True, "message": msg})
    except compose.ComposeError as exc:
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Systemd service management
# ---------------------------------------------------------------------------

@app.get("/api/systemd")
@login_required
def api_systemd_list():
    units = [
        svc.get("systemd")
        for svc in get_services()
        if svc.get("systemd")
    ]
    # Also include well-known platform services if not already listed
    defaults = ["docker", "caddy", "ssh", "ufw", "tailscaled", "wg-quick@wg0"]
    for u in defaults:
        if u not in units:
            units.append(u)
    statuses = []
    for unit in units:
        try:
            statuses.append(systemd.get_service_status(unit))
        except systemd.SystemdError as exc:
            statuses.append({"unit": unit, "active": "unknown", "error": str(exc)})
    return jsonify({"services": statuses})


@app.post("/api/systemd/<unit>/<action>")
@login_required
def api_systemd_action(unit: str, action: str):
    try:
        systemd.service_action(unit, action)
        return jsonify({"ok": True})
    except (systemd.SystemdError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Recipe / role status
# ---------------------------------------------------------------------------

@app.get("/api/recipe")
@login_required
def api_recipe():
    """Return active role and dormant roles read from /opt/platypus/state.yml."""
    import os
    from pathlib import Path

    state_file = Path("/opt/platypus/state.yml")
    roles_dir  = Path("/opt/platypus/roles")

    # Parse state.yml (gracefully handle missing file)
    active_name: str | None = None
    activated_at: str | None = None
    history: list[dict] = []

    if state_file.exists():
        try:
            import yaml as _yaml
            with state_file.open(encoding="utf-8") as fh:
                raw = _yaml.safe_load(fh) or {}
            active_name  = raw.get("active")
            activated_at = str(raw.get("activated_at") or "")
            history      = raw.get("history") or []
        except Exception:  # noqa: BLE001
            pass

    def _dir_size_mb(path: Path) -> float:
        total = sum(
            f.stat().st_size
            for f in path.rglob("*")
            if f.is_file()
        )
        return round(total / (1024 * 1024), 1)

    # Build active entry
    active: dict | None = None
    if active_name:
        data_dir = roles_dir / active_name / "data"
        active = {
            "name": active_name,
            "status": "active",
            "activated_at": activated_at,
            "data_size_mb": _dir_size_mb(data_dir) if data_dir.exists() else 0.0,
        }

    # Build dormant list
    dormant: list[dict] = []
    if roles_dir.exists():
        for role_dir in sorted(roles_dir.iterdir()):
            if not role_dir.is_dir() or role_dir.name == active_name:
                continue
            data_dir     = role_dir / "data"
            answers_file = role_dir / "answers.yml"
            last_active  = next(
                (
                    h.get("deactivated_at")
                    for h in reversed(history)
                    if h.get("role") == role_dir.name
                ),
                None,
            )
            dormant.append({
                "name": role_dir.name,
                "status": "dormant",
                "configured": answers_file.exists(),
                "last_active": str(last_active) if last_active else None,
                "data_size_mb": _dir_size_mb(data_dir) if data_dir.exists() else 0.0,
            })

    return jsonify({
        "active": active,
        "dormant": dormant,
        "history": history[-10:],   # last 10 transitions
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "5050"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
