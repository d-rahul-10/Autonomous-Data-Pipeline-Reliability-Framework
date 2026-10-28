"""Centralized, validated application configuration.

All runtime settings are sourced from environment variables with sensible
defaults. Production mode enforces mandatory secrets and secure cookie flags.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "t"}


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration."""

    env: str
    production: bool
    testing: bool
    debug: bool
    secret_key: str | None
    host: str
    port: int
    state_db_path: Path
    schedule_data_dir: Path
    report_dir: Path
    log_file: str
    model_path: str
    max_content_length: int
    session_cookie_secure: bool
    session_cookie_samesite: str
    permanent_session_lifetime: int
    analysis_history_limit: int
    min_clean_rows: int
    min_sample_rows: int
    max_sample_rows: int
    min_interval_seconds: int
    max_interval_seconds: int
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    oauth_redirect_base_url: str = ""

    @classmethod
    def from_env(cls) -> "AppConfig":
        env = os.environ.get("APP_ENV", "development").strip().lower()
        production = env == "production"
        testing = _env_bool("TESTING", False)
        debug = _env_bool("DEBUG", not production) and not testing

        secret_key = os.environ.get("SECRET_KEY")
        if production and (not secret_key or len(secret_key) < 32):
            raise RuntimeError("Production requires SECRET_KEY with at least 32 characters.")
        if not secret_key:
            secret_key = "dev-secret-key-do-not-use-in-production"

        state_db_path = Path(os.environ.get("STATE_DB_PATH", "pipeline_state.sqlite3"))
        schedule_data_dir = Path(os.environ.get("SCHEDULE_DATA_DIR", "data/incoming"))
        report_dir = Path(os.environ.get("REPORT_DIR", "reports"))

        return cls(
            env=env,
            production=production,
            testing=testing,
            debug=debug,
            secret_key=secret_key,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=_env_int("PORT", 5000, minimum=1, maximum=65535),
            state_db_path=state_db_path,
            schedule_data_dir=schedule_data_dir,
            report_dir=report_dir,
            log_file=os.environ.get("LOG_FILE", "pipeline.log"),
            model_path=os.environ.get("MODEL_PATH", "bottleneck_model.joblib"),
            max_content_length=_env_int("MAX_CONTENT_LENGTH", 500 * 1024 * 1024, minimum=1),
            session_cookie_secure=production,
            session_cookie_samesite="Lax",
            permanent_session_lifetime=_env_int("PERMANENT_SESSION_LIFETIME", 60 * 60 * 24 * 30, minimum=60),
            analysis_history_limit=_env_int("ANALYSIS_HISTORY_LIMIT", 25, minimum=1, maximum=1000),
            min_clean_rows=_env_int("MIN_CLEAN_ROWS", 200, minimum=1),
            min_sample_rows=_env_int("MIN_SAMPLE_ROWS", 1000, minimum=1),
            max_sample_rows=_env_int("MAX_SAMPLE_ROWS", 500_000, minimum=1000),
            min_interval_seconds=_env_int("MIN_INTERVAL_SECONDS", 15, minimum=1),
            max_interval_seconds=_env_int("MAX_INTERVAL_SECONDS", 604800, minimum=1),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", "").strip(),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", "").strip(),
            oauth_redirect_base_url=os.environ.get("OAUTH_REDIRECT_BASE_URL", "").strip().rstrip("/"),
        )

    def to_flask_config(self) -> dict:
        return {
            "ENV": self.env,
            "DEBUG": self.debug,
            "TESTING": self.testing,
            "SECRET_KEY": self.secret_key,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "PERMANENT_SESSION_LIFETIME": self.permanent_session_lifetime,
            "MAX_CONTENT_LENGTH": self.max_content_length,
            "STATE_DB_PATH": self.state_db_path,
            "SCHEDULE_DATA_DIR": self.schedule_data_dir,
            "REPORT_DIR": self.report_dir,
            "LOG_FILE": self.log_file,
            "MODEL_PATH": self.model_path,
        }
