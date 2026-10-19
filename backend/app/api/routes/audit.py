from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.container import Container
from app.db.repositories import AuditFilters
from app.schemas.audit import AuditEvent, AuditListResponse, AuditPurgeResponse
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/audit", tags=["audit"])

Decision = Literal["ALLOWED", "REDACTED", "BLOCKED", "LOCAL_ONLY", "PROCESSING_FAILED"]
Status = Literal["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]
DestinationFilter = Literal["NONE", "LOCAL", "CLOUD"]


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("", response_model=AuditListResponse)
def list_audit(
    container: Container = Depends(get_container),
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(25, ge=1, le=200),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    decision: Decision | None = None,
    policy_id: str | None = Query(None, pattern=r"^[a-z0-9:][a-z0-9:-]{2,63}$"),
    status: Status | None = None,
    destination: DestinationFilter | None = None,
    request_id: str | None = Query(None, pattern=r"^[A-Za-z0-9-]{1,64}$"),
) -> AuditListResponse:
    filters = AuditFilters(
        date_from=_utc(date_from), date_to=_utc(date_to), decision=decision, policy_id=policy_id,
        status=status, destination=destination, request_id=request_id,
    )
    items, total = container.audit_service.list(filters, page, page_size)
    return AuditListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/purge", response_model=AuditPurgeResponse, dependencies=[Depends(require_admin)])
def purge_audit(container: Container = Depends(get_container)) -> AuditPurgeResponse:
    """Apply the configured retention period now."""
    deleted = container.audit_service.purge_expired()
    return AuditPurgeResponse(deleted=deleted, retention_days=container.audit_service.retention_days)


@router.get("/{event_id}", response_model=AuditEvent, responses={404: {"model": ErrorResponse}})
def get_audit_event(
    event_id: str = Path(pattern=r"^evt-[a-f0-9]{16}$"), container: Container = Depends(get_container)
) -> AuditEvent:
    event = container.audit_service.get(event_id)
    if event is None:
        raise ApiError(404, "AUDIT_EVENT_NOT_FOUND", "Audit event not found.")
    return event
