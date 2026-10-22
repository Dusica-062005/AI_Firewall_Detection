"""End-to-end, policy-controlled processing workflow.

Received -> Analyzed -> Policy evaluated -> Protected (tokenized) -> Routed: Local AI / Cloud
-> Re-hydrated locally -> Audited + signed receipt

The local model is called only when the policy decision authorizes local processing. The
cloud receiver is called only when the router chooses the cloud path (policy, kill switch,
dial and detection confidence all allow it) and the final payload passed outbound
validation. Nothing here trusts client-supplied decisions.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from app.ai.summarizer import MAX_SUMMARY_CHARS, Summarizer
from app.audit.service import AuditEntry, AuditService
from app.detection.analyzer import DetectionError
from app.integrations.cloudlink_client import HANDOFF_PATH, CloudLinkClient, CloudLinkRefused
from app.policy.models import Action
from app.schemas.requests import ProcessingMode
from app.schemas.responses import (
    AgentView,
    EntityResult,
    FirewallResult,
    LatencyBreakdown,
    MatchedPolicyResult,
    OutboundInfo,
    ProcessingStep,
    ReceiptRef,
    RoutingInfo,
    SummaryInfo,
    TokenResult,
    ValidationCheckResult,
)
from app.security.outbound_validator import OutboundValidationError
from app.security.redactor import contains_value
from app.services.firewall_service import FirewallService, ProtectionOutcome
from app.services.router import RouteDecision, decide_route
from app.trust.controls import ControlsService
from app.trust.receipts import ReceiptFacts, ReceiptService
from app.trust.vault import TokenVault, VaultUnavailable

logger = logging.getLogger(__name__)

SUMMARY_WARNINGS = {
    "UNAVAILABLE": "LOCAL_MODEL_UNAVAILABLE",
    "MODEL_MISSING": "LOCAL_MODEL_MISSING",
    "TIMEOUT": "LOCAL_MODEL_TIMEOUT",
    "INVALID_OUTPUT": "LOCAL_MODEL_INVALID_OUTPUT",
    "ERROR": "LOCAL_MODEL_ERROR",
}
OUTBOUND_WARNINGS = {
    "VALIDATION_FAILED": "OUTBOUND_VALIDATION_FAILED",
    "UNAVAILABLE": "CLOUDLINK_UNAVAILABLE",
    "REJECTED": "CLOUDLINK_REJECTED",
    "ERROR": "CLOUDLINK_ERROR",
}
# Outbound statuses where the router (not policy) held the request back.
HELD_STATUS = {"kill_switch": "KILL_SWITCH"}


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class ProcessingService:
    def __init__(
        self,
        firewall: FirewallService,
        summarizer: Summarizer,
        cloudlink: CloudLinkClient,
        audit: AuditService,
        expose_detected_values: bool,
        controls: ControlsService,
        vault: TokenVault,
        receipts: ReceiptService,
        low_confidence_stays_local: bool = True,
        normalize_on: bool = False,
    ) -> None:
        self.firewall = firewall
        self.summarizer = summarizer
        self.cloudlink = cloudlink
        self.audit = audit
        self.expose_detected_values = expose_detected_values
        self.controls = controls
        self.vault = vault
        self.receipts = receipts
        self.low_confidence_stays_local = low_confidence_stays_local
        self.normalize_on = normalize_on

    async def run(
        self,
        *,
        request_id: str,
        transcript: str,
        profile: str,
        channel: str,
        mode: ProcessingMode,
        operation: str,
        dial: str | None = None,
        run_models: bool = True,
        normalize: bool | None = None,
        audio: dict | None = None,
    ) -> FirewallResult:
        """Process one call.

        ``dial`` overrides the operator dial for this request only (used by measurement runs).
        ``run_models=False`` skips both summaries while keeping routing, the real outbound
        handoff and the receipt (used by leak-canary batches, where only the payload matters).
        ``normalize`` overrides the spoken-number normalizer setting for this request only.
        ``audio`` (audio calls) holds format, duration, model and transcription time; it goes into
        the latency breakdown and the signed receipt, never audio or text.
        """
        normalize_on = self.normalize_on if normalize is None else normalize
        total_started = time.perf_counter()
        warnings: list[tuple[str, str]] = []
        steps: list[ProcessingStep] = [
            ProcessingStep(
                key="received",
                label="Received",
                status="COMPLETED",
                detail=f"{len(transcript)} characters accepted for profile '{profile}' on channel '{channel}'.",
            )
        ]

        controls = await run_in_threadpool(self.controls.get)
        dial = dial or controls.dial
        outcome: ProtectionOutcome = await run_in_threadpool(
            self.firewall.protect, transcript, profile, channel, dial, normalize_on
        )
        decision = outcome.decision
        failure = outcome.failure
        label = outcome.label

        steps.extend(self._security_steps(outcome))

        route = decide_route(
            failed=failure is not None,
            decision=decision,
            mode=mode,
            kill_switch=controls.kill_switch,
            dial=dial,
            entities=outcome.entities,
            low_confidence_stays_local=self.low_confidence_stays_local,
        )

        # ---- Vault: store the encrypted token -> value map locally ----------------------
        vault_ready = False
        if failure is None and outcome.tokens:
            try:
                await run_in_threadpool(self.vault.store, request_id, outcome.tokens)
                vault_ready = True
            except VaultUnavailable as exc:
                warnings.append(("VAULT_UNAVAILABLE", f"Tokens could not be stored in the vault: {exc}"))
            except Exception:  # noqa: BLE001 - the vault only affects re-hydration, never protection
                warnings.append(("VAULT_UNAVAILABLE", "Tokens could not be stored in the vault."))

        summary = SummaryInfo(status="SKIPPED_BY_MODE", text=None, model=None, latency_ms=None, message="")
        outbound = OutboundInfo(
            status="SKIPPED_BY_MODE", reached_receiver=False, target=None, payload=None, receiver_response=None,
            http_status=None, latency_ms=None, validation=[], message="",
        )
        local_ai_ms: float | None = None
        validation_ms: float | None = None
        cloud_ms: float | None = None
        receipt_id: str | None = None

        # ---- Local AI -------------------------------------------------------------
        if failure is not None or decision is None:
            summary = summary.model_copy(update={"status": "NOT_AUTHORIZED", "message": "Not run: enforcement did not complete."})
        elif mode is ProcessingMode.INSPECT:
            summary = summary.model_copy(update={"message": "Not run: inspection mode does not invoke AI."})
        elif not decision.local_ai_authorized:
            summary = summary.model_copy(update={"status": "NOT_AUTHORIZED", "message": "Not run: the policy decision does not permit AI processing."})
        elif not run_models:
            summary = summary.model_copy(update={"message": "Not run: model calls are disabled for this measurement run."})
        else:
            started = time.perf_counter()
            result = await self.summarizer.summarize(outcome.redacted_text or "")
            local_ai_ms = _ms(started)
            summary = SummaryInfo(
                status=result.status, text=result.text, model=result.model, latency_ms=local_ai_ms, message=result.message
            )
            if result.status in SUMMARY_WARNINGS:
                warnings.append((SUMMARY_WARNINGS[result.status], result.message))

        # ---- Cloud handoff (only when the router chose the cloud path) --------------------
        cloud_summary_status: str | None = None
        cloud_summary: str | None = None
        cloud_model: str | None = None
        cloud_latency: float | None = None
        if route.route == "CLOUD" and await run_in_threadpool(self.controls.kill_switch_on):
            # Re-checked immediately before sending so a toggle mid-batch takes effect at once.
            route = RouteDecision("LOCAL", "kill_switch", "Kill switch turned on before sending: the cloud path is blocked.")

        if failure is not None or decision is None:
            outbound = outbound.model_copy(update={"status": "NOT_AUTHORIZED", "message": "No outbound request: enforcement did not complete."})
        elif mode is not ProcessingMode.FULL:
            outbound = outbound.model_copy(update={"message": "No outbound request: the selected mode does not include cloud handoff."})
        elif not decision.cloud_authorized:
            outbound = outbound.model_copy(
                update={"status": "NOT_AUTHORIZED", "message": f"No outbound request: decision {label} does not authorize cloud transmission."}
            )
        elif route.route != "CLOUD":
            outbound = outbound.model_copy(
                update={"status": HELD_STATUS.get(route.reason, "HELD_LOCAL"), "message": f"No outbound request: {route.message}"}
            )
        else:
            summary_text = summary.text if summary.status == "GENERATED" else None
            started = time.perf_counter()
            try:
                validated = await run_in_threadpool(self.firewall.build_cloud_payload, request_id, outcome, summary_text)
                validation_ms = _ms(started)
            except OutboundValidationError as exc:
                validation_ms = _ms(started)
                validated = None
                outbound = outbound.model_copy(
                    update={
                        "status": "VALIDATION_FAILED",
                        "validation": [ValidationCheckResult(name=c.name, passed=c.passed, detail=c.detail) for c in exc.checks],
                        "message": "No outbound request: the final payload failed validation.",
                    }
                )
            except Exception:  # noqa: BLE001 - any validation error denies transmission
                validation_ms = _ms(started)
                validated = None
                outbound = outbound.model_copy(
                    update={"status": "VALIDATION_FAILED", "message": "No outbound request: payload validation could not be completed."}
                )

            if validated is not None:
                checks = [ValidationCheckResult(name=c.name, passed=c.passed, detail=c.detail) for c in validated.checks]
                started = time.perf_counter()
                try:
                    handoff = await self.cloudlink.send(validated, skip_cloud_summary=not run_models)
                    cloud_ms = _ms(started)
                    sent = handoff.http_status is not None
                    outbound = OutboundInfo(
                        status=handoff.status,
                        reached_receiver=sent,
                        target=f"{self.cloudlink.base_url}{HANDOFF_PATH}",
                        payload=validated.payload.model_dump(mode="json"),
                        receiver_response=handoff.receiver_response,
                        http_status=handoff.http_status,
                        latency_ms=cloud_ms,
                        validation=checks,
                        message=handoff.message,
                    )
                    if handoff.status == "SENT" and handoff.receiver_response:
                        response = handoff.receiver_response
                        receipt_id = response.get("receipt_id")
                        cloud_model = response.get("cloud_model")
                        cloud_latency = response.get("cloud_latency_ms")
                        cloud_summary_status, cloud_summary = await run_in_threadpool(
                            self._check_cloud_summary, response, outcome
                        )
                except CloudLinkRefused as exc:
                    cloud_ms = _ms(started)
                    outbound = outbound.model_copy(
                        update={"status": "VALIDATION_FAILED", "validation": checks, "message": f"No outbound request: {exc}"}
                    )
            if outbound.status in OUTBOUND_WARNINGS:
                warnings.append((OUTBOUND_WARNINGS[outbound.status], outbound.message))
            if outbound.status == "VALIDATION_FAILED":
                route = RouteDecision("LOCAL", "cloud_validation_failed", "The cloud payload failed validation, so nothing was sent.")
            elif outbound.status in ("UNAVAILABLE", "REJECTED", "ERROR"):
                route = RouteDecision("LOCAL", "cloud_unavailable", "The cloud stand-in was unavailable; the local result is used.")

        if decision is not None and decision.no_applicable_policy:
            warnings.append(("NO_APPLICABLE_POLICY", decision.reasons[0]))

        # ---- Re-hydrate locally for the agent ------------------------------------------------
        agent_view = await self._agent_view(request_id, outcome, summary, cloud_summary, vault_ready, warnings)

        routing = RoutingInfo(
            route=route.route,  # type: ignore[arg-type]
            reason=route.reason,
            message=route.message,
            kill_switch=controls.kill_switch or route.reason == "kill_switch",
            dial=dial,
            cloud_model=cloud_model,
            cloud_summary_status=cloud_summary_status,
            cloud_summary=cloud_summary,
            cloud_latency_ms=cloud_latency,
        )
        steps.append(self._ai_step(label, mode, summary, outbound, failure is not None, local_ai_ms, cloud_ms, route))

        status = "FAILED" if failure else ("COMPLETED_WITH_WARNINGS" if warnings else "COMPLETED")
        total_ms = _ms(total_started)
        latency = LatencyBreakdown(
            transcription_ms=audio["transcription_ms"] if audio else None,
            detection_ms=outcome.detection_ms,
            policy_ms=outcome.policy_ms,
            protection_ms=outcome.protection_ms,
            local_ai_ms=local_ai_ms,
            validation_ms=validation_ms,
            cloud_ms=cloud_ms,
            total_ms=total_ms,
        )
        entity_counts = dict(Counter(e.entity_type for e in outcome.entities))
        destination = decision.destination.value if decision and not failure else "NONE"
        policy_ids = tuple(p.policy_id for p in decision.matched_policies) if decision else ()
        error_category = failure.category if failure else (warnings[0][0] if warnings else None)

        # ---- Audit ------------------------------------------------------------------
        audit_started = time.perf_counter()
        event_id: str | None = None
        try:
            entry = AuditEntry(
                request_id=request_id,
                operation=operation,
                mode=mode.value,
                profile=profile,
                channel=channel,
                decision=label,
                status=status,
                destination=destination,
                local_ai_status=summary.status,
                cloud_status=outbound.status,
                policy_version=decision.policy_version if decision else "unavailable",
                decisive_policy_id=decision.decisive_policy_id if decision else "none",
                policy_ids=policy_ids,
                entity_counts=entity_counts,
                latency_ms=latency.model_dump(exclude={"total_ms", "audit_ms"}),
                total_latency_ms=total_ms,
                error_category=error_category,
                transcript_chars=len(transcript),
                warnings=tuple(code for code, _ in warnings),
                cloud_receipt_id=receipt_id,
            )
            event_id = await run_in_threadpool(self.audit.record, entry)
            audit_detail = f"Audit event {event_id} recorded without transcript content or entity values."
            audit_status = "COMPLETED"
        except Exception:  # noqa: BLE001
            logger.error("audit write failed", extra={"request_id": request_id})
            warnings.append(("AUDIT_WRITE_FAILED", "The audit event could not be written to the database."))
            audit_detail = "Audit event could not be written."
            audit_status = "FAILED"

        # ---- Signed, hash-chained receipt -------------------------------------------------
        receipt_ref: ReceiptRef | None = None
        try:
            facts = self._receipt_facts(request_id, event_id, operation, label, decision, outcome, route,
                                        summary, cloud_model, outbound, controls.kill_switch, dial, normalize_on, audio)
            record = await run_in_threadpool(self.receipts.append, facts)
            receipt_ref = ReceiptRef(receipt_id=record.receipt_id, seq=record.seq, hash=record.hash, signed=record.signature is not None)
            audit_detail += f" Receipt #{record.seq} {'signed' if record.signature else 'UNSIGNED'} and chained."
            if record.signature is None:
                warnings.append(("RECEIPT_UNSIGNED", f"Receipt written without a signature: {self.receipts.key_status.message}"))
        except Exception:  # noqa: BLE001
            logger.error("receipt write failed", extra={"request_id": request_id})
            warnings.append(("RECEIPT_WRITE_FAILED", "The signed receipt could not be written."))
            audit_status = "FAILED"
        if warnings and status == "COMPLETED":
            status = "COMPLETED_WITH_WARNINGS"
        audit_ms = _ms(audit_started)
        steps.append(ProcessingStep(key="audited", label="Audited", status=audit_status, duration_ms=audit_ms, detail=audit_detail))
        latency = latency.model_copy(update={"audit_ms": audit_ms})

        logger.info(
            "request processed",
            extra={
                "request_id": request_id,
                "operation": operation,
                "decision": label,
                "status": status,
                "entity_categories": sorted(entity_counts),
                "total_ms": total_ms,
            },
        )

        return FirewallResult(
            request_id=request_id,
            event_id=event_id,
            operation=operation,  # type: ignore[arg-type]
            mode=mode.value,
            profile=profile,
            channel=channel,
            decision=label,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            authorized_destination=destination,  # type: ignore[arg-type]
            policy_version=decision.policy_version if decision else None,
            decisive_policy_id=decision.decisive_policy_id if decision else None,
            error_category=error_category,
            reasons=list(decision.reasons) if decision else [failure.message if failure else "Processing failed."],
            warnings=[message for _, message in warnings],
            transcript_chars=len(transcript),
            entities=self._entity_results(outcome),
            entity_counts=entity_counts,
            matched_policies=[
                MatchedPolicyResult(
                    policy_id=p.policy_id, name=p.name, action=p.action.value, destination=p.destination.value,
                    priority=p.priority, matched_categories=list(p.matched_categories),
                )
                for p in (decision.matched_policies if decision else ())
            ],
            redacted_transcript=outcome.redacted_text if not failure else None,
            tokens=[
                TokenResult(token=t.token, entity_type=t.entity_type, value=t.value if self.expose_detected_values else None)
                for t in outcome.tokens
            ] if not failure else [],
            summary=summary,
            outbound=outbound,
            routing=routing,
            agent_view=agent_view,
            receipt=receipt_ref,
            steps=steps,
            latency=latency,
            created_at=datetime.now(timezone.utc),
        )

    def _check_cloud_summary(self, response: dict, outcome: ProtectionOutcome) -> tuple[str, str | None]:
        """The cloud answer is untrusted: size, protected values and a restricted re-scan."""
        status = str(response.get("cloud_summary_status") or "DISABLED")
        text = response.get("cloud_summary")
        if status != "GENERATED":
            return status, None
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SUMMARY_CHARS:
            return "INVALID_OUTPUT", None
        if any(contains_value(text, e.value) for e in outcome.protected_entities):
            return "INVALID_OUTPUT", None
        try:
            restricted = self.firewall.restricted_categories(outcome.decision, outcome.dial)
            if any(e.entity_type in restricted for e in self.firewall.analyzer.scan(text, resolve_overlaps=False)):
                return "INVALID_OUTPUT", None
        except DetectionError:
            return "INVALID_OUTPUT", None
        return "GENERATED", text

    async def _agent_view(
        self,
        request_id: str,
        outcome: ProtectionOutcome,
        summary: SummaryInfo,
        cloud_summary: str | None,
        vault_ready: bool,
        warnings: list[tuple[str, str]],
    ) -> AgentView:
        if cloud_summary:
            source, tokenized = "CLOUD", cloud_summary
        elif summary.status == "GENERATED" and summary.text:
            source, tokenized = "LOCAL", summary.text
        else:
            return AgentView(status="NO_SUMMARY", source="NONE", summary=None, tokenized_summary=None,
                             message="No summary was produced for this request.")
        label = "cloud stand-in" if source == "CLOUD" else "local model"
        if not outcome.tokens:
            return AgentView(status="REHYDRATED", source=source, summary=tokenized, tokenized_summary=tokenized,
                             message=f"Summary from the {label}; there were no tokens to restore.")
        if not vault_ready:
            return AgentView(status="TOKENS_ONLY", source=source, summary=None, tokenized_summary=tokenized,
                             message="The vault is not available, so tokens cannot be restored.")
        try:
            restored = await run_in_threadpool(self.vault.rehydrate, request_id, tokenized)
        except VaultUnavailable as exc:
            warnings.append(("VAULT_UNAVAILABLE", str(exc)))
            return AgentView(status="TOKENS_ONLY", source=source, summary=None, tokenized_summary=tokenized,
                             message="Tokens could not be restored from the vault.")
        return AgentView(status="REHYDRATED", source=source, summary=restored, tokenized_summary=tokenized,
                         message=f"Summary from the {label}; tokens restored locally from the encrypted vault.")

    def _receipt_facts(
        self, request_id, event_id, operation, label, decision, outcome: ProtectionOutcome, route: RouteDecision,
        summary: SummaryInfo, cloud_model, outbound: OutboundInfo, kill_switch: bool, dial: str, normalize_on: bool,
        audio: dict | None = None,
    ) -> ReceiptFacts:
        sent_texts = [t for t in ((outbound.payload or {}).get(k) for k in ("sanitized_transcript", "sanitized_summary")) if t]
        protected_ids = {id(e) for e in outcome.protected_entities}
        protected_left = any(contains_value(t, e.value) for e in outcome.protected_entities for t in sent_texts)
        allowed_sent = sorted({
            e.entity_type for e in outcome.entities
            if id(e) not in protected_ids and any(contains_value(t, e.value) for t in sent_texts)
        })
        return ReceiptFacts(
            request_id=request_id,
            event_id=event_id,
            operation=operation,
            decision=label,
            policy_version=decision.policy_version if decision else "unavailable",
            entity_counts=dict(Counter(e.entity_type for e in outcome.entities)),
            tokens_created=len(outcome.tokens),
            route=route.route,
            route_reason=route.reason,
            local_model=summary.model if summary.status == "GENERATED" else None,
            cloud_model=cloud_model,
            cloud_sent=outbound.reached_receiver,
            protected_values_left=protected_left,
            allowed_categories_sent=allowed_sent,
            kill_switch=kill_switch,
            dial=dial,
            normalize_on=normalize_on,
            audio=audio,
        )

    def _entity_results(self, outcome: ProtectionOutcome) -> list[EntityResult]:
        if outcome.decision is None:
            return [
                EntityResult(
                    entity_type=e.entity_type, start=e.start, end=e.end, score=e.score, low_confidence=e.low_confidence,
                    recognizer=e.recognizer, value=e.value if self.expose_detected_values else None,
                    action="UNRESOLVED", destination="NONE", policy_id="none", policy_name="Not evaluated",
                    reason="Policy evaluation did not complete.",
                )
                for e in outcome.entities
            ]
        return [
            EntityResult(
                entity_type=d.entity.entity_type, start=d.entity.start, end=d.entity.end, score=d.entity.score,
                low_confidence=d.entity.low_confidence, recognizer=d.entity.recognizer,
                value=d.entity.value if self.expose_detected_values else None,
                action=d.action.value, destination=d.destination.value, policy_id=d.policy_id,
                policy_name=d.policy_name, reason=d.reason,
            )
            for d in outcome.decision.entity_decisions
        ]

    @staticmethod
    def _security_steps(outcome: ProtectionOutcome) -> list[ProcessingStep]:
        failure = outcome.failure
        failed_step = failure.step if failure else None
        order = ["analyzed", "policy", "protected"]
        labels = {"analyzed": "Analyzed", "policy": "Policy evaluated", "protected": "Protected"}
        durations = {"analyzed": outcome.detection_ms, "policy": outcome.policy_ms, "protected": outcome.protection_ms}
        steps: list[ProcessingStep] = []
        reached_failure = False
        for key in order:
            if reached_failure:
                steps.append(ProcessingStep(key=key, label=labels[key], status="SKIPPED", detail="Not run after an earlier failure."))
                continue
            if key == failed_step:
                reached_failure = True
                steps.append(ProcessingStep(key=key, label=labels[key], status="FAILED", duration_ms=durations[key], detail=failure.message))
                continue
            if key == "analyzed":
                cats = sorted({e.entity_type for e in outcome.entities})
                detail = (
                    f"{len(outcome.entities)} sensitive entities detected: {', '.join(cats)}."
                    if cats
                    else "No sensitive entities detected."
                )
                steps.append(ProcessingStep(key=key, label=labels[key], status="COMPLETED", duration_ms=durations[key], detail=detail))
            elif key == "policy":
                d = outcome.decision
                blocked = d.action is Action.BLOCK
                steps.append(ProcessingStep(
                    key=key, label=labels[key], status="BLOCKED" if blocked else "COMPLETED", duration_ms=durations[key],
                    detail=f"Decision {outcome.label}; authorized destination {d.destination.value}; decisive rule {d.decisive_policy_id}.",
                ))
            else:
                count = len(outcome.decision.entities_to_redact)
                detail = (
                    f"{count} span(s) replaced with placeholders and verified."
                    if count
                    else "No redaction required by policy."
                )
                steps.append(ProcessingStep(key=key, label=labels[key], status="COMPLETED", duration_ms=durations[key], detail=detail))
        return steps

    @staticmethod
    def _ai_step(label, mode, summary, outbound, failed, local_ai_ms, cloud_ms, route: RouteDecision) -> ProcessingStep:
        duration = sum(v for v in (local_ai_ms, cloud_ms) if v is not None) or None
        if failed:
            return ProcessingStep(key="ai", label="Local AI / Cloud", status="SKIPPED", detail="No AI processing or outbound request after an enforcement failure.")
        if label == "BLOCKED":
            return ProcessingStep(key="ai", label="Local AI / Cloud", status="BLOCKED", detail="Blocked by policy: no local model call and no outbound request.")
        if mode is ProcessingMode.INSPECT:
            return ProcessingStep(key="ai", label="Local AI / Cloud", status="SKIPPED", detail="Inspection mode: no model call and no outbound request.")
        parts = [
            f"Route {route.route} ({route.reason.replace('_', ' ')}).",
            f"Local AI: {summary.status.replace('_', ' ').lower()}.",
            f"Cloud: {outbound.status.replace('_', ' ').lower()}.",
        ]
        problem = summary.status in SUMMARY_WARNINGS or outbound.status in OUTBOUND_WARNINGS
        return ProcessingStep(key="ai", label="Local AI / Cloud", status="WARNING" if problem else "COMPLETED", duration_ms=duration, detail=" ".join(parts))
