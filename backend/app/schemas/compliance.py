"""Schemas for the compliance module: AI inventory, incidents, data requests and evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SYSTEM_ID_PATTERN = r"^sys-[a-f0-9]{8}$"
INCIDENT_ID_PATTERN = r"^inc-[a-f0-9]{12}$"
DATA_REQUEST_ID_PATTERN = r"^dsr-[a-f0-9]{12}$"
AUDIT_EVENT_ID_PATTERN = r"^evt-[a-f0-9]{16}$"

Hosting = Literal["LOCAL", "CLOUD"]
SystemStatus = Literal["APPROVED", "UNDER_REVIEW", "RETIRED"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
IncidentType = Literal["WRONG_ANSWER", "DATA_EXPOSURE", "BIASED_OUTPUT", "POLICY_BYPASS", "OTHER"]
IncidentStatus = Literal["REPORTED", "CONTAINED", "ROOT_CAUSE_IDENTIFIED", "CLOSED"]
SlaState = Literal["ON_TRACK", "AT_RISK", "BREACHED", "MET", "MISSED"]
DataRequestType = Literal["ERASURE", "ACCESS"]
DataRequestStatus = Literal["OPEN", "COMPLETED"]
SystemTaskStatus = Literal["PENDING", "DONE", "NOT_HELD"]
FrameworkId = Literal["GDPR", "HIPAA", "ISO_42001", "SOC_2"]
ControlStatus = Literal["PASS", "PARTIAL", "FAIL"]


def _clean(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class _Body(BaseModel):
    """Request bodies reject unknown fields, like the rest of the API."""

    model_config = ConfigDict(extra="forbid")


# ---- AI systems ---------------------------------------------------------------------------


class AiSystemCreate(_Body):
    name: str = Field(min_length=3, max_length=80)
    owner: str = Field(min_length=2, max_length=80)
    purpose: str = Field(min_length=3, max_length=300)
    hosting: Hosting
    data_categories: list[str] = Field(default_factory=list, max_length=20)
    status: SystemStatus = "UNDER_REVIEW"
    review_interval_days: int = Field(default=180, ge=30, le=730)

    @field_validator("name", "owner", "purpose")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("data_categories")
    @classmethod
    def _categories(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(c.strip().upper() for c in value if c.strip()))


class AiSystemReview(_Body):
    """Records a completed review. The approval status only changes when one is given."""

    status: SystemStatus | None = None


class AiSystem(BaseModel):
    system_id: str
    name: str
    owner: str
    purpose: str
    hosting: Hosting
    data_categories: list[str]
    status: SystemStatus
    review_interval_days: int
    last_reviewed_at: datetime
    next_review_due: datetime
    review_overdue: bool
    created_at: datetime


class AiSystemListResponse(BaseModel):
    items: list[AiSystem]
    total: int


# ---- Incidents ----------------------------------------------------------------------------


class IncidentCreate(_Body):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    incident_type: IncidentType
    severity: Severity
    owner: str | None = Field(default=None, max_length=80)
    ai_system_id: str | None = Field(default=None, pattern=SYSTEM_ID_PATTERN)
    related_event_id: str | None = Field(default=None, pattern=AUDIT_EVENT_ID_PATTERN)

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("owner")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class IncidentAdvance(_Body):
    """Move the incident to its next stage. Root cause and resolution gate later stages."""

    note: str = Field(default="", max_length=500)
    root_cause: str | None = Field(default=None, max_length=1000)
    resolution: str | None = Field(default=None, max_length=1000)

    @field_validator("note", "root_cause", "resolution")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


class IncidentUpdate(_Body):
    owner: str | None = Field(default=None, max_length=80)
    severity: Severity | None = None

    @field_validator("owner")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


class IncidentTimelineEntry(BaseModel):
    at: datetime
    action: str
    note: str = ""


class Incident(BaseModel):
    incident_id: str
    title: str
    description: str
    incident_type: IncidentType
    severity: Severity
    status: IncidentStatus
    owner: str | None
    ai_system_id: str | None
    related_event_id: str | None
    created_at: datetime
    updated_at: datetime
    sla_due_at: datetime
    sla_state: SlaState
    sla_seconds_remaining: int | None = Field(description="Negative when overdue. Null once contained.")
    contained_at: datetime | None
    closed_at: datetime | None
    root_cause: str | None
    resolution: str | None
    timeline: list[IncidentTimelineEntry]


class IncidentListResponse(BaseModel):
    items: list[Incident]
    total: int


# ---- Data-subject requests ----------------------------------------------------------------


class DataRequestCreate(_Body):
    request_type: DataRequestType
    subject_reference: str = Field(
        min_length=3, max_length=80, description="Ticket or case reference. Do not enter the person's details."
    )
    system_ids: list[str] = Field(min_length=1, max_length=50)
    received_at: datetime | None = None

    @field_validator("subject_reference")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("system_ids")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class DataRequestSystemUpdate(_Body):
    status: SystemTaskStatus
    note: str = Field(default="", max_length=300)

    @field_validator("note")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class DataRequestSystem(BaseModel):
    system_id: str
    system_name: str
    status: SystemTaskStatus
    note: str = ""
    updated_at: datetime | None


class DataRequest(BaseModel):
    request_id: str
    request_type: DataRequestType
    subject_reference: str
    status: DataRequestStatus
    received_at: datetime
    due_at: datetime
    completed_at: datetime | None
    days_remaining: int | None = Field(description="Negative when overdue. Null once completed.")
    overdue: bool
    systems_done: int
    systems_total: int
    systems: list[DataRequestSystem]


class DataRequestListResponse(BaseModel):
    items: list[DataRequest]
    total: int


# ---- Controls, scores and evidence --------------------------------------------------------


class ControlResult(BaseModel):
    control_id: str
    title: str
    description: str
    reference: str
    status: ControlStatus
    evidence: str
    remediation: str | None = None


class FrameworkScore(BaseModel):
    framework: FrameworkId
    name: str
    score: int = Field(ge=0, le=100)
    pass_count: int
    partial_count: int
    fail_count: int
    total: int
    controls: list[ControlResult]


class ComplianceKpis(BaseModel):
    ai_systems: int
    reviews_overdue: int
    open_incidents: int
    sla_breached: int
    open_data_requests: int
    overdue_data_requests: int


class ComplianceOverview(BaseModel):
    generated_at: datetime
    overall_score: int
    frameworks: list[FrameworkScore]
    kpis: ComplianceKpis


class PolicyRuleEvidence(BaseModel):
    policy_id: str
    name: str
    enabled: bool
    action: str
    destination: str
    categories: list[str]
    profiles: list[str]


class PolicyEvidence(BaseModel):
    policy_version: str
    total: int
    enabled: int
    rules: list[PolicyRuleEvidence]


class AuditEvidence(BaseModel):
    retention_days: int
    event_count: int
    oldest_event_at: str | None
    stores_raw_transcripts: bool
    stores_entity_values: bool
    decision_counts: dict[str, int]


class IncidentEvidence(BaseModel):
    total: int
    open: int
    closed: int
    contained_within_sla: int
    sla_missed: int
    sla_breached_open: int
    by_severity: dict[str, int]


class DataRequestEvidence(BaseModel):
    total: int
    open: int
    completed: int
    completed_on_time: int
    completed_late: int
    overdue_open: int


class EvidencePack(BaseModel):
    framework: FrameworkId
    framework_name: str
    generated_at: datetime
    disclaimer: str
    score: int
    controls: list[ControlResult]
    ai_systems: list[AiSystem]
    policies: PolicyEvidence
    audit: AuditEvidence
    incidents: IncidentEvidence
    data_requests: DataRequestEvidence
