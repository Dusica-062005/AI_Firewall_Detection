"""Request schemas. Unknown fields are rejected, so clients cannot submit decisions."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.policy.models import PROFILE_PATTERN, Channel


class ProcessingMode(str, Enum):
    INSPECT = "inspect"  # detect and evaluate policy only
    LOCAL = "local"  # plus local summary when authorized
    FULL = "full"  # plus cloud handoff when authorized


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1, description="Synthetic transcript text.")
    profile: str = Field(default="standard", pattern=PROFILE_PATTERN)
    channel: Channel = "voice"

    @field_validator("transcript")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Transcript must contain text.")
        return value


class ProcessRequest(InspectRequest):
    mode: ProcessingMode = ProcessingMode.FULL
