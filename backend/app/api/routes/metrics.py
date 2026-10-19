from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container
from app.container import Container
from app.schemas.responses import MetricsSummary

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
def metrics_summary(
    container: Container = Depends(get_container), window_hours: int = Query(24, ge=1, le=168)
) -> MetricsSummary:
    """Aggregates over retained audit events; the timeline covers the last ``window_hours``."""
    return container.audit_service.metrics(window_hours)
