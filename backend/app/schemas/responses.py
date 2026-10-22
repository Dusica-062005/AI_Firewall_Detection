"""Response schemas for health, integrations, processing results, metrics and config."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FinalDecision = Literal["ALLOWED", "REDACTED", "BLOCKED", "LOCAL_ONLY", "PROCESSING_FAILED"]
StepStatus = Literal["COMPLETED", "SKIPPED", "BLOCKED", "FAILED", "WARNING"]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ComponentHealth(BaseModel):
    status: str
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time: datetime
    components: dict[str, ComponentHealth]


class OllamaStatus(BaseModel):
    status: str  # CONNECTED | MODEL_MISSING | UNREACHABLE
    base_url: str
    model: str
    model_available: bool
    available_models: list[str]
    latency_ms: float | None
    message: str


class CloudLinkStatus(BaseModel):
    status: str  # CONNECTED | UNREACHABLE | ERROR
    base_url: str
    simulated: bool = True
    receipts_count: int | None
    cloud_model: str | None = None
    latency_ms: float | None
    message: str


class IntegrationsStatus(BaseModel):
    checked_at: datetime
    ollama: OllamaStatus
    cloudlink: CloudLinkStatus


class EntityResult(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float
    low_confidence: bool
    recognizer: str
    value: str | None = Field(default=None, description="Present only when EXPOSE_DETECTED_VALUES is enabled.")
    action: str
    destination: str
    policy_id: str
    policy_name: str
    reason: str


class MatchedPolicyResult(BaseModel):
    policy_id: str
    name: str
    action: str
    destination: str
    priority: int
    matched_categories: list[str]


class ProcessingStep(BaseModel):
    key: Literal["received", "analyzed", "policy", "protected", "ai", "audited"]
    label: str
    status: StepStatus
    duration_ms: float | None = None
    detail: str


class SummaryInfo(BaseModel):
    status: str  # GENERATED | NOT_AUTHORIZED | SKIPPED_BY_MODE | UNAVAILABLE | MODEL_MISSING | TIMEOUT | INVALID_OUTPUT | ERROR
    text: str | None
    model: str | None
    latency_ms: float | None
    message: str


class ValidationCheckResult(BaseModel):
    name: str
    passed: bool
    detail: str


class OutboundInfo(BaseModel):
    status: str  # SENT | NOT_AUTHORIZED | SKIPPED_BY_MODE | VALIDATION_FAILED | REJECTED | UNAVAILABLE | ERROR
    reached_receiver: bool
    simulated: bool = True
    target: str | None
    payload: dict | None = Field(default=None, description="Exact payload sent, only when a request was made.")
    receiver_response: dict | None
    http_status: int | None
    latency_ms: float | None
    validation: list[ValidationCheckResult]
    message: str


class TokenResult(BaseModel):
    token: str
    entity_type: str
    value: str | None = Field(default=None, description="Present only when EXPOSE_DETECTED_VALUES is enabled.")


class RoutingInfo(BaseModel):
    """Sensitivity-based router outcome (FR-13)."""

    route: Literal["LOCAL", "CLOUD", "NONE"]
    reason: str  # machine-readable code, e.g. kill_switch, low_confidence_entity
    message: str
    kill_switch: bool
    dial: str
    cloud_model: str | None = None
    cloud_summary_status: str | None = None
    cloud_summary: str | None = Field(default=None, description="Tokenized summary returned by the cloud stand-in.")
    cloud_latency_ms: float | None = None


class AgentView(BaseModel):
    """What the agent sees: the summary with tokens restored locally from the vault."""

    status: Literal["REHYDRATED", "TOKENS_ONLY", "NO_SUMMARY"]
    source: Literal["CLOUD", "LOCAL", "NONE"]
    summary: str | None
    tokenized_summary: str | None
    message: str


class ReceiptRef(BaseModel):
    receipt_id: str
    seq: int
    hash: str
    signed: bool


class LatencyBreakdown(BaseModel):
    transcription_ms: float | None = None  # audio calls only; not part of total_ms
    detection_ms: float | None = None
    policy_ms: float | None = None
    protection_ms: float | None = None
    local_ai_ms: float | None = None
    validation_ms: float | None = None
    cloud_ms: float | None = None
    audit_ms: float | None = None
    total_ms: float


class FirewallResult(BaseModel):
    request_id: str
    event_id: str | None
    operation: Literal["INSPECT", "PROCESS"]
    mode: str
    profile: str
    channel: str
    decision: FinalDecision
    status: Literal["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]
    authorized_destination: Literal["NONE", "LOCAL", "CLOUD"]
    policy_version: str | None
    decisive_policy_id: str | None
    error_category: str | None
    reasons: list[str]
    warnings: list[str]
    transcript_chars: int
    entities: list[EntityResult]
    entity_counts: dict[str, int]
    matched_policies: list[MatchedPolicyResult]
    redacted_transcript: str | None
    tokens: list[TokenResult] = Field(default_factory=list)
    summary: SummaryInfo
    outbound: OutboundInfo
    routing: RoutingInfo | None = None
    agent_view: AgentView | None = None
    receipt: ReceiptRef | None = None
    steps: list[ProcessingStep]
    latency: LatencyBreakdown
    created_at: datetime


class LatencyStats(BaseModel):
    count: int
    avg_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class TimeBucket(BaseModel):
    start: datetime
    allowed: int
    redacted: int
    local_only: int
    blocked: int
    failed: int


class MetricsSummary(BaseModel):
    generated_at: datetime
    window_hours: int
    total_requests: int
    decision_counts: dict[str, int]
    status_counts: dict[str, int]
    destination_counts: dict[str, int]
    entity_category_counts: dict[str, int]
    total_entities: int
    cloud_handoffs_sent: int
    local_summaries_generated: int
    latency: dict[str, LatencyStats]
    timeline: list[TimeBucket]


class RecognizerInfo(BaseModel):
    category: str
    description: str
    limitations: str
    sources: list[str]


class SecretInfo(BaseModel):
    configured: bool
    display: str


class AppConfig(BaseModel):
    environment: str
    version: str
    cors_origins: list[str]
    max_transcript_chars: int
    max_request_bytes: int
    detection: dict
    recognizers: list[RecognizerInfo]
    policy: dict
    ollama: dict
    cloudlink: dict
    transcription: dict = Field(default_factory=dict)
    audit: dict
    admin_auth_enabled: bool
    trust: dict = Field(default_factory=dict)


class SampleTranscript(BaseModel):
    id: str
    title: str
    description: str
    profile: str
    channel: str
    transcript: str
