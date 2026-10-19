"""Audit API schemas. Contain entity categories and counts, never entity values."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEvent(BaseModel):
    event_id: str
    request_id: str
    created_at: datetime
    operation: str
    mode: str
    profile: str
    channel: str
    decision: str
    status: str
    destination: str
    local_ai_status: str
    cloud_status: str
    policy_version: str
    decisive_policy_id: str
    policy_ids: list[str]
    entity_counts: dict[str, int]
    latency_ms: dict[str, float | None]
    total_latency_ms: float
    error_category: str | None
    transcript_chars: int
    warnings: list[str]
    cloud_receipt_id: str | None


class AuditListResponse(BaseModel):
    items: list[AuditEvent]
    total: int
    page: int
    page_size: int


class AuditPurgeResponse(BaseModel):
    deleted: int
    retention_days: int
