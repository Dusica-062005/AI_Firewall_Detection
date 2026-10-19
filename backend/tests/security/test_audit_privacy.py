"""Raw transcripts and entity values must never be persisted or logged."""

from __future__ import annotations

import logging
import sqlite3

SENSITIVE = ["John Smith", "48291", "maria.gonzalez@example.com", "416-555-0199", "Maria Gonzalez"]
TRANSCRIPTS = [
    ("My name is John Smith, my patient ID is 48291, and I need help with my appointment.", "standard"),
    ("My name is John Smith, my patient ID is 48291, and I need help with my appointment.", "healthcare"),
    ("My name is John Smith, my patient ID is 48291, and I need help with my appointment.", "restricted"),
    ("Hi, this is Maria Gonzalez. My phone is 416-555-0199 and email maria.gonzalez@example.com.", "standard"),
]


def dump_database(path) -> str:
    connection = sqlite3.connect(path)
    try:
        return "\n".join(str(row) for line in connection.iterdump() for row in [line])
    finally:
        connection.close()


def test_raw_values_are_not_written_to_audit_records(harness):
    for transcript, profile in TRANSCRIPTS:
        assert harness.process(transcript=transcript, profile=profile).status_code == 200
    harness.client.post("/api/inspect", json={"transcript": TRANSCRIPTS[0][0], "profile": "standard"})

    dump = dump_database(harness.db_path)
    for value in SENSITIVE:
        assert value not in dump
    assert "appointment" not in dump  # no transcript fragments at all

    listing = harness.client.get("/api/audit?page_size=50").text
    for value in SENSITIVE:
        assert value not in listing


def test_audit_record_contains_categories_and_measured_latency(harness):
    body = harness.process().json()
    event = harness.client.get(f"/api/audit/{body['event_id']}").json()
    assert event["request_id"] == body["request_id"]
    assert event["entity_counts"] == {"PERSON": 1, "PATIENT_ID": 1}
    assert event["decision"] == "REDACTED"
    assert event["destination"] == "CLOUD"
    assert event["cloud_status"] == "SENT"
    assert event["total_latency_ms"] > 0
    assert event["latency_ms"]["detection_ms"] > 0
    assert event["cloud_receipt_id"].startswith("clk-")


def test_logs_do_not_contain_transcripts_or_values(harness, caplog):
    caplog.set_level(logging.DEBUG)
    for transcript, profile in TRANSCRIPTS:
        harness.process(transcript=transcript, profile=profile)
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for value in SENSITIVE:
        assert value not in logged


def test_validation_errors_do_not_echo_input(harness):
    response = harness.client.post("/api/process", json={"transcript": "John Smith 48291", "profile": "INVALID PROFILE"})
    assert response.status_code == 422
    assert "John Smith" not in response.text
    assert "48291" not in response.text


def test_detected_values_can_be_hidden_from_api(harness_factory):
    h = harness_factory(expose_detected_values=False)
    body = h.process().json()
    assert body["entities"] and all(e["value"] is None for e in body["entities"])
