"""Breach Report Generator (Feature 8, FR-11). Drafts only: nothing is ever sent, filed or emailed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.compliance.breach_reports import ReportSourceError, render_markdown
from app.container import Container
from app.db.models import BreachReportRecord
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/breach-reports", tags=["breach reports"])
ReportId = Path(pattern=r"^brr-[a-f0-9]{12}$")
ERRORS = {401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
STATUS = {"CANARY_RUN_NOT_FOUND": 404, "INCIDENT_NOT_FOUND": 404}


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["canary_run", "incident", "window"]
    ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{4,64}$")  # canary run ID or incident ID
    start: datetime | None = Field(default=None, alias="from")
    end: datetime | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def _complete(self) -> "DraftRequest":
        if self.source in ("canary_run", "incident") and not self.ref:
            raise ValueError("ref is required for this source.")
        if self.source == "window" and not (self.start and self.end):
            raise ValueError("from and to are required for a time window.")
        if self.start and self.end and self.start > self.end:
            raise ValueError("from must be before to.")
        return self


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=2, max_length=80)
    decision: Literal["REVIEWED", "WITHDRAWN"] = "REVIEWED"
    note: str = Field(default="", max_length=1000)


class BreachReport(BaseModel):
    report_id: str
    status: Literal["DRAFT", "REVIEWED", "WITHDRAWN"]
    created_at: datetime
    updated_at: datetime
    source_type: str
    source_ref: str | None
    query: dict
    content: dict
    incident_id: str | None
    reviewer: str | None
    reviewed_at: datetime | None
    review_note: str | None


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _out(r: BreachReportRecord) -> BreachReport:
    return BreachReport(
        report_id=r.report_id, status=r.status, created_at=_aware(r.created_at), updated_at=_aware(r.updated_at),  # type: ignore[arg-type]
        source_type=r.source_type, source_ref=r.source_ref, query=r.query, content=r.content, incident_id=r.incident_id,
        reviewer=r.reviewer, reviewed_at=_aware(r.reviewed_at), review_note=r.review_note,
    )


def _get(container: Container, report_id: str) -> BreachReportRecord:
    record = container.breach_reports.get(report_id)
    if record is None:
        raise ApiError(404, "BREACH_REPORT_NOT_FOUND", "Breach report not found.")
    return record


@router.post("", response_model=BreachReport, status_code=201, dependencies=[Depends(require_admin)], responses=ERRORS)
def draft(body: DraftRequest, container: Container = Depends(get_container)) -> BreachReport:
    """Draft a report from stored records for a compliance officer to review. Nothing is sent."""
    start = body.start.astimezone(timezone.utc) if body.start else None
    end = body.end.astimezone(timezone.utc) if body.end else None
    try:
        return _out(container.breach_reports.draft(body.source, body.ref, start, end))
    except ReportSourceError as exc:
        raise ApiError(STATUS.get(exc.code, 422), exc.code, exc.message) from None


@router.get("", response_model=list[BreachReport])
def list_reports(container: Container = Depends(get_container)) -> list[BreachReport]:
    return [_out(r) for r in container.breach_reports.list()]


@router.get("/{report_id}", response_model=BreachReport, responses=ERRORS)
def get_report(report_id: str = ReportId, container: Container = Depends(get_container)) -> BreachReport:
    return _out(_get(container, report_id))


@router.get("/{report_id}/markdown", response_class=PlainTextResponse, responses=ERRORS)
def markdown(report_id: str = ReportId, container: Container = Depends(get_container)) -> PlainTextResponse:
    return PlainTextResponse(render_markdown(_get(container, report_id)), media_type="text/markdown")


@router.get("/{report_id}/verify", responses=ERRORS)
def verify(report_id: str = ReportId, container: Container = Depends(get_container)) -> dict:
    """Recompute every count from the records and compare it with the report."""
    _get(container, report_id)
    return container.breach_reports.verify(report_id)


@router.post("/{report_id}/review", response_model=BreachReport, dependencies=[Depends(require_admin)], responses=ERRORS)
def review(body: ReviewRequest, report_id: str = ReportId, container: Container = Depends(get_container)) -> BreachReport:
    """Record the reviewer's decision. Reviewing files nothing; notification stays a human step."""
    _get(container, report_id)
    return _out(container.breach_reports.review(report_id, body.reviewer, body.decision, body.note))


@router.post("/{report_id}/incident", response_model=BreachReport, dependencies=[Depends(require_admin)], responses=ERRORS)
def create_incident(report_id: str = ReportId, container: Container = Depends(get_container)) -> BreachReport:
    """Open a DATA_EXPOSURE incident from this report and link the two."""
    record = _get(container, report_id)
    if record.incident_id:
        raise ApiError(409, "INCIDENT_ALREADY_LINKED", f"Incident {record.incident_id} is already linked.")
    return _out(container.breach_reports.create_incident(report_id))
