"""Leak-canary runs (Feature 5, FR-8): start a batch, read results, compare two runs."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container, require_admin
from app.api.errors import ApiError
from app.canaries.runner import RunInProgress
from app.container import Container
from app.db.models import CanaryRunRecord
from app.schemas.canaries import (
    Bucket,
    CanaryCompare,
    CanaryRunDetail,
    CanaryRunSummary,
    CanarySetSummary,
    CompareRow,
    StartCanaryRun,
    StartedRun,
)
from app.schemas.responses import ErrorResponse

router = APIRouter(prefix="/canaries", tags=["canaries"])

RUN_ID_PATTERN = r"^canary-[0-9TZ]{16}-[a-f0-9]{6}$"
COMPARE_GROUPS = (("type", "by_type"), ("difficulty", "by_difficulty"), ("language", "by_language"), ("script", "by_script"))


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _summary(r: CanaryRunRecord) -> CanaryRunSummary:
    overall = (r.metrics or {}).get("overall") if r.status == "COMPLETED" else None
    return CanaryRunSummary(
        run_id=r.run_id, status=r.status, created_at=_aware(r.created_at), finished_at=_aware(r.finished_at),  # type: ignore[arg-type]
        canary_set_version=r.canary_set_version, rule_version=r.rule_version, normalize_on=r.normalize_on, dial=r.dial,
        kill_switch_on=r.kill_switch_on, machine=r.machine, duration_s=r.duration_s, progress_done=r.progress_done,
        progress_total=r.progress_total, error=r.error,
        n_planted=overall["n_planted"] if overall else None,
        recall=overall["recall"] if overall else None,
        leak_rate=overall["leak_rate"] if overall else None,
    )


def _detail(r: CanaryRunRecord) -> CanaryRunDetail:
    return CanaryRunDetail(
        **_summary(r).model_dump(),
        low_confidence_threshold=r.low_confidence_threshold,
        metrics=r.metrics if r.status == "COMPLETED" else None,
        misses=r.misses or [],
        leaks=r.leaks or [],
    )


def _get(container: Container, run_id: str) -> CanaryRunRecord:
    record = container.canaries.get(run_id)
    if record is None:
        raise ApiError(404, "CANARY_RUN_NOT_FOUND", f"Canary run {run_id} not found.")
    return record


@router.get("/set", response_model=CanarySetSummary)
def canary_set(container: Container = Depends(get_container)) -> CanarySetSummary:
    return CanarySetSummary(**container.canaries.canary_set().summary())


@router.post(
    "/runs", response_model=StartedRun, status_code=202, dependencies=[Depends(require_admin)],
    responses={409: {"model": ErrorResponse}},
)
def start_run(body: StartCanaryRun | None = None, container: Container = Depends(get_container)) -> StartedRun:
    """Run every canary call through the real pipeline in the background."""
    body = body or StartCanaryRun()
    try:
        run_id = container.canaries.start(body.rule_version, body.normalize_on)
    except RunInProgress as exc:
        raise ApiError(409, "CANARY_RUN_IN_PROGRESS", str(exc)) from None
    return StartedRun(run_id=run_id, status="RUNNING")


@router.get("/runs", response_model=list[CanaryRunSummary])
def list_runs(container: Container = Depends(get_container)) -> list[CanaryRunSummary]:
    return [_summary(r) for r in container.canaries.list()]


@router.get("/runs/{run_id}", response_model=CanaryRunDetail, responses={404: {"model": ErrorResponse}})
def get_run(run_id: str = Path(pattern=RUN_ID_PATTERN), container: Container = Depends(get_container)) -> CanaryRunDetail:
    return _detail(_get(container, run_id))


@router.get("/compare", response_model=CanaryCompare, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def compare(
    a: str = Query(pattern=RUN_ID_PATTERN), b: str = Query(pattern=RUN_ID_PATTERN),
    container: Container = Depends(get_container),
) -> CanaryCompare:
    """Side-by-side metrics. Deltas are b minus a."""
    run_a, run_b = _get(container, a), _get(container, b)
    if run_a.status != "COMPLETED" or run_b.status != "COMPLETED":
        raise ApiError(409, "CANARY_RUN_NOT_COMPLETED", "Both runs must be completed to compare them.")
    rows = [_row("overall", "all", run_a.metrics["overall"], run_b.metrics["overall"])]
    for group, field in COMPARE_GROUPS:
        left = {x["key"]: x for x in run_a.metrics[field]}
        right = {x["key"]: x for x in run_b.metrics[field]}
        rows += [_row(group, key, left.get(key), right.get(key)) for key in sorted(left.keys() | right.keys())]
    return CanaryCompare(a=_summary(run_a), b=_summary(run_b), rows=rows)


def _row(group: str, key: str, a: dict | None, b: dict | None) -> CompareRow:
    def delta(name: str) -> float | None:
        if not a or not b or a[name] is None or b[name] is None:
            return None
        return round(b[name] - a[name], 4)

    return CompareRow(
        group=group, key=key, a=Bucket(**a) if a else None, b=Bucket(**b) if b else None,
        recall_delta=delta("recall"), leak_rate_delta=delta("leak_rate"),
    )
