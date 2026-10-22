"""Schemas for the dial quality score (Feature 4, FR-7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QUALITY_NOTE = (
    "The score measures how close the protected summary is to the summary of the raw text. "
    "It is a similarity number, not a human quality rating."
)


class StartQualityRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)


class StartedQualityRun(BaseModel):
    run_id: str
    status: Literal["RUNNING", "COMPLETED", "FAILED"]


class PositionScore(BaseModel):
    position: Literal["max_privacy", "balanced", "max_quality"]
    score: float | None  # mean cosine similarity, 2 decimals; None when no sample produced a summary
    n: int  # samples that produced a summary
    n_null: int  # samples with no summary at this position


class SampleScore(BaseModel):
    sample_id: str
    title: str
    position: Literal["max_privacy", "balanced", "max_quality"]
    similarity: float | None
    decision: str
    route: str
    source: str
    summary_status: str


class QualityRun(BaseModel):
    run_id: str
    status: Literal["RUNNING", "COMPLETED", "FAILED"]
    created_at: datetime
    finished_at: datetime | None
    sample_ids: list[str]
    reference_model: str
    local_model: str
    cloud_model: str | None
    embed_model: str
    kill_switch_on: bool
    machine: str
    duration_s: float | None
    progress_done: int
    progress_total: int
    error: str | None
    positions: list[PositionScore]
    samples: list[SampleScore]
    note: str = QUALITY_NOTE


class QualityLatest(BaseModel):
    run: QualityRun | None  # the most recent run, any status
    completed: QualityRun | None  # the most recent completed run: the scores to show
