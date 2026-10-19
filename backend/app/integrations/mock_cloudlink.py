"""Mock CloudLink receiver (SIMULATED INTEGRATION).

Runs as a separate process so that a successful handoff means a real HTTP request
reached a separate service:

    uvicorn app.integrations.mock_cloudlink:app --port 8100

It does not connect to any Mitel service. Received payloads are kept in memory only
(last 20) for the demonstration and are lost on restart.
"""

from __future__ import annotations

import secrets
import uuid
from collections import deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.integrations.contracts import CLOUD_DECISIONS, REQUEST_ID_PATTERN

MAX_RECEIPTS = 20


class IncomingHandoff(BaseModel):
    """Receiver-side schema. Deliberately independent of the firewall's own model."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    decision: str
    destination: str
    profile: str = Field(max_length=40)
    channel: str = Field(max_length=10)
    policy_version: str = Field(max_length=40)
    entity_categories: list[str] = Field(default_factory=list, max_length=20)
    sanitized_summary: str | None = Field(default=None, max_length=2000)
    sanitized_transcript: str = Field(max_length=100000)
    created_at: datetime


def create_mock_cloudlink_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    expected_key = settings.cloudlink_api_key.get_secret_value()
    receipts: deque[dict] = deque(maxlen=MAX_RECEIPTS)
    lock = Lock()
    counters = {"accepted": 0, "rejected": 0}

    app = FastAPI(title="Mock CloudLink Receiver (simulated)", version="0.1.0", docs_url="/docs", redoc_url=None)
    app.state.receipts = receipts
    app.state.counters = counters

    def reject(status_code: int, code: str, message: str) -> JSONResponse:
        with lock:
            counters["rejected"] += 1
        return JSONResponse(status_code=status_code, content={"status": "REJECTED", "code": code, "message": message, "simulated": True})

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return reject(422, "SCHEMA_INVALID", f"Payload failed schema validation ({len(exc.errors())} error(s)).")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "service": "mock-cloudlink",
            "simulated": True,
            "receipts_count": counters["accepted"],
            "rejected_count": counters["rejected"],
        }

    @app.post("/v1/handoff")
    def handoff(payload: IncomingHandoff, x_cloudlink_key: str | None = Header(default=None)):
        if expected_key and not (x_cloudlink_key and secrets.compare_digest(x_cloudlink_key, expected_key)):
            return reject(401, "UNAUTHORIZED", "Missing or invalid integration key.")
        if payload.schema_version != "1.0":
            return reject(422, "SCHEMA_VERSION", "Unsupported schema version.")
        if payload.decision not in CLOUD_DECISIONS or payload.destination != "CLOUD":
            return reject(409, "NOT_AUTHORIZED_FOR_CLOUD", f"Payloads marked {payload.decision} are not accepted.")
        receipt = {
            "receipt_id": f"clk-{uuid.uuid4().hex[:12]}",
            "request_id": payload.request_id,
            "status": "ACCEPTED",
            "simulated": True,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "summary_chars": len(payload.sanitized_summary or ""),
            "transcript_chars": len(payload.sanitized_transcript),
            "entity_categories": payload.entity_categories,
        }
        with lock:
            counters["accepted"] += 1
            receipts.appendleft({**receipt, "payload": payload.model_dump(mode="json")})
        return receipt

    @app.get("/v1/receipts")
    def list_receipts() -> dict:
        """Recent receipts (metadata only) for demonstration."""
        with lock:
            items = [{k: v for k, v in r.items() if k != "payload"} for r in receipts]
        return {"simulated": True, "items": items}

    return app


app = create_mock_cloudlink_app()
