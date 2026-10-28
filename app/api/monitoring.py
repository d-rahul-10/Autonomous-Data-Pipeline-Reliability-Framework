"""Monitoring routes: health, status, history, logs, Airflow, and pages."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, session

from app.exceptions import ForbiddenError, UnauthorizedError

monitoring_bp = Blueprint("monitoring", __name__, url_prefix="")


def _config():
    return current_app.config["APP_CONFIG"]


def _session_valid() -> bool:
    user_id = session.get("user_id")
    session_id = session.get("session_id")
    if not user_id or not session_id:
        return False
    config = _config()
    from app.db import connect
    try:
        with connect(config) as db:
            row = db.execute(
                "SELECT users.is_active, sessions.expires_at "
                "FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.id = ? AND sessions.user_id = ?",
                (session_id, user_id),
            ).fetchone()
    except Exception:  # noqa: BLE001 - auth boundary
        current_app.logger.exception("could not validate dashboard session")
        return False
    return bool(
        row and row["is_active"] and row["expires_at"] > datetime.now(timezone.utc).isoformat()
    )


def _csrf_valid() -> bool:
    import secrets

    submitted = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(expected) and bool(submitted) and secrets.compare_digest(submitted, expected)


@monitoring_bp.get("/healthz")
def healthcheck():
    config = _config()
    from app.db import connect
    try:
        with connect(config) as db:
            db.execute("SELECT 1").fetchone()
    except Exception:  # noqa: BLE001 - health boundary
        current_app.logger.exception("health check failed: state database is unavailable")
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok"), 200


@monitoring_bp.get("/")
def index():
    if "user_id" not in session:
        return redirect("/auth")
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@monitoring_bp.get("/auth")
def auth_page():
    if "user_id" in session:
        return redirect("/")
    return render_template("auth.html")


@monitoring_bp.get("/login")
def login_page():
    if "user_id" in session:
        return redirect("/")
    return redirect("/auth#login")


@monitoring_bp.get("/signup")
def signup_page():
    if "user_id" in session:
        return redirect("/")
    return redirect("/auth#signup")


@monitoring_bp.get("/api/status")
def status():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    history = current_app.config["ANALYSIS_HISTORY"]
    latest = history[0] if history else None
    scheduler = current_app.config["SCHEDULER_SERVICE"]
    return jsonify(
        ready=True,
        latest_analysis=latest,
        schedule=scheduler.get_state(),
    )


@monitoring_bp.get("/api/history")
def history():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    history_repo = current_app.config["HISTORY_REPOSITORY"]
    import json

    items = []
    for row in history_repo.recent(limit=_config().analysis_history_limit):
        item = json.loads(row["payload"])
        items.append({
            "generated_at": item["generated_at"],
            "source": item["source"],
            "rows_raw": item["rows_raw"],
            "rows_clean": item["rows_clean"],
            "flagged": item["failures"]["total_flagged"],
            "reliability": round(
                100
                * (1 - item["failures"]["total_flagged"] / max(1, item["failures"]["records"])),
                1,
            ),
            "report_file": item.get("report_file"),
        })
    return jsonify(history=items)


@monitoring_bp.get("/api/logs")
def logs():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        return jsonify(error="Log limit must be a whole number."), 400
    config = _config()
    path = Path(config.log_file)
    if not path.exists():
        return jsonify(logs=[])
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        lines = deque(log_file, maxlen=limit)
    return jsonify(logs=list(lines))


@monitoring_bp.get("/api/monitor")
def monitor():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    history = current_app.config["ANALYSIS_HISTORY"]
    recent_runs = [
        {
            "generated_at": item["generated_at"],
            "source": item["source"],
            "rows_clean": item["rows_clean"],
            "flagged": item["failures"]["total_flagged"],
        }
        for item in history
    ]
    return jsonify(
        recovery=current_app.config.get("LATEST_RECOVERY"),
        history=recent_runs,
    )


@monitoring_bp.get("/api/airflow")
def airflow_status():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    airflow_recovery = current_app.config["AIRFLOW_RECOVERY"]
    data = airflow_recovery.inspect()
    settings = current_app.config["AIRFLOW_SETTINGS"]
    if not settings.configured:
        return jsonify(data)
    if data.get("error"):
        return jsonify(data), 502
    return jsonify(data)


@monitoring_bp.post("/api/airflow/retry")
def airflow_retry():
    if not _session_valid():
        return jsonify(error="Authentication required. Please sign in."), 401
    config = _config()
    airflow_recovery = current_app.config["AIRFLOW_RECOVERY"]
    settings = current_app.config["AIRFLOW_SETTINGS"]
    if not settings.ready_for_automation:
        return jsonify(error="Airflow automatic recovery is not fully configured."), 409
    events = airflow_recovery.recover_once()
    return jsonify(requested=events, events=airflow_recovery.events())
