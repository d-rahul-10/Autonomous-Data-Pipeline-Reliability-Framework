import atexit
from contextlib import closing
import io
import json
import logging
import os
import sqlite3
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

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
from app.config import AppConfig
from app.db import init_db
from app.repositories.schedule import ScheduleRepository
from app.services.scheduler import SchedulerService
from app.services.analysis import AnalysisService


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


def _authenticate_test_client(client, name="API Test"):
    """Create a real, short-lived DB session for protected API tests."""
    user_id = time.time_ns()
    session_id = f"test-{user_id}"
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect("pipeline_state.sqlite3")) as db:
        db.execute(
            "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, f"api-{user_id}@example.com", "unused", now.isoformat()),
        )
        db.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, now.isoformat(), (now + timedelta(hours=1)).isoformat()),
        )
        db.commit()
    with client.session_transaction() as auth_session:
        auth_session["user_id"] = user_id
        auth_session["session_id"] = session_id
        auth_session["user_name"] = name
        auth_session["user_email"] = f"api-{user_id}@example.com"
        auth_session["csrf_token"] = "test-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf-token"


class ApplicationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        self.client.get("/auth")
        with self.client.session_transaction() as auth_session:
            self.client.environ_base["HTTP_X_CSRF_TOKEN"] = auth_session["csrf_token"]

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

    def test_signup_login_logout_and_dashboard_redirects(self):
        email = f"pipeline-test-{time.time_ns()}@example.com"
        signup = self.client.post("/api/auth/signup", json={
            "name": "Pipeline Test",
            "email": email,
            "password": "TestPassword123",
        })
        self.assertEqual(signup.status_code, 200, signup.get_json())
        self.assertEqual(signup.get_json()["redirect"], "/")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/auth").status_code, 302)

        with self.client.session_transaction() as auth_session:
            csrf_token = auth_session["csrf_token"]
        logout = self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
        self.assertEqual(logout.status_code, 200, logout.get_json())
        self.assertEqual(self.client.get("/").status_code, 302)
        self.client.get("/auth")
        with self.client.session_transaction() as auth_session:
            self.client.environ_base["HTTP_X_CSRF_TOKEN"] = auth_session["csrf_token"]

        login = self.client.post("/api/auth/login", json={
            "email": email,
            "password": "TestPassword123",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(self.client.get("/").status_code, 200)
        with self.client.session_transaction() as auth_session:
            self.assertNotEqual(auth_session.get("csrf_token"), csrf_token)

        bad_login_client = flask_app.test_client()
        bad_login_client.get("/auth")
        with bad_login_client.session_transaction() as auth_session:
            bad_login_client.environ_base["HTTP_X_CSRF_TOKEN"] = auth_session["csrf_token"]
        bad_login = bad_login_client.post("/api/auth/login", json={
            "email": email,
            "password": "incorrect",
        })
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(bad_login_client.get("/").status_code, 302)

    def test_auth_rejects_malformed_and_oversized_fields(self):
        malformed = self.client.post("/api/auth/signup", json={
            "name": [], "email": "bad@example.com", "password": "Password123",
        })
        oversized = self.client.post("/api/auth/signup", json={
            "name": "Test User", "email": "long@example.com", "password": "A1a" + "x" * 300,
        })
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(oversized.status_code, 400)

    def test_login_and_signup_require_csrf_token(self):
        anonymous = flask_app.test_client()
        response = anonymous.post("/api/auth/signup", json={
            "name": "Secure Test", "email": "secure@example.com", "password": "Password123",
        })
        self.assertEqual(response.status_code, 403)

    def test_state_changing_dashboard_api_rejects_missing_csrf_token(self):
        _authenticate_test_client(self.client)
        response = self.client.post("/api/schedule", json={
            "enabled": False, "interval_seconds": 60, "rows": 1000,
        }, headers={"X-CSRF-Token": "wrong-token"})
        self.assertEqual(response.status_code, 403)

    def test_auth_page_has_no_broken_social_auth_target(self):
        response = self.client.get("/auth")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"/api/auth/social/", response.data)

    def test_dashboard_api_requires_a_live_authenticated_session(self):
        anonymous = flask_app.test_client()
        self.assertEqual(anonymous.get("/api/status").status_code, 401)
        self.assertEqual(anonymous.post("/api/analyze", data={"rows": "1000"}).status_code, 401)
        _authenticate_test_client(self.client)
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        with self.client.session_transaction() as auth_session:
            auth_session["session_id"] = "revoked-session"
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.get("/").headers["Location"], "/auth")
        self.assertEqual(self.client.get("/auth").status_code, 200)

    def test_airflow_endpoints_require_session_and_retry_requires_csrf(self):
        anonymous = flask_app.test_client()
        self.assertEqual(anonymous.get("/api/airflow").status_code, 401)
        self.assertEqual(anonymous.post("/api/airflow/retry").status_code, 401)

        _authenticate_test_client(self.client)
        recovery = flask_app.config["AIRFLOW_RECOVERY"]
        with patch.object(recovery, "inspect", return_value={
            "status": {"configured": False, "ready_for_automation": False},
            "failed_tasks": [],
        }):
            response = self.client.get("/api/airflow")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["status"]["configured"])

        bad_csrf = self.client.post("/api/airflow/retry", headers={"X-CSRF-Token": "wrong-token"})
        self.assertEqual(bad_csrf.status_code, 403)

    def test_dashboard_renders_airflow_monitor_targets(self):
        _authenticate_test_client(self.client)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        for element_id in ("airflow-status", "airflow-config-note", "airflow-failures", "airflow-events"):
            self.assertIn(f'id="{element_id}"', page)

    def test_security_headers_are_present(self):
        response = self.client.get("/auth")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("csrf-token", response.get_data(as_text=True))

    def test_healthcheck_returns_only_readiness(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_dashboard_and_read_endpoints(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/auth")
        self.assertEqual(self.client.get("/auth").status_code, 200)
        self.assertEqual(self.client.get("/login").headers["Location"], "/auth#login")
        self.assertEqual(self.client.get("/signup").headers["Location"], "/auth#signup")

        _authenticate_test_client(self.client, name="Avery Pipeline")
        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"PipelineIQ", dashboard.data)
        self.assertIn(b"Avery Pipeline", dashboard.data)
        self.assertIn(b'id="logout-button"', dashboard.data)
        static_response = self.client.get("/static/app.js")
        try:
            self.assertEqual(static_response.status_code, 200)
        finally:
            static_response.close()

        _authenticate_test_client(self.client)

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
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/json")

    def test_analysis_persists_history_and_downloadable_reports(self):
        _authenticate_test_client(self.client)
        response = self.client.post("/api/analyze", data={"rows": "1000"})

        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.assertGreaterEqual(result["rows_clean"], 200)
        self.assertEqual(result["failures"]["records"], result["rows_clean"])
        self.assertTrue(result["top_risk"])
        self.assertTrue(all("duration_threshold" in risk for risk in result["top_risk"]))
        self.assertTrue(all(0 <= risk["risk"] <= 1 for risk in result["top_risk"]))
        self.assertTrue(result["report_file"].startswith("report_"))
        report_response = self.client.get("/api/reports/" + result["report_file"])
        try:
            self.assertEqual(report_response.status_code, 200)
        finally:
            report_response.close()

        history = self.client.get("/api/history").get_json()["history"]
        self.assertEqual(history[0]["generated_at"], result["generated_at"])
        self.assertEqual(
            self.client.get("/api/status").get_json()["latest_analysis"]["generated_at"],
            result["generated_at"],
        )

    def test_invalid_analysis_inputs_return_client_errors(self):
        _authenticate_test_client(self.client)
        invalid_rows = self.client.post("/api/analyze", data={"rows": "many"})
        self.assertEqual(invalid_rows.status_code, 400)

        invalid_csv = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"not,a,pipeline,csv\n1,2,3,4\n"), "logs.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid_csv.status_code, 400)

        invalid_extension = self.client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"data"), "logs.txt")},
            content_type="multipart/form-data",
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
        _authenticate_test_client(self.client)
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
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not in the ETL pipeline-log format", response.get_json()["error"])
        self.assertIn("timestamp", response.get_json()["error"])
        self.assertIn("Country Name", response.get_json()["error"])

    def test_request_size_limit_returns_413(self):
        _authenticate_test_client(self.client)
        original_limit = flask_app.config["MAX_CONTENT_LENGTH"]
        flask_app.config["MAX_CONTENT_LENGTH"] = 32
        try:
            response = self.client.post(
                "/api/analyze",
                data=b"x" * 64,
                content_type="application/octet-stream",
            )
        finally:
            flask_app.config["MAX_CONTENT_LENGTH"] = original_limit

        self.assertEqual(response.status_code, 413)

    def test_scheduler_rejects_non_object_json_and_invalid_values(self):
        _authenticate_test_client(self.client)
        non_object = self.client.post("/api/schedule", json=["not", "an object"])
        self.assertEqual(non_object.status_code, 400)

        invalid_interval = self.client.post(
            "/api/schedule",
            json={"enabled": False, "interval_seconds": 1, "rows": 1000},
        )
        self.assertEqual(invalid_interval.status_code, 400)
        fractional_interval = self.client.post(
            "/api/schedule",
            json={"enabled": False, "interval_seconds": 15.5, "rows": 1000},
        )
        self.assertEqual(fractional_interval.status_code, 400)
        invalid_enabled = self.client.post(
            "/api/schedule",
            json={"enabled": "sometimes", "interval_seconds": 15, "rows": 1000},
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
        )
        self.assertEqual(valid.status_code, 200, valid.get_json())
        self.assertFalse(valid.get_json()["schedule"]["enabled"])

    def test_scheduled_csv_upload_and_rejection(self):
        _authenticate_test_client(self.client)
        csv_content = generate_logs(300).to_csv(index=False).encode("utf-8")
        uploaded = self.client.post(
            "/api/schedule/datasets",
            data={"file": (io.BytesIO(csv_content), "pipeline.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())

        datasets = self.client.get("/api/schedule/datasets").get_json()["datasets"]
        self.assertIn("pipeline.csv", [dataset["name"] for dataset in datasets])

        invalid = self.client.post(
            "/api/schedule/datasets",
            data={"file": (io.BytesIO(b"bad"), "pipeline.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_recovery_demo_executes_retry_workflow(self):
        _authenticate_test_client(self.client)
        response = self.client.post("/api/recovery-demo")

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
        _authenticate_test_client(self.client)
        with patch("main.demo_live_pipeline", side_effect=RuntimeError("C:\\private\\secret.csv")):
            response = self.client.post("/api/recovery-demo")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"],
            "Recovery demo failed due to an internal server error.",
        )
        self.assertNotIn("secret.csv", response.get_data(as_text=True))


class SchedulerServiceTests(unittest.TestCase):
    """Unit tests for SchedulerService, independent of Flask and timing loops."""

    def setUp(self):
        self.temp_root = TemporaryDirectory(prefix="pipeline-scheduler-service-tests-")
        self.db_path = Path(self.temp_root.name) / "state.sqlite3"
        self.data_dir = Path(self.temp_root.name) / "incoming"
        self.data_dir.mkdir()

        base = AppConfig.from_env()
        self.config = SimpleNamespace(
            state_db_path=self.db_path,
            schedule_data_dir=self.data_dir,
            min_interval_seconds=15,
            max_interval_seconds=604800,
            min_sample_rows=1000,
            max_sample_rows=500_000,
        )
        init_db(AppConfig.from_env())  # ensure schema on the default path too
        init_db_for_path(self.config)

        self.schedule_repo = ScheduleRepository(_config_for_path(self.config))
        self.analysis_service = Mock(spec=AnalysisService)
        self.scheduler = SchedulerService(
            config=self.config,
            analysis_service=self.analysis_service,
            schedule_repository=self.schedule_repo,
            data_dir=self.data_dir,
        )

    def tearDown(self):
        self.scheduler.stop()
        try:
            self.temp_root.cleanup()
        except PermissionError:
            pass  # Windows may briefly hold SQLite WAL file locks after connections close

    def _persist_raw(self, key: str, value: str):
        with closing(sqlite3.connect(str(self.config.state_db_path), timeout=30)) as db:
            db.execute("PRAGMA busy_timeout = 30000")
            db.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            db.commit()

    def test_configure_valid_sample_schedule(self):
        state = self.scheduler.configure(
            enabled=True, interval_seconds=60, rows=1000,
            source_type="sample", dataset_name="",
        )
        self.assertTrue(state["enabled"])
        self.assertEqual(state["interval_seconds"], 60)
        self.assertEqual(state["rows"], 1000)
        self.assertEqual(state["source_type"], "sample")
        self.assertIsNotNone(state["next_run"])
        self.assertTrue(state["next_run"].endswith("+00:00"))
        row = self.schedule_repo.get()
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row["value"])["runs"], 0)

    def test_configure_rejects_invalid_interval(self):
        with self.assertRaisesRegex(Exception, "interval"):
            self.scheduler.configure(
                enabled=True, interval_seconds=1, rows=1000,
                source_type="sample", dataset_name="",
            )

    def test_configure_rejects_invalid_rows(self):
        with self.assertRaisesRegex(Exception, "sample size"):
            self.scheduler.configure(
                enabled=True, interval_seconds=60, rows=99,
                source_type="sample", dataset_name="",
            )

    def test_configure_csv_requires_existing_dataset(self):
        with self.assertRaisesRegex(Exception, "not available"):
            self.scheduler.configure(
                enabled=True, interval_seconds=60, rows=1000,
                source_type="csv", dataset_name="missing.csv",
            )

    def test_get_state_converts_next_run_to_iso(self):
        self.scheduler.configure(enabled=False, interval_seconds=60, rows=1000,
                                 source_type="sample", dataset_name="")
        with self.scheduler._lock:
            self.scheduler._schedule["next_run"] = time.time() + 100
        state = self.scheduler.get_state()
        self.assertTrue(state["next_run"].endswith("+00:00") or "T" in state["next_run"])

    def test_load_persisted_restores_overdue_schedule(self):
        overdue = time.time() - 120
        self._persist_raw("schedule", json.dumps({
            "enabled": True, "interval_seconds": 15, "rows": 1000,
            "source_type": "sample", "dataset_name": "",
            "next_run": overdue, "last_run": None, "last_error": None, "runs": 4,
        }))
        with patch("app.services.scheduler.threading.Thread") as thread_factory:
            self.scheduler.load_persisted()
        self.assertLess(self.scheduler._schedule["next_run"], time.time())
        self.assertEqual(self.scheduler._schedule["runs"], 4)
        thread_factory.assert_called_once()
        thread_factory.return_value.start.assert_called_once_with()

    def test_load_persisted_malformed_uses_safe_defaults(self):
        self._persist_raw("schedule", "not-json")
        self.scheduler._schedule = self.scheduler._defaults()
        self.scheduler._version = 0
        self.scheduler._scheduler_thread = None
        with patch("app.services.scheduler.threading.Thread") as thread_factory:
            self.scheduler.load_persisted()
        self.assertFalse(self.scheduler._schedule["enabled"])
        self.assertEqual(self.scheduler._schedule["interval_seconds"], 3600)
        thread_factory.assert_not_called()

    def test_run_due_executes_analysis_once_and_persists(self):
        self.scheduler._schedule = self.scheduler._defaults()
        self.scheduler._schedule["enabled"] = True
        self.scheduler._version = 1
        self.analysis_service.analyze = Mock(return_value={})
        with patch("pipeline_core._read_pipeline_csv", return_value=pd.DataFrame()), \
             patch("synthetic_data.generate_logs", return_value=pd.DataFrame()):
            self.scheduler._run_due(self.scheduler._version, 1000, "sample", "")
        self.analysis_service.analyze.assert_called_once()
        self.assertEqual(self.scheduler._schedule["runs"], 1)
        self.assertIsNone(self.scheduler._schedule["last_error"])
        self.assertGreater(self.scheduler._schedule["next_run"], time.time())

    def test_run_due_records_error_when_analysis_fails(self):
        self.scheduler._schedule = self.scheduler._defaults()
        self.scheduler._schedule["enabled"] = True
        self.scheduler._version = 1
        self.analysis_service.analyze = Mock(side_effect=RuntimeError("boom"))
        from pipeline_core import _read_pipeline_csv
        with patch("pipeline_core._read_pipeline_csv", return_value=pd.DataFrame()), \
             patch("synthetic_data.generate_logs", return_value=pd.DataFrame()):
            self.scheduler._run_due(self.scheduler._version, 1000, "sample", "")
        self.assertEqual(self.scheduler._schedule["runs"], 1)
        self.assertIn("RuntimeError: boom", self.scheduler._schedule["last_error"])

    def test_run_due_respects_version_change(self):
        self.scheduler._schedule = self.scheduler._defaults()
        self.scheduler._schedule["enabled"] = True
        self.scheduler._version = 1
        self.analysis_service.analyze = Mock(return_value={})
        with patch("pipeline_core._read_pipeline_csv", return_value=pd.DataFrame()), \
             patch("synthetic_data.generate_logs", return_value=pd.DataFrame()):
            self.scheduler._run_due(999, 1000, "sample", "")  # stale version
        self.analysis_service.analyze.assert_not_called()


def init_db_for_path(config):
    from app.db import transaction, SCHEMA
    with transaction(config) as connection:
        connection.executescript(SCHEMA)


def _config_for_path(config):
    from app.config import AppConfig
    base = AppConfig.from_env()
    return AppConfig(
        env=base.env, production=base.production, testing=True, debug=False,
        secret_key=base.secret_key, host=base.host, port=base.port,
        state_db_path=config.state_db_path,
        schedule_data_dir=config.schedule_data_dir,
        report_dir=base.report_dir, log_file=base.log_file,
        model_path=base.model_path, max_content_length=base.max_content_length,
        session_cookie_secure=base.session_cookie_secure,
        session_cookie_samesite=base.session_cookie_samesite,
        permanent_session_lifetime=base.permanent_session_lifetime,
        analysis_history_limit=base.analysis_history_limit,
        min_clean_rows=base.min_clean_rows,
        min_sample_rows=base.min_sample_rows,
        max_sample_rows=base.max_sample_rows,
        min_interval_seconds=base.min_interval_seconds,
        max_interval_seconds=base.max_interval_seconds,
    )


if __name__ == "__main__":
    unittest.main()
