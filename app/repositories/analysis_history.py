"""Analysis history data access."""
from __future__ import annotations

from app.db import connect, transaction
from app.repositories.base import BaseRepository


class AnalysisHistoryRepository(BaseRepository):
    LIMIT = 25

    def save(self, generated_at: str, payload: str) -> None:
        with transaction(self.config) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO analysis_history (generated_at, payload) VALUES (?, ?)
                """,
                (generated_at, payload),
            )
            connection.execute(
                """
                DELETE FROM analysis_history
                WHERE generated_at NOT IN (
                    SELECT generated_at FROM analysis_history
                    ORDER BY generated_at DESC LIMIT ?
                )
                """,
                (self.LIMIT,),
            )

    def recent(self, limit: int | None = None):
        limit = limit or self.LIMIT
        with connect(self.config) as connection:
            return connection.execute(
                "SELECT payload FROM analysis_history ORDER BY generated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
