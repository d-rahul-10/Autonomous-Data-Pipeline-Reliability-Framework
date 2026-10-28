# Deployment guide

## Current operating limits

This is a single-instance Flask application with a local SQLite database, on-disk reports/model, and an in-process scheduler. Run exactly one web worker so the scheduler and in-memory job state are not duplicated. Use a persistent writable working directory and persistent disk for `pipeline_state.sqlite3`, `data/incoming/`, `reports/`, `pipeline.log`, and `bottleneck_model.joblib`. Back up the database and those files together. This deployment shape is suitable for a private, low-volume instance; it is not a horizontally scaled multi-tenant service.

## Linux host

1. Install Python 3.10 or newer and create a persistent application directory.
2. Copy the repository and enter its directory. Create a virtual environment and install the locked application dependencies from `requirements.txt`.
3. Set `APP_ENV=production` and `SECRET_KEY` in the host's secret manager. Generate a value with:

   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Never commit `.env` or a real secret. The app refuses to start in production when the key is missing or shorter than 32 characters. Production cookies use `Secure`, `HttpOnly`, and `SameSite=Lax`.
4. Start one Gunicorn worker with threads, from the persistent application directory:

   ```sh
   gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 8 --timeout 180 wsgi:app
   ```

5. Put the process behind one maintained HTTPS reverse proxy or hosting platform TLS endpoint. The WSGI app trusts one proxy's forwarded client-IP and scheme headers; block direct inbound access so clients cannot spoof them. Flask emits HSTS on secure requests. Configure process restart/health monitoring, edge rate limits for authentication and upload/analysis routes, and make the app data directory writable only by the service account.

## Windows host

`app.py` provides a convenient localhost development server. The Flask development server is not intended for public production traffic. For a private Windows-hosted deployment, install and configure a production WSGI server that supports Windows (for example Waitress), terminate TLS at a maintained reverse proxy, and keep the same one-process and persistent-storage requirements above. Do not expose the development server directly to the internet.

## Data and operations

- `/healthz` is a minimal database-backed readiness probe. `/api/status` reports pipeline state only to an authenticated session.
- SQLite uses WAL mode. Stop the process cleanly before copying its database files for backups, and include SQLite WAL/SHM files if backing up while it is running.
- Scheduled tasks run only while the process is running. The scheduler currently lives inside the web process.
- Optional Airflow polling and recovery also run inside the web process and require exactly one app worker. They remain disabled by default. Enable them only after setting an API URL, the correct API version and auth method, and explicit DAG and task allowlists. Keep Airflow credentials in the host's secret manager, grant only the API permissions needed for inspection and clearing failed tasks, and test in a non-production Airflow environment first.
- Uploaded CSVs are limited to 500 MB and stored in `data/incoming/` when used by the scheduler. Restrict access and retention for uploaded operational data.
- The app intentionally requires login for dashboard APIs and validates the server-side session on each request. State-changing dashboard requests use a CSRF token.
- Signup and login are email/password only. Password recovery is not configured; the sign-in page links users to the published support email.
- Configure host-level request timeouts, authentication and upload rate limits, disk monitoring, log rotation, backups, and incident response before accepting important production data.
- Before moving to multiple app instances, replace process-local jobs/scheduler state and local SQLite/storage with shared services, then load-test and security-review that architecture.

## Apache Airflow integration

Set these values in the hosting service environment (see `.env.example`):

- `AIRFLOW_API_URL`: base URL of the Airflow web/API server.
- `AIRFLOW_API_VERSION`: `v1` for Airflow 2 or `v2` for Airflow 3.
- `AIRFLOW_AUTH_TYPE`: `basic` for an Airflow 2 API configured for Basic auth; `jwt` for Airflow 3 username/password token exchange; or `bearer` for a pre-issued Airflow 3 JWT.
- Matching `AIRFLOW_API_USERNAME` / `AIRFLOW_API_PASSWORD` or `AIRFLOW_API_TOKEN` values, stored as deployment secrets.
- `AIRFLOW_DAG_ALLOWLIST` and `AIRFLOW_TASK_ALLOWLIST`: comma-separated explicit IDs. The retry worker ignores anything outside both lists.
- `AIRFLOW_AUTO_RETRY_ENABLED=true` to enable the polling worker. The default is false. `AIRFLOW_MAX_AUTOMATIC_RETRIES` is capped at one, and `AIRFLOW_POLL_SECONDS` is bounded to at least 15 seconds.

The connector observes failed task instances and requests a retry by clearing an individual failed task instance through Airflow's public REST API. Airflow then applies the task's existing definition and retry behavior. The API response does not give this integration a dependable failure category, so only allowlist idempotent tasks safe to rerun. No DAG, task input, connection, variable, or secret is modified. A task that fails due to missing input or invalid credentials still needs an operator to correct the source or Airflow configuration. API version/auth setup varies by Airflow deployment; confirm connectivity and permissions on a staging instance before turning on retries.

## Local production-configuration check

On PowerShell, set the two environment variables in the hosting service configuration, then start the WSGI entry point. Example key generation:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Keep `.env` outside source control. `.env.example` contains placeholders only.
