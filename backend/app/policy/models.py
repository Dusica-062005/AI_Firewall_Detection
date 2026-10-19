"""Policy domain model shared by the engine, the repository and the API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ANY_CATEGORY = "ANY"
PROFILE_PATTERN = r"^[a-z0-9][a-z0-9-]{1,39}$"
POLICY_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{2,63}$"

Channel = Literal["voice", "chat", "email", "sms"]


class Action(str, Enum):
    ALLOW = "ALLOW"
    REDACT = "REDACT"
    LOCAL_ONLY = "LOCAL_ONLY"
    BLOCK = "BLOCK"

    @property
    def restrictiveness(self) -> int:
        return _ACTION_RANK[self]


class Destination(str, Enum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"

    @property
    def reach(self) -> int:
        return _DESTINATION_RANK[self]


_ACTION_RANK = {Action.ALLOW: 0, Action.REDACT: 1, Action.LOCAL_ONLY: 2, Action.BLOCK: 3}
_DESTINATION_RANK = {Destination.NONE: 0, Destination.LOCAL: 1, Destination.CLOUD: 2}

# Destinations each action may declare. BLOCK can never reach a model and LOCAL_ONLY can
# never reach the cloud, whatever the stored destination says.
ALLOWED_DESTINATIONS: dict[Action, set[Destination]] = {
    Action.ALLOW: {Destination.LOCAL, Destination.CLOUD},
    Action.REDACT: {Destination.LOCAL, Destination.CLOUD},
    Action.LOCAL_ONLY: {Destination.LOCAL},
    Action.BLOCK: {Destination.NONE},
}


def most_restrictive_action(actions: list[Action]) -> Action:
    return max(actions, key=lambda a: a.restrictiveness)


def most_restrictive_destination(destinations: list[Destination]) -> Destination:
    return min(destinations, key=lambda d: d.reach)


class PolicyConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[str] = Field(default_factory=list, max_length=20)
    channels: list[Channel] = Field(default_factory=list, max_length=4)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("profiles")
    @classmethod
    def _profiles(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for profile in value:
            profile = profile.strip().lower()
            if not re.fullmatch(PROFILE_PATTERN, profile):
                raise ValueError(f"Invalid profile id '{profile}'. Use 2-40 lowercase letters, digits or hyphens.")
            if profile not in cleaned:
                cleaned.append(profile)
        return cleaned

    @field_validator("channels")
    @classmethod
    def _channels(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class PolicyDefinition(BaseModel):
    """Editable fields of a policy rule."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=80)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    priority: int = Field(default=500, ge=1, le=1000)
    entity_categories: list[str] = Field(min_length=1, max_length=20)
    action: Action
    destination: Destination
    conditions: PolicyConditions = Field(default_factory=PolicyConditions)

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("entity_categories")
    @classmethod
    def _categories(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(c.strip().upper() for c in value if c.strip()))
        if not cleaned:
            raise ValueError("At least one entity category is required.")
        if ANY_CATEGORY in cleaned and len(cleaned) > 1:
            raise ValueError("ANY cannot be combined with specific entity categories.")
        return cleaned

    @model_validator(mode="after")
    def _action_destination(self) -> "PolicyDefinition":
        allowed = ALLOWED_DESTINATIONS[self.action]
        if self.destination not in allowed:
            names = ", ".join(sorted(d.value for d in allowed))
            raise ValueError(
                f"Action {self.action.value} requires destination {names}; got {self.destination.value}."
            )
        return self


class Policy(PolicyDefinition):
    policy_id: str = Field(pattern=POLICY_ID_PATTERN)
    version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


class PolicyProfile(BaseModel):
    id: str
    name: str
    description: str = ""
