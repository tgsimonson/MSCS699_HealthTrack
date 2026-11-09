"""reusable openapi response definitions so every route documents its error codes"""
from __future__ import annotations

from typing import Any

from app.schemas.common import Problem, problem_example


def _r(status: int, title: str, detail: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"model": Problem, "description": description,
            "content": {"application/problem+json": {"example": problem_example(status, title, detail, **extra)}}}


R400 = {400: _r(400, "Bad Request", "Malformed request body.", "Malformed request")}
R401 = {401: _r(401, "Unauthorized", "missing bearer token", "Missing, expired, or invalid access token")}
R403 = {403: _r(403, "Forbidden", "role admin cannot access this resource", "Role not allowed for this action")}
R404 = {404: _r(404, "Not Found", "patient not found", "Not found, or outside the caller's scope")}
R409 = {409: _r(409, "Conflict", "a patient with this MRN already exists", "Conflicts with existing data")}
R422 = {422: _r(422, "Validation Error", "One or more fields are invalid.", "Request failed validation",
                errors=[{"field": "systolic_bp", "message": "must be greater than diastolic_bp", "code": "value_error"}])}
R423 = {423: _r(423, "Locked", "account temporarily locked after repeated failed logins", "Account locked")}
R429 = {429: _r(429, "Too Many Requests", "too many login attempts; try again later", "Rate limited")}

AUTHED = {**R401, **R403}
PATIENT_SCOPED = {**R401, **R403, **R404}
