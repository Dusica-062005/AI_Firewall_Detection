"""Outbound adapter for the (mock) CloudLink receiver.

Isolated so it can later be replaced with an approved Mitel integration. The client only
accepts a ValidatedPayload and re-checks it before sending. It never retries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.integrations.contracts import CLOUD_DECISIONS
from app.security.outbound_validator import ValidatedPayload, payload_fingerprint

HANDOFF_PATH = "/v1/handoff"
HEALTH_PATH = "/health"


class CloudLinkRefused(Exception):
    """The client refused to send a payload that failed its own checks."""


@dataclass(frozen=True)
class HandoffResult:
    status: str  # SENT | REJECTED | UNAVAILABLE | ERROR
    latency_ms: float
    http_status: int | None
    receiver_response: dict | None
    message: str


class CloudLinkClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport
        self.requests_sent = 0

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout, transport=self._transport)

    def _headers(self) -> dict[str, str]:
        return {"X-CloudLink-Key": self._api_key} if self._api_key else {}

    async def send(self, validated: ValidatedPayload) -> HandoffResult:
        if not isinstance(validated, ValidatedPayload):
            raise CloudLinkRefused("Only validated payloads can be sent.")
        payload = validated.payload
        if payload_fingerprint(payload) != validated.fingerprint:
            raise CloudLinkRefused("Payload changed after validation.")
        if payload.decision not in CLOUD_DECISIONS or payload.destination != "CLOUD":
            raise CloudLinkRefused("Payload decision does not permit cloud transmission.")
        if payload.request_id != validated.request_id:
            raise CloudLinkRefused("Payload is not bound to the validated request.")

        started = time.perf_counter()
        try:
            async with self._client() as client:
                self.requests_sent += 1
                response = await client.post(
                    HANDOFF_PATH,
                    content=payload.model_dump_json(),
                    headers={**self._headers(), "Content-Type": "application/json"},
                )
        except httpx.TimeoutException:
            return HandoffResult("UNAVAILABLE", _ms(started), None, None, "CloudLink receiver timed out. No retry was attempted.")
        except httpx.HTTPError:
            return HandoffResult("UNAVAILABLE", _ms(started), None, None, "CloudLink receiver is unreachable.")

        latency = _ms(started)
        body = _json_or_none(response)
        if response.status_code == 200 and body and body.get("status") == "ACCEPTED":
            return HandoffResult("SENT", latency, 200, body, "Mock CloudLink receiver accepted the payload.")
        if response.status_code in (401, 403, 409, 422):
            return HandoffResult("REJECTED", latency, response.status_code, body, "Mock CloudLink receiver rejected the payload.")
        return HandoffResult("ERROR", latency, response.status_code, body, "Mock CloudLink receiver returned an unexpected response.")

    async def health(self) -> dict:
        started = time.perf_counter()
        try:
            async with self._client() as client:
                response = await client.get(HEALTH_PATH, timeout=min(self._timeout, 3.0))
            body = _json_or_none(response) or {}
            if response.status_code == 200:
                return {
                    "status": "CONNECTED",
                    "latency_ms": _ms(started),
                    "simulated": bool(body.get("simulated", True)),
                    "receipts_count": body.get("receipts_count"),
                    "message": "Mock CloudLink receiver is reachable.",
                }
            return {"status": "ERROR", "latency_ms": _ms(started), "simulated": True, "receipts_count": None,
                    "message": f"Mock CloudLink receiver returned HTTP {response.status_code}."}
        except httpx.HTTPError:
            return {"status": "UNREACHABLE", "latency_ms": _ms(started), "simulated": True, "receipts_count": None,
                    "message": "Mock CloudLink receiver is not running or not reachable."}


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _json_or_none(response: httpx.Response) -> dict | None:
    try:
        data = response.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None
