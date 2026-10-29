from __future__ import annotations

import pytest

from tests.conftest import DEMO_TRANSCRIPT

NEW_POLICY = {
    "name": "Block locations for billing",
    "description": "Test policy.",
    "enabled": True,
    "priority": 40,
    "entity_categories": ["PERSON"],
    "action": "BLOCK",
    "destination": "NONE",
    "conditions": {"profiles": ["standard"], "channels": [], "min_confidence": 0.0},
}


def test_normal_transcript_is_accepted_and_allowed(harness):
    body = harness.process("Hi, what are your support hours?").json()
    assert body["decision"] == "ALLOWED"
    assert body["entities"] == []
    assert body["outbound"]["status"] == "SENT"
    assert [s["key"] for s in body["steps"]] == ["received", "analyzed", "policy", "protected", "ai", "audited"]
    assert body["latency"]["total_ms"] > 0


def test_demo_result_shape(harness):
    body = harness.process().json()
    assert body["redacted_transcript"] == (
        "My name is [PERSON_1], my patient ID is [PATIENT_ID_1], and I need help with my appointment."
    )
    assert [t["token"] for t in body["tokens"]] == ["[PERSON_1]", "[PATIENT_ID_1]"]
    assert body["routing"]["route"] == "CLOUD" and body["receipt"]["signed"] is True
    assert {e["entity_type"]: e["value"] for e in body["entities"]} == {"PERSON": "John Smith", "PATIENT_ID": "48291"}
    assert body["decisive_policy_id"] == "redact-patient-id"
    assert body["event_id"].startswith("evt-")


def test_invalid_requests_are_rejected(harness):
    cases = [
        {},
        {"transcript": ""},
        {"transcript": "   "},
        {"transcript": 123},
        {"transcript": "hi", "channel": "fax"},
        {"transcript": "hi", "mode": "cloud-only"},
        {"transcript": "hi", "profile": "../etc"},
    ]
    for payload in cases:
        response = harness.client.post("/api/process", json=payload)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.headers["X-Request-ID"]


def test_unknown_profile_is_rejected(harness):
    response = harness.process(profile="does-not-exist")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_PROFILE"


def test_oversized_transcript_is_rejected(harness_factory):
    h = harness_factory(max_transcript_chars=200)
    response = h.process("a" * 201)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "TRANSCRIPT_TOO_LARGE"


