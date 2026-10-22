"""Hardware Fit Calculator (Feature 7, FR-10). Pure computation from stored benchmark runs."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_container
from app.api.errors import ApiError
from app.container import Container
from app.schemas.responses import ErrorResponse
from app.sizing.calculator import SizingInput, estimate

router = APIRouter(prefix="/sizing", tags=["sizing"])


class SizingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seats: int = Field(ge=1, le=100000)
    calls_per_hour: int = Field(ge=1, le=10_000_000)
    avg_call_minutes: float = Field(default=5.0, gt=0, le=240)
    peak_factor: float = Field(default=1.5, ge=1, le=10)
    mode: Literal["post_call", "live"] = "post_call"
    benchmark_run_id: str | None = Field(default=None, pattern=r"^bench-[0-9TZ]{16}-[a-f0-9]{6}$")


class SizingResponse(BaseModel):
    status: Literal["OK", "NOT_MEASURED", "NO_FIT"]
    message: str
    inputs: dict
    budget_s: float
    required_rate_per_min: float
    benchmark_run_id: str | None
    formula: dict | None
    recommendation: dict | None
    caveats: list[str]


@router.post("/estimate", response_model=SizingResponse, responses={404: {"model": ErrorResponse}})
def size(body: SizingRequest, container: Container = Depends(get_container)) -> SizingResponse:
    """Size a deployment from the latest completed benchmark (or the one named). Never extrapolates."""
    if body.benchmark_run_id:
        benchmark = container.benchmarks.get(body.benchmark_run_id)
        if benchmark is None or benchmark.status != "COMPLETED":
            raise ApiError(404, "BENCHMARK_NOT_FOUND", "That benchmark run does not exist or is not completed.")
    else:
        benchmark = container.benchmarks.latest(completed_only=True)
    s = container.settings
    inputs = SizingInput(body.seats, body.calls_per_hour, body.avg_call_minutes, body.peak_factor, body.mode)
    return SizingResponse(**estimate(inputs, benchmark, s.live_assist_budget_s, s.post_call_budget_s))
