"""The receiver must only ever see payloads the policy authorized and validation approved."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.detection.analyzer import DetectionError
from app.integrations.cloudlink_client import CloudLinkRefused
from app.policy.engine import PolicyEvaluationError
from app.security.outbound_validator import ValidatedPayload
from app.security.redactor import RedactionError
from tests.conftest import DEMO_TRANSCRIPT


def test_permitted_sanitized_request_reaches_mock_cloudlink(harness):
    response = harness.process(profile="standard")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REDACTED"
    assert body["status"] == "COMPLETED"
    assert body["outbound"]["status"] == "SENT"
    assert body["outbound"]["reached_receiver"] is True
    assert body["outbound"]["receiver_response"]["status"] == "ACCEPTED"
    assert all(c["passed"] for c in body["outbound"]["validation"])

    sent = harness.receiver_transport.handoff_requests()
    assert len(sent) == 1
    wire = json.loads(sent[0].content)
    assert wire["sanitized_transcript"] == (
        "My name is [PERSON_1], my patient ID is [PATIENT_ID_1], and I need help with my appointment."
    )
    assert wire["sanitized_summary"] == "Customer requested assistance with an appointment."
    assert "John Smith" not in sent[0].content.decode()
    assert "48291" not in sent[0].content.decode()
    assert harness.receiver_app.state.counters["accepted"] == 1


def test_local_model_only_sees_redacted_text(harness):
    harness.process(profile="standard")
    assert len(harness.ollama.prompts) == 1
    assert "John Smith" not in harness.ollama.prompts[0]
    assert "48291" not in harness.ollama.prompts[0]


def test_blocked_request_never_reaches_mock_cloudlink(harness):
    body = harness.process(profile="restricted").json()
    assert body["decision"] == "BLOCKED"
    assert body["outbound"]["status"] == "NOT_AUTHORIZED"
    assert body["outbound"]["reached_receiver"] is False
    assert body["summary"]["status"] == "NOT_AUTHORIZED"
    assert harness.receiver_transport.requests == []
    assert harness.ollama.prompts == []  # blocked means no model call either


def test_local_only_request_never_reaches_mock_cloudlink(harness):
    body = harness.process(profile="healthcare").json()
    assert body["decision"] == "LOCAL_ONLY"
    assert body["authorized_destination"] == "LOCAL"
    assert body["summary"]["status"] == "GENERATED"
    assert body["outbound"]["status"] == "NOT_AUTHORIZED"
    assert harness.receiver_transport.requests == []


def test_government_id_blocks_under_standard_profile(harness):
    body = harness.process("My social security number is 512-44-7321, please reset my PIN.").json()
    assert body["decision"] == "BLOCKED"
    assert harness.receiver_transport.requests == []


def test_policy_evaluation_failure_prevents_outbound(harness, monkeypatch):
    def boom(*_args, **_kwargs):
        raise PolicyEvaluationError("forced")

    monkeypatch.setattr(harness.container.firewall.engine, "evaluate", boom)
    body = harness.process().json()
    assert body["decision"] == "PROCESSING_FAILED"
    assert body["status"] == "FAILED"
    assert body["error_category"] == "POLICY_EVALUATION_FAILURE"
    assert body["redacted_transcript"] is None
    assert harness.receiver_transport.requests == []
    assert harness.ollama.prompts == []


def test_policy_store_failure_prevents_outbound(harness, monkeypatch):
    def boom():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(harness.container.firewall, "_policy_source", boom)
    body = harness.process().json()
    assert body["decision"] == "PROCESSING_FAILED"
    assert body["error_category"] == "POLICY_LOAD_FAILURE"
    assert harness.receiver_transport.requests == []


def test_detection_failure_prevents_outbound(harness, monkeypatch):
    def boom(_text, **_options):
        raise DetectionError("forced")

    monkeypatch.setattr(harness.container.analyzer, "analyze", boom)
    body = harness.process().json()
    assert body["decision"] == "PROCESSING_FAILED"
    assert body["error_category"] == "DETECTION_FAILURE"
    assert [s["status"] for s in body["steps"]][:4] == ["COMPLETED", "FAILED", "SKIPPED", "SKIPPED"]
    assert harness.receiver_transport.requests == []
    assert harness.ollama.prompts == []


def test_redaction_failure_prevents_outbound(harness, monkeypatch):
    def boom(_text, _entities):
        raise RedactionError("forced")

    monkeypatch.setattr(harness.container.firewall.redactor, "redact", boom)
    body = harness.process().json()
    assert body["decision"] == "PROCESSING_FAILED"
    assert body["error_category"] == "REDACTION_FAILURE"
    assert harness.receiver_transport.requests == []


def test_model_output_leaking_a_protected_value_is_not_sent(harness):
    harness.ollama.fixed_text = "John Smith needs help with appointment 48291."
    body = harness.process().json()
    assert body["outbound"]["status"] == "VALIDATION_FAILED"
    failed = {c["name"] for c in body["outbound"]["validation"] if not c["passed"]}
    assert "no_protected_values" in failed
    assert harness.receiver_transport.handoff_requests() == []


def test_model_output_with_new_restricted_entity_is_not_sent(harness):
    harness.ollama.fixed_text = "Caller asked to email the details to someone@example.org."
    body = harness.process(transcript="Please send me the appointment details.").json()
    assert body["outbound"]["status"] == "VALIDATION_FAILED"
    assert harness.receiver_transport.handoff_requests() == []


def test_rescan_failure_prevents_outbound(harness, monkeypatch):
    def boom(_text):
        raise DetectionError("forced")

    monkeypatch.setattr(harness.container.analyzer, "scan", boom)
    body = harness.process().json()
    assert body["outbound"]["status"] == "VALIDATION_FAILED"
    assert harness.receiver_transport.handoff_requests() == []


def test_client_cannot_submit_decisions_or_destinations(harness):
    for extra in ({"decision": "ALLOWED"}, {"destination": "CLOUD"}, {"pre_approved": True}, {"cloud_authorized": True}):
        response = harness.process(profile="restricted", **extra)
        assert response.status_code == 422
    assert harness.receiver_transport.requests == []


def test_mode_can_only_narrow_policy(harness):
    inspect_body = harness.process(mode="inspect").json()
    assert inspect_body["summary"]["status"] == "SKIPPED_BY_MODE"
    assert inspect_body["outbound"]["status"] == "SKIPPED_BY_MODE"
    local_body = harness.process(mode="local").json()
    assert local_body["summary"]["status"] == "GENERATED"
    assert local_body["outbound"]["status"] == "SKIPPED_BY_MODE"
    assert harness.receiver_transport.requests == []


def test_inspect_endpoint_never_calls_ai_or_cloud(harness):
    body = harness.client.post("/api/inspect", json={"transcript": DEMO_TRANSCRIPT, "profile": "standard"}).json()
    assert body["operation"] == "INSPECT"
    assert body["decision"] == "REDACTED"
    assert harness.ollama.prompts == []
    assert harness.receiver_transport.requests == []


def test_receiver_unavailable_is_reported_without_retry(harness_factory):
    h = harness_factory(receiver_down=True)
    body = h.process().json()
    assert body["outbound"]["status"] == "UNAVAILABLE"
    assert body["outbound"]["reached_receiver"] is False
    assert body["status"] == "COMPLETED_WITH_WARNINGS"


def test_client_refuses_payload_modified_after_validation(harness):
    harness.process()
    validated_payload = json.loads(harness.receiver_transport.handoff_requests()[0].content)
    from app.integrations.contracts import CloudHandoffPayload

    original = CloudHandoffPayload.model_validate(validated_payload)
    tampered = original.model_copy(update={"sanitized_transcript": "My name is John Smith"})
    forged = ValidatedPayload(payload=tampered, fingerprint="0" * 64, request_id=original.request_id, checks=())
    with pytest.raises(CloudLinkRefused):
        asyncio.run(harness.container.cloudlink.send(forged))


def _post_to_receiver(app, decision: str, key: str | None = "test-cloudlink-key"):
    import httpx

    async def post():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
            return await client.post(
                "/v1/handoff",
                headers={"X-CloudLink-Key": key} if key else {},
                json={
                    "schema_version": "1.0", "request_id": "abcdef12-3456", "decision": decision,
                    "destination": "CLOUD", "profile": "standard", "channel": "voice", "policy_version": "ps-1",
                    "entity_categories": [], "sanitized_summary": None, "sanitized_transcript": "x",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            )

    return asyncio.run(post())


def test_receiver_rejects_blocked_and_local_only_payloads(harness):
    for decision in ("BLOCKED", "LOCAL_ONLY"):
        response = _post_to_receiver(harness.receiver_app, decision)
        assert response.status_code == 409
        assert response.json()["status"] == "REJECTED"
    assert harness.receiver_app.state.counters["accepted"] == 0


def test_receiver_requires_integration_key(harness):
    assert _post_to_receiver(harness.receiver_app, "REDACTED", key=None).status_code == 401
    assert _post_to_receiver(harness.receiver_app, "REDACTED", key="wrong").status_code == 401
    assert _post_to_receiver(harness.receiver_app, "REDACTED").status_code == 200
