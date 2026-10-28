# PipelineIQ sign-in

PipelineIQ provides email and password signup, login, logout, and an authenticated dashboard. Accounts and server-side session records are stored in `pipeline_state.sqlite3`; passwords are hashed with Werkzeug's PBKDF2-SHA256 implementation.

## Run locally

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000/auth`, create an account, and sign in. The development server uses a random session secret for the current process, so sign in again after restarting it.

## Security behavior

- Dashboard APIs require a valid, unexpired server-side session for an active account.
- Login, signup, logout, and dashboard state changes use a session-bound CSRF token.
- Production mode requires `APP_ENV=production` and a `SECRET_KEY` of at least 32 characters. It enables secure, HTTP-only, same-site cookies and security headers.
- Passwords must contain at least eight characters, including lowercase, uppercase, and a number; values are capped at 256 characters.

## Not configured

Password reset email and Google/GitHub OAuth are not implemented. The forgot-password link opens Support, and social buttons explain that those providers are unavailable. The support email is `devallarahul2@gmail.com`.

For deployment constraints, WSGI startup, persistent storage, HTTPS, and proxy configuration, read [DEPLOYMENT.md](DEPLOYMENT.md). This is a single-instance application; it is not a production-ready multi-tenant identity service.
