"""AI incident log: severity-based containment SLA and a fixed four-stage workflow."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from app.compliance.systems import aware
from app.db.compliance_repositories import IncidentRepository
from app.db.models import IncidentRecord
from app.db.repositories import utcnow
from app.schemas.compliance import Incident, IncidentAdvance, IncidentCreate, IncidentTimelineEntry, IncidentUpdate

# Hours allowed from report to containment.
SLA_HOURS = {"CRITICAL": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}
AT_RISK_FRACTION = 0.75

STAGES = ("REPORTED", "CONTAINED", "ROOT_CAUSE_IDENTIFIED", "CLOSED")
_STAGE_ACTION = {
    "CONTAINED": "Contained",
    "ROOT_CAUSE_IDENTIFIED": "Root cause identified",
    "CLOSED": "Closed",
}


class IncidentClosedError(Exception):
    """The incident is already closed and cannot change."""


class IncidentInputError(Exception):
    """A stage change is missing information it requires."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sla_due_at(created_at: datetime, severity: str) -> datetime:
    return created_at + timedelta(hours=SLA_HOURS[severity])


def sla_status(
    created_at: datetime, due_at: datetime, contained_at: datetime | None, now: datetime
) -> tuple[str, int | None]:
    """Return (state, seconds remaining). Remaining is None once the incident is contained."""
    if contained_at is not None:
        return ("MET" if contained_at <= due_at else "MISSED"), None
    remaining = int((due_at - now).total_seconds())
    if remaining < 0:
        return "BREACHED", remaining
    total = (due_at - created_at).total_seconds()
    elapsed = (now - created_at).total_seconds()
    return ("AT_RISK" if total > 0 and elapsed / total >= AT_RISK_FRACTION else "ON_TRACK"), remaining


def to_schema(record: IncidentRecord, now: datetime) -> Incident:
    created = aware(record.created_at)
    due = aware(record.sla_due_at)
    contained = aware(record.contained_at) if record.contained_at else None
    state, remaining = sla_status(created, due, contained, now)
    return Incident(
        incident_id=record.incident_id,
        title=record.title,
        description=record.description,
        incident_type=record.incident_type,
        severity=record.severity,
        status=record.status,
        owner=record.owner,
        ai_system_id=record.ai_system_id,
        related_event_id=record.related_event_id,
        created_at=created,
        updated_at=aware(record.updated_at),
        sla_due_at=due,
        sla_state=state,
        sla_seconds_remaining=remaining,
        contained_at=contained,
        closed_at=aware(record.closed_at) if record.closed_at else None,
        root_cause=record.root_cause,
        resolution=record.resolution,
        timeline=[
            IncidentTimelineEntry(at=datetime.fromisoformat(e["at"]), action=e["action"], note=e.get("note", ""))
            for e in (record.timeline or [])
        ],
    )


def _entry(now: datetime, action: str, note: str = "") -> dict:
    return {"at": now.isoformat(), "action": action, "note": note}


class IncidentService:
    def __init__(self, repository: IncidentRepository, clock: Callable[[], datetime] = utcnow) -> None:
        self._repo = repository
        self._clock = clock

    def list(self, status: str | None = None, severity: str | None = None) -> list[Incident]:
        now = self._clock()
        items = [to_schema(r, now) for r in self._repo.list()]
        if status:
            items = [i for i in items if i.status == status]
        if severity:
            items = [i for i in items if i.severity == severity]
        return items

    def get(self, incident_id: str) -> Incident | None:
        record = self._repo.get(incident_id)
        return to_schema(record, self._clock()) if record else None

    def create(self, body: IncidentCreate) -> Incident:
        now = self._clock()
        record = IncidentRecord(
            incident_id=f"inc-{uuid.uuid4().hex[:12]}",
            title=body.title,
            description=body.description,
            incident_type=body.incident_type,
            severity=body.severity,
            status="REPORTED",
            owner=body.owner,
            ai_system_id=body.ai_system_id,
            related_event_id=body.related_event_id,
            created_at=now,
            updated_at=now,
            sla_due_at=sla_due_at(now, body.severity),
            timeline=[_entry(now, "Reported", f"Severity {body.severity}")],
        )
        self._repo.add(record)
        return to_schema(record, now)

    def advance(self, incident_id: str, body: IncidentAdvance) -> Incident | None:
        record = self._repo.get(incident_id)
        if record is None:
            return None
        if record.status == "CLOSED":
            raise IncidentClosedError()
        now = self._clock()
        target = STAGES[STAGES.index(record.status) + 1]
        if target == "ROOT_CAUSE_IDENTIFIED":
            if not body.root_cause:
                raise IncidentInputError("ROOT_CAUSE_REQUIRED", "Describe the root cause before moving to this stage.")
            record.root_cause = body.root_cause
        elif target == "CLOSED":
            if not body.resolution:
                raise IncidentInputError("RESOLUTION_REQUIRED", "Describe the resolution before closing the incident.")
            record.resolution = body.resolution
            record.closed_at = now
        elif target == "CONTAINED":
            record.contained_at = now
        record.status = target
        record.updated_at = now
        record.timeline = [*(record.timeline or []), _entry(now, _STAGE_ACTION[target], body.note)]
        self._repo.save(record)
        return to_schema(record, now)

    def update(self, incident_id: str, body: IncidentUpdate) -> Incident | None:
        record = self._repo.get(incident_id)
        if record is None:
            return None
        if record.status == "CLOSED":
            raise IncidentClosedError()
        now = self._clock()
        timeline = list(record.timeline or [])
        if body.owner is not None and (body.owner or None) != record.owner:
            record.owner = body.owner or None
            timeline.append(_entry(now, "Owner changed", record.owner or "Unassigned"))
        if body.severity is not None and body.severity != record.severity:
            record.severity = body.severity
            # The SLA clock keeps running from the original report time. Once contained the
            # outcome is fixed, so a later severity change cannot rewrite it.
            if record.contained_at is None:
                record.sla_due_at = sla_due_at(aware(record.created_at), body.severity)
            timeline.append(_entry(now, "Severity changed", body.severity))
        record.timeline = timeline
        record.updated_at = now
        self._repo.save(record)
        return to_schema(record, now)
