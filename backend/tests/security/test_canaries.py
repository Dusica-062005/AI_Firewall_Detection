"""Leak-canary runner (Feature 5, FR-8) against the real pipeline and the in-process receiver.

Uses a small hand-checked fixture set instead of the 200-call file. Every value is synthetic.
"""

from __future__ import annotations

import json

import pytest

from app.canaries.models import CanaryCall, CanarySet, PlantedValue
from app.canaries.runner import RunInProgress

UNDETECTABLE = "hx-ooqz-vant"  # an invented card code with no cue: no recognizer can know it


def make_call(call_id, text, planted, difficulty="plain", language="en", script="latin") -> CanaryCall:
    values = []
    for entity_type, canonical, surfaces in planted:
        spans, cursor = [], 0
        for surface in surfaces:
            start = text.index(surface, cursor)
            spans.append((start, start + len(surface)))
            cursor = start + len(surface)
        values.append(PlantedValue(type=entity_type, canonical=canonical, spans=spans))
    return CanaryCall(call_id=call_id, language=language, script=script, difficulty=difficulty,
                      profile="standard", text=text, planted=values)


FIXTURE = CanarySet(
    version="canaries-fixture",
    generated_with_seed=0,
    calls=[
        make_call("can-0001", "My patient ID is P9482913 and I need a refill.",
                  [("PATIENT_ID", "P9482913", ["P9482913"])]),
        make_call("can-0002", "Hi, this is Arjun Mehta calling about my appointment.",
                  [("PERSON", "Arjun Mehta", ["Arjun Mehta"])]),
        make_call("can-0003", f"My hospital card says {UNDETECTABLE}, can you check it?",
                  [("PATIENT_ID", UNDETECTABLE, [UNDETECTABLE])]),
        make_call("can-0004", "My patient ID is P nine four eight two nine one three, thanks.",
                  [("PATIENT_ID", "P9482913", ["P nine four eight two nine one three"])], difficulty="spelled_digits"),
        make_call("can-0005", "My Aadhaar number is 9999 1234 5678 for the form.",
                  [("GOVERNMENT_ID", "999912345678", ["9999 1234 5678"])]),
        make_call("can-0006", "Send the report to kavya.iyer42@example.org please.",
                  [("EMAIL_ADDRESS", "kavya.iyer42@example.org", ["kavya.iyer42@example.org"])]),
        make_call("can-0007", "Mera mobile number +91 98450 12345 hai, please call karo.",
                  [("PHONE_NUMBER", "9845012345", ["+91 98450 12345"])], difficulty="hinglish", language="hinglish"),
        make_call("can-0008", "My patient ID is P948. Sorry, then 2913, okay?",
                  [("PATIENT_ID", "P9482913", ["P948", "2913"])], difficulty="split_id"),
    ],
)


@pytest.fixture
def canary_harness(harness_factory):
    def factory(**overrides):
        h = harness_factory(**overrides)
        h.container.canaries._loader = lambda: FIXTURE
        return h

    return factory


def run_and_get(h, **body):
    run_id = h.container.canaries.run(**body)
    return h.client.get(f"/api/canaries/runs/{run_id}").json()


def by_key(buckets, key):
    return next(b for b in buckets if b["key"] == key)


def test_recall_and_leak_rate_are_computed_exactly(canary_harness):
    h = canary_harness()
    run = run_and_get(h, normalize_on=True)
    assert run["status"] == "COMPLETED", run["error"]
    overall = run["metrics"]["overall"]
    # Hand-checked: only the invented card code is missed, and it reaches the receiver.
    assert (overall["n_calls"], overall["n_planted"], overall["detected"], overall["leaked"]) == (8, 8, 7, 1)
    assert overall["recall"] == 0.875
    assert overall["leak_rate"] == 0.125
    assert run["recall"] == 0.875 and run["leak_rate"] == 0.125 and run["n_planted"] == 8
    assert [m["call_id"] for m in run["misses"]] == ["can-0003"]
    assert by_key(run["metrics"]["by_type"], "PATIENT_ID")["recall"] == 0.75
    assert by_key(run["metrics"]["by_type"], "EMAIL_ADDRESS")["leak_rate"] == 0.0
    # The Aadhaar call is blocked by policy, so it is never sent.
    assert run["metrics"]["route_counts"]["NONE"] == 1
    assert run["metrics"]["payloads_sent"] == run["metrics"]["received_lines"] == 7
    assert run["normalize_on"] is True and run["dial"] == "max_quality"
    assert run["rule_version"].startswith("rules-") and run["machine"]


def test_spelled_digit_id_is_missed_without_normalization_and_caught_with_it(canary_harness):
    h = canary_harness()
    off = run_and_get(h, normalize_on=False)
    on = run_and_get(h, normalize_on=True)
    assert by_key(off["metrics"]["by_difficulty"], "spelled_digits")["recall"] == 0.0
    assert by_key(off["metrics"]["by_difficulty"], "spelled_digits")["leak_rate"] == 1.0
    assert by_key(on["metrics"]["by_difficulty"], "spelled_digits")["recall"] == 1.0
    assert by_key(on["metrics"]["by_difficulty"], "spelled_digits")["leak_rate"] == 0.0
    assert by_key(off["metrics"]["by_difficulty"], "split_id")["recall"] == 0.0
    assert by_key(on["metrics"]["by_difficulty"], "split_id")["recall"] == 1.0


