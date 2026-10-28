"""Authentication routes (signup, login, logout, session inspection)."""
from __future__ import annotations

import re
import secrets
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.db import connect
from app.exceptions import ValidationError
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _config():
    return current_app.config["APP_CONFIG"]


def _repositories():
    return UserRepository(_config()), SessionRepository(_config())


def validate_email(email: str) -> bool:
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) is not None


def validate_password(password: str):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    return True, ""


def create_session(session_repo: SessionRepository, user_id: int, remember: bool):
    session_id = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + (timedelta(days=30) if remember else timedelta(hours=24))
    ip_address = request.remote_addr
    user_agent = request.headers.get("User-Agent", "")[:500]
    session_repo.create(user_id, session_id, expires_at.isoformat(), ip_address, user_agent)
    return session_id


def _oauth_settings(provider: str) -> dict | None:
    config = _config()
    providers = {
        "google": {
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "profile_url": "https://openidconnect.googleapis.com/v1/userinfo",
            "scope": "openid email profile",
        },
        "github": {
            "client_id": config.github_client_id,
            "client_secret": config.github_client_secret,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "profile_url": "https://api.github.com/user",
            "scope": "read:user user:email",
        },
    }
    settings = providers.get(provider)
    if not settings or not settings["client_id"] or not settings["client_secret"]:
        return None
    return settings


def _oauth_redirect_uri(provider: str) -> str:
    base_url = _config().oauth_redirect_base_url or request.url_root.rstrip("/")
    return f"{base_url}/api/auth/oauth/{provider}/callback"


def _oauth_json(url: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    payload = urlencode(data).encode() if data is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    response = Request(url, data=payload, headers=request_headers, method="POST" if payload else "GET")
    with urlopen(response, timeout=10) as result:  # nosec B310 - fixed provider URLs
        return json.loads(result.read().decode("utf-8"))


def _oauth_profile(provider: str, access_token: str, profile_url: str) -> tuple[str, str, str]:
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "PipelineIQ"}
    profile = _oauth_json(profile_url, headers=headers)
    if provider == "google":
        if not profile.get("email_verified"):
            raise ValueError("Your Google account must have a verified email address.")
        provider_id = str(profile.get("sub", ""))
        email = str(profile.get("email", "")).strip().lower()
        name = str(profile.get("name") or email.split("@")[0]).strip()
    else:
        provider_id = str(profile.get("id", ""))
        email = str(profile.get("email") or "").strip().lower()
        if not email:
            emails = _oauth_json("https://api.github.com/user/emails", headers=headers)
            primary = next((item for item in emails if item.get("primary") and item.get("verified")), None)
            email = str((primary or {}).get("email", "")).strip().lower()
        name = str(profile.get("name") or profile.get("login") or email.split("@")[0]).strip()
    if not provider_id or not email or not validate_email(email):
        raise ValueError(f"GitHub did not provide a usable email address." if provider == "github" else "Google did not provide a usable profile.")
    return provider_id, name[:100], email


@auth_bp.get("/oauth/<provider>/start")
def oauth_start(provider: str):
    settings = _oauth_settings(provider)
    if not settings:
        return redirect("/auth?oauth_error=provider_not_configured")
    state = secrets.token_urlsafe(32)
    session[f"oauth_state_{provider}"] = state
    query = urlencode({
        "client_id": settings["client_id"],
        "redirect_uri": _oauth_redirect_uri(provider),
        "response_type": "code",
        "scope": settings["scope"],
        "state": state,
    })
    return redirect(f"{settings['authorize_url']}?{query}")


@auth_bp.get("/oauth/<provider>/callback")
def oauth_callback(provider: str):
    settings = _oauth_settings(provider)
    expected_state = session.pop(f"oauth_state_{provider}", "")
    returned_state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not settings:
        return redirect("/auth?oauth_error=provider_not_configured")
    if not expected_state or not secrets.compare_digest(expected_state, returned_state) or not code:
        return redirect("/auth?oauth_error=verification_failed")
    try:
        token = _oauth_json(settings["token_url"], data={
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "code": code,
            "redirect_uri": _oauth_redirect_uri(provider),
            "grant_type": "authorization_code",
        })
        access_token = str(token.get("access_token", ""))
        if not access_token:
            raise ValueError("The sign-in provider did not return an access token.")
        provider_id, name, email = _oauth_profile(provider, access_token, settings["profile_url"])
        user_repo, session_repo = _repositories()
        user_id = user_repo.find_or_create_oauth_user(
            provider, provider_id, name, email,
            generate_password_hash(secrets.token_urlsafe(48), method="pbkdf2:sha256"),
        )
        user = user_repo.find_by_id(user_id)
        if not user or not user["is_active"]:
            return redirect("/auth?oauth_error=account_unavailable")
        session_id = create_session(session_repo, user_id, remember=True)
        session.clear()
        session["user_id"] = user_id
        session["session_id"] = session_id
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session.permanent = True
        session_repo.delete_expired()
        return redirect("/")
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        current_app.logger.info("%s OAuth sign-in failed: %s", provider, exc)
        return redirect("/auth?oauth_error=sign_in_failed")


