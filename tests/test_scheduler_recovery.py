import threading
import time
import unittest
from unittest.mock import Mock, patch

from config import Config
from monitor import (
    PipelineMonitor,
    TaskAlreadyRunningError,
    TaskTimeoutError,
)
from recovery import RecoveryManager
from scheduler import Scheduler


class PipelineMonitorTests(unittest.TestCase):
    def setUp(self):
        self.logger = patch("monitor.get_logger", return_value=Mock())
        self.logger.start()
        self.addCleanup(self.logger.stop)

    def test_monitor_records_success_failure_and_summary(self):
        monitor = PipelineMonitor(timeout_s=0.5)
        self.assertEqual(monitor.run_task("ok", lambda: 42), 42)

        with self.assertRaisesRegex(ValueError, "bad input"):
            monitor.run_task("bad", lambda: (_ for _ in ()).throw(ValueError("bad input")))

        self.assertEqual(monitor.summary()["total_runs"], 2)
        self.assertEqual(monitor.summary()["success"], 1)
        self.assertEqual(monitor.summary()["failed"], 1)
        self.assertEqual(list(monitor.to_frame()["status"]), ["SUCCESS", "FAILED"])

    def test_task_timeout_does_not_terminate_worker_or_allow_same_name_overlap(self):
        monitor = PipelineMonitor(timeout_s=0.02)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_task():
            started.set()
            try:
                release.wait(1)
            finally:
                finished.set()

        with self.assertRaises(TaskTimeoutError) as raised:
            monitor.run_task("shared-task", slow_task)

        self.assertTrue(started.is_set())
        self.assertTrue(raised.exception.task_still_running)
        self.assertIn("worker still running", str(raised.exception))
        with self.assertRaises(TaskAlreadyRunningError):
            monitor.run_task("shared-task", lambda: "overlap")

        release.set()
        self.assertTrue(finished.wait(1))
        self.assertEqual(monitor.run_task("shared-task", lambda: "after completion"), "after completion")
        self.assertEqual(monitor.summary()["timeout"], 1)

    def test_cooperative_timeout_signals_event_without_claiming_termination(self):
        monitor = PipelineMonitor(timeout_s=0.02)
        cancelled = threading.Event()
        finished = threading.Event()

        def cooperative_task(cancel_event):
            try:
                cancel_event.wait(1)
                if cancel_event.is_set():
                    cancelled.set()
            finally:
                finished.set()

        with self.assertRaises(TaskTimeoutError) as raised:
            monitor.run_task("cooperative", cooperative_task, cancel_on_timeout=True)

        self.assertTrue(cancelled.wait(1))
        self.assertTrue(finished.wait(1))
        self.assertIsInstance(raised.exception.task_still_running, bool)

    def test_task_raised_timeout_error_is_failure_not_monitor_timeout(self):
        monitor = PipelineMonitor(timeout_s=0.5)

        with self.assertRaisesRegex(TimeoutError, "remote request timed out"):
            monitor.run_task(
                "remote-timeout",
                lambda: (_ for _ in ()).throw(TimeoutError("remote request timed out")),
            )

        self.assertEqual(monitor.records[0].status, "FAILED")
        self.assertEqual(monitor.records[0].error_type, "TimeoutError")

    def test_monitor_rejects_invalid_timeout(self):
        for timeout in (0, -1, float("inf"), True, "1"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                PipelineMonitor(timeout_s=timeout)


class RecoveryManagerTests(unittest.TestCase):
    def setUp(self):
        self.logger_patches = (
            patch("monitor.get_logger", return_value=Mock()),
            patch("recovery.get_logger", return_value=Mock()),
        )
        for logger_patch in self.logger_patches:
            logger_patch.start()
            self.addCleanup(logger_patch.stop)

    def _manager(self, **config):
        values = {"max_retries": 2, "backoff_base_s": 0, "backoff_factor": 2}
        values.update(config)
        cfg = Config(**values)
        monitor = PipelineMonitor(timeout_s=0.5)
        return RecoveryManager(monitor, cfg), monitor

    def test_recoverable_failure_runs_corrective_action_then_succeeds(self):
        manager, monitor = self._manager()
        attempts = {"count": 0}
        corrected = []

        def task():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ConnectionError("temporarily unavailable")
            return "loaded"

        manager.register_action(ConnectionError, lambda error: corrected.append(str(error)))
        with patch("recovery.time.sleep") as sleep:
            self.assertEqual(manager.execute("load", task), "loaded")

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(corrected, ["temporarily unavailable"])
        sleep.assert_called_once_with(0)
        self.assertEqual(manager.stats["recovered"], 1)
        self.assertEqual(monitor.summary()["total_runs"], 2)

    def test_nonrecoverable_failure_is_not_retried(self):
        manager, monitor = self._manager()
        task = Mock(side_effect=ValueError("invalid schema"))

        with self.assertRaisesRegex(ValueError, "invalid schema"):
            manager.execute("validate", task)

        task.assert_called_once()
        self.assertEqual(manager.stats["non_recoverable"], 1)
        self.assertEqual(monitor.summary()["total_runs"], 1)

    def test_exhausted_retries_return_explicit_fallback_result(self):
        manager, monitor = self._manager(max_retries=1)
        task = Mock(side_effect=ConnectionError("offline"))
        fallback = Mock(return_value="fallback")

        with patch("recovery.time.sleep"):
            result = manager.execute("connect", task, fallback=fallback)

        self.assertEqual(result, "fallback")
        self.assertEqual(task.call_count, 2)
        fallback.assert_called_once_with()
        self.assertEqual(manager.stats["exhausted"], 1)
        self.assertEqual(monitor.summary()["failed"], 2)

    def test_timeout_is_not_retried_by_default_while_worker_may_run(self):
        manager, monitor = self._manager(max_retries=3, task_timeout_s=0.02)
        started = threading.Event()
        release = threading.Event()
        calls = Mock()

        def slow():
            calls()
            started.set()
            release.wait(1)

        with self.assertRaises(TaskTimeoutError) as raised:
            manager.execute("slow", slow)

        self.assertTrue(started.is_set())
        self.assertTrue(raised.exception.task_still_running)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(manager.stats["non_recoverable"], 1)
        self.assertEqual(monitor.summary()["timeout"], 1)
        release.set()

    def test_timeout_retry_requires_explicit_concurrency_permission(self):
        manager, monitor = self._manager(
            max_retries=1, task_timeout_s=0.02, backoff_base_s=0,
        )
        lock = threading.Lock()
        state = {"calls": 0, "active": 0, "max_active": 0}
        release_first = threading.Event()
        first_finished = threading.Event()

        def concurrency_safe_task():
            with lock:
                state["calls"] += 1
                call = state["calls"]
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                if call == 1:
                    release_first.wait(1)
                    first_finished.set()
                    raise ConnectionError("first attempt ended after timeout")
                return "second attempt"
            finally:
                with lock:
                    state["active"] -= 1

        with patch("recovery.time.sleep"):
            result = manager.execute(
                "concurrent-safe", concurrency_safe_task, allow_timeout_retry=True,
            )

        self.assertEqual(result, "second attempt")
        release_first.set()
        self.assertTrue(first_finished.wait(1))
        self.assertEqual(state["calls"], 2)
        self.assertEqual(state["max_active"], 2)
        self.assertEqual(manager.stats["recovered"], 1)
        self.assertEqual(monitor.summary()["timeout"], 1)

    def test_invalid_retry_configuration_is_rejected(self):
        for values in (
            {"max_retries": -1},
            {"max_retries": 1.5},
            {"backoff_base_s": -0.1},
            {"backoff_factor": 0.5},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self._manager(**values)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch("scheduler.get_logger", return_value=Mock())
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def test_due_jobs_run_once_and_failures_do_not_stop_other_jobs(self):
        scheduler = Scheduler()
        results = []
        successful = scheduler.add_job("success", lambda: results.append("ok"), 10)
        failed = scheduler.add_job("failure", lambda: (_ for _ in ()).throw(ValueError("boom")), 10)

        scheduler.run_pending()

        self.assertEqual(results, ["ok"])
        self.assertEqual(successful.runs, 1)
        self.assertEqual(failed.runs, 1)
        self.assertGreater(successful.next_run, time.time() - 1)

    def test_job_cancellation_removes_pending_job_and_reports_missing_job(self):
        scheduler = Scheduler()
        results = []
        scheduler.add_job("pending", lambda: results.append("ran"), 10, run_immediately=False)

        self.assertTrue(scheduler.cancel_job("pending"))
        self.assertFalse(scheduler.cancel_job("pending"))
        scheduler.run_pending()
        self.assertEqual(results, [])

    def test_invalid_job_registration_and_loop_arguments_are_rejected(self):
        scheduler = Scheduler()
        for interval in (0, -1, float("inf"), True, "5"):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                scheduler.add_job("invalid", lambda: None, interval)
        with self.assertRaises(TypeError):
            scheduler.add_job("invalid-callable", None, 1)
        scheduler.add_job("valid", lambda: None, 1)
        with self.assertRaises(ValueError):
            scheduler.add_job("valid", lambda: None, 1)
        with self.assertRaises(ValueError):
            scheduler.run(max_cycles=-1)
        with self.assertRaises(ValueError):
            scheduler.run(tick_s=-1)

    def test_stop_prevents_scheduler_loop_from_starting_jobs(self):
        scheduler = Scheduler()
        results = []
        scheduler.add_job("stopped", lambda: results.append("ran"), 1)
        scheduler.stop()

        scheduler.run(max_cycles=1, tick_s=0)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
