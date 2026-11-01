# Autonomous Data Pipeline Reliability Framework

A local Flask dashboard and Python toolkit for reviewing ETL log quality, detecting failures and anomalies, predicting bottlenecks, and demonstrating retry-based recovery.

## Project overview

**Project title:** Autonomous Data Pipeline Reliability Framework.

**Problem:** ETL pipelines can fail because of missing or corrupted data, schema changes, transformation errors, system failures, delays, or resource bottlenecks. Manual monitoring and troubleshooting take time and can leave inconsistent data or disrupt downstream work.

**Objectives:** Monitor execution and performance; detect failures and anomalies; validate input quality; demonstrate retry-based recovery; schedule recurring analyses; and predict bottleneck risk from historical run data.

**Proposed solution:** A modular Python framework with a Flask dashboard and CLI. Pandas performs quality validation and cleaning; rule-based checks and Isolation Forest flag failures/anomalies; registered recovery actions and retries demonstrate recovery; a Random Forest classifier estimates bottleneck risk; and SQLite, logging, and JSON/Markdown reports support local operation.

**Technology:** Python, Flask, Pandas, NumPy, scikit-learn, joblib, SQLite, HTML, CSS, vanilla JavaScript, and a locally served GSAP animation bundle. An optional Apache Airflow REST API connector monitors approved DAGs and can clear failed task instances for Airflow to retry.

**Current status:** The repository contains a working local prototype with dashboard/API and CLI analysis, synthetic-data and CSV input, validation, failure detection, bottleneck prediction, recovery demonstration, recurring scheduling, report downloads, and backend regression tests. This is not evidence of production deployment, external real-time ETL instrumentation, or validation against the public dataset described in the review slides. The presentation mentions a public dataset with 500,000+ records, but that dataset is not bundled here; generated logs are the default input.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux

The dashboard has email/password signup and login. APIs require an active account session where appropriate, and state-changing requests include CSRF protection. Password reset email delivery is not configured; sign-in links to the support contact. Development mode uses a random process-local session key; sign-in sessions end when that development server restarts.

## Run the dashboard

From the project folder, create and activate a virtual environment, install the dependencies, and launch the app:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) if the browser does not open automatically. The dashboard can analyze generated sample data or an uploaded CSV file. CSV uploads have a 500 MB request-size limit and no separate row-count cap; 500,000-row datasets are supported when they meet the schema below and the server has sufficient memory. Dashboard analyses run as background jobs with phase/progress updates and a five-minute default deadline; set `ANALYSIS_TIMEOUT_SECONDS` (30–3600) to tune that limit.

## CSV format

The default required columns are:

| Column | Meaning |
|---|---|
| `timestamp` | Run date/time |
| `task_id` | Pipeline task name or identifier |
| `status` | Run status; `FAILED`, `ERROR`, and `TIMEOUT` count as failures |
| `duration` | Run duration in seconds |
| `cpu_usage` | CPU usage percentage |
| `memory_usage` | Memory usage percentage |
| `io_throughput` | I/O throughput metric |
| `latency` | Latency in milliseconds |

`error_code` and `dependencies` are optional. Column mappings, failure statuses, validation schema, model parameters, and output paths can be changed in `config.py`. Keep the configured required columns present in uploaded CSVs.

The dashboard and command-line analysis require at least 200 valid rows after cleaning. A CSV export may have metadata rows before its table; the reader retries those files only when it can identify a consistent table. The CLI rejects missing required CSV columns and non-positive generated sample sizes with a clear usage error. Population-statistics files are not ETL execution logs and cannot be analyzed directly by this project.

The dashboard uses a locally bundled GSAP runtime for page transitions and scroll-triggered reveals; CSS provides responsive styling and reduced-motion support. See [STYLE_GUIDE.md](STYLE_GUIDE.md) for the palette, animation tokens, component variants, and asset update instructions. Node.js is only needed when refreshing the GSAP bundle, not to run the Flask app.

## Dashboard workspaces

