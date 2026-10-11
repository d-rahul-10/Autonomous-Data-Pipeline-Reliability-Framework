
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import re
import json
import math
import os
import sqlite3
import secrets
from contextlib import contextmanager

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from auth import AuthManager, require_auth
from auth_routes import auth_bp
from bottleneck_predictor import BottleneckPredictor
from csv_input import read_csv_table
from data_quality import DataQualityValidator
from failure_detector import FailureDetector
from pipeline_core import _read_pipeline_csv, build_config
from main import demo_live_pipeline
from reporter import Reporter
from synthetic_data import generate_logs

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024   # 500 MB upload limit
app.config["STATE_DB_PATH"] = Path("pipeline_state.sqlite3")
app.config["SCHEDULE_DATA_DIR"] = Path("data") / "incoming"
app.config["JWT_SECRET"] = os.environ.get("JWT_SECRET", secrets.token_urlsafe(32))

# Initialize authentication manager
auth_manager = AuthManager(
    db_path=app.config["STATE_DB_PATH"],
    jwt_secret=app.config["JWT_SECRET"],
    jwt_expiry_hours=24
)
app.config["AUTH_MANAGER"] = auth_manager

# Register auth blueprint
app.register_blueprint(auth_bp)

_state_lock = threading.RLock()
_analysis_lock = threading.Lock()
_analysis_history = []
_latest_analysis = None
_latest_recovery = None
_schedule = {
    "enabled": False,
    "interval_seconds": 3600,
    "rows": 10000,
    "source_type": "sample",
    "dataset_name": "",
    "next_run": None,
    "last_run": None,
    "last_error": None,
    "runs": 0,
    "running": False,
}
_scheduler_thread = None
_schedule_version = 0

# Async analysis job tracking
_analysis_jobs = {}
_analysis_jobs_lock = threading.Lock()


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


app.json.default = _json_default


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    return jsonify(error="The uploaded file exceeds the 500 MB limit."), 413


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect_state():
    path = Path(app.config["STATE_DB_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA cache_size = -32768")  # 32MB cache
    return connection


@contextmanager
def _state_connection():
    connection = _connect_state()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _persist_schedule_locked():
    with _state_connection() as db:
        db.execute(
            "INSERT INTO app_state (key, value) VALUES ('schedule', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(_schedule),),
        )


def _load_persistent_state():
    global _latest_analysis, _scheduler_thread, _schedule_version
    incoming_dir = Path(app.config["SCHEDULE_DATA_DIR"])
    incoming_dir.mkdir(parents=True, exist_ok=True)
    with _state_connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS analysis_history "
            "(generated_at TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        schedule_row = db.execute("SELECT value FROM app_state WHERE key = 'schedule'").fetchone()
        history_rows = db.execute(
            "SELECT payload FROM analysis_history ORDER BY generated_at DESC LIMIT 25"
        ).fetchall()

    if schedule_row:
        try:
            persisted_schedule = json.loads(schedule_row[0])
            if not isinstance(persisted_schedule, dict):
                raise ValueError("saved scheduler settings must be a JSON object")
            interval = persisted_schedule.get("interval_seconds", _schedule["interval_seconds"])
            rows = persisted_schedule.get("rows", _schedule["rows"])
            enabled = persisted_schedule.get("enabled", _schedule["enabled"])
            source_type = persisted_schedule.get("source_type", _schedule["source_type"])
            dataset_name = persisted_schedule.get("dataset_name", _schedule["dataset_name"])
            next_run = persisted_schedule.get("next_run")
            last_run = persisted_schedule.get("last_run")
            last_error = persisted_schedule.get("last_error")
            runs = persisted_schedule.get("runs", _schedule["runs"])
            if type(enabled) is not bool:
                raise ValueError("saved enabled value must be a boolean")
            if type(interval) is not int or not 15 <= interval <= 604800:
                raise ValueError("saved interval must be between 15 seconds and 7 days")
            if type(rows) is not int or not 1000 <= rows <= 500000:
                raise ValueError("saved sample size must be between 1,000 and 500,000 rows")
            if source_type not in {"sample", "csv"}:
                raise ValueError("saved source_type is invalid")
            if not isinstance(dataset_name, str):
                raise ValueError("saved dataset_name must be a string")
            if next_run is not None and (
                isinstance(next_run, bool) or not isinstance(next_run, (int, float))
                or not math.isfinite(next_run)
            ):
                raise ValueError("saved next_run must be a finite timestamp or null")
            if last_run is not None and not isinstance(last_run, str):
                raise ValueError("saved last_run must be a string or null")
            if last_error is not None and not isinstance(last_error, str):
                raise ValueError("saved last_error must be a string or null")
            if type(runs) is not int or runs < 0:
                raise ValueError("saved runs must be a non-negative integer")
            if source_type == "csv" and (
                not dataset_name or secure_filename(dataset_name) != dataset_name
                or Path(dataset_name).suffix.lower() != ".csv"
            ):
                raise ValueError("saved CSV dataset name is invalid")
            _schedule.update({
                "enabled": enabled,
                "interval_seconds": interval,
                "rows": rows,
                "source_type": source_type,
                "dataset_name": dataset_name if source_type == "csv" else "",
                "next_run": next_run,
                "last_run": last_run,
                "last_error": last_error,
                "runs": runs,
            })
            _schedule_version += 1
        except (TypeError, ValueError, json.JSONDecodeError):
            app.logger.exception("saved scheduler settings are invalid; using safe defaults")
    _schedule["running"] = False
    if _schedule["enabled"] and not _schedule["next_run"]:
        _schedule["next_run"] = datetime.now(timezone.utc).timestamp()
    _analysis_history.extend(json.loads(row[0]) for row in history_rows)
    if _analysis_history:
        _latest_analysis = _analysis_history[0]
    if _schedule["enabled"]:
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop, name="pipeline-scheduler", daemon=True
        )
        _scheduler_thread.start()


