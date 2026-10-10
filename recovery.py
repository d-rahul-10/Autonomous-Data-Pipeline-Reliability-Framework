"""Automatic recovery: classify errors, apply corrective actions, retry with exponential backoff."""
import time
from math import isfinite
from numbers import Real
from typing import Callable, Optional

from config import Config
from monitor import PipelineMonitor, TaskTimeoutError
from logging_utils import get_logger

# Errors that retrying cannot fix (bad data / code bugs) - escalate immediately.
class SchemaViolation(Exception):
    """Raise for schema changes that retries cannot fix."""


NON_RECOVERABLE = (ValueError, TypeError, KeyError, SchemaViolation)
RECOVERABLE = (ConnectionError, TimeoutError, FileNotFoundError, OSError)


class RecoveryManager:
    def __init__(self, monitor: PipelineMonitor, cfg: Config | None = None):
        self.monitor = monitor
        self.cfg = cfg or Config()
        if (isinstance(self.cfg.max_retries, bool) or not isinstance(self.cfg.max_retries, int)
                or self.cfg.max_retries < 0):
            raise ValueError("max_retries must be a non-negative integer.")
        if (isinstance(self.cfg.backoff_base_s, bool) or not isinstance(self.cfg.backoff_base_s, Real)
                or not isfinite(self.cfg.backoff_base_s) or self.cfg.backoff_base_s < 0):
            raise ValueError("backoff_base_s must be a finite non-negative number.")
        if (isinstance(self.cfg.backoff_factor, bool) or not isinstance(self.cfg.backoff_factor, Real)
                or not isfinite(self.cfg.backoff_factor) or self.cfg.backoff_factor < 1):
            raise ValueError("backoff_factor must be a finite number greater than or equal to 1.")
        self.log = get_logger("recovery", self.cfg.log_file)
        self.actions: dict[type, Callable[[Exception], None]] = {}
        self.stats = {"recovered": 0, "exhausted": 0, "non_recoverable": 0, "clean_first_try": 0}

    def register_action(self, exc_type: type, action: Callable[[Exception], None]):
        """Register a corrective action, e.g. reconnect DB for ConnectionError."""
        self.actions[exc_type] = action

    def _corrective(self, exc: Exception):
        for exc_type, action in self.actions.items():
            if isinstance(exc, exc_type):
                self.log.warning("applying corrective action '%s' for %s", action.__name__, type(exc).__name__)
                try:
                    action(exc)
                except Exception as a_exc:
                    self.log.error("corrective action failed: %s", a_exc)
                return

    def execute(
        self,
        name: str,
        fn: Callable,
        *args,
        fallback: Optional[Callable] = None,
        allow_timeout_retry: bool = False,
        cooperative_cancel: bool = False,
        **kwargs,
    ):
        last_exc = None
        for attempt in range(1, self.cfg.max_retries + 2):
            try:
                result = self.monitor.run_task(
                    name,
                    fn,
                    *args,
                    attempt=attempt,
                    cancel_on_timeout=cooperative_cancel,
                    allow_concurrent=allow_timeout_retry,
                    **kwargs,
                )
                self.stats["clean_first_try" if attempt == 1 else "recovered"] += 1
                if attempt > 1:
                    self.log.info("task=%s RECOVERED after %d attempts", name, attempt)
                return result
            except TaskTimeoutError as exc:
                if not allow_timeout_retry:
                    self.stats["non_recoverable"] += 1
                    self.log.error(
                        "task=%s timed out; retry disabled because its worker may still be running",
                        name,
                    )
                    raise
                last_exc = exc
                if attempt > self.cfg.max_retries:
                    break
                delay = self.cfg.backoff_base_s * (self.cfg.backoff_factor ** (attempt - 1))
                self.log.warning("task=%s timed out; explicitly permitted retry %d/%d in %.2fs",
                                 name, attempt, self.cfg.max_retries, delay)
                time.sleep(delay)
            except NON_RECOVERABLE as exc:
                self.stats["non_recoverable"] += 1
                self.log.error("task=%s non-recoverable %s - escalating", name, type(exc).__name__)
                raise
            except RECOVERABLE as exc:
                last_exc = exc
                if attempt > self.cfg.max_retries:
                    break
                self._corrective(exc)
                delay = self.cfg.backoff_base_s * (self.cfg.backoff_factor ** (attempt - 1))
                self.log.warning("task=%s retry %d/%d in %.2fs", name, attempt, self.cfg.max_retries, delay)
                time.sleep(delay)
        self.stats["exhausted"] += 1
        self.log.error("task=%s retries exhausted", name)
        if fallback:
            self.log.warning("task=%s running fallback", name)
            return fallback()
        raise last_exc
