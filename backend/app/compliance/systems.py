"""AI system inventory: the register of AI systems that evidence packs and data requests refer to."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.db.compliance_repositories import AiSystemRepository
from app.db.models import AiSystemRecord
from app.db.repositories import utcnow
from app.schemas.compliance import AiSystem, AiSystemCreate


class UnknownCategoryError(Exception):
    def __init__(self, categories: list[str]) -> None:
        super().__init__(", ".join(categories))
        self.categories = categories


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# Seeded on first start. The first two are the firewall's own AI components; the rest are
# clearly labelled samples so the inventory, review gaps and data requests can be demonstrated.
_SEED_SYSTEMS: tuple[dict, ...] = (
    {
        "system_id": "sys-a0000001",
        "name": "Local summarizer (Ollama)",
        "owner": "Platform team",
        "purpose": "Summarizes protected transcripts on local infrastructure. Receives protected text only.",
        "hosting": "LOCAL",
        "data_categories": [],
        "status": "APPROVED",
        "interval": 180,
        "reviewed_days_ago": 20,
    },
    {
        "system_id": "sys-a0000002",
        "name": "CloudLink handoff (mock receiver)",
        "owner": "Integration team",
        "purpose": "Receives sanitized payloads that passed outbound validation. Simulated receiver for the prototype.",
        "hosting": "CLOUD",
        "data_categories": [],
        "status": "APPROVED",
        "interval": 90,
        "reviewed_days_ago": 30,
    },
    {
        "system_id": "sys-a0000003",
        "name": "Contact-centre sentiment assistant (sample)",
        "owner": "Customer Care",
        "purpose": "Scores caller sentiment from live transcripts to prioritize callbacks.",
        "hosting": "CLOUD",
        "data_categories": ["PERSON", "PHONE_NUMBER"],
        "status": "APPROVED",
        "interval": 180,
        "reviewed_days_ago": 45,
    },
    {
        "system_id": "sys-a0000004",
        "name": "CRM reply drafting assistant (sample)",
        "owner": "Sales Operations",
        "purpose": "Drafts follow-up emails from call notes stored in the CRM.",
        "hosting": "CLOUD",
        "data_categories": ["PERSON", "EMAIL_ADDRESS", "LOCATION"],
        "status": "UNDER_REVIEW",
        "interval": 180,
        "reviewed_days_ago": 200,
    },
    {
        "system_id": "sys-a0000005",
        "name": "Voicemail transcription service (sample)",
        "owner": "Unified Communications",
        "purpose": "Transcribes voicemail audio so messages can be searched.",
        "hosting": "LOCAL",
        "data_categories": ["PERSON", "PHONE_NUMBER", "PATIENT_ID"],
        "status": "APPROVED",
        "interval": 120,
        "reviewed_days_ago": 10,
    },
)


def to_schema(record: AiSystemRecord, now: datetime) -> AiSystem:
    last = aware(record.last_reviewed_at)
    due = last + timedelta(days=record.review_interval_days)
    return AiSystem(
        system_id=record.system_id,
        name=record.name,
        owner=record.owner,
        purpose=record.purpose,
        hosting=record.hosting,
        data_categories=list(record.data_categories or []),
        status=record.status,
        review_interval_days=record.review_interval_days,
        last_reviewed_at=last,
        next_review_due=due,
        review_overdue=record.status != "RETIRED" and now > due,
        created_at=aware(record.created_at),
    )


class AiSystemService:
    def __init__(
        self,
        repository: AiSystemRepository,
        known_categories: set[str],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repo = repository
        self._known_categories = known_categories
        self._clock = clock

    def initialize(self) -> None:
        if self._repo.count() > 0:
            return
        now = self._clock()
        for seed in _SEED_SYSTEMS:
            self._repo.add(
                AiSystemRecord(
                    system_id=seed["system_id"],
                    name=seed["name"],
                    owner=seed["owner"],
                    purpose=seed["purpose"],
                    hosting=seed["hosting"],
                    data_categories=list(seed["data_categories"]),
                    status=seed["status"],
                    review_interval_days=seed["interval"],
                    last_reviewed_at=now - timedelta(days=seed["reviewed_days_ago"]),
                    created_at=now,
                )
            )

    def list(self) -> list[AiSystem]:
        now = self._clock()
        return sorted((to_schema(r, now) for r in self._repo.list()), key=lambda s: s.name.lower())

    def get(self, system_id: str) -> AiSystem | None:
        record = self._repo.get(system_id)
        return to_schema(record, self._clock()) if record else None

    def create(self, body: AiSystemCreate) -> AiSystem:
        unknown = [c for c in body.data_categories if c not in self._known_categories]
        if unknown:
            raise UnknownCategoryError(unknown)
        now = self._clock()
        record = AiSystemRecord(
            system_id=f"sys-{uuid.uuid4().hex[:8]}",
            name=body.name,
            owner=body.owner,
            purpose=body.purpose,
            hosting=body.hosting,
            data_categories=body.data_categories,
            status=body.status,
            review_interval_days=body.review_interval_days,
            last_reviewed_at=now,
            created_at=now,
        )
        self._repo.add(record)
        return to_schema(record, now)

    def mark_reviewed(self, system_id: str, status: str | None = None) -> AiSystem | None:
        record = self._repo.get(system_id)
        if record is None:
            return None
        record.last_reviewed_at = self._clock()
        if status:
            record.status = status
        self._repo.save(record)
        return to_schema(record, self._clock())
