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
