"""Custom application exceptions.

Every service-layer error carries an HTTP status code so the API layer can
translate it into a consistent client response without leaking internals.
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base class for all expected, handleable application errors."""

    status_code = 500
    public_message = "An internal server error occurred."

    def __init__(self, message: str | None = None, *, status_code: int | None = None):
        self.message = message or self.public_message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class ValidationError(PipelineError):
    """Raised when request input fails validation (HTTP 400)."""

    status_code = 400
    public_message = "Invalid request input."


class NotFoundError(PipelineError):
    """Raised when a requested resource does not exist (HTTP 404)."""

    status_code = 404
    public_message = "The requested resource was not found."


class UnauthorizedError(PipelineError):
    """Raised when authentication is required (HTTP 401)."""

    status_code = 401
    public_message = "Authentication required. Please sign in."


class ForbiddenError(PipelineError):
    """Raised when a request fails verification (HTTP 403)."""

    status_code = 403
    public_message = "Request verification failed. Refresh the page and try again."


class ServiceUnavailableError(PipelineError):
    """Raised when a backing service is temporarily unavailable (HTTP 503)."""

    status_code = 503
    public_message = "The authentication service is temporarily unavailable."


class AnalysisTimeoutError(PipelineError):
    """Raised when a dashboard analysis exceeds its configured deadline."""

    status_code = 504
    public_message = "Analysis exceeded the configured time limit."