- **Overview:** reliability score, run counts, data-quality summary, timeline, and recovery-demo controls.
- **Monitor:** inspect failed tasks from an optional Airflow deployment and enable bounded retries for explicitly allowlisted DAGs and tasks. The local recovery demo remains simulated.
- **Task health:** per-task run counts, failures, duration, and health state.
- **Risk analysis:** predicted bottleneck risk for individual runs.
- **Data quality:** schema, completeness, duplicate, type, and metric-range findings.
- **Performance:** run duration, resource averages, and execution trends.
- **Monitor & recovery:** recent analyses, recovery outcomes, and application log entries.
- **Health check:** `/healthz` reports database-backed readiness without returning user or pipeline data.
- **Reports:** download generated JSON and Markdown reports and review recent analysis history.
- **Scheduler:** analyze generated samples or upload a CSV for recurring analysis. Saved CSVs are placed in `data/incoming/`; each run rereads the latest file contents, so an ETL job can replace its export there. The dashboard polls for new results every two seconds and displays completed scheduled analyses automatically. Choose the 15-second interval for frequent refreshes; analysis time depends on dataset size.

The schedule and last 25 analysis results persist in `pipeline_state.sqlite3` and resume when the app starts again. Scheduled runs execute only while the Flask process is running. All uploaded rows are validated and checked for failures; to keep large runs practical, the bottleneck model trains and evaluates on deterministic samples of up to 100,000 rows each. Reports and the trained model are saved to disk (`reports/` and `bottleneck_model.joblib` by default). A new analysis updates the model file.

### Optional Apache Airflow recovery

The Airflow connector is off by default. Configure it on the server using the `AIRFLOW_*` variables in `.env.example`. Airflow 2 deployments use API `v1` with Basic auth when enabled on that deployment. Airflow 3 deployments use API `v2` with `AIRFLOW_AUTH_TYPE=jwt` (the connector exchanges the configured username/password for JWTs) or `bearer` with a pre-issued token. The configured Airflow user must have permission to list DAG runs and task instances and clear failed task instances.

The monitor page can inspect approved DAGs. Automatic retries start only when `AIRFLOW_AUTO_RETRY_ENABLED=true`, valid API access is configured, and both `AIRFLOW_DAG_ALLOWLIST` and `AIRFLOW_TASK_ALLOWLIST` contain explicit IDs. Only put idempotent tasks that are safe to rerun on those lists: the public Airflow API reports failed state, not a reliable failure category for this connector to distinguish transient failures from bad input. The worker polls at the configured interval and sends at most one automatic retry request per task instance. Airflow performs the retry using the task's existing DAG definition and retry policy. PipelineIQ never edits DAG code, task inputs, Airflow connections, variables, or credentials. Missing/invalid inputs and credentials are surfaced for an operator to fix. Test this integration against a non-production Airflow deployment before enabling it for client workloads.

An enabled schedule whose saved due time has passed runs once after startup. Disabling the schedule prevents future work and cancels a due run that is still waiting to acquire the analysis lock; an analysis already in progress is allowed to finish.

`PipelineMonitor` timeouts do not terminate Python worker threads. A timed-out worker may continue until it returns. Recovery therefore does not retry monitor timeouts by default. Tasks that accept a `cancel_event` can opt into a cooperative cancellation signal with `cooperative_cancel=True`; this is a request to stop, not forced termination. `allow_timeout_retry=True` is an explicit opt-in for callables designed to tolerate overlapping attempts. Enforceable termination would require process isolation, which this local demo does not provide.

## Run from the command line

The original end-to-end demonstration is also available without the web dashboard:

```powershell
python main.py
python main.py --rows 50000
python main.py --data path\to\pipeline_logs.csv
```

Reports are written under `reports/`; application logs are written to `pipeline.log`.

## Run backend tests

Run the focused backend regression tests with:

```powershell
python -m unittest discover -s tests
```

The audit inventory and per-function verification statuses are in `TESTING_REPORT.md` and `TEST_COVERAGE_MATRIX.md`.

## Production deployment

Do not expose `python app.py` publicly; it starts Flask's development server on localhost. The WSGI entry point is `wsgi:app`. On Linux, install `requirements.txt` and run a single Gunicorn worker behind HTTPS. Production mode requires `APP_ENV=production` and a `SECRET_KEY` containing at least 32 characters. Keep the SQLite database and generated files on persistent storage. This release is designed for a private, single-instance deployment; before public use, configure edge rate limits and account recovery, and account for its process-local scheduler and analysis-job state. See [DEPLOYMENT.md](DEPLOYMENT.md) for exact setup and operating limits.
