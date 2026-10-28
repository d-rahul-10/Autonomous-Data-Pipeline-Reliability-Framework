"""Session data access."""
from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.base import BaseRepository
from app.db import transaction, connect


class SessionRepository(BaseRepository):
    def create(self, user_id: int, session_id: str, expires_at: str,
               ip_address: str | None = None, user_agent: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with transaction(self.config) as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, user_id, created_at, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, now, expires_at, ip_address, user_agent),
            )

    def find_valid(self, session_id: str, user_id: int):
        """Return the joined user/session row if active and not expired."""
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.config) as connection:
            return connection.execute(
                """
                SELECT users.is_active, sessions.expires_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.id = ? AND sessions.user_id = ?
                """,
                (session_id, user_id),
            ).fetchone()

    def delete(self, session_id: str) -> None:
        with transaction(self.config) as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def delete_expired(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with transaction(self.config) as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
