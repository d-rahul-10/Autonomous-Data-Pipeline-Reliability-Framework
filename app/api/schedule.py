"""Schedule routes: recurring analysis configuration and dataset uploads."""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app.exceptions import ValidationError
from pipeline_core import _read_pipeline_csv, build_config
from werkzeug.utils import secure_filename

schedule_bp = Blueprint("schedule", __name__, url_prefix="")


def _scheduler():
    return current_app.config["SCHEDULER_SERVICE"]


def _config():
    return current_app.config["APP_CONFIG"]


def _parse_whole_number(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError(f"{field_name} must be a whole number.")
    if isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()):
        raise ValidationError(f"{field_name} must be a whole number.")
    return int(value)


@schedule_bp.get("/api/schedule")
def get_schedule():
    return jsonify(schedule=_scheduler().get_state())


@schedule_bp.get("/api/schedule/datasets")
def schedule_datasets():
    config = _config()
    incoming_dir = config.schedule_data_dir
    incoming_dir.mkdir(parents=True, exist_ok=True)
    datasets = [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(incoming_dir.glob("*.csv"), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    return jsonify(datasets=datasets)


@schedule_bp.post("/api/schedule/datasets")
def upload_schedule_dataset():
    config = _config()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Choose a CSV file to upload."), 400
    filename = secure_filename(upload.filename)
    if not filename or Path(filename).suffix.lower() != ".csv":
        return jsonify(error="Scheduled pipeline data must be a .csv file."), 400

    incoming_dir = config.schedule_data_dir
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = incoming_dir / f".{secrets.token_urlsafe(16)}.upload"
    destination = incoming_dir / filename
    try:
        upload.save(temporary_path)
        cfg = build_config()
        _read_pipeline_csv(temporary_path, cfg)
        os.replace(temporary_path, destination)
    except ValueError as exc:
        current_app.logger.info("scheduled CSV rejected: %s", exc)
        return jsonify(error=str(exc)), 400
    except OSError:
        current_app.logger.exception("could not save scheduled CSV")
        return jsonify(error="Could not save scheduled CSV due to an internal server error."), 500
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return jsonify(dataset={"name": filename, "size": destination.stat().st_size}), 201


@schedule_bp.post("/api/schedule")
def configure_schedule():
    scheduler = _scheduler()
    config = _config()
    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form
    if not hasattr(payload, "get"):
        return jsonify(error="Schedule settings must be a JSON object or form submission."), 400

    default_interval = max(15, config.max_interval_seconds // 100)
    try:
        interval = _parse_whole_number(payload.get("interval_seconds", default_interval), "interval_seconds")
        rows = _parse_whole_number(payload.get("rows", 10000), "rows")
    except ValidationError as exc:
        return jsonify(error=str(exc.message or exc.public_message)), 400

    source_type = str(payload.get("source_type", "sample")).lower()
    dataset_name = secure_filename(str(payload.get("dataset_name", "")))
    if source_type not in {"sample", "csv"}:
        return jsonify(error="Choose either generated sample data or a saved CSV source."), 400

    enabled_value = payload.get("enabled", False)
    if isinstance(enabled_value, bool):
        enabled = enabled_value
    elif isinstance(enabled_value, str) and enabled_value.lower() in (
        "true", "1", "yes", "on", "false", "0", "no", "off", "",
    ):
        enabled = enabled_value.lower() in ("true", "1", "yes", "on")
    else:
        return jsonify(error="Schedule enabled value must be a boolean."), 400

    try:
        return jsonify(
            schedule=scheduler.configure(
                enabled=enabled,
                interval_seconds=interval,
                rows=rows,
                source_type=source_type,
                dataset_name=dataset_name,
            )
        )
    except ValidationError as exc:
        return jsonify(error=str(exc.message or exc.public_message)), 400
