from __future__ import annotations

from datetime import timedelta

from app.db.repositories import utcnow

INCIDENT = {
    "title": "Assistant quoted the wrong refund policy",
    "description": "Customer was told refunds take 90 days.",
    "incident_type": "WRONG_ANSWER",
    "severity": "HIGH",
}


def _systems(h) -> dict[str, dict]:
    return {s["name"]: s for s in h.client.get("/api/compliance/systems").json()["items"]}


def _new_incident(h, **overrides) -> dict:
    response = h.client.post("/api/compliance/incidents", json={**INCIDENT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _advance(h, incident_id: str, **body):
    return h.client.post(f"/api/compliance/incidents/{incident_id}/advance", json=body)


# ---- Inventory ----------------------------------------------------------------------------


def test_inventory_is_seeded_with_one_overdue_system(harness):
    items = harness.client.get("/api/compliance/systems").json()["items"]
    assert len(items) == 5
    assert [s["name"] for s in items if s["review_overdue"]] == ["CRM reply drafting assistant (sample)"]


def test_create_system_validates_categories_and_review_resets_the_clock(harness):
    body = {"name": "Meeting notes bot", "owner": "IT", "purpose": "Summarize meetings.", "hosting": "CLOUD",
            "data_categories": ["person", "EMAIL_ADDRESS"]}
    created = harness.client.post("/api/compliance/systems", json=body)
    assert created.status_code == 201
    assert created.json()["data_categories"] == ["PERSON", "EMAIL_ADDRESS"]
    assert created.json()["status"] == "UNDER_REVIEW"

    bad = harness.client.post("/api/compliance/systems", json={**body, "data_categories": ["NOT_A_CATEGORY"]})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "UNKNOWN_CATEGORY"

    overdue = _systems(harness)["CRM reply drafting assistant (sample)"]
    reviewed = harness.client.post(f"/api/compliance/systems/{overdue['system_id']}/review", json={"status": "APPROVED"})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_overdue"] is False
    assert reviewed.json()["status"] == "APPROVED"

    plain = harness.client.post(f"/api/compliance/systems/{overdue['system_id']}/review")
    assert plain.status_code == 200 and plain.json()["status"] == "APPROVED"
    assert harness.client.post("/api/compliance/systems/sys-00000000/review").status_code == 404


# ---- Incidents ----------------------------------------------------------------------------


def test_incident_follows_the_four_stages_and_gates_each_on_required_text(harness):
    incident = _new_incident(harness)
    iid = incident["incident_id"]
    assert incident["status"] == "REPORTED"
    assert incident["sla_state"] == "ON_TRACK"
    assert incident["timeline"][0]["action"] == "Reported"

    contained = _advance(harness, iid, note="Disabled the assistant").json()
    assert contained["status"] == "CONTAINED"
    assert contained["sla_state"] == "MET"
    assert contained["sla_seconds_remaining"] is None

    missing = _advance(harness, iid)
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "INCIDENT_ROOT_CAUSE_REQUIRED"
    assert _advance(harness, iid, root_cause="Stale knowledge-base article").json()["status"] == "ROOT_CAUSE_IDENTIFIED"

    missing = _advance(harness, iid)
    assert missing.json()["error"]["code"] == "INCIDENT_RESOLUTION_REQUIRED"
    closed = _advance(harness, iid, resolution="Article corrected and assistant re-enabled").json()
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    assert [e["action"] for e in closed["timeline"]] == ["Reported", "Contained", "Root cause identified", "Closed"]

    again = _advance(harness, iid)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INCIDENT_CLOSED"
    assert harness.client.put(f"/api/compliance/incidents/{iid}", json={"owner": "Sam"}).status_code == 409


def test_incident_sla_breach_is_reported_and_fails_the_control(harness):
    iid = _new_incident(harness, severity="CRITICAL")["incident_id"]
    record = harness.container.incidents._repo.get(iid)
    record.created_at = utcnow() - timedelta(hours=5)
    record.sla_due_at = record.created_at + timedelta(hours=4)
    harness.container.incidents._repo.save(record)

    incident = harness.client.get(f"/api/compliance/incidents/{iid}").json()
    assert incident["sla_state"] == "BREACHED"
    assert incident["sla_seconds_remaining"] < 0

    controls = {c["control_id"]: c for c in harness.client.get("/api/compliance/evidence/GDPR").json()["controls"]}
    assert controls["CTL-INCIDENT-SLA"]["status"] == "FAIL"
    assert harness.client.get("/api/compliance/overview").json()["kpis"]["sla_breached"] == 1

    assert _advance(harness, iid).json()["sla_state"] == "MISSED"


def test_incident_owner_severity_filters_and_links(harness):
    event_id = harness.process().json()["event_id"]
    incident = _new_incident(harness, related_event_id=event_id, owner="  Priya  ")
    iid = incident["incident_id"]
    assert incident["owner"] == "Priya" and incident["related_event_id"] == event_id

    updated = harness.client.put(f"/api/compliance/incidents/{iid}", json={"owner": "Marc", "severity": "LOW"}).json()
    assert updated["owner"] == "Marc" and updated["severity"] == "LOW"
    assert {e["action"] for e in updated["timeline"]} >= {"Owner changed", "Severity changed"}
    assert harness.client.put(f"/api/compliance/incidents/{iid}", json={}).json()["error"]["code"] == "NOTHING_TO_UPDATE"

    assert harness.client.get("/api/compliance/incidents?severity=LOW").json()["total"] == 1
    assert harness.client.get("/api/compliance/incidents?severity=HIGH").json()["total"] == 0
    assert harness.client.get("/api/compliance/incidents?status=CLOSED").json()["total"] == 0

    assert harness.client.post("/api/compliance/incidents", json={**INCIDENT, "related_event_id": "evt-0000000000000000"}).status_code == 422
    assert harness.client.post("/api/compliance/incidents", json={**INCIDENT, "ai_system_id": "sys-00000000"}).status_code == 422
    assert harness.client.post("/api/compliance/incidents", json={**INCIDENT, "severity": "SEVERE"}).status_code == 422
    assert harness.client.post("/api/compliance/incidents", json={**INCIDENT, "decision": "x"}).status_code == 422
    assert harness.client.get("/api/compliance/incidents/inc-000000000000").status_code == 404


# ---- Data-subject requests ----------------------------------------------------------------


def test_data_request_completes_when_every_system_is_resolved(harness):
    systems = _systems(harness)
    ids = [systems["Contact-centre sentiment assistant (sample)"]["system_id"], systems["Voicemail transcription service (sample)"]["system_id"]]
    created = harness.client.post(
        "/api/compliance/data-requests",
        json={"request_type": "ERASURE", "subject_reference": "CASE-4412", "system_ids": ids},
    )
    assert created.status_code == 201
    request = created.json()
    rid = request["request_id"]
    assert request["status"] == "OPEN" and request["systems_total"] == 2 and request["systems_done"] == 0
    assert 29 <= request["days_remaining"] <= 30 and request["overdue"] is False

    first = harness.client.put(f"/api/compliance/data-requests/{rid}/systems/{ids[0]}", json={"status": "DONE", "note": "Deleted"})
    assert first.json()["status"] == "OPEN" and first.json()["systems_done"] == 1

    last = harness.client.put(f"/api/compliance/data-requests/{rid}/systems/{ids[1]}", json={"status": "NOT_HELD"}).json()
    assert last["status"] == "COMPLETED" and last["completed_at"] is not None and last["days_remaining"] is None

    locked = harness.client.put(f"/api/compliance/data-requests/{rid}/systems/{ids[0]}", json={"status": "PENDING"})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "DATA_REQUEST_COMPLETED"


def test_data_request_validation_and_overdue(harness):
    systems = _systems(harness)
    ids = [systems["Local summarizer (Ollama)"]["system_id"]]
    base = {"request_type": "ACCESS", "subject_reference": "CASE-1", "system_ids": ids}

    assert harness.client.post("/api/compliance/data-requests", json={**base, "system_ids": []}).status_code == 422
    unknown = harness.client.post("/api/compliance/data-requests", json={**base, "system_ids": ["sys-00000000"]})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_SYSTEM"
    future = (utcnow() + timedelta(days=2)).isoformat()
    assert harness.client.post("/api/compliance/data-requests", json={**base, "received_at": future}).json()["error"]["code"] == "RECEIVED_IN_FUTURE"

    old = (utcnow() - timedelta(days=40)).isoformat()
    late = harness.client.post("/api/compliance/data-requests", json={**base, "received_at": old}).json()
    assert late["overdue"] is True and late["days_remaining"] < 0

    miss = harness.client.put(f"/api/compliance/data-requests/{late['request_id']}/systems/sys-00000000", json={"status": "DONE"})
    assert miss.status_code == 404

    controls = {c["control_id"]: c for c in harness.client.get("/api/compliance/evidence/GDPR").json()["controls"]}
    assert controls["CTL-REQUESTS-TIMELY"]["status"] == "FAIL"


# ---- Scores and evidence ------------------------------------------------------------------


def test_overview_scores_every_framework_from_live_state(harness):
    body = harness.client.get("/api/compliance/overview").json()
    assert [f["framework"] for f in body["frameworks"]] == ["GDPR", "HIPAA", "ISO_42001", "SOC_2"]
    for f in body["frameworks"]:
        assert 0 <= f["score"] <= 100
        assert f["pass_count"] + f["partial_count"] + f["fail_count"] == f["total"] == len(f["controls"])
    assert body["kpis"]["ai_systems"] == 5 and body["kpis"]["reviews_overdue"] == 1

    controls = {c["control_id"]: c for c in body["frameworks"][0]["controls"]}
    assert controls["CTL-ADMIN-AUTH"]["status"] == "FAIL"  # test settings have no admin key
    assert controls["CTL-ADMIN-AUTH"]["remediation"]
    assert controls["CTL-AUDIT-NO-CONTENT"]["status"] == "PASS"
    assert controls["CTL-AUDIT-NO-CONTENT"]["remediation"] is None
    assert controls["CTL-REVIEWS-CURRENT"]["status"] == "PARTIAL"
    assert controls["CTL-SENSITIVE-PROTECTED"]["status"] == "PASS"


def test_scores_react_to_configuration_changes(harness):
    def gdpr() -> dict:
        return {c["control_id"]: c for c in harness.client.get("/api/compliance/overview").json()["frameworks"][0]["controls"]}

    assert gdpr()["CTL-POLICY-ENFORCED"]["status"] == "PASS"
    for policy in harness.client.get("/api/policies").json()["items"]:
        harness.client.put(f"/api/policies/{policy['policy_id']}", json={**{k: policy[k] for k in (
            "name", "description", "priority", "entity_categories", "action", "destination", "conditions")}, "enabled": False})
    controls = gdpr()
    assert controls["CTL-POLICY-ENFORCED"]["status"] == "FAIL"
    assert controls["CTL-SENSITIVE-PROTECTED"]["status"] == "FAIL"


def test_admin_key_flips_the_authentication_control(harness_factory):
    h = harness_factory(admin_api_key="secret")
    controls = {c["control_id"]: c for c in h.client.get("/api/compliance/overview").json()["frameworks"][0]["controls"]}
    assert controls["CTL-ADMIN-AUTH"]["status"] == "PASS"


def test_mutations_require_the_admin_key_when_configured(harness_factory):
    h = harness_factory(admin_api_key="secret")
    assert h.client.post("/api/compliance/incidents", json=INCIDENT).status_code == 401
    ok = h.client.post("/api/compliance/incidents", json=INCIDENT, headers={"X-Admin-Key": "secret"})
    assert ok.status_code == 201
    assert h.client.get("/api/compliance/incidents").status_code == 200  # reads stay open


def test_evidence_pack_json_and_markdown(harness):
    harness.process()
    pack = harness.client.get("/api/compliance/evidence/HIPAA").json()
    assert pack["framework"] == "HIPAA" and pack["framework_name"] == "HIPAA Security Rule"
    assert pack["audit"]["event_count"] == 1
    assert pack["audit"]["stores_raw_transcripts"] is False
    assert len(pack["ai_systems"]) == 5
    assert pack["policies"]["enabled"] == pack["policies"]["total"] == 9
    assert "not legal advice" in pack["disclaimer"]

    md = harness.client.get("/api/compliance/evidence/HIPAA/markdown")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# HIPAA Security Rule evidence pack")
    assert "## Gaps and remediation" in md.text and "Local summarizer (Ollama)" in md.text

    assert harness.client.get("/api/compliance/evidence/PCI").status_code == 404
    assert harness.client.get("/api/compliance/evidence/PCI/markdown").status_code == 404


def test_compliance_records_never_contain_transcript_content(harness):
    harness.process()
    _new_incident(harness)
    texts = [
        harness.client.get("/api/compliance/overview").text,
        harness.client.get("/api/compliance/evidence/GDPR").text,
        harness.client.get("/api/compliance/evidence/GDPR/markdown").text,
    ]
    for text in texts:
        assert "John Smith" not in text and "48291" not in text
