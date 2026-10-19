"""FastAPI dependencies."""

from __future__ import annotations

import secrets

from fastapi import Header, Request

from app.api.errors import ApiError
from app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


def require_admin(request: Request, x_admin_key: str | None = Header(default=None)) -> None:
    """Authentication boundary for policy and compliance record mutations. Enforced when ADMIN_API_KEY is set."""
    expected = get_container(request).settings.admin_api_key.get_secret_value()
    if not expected:
        return
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise ApiError(401, "UNAUTHORIZED", "A valid X-Admin-Key header is required for this change.")
