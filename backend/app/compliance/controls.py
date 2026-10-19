"""Compliance controls evaluated against live system state.

Each control is a pure function of a ``ControlContext`` snapshot, so scores always reflect
the real policies, audit settings, inventory, incidents and requests, never stored numbers.
The framework mappings are indicative and meant for demonstration, not certification.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.policy.models import Action, Policy
from app.schemas.compliance import AiSystem, ControlResult, DataRequest, FrameworkScore, Incident

HIGH_RISK_CATEGORIES = ("GOVERNMENT_ID", "CREDIT_CARD", "ACCOUNT_NUMBER")
PHI_CATEGORY = "PATIENT_ID"
# Context details rather than identifiers: allowed by policy so summaries stay useful, and
# tokenized by the privacy-utility dial (balanced and maximum privacy) instead.
CONTEXT_CATEGORIES = frozenset({"DATE_TIME", "HEALTH_TERM"})
FORBIDDEN_AUDIT_COLUMNS = {
    "transcript", "transcript_text", "text", "content", "payload", "summary", "entity_values", "values", "detected_values",
}
STALE_INCIDENT_DAYS = 30
MAX_RETENTION_PASS_DAYS = 365
MAX_RETENTION_PARTIAL_DAYS = 1095

STATUS_POINTS = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}


@dataclass(frozen=True)
class ControlContext:
    now: datetime
    policies: list[Policy]
    known_categories: list[str]
    unmatched_action: str
    admin_key_configured: bool
    audit_event_count: int
    audit_retention_days: int
    audit_stores_transcripts: bool
    audit_stores_entity_values: bool
    audit_columns: list[str]
    systems: list[AiSystem]
    incidents: list[Incident]
    data_requests: list[DataRequest]


@dataclass(frozen=True)
class CheckResult:
    status: str
    evidence: str


@dataclass(frozen=True)
class ControlDefinition:
    control_id: str
    title: str
    description: str
    remediation: str
    check: Callable[[ControlContext], CheckResult]


def _names(items: list[str], limit: int = 4) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _applies_everywhere(policy: Policy) -> bool:
    c = policy.conditions
    return policy.enabled and not c.profiles and not c.channels and c.min_confidence <= 0.5


def _covers(policy: Policy, category: str) -> bool:
    return category in policy.entity_categories or "ANY" in policy.entity_categories


def _active_systems(ctx: ControlContext) -> list[AiSystem]:
    return [s for s in ctx.systems if s.status != "RETIRED"]


# ---- Checks -------------------------------------------------------------------------------


def _policy_enforced(ctx: ControlContext) -> CheckResult:
    enabled = [p for p in ctx.policies if p.enabled]
    if not enabled:
        return CheckResult("FAIL", "No policy is enabled. Requests are blocked by default, but no handling rules are defined.")
    return CheckResult(
        "PASS",
        f"{len(enabled)} of {len(ctx.policies)} policies enabled. Deny by default, and entities no rule covers are set to {ctx.unmatched_action}.",
    )


def _sensitive_protected(ctx: ControlContext) -> CheckResult:
    categories = [c for c in ctx.known_categories if c not in CONTEXT_CATEGORIES]
    uncovered = [
        c
        for c in categories
        if not any(_applies_everywhere(p) and p.action != Action.ALLOW and _covers(p, c) for p in ctx.policies)
    ]
    if not categories:
        return CheckResult("FAIL", "No sensitive data categories are configured for detection.")
    covered = len(categories) - len(uncovered)
    if not uncovered:
        return CheckResult("PASS", f"All {len(categories)} detected categories have a protection rule that applies to every profile and channel.")
    status = "PARTIAL" if covered else "FAIL"
    return CheckResult(status, f"{covered} of {len(categories)} categories have an always-on protection rule. Missing: {_names(uncovered)}.")


def _high_risk_restricted(ctx: ControlContext) -> CheckResult:
    relevant = [c for c in HIGH_RISK_CATEGORIES if c in ctx.known_categories]
    if not relevant:
        return CheckResult("PASS", "No high-risk identifier categories are configured.")
    restricted = {Action.BLOCK, Action.LOCAL_ONLY}
    missing = [
        c for c in relevant if not any(_applies_everywhere(p) and p.action in restricted and _covers(p, c) for p in ctx.policies)
    ]
    if not missing:
        return CheckResult("PASS", f"{_names(relevant)} are blocked or kept on local processing in every profile.")
    status = "PARTIAL" if len(missing) < len(relevant) else "FAIL"
    return CheckResult(status, f"No always-on block or local-only rule for {_names(missing)}.")


def _phi_controls(ctx: ControlContext) -> CheckResult:
    if PHI_CATEGORY not in ctx.known_categories:
        return CheckResult("PASS", "No patient identifier category is configured.")
    redact = any(_applies_everywhere(p) and p.action != Action.ALLOW and _covers(p, PHI_CATEGORY) for p in ctx.policies)
    restrict = any(
        p.enabled and p.action in {Action.BLOCK, Action.LOCAL_ONLY} and _covers(p, PHI_CATEGORY) for p in ctx.policies
    )
    if redact and restrict:
        return CheckResult("PASS", "Patient identifiers are always protected, and at least one profile blocks them or keeps them local.")
    if redact or restrict:
        missing = "a local-only or block profile" if redact else "an always-on protection rule"
        return CheckResult("PARTIAL", f"Patient identifiers lack {missing}.")
    return CheckResult("FAIL", "No enabled policy protects patient identifiers.")


def _admin_auth(ctx: ControlContext) -> CheckResult:
    if ctx.admin_key_configured:
        return CheckResult("PASS", "An administrator key is required for policy, inventory, incident and request changes.")
    return CheckResult("FAIL", "No administrator key is configured, so anyone who can reach the API can change records.")


def _audit_no_content(ctx: ControlContext) -> CheckResult:
    offending = sorted(FORBIDDEN_AUDIT_COLUMNS.intersection(ctx.audit_columns))
    if offending or ctx.audit_stores_transcripts or ctx.audit_stores_entity_values:
        return CheckResult("FAIL", f"The audit trail can hold content: {_names(offending) or 'storage flags are set'}.")
    return CheckResult("PASS", f"The audit schema has {len(ctx.audit_columns)} columns and none can hold transcript text or detected values.")


def _audit_active(ctx: ControlContext) -> CheckResult:
    if ctx.audit_event_count > 0:
        return CheckResult("PASS", f"{ctx.audit_event_count} firewall decisions recorded in the audit trail.")
    return CheckResult("PARTIAL", "The audit trail is configured but no events have been recorded yet.")


def _retention(ctx: ControlContext) -> CheckResult:
    days = ctx.audit_retention_days
    if days <= MAX_RETENTION_PASS_DAYS:
        return CheckResult("PASS", f"Audit events are deleted after {days} days.")
    status = "PARTIAL" if days <= MAX_RETENTION_PARTIAL_DAYS else "FAIL"
    return CheckResult(status, f"Audit events are kept for {days} days, longer than the {MAX_RETENTION_PASS_DAYS}-day guideline.")


def _inventory(ctx: ControlContext) -> CheckResult:
    active = _active_systems(ctx)
    if not active:
        return CheckResult("FAIL", "No AI systems are registered in the inventory.")
    pending = [s.name for s in active if s.status != "APPROVED"]
    if pending:
        return CheckResult("PARTIAL", f"{len(active) - len(pending)} of {len(active)} AI systems approved. Awaiting approval: {_names(pending)}.")
    return CheckResult("PASS", f"All {len(active)} registered AI systems are approved.")


def _reviews_current(ctx: ControlContext) -> CheckResult:
    active = _active_systems(ctx)
    if not active:
        return CheckResult("FAIL", "There are no registered AI systems to review.")
    overdue = [s.name for s in active if s.review_overdue]
    if not overdue:
        return CheckResult("PASS", f"All {len(active)} AI systems are within their review interval.")
    status = "PARTIAL" if len(overdue) < len(active) else "FAIL"
    return CheckResult(status, f"{len(overdue)} of {len(active)} AI systems have an overdue review: {_names(overdue)}.")


def _incident_sla(ctx: ControlContext) -> CheckResult:
    if not ctx.incidents:
        return CheckResult("PASS", "No incidents recorded.")
    breached = [i for i in ctx.incidents if i.sla_state == "BREACHED"]
    missed = [i for i in ctx.incidents if i.sla_state == "MISSED"]
    if breached:
        return CheckResult("FAIL", f"{len(breached)} open incident(s) are past their containment deadline.")
    if missed:
        return CheckResult("PARTIAL", f"{len(missed)} of {len(ctx.incidents)} incidents were contained after their deadline.")
    return CheckResult("PASS", f"All {len(ctx.incidents)} incidents were contained, or are on track to be contained, within SLA.")


def _incident_closure(ctx: ControlContext) -> CheckResult:
    if not ctx.incidents:
        return CheckResult("PASS", "No incidents recorded.")
    closed = [i for i in ctx.incidents if i.status == "CLOSED"]
    undocumented = [i for i in closed if not (i.root_cause and i.resolution)]
    if undocumented:
        return CheckResult("FAIL", f"{len(undocumented)} closed incident(s) have no documented root cause and resolution.")
    cutoff = ctx.now - timedelta(days=STALE_INCIDENT_DAYS)
    stale = [i for i in ctx.incidents if i.status != "CLOSED" and i.created_at < cutoff]
    if stale:
        return CheckResult("PARTIAL", f"{len(stale)} incident(s) have been open for more than {STALE_INCIDENT_DAYS} days.")
    return CheckResult("PASS", f"{len(closed)} closed incident(s) all document a root cause and resolution. None are stale.")


def _requests_timely(ctx: ControlContext) -> CheckResult:
    if not ctx.data_requests:
        return CheckResult("PASS", "No data-subject requests recorded.")
    overdue = [r for r in ctx.data_requests if r.overdue]
    late = [r for r in ctx.data_requests if r.completed_at and r.completed_at > r.due_at]
    if overdue:
        return CheckResult("FAIL", f"{len(overdue)} open data-subject request(s) are past the 30-day deadline.")
    if late:
        return CheckResult("PARTIAL", f"{len(late)} of {len(ctx.data_requests)} requests were completed after the deadline.")
    return CheckResult("PASS", f"All {len(ctx.data_requests)} data-subject requests are on time or completed on time.")


CONTROLS: dict[str, ControlDefinition] = {
    c.control_id: c
    for c in (
        ControlDefinition(
            "CTL-POLICY-ENFORCED",
            "Data-handling policy is enforced",
            "Enabled policies decide what AI may see and send, and anything unmatched is restricted by default.",
            "Enable at least one policy on the Policies page.",
            _policy_enforced,
        ),
        ControlDefinition(
            "CTL-SENSITIVE-PROTECTED",
            "Every sensitive category has a protection rule",
            "Each detected category is redacted, kept local or blocked in all profiles and channels.",
            "Add or widen a REDACT, LOCAL_ONLY or BLOCK policy so it applies to every profile and channel for the missing categories.",
            _sensitive_protected,
        ),
        ControlDefinition(
            "CTL-HIGH-RISK-RESTRICTED",
            "High-risk identifiers are blocked or kept local",
            "Government IDs, card numbers and account numbers never reach a cloud service.",
            "Add an always-on BLOCK or LOCAL_ONLY policy for the missing categories.",
            _high_risk_restricted,
        ),
        ControlDefinition(
            "CTL-PHI-CONTROLS",
            "Patient identifiers have layered protection",
            "Patient identifiers are always protected, with a stricter profile that blocks them or keeps them local.",
            "Add an always-on REDACT policy and a BLOCK or LOCAL_ONLY policy for PATIENT_ID.",
            _phi_controls,
        ),
        ControlDefinition(
            "CTL-ADMIN-AUTH",
            "Changes require authentication",
            "Policy, inventory, incident and request changes require an administrator key.",
            "Set the ADMIN_API_KEY environment variable and restart the backend.",
            _admin_auth,
        ),
        ControlDefinition(
            "CTL-AUDIT-NO-CONTENT",
            "Audit trail excludes personal data",
            "The audit trail records categories, counts and decisions, never transcripts or detected values.",
            "Remove any audit column or setting that can store transcript text or detected values.",
            _audit_no_content,
        ),
        ControlDefinition(
            "CTL-AUDIT-ACTIVE",
            "Audit trail is recording",
            "Firewall decisions are recorded so activity can be reviewed after the fact.",
            "Process a transcript in the Inspector to create the first audit event.",
            _audit_active,
        ),
        ControlDefinition(
            "CTL-RETENTION",
            "Audit retention is defined and bounded",
            "Audit events are deleted after a fixed period instead of being kept indefinitely.",
            f"Set AUDIT_RETENTION_DAYS to {MAX_RETENTION_PASS_DAYS} or fewer.",
            _retention,
        ),
        ControlDefinition(
            "CTL-AI-INVENTORY",
            "AI systems are inventoried and approved",
            "Every AI system that touches communication data is registered with an owner and an approval status.",
            "Register missing AI systems and approve those that have been reviewed.",
            _inventory,
        ),
        ControlDefinition(
            "CTL-REVIEWS-CURRENT",
            "AI system reviews are current",
            "Each AI system is re-reviewed within its review interval.",
            "Open the AI systems tab and mark overdue systems as reviewed once they have been assessed.",
            _reviews_current,
        ),
        ControlDefinition(
            "CTL-INCIDENT-SLA",
            "Incidents are contained within SLA",
            "AI incidents are contained within the time allowed for their severity.",
            "Contain overdue incidents first, starting with the highest severity.",
            _incident_sla,
        ),
        ControlDefinition(
            "CTL-INCIDENT-CLOSURE",
            "Incidents are closed with a root cause",
            "Closed incidents document the root cause and the resolution, and open ones do not go stale.",
            "Record a root cause and resolution, then close or escalate the stale incidents.",
            _incident_closure,
        ),
        ControlDefinition(
            "CTL-REQUESTS-TIMELY",
            "Data-subject requests are completed on time",
            "Erasure and access requests are completed across every AI system within 30 days.",
            "Complete the pending systems on the overdue requests.",
            _requests_timely,
        ),
    )
}

# Indicative clause references per framework: (control id, clause).
FRAMEWORKS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "GDPR": (
        "GDPR",
        (
            ("CTL-POLICY-ENFORCED", "Art. 25 Data protection by design and by default"),
            ("CTL-SENSITIVE-PROTECTED", "Art. 32 Security of processing"),
            ("CTL-ADMIN-AUTH", "Art. 32 Security of processing"),
            ("CTL-AUDIT-NO-CONTENT", "Art. 5(1)(c) Data minimisation"),
            ("CTL-RETENTION", "Art. 5(1)(e) Storage limitation"),
            ("CTL-AI-INVENTORY", "Art. 30 Records of processing activities"),
            ("CTL-REVIEWS-CURRENT", "Art. 32(1)(d) Regular testing and evaluation"),
            ("CTL-INCIDENT-SLA", "Art. 33 Notification of a personal data breach"),
            ("CTL-REQUESTS-TIMELY", "Art. 12(3) and Art. 17 Right to erasure"),
        ),
    ),
    "HIPAA": (
        "HIPAA Security Rule",
        (
            ("CTL-PHI-CONTROLS", "45 CFR 164.502(b) Minimum necessary"),
            ("CTL-HIGH-RISK-RESTRICTED", "45 CFR 164.308(a)(1)(ii)(B) Risk management"),
            ("CTL-ADMIN-AUTH", "45 CFR 164.312(d) Person or entity authentication"),
            ("CTL-AUDIT-ACTIVE", "45 CFR 164.312(b) Audit controls"),
            ("CTL-REVIEWS-CURRENT", "45 CFR 164.308(a)(8) Evaluation"),
            ("CTL-INCIDENT-SLA", "45 CFR 164.308(a)(6) Security incident procedures"),
            ("CTL-INCIDENT-CLOSURE", "45 CFR 164.308(a)(6)(ii) Response and reporting"),
        ),
    ),
    "ISO_42001": (
        "ISO/IEC 42001 AI management system",
        (
            ("CTL-AI-INVENTORY", "Clause 4.3 Scope of the AI management system"),
            ("CTL-POLICY-ENFORCED", "Clause 5.2 AI policy"),
            ("CTL-HIGH-RISK-RESTRICTED", "Clause 6.1 Actions to address risks and opportunities"),
            ("CTL-SENSITIVE-PROTECTED", "Clause 8.1 Operational planning and control"),
            ("CTL-AUDIT-ACTIVE", "Clause 7.5 Documented information"),
            ("CTL-REVIEWS-CURRENT", "Clause 9.1 Monitoring, measurement, analysis and evaluation"),
            ("CTL-INCIDENT-SLA", "Clause 10.2 Nonconformity and corrective action"),
            ("CTL-INCIDENT-CLOSURE", "Clause 10.2 Nonconformity and corrective action"),
        ),
    ),
    "SOC_2": (
        "SOC 2 Trust Services Criteria",
        (
            ("CTL-ADMIN-AUTH", "CC6.1 Logical access security"),
            ("CTL-SENSITIVE-PROTECTED", "CC6.7 Restricting transmission of information"),
            ("CTL-HIGH-RISK-RESTRICTED", "CC6.7 Restricting transmission of information"),
            ("CTL-POLICY-ENFORCED", "CC5.2 Control activities over technology"),
            ("CTL-AUDIT-ACTIVE", "CC7.2 Monitoring of system components"),
            ("CTL-REVIEWS-CURRENT", "CC4.1 Monitoring activities"),
            ("CTL-INCIDENT-SLA", "CC7.4 Incident response"),
            ("CTL-INCIDENT-CLOSURE", "CC7.5 Recovery from incidents"),
            ("CTL-RETENTION", "P4.2 Retention of personal information"),
            ("CTL-REQUESTS-TIMELY", "P4.3 Disposal of personal information"),
        ),
    ),
}


def evaluate_framework(framework: str, ctx: ControlContext) -> FrameworkScore:
    name, mapping = FRAMEWORKS[framework]
    results: list[ControlResult] = []
    for control_id, reference in mapping:
        definition = CONTROLS[control_id]
        outcome = definition.check(ctx)
        results.append(
            ControlResult(
                control_id=control_id,
                title=definition.title,
                description=definition.description,
                reference=reference,
                status=outcome.status,
                evidence=outcome.evidence,
                remediation=None if outcome.status == "PASS" else definition.remediation,
            )
        )
    points = sum(STATUS_POINTS[r.status] for r in results)
    return FrameworkScore(
        framework=framework,
        name=name,
        score=round(100 * points / len(results)),
        pass_count=sum(r.status == "PASS" for r in results),
        partial_count=sum(r.status == "PARTIAL" for r in results),
        fail_count=sum(r.status == "FAIL" for r in results),
        total=len(results),
        controls=results,
    )
