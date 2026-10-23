"""Audit recording and metrics aggregation.

AuditEntry has no field that can hold transcript text or entity values, so a routine
audit event cannot contain them by construction.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.models import AuditEventRecord
from app.db.repositories import AuditFilters, AuditRepository, utcnow
from app.schemas.audit import AuditEvent
from app.schemas.responses import LatencyStats, MetricsSummary, TimeBucket

DECISIONS = ("ALLOWED", "REDACTED", "LOCAL_ONLY", "BLOCKED", "PROCESSING_FAILED")


@dataclass(frozen=True)
class AuditEntry:
    request_id: str
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
    policy_ids: tuple[str, ...]
    entity_counts: dict[str, int]
    latency_ms: dict[str, float | None]
    total_latency_ms: float
    error_category: str | None
    transcript_chars: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
    cloud_receipt_id: str | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_schema(record: AuditEventRecord) -> AuditEvent:
    return AuditEvent(
        event_id=record.event_id,
        request_id=record.request_id,
        created_at=_aware(record.created_at),
        operation=record.operation,
        mode=record.mode,
        profile=record.profile,
        channel=record.channel,
        decision=record.decision,
        status=record.status,
        destination=record.destination,
        local_ai_status=record.local_ai_status,
        cloud_status=record.cloud_status,
        policy_version=record.policy_version,
        decisive_policy_id=record.decisive_policy_id,
        policy_ids=list(record.policy_ids or []),
        entity_counts=dict(record.entity_counts or {}),
        latency_ms=dict(record.latency_ms or {}),
        total_latency_ms=record.total_latency_ms,
        error_category=record.error_category,
        transcript_chars=record.transcript_chars,
        warnings=list(record.warnings or []),
        cloud_receipt_id=record.cloud_receipt_id,
    )


def _stats(values: list[float]) -> LatencyStats:
    if not values:
        return LatencyStats(count=0, avg_ms=None, p50_ms=None, p95_ms=None, max_ms=None)
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, round(0.95 * len(ordered)) - 1))
    return LatencyStats(
        count=len(ordered),
        avg_ms=round(statistics.fmean(ordered), 2),
        p50_ms=round(statistics.median(ordered), 2),
        p95_ms=round(ordered[p95_index], 2),
        max_ms=round(ordered[-1], 2),
    )


class AuditService:
    def __init__(self, repository: AuditRepository, retention_days: int) -> None:
        self._repo = repository
        self.retention_days = retention_days

    def record(self, entry: AuditEntry) -> str:
        event_id = f"evt-{uuid.uuid4().hex[:16]}"
        self._repo.add(
            AuditEventRecord(
                event_id=event_id,
                request_id=entry.request_id,
                created_at=utcnow(),
                operation=entry.operation,
                mode=entry.mode,
                profile=entry.profile,
                channel=entry.channel,
                decision=entry.decision,
                status=entry.status,
                destination=entry.destination,
                local_ai_status=entry.local_ai_status,
                cloud_status=entry.cloud_status,
                policy_version=entry.policy_version,
                decisive_policy_id=entry.decisive_policy_id,
                policy_ids=list(entry.policy_ids),
                policy_ids_index="," + ",".join(entry.policy_ids) + ",",
                entity_counts=dict(entry.entity_counts),
                latency_ms=dict(entry.latency_ms),
                total_latency_ms=entry.total_latency_ms,
                error_category=entry.error_category,
                transcript_chars=entry.transcript_chars,
                warnings=list(entry.warnings),
                cloud_receipt_id=entry.cloud_receipt_id,
            )
        )
        return event_id

    def list(self, filters: AuditFilters, page: int, page_size: int) -> tuple[list[AuditEvent], int]:
        rows, total = self._repo.query(filters, page, page_size)
        return [to_schema(r) for r in rows], total

    def all(self, filters: AuditFilters) -> list[AuditEvent]:
        """Every matching event, oldest first (for evidence export)."""
        events: list[AuditEvent] = []
        page = 1
        while True:
            rows, total = self._repo.query(filters, page, 500)
            events += [to_schema(r) for r in rows]
            if not rows or len(events) >= total:
                break
            page += 1
        return sorted(events, key=lambda e: e.created_at)

    def get(self, event_id: str) -> AuditEvent | None:
        row = self._repo.get(event_id)
        return to_schema(row) if row else None

    def purge_expired(self) -> int:
        return self._repo.purge_older_than(utcnow() - timedelta(days=self.retention_days))

    def storage_info(self) -> dict:
        oldest = self._repo.oldest()
        return {
            "retention_days": self.retention_days,
            "event_count": self._repo.count(),
            "oldest_event_at": oldest.isoformat() if oldest else None,
            "stores_raw_transcripts": False,
            "stores_entity_values": False,
        }

    def metrics(self, window_hours: int = 24) -> MetricsSummary:
        now = utcnow()
        records = self._repo.since(None)
        decisions = Counter(r.decision for r in records)
        statuses = Counter(r.status for r in records)
        destinations = Counter(r.destination for r in records)
        entities: Counter[str] = Counter()
        for r in records:
            entities.update({k: int(v) for k, v in (r.entity_counts or {}).items()})

        def stage(name: str) -> list[float]:
            return [float(r.latency_ms[name]) for r in records if (r.latency_ms or {}).get(name) is not None]

        latency = {
            "total": _stats([r.total_latency_ms for r in records]),
            "detection": _stats(stage("detection_ms")),
            "policy": _stats(stage("policy_ms")),
            "local_ai": _stats(stage("local_ai_ms")),
            "cloud": _stats(stage("cloud_ms")),
        }

        start_hour = (now - timedelta(hours=window_hours - 1)).replace(minute=0, second=0, microsecond=0)
        buckets = {start_hour + timedelta(hours=i): Counter() for i in range(window_hours)}
        for r in records:
            created = _aware(r.created_at).replace(minute=0, second=0, microsecond=0)
            if created in buckets:
                buckets[created][r.decision] += 1
        timeline = [
            TimeBucket(
                start=start,
                allowed=c["ALLOWED"],
                redacted=c["REDACTED"],
                local_only=c["LOCAL_ONLY"],
                blocked=c["BLOCKED"],
                failed=c["PROCESSING_FAILED"],
            )
            for start, c in buckets.items()
        ]

        return MetricsSummary(
            generated_at=now,
            window_hours=window_hours,
            total_requests=len(records),
            decision_counts={d: decisions.get(d, 0) for d in DECISIONS},
            status_counts=dict(statuses),
            destination_counts={d: destinations.get(d, 0) for d in ("NONE", "LOCAL", "CLOUD")},
            entity_category_counts=dict(entities.most_common()),
            total_entities=sum(entities.values()),
            cloud_handoffs_sent=sum(1 for r in records if r.cloud_status == "SENT"),
            local_summaries_generated=sum(1 for r in records if r.local_ai_status == "GENERATED"),
            latency=latency,
            timeline=timeline,
        )
