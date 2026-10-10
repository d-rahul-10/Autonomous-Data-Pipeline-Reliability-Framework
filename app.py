
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import re
import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from bottleneck_predictor import BottleneckPredictor
from csv_input import read_csv_table
from data_quality import DataQualityValidator
from failure_detector import FailureDetector
from main import build_config, demo_live_pipeline
from reporter import Reporter
from synthetic_data import generate_logs

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024   # 500 MB upload limit
app.config["STATE_DB_PATH"] = Path("pipeline_state.sqlite3")
app.config["SCHEDULE_DATA_DIR"] = Path("data") / "incoming"

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
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
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


def _read_pipeline_csv(file_path, source, cfg, check_clean_rows=True):
    try:
        df = read_csv_table(file_path, low_memory=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise ValueError(f"Could not read CSV '{source}': {exc}") from exc
    needed = [
        cfg.col_timestamp, cfg.col_task, cfg.col_status, cfg.col_duration,
        cfg.col_cpu, cfg.col_memory, cfg.col_io, cfg.col_latency,
    ]
    missing = [column for column in needed if column not in df.columns]
    if missing:
        raise ValueError(
            f"CSV '{source}' was read, but it is not in the ETL pipeline-log format this "
            f"dashboard analyzes; missing required columns: {missing}. "
            f"Found columns: {list(df.columns)}. Upload ETL run logs with the required "
            "timestamp, task_id, status, duration, cpu_usage, memory_usage, "
            "io_throughput, and latency columns, or map your ETL column names in config.py."
        )
    if cfg.col_error not in df.columns:
        df[cfg.col_error] = None
    if cfg.col_deps not in df.columns:
        df[cfg.col_deps] = ""
    df[cfg.col_timestamp] = pd.to_datetime(df[cfg.col_timestamp], errors="coerce")
    if check_clean_rows and len(DataQualityValidator(cfg).clean(df)) < 200:
        raise ValueError("Too few valid rows after cleaning (need at least 200).")
    return df


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
        "timestamp": str(row[timestamp]),
        "task": str(row[task]),
        "duration": round(float(row[duration]), 2),
        "risk": round(float(row["bottleneck_risk"]), 3),
    } for _, row in risk.iterrows()]

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


def _scheduler_loop():
    global _scheduler_thread
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
                        df = _read_pipeline_csv(dataset_path, dataset_name, cfg, check_clean_rows=False)
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
        threading.Event().wait(1)


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


@app.post("/api/analyze")
def analyze():
    cfg = build_config()
    cfg.backoff_base_s = 0.1
    upload = request.files.get("file")
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
            df = _read_pipeline_csv(upload, upload.filename, cfg, check_clean_rows=False)
            source = secure_filename(upload.filename) or "uploaded.csv"

        with _analysis_lock:
            result = _analyze_dataframe(df, source, cfg)
        return jsonify(result)
    except (ValueError, pd.errors.ParserError) as exc:
        app.logger.info("analysis input rejected: %s", exc)
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception("analysis failed")
        return jsonify(error="Analysis failed due to an internal server error."), 500


@app.get("/api/status")
def status():
    with _state_lock:
        return jsonify(
            ready=True,
            latest_analysis=_analysis_history[0] if _analysis_history else None,
            schedule=_schedule_response(),
        )


@app.get("/api/history")
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
def download_report(filename):
    if not re.fullmatch(r"report_[A-Za-z0-9_-]+\.(?:json|md)", filename):
        return jsonify(error="Invalid report filename."), 400
    path = Path(build_config().report_dir) / filename
    if not path.is_file():
        return jsonify(error="Report not found."), 404
    return send_file(path.resolve(), as_attachment=True, download_name=path.name)


@app.get("/api/logs")
def logs():
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 1000))
    except ValueError:
        return jsonify(error="Log limit must be a whole number."), 400
    path = Path(build_config().log_file)
    if not path.exists():
        return jsonify(logs=[])

    chunk_size = 8192
    with path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        position = log_file.tell()
        content = b""
        while position > 0 and content.count(b"\n") <= limit:
            read_size = min(chunk_size, position)
            position -= read_size
            log_file.seek(position)
            content = log_file.read(read_size) + content
    lines = content.decode("utf-8", errors="replace").splitlines()
    return jsonify(logs=lines[-limit:])


@app.get("/api/monitor")
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
def get_schedule():
    return jsonify(schedule=_schedule_response())


@app.get("/api/schedule/datasets")
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
def upload_schedule_dataset():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Choose a CSV file to upload."), 400
    filename = secure_filename(upload.filename)
    if not filename or Path(filename).suffix.lower() != ".csv":
        return jsonify(error="Scheduled pipeline data must be a .csv file."), 400

    incoming_dir = Path(app.config["SCHEDULE_DATA_DIR"])
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = incoming_dir / f".{uuid.uuid4().hex}.upload"
    destination = incoming_dir / filename
    try:
        upload.save(temporary_path)
        _read_pipeline_csv(temporary_path, filename, build_config())
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
