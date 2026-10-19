"""Data-subject request tracker: which AI systems must act, and whether each one has."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from app.compliance.systems import AiSystemService, aware
from app.db.compliance_repositories import DataRequestRepository
from app.db.models import DataRequestRecord
from app.db.repositories import utcnow
from app.schemas.compliance import DataRequest, DataRequestCreate, DataRequestSystem, DataRequestSystemUpdate

# GDPR Art. 12(3): respond without undue delay and within one month.
RESPONSE_DAYS = 30


class DataRequestCompletedError(Exception):
    """The request is complete and can no longer change."""


class UnknownSystemError(Exception):
    def __init__(self, system_ids: list[str]) -> None:
        super().__init__(", ".join(system_ids))
        self.system_ids = system_ids


class InvalidReceivedDateError(Exception):
    """received_at is in the future."""


def to_schema(record: DataRequestRecord, now: datetime) -> DataRequest:
    due = aware(record.due_at)
    completed = aware(record.completed_at) if record.completed_at else None
    systems = [
        DataRequestSystem(
            system_id=s["system_id"],
            system_name=s["system_name"],
            status=s["status"],
            note=s.get("note", ""),
            updated_at=datetime.fromisoformat(s["updated_at"]) if s.get("updated_at") else None,
        )
        for s in (record.systems or [])
    ]
    open_ = record.status == "OPEN"
    return DataRequest(
        request_id=record.request_id,
        request_type=record.request_type,
        subject_reference=record.subject_reference,
        status=record.status,
        received_at=aware(record.received_at),
        due_at=due,
        completed_at=completed,
        days_remaining=int((due - now).total_seconds() / 86400) if open_ else None,  # truncates towards zero
        overdue=open_ and now > due,
        systems_done=sum(1 for s in systems if s.status != "PENDING"),
        systems_total=len(systems),
        systems=systems,
    )


class DataRequestService:
    def __init__(
        self,
        repository: DataRequestRepository,
        systems: AiSystemService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repo = repository
        self._systems = systems
        self._clock = clock

    def list(self, status: str | None = None) -> list[DataRequest]:
        now = self._clock()
        items = [to_schema(r, now) for r in self._repo.list()]
        return [i for i in items if i.status == status] if status else items

    def get(self, request_id: str) -> DataRequest | None:
        record = self._repo.get(request_id)
        return to_schema(record, self._clock()) if record else None

    def create(self, body: DataRequestCreate) -> DataRequest:
        now = self._clock()
        received = aware(body.received_at) if body.received_at else now
        if received > now:
            raise InvalidReceivedDateError()
        by_id = {s.system_id: s for s in self._systems.list() if s.status != "RETIRED"}
        missing = [sid for sid in body.system_ids if sid not in by_id]
        if missing:
            raise UnknownSystemError(missing)
        record = DataRequestRecord(
            request_id=f"dsr-{uuid.uuid4().hex[:12]}",
            request_type=body.request_type,
            subject_reference=body.subject_reference,
            status="OPEN",
            received_at=received,
            due_at=received + timedelta(days=RESPONSE_DAYS),
            systems=[
                {"system_id": sid, "system_name": by_id[sid].name, "status": "PENDING", "note": "", "updated_at": None}
                for sid in body.system_ids
            ],
        )
        self._repo.add(record)
        return to_schema(record, now)

    def update_system(self, request_id: str, system_id: str, body: DataRequestSystemUpdate) -> DataRequest | None:
        """Returns None when the request or the system entry does not exist."""
        record = self._repo.get(request_id)
        if record is None:
            return None
        if record.status == "COMPLETED":
            raise DataRequestCompletedError()
        now = self._clock()
        systems = [dict(s) for s in record.systems or []]
        target = next((s for s in systems if s["system_id"] == system_id), None)
        if target is None:
            return None
        target.update(status=body.status, note=body.note, updated_at=now.isoformat())
        record.systems = systems
        if all(s["status"] != "PENDING" for s in systems):
            record.status = "COMPLETED"
            record.completed_at = now
        self._repo.save(record)
        return to_schema(record, now)
