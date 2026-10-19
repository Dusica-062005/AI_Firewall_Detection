"""The governance boundary: detection -> policy -> protection -> outbound validation.

Every stage fails closed. A failure is reported as a technical failure (not a blocked
decision) and nothing downstream of it runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.detection.analyzer import DetectionError, SensitiveDataAnalyzer
from app.detection.entities import DetectedEntity
from app.policy.dial import dial_extra_entities, dial_protects
from app.policy.engine import PolicyDecision, PolicyEngine, PolicyEvaluationError
from app.policy.models import Action, Destination, Policy
from app.security.outbound_validator import (
    DECISION_LABELS,
    OutboundValidationError,
    OutboundValidator,
    ValidatedPayload,
    ValidationCheck,
)
from app.security.redactor import RedactionError, Redactor, TokenInfo


@dataclass(frozen=True)
class Failure:
    category: str  # DETECTION_FAILURE | POLICY_LOAD_FAILURE | POLICY_EVALUATION_FAILURE | REDACTION_FAILURE
    step: str
    message: str


@dataclass
class ProtectionOutcome:
    entities: list[DetectedEntity] = field(default_factory=list)
    decision: PolicyDecision | None = None
    redacted_text: str | None = None  # tokenized text, e.g. "[PERSON_1] called about ..."
    tokens: tuple[TokenInfo, ...] = ()
    # Everything that was tokenized: the policy's redactions plus any the dial added.
    protected_entities: list[DetectedEntity] = field(default_factory=list)
    dial: str = "max_quality"
    failure: Failure | None = None
    detection_ms: float | None = None
    policy_ms: float | None = None
    protection_ms: float | None = None

    @property
    def label(self) -> str:
        if self.failure or self.decision is None:
            return "PROCESSING_FAILED"
        return DECISION_LABELS[self.decision.action.value]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class FirewallService:
    def __init__(
        self,
        analyzer: SensitiveDataAnalyzer,
        engine: PolicyEngine,
        redactor: Redactor,
        validator: OutboundValidator,
        policy_source,  # callable returning list[Policy]
    ) -> None:
        self.analyzer = analyzer
        self.engine = engine
        self.redactor = redactor
        self.validator = validator
        self._policy_source = policy_source

    def protect(self, text: str, profile: str, channel: str, dial: str = "max_quality") -> ProtectionOutcome:
        outcome = ProtectionOutcome(dial=dial)

        started = time.perf_counter()
        try:
            outcome.entities = self.analyzer.analyze(text)
        except DetectionError:
            outcome.detection_ms = _ms(started)
            outcome.failure = Failure("DETECTION_FAILURE", "analyzed", "Sensitive-data detection could not be completed.")
            return outcome
        outcome.detection_ms = _ms(started)

        started = time.perf_counter()
        try:
            policies: list[Policy] = self._policy_source()
        except Exception:  # noqa: BLE001 - policy store failure must fail closed
            outcome.policy_ms = _ms(started)
            outcome.failure = Failure("POLICY_LOAD_FAILURE", "policy", "Policy configuration could not be loaded.")
            return outcome
        try:
            outcome.decision = self.engine.evaluate(outcome.entities, policies, profile, channel)
        except PolicyEvaluationError:
            outcome.policy_ms = _ms(started)
            outcome.failure = Failure("POLICY_EVALUATION_FAILURE", "policy", "Policy evaluation failed.")
            return outcome
        outcome.policy_ms = _ms(started)

        started = time.perf_counter()
        protected = list(outcome.decision.entities_to_redact) + dial_extra_entities(dial, outcome.decision)
        try:
            tokenized = self.redactor.redact(text, protected)
        except RedactionError:
            outcome.protection_ms = _ms(started)
            outcome.failure = Failure("REDACTION_FAILURE", "protected", "Redaction could not be completed or verified.")
            outcome.redacted_text = None
            return outcome
        outcome.redacted_text = tokenized.text
        outcome.tokens = tokenized.tokens
        outcome.protected_entities = protected
        outcome.protection_ms = _ms(started)
        return outcome

    def restricted_categories(self, decision: PolicyDecision, dial: str = "max_quality") -> set[str]:
        """Categories that must not appear in a cloud-bound payload for this request."""
        policies = self._policy_source()
        restricted: set[str] = set()
        for category in self.analyzer.categories:
            action, destination = self.engine.resolve_category(category, policies, decision.profile, decision.channel)
            if action is not Action.ALLOW or destination is not Destination.CLOUD or dial_protects(dial, category):
                restricted.add(category)
        return restricted

    def build_cloud_payload(
        self,
        request_id: str,
        outcome: ProtectionOutcome,
        summary_text: str | None,
    ) -> ValidatedPayload:
        """Build and validate the cloud payload. Raises OutboundValidationError."""
        decision = outcome.decision
        if decision is None or outcome.redacted_text is None or outcome.failure is not None:
            raise OutboundValidationError(
                [ValidationCheck("enforcement_complete", False, "Enforcement did not complete; nothing can be sent.")]
            )
        payload_data = {
            "schema_version": "1.0",
            "request_id": request_id,
            "decision": DECISION_LABELS[decision.action.value],
            "destination": decision.destination.value,
            "profile": decision.profile,
            "channel": decision.channel,
            "policy_version": decision.policy_version,
            "entity_categories": sorted({e.entity_type for e in outcome.entities}),
            "sanitized_summary": summary_text,
            "sanitized_transcript": outcome.redacted_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        sensitive_values = [e.value for e in outcome.protected_entities]
        return self.validator.validate(
            payload_data,
            decision,
            request_id,
            sensitive_values,
            self.restricted_categories(decision, outcome.dial),
        )
