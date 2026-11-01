"""Async analysis job manager.

Tracks in-flight analysis jobs in a thread-safe registry with optional
time-based cleanup. Independent of Flask so it can be unit tested directly.
"""
from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.services.analysis import AnalysisService
from app.exceptions import AnalysisTimeoutError, PipelineError

logger = logging.getLogger("app.services.jobs")


class AnalysisJobManager:
    def __init__(
        self,
        analysis_service: AnalysisService,
        max_age_hours: int = 24,
        analysis_lock=None,
        timeout_seconds: int = 300,
    ):
        self.analysis_service = analysis_service
        self.max_age_hours = max_age_hours
        self.analysis_lock = analysis_lock or threading.Lock()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._jobs = {}
        self._lock = threading.Lock()

    def create(self, job_id: str | None = None, timeout_seconds: int | None = None) -> str:
        job_id = job_id or str(uuid4())
        timeout = self.timeout_seconds if timeout_seconds is None else max(1, int(timeout_seconds))
        now = time.monotonic()
        with self._lock:
            self._jobs[job_id] = {
                "status": "queued",
                "progress": 0,
                "stage": "queued",
                "result": None,
                "error": None,
                "started_at": self._iso_now(),
                "deadline_at": self._iso_from_timestamp(time.time() + timeout),
                "_deadline_monotonic": now + timeout,
            }
        return job_id

    def get(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._mark_timed_out_locked(job)
            return self._public_job(job) if job is not None else None

    def list(self):
        with self._lock:
            for job in self._jobs.values():
                self._mark_timed_out_locked(job)
            jobs = [
                {
                    "job_id": jid,
                    **{k: v for k, v in self._public_job(job).items() if k != "result"},
                }
                for jid, job in self._jobs.items()
            ]
        jobs.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return jobs

    def cleanup_old(self, max_age_hours: int | None = None) -> None:
        max_age_hours = self.max_age_hours if max_age_hours is None else max_age_hours
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        with self._lock:
            to_remove = [
                jid
                for jid, job in self._jobs.items()
                if job["status"] in ("completed", "failed")
                and datetime.fromisoformat(job.get("completed_at", "1970-01-01")).timestamp()
                < cutoff
            ]
            for jid in to_remove:
                del self._jobs[jid]

    def run(self, job_id: str, input_data, source: str, cfg) -> None:
        """Execute an analysis in the background, updating the job registry."""

        def update_progress(stage: str, progress: int):
            with self._lock:
                if job_id in self._jobs:
                    if self._mark_timed_out_locked(self._jobs[job_id]):
                        raise AnalysisTimeoutError(self._timeout_message())
                    if stage != "queued" and self._jobs[job_id]["status"] == "queued":
                        self._jobs[job_id]["status"] = "running"
                    self._jobs[job_id]["stage"] = stage
                    self._jobs[job_id]["progress"] = progress

        service = self.analysis_service

        try:
            update_progress("queued", 2)
            remaining = self._remaining_seconds(job_id)
            if remaining <= 0 or not self.analysis_lock.acquire(timeout=remaining):
                raise AnalysisTimeoutError(self._timeout_message())
            try:
                update_progress("reading_csv" if callable(input_data) else "validating", 5)
                # Uploaded files are parsed in this worker rather than in the
                # request handler.  This keeps the HTTP response fast and
                # makes parse failures visible through the job endpoint.
                df = input_data() if callable(input_data) else input_data
                update_progress("validating", 10)
                result = service.analyze(df, source, progress=update_progress, cfg=cfg)
            finally:
                self.analysis_lock.release()
            with self._lock:
                job = self._jobs[job_id]
                if not self._mark_timed_out_locked(job):
                    job.update({
                        "status": "completed",
                        "progress": 100,
                        "stage": "done",
                        "result": result,
                        "completed_at": self._iso_now(),
                    })
        except Exception as exc:  # noqa: BLE001 - background worker boundary
            if isinstance(exc, (PipelineError, ValueError)):
                logger.info("async analysis rejected: %s", exc)
            else:
                logger.exception("async analysis failed")
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None and not self._mark_timed_out_locked(job):
                    if isinstance(exc, PipelineError):
                        message = exc.message
                    elif isinstance(exc, ValueError):
                        # CSV validation and model precondition errors are
                        # safe, actionable dataset feedback.  Do not turn
                        # them into an opaque internal-server message.
                        message = f"Dataset could not be processed: {exc}"
                    else:
                        message = "Analysis failed due to an internal server error."
                    job.update({
                        "status": "failed",
                        "progress": 100,
                        "stage": "error",
                        "error": message,
                        "completed_at": self._iso_now(),
                    })
        finally:
            cleanup = getattr(input_data, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except OSError:
                    logger.warning("could not remove staged analysis upload", exc_info=True)

    def _remaining_seconds(self, job_id: str) -> float:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or self._mark_timed_out_locked(job):
                return 0.0
            return max(0.0, job["_deadline_monotonic"] - time.monotonic())

    def _mark_timed_out_locked(self, job: dict) -> bool:
        if job["status"] in ("completed", "failed"):
            return job.get("stage") == "timeout"
        if time.monotonic() < job["_deadline_monotonic"]:
            return False
        job.update({
            "status": "failed",
            "progress": 100,
            "stage": "timeout",
            "error": self._timeout_message(),
            "completed_at": self._iso_now(),
        })
        return True

    def _timeout_message(self) -> str:
        return (
            f"Analysis exceeded the {self.timeout_seconds}-second processing limit. "
            "Try a smaller CSV or review the dataset for malformed rows."
        )

    @staticmethod
    def _public_job(job: dict) -> dict:
        """Return API-safe job data without server-only deadline bookkeeping."""
        return deepcopy({key: value for key, value in job.items() if not key.startswith("_")})

    @staticmethod
    def _iso_now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _iso_from_timestamp(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
