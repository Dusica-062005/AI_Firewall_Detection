"""Schemas for the latency benchmark (NFR-2, NFR-3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Verdict = Literal["REAL_TIME_CAPABLE", "POST_CALL_WRAP_UP", "NOT_DETERMINED"]


class StartBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls_per_level: int = Field(default=20, ge=1, le=200)
    concurrency: list[int] = Field(default_factory=lambda: [1, 2, 4], min_length=1, max_length=5)
    include_transcription: bool = False
    dial: Literal["max_privacy", "balanced", "max_quality"] | None = None  # None: the operator dial

    @field_validator("concurrency")
    @classmethod
    def _levels(cls, value: list[int]) -> list[int]:
        if any(c < 1 or c > 16 for c in value):
            raise ValueError("Concurrency levels must be between 1 and 16.")
        return value


class StageStats(BaseModel):
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


class BenchmarkLevel(BaseModel):
    concurrency: int
    n_calls: int
    wall_s: float
    calls_per_minute: float | None
    stages: dict[str, StageStats | None]
    failures: dict[str, int]


class BenchmarkRun(BaseModel):
    run_id: str
    status: Literal["RUNNING", "COMPLETED", "FAILED"]
    created_at: datetime
    finished_at: datetime | None
    config: dict
    machine: dict
    models: dict
    cold: dict | None
    levels: list[BenchmarkLevel]
    budget_s: float
    verdict: Verdict | None
    verdict_reason: str | None
    duration_s: float | None
    progress_done: int
    progress_total: int
    error: str | None


class BenchmarkLatest(BaseModel):
    run: BenchmarkRun | None  # the most recent run, any status
    completed: BenchmarkRun | None  # the most recent completed run