def test_oversized_body_is_rejected(harness_factory):
    h = harness_factory(max_request_bytes=2048)
    response = h.process("a" * 5000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert h.receiver_transport.requests == []


def test_policy_crud_and_validation(harness):
    client = harness.client
    listing = client.get("/api/policies").json()
    assert listing["total"] == 10

    created = client.post("/api/policies", json=NEW_POLICY)
    assert created.status_code == 201, created.text
    policy_id = created.json()["policy_id"]
    assert policy_id == "block-locations-for-billing"
    assert client.post("/api/policies", json={**NEW_POLICY, "policy_id": policy_id}).status_code == 409

    updated = client.put(f"/api/policies/{policy_id}", json={**NEW_POLICY, "enabled": False})
    assert updated.status_code == 200 and updated.json()["version"] == 2 and not updated.json()["enabled"]

    assert client.delete(f"/api/policies/{policy_id}").status_code == 204
    assert client.get(f"/api/policies/{policy_id}").status_code == 404
    assert client.delete(f"/api/policies/{policy_id}").status_code == 404


def test_invalid_policies_are_rejected_by_api(harness):
    client = harness.client
    bad_destination = client.post("/api/policies", json={**NEW_POLICY, "destination": "CLOUD"})
    assert bad_destination.status_code == 422
    unknown = client.post("/api/policies", json={**NEW_POLICY, "entity_categories": ["SHOE_SIZE"]})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "POLICY_INVALID"
    check = client.post("/api/policies/validate", json={**NEW_POLICY, "entity_categories": ["SHOE_SIZE"]}).json()
    assert check["valid"] is False and check["errors"]
    ok = client.post("/api/policies/validate", json=NEW_POLICY).json()
    assert ok["valid"] is True
    assert client.get("/api/policies").json()["total"] == 10  # nothing was saved


def test_policy_change_affects_backend_behaviour(harness):
    assert harness.process().json()["decision"] == "REDACTED"
    assert harness.client.post("/api/policies", json=NEW_POLICY).status_code == 201
    body = harness.process().json()
    assert body["decision"] == "BLOCKED"
    assert harness.receiver_transport.handoff_requests().__len__() == 1  # only the first request


def test_disabling_the_baseline_rule_denies_cloud(harness):
    baseline = harness.client.get("/api/policies/baseline-sanitized-cloud").json()
    payload = {k: baseline[k] for k in ("name", "description", "priority", "entity_categories", "action", "destination", "conditions")}
    harness.client.put("/api/policies/baseline-sanitized-cloud", json={**payload, "enabled": False})
    body = harness.process("Hi, what are your support hours?").json()
    assert body["decision"] == "BLOCKED"
    assert harness.receiver_transport.requests == []


def test_policy_changes_persist_across_restarts(harness_factory):
    first = harness_factory()
    assert first.client.post("/api/policies", json=NEW_POLICY).status_code == 201
    first.process()
    first.client.__exit__(None, None, None)

    second = harness_factory()  # same tmp database file
    ids = [p["policy_id"] for p in second.client.get("/api/policies").json()["items"]]
    assert "block-locations-for-billing" in ids
    assert second.client.get("/api/audit").json()["total"] == 1
    assert second.process().json()["decision"] == "BLOCKED"


def test_reset_to_defaults(harness):
    harness.client.post("/api/policies", json=NEW_POLICY)
    reset = harness.client.post("/api/policies/reset").json()
    assert reset["total"] == 10


def test_written_channels_keep_contact_details_local(harness):
    voice = harness.process(channel="voice").json()
    email = harness.process(channel="email").json()
    assert voice["decision"] == "REDACTED" and voice["authorized_destination"] == "CLOUD"
    assert email["decision"] == "LOCAL_ONLY" and email["authorized_destination"] == "LOCAL"
    assert "written-channels-contact-local" in {p["policy_id"] for p in email["matched_policies"]}
    assert len(harness.receiver_transport.handoff_requests()) == 1  # only the voice request left the firewall


def test_admin_key_protects_policy_mutations(harness_factory):
    h = harness_factory(admin_api_key="admin-secret")
    assert h.client.post("/api/policies", json=NEW_POLICY).status_code == 401
    assert h.client.delete("/api/policies/redact-patient-id").status_code == 401
    assert h.client.get("/api/policies").status_code == 200
    ok = h.client.post("/api/policies", json=NEW_POLICY, headers={"X-Admin-Key": "admin-secret"})
    assert ok.status_code == 201


def test_audit_filters_and_pagination(harness):
    for profile in ("standard", "healthcare", "restricted"):
        harness.process(profile=profile)
    client = harness.client
    assert client.get("/api/audit").json()["total"] == 3
    assert client.get("/api/audit?decision=BLOCKED").json()["total"] == 1
    assert client.get("/api/audit?destination=LOCAL").json()["total"] == 1
    assert client.get("/api/audit?policy_id=healthcare-phi-local-only").json()["total"] == 1
    page = client.get("/api/audit?page=2&page_size=2").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get("/api/audit?decision=NOPE").status_code == 422
    assert client.get("/api/audit?date_from=2999-01-01T00:00:00Z").json()["total"] == 0
    assert client.get("/api/audit/evt-0000000000000000").status_code == 404


def test_metrics_summary_reflects_processing(harness):
    for profile in ("standard", "healthcare", "restricted"):
        harness.process(profile=profile)
    metrics = harness.client.get("/api/metrics/summary").json()
    assert metrics["total_requests"] == 3
    assert metrics["decision_counts"]["REDACTED"] == 1
    assert metrics["decision_counts"]["LOCAL_ONLY"] == 1
    assert metrics["decision_counts"]["BLOCKED"] == 1
    assert metrics["entity_category_counts"] == {"PERSON": 3, "PATIENT_ID": 3}
    assert metrics["cloud_handoffs_sent"] == 1
    assert metrics["latency"]["total"]["count"] == 3
    assert sum(b["redacted"] for b in metrics["timeline"]) == 1


def test_health_and_integrations_without_credentials(harness):
    health = harness.client.get("/api/health").json()
    assert health["components"]["detection"]["status"] == "READY"
    assert health["components"]["policies"]["status"] == "READY"
    status = harness.client.get("/api/integrations/status").json()
    assert status["ollama"]["status"] == "CONNECTED"
    assert status["cloudlink"]["status"] == "CONNECTED" and status["cloudlink"]["simulated"] is True


def test_missing_model_is_reported_across_the_api(harness_factory):
    h = harness_factory(ollama_mode="missing")
    assert h.client.get("/api/integrations/status").json()["ollama"]["status"] == "MODEL_MISSING"
    body = h.process(profile="healthcare").json()
    assert body["summary"]["status"] == "MODEL_MISSING"
    assert body["summary"]["text"] is None
    assert body["status"] == "COMPLETED_WITH_WARNINGS"
    assert h.receiver_transport.handoff_requests() == []  # no cloud fallback


def test_timeout_is_reported_and_cloud_egress_fails_closed(harness_factory):
    h = harness_factory(ollama_mode="timeout")
    body = h.process(profile="standard").json()
    assert body["summary"]["status"] == "TIMEOUT"
    # NFR-5: with the local model unavailable, nothing goes to the cloud either, but the
    # request stays usable: detection and redaction results are still returned.
    assert body["outbound"]["status"] == "HELD_LOCAL"
    assert body["routing"]["reason"] == "local_model_unavailable"
    assert h.receiver_transport.handoff_requests() == []
    assert "[PERSON_1]" in body["redacted_transcript"]


@pytest.mark.parametrize("mode", ["down", "missing", "empty"])
def test_unavailable_local_model_never_falls_back_to_cloud(harness_factory, mode):
    h = harness_factory(ollama_mode=mode)
    body = h.process(profile="standard").json()
    assert body["summary"]["status"] != "GENERATED"
    assert h.receiver_transport.handoff_requests() == []
    assert body["routing"]["route"] == "LOCAL" and body["decision"] == "REDACTED"


def test_config_never_exposes_secrets(harness):
    config = harness.client.get("/api/config")
    assert config.status_code == 200
    assert "test-cloudlink-key" not in config.text
    assert config.json()["cloudlink"]["api_key"]["configured"] is True
    assert config.json()["cloudlink"]["simulated"] is True


def test_samples_and_profiles(harness):
    samples = harness.client.get("/api/samples").json()
    assert samples[0]["transcript"] == DEMO_TRANSCRIPT
    profiles = {p["id"] for p in harness.client.get("/api/policies/profiles").json()["items"]}
    assert {"standard", "healthcare", "restricted"} <= profiles


def test_cors_only_allows_configured_origin(harness):
    allowed = harness.client.options(
        "/api/health", headers={"Origin": "http://localhost:4200", "Access-Control-Request-Method": "GET"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:4200"
    denied = harness.client.options(
        "/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in denied.headers
