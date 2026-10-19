"""Semantic policy validation beyond the schema: known categories and conflict warnings."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.policy.models import ANY_CATEGORY, Action, Destination, Policy, PolicyDefinition


@dataclass
class PolicyCheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def _scopes_overlap(a: PolicyDefinition, b: PolicyDefinition) -> bool:
    profiles_overlap = (
        not a.conditions.profiles
        or not b.conditions.profiles
        or bool(set(a.conditions.profiles) & set(b.conditions.profiles))
    )
    channels_overlap = (
        not a.conditions.channels
        or not b.conditions.channels
        or bool(set(a.conditions.channels) & set(b.conditions.channels))
    )
    return profiles_overlap and channels_overlap


def check_policy(
    definition: PolicyDefinition,
    known_categories: set[str],
    existing: list[Policy],
    policy_id: str | None = None,
) -> PolicyCheckResult:
    result = PolicyCheckResult()

    unknown = [c for c in definition.entity_categories if c != ANY_CATEGORY and c not in known_categories]
    if unknown:
        result.errors.append(
            f"Unknown entity categories: {', '.join(unknown)}. Configure a recognizer before referencing them."
        )

    if ANY_CATEGORY in definition.entity_categories and definition.action is Action.REDACT:
        result.errors.append("REDACT requires specific entity categories; ANY has no span to redact.")

    if definition.action is Action.ALLOW and definition.destination is Destination.CLOUD:
        if ANY_CATEGORY not in definition.entity_categories:
            result.warnings.append(
                "ALLOW to CLOUD leaves these values unredacted in cloud-bound payloads. "
                "Confirm this is intended for: " + ", ".join(definition.entity_categories) + "."
            )

    if not definition.enabled:
        result.warnings.append("This policy is disabled and will not affect decisions until enabled.")

    for other in existing:
        if other.policy_id == policy_id or not other.enabled or not definition.enabled:
            continue
        if not _scopes_overlap(definition, other):
            continue
        shared = set(definition.entity_categories) & set(other.entity_categories)
        if not shared:
            continue
        cats = ", ".join(sorted(shared))
        if other.action.restrictiveness > definition.action.restrictiveness:
            result.warnings.append(
                f"'{other.name}' applies the more restrictive {other.action.value} to {cats}; "
                f"it takes precedence over this {definition.action.value} rule where both apply."
            )
        elif other.action.restrictiveness < definition.action.restrictiveness:
            result.warnings.append(
                f"This rule overrides the less restrictive {other.action.value} from '{other.name}' for {cats}."
            )

    return result