def _analyze_dataframe(df, source, cfg):
    """Run the complete analysis once, for uploads, samples, and scheduled runs."""
    global _latest_analysis
    dq_report = DataQualityValidator(cfg).validate(df)
    clean = DataQualityValidator(cfg).clean(df)
    if len(clean) < 200:
        raise ValueError("Too few valid rows after cleaning (need at least 200).")

    fd = FailureDetector(cfg).fit_anomaly(clean)
    detected = fd.detect(clean)
    failures = fd.summarize(detected)

    predictor = BottleneckPredictor(cfg)
    metrics = predictor.train(clean)
    predictor.save()
    metrics.pop("report", None)

    timestamp, duration, task = cfg.col_timestamp, cfg.col_duration, cfg.col_task
    ordered = detected[[timestamp, duration, "failure_detected"]].sort_values(
        timestamp, kind="stable"
    ).reset_index(drop=True)
    chunks = [indices for indices in np.array_split(
        np.arange(len(ordered)), min(80, len(ordered))
    ) if len(indices)]
    timeline = [{
        "t": str(ordered[timestamp].iloc[indices[0]])[:16],
        "avg_duration": round(float(ordered[duration].iloc[indices].mean()), 2),
        "failures": int(ordered["failure_detected"].iloc[indices].sum()),
    } for indices in chunks]

    by_task = (
        detected.groupby(task)
        .agg(runs=("failure_detected", "size"),
             flagged=("failure_detected", "sum"),
             avg_duration=(duration, "mean"))
        .round(2)
        .reset_index()
        .rename(columns={task: "task"})
        .to_dict("records")
    )

    risk = predictor.predict_risk(clean.tail(5000)).nlargest(10, "bottleneck_risk")
    top_risk = [{
        "timestamp": str(getattr(row, timestamp)),
        "task": str(getattr(row, task)),
        "duration": round(float(getattr(row, duration)), 2),
        "risk": round(float(row.bottleneck_risk), 3),
    } for row in risk.itertuples(index=False)]

    performance = {
        "avg_duration": round(float(clean[duration].mean()), 2),
        "p95_duration": round(float(clean[duration].quantile(.95)), 2),
        "max_duration": round(float(clean[duration].max()), 2),
        "avg_cpu": round(float(clean[cfg.col_cpu].mean()), 2),
        "avg_memory": round(float(clean[cfg.col_memory].mean()), 2),
        "avg_io": round(float(clean[cfg.col_io].mean()), 2),
        "avg_latency": round(float(clean[cfg.col_latency].mean()), 2),
        "task_count": int(clean[task].nunique()),
    }

    payload = {
        "source": source,
        "generated_at": _iso_now(),
        "rows_raw": len(df),
        "rows_clean": len(clean),
        "data_quality": dq_report,
        "failures": failures,
        "model": metrics,
        "performance": performance,
        "timeline": timeline,
        "by_task": by_task,
        "top_risk": top_risk,
    }
    json_report, _ = Reporter(cfg).write({"source": source, "analysis": payload})
    payload["report_file"] = Path(json_report).name

    with _state_lock:
        _latest_analysis = payload
        _analysis_history.insert(0, payload)
        del _analysis_history[25:]
        with _state_connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO analysis_history (generated_at, payload) VALUES (?, ?)",
                (payload["generated_at"], json.dumps(payload, default=_json_default)),
            )
            db.execute(
                "DELETE FROM analysis_history WHERE generated_at NOT IN "
                "(SELECT generated_at FROM analysis_history ORDER BY generated_at DESC LIMIT 25)"
            )
    return payload


