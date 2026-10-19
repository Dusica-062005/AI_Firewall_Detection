"""Compliance overview and evidence-pack generation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime

from app.audit.service import AuditService
from app.compliance.controls import FRAMEWORKS, ControlContext, evaluate_framework
from app.compliance.data_requests import DataRequestService
from app.compliance.incidents import IncidentService
from app.compliance.systems import AiSystemService
from app.config import Settings
from app.db.models import AuditEventRecord
from app.db.repositories import utcnow
from app.schemas.compliance import (
    AuditEvidence,
    ComplianceKpis,
    ComplianceOverview,
    DataRequestEvidence,
    EvidencePack,
    IncidentEvidence,
    PolicyEvidence,
    PolicyRuleEvidence,
)
from app.services.policy_service import PolicyService

DISCLAIMER = (
    "Indicative mapping generated from the live configuration of the Mitel AI Data Firewall prototype. "
    "It is a demonstration aid, not legal advice and not a certification or attestation."
)


class ComplianceService:
    def __init__(
        self,
        settings: Settings,
        policies: PolicyService,
        audit: AuditService,
        systems: AiSystemService,
        incidents: IncidentService,
        data_requests: DataRequestService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._audit = audit
        self._systems = systems
        self._incidents = incidents
        self._data_requests = data_requests
        self._clock = clock

    def _context(self) -> ControlContext:
        storage = self._audit.storage_info()
        return ControlContext(
            now=self._clock(),
            policies=self._policies.list(),
            known_categories=sorted(self._policies.known_categories),
            unmatched_action=self._settings.unmatched_entity_action,
            admin_key_configured=bool(self._settings.admin_api_key.get_secret_value()),
            audit_event_count=storage["event_count"],
            audit_retention_days=storage["retention_days"],
            audit_stores_transcripts=storage["stores_raw_transcripts"],
            audit_stores_entity_values=storage["stores_entity_values"],
            audit_columns=[c.name for c in AuditEventRecord.__table__.columns],
            systems=self._systems.list(),
            incidents=self._incidents.list(),
            data_requests=self._data_requests.list(),
        )

    def overview(self) -> ComplianceOverview:
        ctx = self._context()
        frameworks = [evaluate_framework(f, ctx) for f in FRAMEWORKS]
        active = [s for s in ctx.systems if s.status != "RETIRED"]
        return ComplianceOverview(
            generated_at=ctx.now,
            overall_score=round(sum(f.score for f in frameworks) / len(frameworks)),
            frameworks=frameworks,
            kpis=ComplianceKpis(
                ai_systems=len(active),
                reviews_overdue=sum(s.review_overdue for s in active),
                open_incidents=sum(i.status != "CLOSED" for i in ctx.incidents),
                sla_breached=sum(i.sla_state == "BREACHED" for i in ctx.incidents),
                open_data_requests=sum(r.status == "OPEN" for r in ctx.data_requests),
                overdue_data_requests=sum(r.overdue for r in ctx.data_requests),
            ),
        )

    def evidence(self, framework: str) -> EvidencePack:
        ctx = self._context()
        scored = evaluate_framework(framework, ctx)
        storage = self._audit.storage_info()
        rules = [
            PolicyRuleEvidence(
                policy_id=p.policy_id,
                name=p.name,
                enabled=p.enabled,
                action=p.action.value,
                destination=p.destination.value,
                categories=list(p.entity_categories),
                profiles=list(p.conditions.profiles),
            )
            for p in ctx.policies
        ]
        done = [r for r in ctx.data_requests if r.completed_at]
        return EvidencePack(
            framework=framework,
            framework_name=scored.name,
            generated_at=ctx.now,
            disclaimer=DISCLAIMER,
            score=scored.score,
            controls=scored.controls,
            ai_systems=ctx.systems,
            policies=PolicyEvidence(
                policy_version=self._policies.version(),
                total=len(rules),
                enabled=sum(r.enabled for r in rules),
                rules=rules,
            ),
            audit=AuditEvidence(
                retention_days=storage["retention_days"],
                event_count=storage["event_count"],
                oldest_event_at=storage["oldest_event_at"],
                stores_raw_transcripts=storage["stores_raw_transcripts"],
                stores_entity_values=storage["stores_entity_values"],
                decision_counts=self._audit.metrics(24).decision_counts,
            ),
            incidents=IncidentEvidence(
                total=len(ctx.incidents),
                open=sum(i.status != "CLOSED" for i in ctx.incidents),
                closed=sum(i.status == "CLOSED" for i in ctx.incidents),
                contained_within_sla=sum(i.sla_state == "MET" for i in ctx.incidents),
                sla_missed=sum(i.sla_state == "MISSED" for i in ctx.incidents),
                sla_breached_open=sum(i.sla_state == "BREACHED" for i in ctx.incidents),
                by_severity=dict(Counter(i.severity for i in ctx.incidents)),
            ),
            data_requests=DataRequestEvidence(
                total=len(ctx.data_requests),
                open=sum(r.status == "OPEN" for r in ctx.data_requests),
                completed=len(done),
                completed_on_time=sum(r.completed_at <= r.due_at for r in done),
                completed_late=sum(r.completed_at > r.due_at for r in done),
                overdue_open=sum(r.overdue for r in ctx.data_requests),
            ),
        )
