"""Session-based authentication, password hashing, CSRF, and rate limiting."""

from __future__ import annotations

import functools
import hmac
import os
import secrets
import threading
import time

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_rate_lock = threading.Lock()
_failed_attempts: dict[str, list[float]] = {}


def get_secret_key() -> str:
    """Return configured ``DASHBOARD_SECRET_KEY`` or generate a random ephemeral key."""
    configured = os.environ.get("DASHBOARD_SECRET_KEY", "").strip()
    if configured:
        return configured
    return secrets.token_hex(32)


def using_default_credentials() -> bool:
    """Return True when neither custom user/password nor password hash is configured."""
    if os.environ.get("DASHBOARD_PASSWORD_HASH", "").strip():
        return False
    user = os.environ.get("DASHBOARD_USER", "admin")
    pw = os.environ.get("DASHBOARD_PASSWORD", "platypus")
    return user == "admin" and pw == "platypus"


# Backward-compatible module constant evaluated at import time
USING_DEFAULT_CREDENTIALS = using_default_credentials()


def reset_rate_limiter() -> None:
    """Clear login failure counters (used by tests)."""
    with _rate_lock:
        _failed_attempts.clear()


def is_rate_limited(client_ip: str, now: float | None = None) -> bool:
    ts = time.monotonic() if now is None else now
    cutoff = ts - RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        history = [t for t in _failed_attempts.get(client_ip, []) if t >= cutoff]
        if history:
            _failed_attempts[client_ip] = history
        else:
            _failed_attempts.pop(client_ip, None)
        return len(history) >= RATE_LIMIT_MAX_ATTEMPTS


def record_login_failure(client_ip: str, now: float | None = None) -> None:
    ts = time.monotonic() if now is None else now
    cutoff = ts - RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        history = [t for t in _failed_attempts.get(client_ip, []) if t >= cutoff]
        history.append(ts)
        _failed_attempts[client_ip] = history


def clear_login_failures(client_ip: str) -> None:
    with _rate_lock:
        _failed_attempts.pop(client_ip, None)


def is_authenticated() -> bool:
    return bool(session.get("authenticated"))


def ensure_csrf_token() -> str:
    """Return or initialize the session's CSRF token."""
    token = session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 16:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def check_credentials(username: str, password: str) -> bool:
    """Constant-time username comparison + Werkzeug hash or constant-time password check."""
    expected_user = os.environ.get("DASHBOARD_USER", "admin")
    pw_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "").strip()

    user_ok = hmac.compare_digest(
        username.encode("utf-8"),
        expected_user.encode("utf-8"),
    )
    if pw_hash:
        pw_ok = check_password_hash(pw_hash, password)
    else:
        expected_pw = os.environ.get("DASHBOARD_PASSWORD", "platypus")
        pw_ok = hmac.compare_digest(
            password.encode("utf-8"),
            expected_pw.encode("utf-8"),
        )
    return bool(user_ok and pw_ok)


def login_required(f):
    """Decorator enforcing session auth and CSRF token on state-changing API calls."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login_page"))

        if request.method in _MUTATING_METHODS and request.path.startswith("/api/"):
            expected = session.get("csrf_token") or ""
            provided = request.headers.get("X-CSRF-Token") or ""
            if not expected or not hmac.compare_digest(
                provided.encode("utf-8"),
                expected.encode("utf-8"),
            ):
                return jsonify({"error": "CSRF token missing or invalid"}), 403

        return f(*args, **kwargs)

    return wrapper
