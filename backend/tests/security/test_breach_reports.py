"""Breach Report Generator (Feature 8, FR-11): drafts only, built from records, no raw values."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.compliance.breach_reports import WATERMARK
from app.db.models import CanaryRunRecord
from tests.security.test_canaries import FIXTURE, UNDETECTABLE

# Every planted value in the fixture set. None may appear outside the synthetic appendix.
PLANTED = [c.text[s:e] for c in FIXTURE.calls for p in c.planted for s, e in p.spans]
ALLOWED_TEXT = "My name is John Smith and I have diabetes, can I come on Thursday?"


@pytest.fixture
def reports(harness_factory):
    def factory(**overrides):
        h = harness_factory(**overrides)
        h.container.canaries._loader = lambda: FIXTURE
        return h

    return factory


def draft(h, **body):
    return h.client.post("/api/breach-reports", json=body)


def canary_report(h) -> dict:
    run_id = h.container.canaries.run(normalize_on=True)
    response = draft(h, source="canary_run", ref=run_id)
    assert response.status_code == 201, response.text
    return response.json()


def without_appendix(report: dict, markdown: str) -> tuple[str, str]:
    content = {k: v for k, v in report["content"].items() if k != "synthetic_appendix"}
    return json.dumps(content, ensure_ascii=False), markdown.split("## Appendix: synthetic test data")[0]


def test_canary_report_counts_match_the_records(reports):
    h = reports()
    report = canary_report(h)
    c = report["content"]
    run = h.client.get(f"/api/canaries/runs/{report['source_ref']}").json()
    assert c["affected_requests"] == len(run["leaks"]) == 1
    assert c["categories"] == {"PATIENT_ID": 1}
    assert c["reasons"] == {"LEAK_MEASURED_AT_RECEIVER": 1}
    assert len(c["receipt_ids"]) == 1 and c["routes"] == {"CLOUD": 1}
    assert c["chain"]["ok"] is True
    assert report["status"] == "DRAFT" and c["watermark"] == WATERMARK
    assert c["synthetic_appendix"] == [
        {"call_id": "can-0003", "type": "PATIENT_ID", "field": "sanitized_transcript", "surface": UNDETECTABLE}
    ]


def test_no_raw_values_outside_the_synthetic_appendix(reports):
    h = reports()
    report = canary_report(h)
    markdown = h.client.get(f"/api/breach-reports/{report['report_id']}/markdown").text
    body, main = without_appendix(report, markdown)
    for value in PLANTED:
        assert value not in body and value not in main, value
    assert UNDETECTABLE in markdown.split("## Appendix: synthetic test data")[1]  # labelled appendix only


def test_markdown_carries_the_draft_watermark_at_top_and_bottom(reports):
    h = reports()
    report = canary_report(h)
    lines = h.client.get(f"/api/breach-reports/{report['report_id']}/markdown").text.strip().splitlines()
    assert WATERMARK in lines[0] and WATERMARK in lines[-1]
    assert any("Regulators to consider" in line for line in lines)


def test_drafting_sends_nothing(reports):
    h = reports()
    run_id = h.container.canaries.run(normalize_on=True)
    before = len(h.receiver_transport.requests)
    draft(h, source="canary_run", ref=run_id)
    assert len(h.receiver_transport.requests) == before


def test_verify_is_ok_then_detects_a_changed_record(reports):
    h = reports()
    report = canary_report(h)
    path = f"/api/breach-reports/{report['report_id']}/verify"
    ok = h.client.get(path).json()
    assert ok["ok"] is True and ok["mismatches"] == []

    with h.container.benchmarks._sessions.begin() as s:  # someone edits the stored run afterwards
        s.get(CanaryRunRecord, report["source_ref"]).leaks = []
    changed = h.client.get(path).json()
    assert changed["ok"] is False
    assert {m["field"] for m in changed["mismatches"]} >= {"affected_requests", "categories"}


def test_a_canary_run_without_leaks_has_nothing_to_report(reports):
    h = reports()
    h.container.controls.set_kill_switch(True)
    run_id = h.container.canaries.run(normalize_on=True)
    response = draft(h, source="canary_run", ref=run_id)
    assert response.status_code == 422 and response.json()["error"]["code"] == "NO_LEAKS"
    assert draft(h, source="canary_run", ref="canary-unknown-run").status_code == 404


def test_window_report_counts_allowed_categories_sent(reports):
    h = reports()
    h.container.controls.set_dial("max_quality")  # health terms and dates may then reach the cloud
    body = h.process(ALLOWED_TEXT).json()
    assert body["outbound"]["reached_receiver"]
    now = datetime.now(timezone.utc)
    report = draft(h, source="window", **{"from": (now - timedelta(hours=1)).isoformat(),
                                         "to": (now + timedelta(hours=1)).isoformat()}).json()
    c = report["content"]
    assert c["affected_requests"] == 1 and c["reasons"] == {"ALLOWED_CATEGORY_SENT": 1}
    assert "HEALTH_TERM" in c["categories"] and c["dials"] == {"max_quality": 1}
    assert "John Smith" not in json.dumps(report) and "diabetes" not in json.dumps(report)


def test_incident_report_and_incident_from_report(reports):
    h = reports()
    h.container.controls.set_dial("max_quality")
    event_id = h.process(ALLOWED_TEXT).json()["event_id"]
    incident = h.client.post("/api/compliance/incidents", json={
        "title": "Health term reached the cloud stand-in", "incident_type": "DATA_EXPOSURE",
        "severity": "MEDIUM", "related_event_id": event_id,
    }).json()
    report = draft(h, source="incident", ref=incident["incident_id"]).json()
    assert report["incident_id"] == incident["incident_id"]
    assert report["content"]["affected_requests"] == 1
    assert report["content"]["incident"]["status"] == "REPORTED"

    canary = canary_report(h)
    linked = h.client.post(f"/api/breach-reports/{canary['report_id']}/incident").json()
    created = h.client.get(f"/api/compliance/incidents/{linked['incident_id']}").json()
    assert created["incident_type"] == "DATA_EXPOSURE" and canary["report_id"] in created["description"]
    assert h.client.post(f"/api/breach-reports/{canary['report_id']}/incident").status_code == 409


def test_review_records_the_reviewer_and_files_nothing(reports):
    h = reports()
    report = canary_report(h)
    before = len(h.receiver_transport.requests)
    reviewed = h.client.post(f"/api/breach-reports/{report['report_id']}/review",
                             json={"reviewer": "A. Officer", "note": "Synthetic test leak; no notification."}).json()
    assert reviewed["status"] == "REVIEWED" and reviewed["reviewer"] == "A. Officer" and reviewed["reviewed_at"]
    markdown = h.client.get(f"/api/breach-reports/{report['report_id']}/markdown").text
    assert "Reviewed by A. Officer" in markdown and WATERMARK in markdown
    assert len(h.receiver_transport.requests) == before
    assert [r["report_id"] for r in h.client.get("/api/breach-reports").json()] == [report["report_id"]]


def test_admin_key_and_input_validation(reports):
    h = reports(admin_api_key="admin-secret")
    assert draft(h, source="window").status_code == 401
    headers = {"X-Admin-Key": "admin-secret"}
    assert h.client.post("/api/breach-reports", json={"source": "window"}, headers=headers).status_code == 422
    assert h.client.post("/api/breach-reports", json={"source": "incident"}, headers=headers).status_code == 422
    assert h.client.get("/api/breach-reports/brr-000000000000").status_code == 404
