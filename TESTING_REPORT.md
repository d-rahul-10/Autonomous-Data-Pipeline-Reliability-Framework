# Testing and Reliability Audit

## Final status: PASS WITH ISSUES

This status reflects the evidence collected, not a claim that every function or branch is correct. The automated suite passed, and an isolated browser workflow completed. Thread timeouts remain non-enforceable for non-cooperative Python workers; multiple interactions and deployment/security checks remain unverified.

## Project overview

The project is a local Python data-pipeline demo:

- `app.py` exposes a Flask dashboard/API, SQLite-backed analysis history and schedule state, uploads, reports, and an in-process schedule loop.
- `main.py` provides the command-line pipeline.
- `data_quality.py`, `failure_detector.py`, and `bottleneck_predictor.py` implement validation/cleaning, failure detection, and model training/inference.
- `monitor.py`, `recovery.py`, and `scheduler.py` implement task monitoring, retries/corrective actions, and a reusable interval scheduler.
- `reporter.py`, `logging_utils.py`, `config.py`, and `synthetic_data.py` support reports, logging, configuration, and generated test/demo data.
- `templates/index.html` and `static/app.js` implement the dashboard.
- Dependencies include Flask, pandas, NumPy, scikit-learn, and joblib. `requirements.txt` uses minimum versions; no lockfile was identified.

The browser check used an isolated temporary working directory and bound the test server to `127.0.0.1`. The project's persistent SQLite database and saved schedule were not used for that check.

## Function and feature inventory

The function-by-function statuses, test references, and gaps are in [TEST_COVERAGE_MATRIX.md](./TEST_COVERAGE_MATRIX.md). That inventory covers all Python declarations found in the application modules, the JavaScript functions and event-handler pathways, and the main API/UI features. A status of PASS means a direct unit test or an exercised integration path exists; it does not mean every input/branch was tested.

The unittest count is a count of test cases, not of unique callables: tests exercise multiple helpers transitively, so no exact independent-function count is claimed. The matrix identifies exercised functions/features and explicitly marks inspected-only or unverified paths as NOT TESTED.

## Test results

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | **46 passed, 0 failed, 0 skipped** |
| Test cases blocked | **0** |
| Python compilation (`py_compile` for project modules and tests) | Passed |
| `node --check .\static\app.js` | Passed |
| `.venv\Scripts\python.exe -m pip check` | Passed: no broken requirements |
| Isolated Flask/browser workflow | Passed for the scenarios below |
| Coverage measurement | Not run: `coverage` is not installed |
| Dependency vulnerability scan | Not run: `pip-audit` is not installed |
| Lint and static type checks | Not run: `ruff` and `mypy` are not installed and no configured equivalents were found |

The four automated test modules are `tests/test_backend.py` (13 tests), `tests/test_app_api.py` (14), `tests/test_scheduler_recovery.py` (15), and `tests/test_main_cli.py` (4).

### Browser/integration evidence

An isolated Flask process on `127.0.0.1:5507` was used with temporary database, report, model, and upload paths. The checks exercised all eight dashboard tabs; analyzed and persisted 10,000 rows; displayed analysis, data-quality, monitor, report, and history results; downloaded a report with HTTP 200 and an attachment filename; uploaded a valid scheduled CSV; enabled and disabled the schedule; and ran the recovery demo, which loaded 100 rows and recovered two tasks. After reload, reports/history remained available, and the browser check recorded no console or page errors. The server was stopped by its verified process ID and the temporary workspace was removed.

This was a focused browser validation, not a maintained automated end-to-end browser suite. It did not exercise every visible control or every failure state.

## Defects found and disposition

| Severity | Defect and root cause | Fix / regression evidence |
| --- | --- | --- |
| Medium | A recovery retry after a thread timeout could overlap the original still-running worker. A `ThreadPoolExecutor` timeout stops waiting, not the thread. | Monitor tracks active work by task name; timeout retries are disabled by default and require explicit `allow_timeout_retry=True`. Cooperative cancellation is signaled only when opted in. Covered by `test_task_timeout_does_not_terminate_worker_or_allow_same_name_overlap`, `test_cooperative_timeout_signals_event_without_claiming_termination`, and recovery timeout tests in `tests/test_scheduler_recovery.py`. |
| Medium | A disabled app scheduler could leave its scheduler thread alive; due work waiting on the analysis lock could run after schedule changes. | The loop exits when disabled, and a schedule-generation check prevents stale queued work from starting. Covered by API scheduler stop/cancellation tests and isolated browser enable/disable. |
| Medium | Persisted schedule JSON and values were not fully checked before restoring scheduler state. | Schedule restoration validates object shape, types, and ranges and uses safe defaults for invalid persisted state. Covered by malformed-state and overdue-restart tests in `tests/test_app_api.py`. |
| Low | A monitor completion callback registered while holding the task-registry lock could deadlock for an already-completed future. | Callback registration occurs outside the lock. The full timeout/recovery suite passed afterward. |
| Low | Recovery-demo and CSV-write error responses could expose internal exception details. | Client-facing errors are generic while details remain in application logs. Covered by recovery error-redaction and upload rejection API tests. |