def _run_analysis_async(job_id: str, df, source: str, cfg):
    """Background thread target for async analysis."""
    with _analysis_jobs_lock:
        _analysis_jobs[job_id] = {
            "status": "running",
            "progress": 0,
            "stage": "starting",
            "result": None,
            "error": None,
            "started_at": _iso_now(),
        }

    def update_progress(stage: str, progress: int):
        with _analysis_jobs_lock:
            if job_id in _analysis_jobs:
                _analysis_jobs[job_id]["stage"] = stage
                _analysis_jobs[job_id]["progress"] = progress

    try:
        update_progress("validating", 10)
        dq_report = DataQualityValidator(cfg).validate(df)

        update_progress("cleaning", 20)
        clean = DataQualityValidator(cfg).clean(df)
        if len(clean) < 200:
            raise ValueError("Too few valid rows after cleaning (need at least 200).")

        update_progress("detecting_failures", 40)
        fd = FailureDetector(cfg).fit_anomaly(clean)
        detected = fd.detect(clean)
        failures = fd.summarize(detected)

        update_progress("training_model", 60)
        predictor = BottleneckPredictor(cfg)
        metrics = predictor.train(clean)
        predictor.save()
        metrics.pop("report", None)

        update_progress("computing_metrics", 80)
        timestamp, duration, task = cfg.col_timestamp, cfg.col_duration, cfg.col_task
        ordered = detected[[timestamp, duration, "failure_detected"]].sort_values(
            timestamp, kind="stable"
        ).reset_index(drop=True)
        chunks = [indices for indices in np.array_split(
            np.arange(len(ordered)), min(80, len(ordered))
        ) if len(indices)]
        timeline = [{
            "t": str(ordered[timestamp].iloc[indices[0]])[:16],
            "avg_duration": round(float(ordered[duration].iloc[indices].mean()), 2),
            "failures": int(ordered["failure_detected"].iloc[indices].sum()),
        } for indices in chunks]

        by_task = (
            detected.groupby(task)
            .agg(runs=("failure_detected", "size"),
                 flagged=("failure_detected", "sum"),
                 avg_duration=(duration, "mean"))
            .round(2)
            .reset_index()
            .rename(columns={task: "task"})
            .to_dict("records")
        )

        risk = predictor.predict_risk(clean.tail(5000)).nlargest(10, "bottleneck_risk")
        top_risk = [{
            "timestamp": str(getattr(row, timestamp)),
            "task": str(getattr(row, task)),
            "duration": round(float(getattr(row, duration)), 2),
            "risk": round(float(row.bottleneck_risk), 3),
        } for row in risk.itertuples(index=False)]

        performance = {
            "avg_duration": round(float(clean[duration].mean()), 2),
            "p95_duration": round(float(clean[duration].quantile(.95)), 2),
            "max_duration": round(float(clean[duration].max()), 2),
            "avg_cpu": round(float(clean[cfg.col_cpu].mean()), 2),
            "avg_memory": round(float(clean[cfg.col_memory].mean()), 2),
            "avg_io": round(float(clean[cfg.col_io].mean()), 2),
            "avg_latency": round(float(clean[cfg.col_latency].mean()), 2),
            "task_count": int(clean[task].nunique()),
        }

        payload = {
            "source": source,
            "generated_at": _iso_now(),
            "rows_raw": len(df),
            "rows_clean": len(clean),
            "data_quality": dq_report,
            "failures": failures,
            "model": metrics,
            "performance": performance,
            "timeline": timeline,
            "by_task": by_task,
            "top_risk": top_risk,
        }
        json_report, _ = Reporter(cfg).write({"source": source, "analysis": payload})
        payload["report_file"] = Path(json_report).name

        update_progress("finalizing", 95)

        with _state_lock:
            _latest_analysis = payload
            _analysis_history.insert(0, payload)
            del _analysis_history[25:]
            with _state_connection() as db:
                db.execute(
                    "INSERT OR REPLACE INTO analysis_history (generated_at, payload) VALUES (?, ?)",
                    (payload["generated_at"], json.dumps(payload, default=_json_default)),
                )
                db.execute(
                    "DELETE FROM analysis_history WHERE generated_at NOT IN "
                    "(SELECT generated_at FROM analysis_history ORDER BY generated_at DESC LIMIT 25)"
                )

        with _analysis_jobs_lock:
            _analysis_jobs[job_id].update({
                "status": "completed",
                "progress": 100,
                "stage": "done",
                "result": payload,
                "completed_at": _iso_now(),
            })

    except Exception as exc:
        app.logger.exception("async analysis failed")
        with _analysis_jobs_lock:
            _analysis_jobs[job_id].update({
                "status": "failed",
                "progress": 100,
                "stage": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "completed_at": _iso_now(),
            })


