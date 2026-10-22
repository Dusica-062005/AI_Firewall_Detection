"""SQLAlchemy models. Audit rows hold privacy-safe metadata only: no transcripts or values."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PolicyRecord(Base):
    __tablename__ = "policies"

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=500)
    entity_categories: Mapped[list] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(16))
    destination: Mapped[str] = mapped_column(String(16))
    conditions: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiSystemRecord(Base):
    """Inventory entry for an AI system. Holds descriptive metadata only."""

    __tablename__ = "ai_systems"

    system_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    owner: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(Text)
    hosting: Mapped[str] = mapped_column(String(8))  # LOCAL | CLOUD
    data_categories: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)  # APPROVED | UNDER_REVIEW | RETIRED
    review_interval_days: Mapped[int] = mapped_column(Integer)
    last_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncidentRecord(Base):
    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    incident_type: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_event_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    contained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[list] = mapped_column(JSON)  # [{"at": iso, "action": str, "note": str}]


class DataRequestRecord(Base):
    """Data-subject request. Stores an opaque reference, never the person's details."""

    __tablename__ = "data_requests"

    request_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_type: Mapped[str] = mapped_column(String(10))  # ERASURE | ACCESS
    subject_reference: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), index=True)  # OPEN | COMPLETED
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # [{"system_id", "system_name", "status": PENDING|DONE|NOT_HELD, "note", "updated_at": iso}]
    systems: Mapped[list] = mapped_column(JSON)


class VaultEntryRecord(Base):
    """Token vault (Feature 1). The real value is stored only Fernet-encrypted."""

    __tablename__ = "vault_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    token: Mapped[str] = mapped_column(String(48))
    entity_type: Mapped[str] = mapped_column(String(40))
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RuntimeControlRecord(Base):
    """Operator controls that take effect immediately: kill switch and privacy-utility dial."""

    __tablename__ = "runtime_controls"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReceiptRecord(Base):
    """Signed, hash-chained audit receipt (Feature 2). ``body`` is the exact signed JSON."""

    __tablename__ = "receipts"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    body: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(16), nullable=True)


class CanaryRunRecord(Base):
    """One leak-canary batch (Feature 5). Canary data is synthetic, so misses may hold surface text."""

    __tablename__ = "canary_runs"

    run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), index=True)  # RUNNING | COMPLETED | FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canary_set_version: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str] = mapped_column(String(64))
    normalize_on: Mapped[bool] = mapped_column(Boolean)
    low_confidence_threshold: Mapped[float] = mapped_column(Float)
    dial: Mapped[str] = mapped_column(String(16))
    kill_switch_on: Mapped[bool] = mapped_column(Boolean)
    machine: Mapped[str] = mapped_column(String(200))
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    misses: Mapped[list] = mapped_column(JSON, default=list)
    leaks: Mapped[list] = mapped_column(JSON, default=list)


class QualityRunRecord(Base):
    """One dial quality measurement (Feature 4): embedding similarity per dial position."""

    __tablename__ = "quality_runs"

    run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), index=True)  # RUNNING | COMPLETED | FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sample_ids: Mapped[list] = mapped_column(JSON)
    reference_model: Mapped[str] = mapped_column(String(80))
    local_model: Mapped[str] = mapped_column(String(80))
    cloud_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embed_model: Mapped[str] = mapped_column(String(80))
    kill_switch_on: Mapped[bool] = mapped_column(Boolean)
    machine: Mapped[str] = mapped_column(String(200))
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    positions: Mapped[list] = mapped_column(JSON, default=list)  # per dial position: score and n
    samples: Mapped[list] = mapped_column(JSON, default=list)  # per sample and position


class BenchmarkRunRecord(Base):
    """One latency benchmark (NFR-2, NFR-3): per-stage timings and throughput per concurrency level."""

    __tablename__ = "benchmark_runs"

    run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), index=True)  # RUNNING | COMPLETED | FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict] = mapped_column(JSON)  # calls_per_level, concurrency, include_transcription, dial, samples
    machine: Mapped[dict] = mapped_column(JSON)  # platform, cpu, cores, ram, gpu (only what was detected)
    models: Mapped[dict] = mapped_column(JSON)  # local, cloud stand-in, whisper, Ollama version
    cold: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the first call, excluded from stats
    levels: Mapped[list] = mapped_column(JSON, default=list)  # per concurrency: stage stats, throughput
    budget_s: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualityReferenceRecord(Base):
    """Cached reference summaries of the raw synthetic samples, keyed by sha256(model + prompt + text)."""

    __tablename__ = "quality_references"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    operation: Mapped[str] = mapped_column(String(16))  # INSPECT | PROCESS
    mode: Mapped[str] = mapped_column(String(16))
    profile: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(10))
    decision: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(16), index=True)
    local_ai_status: Mapped[str] = mapped_column(String(24))
    cloud_status: Mapped[str] = mapped_column(String(24))
    policy_version: Mapped[str] = mapped_column(String(40))
    decisive_policy_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_ids: Mapped[list] = mapped_column(JSON)
    policy_ids_index: Mapped[str] = mapped_column(Text)  # ",id1,id2," for filtering
    entity_counts: Mapped[dict] = mapped_column(JSON)  # {"PERSON": 1} - categories only
    latency_ms: Mapped[dict] = mapped_column(JSON)  # per stage
    total_latency_ms: Mapped[float] = mapped_column(Float)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    transcript_chars: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list] = mapped_column(JSON)  # warning codes only
    cloud_receipt_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
