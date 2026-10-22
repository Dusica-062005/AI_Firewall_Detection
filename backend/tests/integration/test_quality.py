"""Dial quality score (Feature 4, FR-7) with the Ollama stub's fixed embeddings."""

from __future__ import annotations

import pytest

from app.quality.service import QualityMeasurementError, QualityRunInProgress, cosine
from tests.conftest import fixed_embedding


def test_cosine_is_computed_correctly():
    assert cosine([1.0, 0.0], [0.6, 0.8]) == pytest.approx(0.6)
    assert cosine([2.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)
    with pytest.raises(QualityMeasurementError):
        cosine([0.0, 0.0], [1.0, 0.0])


def test_scores_are_the_mean_cosine_of_reference_and_candidate(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    run_id = h.container.quality.run(["appointment-standard", "contact-update"])
    run = h.client.get(f"/api/quality/runs/{run_id}").json()
    assert run["status"] == "COMPLETED", run["error"]

    # Embedding requests arrive as [reference, candidate] pairs, in sample-then-position order.
    pairs = list(zip(h.ollama.embedded[0::2], h.ollama.embedded[1::2]))
    expected = [round(cosine(fixed_embedding(a), fixed_embedding(b)), 4) for a, b in pairs]
    assert [s["similarity"] for s in run["samples"]] == expected

    for position in run["positions"]:
        values = [s["similarity"] for s in run["samples"] if s["position"] == position["position"]]
        assert position["n"] == 2 and position["n_null"] == 0
        assert position["score"] == round(sum(values) / len(values), 2)
    assert {p["position"] for p in run["positions"]} == {"max_privacy", "balanced", "max_quality"}
    assert run["embed_model"] == "nomic-embed-text" and run["reference_model"] == "llama3.2:3b"
    assert "not a human quality rating" in run["note"]


def test_reference_summary_is_cached(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    h.container.quality.run(["appointment-standard"])
    raw_prompts = [p for p in h.ollama.prompts if "John Smith" in p]
    assert len(raw_prompts) == 1  # the reference: the only prompt that sees the raw name
    h.container.quality.run(["appointment-standard"])
    assert len([p for p in h.ollama.prompts if "John Smith" in p]) == 1


def test_raw_text_never_reaches_the_mock_cloud(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    h.container.quality.run(["appointment-standard", "reschedule-dob"])
    sent = b"".join(r.content for r in h.receiver_transport.handoff_requests())
    assert sent  # the cloud path was exercised
    for raw in (b"John Smith", b"48291", b"Daniel Okafor", b"77120"):
        assert raw not in sent


def test_positions_without_a_summary_are_null_not_zero(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    run = h.client.get(f"/api/quality/runs/{h.container.quality.run(['appointment-restricted'])}").json()
    assert run["status"] == "COMPLETED"
    assert all(s["similarity"] is None and s["decision"] == "BLOCKED" for s in run["samples"])
    assert all(p["score"] is None and p["n"] == 0 and p["n_null"] == 1 for p in run["positions"])


def test_missing_embedding_model_fails_with_the_pull_hint(harness_factory):
    h = harness_factory()
    h.ollama.embed_missing = True
    run = h.client.get(f"/api/quality/runs/{h.container.quality.run()}").json()
    assert run["status"] == "FAILED"
    assert "ollama pull nomic-embed-text" in run["error"]
    assert run["positions"] == [] and run["samples"] == []


def test_latest_shows_not_measured_until_a_run_completes(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    assert h.client.get("/api/quality/latest").json() == {"run": None, "completed": None}
    h.ollama.embed_missing = True
    h.container.quality.run(["appointment-standard"])
    latest = h.client.get("/api/quality/latest").json()
    assert latest["run"]["status"] == "FAILED" and latest["completed"] is None


def test_post_runs_in_the_background(harness_factory):
    h = harness_factory(ollama_mode="echo_tokens")
    response = h.client.post("/api/quality/runs", json={"sample_ids": ["appointment-standard"]})
    assert response.status_code == 202
    h.container.quality.wait(timeout=120)
    latest = h.client.get("/api/quality/latest").json()
    assert latest["completed"]["run_id"] == response.json()["run_id"]
    assert latest["completed"]["progress_done"] == latest["completed"]["progress_total"] == 4


def test_unknown_sample_and_concurrent_run_are_rejected(harness_factory):
    h = harness_factory()
    assert h.client.post("/api/quality/runs", json={"sample_ids": ["nope"]}).status_code == 422

    class Alive:  # stands in for a run thread that is still working
        def is_alive(self):
            return True

    h.container.quality._thread = Alive()
    with pytest.raises(QualityRunInProgress):
        h.container.quality.start()
    assert h.client.post("/api/quality/runs", json={}).status_code == 409
    h.container.quality._thread = None


def test_post_requires_the_admin_key_when_configured(harness_factory):
    h = harness_factory(admin_api_key="admin-secret")
    assert h.client.post("/api/quality/runs", json={}).status_code == 401
