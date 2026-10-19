"""Repositories encapsulate all database access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditEventRecord, PolicyRecord
from app.policy.models import Policy, PolicyDefinition


class RepositoryError(Exception):
    """A database operation failed."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _to_policy(record: PolicyRecord) -> Policy:
    return Policy.model_validate(
        {
            "policy_id": record.policy_id,
            "name": record.name,
            "description": record.description,
            "enabled": record.enabled,
            "priority": record.priority,
            "entity_categories": record.entity_categories,
            "action": record.action,
            "destination": record.destination,
            "conditions": record.conditions,
            "version": record.version,
            "created_at": _aware(record.created_at),
            "updated_at": _aware(record.updated_at),
        }
    )


def _apply(record: PolicyRecord, definition: PolicyDefinition) -> None:
    record.name = definition.name
    record.description = definition.description
    record.enabled = definition.enabled
    record.priority = definition.priority
    record.entity_categories = list(definition.entity_categories)
    record.action = definition.action.value
    record.destination = definition.destination.value
    record.conditions = definition.conditions.model_dump(mode="json")


class PolicyRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def list(self) -> list[Policy]:
        with self._sessions() as s:
            rows = s.scalars(select(PolicyRecord).order_by(PolicyRecord.priority, PolicyRecord.policy_id)).all()
            return [_to_policy(r) for r in rows]

    def get(self, policy_id: str) -> Policy | None:
        with self._sessions() as s:
            row = s.get(PolicyRecord, policy_id)
            return _to_policy(row) if row else None

    def count(self) -> int:
        with self._sessions() as s:
            return s.scalar(select(func.count()).select_from(PolicyRecord)) or 0

    def create(self, policy_id: str, definition: PolicyDefinition) -> Policy:
        now = utcnow()
        with self._sessions.begin() as s:
            if s.get(PolicyRecord, policy_id) is not None:
                raise KeyError(policy_id)
            record = PolicyRecord(policy_id=policy_id, version=1, created_at=now, updated_at=now)
            _apply(record, definition)
            s.add(record)
        return self.get(policy_id)  # type: ignore[return-value]

    def update(self, policy_id: str, definition: PolicyDefinition) -> Policy | None:
        with self._sessions.begin() as s:
            record = s.get(PolicyRecord, policy_id)
            if record is None:
                return None
            _apply(record, definition)
            record.version += 1
            record.updated_at = utcnow()
        return self.get(policy_id)

    def delete(self, policy_id: str) -> bool:
        with self._sessions.begin() as s:
            record = s.get(PolicyRecord, policy_id)
            if record is None:
                return False
            s.delete(record)
        return True

    def replace_all(self, seeds: list[tuple[str, PolicyDefinition]]) -> list[Policy]:
        now = utcnow()
        with self._sessions.begin() as s:
            s.execute(delete(PolicyRecord))
            for policy_id, definition in seeds:
                record = PolicyRecord(policy_id=policy_id, version=1, created_at=now, updated_at=now)
                _apply(record, definition)
                s.add(record)
        return self.list()


@dataclass
class AuditFilters:
    date_from: datetime | None = None
    date_to: datetime | None = None
    decision: str | None = None
    policy_id: str | None = None
    status: str | None = None
    destination: str | None = None
    request_id: str | None = None


class AuditRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def add(self, record: AuditEventRecord) -> None:
        with self._sessions.begin() as s:
            s.add(record)

    def get(self, event_id: str) -> AuditEventRecord | None:
        with self._sessions() as s:
            return s.get(AuditEventRecord, event_id)

    def query(self, filters: AuditFilters, page: int, page_size: int) -> tuple[list[AuditEventRecord], int]:
        stmt = select(AuditEventRecord)
        if filters.date_from:
            stmt = stmt.where(AuditEventRecord.created_at >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(AuditEventRecord.created_at <= filters.date_to)
        if filters.decision:
            stmt = stmt.where(AuditEventRecord.decision == filters.decision)
        if filters.status:
            stmt = stmt.where(AuditEventRecord.status == filters.status)
        if filters.destination:
            stmt = stmt.where(AuditEventRecord.destination == filters.destination)
        if filters.request_id:
            stmt = stmt.where(AuditEventRecord.request_id.contains(filters.request_id))
        if filters.policy_id:
            stmt = stmt.where(AuditEventRecord.policy_ids_index.contains(f",{filters.policy_id},"))
        with self._sessions() as s:
            total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = s.scalars(
                stmt.order_by(AuditEventRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return list(rows), total

    def since(self, since: datetime | None = None) -> list[AuditEventRecord]:
        stmt = select(AuditEventRecord).order_by(AuditEventRecord.created_at)
        if since:
            stmt = stmt.where(AuditEventRecord.created_at >= since)
        with self._sessions() as s:
            return list(s.scalars(stmt).all())

    def purge_older_than(self, cutoff: datetime) -> int:
        with self._sessions.begin() as s:
            result = s.execute(delete(AuditEventRecord).where(AuditEventRecord.created_at < cutoff))
            return result.rowcount or 0

    def oldest(self) -> datetime | None:
        with self._sessions() as s:
            value = s.scalar(select(func.min(AuditEventRecord.created_at)))
            return _aware(value) if value else None

    def count(self) -> int:
        with self._sessions() as s:
            return s.scalar(select(func.count()).select_from(AuditEventRecord)) or 0
