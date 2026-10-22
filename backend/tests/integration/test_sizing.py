"""Hardware Fit Calculator (Feature 7, FR-10) on a fixed benchmark record."""

from __future__ import annotations

import pytest

from app.db.models import BenchmarkRunRecord
from app.db.repositories import utcnow

RUN_ID = "bench-20261022T080000Z-abc123"


def stats(p50: float, p95: float, n: int = 20) -> dict:
    return {"n": n, "mean_ms": p50, "p50_ms": p50, "p95_ms": p95, "max_ms": p95}


def level(concurrency: int, rate: float, p95_ms: float, failures: dict | None = None) -> dict:
    return {"concurrency": concurrency, "n_calls": 20, "wall_s": 60.0, "calls_per_minute": rate,
            "stages": {"total": stats(p95_ms * 0.8, p95_ms)}, "failures": failures or {}}


def add_benchmark(h, levels: list[dict], run_id: str = RUN_ID, status: str = "COMPLETED") -> None:
    with h.container.benchmarks._sessions.begin() as s:
        s.add(BenchmarkRunRecord(
            run_id=run_id, status=status, created_at=utcnow(), finished_at=utcnow(),
            config={"calls_per_level": 20, "concurrency": [lv["concurrency"] for lv in levels],
                    "include_transcription": False, "dial": "balanced", "inputs": []},
            machine={"platform": "Windows-11", "cpu": "Test CPU", "physical_cores": 4, "logical_cores": 8, "ram_gb": 16.0},
            models={"local": "llama3.2:3b", "gpu": "not detected"}, cold=None, levels=levels, budget_s=5.0,
            verdict="POST_CALL_WRAP_UP", verdict_reason="", duration_s=180.0, progress_done=61, progress_total=61,
        ))


def estimate(h, **body):
    body = {"seats": 300, "calls_per_hour": 1200, **body}
    return h.client.post("/api/sizing/estimate", json=body).json()


def test_formula_is_exact_on_a_fixed_benchmark(harness_factory):
    h = harness_factory()
    add_benchmark(h, [level(1, 12.0, 4000), level(2, 20.0, 9000), level(4, 26.0, 70000)])
    body = estimate(h)  # post_call: 60 s budget, so concurrency 4 (p95 70 s) does not fit
    assert body["status"] == "OK" and body["benchmark_run_id"] == RUN_ID
    assert body["required_rate_per_min"] == 30.0  # 1200 x 1.5 / 60
    rec = body["recommendation"]
    assert rec["concurrency_per_machine"] == 2 and rec["per_machine_rate_per_min"] == 20.0
    assert rec["machines"] == 2  # ceil(30 / 20)
    assert rec["headroom_pct"] == 25.0  # (40 - 30) / 40
    assert rec["expected_latency"] == {"p50_s": 7.2, "p95_s": 9.0, "n": 20}
    assert rec["model"] == "llama3.2:3b" and rec["machine"]["cpu"] == "Test CPU"
    assert body["formula"]["machines"] == "ceil(30.00 / 20.00) = 2"
    assert any("Mitel Edge appliance was not benchmarked" in c for c in body["caveats"])
    assert any("did not include transcription" in c for c in body["caveats"])


@pytest.mark.parametrize("calls_per_hour, machines", [(800, 1), (801, 2), (1600, 2), (1601, 3)])
def test_ceil_boundaries(harness_factory, calls_per_hour, machines):
    h = harness_factory()
    add_benchmark(h, [level(2, 20.0, 9000)])  # 20 calls/min; 800 x 1.5 / 60 = exactly 20
    assert estimate(h, calls_per_hour=calls_per_hour, seats=10000)["recommendation"]["machines"] == machines


def test_live_mode_uses_the_live_budget(harness_factory):
    h = harness_factory(live_assist_budget_s=5)
    add_benchmark(h, [level(1, 12.0, 4000), level(2, 20.0, 9000)])
    body = estimate(h, mode="live")
    assert body["budget_s"] == 5 and body["recommendation"]["concurrency_per_machine"] == 1
    assert body["recommendation"]["machines"] == 3  # ceil(30 / 12)


def test_no_configuration_fits_live_mode(harness_factory):
    h = harness_factory(live_assist_budget_s=5)
    add_benchmark(h, [level(1, 12.0, 8000)])
    body = estimate(h, mode="live")
    assert body["status"] == "NO_FIT" and "Consider post-call mode" in body["message"]
    assert body["recommendation"] is None and body["formula"] is None


def test_levels_with_failed_calls_are_never_used(harness_factory):
    h = harness_factory()
    add_benchmark(h, [level(1, 12.0, 4000), level(2, 50.0, 5000, failures={"local_ai": 3})])
    assert estimate(h)["recommendation"]["concurrency_per_machine"] == 1


def test_no_benchmark_means_no_numbers(harness_factory):
    body = estimate(harness_factory())
    assert body["status"] == "NOT_MEASURED" and "Not measured yet" in body["message"]
    assert body["recommendation"] is None and body["formula"] is None and body["benchmark_run_id"] is None


def test_seat_capacity_is_checked(harness_factory):
    h = harness_factory()
    add_benchmark(h, [level(1, 12.0, 4000)])
    body = estimate(h, seats=10, calls_per_hour=1200)  # 10 seats x 12 calls/hour = 120
    assert any("more than 10 seats can handle" in c for c in body["caveats"])


def test_a_named_benchmark_must_exist_and_be_completed(harness_factory):
    h = harness_factory()
    add_benchmark(h, [level(1, 12.0, 4000)], status="RUNNING")
    response = h.client.post("/api/sizing/estimate", json={"seats": 1, "calls_per_hour": 1, "benchmark_run_id": RUN_ID})
    assert response.status_code == 404
    assert estimate(h)["status"] == "NOT_MEASURED"  # a running benchmark is never used
