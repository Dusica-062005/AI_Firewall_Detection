from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_container
from app.config import APP_VERSION
from app.container import Container
from app.schemas.responses import ComponentHealth, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(container: Container = Depends(get_container)) -> HealthResponse:
    components: dict[str, ComponentHealth] = {}

    try:
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = ComponentHealth(status="READY", message="Database reachable.")
    except Exception:  # noqa: BLE001
        components["database"] = ComponentHealth(status="ERROR", message="Database is not reachable.")

    components["detection"] = ComponentHealth(status=container.analyzer.status, message=container.analyzer.message)
    components["policies"] = ComponentHealth(**container.policy_status)

    ollama, cloud = await asyncio.gather(container.ollama.status(), container.cloudlink.health())
    components["ollama"] = ComponentHealth(status=ollama["status"], message=ollama["message"])
    components["cloudlink"] = ComponentHealth(status=cloud["status"], message=cloud["message"] + " (simulated)")
    # Optional: only audio requests need it. NOT_LOADED until the first audio request.
    components["transcription"] = ComponentHealth(status=container.transcriber.status, message=container.transcriber.message)

    # Detection, policies and database are required for enforcement. AI services are optional.
    core_ok = all(components[k].status == "READY" for k in ("database", "detection", "policies"))
    optional_ok = components["ollama"].status == "CONNECTED" and components["cloudlink"].status == "CONNECTED"
    return HealthResponse(
        status="ok" if core_ok and optional_ok else "degraded",
        version=APP_VERSION,
        time=datetime.now(timezone.utc),
        components=components,
    )
