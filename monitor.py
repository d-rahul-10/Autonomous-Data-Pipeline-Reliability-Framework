"""Pipeline execution monitor: runs tasks, records duration/status, enforces timeouts."""
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, asdict
from datetime import datetime
from math import isfinite
from numbers import Real
from typing import Callable, Optional

import pandas as pd

from logging_utils import get_logger


class TaskTimeoutError(TimeoutError):
    """A task exceeded its deadline; this does not imply its worker was terminated."""

    def __init__(self, message: str, task_still_running: bool):
        super().__init__(message)
        self.task_still_running = task_still_running


class TaskAlreadyRunningError(RuntimeError):
    """Raised when a task name is reused while its previous worker is still active."""


@dataclass
class ExecutionRecord:
    task: str
    started_at: str
    duration_s: float
    status: str                 # SUCCESS | FAILED | TIMEOUT
    attempt: int = 1
    error_type: Optional[str] = None
    error_msg: Optional[str] = None


class PipelineMonitor:
    def __init__(self, timeout_s: float = 10.0, log_file: str = "pipeline.log"):
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, Real)
                or not isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError("timeout_s must be a finite positive number.")
        self.timeout_s = timeout_s
        self.records: list[ExecutionRecord] = []
        self.log = get_logger("monitor", log_file)
        self._active_lock = threading.Lock()
        self._active_tasks = {}
        self._records_lock = threading.Lock()

    def run_task(
        self,
        name: str,
        fn: Callable,
        *args,
        attempt: int = 1,
        cancel_on_timeout: bool = False,
        allow_concurrent: bool = False,
        **kwargs,
    ):
        """Run fn with timeout; record outcome; re-raise on failure."""
        if cancel_on_timeout and "cancel_event" in kwargs:
            raise ValueError("cancel_event is provided by the monitor when cancel_on_timeout is enabled.")

        start = time.perf_counter()
        started_at = datetime.now().isoformat(timespec="seconds")
        cancel_event = threading.Event()
        if cancel_on_timeout:
            kwargs["cancel_event"] = cancel_event

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            self._check_concurrent(name, pool, allow_concurrent)
            future = pool.submit(fn, *args, **kwargs)
            self._track_task(name, future)
            result = self._wait_for_result(future)
            self._record(name, started_at, start, "SUCCESS", attempt)
            self.log.info("task=%s attempt=%d status=SUCCESS", name, attempt)
            return result
        except FutTimeout:
            self._handle_timeout(name, started_at, start, attempt, future, cancel_event, cancel_on_timeout)
        except Exception as exc:
            self._handle_exception(name, started_at, start, attempt, exc)
        finally:
            pool.shutdown(wait=False)

    def _check_concurrent(self, name: str, pool: ThreadPoolExecutor, allow_concurrent: bool) -> None:
        with self._active_lock:
            active = self._active_tasks.get(name, set())
            active = {future for future in active if not future.done()}
            if active and not allow_concurrent:
                pool.shutdown(wait=False)
                raise TaskAlreadyRunningError(
                    f"Task '{name}' is still running after its previous attempt timed out."
                )

    def _track_task(self, name: str, future) -> None:
        with self._active_lock:
            active = self._active_tasks.get(name, set())
            active.add(future)
            self._active_tasks[name] = active
        future.add_done_callback(lambda completed: self._release_task(name, completed))

    def _wait_for_result(self, future):
        return future.result(timeout=self.timeout_s)

    def _handle_timeout(
        self,
        name: str,
        started_at: str,
        start: float,
        attempt: int,
        future,
        cancel_event: threading.Event,
        cancel_on_timeout: bool,
    ) -> None:
        if future.done():
            task_error = future.exception()
            if task_error is not None:
                self._record(
                    name, started_at, start, "FAILED", attempt,
                    type(task_error).__name__, str(task_error),
                )
                self.log.error(
                    "task=%s attempt=%d status=FAILED error=%s: %s",
                    name, attempt, type(task_error).__name__, task_error,
                )
                raise task_error
        if cancel_on_timeout:
            cancel_event.set()
        task_still_running = not future.done()
        message = (
            f"Task '{name}' exceeded {self.timeout_s}s; "
            f"worker still running at timeout check: {task_still_running}."
        )
        self._record(name, started_at, start, "TIMEOUT", attempt, "TaskTimeoutError", message)
        self.log.error("task=%s attempt=%d status=TIMEOUT worker_running=%s",
                       name, attempt, task_still_running)
        raise TaskTimeoutError(message, task_still_running)

    def _handle_exception(
        self,
        name: str,
        started_at: str,
        start: float,
        attempt: int,
        exc: Exception,
    ) -> None:
        self._record(name, started_at, start, "FAILED", attempt, type(exc).__name__, str(exc))
        self.log.error("task=%s attempt=%d status=FAILED error=%s: %s\n%s",
                       name, attempt, type(exc).__name__, exc, traceback.format_exc(limit=2))
        raise

    def _release_task(self, name, future):
        with self._active_lock:
            active = self._active_tasks.get(name)
            if active is not None:
                active.discard(future)
                if not active:
                    self._active_tasks.pop(name, None)

    def _record(self, name, started_at, start, status, attempt, etype=None, emsg=None):
        record = ExecutionRecord(name, started_at, round(time.perf_counter() - start, 4),
                                 status, attempt, etype, emsg)
        with self._records_lock:
            self.records.append(record)

    def to_frame(self) -> pd.DataFrame:
        with self._records_lock:
            records = list(self.records)
        return pd.DataFrame([asdict(record) for record in records])

    def summary(self) -> dict:
        df = self.to_frame()
        if df.empty:
            return {"total_runs": 0}
        return {
            "total_runs": len(df),
            "success": int((df.status == "SUCCESS").sum()),
            "failed": int((df.status == "FAILED").sum()),
            "timeout": int((df.status == "TIMEOUT").sum()),
            "avg_duration_s": round(df.duration_s.mean(), 4),
            "max_duration_s": round(df.duration_s.max(), 4),
        }