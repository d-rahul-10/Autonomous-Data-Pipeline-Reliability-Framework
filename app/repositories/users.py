"""User data access."""
from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.base import BaseRepository
from app.db import connect, transaction

class UserRepository(BaseRepository):
    def create(self, name: str, email: str, password_hash: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with transaction(self.config) as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, password_hash, now),
            )
            return int(cursor.lastrowid)

    def find_by_email(self, email: str):
        with connect(self.config) as connection:
            return connection.execute(
                "SELECT id, name, email, password_hash, is_active FROM users WHERE email = ?",
                (email,),
            ).fetchone()

    def find_by_id(self, user_id: int):
        with connect(self.config) as connection:
            return connection.execute(
                "SELECT id, name, email, created_at, last_login, is_active, email_verified "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    def find_or_create_oauth_user(self, provider: str, provider_user_id: str,
                                  name: str, email: str, password_hash: str) -> int:
        """Link a verified provider identity to an existing or new local user."""
        now = datetime.now(timezone.utc).isoformat()
        with transaction(self.config) as connection:
            linked = connection.execute(
                "SELECT user_id FROM oauth_accounts WHERE provider = ? AND provider_user_id = ?",
                (provider, provider_user_id),
            ).fetchone()
            if linked:
                return int(linked["user_id"])

            existing = connection.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if existing:
                user_id = int(existing["id"])
            else:
                cursor = connection.execute(
                    "INSERT INTO users (name, email, password_hash, created_at, email_verified) VALUES (?, ?, ?, ?, 1)",
                    (name, email, password_hash, now),
                )
                user_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO oauth_accounts (provider, provider_user_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                (provider, provider_user_id, user_id, now),
            )
            return user_id

    def update_last_login(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with transaction(self.config) as connection:
            connection.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (now, user_id),
            )

    def set_active(self, user_id: int, is_active: bool) -> None:
        with transaction(self.config) as connection:
            connection.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, user_id),
            )
