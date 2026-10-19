"""Privacy-utility dial (Feature 4).

The dial can only ADD protection on top of the policy decision; it never weakens a policy.

| Position    | Extra tokenization                                   | Cloud path |
|-------------|------------------------------------------------------|------------|
| max_privacy | every detected entity, even ones policy allows       | never      |
| balanced    | every detected entity except LOCATION and DATE_TIME  | allowed    |
| max_quality | none: only what policy requires                      | allowed    |
"""

from __future__ import annotations

from typing import Literal

from app.detection.entities import DetectedEntity
from app.policy.engine import PolicyDecision
from app.policy.models import Action

DialPosition = Literal["max_privacy", "balanced", "max_quality"]
DIAL_POSITIONS: tuple[str, ...] = ("max_privacy", "balanced", "max_quality")
BALANCED_EXEMPT = frozenset({"LOCATION", "DATE_TIME"})

DIAL_LABELS = {
    "max_privacy": "Maximum privacy",
    "balanced": "Balanced",
    "max_quality": "Maximum quality",
}


def dial_protects(position: str, category: str) -> bool:
    """Whether the dial itself requires ``category`` to be tokenized."""
    if position == "max_privacy":
        return True
    if position == "balanced":
        return category not in BALANCED_EXEMPT
    return False


def dial_extra_entities(position: str, decision: PolicyDecision) -> list[DetectedEntity]:
    """Entities that policy allows in clear text but the dial position tokenizes."""
    return [
        d.entity
        for d in decision.entity_decisions
        if d.action is Action.ALLOW and dial_protects(position, d.entity.entity_type)
    ]


def dial_allows_cloud(position: str) -> bool:
    return position != "max_privacy"
