# PipelineIQ implementation summary

## Current application

PipelineIQ is a Flask dashboard and Python CLI for validating ETL logs, flagging failures and anomalies, estimating bottleneck risk, demonstrating retry-based recovery, scheduling analyses, and generating reports. Its authentication UI supports email/password signup, login, and logout.

## Authentication implementation

- Passwords are hashed with Werkzeug PBKDF2-SHA256.
- Account and session rows are stored in SQLite (`pipeline_state.sqlite3`). Dashboard API requests validate an active, unexpired server-side session.
- Login, signup, logout, and dashboard state-changing requests require a CSRF token.
- Production startup requires `APP_ENV=production` and a secret `SECRET_KEY` at least 32 characters long. Production cookies are secure, HTTP-only, and SameSite Lax.
- Input sizes are bounded; inactive accounts cannot sign in; invalid login responses do not reveal whether an email exists.

## Current limitations

- Password reset and email delivery are not configured.
- Google and GitHub OAuth buttons are informational placeholders.
- Rate limiting must be configured at the hosting edge before exposing the application publicly.
- The scheduler and analysis jobs use process-local state. Run a single web worker; horizontal scaling and multi-worker operation are unsupported.
- The Flask development server is local-only. Use a production WSGI server behind HTTPS and persistent storage as documented in [DEPLOYMENT.md](DEPLOYMENT.md).

## Verification

Run the automated tests with:

```powershell
python -m pytest -q -p no:cacheprovider
```

The current suite covers authentication, session expiry/revocation, CSRF enforcement, dashboard APIs, CSV validation, analysis, scheduling, recovery, and reports.
