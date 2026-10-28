"""API blueprint registration."""
from __future__ import annotations

from flask import Flask

from app.api import analysis, auth, monitoring, reports, schedule


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(analysis.analysis_bp)
    app.register_blueprint(schedule.schedule_bp)
    app.register_blueprint(reports.reports_bp)
    app.register_blueprint(monitoring.monitoring_bp)