def test_undetectable_value_is_measured_at_the_real_receiver(canary_harness):
    h = canary_harness()
    run = run_and_get(h, normalize_on=True)
    assert run["leaks"] == [{
        "call_id": "can-0003", "type": "PATIENT_ID", "difficulty": "plain", "language": "en", "script": "latin",
        "surface": UNDETECTABLE, "field": "sanitized_transcript",
    }]
    lines = [json.loads(line) for line in h.container.settings.received_log_file.read_text("utf-8").splitlines()]
    leaked = [line for line in lines if line["request_id"] == f"{run['run_id']}-can-0003"]
    assert len(leaked) == 1 and UNDETECTABLE in leaked[0]["sanitized_transcript"]


def test_receiver_log_mismatch_fails_the_run_instead_of_reporting_zero(canary_harness, tmp_path):
    h = canary_harness()
    h.container.canaries._received_log_file = tmp_path / "elsewhere.log"  # not where the receiver writes
    run = run_and_get(h, normalize_on=True)
    assert run["status"] == "FAILED"
    assert "RECEIVED_LOG_FILE" in run["error"]
    assert run["leak_rate"] is None and run["metrics"] is None


def test_kill_switch_means_nothing_sent_and_zero_leaks(canary_harness):
    h = canary_harness()
    h.container.controls.set_kill_switch(True)
    run = run_and_get(h, normalize_on=False)
    assert run["status"] == "COMPLETED"
    assert run["kill_switch_on"] is True
    assert run["metrics"]["payloads_sent"] == 0 and run["metrics"]["received_lines"] == 0
    assert run["leak_rate"] == 0.0 and run["leaks"] == []
    assert h.receiver_transport.handoff_requests() == []


def test_same_set_and_settings_give_identical_metrics(canary_harness):
    h = canary_harness()
    first = run_and_get(h, normalize_on=True)
    second = run_and_get(h, normalize_on=True)
    assert first["metrics"] == second["metrics"]
    assert first["misses"] == second["misses"] and first["leaks"] == second["leaks"]


def test_compare_returns_correct_deltas(canary_harness):
    h = canary_harness()
    off = h.container.canaries.run(normalize_on=False)
    on = h.container.canaries.run(normalize_on=True)
    body = h.client.get(f"/api/canaries/compare?a={off}&b={on}").json()
    overall = next(r for r in body["rows"] if r["group"] == "overall")
    assert overall["a"]["recall"] == 0.625 and overall["b"]["recall"] == 0.875
    assert overall["recall_delta"] == 0.25
    assert overall["leak_rate_delta"] == -0.25
    spelled = next(r for r in body["rows"] if r["group"] == "difficulty" and r["key"] == "spelled_digits")
    assert spelled["recall_delta"] == 1.0


def test_post_starts_a_background_run_and_reports_progress(canary_harness):
    h = canary_harness()
    response = h.client.post("/api/canaries/runs", json={"normalize_on": True})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    h.container.canaries.wait(timeout=120)
    run = h.client.get(f"/api/canaries/runs/{run_id}").json()
    assert run["status"] == "COMPLETED"
    assert run["progress_done"] == run["progress_total"] == 8
    listed = h.client.get("/api/canaries/runs").json()
    assert [r["run_id"] for r in listed] == [run_id]


def test_only_one_run_at_a_time(canary_harness):
    h = canary_harness()

    class Alive:  # stands in for a run thread that is still working
        def is_alive(self):
            return True

    h.container.canaries._thread = Alive()
    with pytest.raises(RunInProgress):
        h.container.canaries.start()
    assert h.client.post("/api/canaries/runs", json={}).status_code == 409
    h.container.canaries._thread = None


def test_post_requires_the_admin_key_when_configured(canary_harness):
    h = canary_harness(admin_api_key="admin-secret")
    assert h.client.post("/api/canaries/runs", json={}).status_code == 401
    response = h.client.post("/api/canaries/runs", json={}, headers={"X-Admin-Key": "admin-secret"})
    assert response.status_code == 202
    h.container.canaries.wait(timeout=120)


def test_set_summary_and_run_receipts_record_normalize_on(canary_harness):
    h = canary_harness()
    summary = h.client.get("/api/canaries/set").json()
    assert summary["version"] == "canaries-fixture" and summary["calls"] == 8
    run_id = h.container.canaries.run(normalize_on=False)
    bodies = [json.loads(r.body) for r in h.container.receipts.all() if r.request_id.startswith(run_id)]
    assert len(bodies) == 8 and all(b["normalize_on"] is False for b in bodies)
