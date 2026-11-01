"""Analysis routes: on-demand and asynchronous pipeline analysis."""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.services.analysis import AnalysisService
from pipeline_core import _read_pipeline_csv, build_config
from synthetic_data import generate_logs

analysis_bp = Blueprint("analysis", __name__, url_prefix="")


def _services():
    return current_app.config["ANALYSIS_SERVICE"], current_app.config["JOB_MANAGER"]


def _config():
    return current_app.config["APP_CONFIG"]


def session_has_user() -> bool:
    from flask import session

    return bool(session.get("user_id") and session.get("session_id"))


def _stage_upload(upload) -> str:
    """Copy an uploaded CSV to a temporary file owned by the job worker.

    Flask may close its request stream as soon as this route returns.  A job
    therefore cannot safely retain ``FileStorage`` and parse it in a daemon
    thread.  Staging gives the worker a stable file while avoiding expensive
    CSV parsing in the request/response cycle.
    """
    descriptor, path = tempfile.mkstemp(prefix="pipelineiq-analysis-", suffix=".csv")
    os.close(descriptor)
    try:
        upload.save(path)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


@analysis_bp.post("/api/analyze")
def analyze():
    analysis_service, job_manager = _services()
    config = _config()

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
            rows = max(config.min_sample_rows, min(rows, config.max_sample_rows))
            source = f"synthetic ({rows:,} rows)"
            input_data = lambda: generate_logs(rows)
        else:
            if Path(upload.filename).suffix.lower() != ".csv":
                return jsonify(error="Upload a CSV file to analyze."), 400
            source = secure_filename(upload.filename) or "uploaded.csv"
            if async_mode:
                path = _stage_upload(upload)

                def input_data():
                    try:
                        return _read_pipeline_csv(path, cfg, check_clean_rows=False)
                    finally:
                        try:
                            os.unlink(path)
                        except FileNotFoundError:
                            pass

                # The worker also invokes this if it times out while queued,
                # before it has had a chance to call ``input_data``.
                input_data.cleanup = lambda: os.unlink(path) if os.path.exists(path) else None
            else:
                input_data = lambda: _read_pipeline_csv(upload, cfg, check_clean_rows=False)

        if async_mode:
            job_id = str(uuid.uuid4())
            job_manager.create(job_id)
            worker = threading.Thread(
                target=job_manager.run,
                args=(job_id, input_data, source, cfg),
                name=f"analysis-{job_id[:8]}",
                daemon=True,
            )
            worker.start()
            return jsonify({"job_id": job_id, "status": "queued"}), 202

        with current_app.config["ANALYSIS_LOCK"]:
            result = analysis_service.analyze(input_data(), source, cfg=cfg)
        return jsonify(result)
    except (ValueError, pd.errors.ParserError) as exc:
        current_app.logger.info("analysis input rejected: %s", exc)
        return jsonify(error=str(exc)), 400
    except Exception:  # noqa: BLE001 - analysis boundary
        current_app.logger.exception("analysis failed")
        return jsonify(error="Analysis failed due to an internal server error."), 500


@analysis_bp.get("/api/analyze/jobs/<job_id>")
def get_analysis_job(job_id):
    _, job_manager = _services()
    job_manager.cleanup_old()
    job = job_manager.get(job_id)
    if not job:
        return jsonify(error="Job not found"), 404
    return jsonify(job)


@analysis_bp.get("/api/analyze/jobs")
def list_analysis_jobs():
    _, job_manager = _services()
    job_manager.cleanup_old()
    jobs = job_manager.list()
    return jsonify(jobs=jobs)


@analysis_bp.post("/api/recovery-demo")
def recovery_demo():
    from main import demo_live_pipeline

    cfg = build_config()
    cfg.backoff_base_s = 0.3
    try:
        result = demo_live_pipeline(cfg)
        current_app.config["LATEST_RECOVERY"] = result
        return jsonify(result)
    except Exception:  # noqa: BLE001 - recovery demo boundary
        current_app.logger.exception("recovery demo failed")
        return jsonify(error="Recovery demo failed due to an internal server error."), 500
