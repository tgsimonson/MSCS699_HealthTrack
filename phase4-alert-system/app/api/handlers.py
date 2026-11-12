"""exception handlers: every error becomes rfc 9457 problem+json with the request id"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import HealthTrackError
from app.logging_config import get_logger, request_id_var

log = get_logger("api.errors")
PROBLEM = "application/problem+json"


def _problem(request: Request, status: int, title: str, detail: str, code: str, **extra) -> JSONResponse:  # noqa: ANN003
    body = {"type": f"https://api.healthtrack.example/problems/{code}", "title": title, "status": status,
            "detail": detail, "instance": request.url.path, "request_id": request_id_var.get()}
    body.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def _loc(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    out = ""
    for p in parts:
        out += f"[{p}]" if p.isdigit() else (f".{p}" if out else p)
    return out or "request"


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(HealthTrackError)
    async def domain_error(request: Request, exc: HealthTrackError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("request failed", extra={"ctx": {"path": request.url.path, "error": exc.code}})
        resp = _problem(request, exc.status_code, exc.title, exc.detail, exc.code, errors=exc.errors,
                        **{k: v for k, v in exc.extra.items() if k != "constraint"})
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": _loc(e.get("loc", ())), "message": e.get("msg", "invalid"), "code": e.get("type", "invalid")}
                  for e in exc.errors()]
        return _problem(request, 422, "Validation Error", "One or more fields are invalid.", "validation_error",
                        errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        titles = {404: "Not Found", 405: "Method Not Allowed", 401: "Unauthorized", 403: "Forbidden"}
        title = titles.get(exc.status_code, "Error")
        return _problem(request, exc.status_code, title, str(exc.detail), title.lower().replace(" ", "_"))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # log the stack trace with the request id; never send internals to the client
        log.error("unhandled exception", extra={"ctx": {"path": request.url.path}}, exc_info=exc)
        return _problem(request, 500, "Internal Server Error",
                        "An unexpected error occurred. Quote the request_id when reporting it.", "internal_error")
