"""Latency benchmark (NFR-2, NFR-3)."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.benchmark.runner import BenchmarkInProgress
from app.container import Container
from app.db.models import BenchmarkRunRecord
from app.schemas.benchmarks import BenchmarkLatest, BenchmarkRun, StartBenchmark
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def to_run(r: BenchmarkRunRecord | None) -> BenchmarkRun | None:
    if r is None:
        return None
    return BenchmarkRun(
        run_id=r.run_id, status=r.status, created_at=_aware(r.created_at), finished_at=_aware(r.finished_at),  # type: ignore[arg-type]
        config=r.config, machine=r.machine, models=r.models, cold=r.cold, levels=r.levels or [], budget_s=r.budget_s,
        verdict=r.verdict, verdict_reason=r.verdict_reason, duration_s=r.duration_s,  # type: ignore[arg-type]
        progress_done=r.progress_done, progress_total=r.progress_total, error=r.error,
    )


@router.post("/runs", status_code=202, dependencies=[Depends(require_admin)], responses={409: {"model": ErrorResponse}})
def start_run(body: StartBenchmark | None = None, container: Container = Depends(get_container)) -> dict:
    """Time the real pipeline in the background. Each call also writes an audit event and a receipt."""
    body = body or StartBenchmark()
    try:
        run_id = container.benchmarks.start(body.calls_per_level, body.concurrency, body.include_transcription, body.dial)
    except BenchmarkInProgress as exc:
        raise ApiError(409, "BENCHMARK_IN_PROGRESS", str(exc)) from None
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/runs", response_model=list[BenchmarkRun])
def list_runs(container: Container = Depends(get_container)) -> list[BenchmarkRun]:
    return [to_run(r) for r in container.benchmarks.list()]


@router.get("/latest", response_model=BenchmarkLatest)
def latest(container: Container = Depends(get_container)) -> BenchmarkLatest:
    return BenchmarkLatest(
        run=to_run(container.benchmarks.latest()), completed=to_run(container.benchmarks.latest(completed_only=True))
    )


@router.get("/runs/{run_id}", response_model=BenchmarkRun, responses={404: {"model": ErrorResponse}})
def get_run(
    run_id: str = Path(pattern=r"^bench-[0-9TZ]{16}-[a-f0-9]{6}$"), container: Container = Depends(get_container)
) -> BenchmarkRun:
    record = container.benchmarks.get(run_id)
    if record is None:
        raise ApiError(404, "BENCHMARK_NOT_FOUND", f"Benchmark run {run_id} not found.")
    return to_run(record)
