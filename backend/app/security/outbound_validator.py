"""Final gate before any cloud transmission.

Model output and redacted text are treated as untrusted. A payload is sendable only if
every check passes; any exception while checking counts as a failure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import ValidationError

from app.detection.analyzer import DetectionError, SensitiveDataAnalyzer
from app.integrations.contracts import CLOUD_DECISIONS, CloudHandoffPayload
from app.policy.engine import PolicyDecision
from app.security.redactor import contains_value

DECISION_LABELS = {"ALLOW": "ALLOWED", "REDACT": "REDACTED", "LOCAL_ONLY": "LOCAL_ONLY", "BLOCK": "BLOCKED"}


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str


class OutboundValidationError(Exception):
    def __init__(self, checks: list[ValidationCheck]) -> None:
        super().__init__("Outbound payload failed validation.")
        self.checks = checks


@dataclass(frozen=True)
class ValidatedPayload:
    """Proof that a specific payload passed validation for a specific decision."""

    payload: CloudHandoffPayload
    fingerprint: str
    request_id: str
    checks: tuple[ValidationCheck, ...]


def payload_fingerprint(payload: CloudHandoffPayload) -> str:
    return hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()


class OutboundValidator:
    def __init__(self, analyzer: SensitiveDataAnalyzer, max_payload_bytes: int = 131072) -> None:
        self._analyzer = analyzer
        self._max_payload_bytes = max_payload_bytes

    def validate(
        self,
        payload_data: dict,
        decision: PolicyDecision,
        request_id: str,
        sensitive_values: list[str],
        restricted_categories: set[str],
    ) -> ValidatedPayload:
        checks: list[ValidationCheck] = []

        def add(name: str, passed: bool, detail: str) -> None:
            checks.append(ValidationCheck(name, passed, detail))

        add(
            "policy_authorization",
            decision.cloud_authorized,
            "Policy authorizes cloud transmission."
            if decision.cloud_authorized
            else "Policy does not authorize cloud transmission.",
        )

        payload: CloudHandoffPayload | None = None
        try:
            payload = CloudHandoffPayload.model_validate(payload_data)
            add("schema", True, "Payload matches the CloudLink handoff schema.")
        except ValidationError as exc:
            add("schema", False, f"Payload failed schema validation ({exc.error_count()} error(s)).")

        if payload is not None:
            expected_label = DECISION_LABELS[decision.action.value]
            bound = (
                payload.request_id == request_id
                and payload.policy_version == decision.policy_version
                and payload.decision == expected_label
                and payload.decision in CLOUD_DECISIONS
            )
            add(
                "decision_binding",
                bound,
                "Payload is bound to this request and policy decision."
                if bound
                else "Payload request, policy version or decision does not match the enforced decision.",
            )

            size = len(payload.model_dump_json().encode("utf-8"))
            add("size", size <= self._max_payload_bytes, f"Payload size {size} bytes (limit {self._max_payload_bytes}).")

            leaked = [v for v in sensitive_values if any(contains_value(t, v) for t in payload.text_fields())]
            add(
                "no_protected_values",
                not leaked,
                "No protected values appear in the payload."
                if not leaked
                else f"{len(leaked)} protected value(s) found in the payload.",
            )

            try:
                findings: list[str] = []
                for text in payload.text_fields():
                    findings.extend(
                        e.entity_type
                        for e in self._analyzer.scan(text, resolve_overlaps=False)
                        if e.entity_type in restricted_categories
                    )
                add(
                    "rescan",
                    not findings,
                    "Re-scan found no restricted entities in the payload."
                    if not findings
                    else f"Re-scan found restricted entities: {', '.join(sorted(set(findings)))}.",
                )
            except DetectionError:
                add("rescan", False, "Re-scan could not be completed; transmission denied.")

        if not all(c.passed for c in checks) or payload is None:
            raise OutboundValidationError(checks)
        return ValidatedPayload(
            payload=payload,
            fingerprint=payload_fingerprint(payload),
            request_id=request_id,
            checks=tuple(checks),
        )
