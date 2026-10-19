"""Deterministic policy engine.

The engine is independent of FastAPI and of the frontend. It receives detected entities
and the authoritative policy set, and returns a decision that later stages must enforce.

Precedence rules:
  * Only enabled policies whose profile and channel conditions match apply.
  * For each entity, every applicable rule that covers its category (and whose
    min_confidence is met) is a candidate. The most restrictive action wins
    (BLOCK > LOCAL_ONLY > REDACT > ALLOW) and the most restrictive destination wins
    (NONE < LOCAL < CLOUD). Priority only orders rules that share the winning action.
  * Rules with the category ANY apply to the whole request.
  * An entity that no rule covers receives the configured unmatched action.
  * If no rule applies at all the request is blocked (deny by default).
  * Cloud transmission is authorized only when the resolved destination is CLOUD.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.detection.entities import DetectedEntity
from app.policy.models import (
    ANY_CATEGORY,
    Action,
    Destination,
    Policy,
    most_restrictive_action,
    most_restrictive_destination,
)

SYSTEM_UNMATCHED = "system:unmatched-entity"
SYSTEM_NO_POLICY = "system:no-applicable-policy"


class PolicyEvaluationError(Exception):
    """Raised when a decision cannot be established. Callers must fail closed."""


@dataclass(frozen=True)
class EntityDecision:
    entity: DetectedEntity
    action: Action
    destination: Destination
    policy_id: str
    policy_name: str
    reason: str
    priority: int = 0


@dataclass(frozen=True)
class MatchedPolicy:
    policy_id: str
    name: str
    action: Action
    destination: Destination
    priority: int
    matched_categories: tuple[str, ...]


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    destination: Destination
    decisive_policy_id: str
    entity_decisions: tuple[EntityDecision, ...]
    matched_policies: tuple[MatchedPolicy, ...]
    reasons: tuple[str, ...]
    policy_version: str
    profile: str
    channel: str
    no_applicable_policy: bool = False

    @property
    def local_ai_authorized(self) -> bool:
        return self.action is not Action.BLOCK and self.destination.reach >= Destination.LOCAL.reach

    @property
    def cloud_authorized(self) -> bool:
        return self.action is not Action.BLOCK and self.destination is Destination.CLOUD

    @property
    def entities_to_redact(self) -> list[DetectedEntity]:
        """Every entity whose resolved action is not ALLOW is masked before AI processing."""
        return [d.entity for d in self.entity_decisions if d.action is not Action.ALLOW]


def policy_set_version(policies: list[Policy]) -> str:
    """Stable fingerprint of the enabled policy configuration used for a decision."""
    canonical = sorted(
        (p.policy_id, p.version, p.updated_at.isoformat()) for p in policies if p.enabled
    )
    digest = hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest()
    return f"ps-{digest[:12]}"


def _sort_key(policy: Policy) -> tuple[int, int, str]:
    # Most restrictive first, then lowest priority number, then id for determinism.
    return (-policy.action.restrictiveness, policy.priority, policy.policy_id)


@dataclass
class PolicyEngine:
    unmatched_entity_action: Action = Action.LOCAL_ONLY

    def __post_init__(self) -> None:
        if self.unmatched_entity_action not in (Action.LOCAL_ONLY, Action.BLOCK):
            raise ValueError("The unmatched entity action must be LOCAL_ONLY or BLOCK.")

    @staticmethod
    def applicable_policies(policies: list[Policy], profile: str, channel: str) -> list[Policy]:
        applicable = [
            p
            for p in policies
            if p.enabled
            and (not p.conditions.profiles or profile in p.conditions.profiles)
            and (not p.conditions.channels or channel in p.conditions.channels)
        ]
        return sorted(applicable, key=_sort_key)

    def evaluate(
        self,
        entities: list[DetectedEntity],
        policies: list[Policy],
        profile: str,
        channel: str,
    ) -> PolicyDecision:
        try:
            return self._evaluate(entities, policies, profile, channel)
        except PolicyEvaluationError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure must fail closed
            raise PolicyEvaluationError("Policy evaluation failed.") from exc

    def _evaluate(
        self,
        entities: list[DetectedEntity],
        policies: list[Policy],
        profile: str,
        channel: str,
    ) -> PolicyDecision:
        version = policy_set_version(policies)
        applicable = self.applicable_policies(policies, profile, channel)
        any_rules = [p for p in applicable if ANY_CATEGORY in p.entity_categories]

        matched: dict[str, set[str]] = {p.policy_id: set() for p in any_rules}
        for p in any_rules:
            matched[p.policy_id].add(ANY_CATEGORY)

        entity_decisions: list[EntityDecision] = []
        reasons: list[str] = []
        for entity in entities:
            candidates = [
                p
                for p in applicable
                if entity.entity_type in p.entity_categories
                and entity.score >= p.conditions.min_confidence
            ]
            if not candidates:
                action = self.unmatched_entity_action
                destination = Destination.LOCAL if action is Action.LOCAL_ONLY else Destination.NONE
                entity_decisions.append(
                    EntityDecision(
                        entity=entity,
                        action=action,
                        destination=destination,
                        policy_id=SYSTEM_UNMATCHED,
                        policy_name="Unmatched entity default",
                        reason=f"No enabled policy covers {entity.entity_type}; conservative default {action.value} applied.",
                    )
                )
                continue

            winner = candidates[0]  # already sorted: most restrictive, then priority
            action = most_restrictive_action([c.action for c in candidates])
            destination = most_restrictive_destination([c.destination for c in candidates])
            if action is Action.BLOCK:
                destination = Destination.NONE
            elif action is Action.LOCAL_ONLY:
                destination = most_restrictive_destination([destination, Destination.LOCAL])
            for c in candidates:
                matched.setdefault(c.policy_id, set()).add(entity.entity_type)
            overridden = [c.policy_id for c in candidates[1:] if c.action is not action]
            reason = f"{winner.name} applies {action.value} to {entity.entity_type}."
            if overridden:
                reason += f" Less restrictive rules not applied: {', '.join(overridden)}."
            entity_decisions.append(
                EntityDecision(
                    entity=entity,
                    action=action,
                    destination=destination,
                    policy_id=winner.policy_id,
                    policy_name=winner.name,
                    reason=reason,
                    priority=winner.priority,
                )
            )

        matched_policies = tuple(
            MatchedPolicy(
                policy_id=p.policy_id,
                name=p.name,
                action=p.action,
                destination=p.destination,
                priority=p.priority,
                matched_categories=tuple(sorted(matched[p.policy_id])),
            )
            for p in applicable
            if p.policy_id in matched
        )

        if not entity_decisions and not any_rules:
            return PolicyDecision(
                action=Action.BLOCK,
                destination=Destination.NONE,
                decisive_policy_id=SYSTEM_NO_POLICY,
                entity_decisions=(),
                matched_policies=(),
                reasons=(
                    f"No enabled policy applies to profile '{profile}' and channel '{channel}'. "
                    "Processing is denied by default.",
                ),
                policy_version=version,
                profile=profile,
                channel=channel,
                no_applicable_policy=True,
            )

        actions = [d.action for d in entity_decisions] + [p.action for p in any_rules]
        destinations = [d.destination for d in entity_decisions] + [p.destination for p in any_rules]
        action = most_restrictive_action(actions)
        destination = most_restrictive_destination(destinations)
        if action is Action.BLOCK:
            destination = Destination.NONE
        elif action is Action.LOCAL_ONLY:
            destination = most_restrictive_destination([destination, Destination.LOCAL])

        decisive = self._decisive_policy(action, entity_decisions, any_rules)

        if entities:
            categories = sorted({e.entity_type for e in entities})
            reasons.append(f"Detected categories: {', '.join(categories)}.")
        else:
            reasons.append("No sensitive entities were detected.")
        reasons.extend(d.reason for d in entity_decisions)
        reasons.append(f"Resolved decision {action.value} with authorized destination {destination.value}.")
        if destination is not Destination.CLOUD:
            reasons.append("Cloud transmission is not authorized for this request.")

        return PolicyDecision(
            action=action,
            destination=destination,
            decisive_policy_id=decisive,
            entity_decisions=tuple(entity_decisions),
            matched_policies=matched_policies,
            reasons=tuple(dict.fromkeys(reasons)),
            policy_version=version,
            profile=profile,
            channel=channel,
        )

    @staticmethod
    def _decisive_policy(
        action: Action, entity_decisions: list[EntityDecision], any_rules: list[Policy]
    ) -> str:
        # The highest-priority rule (lowest number) that produced the winning action.
        candidates: list[tuple[int, str]] = []
        for d in entity_decisions:
            if d.action is action:
                candidates.append((d.priority, d.policy_id))
        for p in any_rules:
            if p.action is action:
                candidates.append((p.priority, p.policy_id))
        return min(candidates)[1] if candidates else SYSTEM_NO_POLICY

    def resolve_category(
        self, category: str, policies: list[Policy], profile: str, channel: str
    ) -> tuple[Action, Destination]:
        """Resolution for a hypothetical high-confidence entity of ``category``."""
        probe = DetectedEntity(category, 0, 0, 1.0, "", "probe")
        decision = self._evaluate([probe], policies, profile, channel)
        return decision.entity_decisions[0].action, decision.entity_decisions[0].destination
