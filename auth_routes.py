"""Authentication routes for PipelineIQ.

Provides user registration, login, and session management.
"""
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Database path
DB_PATH = Path("pipeline_state.sqlite3")


@contextmanager
def get_db_connection():
    """Yield a configured database connection and always close it."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_auth_db():
    """Initialize authentication tables."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT,
                is_active INTEGER DEFAULT 1,
                email_verified INTEGER DEFAULT 0
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)
        """)
        
        conn.commit()


def require_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            valid_session = _session_is_valid()
        except sqlite3.Error:
            return jsonify(error="Authentication service is temporarily unavailable"), 503
        if not valid_session:
            session.clear()
            return jsonify(error="Authentication required"), 401
        return f(*args, **kwargs)
    return decorated_function


def _session_is_valid() -> bool:
    user_id = session.get('user_id')
    session_id = session.get('session_id')
    if not user_id or not session_id:
        return False
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT users.is_active, sessions.expires_at "
            "FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.id = ? AND sessions.user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return bool(row and row['is_active'] and row['expires_at'] > datetime.now(timezone.utc).isoformat())


def validate_email(email: str) -> bool:
    """Validate email format."""
    import re
    pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return re.match(pattern, email) is not None


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password strength.
    
    Returns:
        (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    
    return True, ""


def create_session(user_id: int, remember: bool = False) -> str:
    """Create a new session for the user.
    
    Args:
        user_id: User ID
        remember: If True, session lasts 30 days; otherwise 24 hours
    
    Returns:
        Session ID
    """
    session_id = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    
    if remember:
        expires_at = created_at + timedelta(days=30)
    else:
        expires_at = created_at + timedelta(hours=24)
    
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')[:500]
    
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO sessions (id, user_id, created_at, expires_at, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, user_id, created_at.isoformat(), expires_at.isoformat(), 
              ip_address, user_agent))
        conn.commit()
    
    return session_id


def cleanup_expired_sessions():
    """Remove expired sessions from database."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.commit()


@auth_bp.route('/signup', methods=['POST'])
def signup():
    """Register a new user.
    
    Request JSON:
        {
            "name": "John Doe",
            "email": "john@example.com",
            "password": "SecurePass123"
        }
    
    Response:
        200: { "message": "Account created", "redirect": "/" }
        400: { "error": "Error message" }
    """
    data = request.get_json()
    
    if not isinstance(data, dict):
        return jsonify(error="Invalid request data"), 400
    
    name = data.get('name', '')
    email = data.get('email', '')
    password = data.get('password', '')
    if not all(isinstance(value, str) for value in (name, email, password)):
        return jsonify(error="Name, email, and password must be text values"), 400
    name = name.strip()
    email = email.strip().lower()
    if len(email) > 254:
        return jsonify(error="Email address is too long"), 400
    
    # Validation
    if not name or len(name) < 2 or len(name) > 100:
        return jsonify(error="Name must be between 2 and 100 characters"), 400
    
    if not email or not validate_email(email):
        return jsonify(error="Invalid email address"), 400

    if len(password) > 256:
        return jsonify(error="Password must be no longer than 256 characters"), 400
    
    is_valid, error_msg = validate_password(password)
    if not is_valid:
        return jsonify(error=error_msg), 400
    
    # Check if user already exists
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        
        if existing:
            return jsonify(error="An account with this email already exists"), 400
        
        # Create user
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        created_at = datetime.now(timezone.utc).isoformat()
        
        cursor = conn.execute("""
            INSERT INTO users (name, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
        """, (name, email, password_hash, created_at))
        
        user_id = cursor.lastrowid
        conn.commit()
    
    # Create session
    session_id = create_session(user_id, remember=False)
    session.clear()
    session['user_id'] = user_id
    session['session_id'] = session_id
    session['user_name'] = name
    session['user_email'] = email
    
    return jsonify(
        message="Account created successfully",
        redirect="/",
        user={"id": user_id, "name": name, "email": email}
    ), 200


@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate a user.
    
    Request JSON:
        {
            "email": "john@example.com",
            "password": "SecurePass123",
            "remember": false
        }
    
    Response:
        200: { "message": "Login successful", "redirect": "/" }
        401: { "error": "Invalid credentials" }
    """
    data = request.get_json()
    
    if not isinstance(data, dict):
        return jsonify(error="Invalid request data"), 400
    
    email = data.get('email', '')
    password = data.get('password', '')
    remember = data.get('remember', False)
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password must be text values"), 400
    email = email.strip().lower()
    if len(email) > 254:
        return jsonify(error="Invalid email or password"), 401
    
    if not email or not password or len(password) > 256:
        return jsonify(error="Email and password are required"), 400
    if not isinstance(remember, bool):
        return jsonify(error="Remember me must be true or false"), 400
    
    # Find user
    with get_db_connection() as conn:
        user = conn.execute("""
            SELECT id, name, email, password_hash, is_active
            FROM users WHERE email = ?
        """, (email,)).fetchone()
        
        if not user or not user['is_active'] or not check_password_hash(user['password_hash'], password):
            return jsonify(error="Invalid email or password"), 401
        
        # Update last login
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), user['id'])
        )
        conn.commit()
    
    # Create session
    session_id = create_session(user['id'], remember=remember)
    session.clear()
    session['user_id'] = user['id']
    session['session_id'] = session_id
    session['user_name'] = user['name']
    session['user_email'] = user['email']
    session.permanent = remember
    
    # Cleanup old sessions
    cleanup_expired_sessions()
    
    return jsonify(
        message="Login successful",
        redirect="/",
        user={"id": user['id'], "name": user['name'], "email": user['email']}
    ), 200


@auth_bp.route('/logout', methods=['POST'])
@require_auth
def logout():
    """Log out the current user.
    
    Response:
        200: { "message": "Logged out successfully" }
    """
    session_id = session.get('session_id')
    
    if session_id:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
    
    session.clear()
    
    return jsonify(message="Logged out successfully"), 200


@auth_bp.route('/me', methods=['GET'])
@require_auth
def get_current_user():
    """Get current authenticated user.
    
    Response:
        200: { "user": { "id": 1, "name": "John", "email": "john@example.com" } }
        401: { "error": "Not authenticated" }
    """
    user_id = session.get('user_id')
    
    with get_db_connection() as conn:
        user = conn.execute("""
            SELECT id, name, email, created_at, last_login, email_verified
            FROM users WHERE id = ? AND is_active = 1
        """, (user_id,)).fetchone()
        
        if not user:
            session.clear()
            return jsonify(error="User not found"), 401
    
    return jsonify(user=dict(user)), 200


@auth_bp.route('/check', methods=['GET'])
def check_auth():
    """Check if user is authenticated.
    
    Response:
        200: { "authenticated": true/false }
    """
    try:
        authenticated = _session_is_valid()
    except sqlite3.Error:
        return jsonify(error="Authentication service is temporarily unavailable"), 503
    if not authenticated:
        session.clear()
    return jsonify(authenticated=authenticated), 200


# Initialize database when module is imported
init_auth_db()
