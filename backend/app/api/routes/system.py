"""Integration status, safe configuration and synthetic samples."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.config import APP_VERSION
from app.container import Container
from app.samples import SAMPLES
from app.schemas.responses import (
    AppConfig,
    CloudLinkStatus,
    IntegrationsStatus,
    OllamaStatus,
    RecognizerInfo,
    SampleTranscript,
)

router = APIRouter(tags=["system"])


def _secret(value: str) -> dict:
    return {"configured": bool(value), "display": "configured (hidden)" if value else "not configured"}


@router.get("/integrations/status", response_model=IntegrationsStatus)
async def integrations_status(container: Container = Depends(get_container)) -> IntegrationsStatus:
    ollama, cloud = await asyncio.gather(container.ollama.status(), container.cloudlink.health())
    return IntegrationsStatus(
        checked_at=datetime.now(timezone.utc),
        ollama=OllamaStatus(base_url=container.ollama.base_url, **ollama),
        cloudlink=CloudLinkStatus(
            base_url=container.cloudlink.base_url,
            status=cloud["status"],
            simulated=True,
            receipts_count=cloud.get("receipts_count"),
            latency_ms=cloud.get("latency_ms"),
            message=cloud["message"],
        ),
    )


@router.get("/config", response_model=AppConfig)
def app_config(container: Container = Depends(get_container)) -> AppConfig:
    s = container.settings
    return AppConfig(
        environment=s.app_env,
        version=APP_VERSION,
        cors_origins=s.cors_origin_list,
        max_transcript_chars=s.max_transcript_chars,
        max_request_bytes=s.max_request_bytes,
        detection={
            "engine": "Microsoft Presidio",
            "spacy_model": s.spacy_model,
            "status": container.analyzer.status,
            "message": container.analyzer.message,
            "load_seconds": container.analyzer.load_seconds,
            "score_threshold": s.detection_score_threshold,
            "low_confidence_threshold": s.detection_low_confidence_threshold,
            "expose_detected_values": s.expose_detected_values,
            "unmatched_entity_action": s.unmatched_entity_action,
        },
        recognizers=[RecognizerInfo(**r) for r in container.analyzer.describe()],
        policy={
            **container.policy_status,
            "policy_count": len(container.policy_service.list()) if container.policy_status["status"] == "READY" else 0,
            "policy_version": container.policy_service.version() if container.policy_status["status"] == "READY" else None,
            "seed_file": s.policy_seed_file.name,
            "precedence": "BLOCK > LOCAL_ONLY > REDACT > ALLOW; priority breaks ties only; deny by default.",
        },
        ollama={
            "base_url": s.ollama_base_url,
            "model": s.ollama_model,
            "timeout_seconds": s.ollama_timeout_seconds,
            "cloud_fallback": False,
        },
        cloudlink={
            "base_url": s.cloudlink_base_url,
            "timeout_seconds": s.cloudlink_timeout_seconds,
            "simulated": True,
            "api_key": _secret(s.cloudlink_api_key.get_secret_value()),
            "retries": 0,
        },
        audit=container.audit_service.storage_info(),
        admin_auth_enabled=bool(s.admin_api_key.get_secret_value()),
    )


@router.get("/samples", response_model=list[SampleTranscript])
def samples() -> list[SampleTranscript]:
    return SAMPLES
