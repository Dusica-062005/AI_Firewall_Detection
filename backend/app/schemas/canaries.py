"""Schemas for leak-canary runs (Feature 5, FR-8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["RUNNING", "COMPLETED", "FAILED"]


class StartCanaryRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    normalize_on: bool | None = None  # None: use the NORMALIZE_NUMBERS setting
    set: Literal["main", "holdout"] = "main"  # holdout: new templates, checks for overfitting


class StartedRun(BaseModel):
    run_id: str
    status: RunStatus


class Bucket(BaseModel):
    """Recall and leak rate for one slice of the canary set. Rates are None when n is 0."""

    key: str
    n_calls: int
    n_planted: int
    detected: int
    recall: float | None
    leaked: int
    leak_rate: float | None


class CanaryMetrics(BaseModel):
    overall: Bucket
    by_type: list[Bucket]
    by_difficulty: list[Bucket]
    by_language: list[Bucket]
    by_script: list[Bucket]  # key "hi/native"
    route_counts: dict[str, int]  # CLOUD | LOCAL | NONE -> calls
    route_reasons: dict[str, int]
    payloads_sent: int  # what the firewall reports as delivered
    received_lines: int  # what the receiver logged for this run
    low_confidence_holds: int  # calls kept local only because a detection was low-confidence
    call_errors: int


class CanaryMiss(BaseModel):
    call_id: str
    type: str
    difficulty: str
    language: str
    script: str
    surface: str


class CanaryLeak(CanaryMiss):
    field: str  # sanitized_transcript | sanitized_summary


class CanaryRunSummary(BaseModel):
    run_id: str
    status: RunStatus
    created_at: datetime
    finished_at: datetime | None
    canary_set_version: str
    rule_version: str
    normalize_on: bool
    dial: str
    kill_switch_on: bool
    machine: str
    duration_s: float | None
    progress_done: int
    progress_total: int
    error: str | None
    n_planted: int | None
    recall: float | None
    leak_rate: float | None


class CanaryRunDetail(CanaryRunSummary):
    low_confidence_threshold: float
    metrics: CanaryMetrics | None
    misses: list[CanaryMiss]
    leaks: list[CanaryLeak]
    breach_report_id: str | None = None  # the draft breach report created for this run's leaks


class CompareRow(BaseModel):
    group: str  # overall | type | difficulty | language | script
    key: str
    a: Bucket | None
    b: Bucket | None
    recall_delta: float | None  # b - a
    leak_rate_delta: float | None  # b - a


class CanaryCompare(BaseModel):
    a: CanaryRunSummary
    b: CanaryRunSummary
    rows: list[CompareRow]


class CanarySetSummary(BaseModel):
    version: str
    calls: int
    planted_values: int
    by_language: dict[str, int]
    by_script: dict[str, int]
    by_difficulty: dict[str, int]
    by_type: dict[str, int]
