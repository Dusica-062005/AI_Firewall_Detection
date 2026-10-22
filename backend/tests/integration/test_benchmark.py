"""Latency benchmark (NFR-2, NFR-3) with the Ollama stub and the in-process receiver."""

from __future__ import annotations

import pytest

from app.benchmark.runner import BenchmarkInProgress, percentile, stage_stats
from tests.integration.test_audio import TranscriberStub


def run(h, **options):
    options.setdefault("calls_per_level", 3)
    options.setdefault("concurrency", [1, 2])
    return h.client.get(f"/api/benchmarks/runs/{h.container.benchmarks.run(**options)}").json()


def test_nearest_rank_percentiles_are_exact():
    values = [float(v) for v in range(1, 21)]  # 1..20
    assert percentile(values, 50) == 10.0
    assert percentile(values, 95) == 19.0
    assert percentile([7.0], 95) == 7.0
    assert stage_stats([30.0, 10.0, 20.0, 40.0]) == {"n": 4, "mean_ms": 25.0, "p50_ms": 20.0, "p95_ms": 40.0, "max_ms": 40.0}
    assert stage_stats([]) is None


def test_run_records_stage_stats_throughput_cold_call_and_machine(harness_factory):
    h = harness_factory()
    body = run(h)
    assert body["status"] == "COMPLETED", body["error"]
    assert [lv["concurrency"] for lv in body["levels"]] == [1, 2]
    level = body["levels"][0]
    assert level["n_calls"] == 3 and level["calls_per_minute"] > 0
    for stage in ("detection", "policy", "protection", "local_ai", "total"):
        assert level["stages"][stage]["n"] == 3
    assert level["stages"]["transcription"] is None  # not part of this run
    # The cold call is reported separately and not counted in the levels.
    assert body["cold"]["stages"]["total"] > 0
    assert body["progress_done"] == body["progress_total"] == 1 + 3 * 2
    machine = body["machine"]
    assert machine["platform"] and machine["logical_cores"] and machine["cpu"]
    assert body["models"]["local"] == "llama3.2:3b" and body["models"]["ollama_version"] == "0.0.0-stub"
    assert body["models"]["gpu"] == "not detected"


def test_verdict_flips_at_the_live_assist_budget(harness_factory):
    fast = run(harness_factory(live_assist_budget_s=600))
    assert fast["verdict"] == "REAL_TIME_CAPABLE"
    p95 = fast["levels"][0]["stages"]["total"]["p95_ms"]
    assert f"{p95 / 1000:.2f} s" in fast["verdict_reason"]

    h = harness_factory(live_assist_budget_s=0.001)
    h.ollama.delay_s = 0.05
    slow = run(h)
    assert slow["verdict"] == "POST_CALL_WRAP_UP"
    assert "post-call wrap-up" in slow["verdict_reason"]


def test_a_failing_stage_is_recorded_not_hidden(harness_factory):
    body = run(harness_factory(ollama_mode="down"))
    assert body["status"] == "COMPLETED"
    assert body["levels"][0]["failures"]["local_ai"] == 3
    assert body["verdict"] == "NOT_DETERMINED" and "local_ai" in body["verdict_reason"]


def test_transcription_stage_is_timed_when_included(harness_factory):
    h = harness_factory()
    h.container.transcriber = TranscriberStub()
    body = run(h, concurrency=[1], include_transcription=True)
    stages = body["levels"][0]["stages"]
    assert stages["transcription"] == {"n": 3, "mean_ms": 12.5, "p50_ms": 12.5, "p95_ms": 12.5, "max_ms": 12.5}
    assert stages["total"]["p50_ms"] >= 12.5
    assert body["config"]["inputs"] == ["appointment.wav", "contact.wav", "clean.wav"]


def test_api_starts_in_background_and_rejects_a_second_run(harness_factory):
    h = harness_factory()
    response = h.client.post("/api/benchmarks/runs", json={"calls_per_level": 2, "concurrency": [1]})
    assert response.status_code == 202
    h.container.benchmarks.wait(timeout=120)
    latest = h.client.get("/api/benchmarks/latest").json()
    assert latest["completed"]["run_id"] == response.json()["run_id"]

    class Alive:
        def is_alive(self):
            return True

    h.container.benchmarks._thread = Alive()
    with pytest.raises(BenchmarkInProgress):
        h.container.benchmarks.start()
    assert h.client.post("/api/benchmarks/runs", json={}).status_code == 409
    h.container.benchmarks._thread = None


def test_latest_is_empty_before_any_run_and_input_is_validated(harness_factory):
    h = harness_factory(admin_api_key="admin-secret")
    assert h.client.get("/api/benchmarks/latest").json() == {"run": None, "completed": None}
    assert h.client.post("/api/benchmarks/runs", json={}).status_code == 401
    headers = {"X-Admin-Key": "admin-secret"}
    assert h.client.post("/api/benchmarks/runs", json={"concurrency": [0]}, headers=headers).status_code == 422