def _cleanup_old_jobs(max_age_hours: int = 24):
    """Remove completed/failed jobs older than max_age_hours."""
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    with _analysis_jobs_lock:
        to_remove = [
            jid for jid, job in _analysis_jobs.items()
            if job["status"] in ("completed", "failed")
            and datetime.fromisoformat(job.get("completed_at", "1970-01-01")).timestamp() < cutoff
        ]
        for jid in to_remove:
            del _analysis_jobs[jid]


def _scheduler_loop():
    global _scheduler_thread
    wait_event = threading.Event()
    while True:
        due = False
        with _state_lock:
            if not _schedule["enabled"]:
                if _scheduler_thread is threading.current_thread():
                    _scheduler_thread = None
                return
            now = datetime.now(timezone.utc)
            next_run = _schedule["next_run"]
            if _schedule["enabled"] and next_run and now.timestamp() >= next_run:
                _schedule["next_run"] = now.timestamp() + _schedule["interval_seconds"]
                _schedule["running"] = True
                due = True
                schedule_version = _schedule_version
                rows = _schedule["rows"]
                source_type = _schedule["source_type"]
                dataset_name = _schedule["dataset_name"]

        if due:
            try:
                with _analysis_lock:
                    with _state_lock:
                        should_run = (
                            _schedule["enabled"] and schedule_version == _schedule_version
                        )
                    if not should_run:
                        continue
                    cfg = build_config()
                    if source_type == "csv":
                        dataset_path = Path(app.config["SCHEDULE_DATA_DIR"]) / dataset_name
                        if not dataset_path.is_file():
                            raise FileNotFoundError(
                                f"Scheduled CSV '{dataset_name}' was not found in the incoming data folder."
                            )
                        df = _read_pipeline_csv(dataset_path, cfg, check_clean_rows=False)
                        source = f"scheduled CSV ({dataset_name})"
                    else:
                        df = generate_logs(rows)
                        source = f"scheduled synthetic ({rows:,} rows)"
                    _analyze_dataframe(df, source, cfg)
                with _state_lock:
                    _schedule["last_run"] = _iso_now()
                    _schedule["last_error"] = None
                    _schedule["runs"] += 1
            except Exception as exc:
                app.logger.exception("scheduled analysis failed")
                with _state_lock:
                    _schedule["last_run"] = _iso_now()
                    _schedule["last_error"] = f"{type(exc).__name__}: {exc}"
                    _schedule["runs"] += 1
            finally:
                with _state_lock:
                    _schedule["running"] = False
                    if _schedule["enabled"] and schedule_version == _schedule_version:
                        _schedule["next_run"] = (
                            datetime.now(timezone.utc).timestamp()
                            + _schedule["interval_seconds"]
                        )
                    try:
                        _persist_schedule_locked()
                    except sqlite3.Error:
                        app.logger.exception("could not persist completed scheduler state")
        wait_event.wait(1)


def _schedule_response():
    with _state_lock:
        response = dict(_schedule)
        if isinstance(response["next_run"], (float, int)):
            response["next_run"] = datetime.fromtimestamp(
                response["next_run"], timezone.utc
            ).isoformat(timespec="seconds")
        return response


_load_persistent_state()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/login")
def login_page():
    return render_template("login.html")


@app.get("/signup")
def signup_page():
    return render_template("signup.html")


