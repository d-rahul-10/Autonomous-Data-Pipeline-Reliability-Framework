"""
Authentication module for PipelineIQ.
Handles user registration, login, JWT tokens, and session management.
"""

import os
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import bcrypt
import jwt
from flask import request, jsonify, g, current_app


class AuthError(Exception):
    """Custom exception for authentication errors."""
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class User:
    """User model for authentication."""

    def __init__(self, id: int, email: str, password_hash: str, created_at: str,
                 last_login: Optional[str] = None, is_active: bool = True):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.created_at = created_at
        self.last_login = last_login
        self.is_active = is_active

    @staticmethod
    def from_row(row: Tuple) -> 'User':
        return User(
            id=row[0],
            email=row[1],
            password_hash=row[2],
            created_at=row[3],
            last_login=row[4],
            is_active=bool(row[5]) if len(row) > 5 else True
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'email': self.email,
            'created_at': self.created_at,
            'last_login': self.last_login,
            'is_active': self.is_active
        }

    def verify_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))


class AuthManager:
    """Manages authentication operations."""

    def __init__(self, db_path: Path, jwt_secret: Optional[str] = None,
                 jwt_algorithm: str = 'HS256', jwt_expiry_hours: int = 24):
        self.db_path = db_path
        self.jwt_secret = jwt_secret or secrets.token_urlsafe(32)
        self.jwt_algorithm = jwt_algorithm
        self.jwt_expiry_hours = jwt_expiry_hours
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize the users table."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
            """)

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def create_user(self, email: str, password: str) -> User:
        """Create a new user."""
        email = email.lower().strip()
        if not email or '@' not in email:
            raise AuthError('Invalid email address', 400)
        if len(password) < 8:
            raise AuthError('Password must be at least 8 characters', 400)

        password_hash = self.hash_password(password)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, password_hash, created_at)
                )
                user_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                raise AuthError('Email already registered', 409)

        return User(user_id, email, password_hash, created_at)

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        email = email.lower().strip()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id, email, password_hash, created_at, last_login, is_active FROM users WHERE email = ?",
                (email,)
            ).fetchone()
        return User.from_row(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id, email, password_hash, created_at, last_login, is_active FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
        return User.from_row(row) if row else None

    def authenticate(self, email: str, password: str) -> User:
        """Authenticate a user with email and password."""
        user = self.get_user_by_email(email)
        if not user:
            raise AuthError('Invalid credentials', 401)
        if not user.is_active:
            raise AuthError('Account deactivated', 403)
        if not user.verify_password(password):
            raise AuthError('Invalid credentials', 401)

        # Update last login
        last_login = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (last_login, user.id))
        user.last_login = last_login
        return user

    def generate_token(self, user: User) -> str:
        """Generate a JWT token for the user."""
        payload = {
            'sub': str(user.id),
            'email': user.email,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(hours=self.jwt_expiry_hours)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthError('Token expired', 401)
        except jwt.InvalidTokenError:
            raise AuthError('Invalid token', 401)

    def get_user_from_token(self, token: str) -> User:
        """Get user from JWT token."""
        payload = self.verify_token(token)
        user = self.get_user_by_id(payload['sub'])
        if not user or not user.is_active:
            raise AuthError('User not found or deactivated', 401)
        return user


def require_auth(f):
    """Decorator to require authentication for a route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization header required'}), 401

        token = auth_header[7:]  # Remove 'Bearer '
        auth_manager: AuthManager = current_app.config['AUTH_MANAGER']

        try:
            user = auth_manager.get_user_from_token(token)
            g.current_user = user
            g.auth_token = token
        except AuthError as e:
            return jsonify({'error': e.message}), e.status_code

        return f(*args, **kwargs)
    return decorated


def optional_auth(f):
    """Decorator for optional authentication (sets g.current_user if token valid)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            auth_manager: AuthManager = current_app.config['AUTH_MANAGER']
            try:
                user = auth_manager.get_user_from_token(token)
                g.current_user = user
                g.auth_token = token
            except AuthError:
                pass
        return f(*args, **kwargs)
    return decorated