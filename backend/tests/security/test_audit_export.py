"""Audit evidence export (use case step 11: export the audit records for a HIPAA audit)."""

from __future__ import annotations

import csv
import io
import json

RAW_VALUES = ("John Smith", "48291")


def test_json_export_bundles_events_receipts_and_chain(harness):
    for _ in range(2):
        harness.process()
    response = harness.client.get("/api/audit/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    bundle = response.json()
    assert bundle["event_count"] == 2 and len(bundle["events"]) == 2
    assert bundle["receipt_count"] == 2
    assert bundle["receipt_chain"]["ok"] is True
    assert bundle["receipt_public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    assert {r["request_id"] for r in bundle["receipts"]} == {e["request_id"] for e in bundle["events"]}
    text = response.text
    assert not any(value in text for value in RAW_VALUES)


def test_csv_export_has_one_row_per_event_and_no_values(harness):
    harness.process()
    response = harness.client.get("/api/audit/export?format=csv")
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["decision"] == "REDACTED"
    assert json.loads(rows[0]["entity_counts"]) == {"PATIENT_ID": 1, "PERSON": 1}
    assert not any(value in response.text for value in RAW_VALUES)


def test_export_respects_the_date_range_and_single_events_still_resolve(harness):
    event_id = harness.process().json()["event_id"]
    assert harness.client.get("/api/audit/export?date_to=2000-01-01T00:00:00Z").json()["event_count"] == 0
    assert harness.client.get(f"/api/audit/{event_id}").status_code == 200