@auth_bp.route("/signup", methods=["POST"])
def signup():
    user_repo, session_repo = _repositories()
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify(error="Invalid request data"), 400

    name = data.get("name", "")
    email = data.get("email", "")
    password = data.get("password", "")
    if not all(isinstance(value, str) for value in (name, email, password)):
        return jsonify(error="Name, email, and password must be text values"), 400
    name = name.strip()
    email = email.strip().lower()
    if len(email) > 254:
        return jsonify(error="Email address is too long"), 400
    if not name or len(name) < 2 or len(name) > 100:
        return jsonify(error="Name must be between 2 and 100 characters"), 400
    if not email or not validate_email(email):
        return jsonify(error="Invalid email address"), 400
    if len(password) > 256:
        return jsonify(error="Password must be no longer than 256 characters"), 400
    is_valid, error_msg = validate_password(password)
    if not is_valid:
        return jsonify(error=error_msg), 400

    password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    try:
        user_id = user_repo.create(name, email, password_hash)
    except sqlite3.IntegrityError:
        # The unique index is authoritative when two signups race.
        return jsonify(error="An account with this email already exists"), 400

    session_id = create_session(session_repo, user_id, remember=False)
    session.clear()
    session["user_id"] = user_id
    session["session_id"] = session_id
    session["user_name"] = name
    session["user_email"] = email
    return jsonify(
        message="Account created successfully",
        redirect="/",
        user={"id": user_id, "name": name, "email": email},
    ), 200


@auth_bp.route("/login", methods=["POST"])
def login():
    _, session_repo = _repositories()
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify(error="Invalid request data"), 400

    email = data.get("email", "")
    password = data.get("password", "")
    remember = data.get("remember", False)
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password must be text values"), 400
    email = email.strip().lower()
    if len(email) > 254:
        return jsonify(error="Invalid email or password"), 401
    if not email or not password or len(password) > 256:
        return jsonify(error="Email and password are required"), 400
    if not isinstance(remember, bool):
        return jsonify(error="Remember me must be true or false"), 400

    with connect(_config()) as connection:
        user = connection.execute(
            "SELECT id, name, email, password_hash, is_active FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if not user or not user["is_active"] or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Invalid email or password"), 401
        connection.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), user["id"]),
        )
        connection.commit()

    session_id = create_session(session_repo, int(user["id"]), remember=remember)
    session.clear()
    session["user_id"] = int(user["id"])
    session["session_id"] = session_id
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]
    session.permanent = remember
    session_repo.delete_expired()
    return jsonify(
        message="Login successful",
        redirect="/",
        user={"id": int(user["id"]), "name": user["name"], "email": user["email"]},
    ), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    _, session_repo = _repositories()
    session_id = session.get("session_id")
    if session_id:
        session_repo.delete(session_id)
    session.clear()
    return jsonify(message="Logged out successfully"), 200


@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    _, session_repo = _repositories()
    user_id = session.get("user_id")
    session_id = session.get("session_id")
    if not user_id or not session_id:
        return jsonify(error="Not authenticated"), 401
    row = session_repo.find_valid(session_id, user_id)
    if not row or not row["is_active"] or row["expires_at"] <= datetime.now(timezone.utc).isoformat():
        session.clear()
        return jsonify(error="Not authenticated"), 401
    user = UserRepository(_config()).find_by_id(user_id)
    if not user:
        session.clear()
        return jsonify(error="User not found"), 401
    return jsonify(user=dict(user)), 200


@auth_bp.route("/check", methods=["GET"])
def check_auth():
    _, session_repo = _repositories()
    user_id = session.get("user_id")
    session_id = session.get("session_id")
    if not user_id or not session_id:
        session.clear()
        return jsonify(authenticated=False), 200
    row = session_repo.find_valid(session_id, user_id)
    authenticated = bool(
        row and row["is_active"] and row["expires_at"] > datetime.now(timezone.utc).isoformat()
    )
    if not authenticated:
        session.clear()
    return jsonify(authenticated=authenticated), 200
