"""Structured error responses.

Every error body has the same shape::

    {"error": {"code": "insufficient_funds", "message": "...", "details": {...},
               "correlation_id": "..."}}

Unexpected exceptions return a generic 500 without internals; the stack trace
goes to the logs under the same correlation ID.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from waltrix_core.errors import WaltrixError

from .observability import correlation_id_var

log = logging.getLogger("waltrix.errors")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = details or {}
        self.headers = headers or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "correlation_id": correlation_id_var.get(),
        }
    }


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(code, message, details), status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(WaltrixError)
    async def _domain(_: Request, exc: WaltrixError) -> JSONResponse:
        if exc.status_hint >= 500:
            log.error("internal domain error %s: %s", exc.code, exc.message)
            return error_response(500, "internal_error", "an internal error occurred")
        return error_response(exc.status_hint, exc.code, exc.message, exc.details)

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "message": e.get("msg")}
            for e in exc.errors()
        ]
        return error_response(422, "validation_failed", "request validation failed", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return error_response(500, "internal_error", "an internal error occurred")
