"""Database connection management and schema initialization.

Provides thread-safe, context-managed SQLite connections with sane WAL-mode
defaults and a single source of truth for the application schema.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import AppConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT,
    is_active INTEGER DEFAULT 1,
    email_verified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS oauth_accounts (
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_user_id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_history (
    generated_at TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth_accounts_user_id ON oauth_accounts (user_id);
CREATE INDEX IF NOT EXISTS idx_analysis_history_generated_at ON analysis_history (generated_at DESC);
"""


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that also closes when used as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(config: AppConfig) -> sqlite3.Connection:
    """Open a configured SQLite connection to the state database."""
    path = config.state_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(path), timeout=30, isolation_level=None, factory=_ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA cache_size = -32768")
    return connection


@contextmanager
def transaction(config: AppConfig):
    """Yield a connection inside an explicit, rollback-safe write transaction."""
    connection = connect(config)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(config: AppConfig) -> None:
    """Create all application tables and indexes if they do not exist."""
    connection = connect(config)
    try:
        # Set journal mode once during initialization, rather than on every
        # request connection where it can contend with active readers/writers.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
    finally:
        connection.close()
