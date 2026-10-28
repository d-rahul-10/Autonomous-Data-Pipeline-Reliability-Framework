"""Request middleware: authentication, CSRF, security headers, and error handling."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from flask import Flask, jsonify, make_response, redirect, request, session
from werkzeug.exceptions import RequestEntityTooLarge

from app.config import AppConfig
from app.exceptions import PipelineError


def _dashboard_paths() -> set[str]:
    return {"/", "/auth"}


def _csrf_exempt_paths() -> set[str]:
    return {"/api/auth/login", "/api/auth/signup"}


def init_middleware(app: Flask, config: AppConfig) -> None:
    production = config.production

    @app.context_processor
    def expose_csrf_token():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return {"csrf_token": token}

    @app.before_request
    def require_dashboard_session():
        """Keep dashboard pages/APIs private and reject revoked or expired sessions."""
        from app.api.monitoring import _session_valid, _csrf_valid

        if request.path in _csrf_exempt_paths():
            submitted_token = request.headers.get("X-CSRF-Token", "")
            expected_token = session.get("csrf_token", "")
            if not expected_token or not secrets.compare_digest(submitted_token, expected_token):
                return jsonify(error="Request verification failed. Refresh the page and try again."), 403
            return None

        dashboard_page = request.path in _dashboard_paths()
        dashboard_api = request.path.startswith("/api/") and not request.path.startswith("/api/auth/")
        protected_auth_api = request.path == "/api/auth/logout"
        if not dashboard_page and not dashboard_api and not protected_auth_api:
            return None

        if dashboard_page and "user_id" not in session:
            return None

        if not _session_valid():
            session.clear()
            if dashboard_api or protected_auth_api:
                return jsonify(error="Authentication required. Please sign in."), 401
            if request.path == "/":
                return redirect("/auth")
            return None

        submitted_token = request.headers.get("X-CSRF-Token", "")
        expected_token = session.get("csrf_token", "")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            not expected_token or not secrets.compare_digest(submitted_token, expected_token)
        ):
            return jsonify(error="Request verification failed. Refresh the page and try again."), 403
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if production and request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify(error="The uploaded file exceeds the allowed limit."), 413

    @app.errorhandler(PipelineError)
    def handle_pipeline_error(error: PipelineError):
        return jsonify(error=error.message), error.status_code

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Not found."), 404

    @app.errorhandler(500)
    def internal_error(_error):
        app.logger.exception("unhandled server error")
        return jsonify(error="An internal server error occurred."), 500
