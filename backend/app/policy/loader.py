"""Loads seed policies and profiles from YAML. Invalid files are rejected as a whole."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.policy.models import POLICY_ID_PATTERN, PolicyDefinition, PolicyProfile


class PolicyFileError(Exception):
    """The policy file could not be parsed or failed validation."""


class SeedPolicy(PolicyDefinition):
    policy_id: str = Field(pattern=POLICY_ID_PATTERN)


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[PolicyProfile] = Field(default_factory=list)
    policies: list[SeedPolicy] = Field(min_length=1)


def load_policy_file(path: Path) -> PolicyFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyFileError("Policy seed file not found.") from exc
    except yaml.YAMLError as exc:
        raise PolicyFileError("Policy seed file is not valid YAML.") from exc
    if not isinstance(raw, dict):
        raise PolicyFileError("Policy seed file must contain a mapping.")
    try:
        parsed = PolicyFile.model_validate(raw)
    except ValidationError as exc:
        raise PolicyFileError(f"Policy seed file failed validation: {exc.error_count()} error(s).") from exc
    ids = [p.policy_id for p in parsed.policies]
    if len(ids) != len(set(ids)):
        raise PolicyFileError("Policy seed file contains duplicate policy ids.")
    return parsed
