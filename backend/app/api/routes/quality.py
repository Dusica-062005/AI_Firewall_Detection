"""Dial quality measurement (Feature 4, FR-7)."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.container import Container
from app.db.models import QualityRunRecord
from app.quality.service import QualityRunInProgress
from app.schemas.quality import QualityLatest, QualityRun, StartedQualityRun, StartQualityRun
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/quality", tags=["quality"])


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _run(r: QualityRunRecord | None) -> QualityRun | None:
    if r is None:
        return None
    return QualityRun(
        run_id=r.run_id, status=r.status, created_at=_aware(r.created_at), finished_at=_aware(r.finished_at),  # type: ignore[arg-type]
        sample_ids=r.sample_ids, reference_model=r.reference_model, local_model=r.local_model, cloud_model=r.cloud_model,
        embed_model=r.embed_model, kill_switch_on=r.kill_switch_on, machine=r.machine, duration_s=r.duration_s,
        progress_done=r.progress_done, progress_total=r.progress_total, error=r.error,
        positions=r.positions or [], samples=r.samples or [],
    )


@router.post(
    "/runs", response_model=StartedQualityRun, status_code=202, dependencies=[Depends(require_admin)],
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def start_run(body: StartQualityRun | None = None, container: Container = Depends(get_container)) -> StartedQualityRun:
    """Measure the summary quality of each dial position in the background."""
    body = body or StartQualityRun()
    try:
        run_id = container.quality.start(body.sample_ids)
    except QualityRunInProgress as exc:
        raise ApiError(409, "QUALITY_RUN_IN_PROGRESS", str(exc)) from None
    except ValueError as exc:
        raise ApiError(422, "UNKNOWN_SAMPLE", str(exc)) from None
    return StartedQualityRun(run_id=run_id, status="RUNNING")


@router.get("/latest", response_model=QualityLatest)
def latest(container: Container = Depends(get_container)) -> QualityLatest:
    return QualityLatest(run=_run(container.quality.latest()), completed=_run(container.quality.latest(completed_only=True)))


@router.get("/runs/{run_id}", response_model=QualityRun, responses={404: {"model": ErrorResponse}})
def get_run(
    run_id: str = Path(pattern=r"^quality-[0-9TZ]{16}-[a-f0-9]{6}$"), container: Container = Depends(get_container)
) -> QualityRun:
    record = container.quality.get(run_id)
    if record is None:
        raise ApiError(404, "QUALITY_RUN_NOT_FOUND", f"Quality run {run_id} not found.")
    return _run(record)
