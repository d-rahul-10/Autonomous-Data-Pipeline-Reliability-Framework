"""Fail-safe Apache Airflow REST API client and retry policy.

This integration only retries failed task instances explicitly listed in both
the DAG and task allowlists. It never edits DAG definitions, connections, or
variables. Airflow configuration is supplied by the deployment environment.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


class AirflowError(RuntimeError):
    """A sanitized Airflow connection or API error."""


@dataclass(frozen=True)
class AirflowSettings:
    base_url: str
    api_version: str
    auth_type: str
    username: str
    password: str
    token: str
    dag_allowlist: tuple[str, ...]
    task_allowlist: tuple[str, ...]
    auto_retry_enabled: bool
    poll_seconds: int
    max_retries: int
    request_timeout: int

    @classmethod
    def from_env(cls) -> "AirflowSettings":
        version = os.getenv("AIRFLOW_API_VERSION", "v1").strip().lower()
        auth_type = os.getenv("AIRFLOW_AUTH_TYPE", "basic").strip().lower()
        return cls(
            base_url=os.getenv("AIRFLOW_API_URL", "").strip().rstrip("/"),
            api_version=version,
            auth_type=auth_type,
            username=os.getenv("AIRFLOW_API_USERNAME", ""),
            password=os.getenv("AIRFLOW_API_PASSWORD", ""),
            token=os.getenv("AIRFLOW_API_TOKEN", ""),
            dag_allowlist=_csv_env("AIRFLOW_DAG_ALLOWLIST"),
            task_allowlist=_csv_env("AIRFLOW_TASK_ALLOWLIST"),
            auto_retry_enabled=_env_bool("AIRFLOW_AUTO_RETRY_ENABLED", False),
            poll_seconds=_bounded_int("AIRFLOW_POLL_SECONDS", 60, 15, 3600),
            max_retries=_bounded_int("AIRFLOW_MAX_AUTOMATIC_RETRIES", 1, 0, 1),
            request_timeout=_bounded_int("AIRFLOW_REQUEST_TIMEOUT", 10, 2, 60),
        )

    @property
    def configured(self) -> bool:
        if not self.base_url or self.api_version not in {"v1", "v2"}:
            return False
        if self.auth_type == "basic":
            return bool(self.username and self.password)
        if self.auth_type == "jwt":
            return bool(self.username and self.password and self.api_version == "v2")
        if self.auth_type == "bearer":
            return bool(self.token)
        return False

    @property
    def ready_for_automation(self) -> bool:
        return (
            self.configured
            and self.auto_retry_enabled
            and bool(self.dag_allowlist)
            and bool(self.task_allowlist)
            and self.max_retries > 0
        )


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in os.getenv(name, "").split(",") if item.strip()))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


class AirflowClient:
    """Small stdlib-only Airflow REST client with TLS verification enabled."""

    def __init__(self, settings: AirflowSettings, opener=None):
        self.settings = settings
        self._opener = opener or urlopen
        self._token_lock = threading.Lock()
        self._cached_token = ""
        self._token_expiry = 0.0
        if not settings.configured:
            raise AirflowError("Airflow integration is not configured. Check its API URL, version, and auth settings.")
        parts = urlsplit(settings.base_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
            raise AirflowError("Airflow API URL must be an HTTP(S) URL without embedded credentials.")
        if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise AirflowError("Airflow API must use HTTPS except when connecting to localhost.")
        self._root = f"{settings.base_url}/api/{settings.api_version}"

    def _request(self, method: str, path: str, *, query=None, payload=None) -> Any:
        url = f"{self._root}{path}"
        if query:
            url += "?" + urlencode(query, doseq=True)
        headers = {"Accept": "application/json"}
        if self.settings.auth_type == "basic":
            pair = f"{self.settings.username}:{self.settings.password}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("ascii")
        elif self.settings.auth_type == "jwt":
            headers["Authorization"] = f"Bearer {self._get_jwt()}"
        else:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self.settings.request_timeout) as response:
                content = response.read(2_000_000)
                if not content:
                    return {}
                return json.loads(content.decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise AirflowError("Airflow rejected the configured credentials or permissions.") from None
            if exc.code == 404:
                raise AirflowError("Airflow API endpoint or configured resource was not found.") from None
            raise AirflowError(f"Airflow API returned HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError):
            raise AirflowError("Could not reach the Airflow API. Check its URL, network access, and TLS certificate.") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AirflowError("Airflow returned an invalid JSON response.") from None

    def _get_jwt(self) -> str:
        with self._token_lock:
            if self._cached_token and time.time() < self._token_expiry - 30:
                return self._cached_token
            url = f"{self.settings.base_url}/auth/token"
            body = json.dumps({"username": self.settings.username, "password": self.settings.password}).encode("utf-8")
            request = Request(url, data=body, headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST")
            try:
                with self._opener(request, timeout=self.settings.request_timeout) as response:
                    result = json.loads(response.read(128_000).decode("utf-8"))
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise AirflowError("Airflow rejected the configured credentials or permissions.") from None
                raise AirflowError(f"Airflow token endpoint returned HTTP {exc.code}.") from None
            except (URLError, TimeoutError, OSError):
                raise AirflowError("Could not reach the Airflow token endpoint. Check its URL, network access, and TLS certificate.") from None
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise AirflowError("Airflow token endpoint returned invalid JSON.") from None
            token = result.get("access_token") if isinstance(result, dict) else None
            if not isinstance(token, str) or not token:
                raise AirflowError("Airflow token endpoint did not return an access token.")
            self._cached_token = token
            try:
                claims = token.split(".")[1]
                claims += "=" * (-len(claims) % 4)
                expiry = json.loads(base64.urlsafe_b64decode(claims)).get("exp")
                self._token_expiry = float(expiry) if expiry else time.time() + 300
            except (IndexError, ValueError, TypeError, json.JSONDecodeError):
                self._token_expiry = time.time() + 300
            return token

    def health(self) -> dict:
        path = "/monitor/health" if self.settings.api_version == "v2" else "/health"
        return self._request("GET", path)

    def failed_task_instances(self, dag_id: str, *, limit: int = 100) -> list[dict]:
        dag = quote(dag_id, safe="")
        runs = self._request(
            "GET", f"/dags/{dag}/dagRuns",
            query={"limit": max(1, min(limit, 100)), "state": "failed", "order_by": "-logical_date"},
        )
        run_items = runs.get("dag_runs", []) if isinstance(runs, dict) else []
        failed = []
        for run in run_items[:limit]:
            if run.get("state") != "failed" or not run.get("dag_run_id"):
                continue
            run_id = quote(str(run["dag_run_id"]), safe="")
            page = self._request(
                "GET", f"/dags/{dag}/dagRuns/{run_id}/taskInstances",
                query={"limit": 100, "state": "failed"},
            )
            instances = page.get("task_instances", []) if isinstance(page, dict) else []
            for instance in instances:
                if instance.get("state") == "failed":
                    failed.append({**instance, "dag_id": dag_id, "dag_run_id": run["dag_run_id"]})
        return failed

    def retry_failed_task(self, dag_id: str, dag_run_id: str, task_id: str, *, map_index: int = -1, dry_run: bool = False) -> dict:
        if map_index >= 0 and self.settings.api_version == "v1":
            raise AirflowError("Airflow v1 cannot safely target one mapped task instance; retry it manually in Airflow.")
        dag = quote(dag_id, safe="")
        payload = {
            "dry_run": bool(dry_run), "only_failed": True, "only_running": False,
            "task_ids": [[task_id, map_index]] if map_index >= 0 else [task_id], "dag_run_id": dag_run_id,
            "include_upstream": False, "include_downstream": False,
            "include_future": False, "include_past": False,
        }
        if self.settings.api_version == "v1":
            payload["include_subdags"] = False
            payload["include_parentdag"] = False
        else:
            payload["reset_dag_runs"] = True
            payload["prevent_running_task"] = True
        return self._request("POST", f"/dags/{dag}/clearTaskInstances", payload=payload)


class AirflowRecoveryService:
    """Apply allowlisted, one-retry-per-task-instance recovery policy."""

    def __init__(self, settings: AirflowSettings, client_factory=AirflowClient):
        self.settings = settings
        self.client_factory = client_factory
        self._lock = threading.Lock()
        self._last_retry: dict[tuple[str, str, str], float] = {}
        self._events: list[dict] = []

    def status(self) -> dict:
        return {
            "configured": self.settings.configured,
            "api_version": self.settings.api_version,
            "auto_retry_enabled": self.settings.auto_retry_enabled,
            "ready_for_automation": self.settings.ready_for_automation,
            "dag_allowlist": list(self.settings.dag_allowlist),
            "task_allowlist": list(self.settings.task_allowlist),
            "message": "Ready" if self.settings.ready_for_automation else "Setup required; automatic retries are disabled.",
        }

    def inspect(self) -> dict:
        if not self.settings.configured:
            return {"status": self.status(), "failed_tasks": [], "error": "Airflow is not configured."}
        client = self.client_factory(self.settings)
        try:
            health = client.health()
            failed = []
            for dag_id in self.settings.dag_allowlist:
                failed.extend(client.failed_task_instances(dag_id))
            return {"status": self.status(), "health": health, "failed_tasks": failed, "events": self.events()}
        except AirflowError as exc:
            return {"status": self.status(), "failed_tasks": [], "error": str(exc), "events": self.events()}

    def recover_once(self) -> list[dict]:
        if not self.settings.ready_for_automation:
            return []
        client = self.client_factory(self.settings)
        created = []
        for dag_id in self.settings.dag_allowlist:
            try:
                failed = client.failed_task_instances(dag_id)
            except AirflowError as exc:
                self._record({"time": _now(), "dag_id": dag_id, "status": "error", "detail": str(exc)})
                continue
            for task in failed:
                task_id = str(task.get("task_id", ""))
                run_id = str(task.get("dag_run_id", ""))
                if task_id not in self.settings.task_allowlist or not run_id:
                    continue
                # Airflow's try_number starts at 1. Permit at most one automatic
                # recovery attempt, even if this process restarts.
                try:
                    try_number = int(task.get("try_number", 1))
                except (TypeError, ValueError):
                    continue
                if try_number < 1 or try_number > self.settings.max_retries:
                    continue
                key = (dag_id, run_id, task_id)
                with self._lock:
                    if key in self._last_retry:
                        continue
                    self._last_retry[key] = time.monotonic()
                try:
                    try:
                        map_index = int(task.get("map_index", -1))
                    except (TypeError, ValueError):
                        continue
                    result = client.retry_failed_task(dag_id, run_id, task_id, map_index=map_index, dry_run=False)
                    event = {"time": _now(), "dag_id": dag_id, "dag_run_id": run_id,
                             "task_id": task_id, "status": "retry_requested", "detail": "Failed task cleared for Airflow retry."}
                    created.append({**event, "airflow_response": result})
                    self._record(event)
                except AirflowError as exc:
                    self._record({"time": _now(), "dag_id": dag_id, "dag_run_id": run_id,
                                  "task_id": task_id, "status": "error", "detail": str(exc)})
        return created

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def _record(self, event: dict) -> None:
        with self._lock:
            self._events.insert(0, event)
            del self._events[100:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
