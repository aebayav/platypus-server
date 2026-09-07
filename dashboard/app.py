"""Flask app serving the mini dashboard and its status API."""

import os
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory

from . import dockerctl, metrics
from .services import get_services

app = Flask(__name__, static_folder="static", static_url_path="/static")

CHECK_TIMEOUT = 1.5


def _http_check(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=CHECK_TIMEOUT) as resp:
            return resp.status
    except Exception:
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


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    return jsonify(_snapshot())


@app.get("/api/containers")
def api_containers():
    try:
        return jsonify({"containers": dockerctl.list_containers()})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/images")
def api_images():
    try:
        return jsonify({"images": dockerctl.list_images()})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/containers")
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
def api_remove_container(cid: str):
    try:
        dockerctl.remove_container(cid)
        return jsonify({"ok": True})
    except dockerctl.DockerError as exc:
        return jsonify({"error": str(exc)}), 500


def main() -> None:
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "5050"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
