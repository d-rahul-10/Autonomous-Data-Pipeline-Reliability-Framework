"""Schedule state data access."""
from __future__ import annotations

from app.db import connect, transaction
from app.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository):
    KEY = "schedule"

    def get(self):
        with connect(self.config) as connection:
            return connection.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (self.KEY,),
            ).fetchone()

    def save(self, value: str) -> None:
        with transaction(self.config) as connection:
            connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (self.KEY, value),
            )
