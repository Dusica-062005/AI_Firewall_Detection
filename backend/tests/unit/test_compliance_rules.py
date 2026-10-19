from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.compliance.controls import CONTROLS, ControlContext, evaluate_framework
from app.compliance.incidents import SLA_HOURS, sla_due_at, sla_status
from app.policy.models import Action, Destination, Policy

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
CATEGORIES = ["ACCOUNT_NUMBER", "CREDIT_CARD", "GOVERNMENT_ID", "PATIENT_ID", "PERSON"]


def _policy(policy_id: str, categories: list[str], action: Action, profiles: list[str] | None = None, enabled: bool = True) -> Policy:
    destination = {Action.BLOCK: Destination.NONE, Action.LOCAL_ONLY: Destination.LOCAL}.get(action, Destination.CLOUD)
    return Policy.model_validate({
        "policy_id": policy_id, "name": policy_id, "enabled": enabled, "priority": 100, "entity_categories": categories,
        "action": action, "destination": destination, "conditions": {"profiles": profiles or [], "channels": [], "min_confidence": 0.0},
        "version": 1, "created_at": T0, "updated_at": T0,
    })


def _ctx(policies: list[Policy], **overrides) -> ControlContext:
    values = dict(
        now=T0, policies=policies, known_categories=CATEGORIES, unmatched_action="LOCAL_ONLY", admin_key_configured=True,
        audit_event_count=3, audit_retention_days=30, audit_stores_transcripts=False, audit_stores_entity_values=False,
        audit_columns=["event_id", "decision", "transcript_chars"], systems=[], incidents=[], data_requests=[],
    )
    values.update(overrides)
    return ControlContext(**values)


def _status(control_id: str, ctx: ControlContext) -> str:
    return CONTROLS[control_id].check(ctx).status


@pytest.mark.parametrize("severity,hours", [("CRITICAL", 4), ("HIGH", 24), ("MEDIUM", 72), ("LOW", 168)])
def test_sla_deadline_depends_on_severity(severity, hours):
    assert SLA_HOURS[severity] == hours
    assert sla_due_at(T0, severity) == T0 + timedelta(hours=hours)


def test_sla_states_before_containment():
    due = sla_due_at(T0, "HIGH")  # 24 hours
    assert sla_status(T0, due, None, T0 + timedelta(hours=6)) == ("ON_TRACK", 18 * 3600)
    assert sla_status(T0, due, None, T0 + timedelta(hours=18))[0] == "AT_RISK"
    state, remaining = sla_status(T0, due, None, T0 + timedelta(hours=25))
    assert state == "BREACHED" and remaining == -3600


def test_sla_outcome_is_fixed_once_contained():
    due = sla_due_at(T0, "HIGH")
    assert sla_status(T0, due, T0 + timedelta(hours=23), T0 + timedelta(days=30)) == ("MET", None)
    assert sla_status(T0, due, T0 + timedelta(hours=30), T0 + timedelta(days=30)) == ("MISSED", None)


def test_sensitive_categories_need_an_always_on_rule():
    always = _policy("redact-all", CATEGORIES, Action.REDACT)
    assert _status("CTL-SENSITIVE-PROTECTED", _ctx([always])) == "PASS"

    profile_only = _policy("redact-health", CATEGORIES, Action.REDACT, profiles=["healthcare"])
    assert _status("CTL-SENSITIVE-PROTECTED", _ctx([profile_only])) == "FAIL"

    some = _policy("redact-person", ["PERSON"], Action.REDACT)
    assert _status("CTL-SENSITIVE-PROTECTED", _ctx([some])) == "PARTIAL"

    allow_any = _policy("allow-all", ["ANY"], Action.ALLOW)
    assert _status("CTL-SENSITIVE-PROTECTED", _ctx([allow_any])) == "FAIL"
    assert _status("CTL-SENSITIVE-PROTECTED", _ctx([_policy("redact-all", CATEGORIES, Action.REDACT, enabled=False)])) == "FAIL"


def test_high_risk_and_phi_controls():
    block = _policy("block-high-risk", ["GOVERNMENT_ID", "CREDIT_CARD"], Action.BLOCK)
    local = _policy("local-accounts", ["ACCOUNT_NUMBER"], Action.LOCAL_ONLY)
    assert _status("CTL-HIGH-RISK-RESTRICTED", _ctx([block])) == "PARTIAL"
    assert _status("CTL-HIGH-RISK-RESTRICTED", _ctx([block, local])) == "PASS"
    assert _status("CTL-HIGH-RISK-RESTRICTED", _ctx([])) == "FAIL"

    redact = _policy("redact-phi", ["PATIENT_ID"], Action.REDACT)
    strict = _policy("local-phi", ["PATIENT_ID"], Action.LOCAL_ONLY, profiles=["healthcare"])
    assert _status("CTL-PHI-CONTROLS", _ctx([redact, strict])) == "PASS"
    assert _status("CTL-PHI-CONTROLS", _ctx([redact])) == "PARTIAL"
    assert _status("CTL-PHI-CONTROLS", _ctx([])) == "FAIL"


def test_audit_controls():
    assert _status("CTL-AUDIT-NO-CONTENT", _ctx([])) == "PASS"
    assert _status("CTL-AUDIT-NO-CONTENT", _ctx([], audit_columns=["event_id", "transcript"])) == "FAIL"
    assert _status("CTL-AUDIT-NO-CONTENT", _ctx([], audit_stores_entity_values=True)) == "FAIL"
    assert _status("CTL-AUDIT-ACTIVE", _ctx([], audit_event_count=0)) == "PARTIAL"
    assert [_status("CTL-RETENTION", _ctx([], audit_retention_days=d)) for d in (365, 366, 1095, 1096)] == [
        "PASS", "PARTIAL", "PARTIAL", "FAIL",
    ]


def test_score_gives_half_credit_for_partial_controls():
    ctx = _ctx([_policy("redact-person", ["PERSON"], Action.REDACT)], admin_key_configured=False)
    score = evaluate_framework("HIPAA", ctx)
    expected = round(100 * (score.pass_count + 0.5 * score.partial_count) / score.total)
    assert score.score == expected
    assert score.fail_count >= 1 and all(c.remediation for c in score.controls if c.status != "PASS")
    assert all(c.remediation is None for c in score.controls if c.status == "PASS")