## Files changed

- `app.py`: scheduler state validation, stale-job cancellation, disabled-thread exit, schedule persistence behavior, and safer API error responses.
- `monitor.py`: explicit timeout state, cooperative cancellation signal, active-task overlap guard, input validation, and thread-safe execution records.
- `recovery.py`: safer timeout retry defaults and validation of retry/backoff options.
- `scheduler.py`: job/loop validation, duplicate rejection, pending-job cancellation, stop control, and lock-free job invocation.
- `tests/test_app_api.py`, `tests/test_backend.py`, and `tests/test_main_cli.py`: regression and integration cases.
- `tests/test_scheduler_recovery.py`: new scheduler, timeout, and recovery regression coverage.
- `README.md`: documents overdue scheduling and timeout/cancellation/retry semantics.
- `TESTING_REPORT.md` and `TEST_COVERAGE_MATRIX.md`: requested audit deliverables.

The audit test run appended records to the existing `pipeline.log`. Those exact appended records were removed by restoring the file to its recorded pre-audit length (17,382 bytes); the file is not claimed to have been untouched.

## Coverage and unverified code

No line or branch coverage percentage is available. The `coverage` package is absent, and no coverage run was performed. The matrix marks non-exercised functions and paths as NOT TESTED instead of inferring coverage from source inspection.

Not independently verified: all possible Flask error branches; large-file memory/performance behavior; sustained high-concurrency SQLite access; exact real-time periodic cadence over a long-running session; process crash/restart while work is executing; non-cooperative worker termination; every frontend event handler and validation message; and report/model filesystem failure cases.

## Scheduler and timeout verification

- Temporary-database tests verify valid and malformed saved schedules, overdue restoration without changing the saved timestamp, a due job running once, persisted success/failure counts, later recovery after a failed run, disabled scheduler behavior, and preventing queued work from running after disable.
- Reusable-scheduler tests verify valid/invalid job registration, duplicate names, due-job execution, cancellation, failure isolation, and stop behavior.
- Timeout tests reproduce the condition where the caller reaches its deadline while the worker remains alive. They verify no same-name overlap by default, cooperative event signaling, retry limits/backoff and corrective actions, fallback results, and explicit opt-in for timeout retry.
- No test claims that Python killed a timed-out thread. A non-cooperative worker may continue until it returns. Process isolation is not implemented.
- The real persistent overdue schedule was not executed. The restart test uses temporary state and stubs the scheduler thread target; the browser test uses isolated state.

## Security, performance, and integration

- The app is a local demo with no authentication or authorization. The test server was deliberately bound to loopback; this does not establish deployment security.
- API request-size rejection is covered, but the configured maximum-size boundary and very large CSV memory use were not stress-tested. The browser exercised 10,000 rows only.
- No dependency vulnerability scanner was available, so dependency CVEs are **unverified**. `pip check` validates installed dependency consistency only; it is not a vulnerability scan.
- A targeted local search of the application sources for common hardcoded credential assignments and private-key headers found no matches; no automated secrets scanner was run. No credentials were supplied or used during the isolated tests.
- SQLite writes, report creation/download, analysis history, and temporary scheduler state were exercised. Production database concurrency and external service integrations were not applicable/tested.
- Startup and normal isolated shutdown were exercised. Crash recovery, graceful shutdown during an active analysis, and long-duration resource usage remain unverified.

## Remaining risks and commands

1. Non-cooperative timed-out tasks cannot be forcibly stopped in the current thread-based design. Keep timeout retries disabled unless the task is explicitly safe to overlap; use process isolation if termination must be enforceable.
2. No coverage or dependency-vulnerability report exists because the corresponding scanner is unavailable.
3. UI controls including browser-history navigation, visibility changes, notice dismissal, quality-detail toggle, and several invalid-form/upload states are not individually tested.
4. No production deployment, authentication, large-file stress test, or multi-process scheduler test was performed.

Run the app and available checks from the project directory:

```powershell
python app.py
python main.py --rows 50000
python -m unittest discover -s tests -v
node --check .\static\app.js
python -m py_compile .\app.py .\main.py .\monitor.py .\recovery.py .\scheduler.py
python -m pip check
```

**Conclusion:** PASS WITH ISSUES. All 46 automated tests and the recorded focused browser checks passed. The remaining timeout limitation and unmeasured/unverified areas above prevent a PASS classification.
