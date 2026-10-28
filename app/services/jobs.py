"""Async analysis job manager.

Tracks in-flight analysis jobs in a thread-safe registry with optional
time-based cleanup. Independent of Flask so it can be unit tested directly.
"""
from __future__ import annotations

import logging
import threading
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.services.analysis import AnalysisService
from app.exceptions import PipelineError

logger = logging.getLogger("app.services.jobs")


class AnalysisJobManager:
    def __init__(self, analysis_service: AnalysisService, max_age_hours: int = 24, analysis_lock=None):
        self.analysis_service = analysis_service
        self.max_age_hours = max_age_hours
        self.analysis_lock = analysis_lock or threading.Lock()
        self._jobs = {}
        self._lock = threading.Lock()

    def create(self, job_id: str | None = None) -> str:
        job_id = job_id or str(uuid4())
        with self._lock:
            self._jobs[job_id] = {
                "status": "running",
                "progress": 0,
                "stage": "starting",
                "result": None,
                "error": None,
                "started_at": self._iso_now(),
            }
        return job_id

    def get(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job is not None else None

    def list(self):
        with self._lock:
            jobs = [
                {"job_id": jid, **{k: v for k, v in job.items() if k != "result"}}
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

    def run(self, job_id: str, df, source: str, cfg) -> None:
        """Execute an analysis in the background, updating the job registry."""

        def update_progress(stage: str, progress: int):
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["stage"] = stage
                    self._jobs[job_id]["progress"] = progress

        service = self.analysis_service

        try:
            update_progress("validating", 10)
            with self.analysis_lock:
                result = service.analyze(df, source, progress=update_progress, cfg=cfg)
            with self._lock:
                self._jobs[job_id].update({
                    "status": "completed",
                    "progress": 100,
                    "stage": "done",
                    "result": result,
                    "completed_at": self._iso_now(),
                })
        except Exception as exc:  # noqa: BLE001 - background worker boundary
            logger.exception("async analysis failed")
            with self._lock:
                self._jobs[job_id].update({
                    "status": "failed",
                    "progress": 100,
                    "stage": "error",
                    "error": exc.message if isinstance(exc, PipelineError) else "Analysis failed due to an internal server error.",
                    "completed_at": self._iso_now(),
                })

    @staticmethod
    def _iso_now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
