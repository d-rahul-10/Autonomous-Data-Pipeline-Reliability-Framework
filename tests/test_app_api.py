import atexit
import io
import json
import logging
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_CWD = Path.cwd()
_TEST_ROOT = TemporaryDirectory(prefix="pipeline-api-tests-")
os.chdir(_TEST_ROOT.name)
sys.path.insert(0, str(_PROJECT_ROOT))

from app import _json_default, app as flask_app
from main import build_config
from pipeline_core import _read_pipeline_csv
from synthetic_data import generate_logs


def _cleanup_test_environment():
    os.chdir(_ORIGINAL_CWD)
    for name in ("main", "monitor", "recovery"):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
    _TEST_ROOT.cleanup()


atexit.register(_cleanup_test_environment)
flask_app.config.update(TESTING=True)


class ApplicationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        self._auth_token = self._get_auth_token()

    def _get_auth_token(self):
        """Sign up a test user and return the JWT token."""
        # Use a unique email to avoid conflicts
        import uuid
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        response = self.client.post("/api/auth/signup", json={
            "email": email,
            "password": "password123",
            "confirm_password": "password123"
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["token"]

    def _auth_headers(self):
        """Return headers with Authorization Bearer token."""
        return {"Authorization": f"Bearer {self._auth_token}"}

    def test_json_default_serializes_numpy_values_and_timestamps(self):
        payload = {
            "count": np.int64(4),
            "generated_at": pd.Timestamp("2025-01-02T03:04:05Z"),
            "fallback": object(),
        }

        encoded = json.dumps(payload, default=_json_default)

        self.assertEqual(
            json.loads(encoded),
            {
                "count": 4,
                "generated_at": "2025-01-02T03:04:05+00:00",
                "fallback": str(payload["fallback"]),
            },
        )

    def test_dashboard_and_read_endpoints(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        static_response = self.client.get("/static/app.js")
        try:
            self.assertEqual(static_response.status_code, 200)
        finally:
            static_response.close()

        for endpoint in (
            "/api/status",
            "/api/history",
            "/api/reports",
            "/api/logs",
            "/api/monitor",
            "/api/schedule",
            "/api/schedule/datasets",
        ):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint, headers=self._auth_headers())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/json")

    def test_analysis_persists_history_and_downloadable_reports(self):
        response = self.client.post("/api/analyze", data={"rows": "1000"}, headers=self._auth_headers())

        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.assertGreaterEqual(result["rows_clean"], 200)
        self.assertEqual(result["failures"]["records"], result["rows_clean"])
        self.assertTrue(result["report_file"].startswith("report_"))
        report_response = self.client.get("/api/reports/" + result["report_file"], headers=self._auth_headers())
        try:
            self.assertEqual(report_response.status_code, 200)
        finally:
            report_response.close()

        history = self.client.get("/api/history", headers=self._auth_headers()).get_json()["history"]
        self.assertEqual(history[0]["generated_at"], result["generated_at"])
        self.assertEqual(
            self.client.get("/api/status", headers=self._auth_headers()).get_json()["latest_analysis"]["generated_at"],
            result["generated_at"],
        )

    def test_invalid_analysis_inputs_return_client_errors(self):
        invalid_rows = self.client.post("/api/analyze", data={"rows": "many"}, headers=self._auth_headers())
        self.assertEqual(invalid_rows.status_code, 400)

        invalid_csv = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"not,a,pipeline,csv\n1,2,3,4\n"), "logs.csv")},
            content_type="multipart/form-data",
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid_csv.status_code, 400)

        invalid_extension = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"data"), "logs.txt")},
            content_type="multipart/form-data",
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid_extension.status_code, 400)

    def test_csv_reader_skips_metadata_before_pipeline_table(self):
        frame = generate_logs(250)
        metadata = "Report,Population,Source\nGenerated,2026,Example\n,,\nExport,CSV,1\n"
        csv_content = metadata + frame.to_csv(index=False)

        parsed = _read_pipeline_csv(
            io.BytesIO(csv_content.encode("utf-8")),
            build_config(),
            check_clean_rows=False,
        )

        self.assertEqual(len(parsed), len(frame))
        self.assertEqual(list(parsed.columns[:8]), list(frame.columns[:8]))

    def test_population_csv_reports_unsupported_dataset_after_parsing(self):
        columns = [f"year_{year}" for year in range(1960, 2023)]
        header = ["Country Name", "Country Code", "Indicator Name", "Indicator Code", *columns]
        records = [
            ["Example", "EX", "Population", "SP.POP", *([100] * len(columns))],
            ["Example 2", "EX2", "Population", "SP.POP", *([200] * len(columns))],
        ]
        csv_content = (
            "Report,Population,Source\nGenerated,2026,Example\n,,\nExport,CSV,1\n"
            + pd.DataFrame(records, columns=header).to_csv(index=False)
        )

        response = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(csv_content.encode("utf-8")), "population_data.csv")},
            content_type="multipart/form-data",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not in the ETL pipeline-log format", response.get_json()["error"])
        self.assertIn("timestamp", response.get_json()["error"])
        self.assertIn("Country Name", response.get_json()["error"])

    def test_request_size_limit_returns_413(self):
        original_limit = flask_app.config["MAX_CONTENT_LENGTH"]
        flask_app.config["MAX_CONTENT_LENGTH"] = 32
        try:
            response = self.client.post(
                "/api/analyze",
                data=b"x" * 64,
                content_type="application/octet-stream",
                headers=self._auth_headers(),
            )
        finally:
            flask_app.config["MAX_CONTENT_LENGTH"] = original_limit

        self.assertEqual(response.status_code, 413)

    def test_scheduler_rejects_non_object_json_and_invalid_values(self):
        non_object = self.client.post("/api/schedule", json=["not", "an object"], headers=self._auth_headers())
        self.assertEqual(non_object.status_code, 400)

        invalid_interval = self.client.post(
            "/api/schedule",
            json={"enabled": False, "interval_seconds": 1, "rows": 1000},
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid_interval.status_code, 400)
        fractional_interval = self.client.post(
            "/api/schedule",
            json={"enabled": False, "interval_seconds": 15.5, "rows": 1000},
            headers=self._auth_headers(),
        )
        self.assertEqual(fractional_interval.status_code, 400)
        invalid_enabled = self.client.post(
            "/api/schedule",
            json={"enabled": "sometimes", "interval_seconds": 15, "rows": 1000},
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid_enabled.status_code, 400)
        missing_dataset = self.client.post(
            "/api/schedule",
            json={
                "enabled": True,
                "interval_seconds": 15,
                "rows": 1000,
                "source_type": "csv",
                "dataset_name": "missing.csv",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(missing_dataset.status_code, 400)

        valid = self.client.post(
            "/api/schedule",
            json={
                "enabled": False,
                "interval_seconds": 15,
                "rows": 1000,
                "source_type": "sample",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(valid.status_code, 200, valid.get_json())
        self.assertFalse(valid.get_json()["schedule"]["enabled"])

    def test_scheduled_csv_upload_and_rejection(self):
        csv_content = generate_logs(300).to_csv(index=False).encode("utf-8")
        uploaded = self.client.post(
            "/api/schedule/datasets",
            data={"file": (io.BytesIO(csv_content), "pipeline.csv")},
            content_type="multipart/form-data",
            headers=self._auth_headers(),
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())

        datasets = self.client.get("/api/schedule/datasets", headers=self._auth_headers()).get_json()["datasets"]
        self.assertIn("pipeline.csv", [dataset["name"] for dataset in datasets])

        invalid = self.client.post(
            "/api/schedule/datasets",
            data={"file": (io.BytesIO(b"bad"), "pipeline.txt")},
            content_type="multipart/form-data",
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid.status_code, 400)

    def test_recovery_demo_executes_retry_workflow(self):
        response = self.client.post("/api/recovery-demo", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200, response.get_json())
        result = json.loads(response.get_data(as_text=True), parse_constant=self._reject_json_constant)
        self.assertEqual(result["rows_loaded"], 100)
        self.assertGreaterEqual(result["recovery"]["recovered"], 1)
        self.assertEqual(result["recovery"]["non_recoverable"], 0)
        self.assertGreater(result["monitor"]["total_runs"], 0)
        successful_records = [record for record in result["records"] if record["status"] == "SUCCESS"]
        self.assertTrue(successful_records)
        self.assertTrue(all(record["error_msg"] is None for record in successful_records))
        self.assertTrue(all(record["error_type"] is None for record in successful_records))

    @staticmethod
    def _reject_json_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def test_recovery_demo_redacts_internal_errors(self):
        with patch("app.demo_live_pipeline", side_effect=RuntimeError("C:\\private\\secret.csv")):
            response = self.client.post("/api/recovery-demo", headers=self._auth_headers())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"],
            "Recovery demo failed due to an internal server error.",
        )
        self.assertNotIn("secret.csv", response.get_data(as_text=True))


class ApplicationSchedulerTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.client = application.app.test_client()
        self.temp_root = TemporaryDirectory(prefix="pipeline-scheduler-tests-", dir=_TEST_ROOT.name)
        self.original_paths = {
            key: application.app.config[key]
            for key in ("STATE_DB_PATH", "SCHEDULE_DATA_DIR")
        }
        self.original_schedule = dict(application._schedule)
        self.original_version = application._schedule_version
        self.original_thread = application._scheduler_thread
        self.original_history = list(application._analysis_history)
        self.original_latest = application._latest_analysis
        self.original_recovery = application._latest_recovery

        old_thread = application._scheduler_thread
        with application._state_lock:
            application._schedule["enabled"] = False
            application._schedule["next_run"] = None
        if isinstance(old_thread, threading.Thread) and old_thread.is_alive():
            old_thread.join(timeout=2)

        root = Path(self.temp_root.name)
        application.app.config["STATE_DB_PATH"] = root / "state.sqlite3"
        application.app.config["SCHEDULE_DATA_DIR"] = root / "incoming"
        application.app.config["SCHEDULE_DATA_DIR"].mkdir()
        application._scheduler_thread = None
        application._schedule_version = 0
        application._analysis_history.clear()
        application._latest_analysis = None
        application._latest_recovery = None
        with application._state_lock:
            application._schedule.update({
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
            })
        with application._state_connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS analysis_history "
                "(generated_at TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
        
        # Get auth token for tests
        self._auth_token = self._get_auth_token()

    def _get_auth_token(self):
        """Sign up a test user and return the JWT token."""
        import uuid
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        response = self.client.post("/api/auth/signup", json={
            "email": email,
            "password": "password123",
            "confirm_password": "password123"
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["token"]

    def _auth_headers(self):
        """Return headers with Authorization Bearer token."""
        return {"Authorization": f"Bearer {self._auth_token}"}

    def tearDown(self):
        application = self.application
        with application._state_lock:
            application._schedule["enabled"] = False
            application._schedule["next_run"] = None
        thread = application._scheduler_thread
        if isinstance(thread, threading.Thread) and thread.is_alive():
            thread.join(timeout=3)
        application._scheduler_thread = None
        application.app.config.update(self.original_paths)
        application._schedule.clear()
        application._schedule.update(self.original_schedule)
        application._schedule_version = self.original_version
        application._analysis_history[:] = self.original_history
        application._latest_analysis = self.original_latest
        application._latest_recovery = self.original_recovery
        self.temp_root.cleanup()

    def _enable_schedule(self):
        response = self.client.post("/api/schedule", json={
            "enabled": True,
            "interval_seconds": 15,
            "rows": 1000,
            "source_type": "sample",
        }, headers=self._auth_headers())
        self.assertEqual(response.status_code, 200, response.get_json())

    def _disable_schedule(self):
        response = self.client.post("/api/schedule", json={
            "enabled": False,
            "interval_seconds": 15,
            "rows": 1000,
            "source_type": "sample",
        }, headers=self._auth_headers())
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_restart_restores_overdue_schedule_without_losing_due_timestamp(self):
        application = self.application
        overdue_timestamp = time.time() - 120
        saved = {
            "enabled": True,
            "interval_seconds": 15,
            "rows": 1000,
            "source_type": "sample",
            "dataset_name": "",
            "next_run": overdue_timestamp,
            "last_run": None,
            "last_error": None,
            "runs": 4,
        }
        with application._state_connection() as db:
            db.execute(
                "INSERT INTO app_state (key, value) VALUES ('schedule', ?)",
                (json.dumps(saved),),
            )
            db.execute(
                "INSERT INTO analysis_history (generated_at, payload) VALUES (?, ?)",
                ("2026-10-08T00:00:00+00:00", json.dumps({"generated_at": "2026-10-08T00:00:00+00:00"})),
            )

        with patch("app.threading.Thread") as thread_factory:
            application._load_persistent_state()

        self.assertLess(application._schedule["next_run"], time.time())
        self.assertEqual(application._schedule["runs"], 4)
        self.assertEqual(len(application._analysis_history), 1)
        thread_factory.assert_called_once()
        thread_factory.return_value.start.assert_called_once_with()

    def test_malformed_or_invalid_persisted_schedule_uses_safe_defaults(self):
        application = self.application
        for saved_value in ("[]", json.dumps({"enabled": True, "interval_seconds": -1})):
            with self.subTest(saved_value=saved_value):
                with application._state_connection() as db:
                    db.execute(
                        "INSERT INTO app_state (key, value) VALUES ('schedule', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (saved_value,),
                    )
                application._schedule.update({
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
                })
                application._scheduler_thread = None
                with patch("app.threading.Thread") as thread_factory:
                    application._load_persistent_state()

                self.assertFalse(application._schedule["enabled"])
                self.assertEqual(application._schedule["interval_seconds"], 3600)
                thread_factory.assert_not_called()

    def test_scheduler_runs_overdue_job_once_persists_result_and_stops_when_disabled(self):
        application = self.application
        completed = threading.Event()

        def fake_analysis(*_args):
            completed.set()
            return {}

        with patch("app._analyze_dataframe", side_effect=fake_analysis) as analyze:
            self._enable_schedule()
            with application._state_lock:
                application._schedule["next_run"] = time.time() - 1

            self.assertTrue(completed.wait(5), "the due scheduled job did not execute")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with application._state_lock:
                    if application._schedule["runs"] == 1 and not application._schedule["running"]:
                        break
                time.sleep(0.01)

            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(application._schedule["runs"], 1)
            self.assertIsNone(application._schedule["last_error"])
            self.assertGreater(application._schedule["next_run"], time.time())
            with application._state_connection() as db:
                saved = db.execute(
                    "SELECT value FROM app_state WHERE key = 'schedule'"
                ).fetchone()
            self.assertEqual(json.loads(saved[0])["runs"], 1)

        thread = application._scheduler_thread
        self._disable_schedule()
        if isinstance(thread, threading.Thread):
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive(), "disabled scheduler thread should exit")
        self.assertIsNone(application._scheduler_thread)

    def test_scheduler_records_failure_then_recovers_on_a_later_run(self):
        application = self.application
        first_run = threading.Event()
        second_run = threading.Event()
        calls = []
        active = {"count": 0, "max": 0}
        active_lock = threading.Lock()

        def failing_then_successful(*_args):
            with active_lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            try:
                calls.append(len(calls) + 1)
                if len(calls) == 1:
                    first_run.set()
                    raise RuntimeError("isolated source failure")
                second_run.set()
            finally:
                with active_lock:
                    active["count"] -= 1

        with patch("app._analyze_dataframe", side_effect=failing_then_successful):
            self._enable_schedule()
            with application._state_lock:
                application._schedule["next_run"] = time.time() - 1

            self.assertTrue(first_run.wait(5), "the first scheduled attempt did not execute")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with application._state_lock:
                    if application._schedule["runs"] == 1 and application._schedule["last_error"]:
                        break
                time.sleep(0.01)
            self.assertEqual(application._schedule["runs"], 1)
            self.assertIn("RuntimeError: isolated source failure", application._schedule["last_error"])

            with application._state_lock:
                application._schedule["next_run"] = time.time() - 1
            self.assertTrue(second_run.wait(5), "the later scheduled attempt did not execute")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with application._state_lock:
                    if application._schedule["runs"] == 2 and not application._schedule["running"]:
                        break
                time.sleep(0.01)

            self.assertEqual(calls, [1, 2])
            self.assertEqual(active["max"], 1)
            self.assertEqual(application._schedule["runs"], 2)
            self.assertIsNone(application._schedule["last_error"])

        thread = application._scheduler_thread
        self._disable_schedule()
        if isinstance(thread, threading.Thread):
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_disabling_schedule_cancels_due_job_waiting_for_analysis_lock(self):
        application = self.application
        application._analysis_lock.acquire()
        try:
            with patch("app._analyze_dataframe") as analyze:
                self._enable_schedule()
                with application._state_lock:
                    application._schedule["next_run"] = time.time() - 1
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with application._state_lock:
                        if application._schedule["running"]:
                            break
                    time.sleep(0.01)
                self.assertTrue(application._schedule["running"], "scheduled job was not dispatched")

                thread = application._scheduler_thread
                self._disable_schedule()
                application._analysis_lock.release()
                thread.join(timeout=3)

                analyze.assert_not_called()
                self.assertEqual(application._schedule["runs"], 0)
                self.assertFalse(thread.is_alive())
        finally:
            if application._analysis_lock.locked():
                application._analysis_lock.release()


if __name__ == "__main__":
    unittest.main()
