"""Milestone A: reversible tokenization, router, kill switch, dial and signed receipts."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

from app.config import BACKEND_ROOT
from app.detection.entities import DetectedEntity
from app.policy.engine import PolicyEngine
from app.policy.models import Action
from app.schemas.requests import ProcessingMode
from app.services.router import decide_route
from tests.conftest import DEMO_TRANSCRIPT

VERIFIER = BACKEND_ROOT / "scripts" / "verify_chain.py"
HEALTH_CALL = "My name is John Smith and I have diabetes. Can I move my appointment to Monday?"


# ---- Router rules (pure) ----------------------------------------------------------------


def _decision(harness, entities):
    policies = harness.container.policy_repository.list()
    return PolicyEngine(Action.LOCAL_ONLY).evaluate(entities, policies, "standard", "voice")


def test_router_rules_fail_closed(harness):
    person = DetectedEntity("PERSON", 0, 4, 0.85, "John", "t")
    shaky = DetectedEntity("PERSON", 0, 4, 0.45, "John", "t", low_confidence=True)
    cloud_ok = _decision(harness, [person])

    def route(**overrides):
        args = dict(failed=False, decision=cloud_ok, mode=ProcessingMode.FULL, kill_switch=False,
                    dial="balanced", entities=[person], low_confidence_stays_local=True)
        args.update(overrides)
        return decide_route(**args)

    assert route().route == "CLOUD"
    assert route(kill_switch=True).reason == "kill_switch"
    assert route(dial="max_privacy").reason == "dial_max_privacy"
    assert route(entities=[shaky], decision=_decision(harness, [shaky])).reason == "low_confidence_entity"
    assert route(mode=ProcessingMode.LOCAL).route == "LOCAL"
    assert route(mode=ProcessingMode.INSPECT).route == "NONE"
    assert route(failed=True).route == "NONE"


# ---- Round trip (Feature 1) ---------------------------------------------------------------


def test_round_trip_model_sees_tokens_and_agent_sees_real_values(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    body = h.process().json()
    prompt = h.ollama.prompts[0]
    assert "John Smith" not in prompt and "48291" not in prompt
    assert "[PERSON_1]" in prompt
    view = body["agent_view"]
    assert view["status"] == "REHYDRATED" and view["source"] == "LOCAL"
    assert "[PERSON_1]" in view["tokenized_summary"]
    assert "John Smith" in view["summary"] and "48291" in view["summary"]


def test_vault_stores_values_encrypted(harness):
    harness.process()
    assert harness.container.vault.count() == 2
    raw = harness.db_path.read_bytes()
    wal = harness.db_path.with_name(harness.db_path.name + "-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    assert b"John Smith" not in raw and b"48291" not in raw


def test_missing_vault_key_still_protects_but_cannot_rehydrate(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens", vault_key="")
    body = h.process().json()
    assert body["redacted_transcript"].startswith("My name is [PERSON_1]")
    assert body["agent_view"]["status"] == "TOKENS_ONLY" and body["agent_view"]["summary"] is None
    assert any("vault" in w.lower() for w in body["warnings"])


def test_cloud_stand_in_summarizes_tokens_and_firewall_rehydrates(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens", mock_cloud_model="llama3.1:8b")
    body = h.process().json()
    routing = body["routing"]
    assert routing["route"] == "CLOUD" and routing["cloud_model"] == "llama3.1:8b"
    assert routing["cloud_summary_status"] == "GENERATED" and "[PERSON_1]" in routing["cloud_summary"]
    assert body["agent_view"]["source"] == "CLOUD" and "John Smith" in body["agent_view"]["summary"]
    # Both the local and the cloud prompt only ever contained tokens.
    assert len(h.ollama.prompts) == 2
    assert all("John Smith" not in p and "48291" not in p for p in h.ollama.prompts)


def test_received_log_never_contains_original_values_over_20_calls(harness):
    calls = [
        DEMO_TRANSCRIPT,
        "Hi, this is Maria Gonzalez. My new phone number is 416-555-0199 and my email is maria.gonzalez@example.com.",
        "This is Daniel Okafor, date of birth March 2, 1979, patient ID 77120. Please move my appointment.",
        "Hello, main Priya Sharma bol rahi hoon, patient ID P9048213, mera number +91 98450 12345 hai.",
    ] * 5
    originals = ["John Smith", "48291", "Maria Gonzalez", "416-555-0199", "maria.gonzalez@example.com",
                 "Daniel Okafor", "March 2, 1979", "77120", "Priya Sharma", "P9048213", "98450 12345"]
    for text in calls:
        assert harness.process(text).status_code == 200
    log = harness.container.settings.received_log_file.read_text(encoding="utf-8")
    assert log.count("\n") >= 4  # the cloud path was really exercised
    for value in originals:
        assert value.lower() not in log.lower(), value


# ---- Kill switch (Feature 3) and dial (Feature 4) -----------------------------------------


def test_kill_switch_blocks_cloud_but_local_processing_continues(harness):
    on = harness.client.put("/api/controls/kill-switch", json={"enabled": True}).json()
    assert on["kill_switch"] is True and on["cloud_path"] == "BLOCKED"
    body = harness.process().json()
    assert body["routing"]["route"] == "LOCAL" and body["routing"]["reason"] == "kill_switch"
    assert body["outbound"]["status"] == "KILL_SWITCH"
    assert body["summary"]["status"] == "GENERATED"
    assert harness.receiver_transport.handoff_requests() == []

    harness.client.put("/api/controls/kill-switch", json={"enabled": False})
    assert harness.process().json()["outbound"]["status"] == "SENT"


def test_controls_require_admin_key_when_configured(harness_factory):
    h = harness_factory(admin_api_key="secret")
    assert h.client.put("/api/controls/kill-switch", json={"enabled": True}).status_code == 401
    ok = h.client.put("/api/controls/kill-switch", json={"enabled": True}, headers={"X-Admin-Key": "secret"})
    assert ok.status_code == 200 and h.client.get("/api/controls").json()["kill_switch"] is True


def test_dial_positions_change_tokenization_and_routing(harness):
    def run(position):
        harness.client.put("/api/controls/dial", json={"position": position})
        return harness.process(HEALTH_CALL).json()

    quality = run("max_quality")
    assert "diabetes" in quality["redacted_transcript"] and quality["routing"]["route"] == "CLOUD"
    assert "Monday" in quality["redacted_transcript"]

    balanced = run("balanced")
    assert "[HEALTH_TERM_1]" in balanced["redacted_transcript"] and "Monday" in balanced["redacted_transcript"]
    assert balanced["routing"]["route"] == "CLOUD"

    private = run("max_privacy")
    assert "[DATE_TIME_1]" in private["redacted_transcript"] and "[HEALTH_TERM_1]" in private["redacted_transcript"]
    assert private["routing"]["route"] == "LOCAL" and private["routing"]["reason"] == "dial_max_privacy"
    assert len(harness.receiver_transport.handoff_requests()) == 2


def test_low_confidence_detection_keeps_the_request_local(harness):
    body = harness.process("Please note the reference 2345 6789 0123 for my file, thanks.").json()
    assert any(e["low_confidence"] for e in body["entities"])
    assert body["routing"]["route"] in ("LOCAL", "NONE")
    assert harness.receiver_transport.handoff_requests() == []


# ---- Signed, hash-chained receipts (Feature 2) --------------------------------------------


def _offline_verify(h, *extra):
    pubkey = h.container.settings.keys_dir / "receipt_public_key.pem"
    return subprocess.run(
        [sys.executable, str(VERIFIER), "--db", str(h.db_path), "--pubkey", str(pubkey), *extra],
        capture_output=True, text=True, timeout=60, check=False,
    )


def test_every_request_gets_a_signed_chained_receipt_without_values(harness):
    for profile in ("standard", "healthcare", "restricted"):
        harness.process(profile=profile)
    listing = harness.client.get("/api/receipts").json()
    assert listing["total"] == 3 and listing["signing"]["status"] == "CONFIGURED"
    first, second = sorted(listing["items"], key=lambda r: r["seq"])[:2]
    assert first["prev_hash"] == "GENESIS" and second["prev_hash"] == first["hash"]
    blob = json.dumps(listing)
    assert "John Smith" not in blob and "48291" not in blob
    body = second["body"]
    assert body["entity_counts"] == {"PERSON": 1, "PATIENT_ID": 1} and body["protected_values_left"] is False
    assert harness.container.receipts.verify().ok


def test_offline_verifier_passes_then_detects_edits_and_deletions(harness):
    for _ in range(3):
        harness.process()
    ok = _offline_verify(harness)
    assert ok.returncode == 0 and "CHAIN OK (3 receipts)" in ok.stdout

    demo = _offline_verify(harness, "--tamper-demo")
    assert demo.returncode == 1 and "TAMPERED at receipt #2" in demo.stdout
    assert _offline_verify(harness).returncode == 0  # the demo never touches the original

    harness.container.engine.dispose()
    with sqlite3.connect(harness.db_path) as db:
        body = json.loads(db.execute("SELECT body FROM receipts WHERE seq = 2").fetchone()[0])
        body["entity_counts"] = {}
        db.execute("UPDATE receipts SET body = ? WHERE seq = 2", (json.dumps(body, sort_keys=True, separators=(",", ":")),))
    edited = _offline_verify(harness)
    assert edited.returncode == 1 and "TAMPERED at receipt #2" in edited.stdout

    with sqlite3.connect(harness.db_path) as db:
        db.execute("DELETE FROM receipts WHERE seq = 2")
    assert "TAMPERED" in _offline_verify(harness).stdout


def test_verify_endpoint_runs_the_offline_script(harness):
    harness.process()
    result = harness.client.post("/api/receipts/verify").json()
    assert result["verifier"] == "offline-script" and result["ok"] is True
    demo = harness.client.post("/api/receipts/verify?tamper_demo=true").json()
    assert demo["ok"] is False and "TAMPERED" in demo["output"]
