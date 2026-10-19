"""Mock CloudLink receiver (SIMULATED INTEGRATION).

Runs as a separate process so that a successful handoff means a real HTTP request
reached a separate service:

    uvicorn app.integrations.mock_cloudlink:app --port 8100

It does not connect to any Mitel service. The last 20 payloads are kept in memory, and every
accepted payload is appended to ``RECEIVED_LOG_FILE`` (JSON lines) so leak canaries can
measure what actually arrived at the receiving end.

"Cloud" stand-in: when ``MOCK_CLOUD_MODEL`` is set (for example ``llama3.1:8b``), the
receiver summarizes the tokenized transcript with that larger local model and returns the
tokenized summary. It only ever sees tokens; the firewall re-hydrates the answer locally.
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from threading import Lock

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.ai.summarizer import MAX_SUMMARY_CHARS, build_prompt, clean_output
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


def _cloud_summary(settings: Settings, transcript: str, transport: httpx.BaseTransport | None) -> dict:
    """Summarize with the cloud stand-in model. Returns status, text, model and latency."""
    model = settings.mock_cloud_model
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=settings.ollama_base_url, timeout=settings.mock_cloud_timeout_seconds, transport=transport) as client:
            response = client.post(
                "/api/generate",
                json={"model": model, "prompt": build_prompt(transcript), "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 220}},
            )
        latency = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code == 404:
            return {"status": "MODEL_MISSING", "text": None, "model": model, "latency_ms": latency}
        text = clean_output(str(response.json().get("response", ""))) if response.status_code == 200 else ""
    except httpx.TimeoutException:
        return {"status": "TIMEOUT", "text": None, "model": model, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    except (httpx.HTTPError, ValueError):
        return {"status": "UNAVAILABLE", "text": None, "model": model, "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    if not text or len(text) > MAX_SUMMARY_CHARS:
        return {"status": "INVALID_OUTPUT", "text": None, "model": model, "latency_ms": latency}
    return {"status": "GENERATED", "text": text, "model": model, "latency_ms": latency}


def create_mock_cloudlink_app(
    settings: Settings | None = None, ollama_transport: httpx.BaseTransport | None = None
) -> FastAPI:
    settings = settings or get_settings()
    expected_key = settings.cloudlink_api_key.get_secret_value()
    receipts: deque[dict] = deque(maxlen=MAX_RECEIPTS)
    lock = Lock()
    counters = {"accepted": 0, "rejected": 0}
    log_path = settings.received_log_file

    app = FastAPI(title="Mock CloudLink Receiver (simulated)", version="0.1.0", docs_url="/docs", redoc_url=None)
    app.state.receipts = receipts
    app.state.counters = counters

    def log_received(payload: IncomingHandoff) -> None:
        line = json.dumps({
            "received_at": datetime.now(timezone.utc).isoformat(),
            "request_id": payload.request_id,
            "sanitized_transcript": payload.sanitized_transcript,
            "sanitized_summary": payload.sanitized_summary,
        }, ensure_ascii=False)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with lock, log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

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
            "cloud_model": settings.mock_cloud_model or None,
        }

    @app.post("/v1/handoff")
    def handoff(
        payload: IncomingHandoff,
        x_cloudlink_key: str | None = Header(default=None),
        x_skip_cloud_summary: str | None = Header(default=None),
    ):
        if expected_key and not (x_cloudlink_key and secrets.compare_digest(x_cloudlink_key, expected_key)):
            return reject(401, "UNAUTHORIZED", "Missing or invalid integration key.")
        if payload.schema_version != "1.0":
            return reject(422, "SCHEMA_VERSION", "Unsupported schema version.")
        if payload.decision not in CLOUD_DECISIONS or payload.destination != "CLOUD":
            return reject(409, "NOT_AUTHORIZED_FOR_CLOUD", f"Payloads marked {payload.decision} are not accepted.")
        log_received(payload)
        if settings.mock_cloud_model and x_skip_cloud_summary != "1":
            cloud = _cloud_summary(settings, payload.sanitized_transcript, ollama_transport)
        else:
            cloud = {"status": "DISABLED", "text": None, "model": None, "latency_ms": None}
        receipt = {
            "receipt_id": f"clk-{uuid.uuid4().hex[:12]}",
            "request_id": payload.request_id,
            "status": "ACCEPTED",
            "simulated": True,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "summary_chars": len(payload.sanitized_summary or ""),
            "transcript_chars": len(payload.sanitized_transcript),
            "entity_categories": payload.entity_categories,
            "cloud_summary_status": cloud["status"],
            "cloud_summary": cloud["text"],
            "cloud_model": cloud["model"],
            "cloud_latency_ms": cloud["latency_ms"],
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