@app.post("/api/analyze")
@require_auth
def analyze():
    cfg = build_config()
    cfg.backoff_base_s = 0.1
    upload = request.files.get("file")
    async_mode = request.form.get("async", "false").lower() == "true"
    try:
        if not upload or not upload.filename:
            try:
                rows = int(request.form.get("rows", 30000))
            except (TypeError, ValueError):
                return jsonify(error="Sample row count must be a whole number."), 400
            rows = max(1000, min(rows, 500_000))
            df = generate_logs(rows)
            source = f"synthetic ({rows:,} rows)"
        else:
            if Path(upload.filename).suffix.lower() != ".csv":
                return jsonify(error="Upload a CSV file to analyze."), 400
            df = _read_pipeline_csv(upload, cfg, check_clean_rows=False)
            source = secure_filename(upload.filename) or "uploaded.csv"

        if async_mode:
            import uuid
            job_id = str(uuid.uuid4())
            thread = threading.Thread(
                target=_run_analysis_async,
                args=(job_id, df, source, cfg),
                name=f"analysis-{job_id[:8]}",
                daemon=True,
            )
            thread.start()
            return jsonify({"job_id": job_id, "status": "started"}), 202

        with _analysis_lock:
            result = _analyze_dataframe(df, source, cfg)
        return jsonify(result)
    except (ValueError, pd.errors.ParserError) as exc:
        app.logger.info("analysis input rejected: %s", exc)
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception("analysis failed")
        return jsonify(error="Analysis failed due to an internal server error."), 500


@app.get("/api/analyze/jobs/<job_id>")
@require_auth
def get_analysis_job(job_id):
    _cleanup_old_jobs()
    with _analysis_jobs_lock:
        job = _analysis_jobs.get(job_id)
    if not job:
        return jsonify(error="Job not found"), 404
    return jsonify(job)


@app.get("/api/analyze/jobs")
@require_auth
def list_analysis_jobs():
    _cleanup_old_jobs()
    with _analysis_jobs_lock:
        jobs = [
            {"job_id": jid, **{k: v for k, v in job.items() if k != "result"}}
            for jid, job in _analysis_jobs.items()
        ]
    jobs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return jsonify(jobs=jobs)


@app.get("/api/status")
@require_auth
def status():
    with _state_lock:
        return jsonify(
            ready=True,
            latest_analysis=_analysis_history[0] if _analysis_history else None,
            schedule=_schedule_response(),
        )


@app.get("/api/history")
@require_auth
def history():
    with _state_lock:
        items = [{
            "generated_at": item["generated_at"],
            "source": item["source"],
            "rows_raw": item["rows_raw"],
            "rows_clean": item["rows_clean"],
            "flagged": item["failures"]["total_flagged"],
            "reliability": round(
                100 * (1 - item["failures"]["total_flagged"] / max(1, item["failures"]["records"])), 1
            ),
            "report_file": item.get("report_file"),
        } for item in _analysis_history]
    return jsonify(history=items)


