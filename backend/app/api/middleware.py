"""Request correlation, size limits, security headers and structured logging."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

logger = logging.getLogger("app.access")


def current_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_request_bytes: int, large_body_limits: dict[str, int] | None = None) -> None:
        super().__init__(app)
        self.max_request_bytes = max_request_bytes
        # Paths that accept larger bodies (audio uploads), with their own limit.
        self.large_body_limits = large_body_limits or {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _CLIENT_ID.fullmatch(supplied) else str(uuid.uuid4())
        token = _request_id.set(request_id)
        started = time.perf_counter()
        limit = self.large_body_limits.get(request.url.path, self.max_request_bytes)
        try:
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    too_large = int(length) > limit
                except ValueError:
                    too_large = True
                if too_large:
                    return self._reject(request_id, 413, "PAYLOAD_TOO_LARGE", f"Request body exceeds {limit} bytes.")
            elif request.method in ("POST", "PUT", "PATCH"):
                body = await request.body()
                if len(body) > limit:
                    return self._reject(request_id, 413, "PAYLOAD_TOO_LARGE", f"Request body exceeds {limit} bytes.")

            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001 - never leak details
                logging.getLogger("app.errors").error("unhandled error", extra={"error_type": type(exc).__name__})
                response = self._reject(request_id, 500, "INTERNAL_ERROR",
                                        "An unexpected error occurred. No data was sent to any AI service.")
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            _request_id.reset(token)

    @staticmethod
    def _reject(request_id: str, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "request_id": request_id, "details": []}},
            headers={"X-Request-ID": request_id},
        )


class JsonFormatter(logging.Formatter):
    """Structured logs. Only whitelisted extra fields are emitted; never request bodies."""

    FIELDS = ("request_id", "method", "path", "status", "duration_ms", "operation", "decision",
              "entity_categories", "total_ms", "error_type", "load_seconds")

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or current_request_id()
        if rid:
            data["request_id"] = rid
        for name in self.FIELDS:
            if name != "request_id" and hasattr(record, name):
                data[name] = getattr(record, name)
        return json.dumps(data, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Presidio logs registry notices at WARNING for unused languages; keep errors only.
    for noisy in ("presidio-analyzer", "presidio-anonymizer"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").disabled = True
