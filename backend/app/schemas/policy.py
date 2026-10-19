"""Policy API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.policy.models import POLICY_ID_PATTERN, Policy, PolicyDefinition, PolicyProfile


class PolicyCreate(PolicyDefinition):
    policy_id: str | None = Field(default=None, pattern=POLICY_ID_PATTERN)


class PolicyUpdate(PolicyDefinition):
    pass


class PolicyListResponse(BaseModel):
    items: list[Policy]
    policy_version: str
    total: int


class PolicyValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class ProfileInfo(PolicyProfile):
    applicable_policies: int


class ProfileListResponse(BaseModel):
    items: list[ProfileInfo]


class EntityCategoryListResponse(BaseModel):
    items: list[str]
