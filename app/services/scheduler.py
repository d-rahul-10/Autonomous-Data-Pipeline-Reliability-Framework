"""Background schedule service.

Runs recurring pipeline analyses on an interval. Keeps schedule state in
memory and persists it to SQLite. Independent of Flask so it can be unit
tested and started/stopped cleanly by the application factory.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.db import transaction
from app.exceptions import ValidationError
from app.repositories.schedule import ScheduleRepository
from app.services.analysis import AnalysisService

logger = logging.getLogger("app.services.scheduler")


class SchedulerService:
    def __init__(
        self,
        config,
        analysis_service: AnalysisService,
        schedule_repository: ScheduleRepository,
        data_dir: Path | None = None,
        analysis_lock=None,
    ):
        self.config = config
        self.analysis_service = analysis_service
        self.schedule_repository = schedule_repository
        self.data_dir = data_dir or config.schedule_data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._schedule = self._defaults()
        self._version = 0
        self._lock = threading.RLock()
        self._analysis_lock = analysis_lock or threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ state
    def _defaults(self) -> dict:
        return {
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

    def get_state(self) -> dict:
        with self._lock:
            state = dict(self._schedule)
        next_run = state.get("next_run")
        if isinstance(next_run, (int, float)):
            state["next_run"] = (
                datetime.fromtimestamp(next_run, timezone.utc).isoformat(timespec="seconds")
            )
        return state

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._schedule["enabled"])

    # ------------------------------------------------------------------ configuration
    def configure(self, *, enabled: bool, interval_seconds: int, rows: int,
                  source_type: str, dataset_name: str = "") -> dict:
        if source_type not in {"sample", "csv"}:
            raise ValidationError("Choose either generated sample data or a saved CSV source.")
        if not isinstance(interval_seconds, int) or not (self.config.min_interval_seconds <= interval_seconds <= self.config.max_interval_seconds):
            raise ValidationError(
                f"Schedule interval must be between {self.config.min_interval_seconds} and "
                f"{self.config.max_interval_seconds} seconds."
            )
        if not isinstance(rows, int) or not (self.config.min_sample_rows <= rows <= self.config.max_sample_rows):
            raise ValidationError(
                f"Scheduled sample size must be between {self.config.min_sample_rows} and "
                f"{self.config.max_sample_rows} rows."
            )
        if source_type == "csv":
            safe_name = self._safe_dataset_name(dataset_name)
            dataset_path = self.data_dir / safe_name
            if not dataset_path.is_file():
                raise ValidationError(
                    f"Scheduled CSV '{safe_name}' is not available. Upload it first."
                )
            dataset_name = safe_name
        else:
            dataset_name = ""

        next_run = None
        if enabled:
            next_run = datetime.now(timezone.utc).timestamp() + interval_seconds

        with self._lock:
            self._version += 1
            self._schedule.update({
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                "rows": rows,
                "source_type": source_type,
                "dataset_name": dataset_name,
                "next_run": next_run,
                "last_error": None,
            })
            self._persist_locked()
            self._restart_thread_locked()
        return self.get_state()

    def _safe_dataset_name(self, name: str) -> str:
        from werkzeug.utils import secure_filename

        filename = secure_filename(name)
        if not filename or Path(filename).suffix.lower() != ".csv":
            raise ValidationError("Scheduled pipeline data must be a .csv file.")
        return filename

    # ------------------------------------------------------------------ persistence / lifecycle
    def load_persisted(self) -> None:
        """Load schedule from the database and start the loop if enabled."""
        row = self.schedule_repository.get()
        if row:
            try:
                persisted = json.loads(row["value"])
                if not isinstance(persisted, dict):
                    raise ValueError("saved scheduler settings must be a JSON object")
                self._validate_and_apply(persisted)
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.exception("saved scheduler settings are invalid; using safe defaults")
        self._schedule["running"] = False
        if self._schedule["enabled"] and not self._schedule["next_run"]:
            self._schedule["next_run"] = datetime.now(timezone.utc).timestamp()
        if self._schedule["enabled"]:
            self._start_thread_locked()

    def _validate_and_apply(self, persisted: dict) -> None:
        interval = persisted.get("interval_seconds", self._schedule["interval_seconds"])
        rows = persisted.get("rows", self._schedule["rows"])
        enabled = persisted.get("enabled", self._schedule["enabled"])
        source_type = persisted.get("source_type", self._schedule["source_type"])
        dataset_name = persisted.get("dataset_name", self._schedule["dataset_name"])
        next_run = persisted.get("next_run")
        last_run = persisted.get("last_run")
        last_error = persisted.get("last_error")
        runs = persisted.get("runs", self._schedule["runs"])

        if type(enabled) is not bool:
            raise ValueError("saved enabled value must be a boolean")
        if type(interval) is not int or not (self.config.min_interval_seconds <= interval <= self.config.max_interval_seconds):
            raise ValueError("saved interval is out of range")
        if type(rows) is not int or not (self.config.min_sample_rows <= rows <= self.config.max_sample_rows):
            raise ValueError("saved sample size is out of range")
        if source_type not in {"sample", "csv"}:
            raise ValueError("saved source_type is invalid")
        if not isinstance(dataset_name, str):
            raise ValueError("saved dataset_name must be a string")
        if next_run is not None and (
            isinstance(next_run, bool) or not isinstance(next_run, (int, float)) or not math.isfinite(next_run)
        ):
            raise ValueError("saved next_run must be a finite timestamp or null")
        if last_run is not None and not isinstance(last_run, str):
            raise ValueError("saved last_run must be a string or null")
        if last_error is not None and not isinstance(last_error, str):
            raise ValueError("saved last_error must be a string or null")
        if type(runs) is not int or runs < 0:
            raise ValueError("saved runs must be a non-negative integer")
        if source_type == "csv" and (
            not dataset_name
            or self._safe_dataset_name(dataset_name) != dataset_name
            or Path(dataset_name).suffix.lower() != ".csv"
        ):
            raise ValueError("saved CSV dataset name is invalid")

        with self._lock:
            self._version += 1
            self._schedule.update({
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

    def _persist_locked(self) -> None:
        self.schedule_repository.save(json.dumps(self._schedule))

    def _start_thread_locked(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="pipeline-scheduler", daemon=True
            )
            self._thread.start()

    def _restart_thread_locked(self) -> None:
        if self._schedule["enabled"]:
            self._start_thread_locked()

    def stop(self) -> None:
        with self._lock:
            self._schedule["enabled"] = False
            self._schedule["next_run"] = None
            self._schedule["running"] = False
            self._stop.set()
            thread = self._thread
        if isinstance(thread, threading.Thread):
            thread.join(timeout=3)

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        wait_event = threading.Event()
        while not self._stop.wait(1):
            with self._lock:
                if not self._schedule["enabled"]:
                    if threading.current_thread() is self._thread:
                        self._thread = None
                    return
                now = datetime.now(timezone.utc)
                next_run = self._schedule["next_run"]
                due = bool(
                    self._schedule["enabled"]
                    and next_run is not None
                    and now.timestamp() >= next_run
                )
                if not due:
                    continue
                schedule_version = self._version
                self._schedule["next_run"] = now.timestamp() + self._schedule["interval_seconds"]
                self._schedule["running"] = True
                rows = self._schedule["rows"]
                source_type = self._schedule["source_type"]
                dataset_name = self._schedule["dataset_name"]

            if due:
                self._run_due(schedule_version, rows, source_type, dataset_name)

    def _run_due(self, schedule_version: int, rows: int, source_type: str, dataset_name: str) -> None:
        try:
            with self._analysis_lock:
                with self._lock:
                    should_run = (
                        self._schedule["enabled"] and schedule_version == self._version
                    )
                if not should_run:
                    return
                cfg = self._build_config()
                if source_type == "csv":
                    dataset_path = self.data_dir / dataset_name
                    if not dataset_path.is_file():
                        raise FileNotFoundError(
                            f"Scheduled CSV '{dataset_name}' was not found in the incoming data folder."
                        )
                    from pipeline_core import _read_pipeline_csv
                    df = _read_pipeline_csv(dataset_path, cfg, check_clean_rows=False)
                    source = f"scheduled CSV ({dataset_name})"
                else:
                    from synthetic_data import generate_logs
                    df = generate_logs(rows)
                    source = f"scheduled synthetic ({rows:,} rows)"
                self.analysis_service.analyze(df, source, cfg=cfg)
            with self._lock:
                self._schedule["last_run"] = self._iso_now()
                self._schedule["last_error"] = None
                self._schedule["runs"] += 1
        except Exception as exc:  # noqa: BLE001 - scheduler boundary
            logger.exception("scheduled analysis failed")
            with self._lock:
                self._schedule["last_run"] = self._iso_now()
                self._schedule["last_error"] = f"{type(exc).__name__}: {exc}"
                self._schedule["runs"] += 1
        finally:
            with self._lock:
                self._schedule["running"] = False
                if self._schedule["enabled"] and schedule_version == self._version:
                    self._schedule["next_run"] = (
                        datetime.now(timezone.utc).timestamp() + self._schedule["interval_seconds"]
                    )
                try:
                    self._persist_locked()
                except Exception:  # noqa: BLE001
                    logger.exception("could not persist completed scheduler state")

    # ------------------------------------------------------------------ helpers
    def _build_config(self):
        from pipeline_core import build_config

        cfg = build_config()
        cfg.backoff_base_s = 0.1
        return cfg

    @staticmethod
    def _iso_now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
