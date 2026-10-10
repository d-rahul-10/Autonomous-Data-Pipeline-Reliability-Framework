# Autonomous Data Pipeline Reliability Framework

A local Flask dashboard and Python toolkit for reviewing ETL log quality, detecting failures and anomalies, predicting bottlenecks, and demonstrating retry-based recovery.

## Project overview

**Project title:** Autonomous Data Pipeline Reliability Framework.

**Problem:** ETL pipelines can fail because of missing or corrupted data, schema changes, transformation errors, system failures, delays, or resource bottlenecks. Manual monitoring and troubleshooting take time and can leave inconsistent data or disrupt downstream work.

**Objectives:** Monitor execution and performance; detect failures and anomalies; validate input quality; demonstrate retry-based recovery; schedule recurring analyses; and predict bottleneck risk from historical run data.

**Proposed solution:** A modular Python framework with a Flask dashboard and CLI. Pandas performs quality validation and cleaning; rule-based checks and Isolation Forest flag failures/anomalies; registered recovery actions and retries demonstrate recovery; a Random Forest classifier estimates bottleneck risk; and SQLite, logging, and JSON/Markdown reports support local operation.

**Technology:** Python, Flask, Pandas, NumPy, scikit-learn, joblib, SQLite, HTML, CSS, and vanilla JavaScript.

**Current status:** The repository contains a working local prototype with dashboard/API and CLI analysis, synthetic-data and CSV input, validation, failure detection, bottleneck prediction, recovery demonstration, recurring scheduling, report downloads, and backend regression tests. This is not evidence of production deployment, external real-time ETL instrumentation, or validation against the public dataset described in the review slides. The presentation mentions a public dataset with 500,000+ records, but that dataset is not bundled here; generated logs are the default input.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux

## Run the dashboard

From the project folder, create and activate a virtual environment, install the dependencies, and launch the app:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) if the browser does not open automatically. The dashboard can analyze generated sample data or an uploaded CSV file. CSV uploads have a 500 MB request-size limit and no separate row-count cap; 500,000-row datasets are supported when they meet the schema below and the server has sufficient memory.

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

## Dashboard workspaces

- **Overview:** reliability score, run counts, data-quality summary, timeline, and recovery-demo controls.
- **Task health:** per-task run counts, failures, duration, and health state.
- **Risk analysis:** predicted bottleneck risk for individual runs.
- **Data quality:** schema, completeness, duplicate, type, and metric-range findings.
- **Performance:** run duration, resource averages, and execution trends.
- **Monitor & recovery:** recent analyses, recovery outcomes, and application log entries.
- **Reports:** download generated JSON and Markdown reports and review recent analysis history.
- **Scheduler:** analyze generated samples or upload a CSV for recurring analysis. Saved CSVs are placed in `data/incoming/`; each run rereads the latest file contents, so an ETL job can replace its export there. The dashboard polls for new results every two seconds and displays completed scheduled analyses automatically. Choose the 15-second interval for frequent refreshes; analysis time depends on dataset size.

The schedule and last 25 analysis results persist in `pipeline_state.sqlite3` and resume when the app starts again. Scheduled runs execute only while the Flask process is running. All uploaded rows are validated and checked for failures; to keep large runs practical, the bottleneck model trains and evaluates on deterministic samples of up to 100,000 rows each. Reports and the trained model are saved to disk (`reports/` and `bottleneck_model.joblib` by default). A new analysis updates the model file.

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
