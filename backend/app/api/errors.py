"""Consistent error responses that never echo request bodies, paths or stack traces."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import current_request_id

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_response(status_code: int, code: str, message: str, details: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": current_request_id(), "details": details or []}},
        headers={"X-Request-ID": current_request_id() or ""},
    )


_HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
               409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 503: "SERVICE_UNAVAILABLE"}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Strip "input" and "ctx": they can echo the submitted transcript.
        details = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg", "Invalid value."), "type": err.get("type", "value_error")}
            for err in exc.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "The request failed validation.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, _HTTP_CODES.get(exc.status_code, "HTTP_ERROR"), message)

    @app.exception_handler(HTTPException)
    async def _fastapi_http(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, _HTTP_CODES.get(exc.status_code, "HTTP_ERROR"), message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", extra={"error_type": type(exc).__name__})
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred. No data was sent to any AI service.")
