from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.detection.entities import DetectedEntity
from app.policy.engine import SYSTEM_NO_POLICY, SYSTEM_UNMATCHED, PolicyEngine, PolicyEvaluationError
from app.policy.loader import load_policy_file
from app.policy.models import Action, Destination, Policy
from app.config import Settings

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def policy(pid, categories, action, destination, priority=500, profiles=(), channels=(), min_confidence=0.0, enabled=True):
    return Policy(
        policy_id=pid, name=pid.replace("-", " ").title(), description="", enabled=enabled, priority=priority,
        entity_categories=list(categories), action=action, destination=destination,
        conditions={"profiles": list(profiles), "channels": list(channels), "min_confidence": min_confidence},
        version=1, created_at=NOW, updated_at=NOW,
    )


def ent(entity_type, score=0.9):
    return DetectedEntity(entity_type, 0, 4, score, "xxxx", "test")


ALLOW_ALL = policy("allow-all", ["ANY"], Action.ALLOW, Destination.CLOUD, priority=1)


@pytest.fixture
def engine():
    return PolicyEngine(unmatched_entity_action=Action.LOCAL_ONLY)


def test_broad_allow_cannot_override_restrictive_rule(engine):
    # The ALLOW rule has the *highest* priority, but BLOCK must still win.
    policies = [
        ALLOW_ALL,
        policy("allow-person", ["PERSON"], Action.ALLOW, Destination.CLOUD, priority=1),
        policy("block-person", ["PERSON"], Action.BLOCK, Destination.NONE, priority=999),
    ]
    decision = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    assert decision.action is Action.BLOCK
    assert decision.destination is Destination.NONE
    assert not decision.cloud_authorized and not decision.local_ai_authorized
    assert decision.entity_decisions[0].policy_id == "block-person"


def test_local_only_restricts_cloud_even_with_allow_any(engine):
    policies = [ALLOW_ALL, policy("phi-local", ["PATIENT_ID"], Action.LOCAL_ONLY, Destination.LOCAL)]
    decision = engine.evaluate([ent("PATIENT_ID")], policies, "standard", "voice")
    assert decision.action is Action.LOCAL_ONLY
    assert decision.local_ai_authorized and not decision.cloud_authorized


def test_most_restrictive_destination_wins_between_redact_rules(engine):
    policies = [
        ALLOW_ALL,
        policy("redact-cloud", ["PERSON"], Action.REDACT, Destination.CLOUD),
        policy("redact-local", ["PERSON"], Action.REDACT, Destination.LOCAL),
    ]
    decision = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    assert decision.action is Action.REDACT
    assert decision.destination is Destination.LOCAL


def test_redact_with_cloud_baseline_authorizes_cloud(engine):
    policies = [ALLOW_ALL, policy("redact-person", ["PERSON"], Action.REDACT, Destination.CLOUD)]
    decision = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    assert decision.action is Action.REDACT and decision.cloud_authorized
    assert [e.entity_type for e in decision.entities_to_redact] == ["PERSON"]


def test_unmatched_entity_gets_conservative_default(engine):
    decision = engine.evaluate([ent("LOCATION")], [ALLOW_ALL], "standard", "voice")
    assert decision.entity_decisions[0].policy_id == SYSTEM_UNMATCHED
    assert decision.action is Action.LOCAL_ONLY
    assert not decision.cloud_authorized


def test_no_applicable_policy_denies_by_default(engine):
    decision = engine.evaluate([], [policy("other-allow", ["ANY"], Action.ALLOW, Destination.CLOUD, profiles=["other"])], "standard", "voice")
    assert decision.no_applicable_policy
    assert decision.action is Action.BLOCK and decision.decisive_policy_id == SYSTEM_NO_POLICY


def test_disabled_policies_are_ignored(engine):
    policies = [ALLOW_ALL, policy("block-person", ["PERSON"], Action.BLOCK, Destination.NONE, enabled=False)]
    decision = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    assert decision.action is Action.LOCAL_ONLY  # falls back to the unmatched default, never ALLOW


def test_profile_and_channel_conditions(engine):
    policies = [
        ALLOW_ALL,
        policy("redact-person", ["PERSON"], Action.REDACT, Destination.CLOUD),
        policy("healthcare-block", ["PERSON"], Action.BLOCK, Destination.NONE, profiles=["healthcare"]),
        policy("email-local", ["PERSON"], Action.LOCAL_ONLY, Destination.LOCAL, channels=["email"]),
    ]
    assert engine.evaluate([ent("PERSON")], policies, "standard", "voice").action is Action.REDACT
    assert engine.evaluate([ent("PERSON")], policies, "healthcare", "voice").action is Action.BLOCK
    assert engine.evaluate([ent("PERSON")], policies, "standard", "email").action is Action.LOCAL_ONLY


def test_min_confidence_condition(engine):
    policies = [ALLOW_ALL, policy("redact-person", ["PERSON"], Action.REDACT, Destination.CLOUD, min_confidence=0.8)]
    low = engine.evaluate([ent("PERSON", score=0.5)], policies, "standard", "voice")
    assert low.entity_decisions[0].policy_id == SYSTEM_UNMATCHED
    assert not low.cloud_authorized


def test_priority_breaks_ties_between_equal_actions(engine):
    policies = [
        ALLOW_ALL,
        policy("redact-b", ["PERSON"], Action.REDACT, Destination.CLOUD, priority=300),
        policy("redact-a", ["PERSON"], Action.REDACT, Destination.CLOUD, priority=100),
    ]
    decision = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    assert decision.entity_decisions[0].policy_id == "redact-a"


def test_evaluation_is_deterministic(engine):
    policies = [ALLOW_ALL, policy("redact-person", ["PERSON"], Action.REDACT, Destination.CLOUD)]
    first = engine.evaluate([ent("PERSON")], policies, "standard", "voice")
    second = engine.evaluate([ent("PERSON")], list(reversed(policies)), "standard", "voice")
    assert first == second


def test_evaluation_error_is_wrapped(engine):
    broken = [object()]  # not a Policy
    with pytest.raises(PolicyEvaluationError):
        engine.evaluate([ent("PERSON")], broken, "standard", "voice")  # type: ignore[arg-type]


def test_seed_policies_produce_three_demo_outcomes(engine):
    seed = load_policy_file(Settings().policy_seed_file)
    policies = [
        Policy(**p.model_dump(), version=1, created_at=NOW, updated_at=NOW) for p in seed.policies
    ]
    entities = [ent("PERSON"), ent("PATIENT_ID")]
    assert engine.evaluate(entities, policies, "standard", "voice").action is Action.REDACT
    assert engine.evaluate(entities, policies, "healthcare", "voice").action is Action.LOCAL_ONLY
    assert engine.evaluate(entities, policies, "restricted", "voice").action is Action.BLOCK
