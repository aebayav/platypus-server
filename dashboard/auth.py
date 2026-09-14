"""Session-based authentication for the dashboard."""
from __future__ import annotations

import functools
import os

from flask import jsonify, redirect, request, session, url_for

DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "platypus")

# Warn at startup when defaults are still in use.
USING_DEFAULT_CREDENTIALS = (
    DASHBOARD_USER == "admin" and DASHBOARD_PASSWORD == "platypus"
)


def is_authenticated() -> bool:
    return bool(session.get("authenticated"))


def check_credentials(username: str, password: str) -> bool:
    return username == DASHBOARD_USER and password == DASHBOARD_PASSWORD


def login_required(f):
    """Decorator that redirects to /login (HTML) or returns 401 (API)."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper
