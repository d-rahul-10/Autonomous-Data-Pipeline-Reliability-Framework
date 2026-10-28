"""Application factory and WSGI entry point assembly.

Creates the Flask application with clean layering:
  config      -> immutable, validated settings
  db          -> connection management + schema
  repositories-> data access (parameterized queries)
  services    -> business logic (analysis, scheduling, jobs)
  api         -> route blueprints (thin HTTP layer)
  middleware  -> auth, CSRF, security headers, error handlers

Exposes `app` (the Flask instance) and `json_default` for backwards
compatibility with existing tests and WSGI entry points.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify

from app.api import register_blueprints
from app.config import AppConfig, BASE_DIR
from app.db import init_db
from app.exceptions import PipelineError
from app.middleware import init_middleware
from app.repositories.analysis_history import AnalysisHistoryRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.services.analysis import AnalysisService, json_default
from app.services.jobs import AnalysisJobManager
from app.services.scheduler import SchedulerService
from airflow_integration import AirflowRecoveryService, AirflowSettings

__all__ = ["create_app", "app", "json_default", "_json_default", "get_config"]


def _load_analysis_history(app: Flask, history_repository: AnalysisHistoryRepository, limit: int) -> list:
    history = []
    for row in history_repository.recent(limit=limit):
        try:
            history.append(json.loads(row["payload"]))
        except (json.JSONDecodeError, TypeError):
            app.logger.exception("skipping corrupt analysis history row")
    return history


def _start_airflow_recovery_worker(app: Flask, settings: AirflowSettings, recovery: AirflowRecoveryService) -> None:
    if not settings.ready_for_automation:
        return
    stop = app.config["AIRFLOW_WORKER_STOP"]
    thread = app.config.get("AIRFLOW_WORKER_THREAD")
    if thread is None or not thread.is_alive():
        stop.clear()

        def loop():
            while not stop.is_set():
                try:
                    events = recovery.recover_once()
                    for event in events:
                        app.logger.warning(
                            "Airflow recovery requested for dag=%s task=%s run=%s",
                            event.get("dag_id"), event.get("task_id"), event.get("dag_run_id"),
                        )
                except Exception:  # noqa: BLE001 - background worker boundary
                    app.logger.exception("Airflow recovery poll failed")
                stop.wait(settings.poll_seconds)

        app.config["AIRFLOW_WORKER_THREAD"] = threading.Thread(
            target=loop, name="airflow-recovery", daemon=True
        )
        app.config["AIRFLOW_WORKER_THREAD"].start()


def create_app(config: AppConfig | None = None) -> Flask:
    """Build and configure the Flask application."""
    if config is None:
        config = AppConfig.from_env()

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
        static_url_path="/static",
    )
    app.config.from_mapping(config.to_flask_config())
    app.config["APP_CONFIG"] = config
    app.config["ANALYSIS_LOCK"] = threading.Lock()
    app.config["LATEST_RECOVERY"] = None
    app.config["AIRFLOW_WORKER_STOP"] = threading.Event()
    app.config["AIRFLOW_WORKER_THREAD"] = None

    # ---- database + schema ----
    init_db(config)

    # ---- repositories ----
    user_repository = UserRepository(config)
    session_repository = SessionRepository(config)
    schedule_repository = ScheduleRepository(config)
    history_repository = AnalysisHistoryRepository(config)

    # ---- in-memory analysis history (bounded cache) ----
    analysis_history = _load_analysis_history(
        app, history_repository, config.analysis_history_limit
    )

    def _history_sink(payload: dict) -> None:
        analysis_history.insert(0, payload)
        del analysis_history[config.analysis_history_limit:]

    # ---- services ----
    analysis_service = AnalysisService(
        history_repository=history_repository,
        min_clean_rows=config.min_clean_rows,
        history_sink=_history_sink,
    )
    job_manager = AnalysisJobManager(
        analysis_service, max_age_hours=24, analysis_lock=app.config["ANALYSIS_LOCK"]
    )
    scheduler_service = SchedulerService(
        config=config,
        analysis_service=analysis_service,
        schedule_repository=schedule_repository,
        data_dir=config.schedule_data_dir,
        analysis_lock=app.config["ANALYSIS_LOCK"],
    )

    app.config["ANALYSIS_SERVICE"] = analysis_service
    app.config["JOB_MANAGER"] = job_manager
    app.config["SCHEDULER_SERVICE"] = scheduler_service
    app.config["HISTORY_REPOSITORY"] = history_repository
    app.config["ANALYSIS_HISTORY"] = analysis_history

    # ---- blueprints + middleware ----
    register_blueprints(app)
    init_middleware(app, config)

    # ---- persisted schedule + background workers ----
    scheduler_service.load_persisted()
    settings = AirflowSettings.from_env()
    recovery = AirflowRecoveryService(settings)
    app.config["AIRFLOW_RECOVERY"] = recovery
    app.config["AIRFLOW_SETTINGS"] = settings
    _start_airflow_recovery_worker(app, settings, recovery)

    return app


# Application instance used by `python app.py`, `wsgi:app`, and tests.
app = create_app()


def get_config() -> AppConfig:
    return app.config["APP_CONFIG"]


_json_default = json_default


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
