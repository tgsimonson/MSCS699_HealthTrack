"""domain exceptions raised by the data access and service layers

the api layer turns each into an rfc 9457 problem+json response (see app/api/handlers.py)
"""
from __future__ import annotations

from typing import Any


class HealthTrackError(Exception):
    status_code = 500
    title = "Internal Server Error"
    code = "internal_error"

    def __init__(self, detail: str | None = None, *, errors: list[dict[str, Any]] | None = None,
                 headers: dict[str, str] | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors
        self.headers = headers
        self.extra = extra


class NotFoundError(HealthTrackError):
    status_code, title, code = 404, "Not Found", "not_found"


class ConflictError(HealthTrackError):
    status_code, title, code = 409, "Conflict", "conflict"


class ValidationFailed(HealthTrackError):
    status_code, title, code = 422, "Validation Error", "validation_error"


class AuthenticationError(HealthTrackError):
    status_code, title, code = 401, "Unauthorized", "unauthorized"

    def __init__(self, detail: str | None = None, **kw: Any) -> None:
        kw.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(detail, **kw)


class PermissionDenied(HealthTrackError):
    status_code, title, code = 403, "Forbidden", "forbidden"


class AccountLocked(HealthTrackError):
    status_code, title, code = 423, "Locked", "account_locked"


class RateLimited(HealthTrackError):
    status_code, title, code = 429, "Too Many Requests", "rate_limited"


class DataAccessError(HealthTrackError):
    status_code, title, code = 503, "Service Unavailable", "database_unavailable"
