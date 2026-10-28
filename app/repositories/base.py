"""Base data access repository."""
from __future__ import annotations

from app.db import transaction
from app.config import AppConfig


class BaseRepository:
    def __init__(self, config: AppConfig):
        self.config = config