@app.get("/api/reports")
@require_auth
def reports():
    report_dir = Path(build_config().report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(report_dir.glob("report_*.*"), key=lambda item: item.stat().st_mtime, reverse=True)[:50]:
        if path.suffix.lower() not in {".json", ".md"}:
            continue
        items.append({
            "filename": path.name,
            "format": path.suffix.lstrip(".").upper(),
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
    return jsonify(reports=items)


@app.get("/api/reports/<path:filename>")
@require_auth
def download_report(filename):
    if not re.fullmatch(r"report_[A-Za-z0-9_-]+\.(?:json|md)", filename):
        return jsonify(error="Invalid report filename."), 400
    path = Path(build_config().report_dir) / filename
    if not path.is_file():
        return jsonify(error="Report not found."), 404
    return send_file(path.resolve(), as_attachment=True, download_name=path.name)


@app.get("/api/logs")
@require_auth
def logs():
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        return jsonify(error="Log limit must be a whole number."), 400
    path = Path(build_config().log_file)
    if not path.exists():
        return jsonify(logs=[])

    # Read last N lines efficiently using deque
    from collections import deque
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        lines = deque(log_file, maxlen=limit)
    return jsonify(logs=list(lines))


@app.get("/api/monitor")
@require_auth
def monitor():
    with _state_lock:
        recent_runs = [{
            "generated_at": item["generated_at"],
            "source": item["source"],
            "rows_clean": item["rows_clean"],
            "flagged": item["failures"]["total_flagged"],
        } for item in _analysis_history]
        return jsonify(recovery=_latest_recovery, history=recent_runs)


@app.get("/api/schedule")
@require_auth
def get_schedule():
    return jsonify(schedule=_schedule_response())


@app.get("/api/schedule/datasets")
@require_auth
def schedule_datasets():
    incoming_dir = Path(app.config["SCHEDULE_DATA_DIR"])
    incoming_dir.mkdir(parents=True, exist_ok=True)
    datasets = [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(incoming_dir.glob("*.csv"), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    return jsonify(datasets=datasets)


@app.post("/api/schedule/datasets")
@require_auth
def upload_schedule_dataset():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Choose a CSV file to upload."), 400
    filename = secure_filename(upload.filename)
    if not filename or Path(filename).suffix.lower() != ".csv":
        return jsonify(error="Scheduled pipeline data must be a .csv file."), 400

    incoming_dir = Path(app.config["SCHEDULE_DATA_DIR"])
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = incoming_dir / f".{secrets.token_urlsafe(16)}.upload"
    destination = incoming_dir / filename
    try:
        upload.save(temporary_path)
        _read_pipeline_csv(temporary_path, build_config())
        os.replace(temporary_path, destination)
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        app.logger.info("scheduled CSV rejected: %s", exc)
        return jsonify(error=str(exc)), 400
    except OSError:
        app.logger.exception("could not save scheduled CSV")
        return jsonify(error="Could not save scheduled CSV due to an internal server error."), 500
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return jsonify(dataset={"name": filename, "size": destination.stat().st_size}), 201


@app.post("/api/schedule")
@require_auth
def configure_schedule():
    global _scheduler_thread, _schedule_version
    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form
    if not hasattr(payload, "get"):
        return jsonify(error="Schedule settings must be a JSON object or form submission."), 400
    interval_value = payload.get("interval_seconds", _schedule["interval_seconds"])
    rows_value = payload.get("rows", _schedule["rows"])
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, str))
        or (isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()))
        for value in (interval_value, rows_value)
    ):
        return jsonify(error="Schedule interval and sample rows must be whole numbers."), 400
    try:
        interval = int(interval_value)
        rows = int(rows_value)
    except ValueError:
        return jsonify(error="Schedule interval and sample rows must be whole numbers."), 400
    if not 15 <= interval <= 604800:
        return jsonify(error="Schedule interval must be between 15 seconds and 7 days."), 400
    if not 1000 <= rows <= 500000:
        return jsonify(error="Scheduled sample size must be between 1,000 and 500,000 rows."), 400
    source_type = str(payload.get("source_type", _schedule["source_type"])).lower()
    dataset_name = secure_filename(str(payload.get("dataset_name", _schedule["dataset_name"])))
    if source_type not in {"sample", "csv"}:
        return jsonify(error="Choose either generated sample data or a saved CSV source."), 400
    if source_type == "csv":
        if not dataset_name or Path(dataset_name).suffix.lower() != ".csv":
            return jsonify(error="Choose a saved CSV dataset for scheduled runs."), 400
        dataset_path = Path(app.config["SCHEDULE_DATA_DIR"]) / dataset_name
        if not dataset_path.is_file():
            return jsonify(error=f"Scheduled CSV '{dataset_name}' is not available. Upload it first."), 400
    enabled_value = payload.get("enabled", False)
    if isinstance(enabled_value, bool):
        enabled = enabled_value
    elif isinstance(enabled_value, str) and enabled_value.lower() in ("true", "1", "yes", "on", "false", "0", "no", "off", ""):
        enabled = enabled_value.lower() in ("true", "1", "yes", "on")
    else:
        return jsonify(error="Schedule enabled value must be a boolean."), 400

    with _state_lock:
        _schedule_version += 1
        _schedule["enabled"] = enabled
        _schedule["interval_seconds"] = interval
        _schedule["rows"] = rows
        _schedule["source_type"] = source_type
        _schedule["dataset_name"] = dataset_name if source_type == "csv" else ""
        _schedule["next_run"] = datetime.now(timezone.utc).timestamp() + interval if enabled else None
        _schedule["last_error"] = None
        _persist_schedule_locked()
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_thread = threading.Thread(target=_scheduler_loop, name="pipeline-scheduler", daemon=True)
            _scheduler_thread.start()
    return jsonify(schedule=_schedule_response())


@app.post("/api/recovery-demo")
@require_auth
def recovery_demo():
    global _latest_recovery
    cfg = build_config()
    cfg.backoff_base_s = 0.3
    try:
        result = demo_live_pipeline(cfg)
        with _state_lock:
            _latest_recovery = result
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("recovery demo failed")
        return jsonify(error="Recovery demo failed due to an internal server error."), 500


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
