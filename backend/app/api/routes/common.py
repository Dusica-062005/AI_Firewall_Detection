"""Shared request checks for inspect and process."""

from __future__ import annotations

import uuid

from app.api.errors import ApiError
from app.api.middleware import current_request_id
from app.container import Container
from app.schemas.requests import InspectRequest


def check_transcript_request(body: InspectRequest, container: Container) -> str:
    limit = container.settings.max_transcript_chars
    if len(body.transcript) > limit:
        raise ApiError(413, "TRANSCRIPT_TOO_LARGE", f"Transcript exceeds the {limit}-character limit.")
    if container.policy_status["status"] != "READY":
        raise ApiError(503, "POLICY_UNAVAILABLE", "Policy configuration is not loaded; processing is disabled.")
    known = {profile.id for profile, _ in container.policy_service.profiles()}
    if body.profile not in known:
        raise ApiError(422, "UNKNOWN_PROFILE", f"Unknown policy profile '{body.profile}'.")
    return current_request_id() or str(uuid.uuid4())
