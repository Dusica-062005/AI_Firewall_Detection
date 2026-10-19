"""Payload contract between the firewall and the (mock) CloudLink receiver."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CLOUD_DECISIONS = ("ALLOWED", "REDACTED")
REQUEST_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


class CloudHandoffPayload(BaseModel):
    """The only shape the firewall is permitted to send to CloudLink."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    decision: Literal["ALLOWED", "REDACTED"]
    destination: Literal["CLOUD"]
    profile: str = Field(max_length=40)
    channel: str = Field(max_length=10)
    policy_version: str = Field(max_length=40)
    entity_categories: list[str] = Field(default_factory=list, max_length=20)
    sanitized_summary: str | None = Field(default=None, max_length=2000)
    sanitized_transcript: str = Field(max_length=100000)
    created_at: datetime

    def text_fields(self) -> list[str]:
        return [t for t in (self.sanitized_summary, self.sanitized_transcript) if t]
