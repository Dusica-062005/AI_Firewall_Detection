from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

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


@router.get("/export", responses={200: {"content": {"application/json": {}, "text/csv": {}}}})
def export_audit(
    container: Container = Depends(get_container),
    format: Literal["json", "csv"] = "json",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Response:
    """Evidence export for an auditor: every audit event in the range, plus (JSON) the signed
    receipts, a fresh chain verification and the public key. Categories and counts only; no
    transcript text or values exist in these records to export."""
    events = container.audit_service.all(AuditFilters(date_from=_utc(date_from), date_to=_utc(date_to)))
    stamp = datetime.now(timezone.utc)
    name = f"audit-evidence-{stamp.strftime('%Y%m%dT%H%M%SZ')}"
    if format == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_COLUMNS)
        for e in events:
            row = e.model_dump(mode="json")
            writer.writerow([
                json.dumps(row[c], sort_keys=True) if isinstance(row[c], (dict, list)) else row[c] for c in CSV_COLUMNS
            ])
        return Response(out.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})

    request_ids = {e.request_id for e in events}
    receipts = [r for r in container.receipts.all() if r.request_id in request_ids]
    chain = container.receipts.verify()
    bundle = {
        "generated_at": stamp.isoformat(),
        "generated_by": "Mitel AI Data Firewall",
        "range": {"from": _utc(date_from).isoformat() if date_from else None,
                  "to": _utc(date_to).isoformat() if date_to else None},
        "privacy": "Audit events and receipts hold categories, counts, decisions and timings only. "
                   "No transcript text or detected values are stored, so none can be exported.",
        "event_count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
        "receipt_count": len(receipts),
        "receipts": [
            {"seq": r.seq, "receipt_id": r.receipt_id, "request_id": r.request_id, "hash": r.hash,
             "prev_hash": r.prev_hash, "signature": r.signature, "key_id": r.key_id, "body": json.loads(r.body)}
            for r in receipts
        ],
        "receipt_chain": {"ok": chain.ok, "count": chain.count, "reason": chain.reason,
                          "verify_offline": "python scripts/verify_chain.py --db <database file> --pubkey <public key>"},
        "receipt_public_key_pem": container.receipts.public_key_pem,
    }
    return Response(json.dumps(bundle, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


CSV_COLUMNS = (
    "event_id", "request_id", "created_at", "operation", "mode", "profile", "channel", "decision", "status",
    "destination", "local_ai_status", "cloud_status", "policy_version", "decisive_policy_id", "policy_ids",
    "entity_counts", "latency_ms", "total_latency_ms", "error_category", "transcript_chars", "warnings",
    "cloud_receipt_id",
)


@router.get("/{event_id}", response_model=AuditEvent, responses={404: {"model": ErrorResponse}})
def get_audit_event(
    event_id: str = Path(pattern=r"^evt-[a-f0-9]{16}$"), container: Container = Depends(get_container)
) -> AuditEvent:
    event = container.audit_service.get(event_id)
    if event is None:
        raise ApiError(404, "AUDIT_EVENT_NOT_FOUND", "Audit event not found.")
    return event
