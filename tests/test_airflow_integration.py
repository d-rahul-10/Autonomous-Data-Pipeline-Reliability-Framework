import json
import base64
import unittest
from dataclasses import replace
import time

from airflow_integration import AirflowClient, AirflowError, AirflowRecoveryService, AirflowSettings


def settings(**changes):
    base = AirflowSettings(
        base_url="https://airflow.example.test", api_version="v1", auth_type="basic",
        username="pipeline", password="secret", token="", dag_allowlist=("approved_dag",),
        task_allowlist=("approved_task",), auto_retry_enabled=True, poll_seconds=60,
        max_retries=1, request_timeout=10,
    )
    return replace(base, **changes)


class Response:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit=-1):
        return self._data


class AirflowIntegrationTests(unittest.TestCase):
    def test_configuration_requires_allowlists_for_automation(self):
        self.assertTrue(settings().ready_for_automation)
        self.assertFalse(settings(task_allowlist=()).ready_for_automation)
        self.assertFalse(settings(dag_allowlist=()).ready_for_automation)
        self.assertFalse(settings(auto_retry_enabled=False).ready_for_automation)

    def test_requires_https_for_non_local_airflow(self):
        with self.assertRaises(AirflowError):
            AirflowClient(settings(base_url="http://airflow.example.test"))

    def test_failed_task_discovery_is_scoped_to_failed_runs_and_tasks(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.full_url.endswith("/dagRuns?") or "/dagRuns?" in request.full_url:
                return Response({"dag_runs": [{"dag_run_id": "run 1", "state": "failed"}]})
            return Response({"task_instances": [{"task_id": "approved_task", "state": "failed", "try_number": 1}]})

        client = AirflowClient(settings(), opener=opener)
        found = client.failed_task_instances("approved_dag")
        self.assertEqual(found[0]["dag_run_id"], "run 1")
        self.assertIn("state=failed", requests[0].full_url)
        self.assertIn("run%201", requests[1].full_url)

    def test_retry_clears_only_single_task_instance_without_neighbors(self):
        captured = []

        def opener(request, timeout):
            captured.append(request)
            return Response({"task_instances": []})

        client = AirflowClient(settings(), opener=opener)
        client.retry_failed_task("approved_dag", "run-1", "approved_task")
        payload = json.loads(captured[0].data)
        self.assertEqual(payload["task_ids"], ["approved_task"])
        self.assertEqual(payload["dag_run_id"], "run-1")
        self.assertFalse(payload["include_downstream"])
        self.assertFalse(payload["include_upstream"])
        self.assertFalse(payload["dry_run"])

    def test_airflow3_jwt_credentials_are_supported(self):
        self.assertTrue(settings(api_version="v2", auth_type="jwt").configured)
        self.assertFalse(settings(api_version="v1", auth_type="jwt").configured)
        self.assertTrue(settings(api_version="v2", auth_type="bearer", token="issued-token").configured)

    def test_airflow3_jwt_is_exchanged_and_cached(self):
        encoded = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 600}).encode()).decode().rstrip("=")
        token = f"header.{encoded}.signature"
        requests = []

        def opener(request, timeout):
            requests.append(request)
            if request.full_url.endswith("/auth/token"):
                return Response({"access_token": token})
            return Response({"status": "healthy"})

        client = AirflowClient(settings(api_version="v2", auth_type="jwt"), opener=opener)
        client.health()
        client.health()
        self.assertEqual(len([request for request in requests if request.full_url.endswith("/auth/token")]), 1)
        api_calls = [request for request in requests if "/api/v2/" in request.full_url]
        self.assertTrue(all(request.get_header("Authorization") == f"Bearer {token}" for request in api_calls))

    def test_recovery_only_retries_allowlisted_task_once(self):
        class FakeClient:
            retry_count = 0

            def __init__(self, _settings):
                pass

            def failed_task_instances(self, dag_id):
                return [
                    {"dag_run_id": "run", "task_id": "approved_task", "try_number": 1},
                    {"dag_run_id": "run", "task_id": "unapproved_task", "try_number": 1},
                ]

            def retry_failed_task(self, *args, **kwargs):
                self.retry_count += 1
                return {"ok": True}

        service = AirflowRecoveryService(settings(), client_factory=FakeClient)
        self.assertEqual(len(service.recover_once()), 1)
        self.assertEqual(len(service.recover_once()), 0)
        self.assertEqual(len(service.events()), 1)

    def test_recovery_does_not_retry_after_first_failed_attempt(self):
        class FakeClient:
            calls = 0

            def __init__(self, _settings):
                pass

            def failed_task_instances(self, _dag):
                return [{"dag_run_id": "run", "task_id": "approved_task", "try_number": 2}]

            def retry_failed_task(self, *args, **kwargs):
                self.calls += 1

        service = AirflowRecoveryService(settings(), client_factory=FakeClient)
        self.assertEqual(service.recover_once(), [])
        self.assertEqual(FakeClient.calls, 0)


if __name__ == "__main__":
    unittest.main()
