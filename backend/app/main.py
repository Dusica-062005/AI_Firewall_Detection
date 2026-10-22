"""Mitel AI Data Firewall - FastAPI application.

    uvicorn app.main:app --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.middleware import RequestContextMiddleware, configure_logging
from app.api.routes import (
    audit,
    canaries,
    compliance,
    health,
    inspect,
    metrics,
    policies,
    process,
    quality,
    system,
    trust,
)
from app.config import APP_VERSION, Settings, get_settings
from app.container import Container, build_container


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    if container is None:
        configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container or build_container(settings)
        yield
        app.state.container.engine.dispose()

    app = FastAPI(
        title="Mitel AI Data Firewall",
        version=APP_VERSION,
        description="Privacy and AI governance gateway for communication workloads (prototype).",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, max_request_bytes=settings.max_request_bytes)
    # Added last so it is the outermost middleware and also decorates error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Admin-Key"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )
    for module in (health, system, inspect, process, policies, audit, metrics, compliance, trust, canaries, quality):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
