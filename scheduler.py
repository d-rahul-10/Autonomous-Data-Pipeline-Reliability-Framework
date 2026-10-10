"""Lightweight interval scheduler (stdlib only)."""
import math
import threading
import time
from dataclasses import dataclass, field
from numbers import Real
from typing import Callable

from logging_utils import get_logger


@dataclass
class Job:
    name: str
    fn: Callable
    interval_s: float
    next_run: float = field(default=0.0)
    runs: int = 0
    running: bool = False


class Scheduler:
    def __init__(self, log_file: str = "pipeline.log"):
        self.jobs: list[Job] = []
        self.log = get_logger("scheduler", log_file)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

    def add_job(
        self,
        name: str,
        fn: Callable,
        interval_s: float,
        run_immediately: bool = True,
    ):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Job name must be a non-empty string.")
        if not callable(fn):
            raise TypeError("Job function must be callable.")
        if (isinstance(interval_s, bool) or not isinstance(interval_s, Real)
                or not math.isfinite(interval_s) or interval_s <= 0):
            raise ValueError("interval_s must be a finite positive number.")
        if not isinstance(run_immediately, bool):
            raise ValueError("run_immediately must be a boolean.")
        with self._lock:
            if any(job.name == name for job in self.jobs):
                raise ValueError(f"A job named '{name}' is already registered.")
            job = Job(
                name,
                fn,
                float(interval_s),
                time.time() if run_immediately else time.time() + interval_s,
            )
            self.jobs.append(job)
        return job

    def cancel_job(self, name: str) -> bool:
        """Remove a pending job. This does not interrupt a job already executing."""
        with self._lock:
            for job in self.jobs:
                if job.name == name:
                    self.jobs.remove(job)
                    return True
        return False

    def run_pending(self):
        now = time.time()
        with self._lock:
            jobs = list(self.jobs)
        for job in jobs:
            with self._lock:
                if job not in self.jobs or job.running or now < job.next_run:
                    continue
                job.running = True
            self.log.info("scheduler: running job '%s'", job.name)
            try:
                job.fn()
            except Exception as exc:                    # one bad job must not kill the scheduler
                self.log.error("job '%s' crashed: %s", job.name, exc)
            finally:
                with self._lock:
                    job.runs += 1
                    job.running = False
                    job.next_run = time.time() + job.interval_s

    def run(self, max_cycles: int | None = None, tick_s: float = 0.5):
        if (max_cycles is not None and (
            isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 0
        )):
            raise ValueError("max_cycles must be a non-negative integer or None.")
        if (isinstance(tick_s, bool) or not isinstance(tick_s, Real)
                or not math.isfinite(tick_s) or tick_s < 0):
            raise ValueError("tick_s must be a finite non-negative number.")
        cycles = 0
        while not self._stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            self.run_pending()
            cycles += 1
            time.sleep(tick_s)

    def stop(self):
        """Stop the scheduler loop after its current synchronous job finishes."""
        self._stop_event.set()
