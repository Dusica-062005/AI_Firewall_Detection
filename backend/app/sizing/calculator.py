"""Hardware Fit Calculator (Feature 7, FR-10).

Sizing uses ONLY a completed benchmark run (C2), never estimates or extrapolation:

    required_rate    = calls_per_hour * peak_factor / 60            (calls per minute)
    per_machine_rate = best measured calls per minute at a concurrency whose warm p95 total
                       fits the budget for the mode (live: LIVE_ASSIST_BUDGET_S,
                       post_call: POST_CALL_BUDGET_S), from levels with no failed calls
    machines         = ceil(required_rate / per_machine_rate)
    headroom         = (machines * per_machine_rate - required_rate) / (machines * per_machine_rate)
    expected latency = the measured p50 and p95 total at that concurrency

Only the benchmarked machine and models can be recommended. Anything else is reported as "not
benchmarked" in the caveats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizingInput:
    seats: int
    calls_per_hour: int
    avg_call_minutes: float = 5.0
    peak_factor: float = 1.5
    mode: str = "post_call"  # post_call | live


def estimate(inp: SizingInput, benchmark, live_budget_s: float, post_call_budget_s: float) -> dict:
    """``benchmark`` is a completed BenchmarkRunRecord, or None."""
    budget_s = live_budget_s if inp.mode == "live" else post_call_budget_s
    required = inp.calls_per_hour * inp.peak_factor / 60
    result = {
        "inputs": {"seats": inp.seats, "calls_per_hour": inp.calls_per_hour, "avg_call_minutes": inp.avg_call_minutes,
                   "peak_factor": inp.peak_factor, "mode": inp.mode},
        "budget_s": budget_s,
        "required_rate_per_min": round(required, 2),
        "benchmark_run_id": None,
        "formula": None,
        "recommendation": None,
        "caveats": [],
    }
    seat_capacity = inp.seats * 60 / inp.avg_call_minutes
    if inp.calls_per_hour > seat_capacity:
        result["caveats"].append(
            f"{inp.calls_per_hour} calls/hour is more than {inp.seats} seats can handle at "
            f"{inp.avg_call_minutes:g} minutes per call ({seat_capacity:.0f} calls/hour); check the inputs."
        )
    if benchmark is None:
        return {**result, "status": "NOT_MEASURED",
                "message": "Not measured yet. Run a benchmark (Measurements > Benchmark) to size a deployment."}

    result["benchmark_run_id"] = benchmark.run_id
    fitting = [
        lv for lv in benchmark.levels
        if not lv["failures"] and lv["calls_per_minute"] and lv["stages"]["total"]
        and lv["stages"]["total"]["p95_ms"] / 1000 <= budget_s
    ]
    result["caveats"] += _caveats(benchmark)
    if not fitting:
        hint = " Consider post-call mode." if inp.mode == "live" else ""
        return {**result, "status": "NO_FIT",
                "message": f"No benchmarked configuration meets the {budget_s:g} s {_mode(inp.mode)} budget.{hint}"}

    best = max(fitting, key=lambda lv: lv["calls_per_minute"])
    per_machine = best["calls_per_minute"]
    machines = max(1, math.ceil(required / per_machine))
    capacity = machines * per_machine
    total = best["stages"]["total"]
    result["formula"] = {
        "required_rate": f"{inp.calls_per_hour} calls/hour x {inp.peak_factor:g} peak factor / 60 = {required:.2f} calls/min",
        "per_machine_rate": f"{per_machine:.2f} calls/min measured at concurrency {best['concurrency']} "
                            f"(warm p95 {total['p95_ms'] / 1000:.2f} s <= {budget_s:g} s budget, n={total['n']})",
        "machines": f"ceil({required:.2f} / {per_machine:.2f}) = {machines}",
        "headroom": f"({machines} x {per_machine:.2f} - {required:.2f}) / ({machines} x {per_machine:.2f}) "
                    f"= {(capacity - required) / capacity * 100:.1f}%",
    }
    machine = benchmark.machine
    result["recommendation"] = {
        "machines": machines,
        "concurrency_per_machine": best["concurrency"],
        "per_machine_rate_per_min": per_machine,
        "headroom_pct": round((capacity - required) / capacity * 100, 1),
        "expected_latency": {"p50_s": round(total["p50_ms"] / 1000, 2), "p95_s": round(total["p95_ms"] / 1000, 2),
                             "n": total["n"]},
        "model": benchmark.models.get("local"),
        "machine": {k: machine.get(k) for k in ("cpu", "physical_cores", "logical_cores", "ram_gb", "platform")},
        "gpu": benchmark.models.get("gpu", "not detected"),
    }
    return {**result, "status": "OK",
            "message": f"{machines} machine(s) like the benchmarked one, each at concurrency {best['concurrency']}."}


def _mode(mode: str) -> str:
    return "live-assist" if mode == "live" else "post-call"


def _caveats(benchmark) -> list[str]:
    machine, models, config = benchmark.machine, benchmark.models, benchmark.config
    caveats = [
        f"Measured on one machine: {machine.get('cpu')}, {machine.get('physical_cores') or '?'} cores, "
        f"{machine.get('ram_gb') or '?'} GB RAM, GPU {models.get('gpu', 'not detected')}. "
        "A Mitel Edge appliance was not benchmarked.",
        f"Only the benchmarked local model ({models.get('local')}) can be recommended; larger models were not benchmarked.",
        "Throughput was measured on short synthetic calls; real calls are longer, so treat this as a lower bound "
        "on the hardware needed.",
    ]
    if not config.get("include_transcription"):
        caveats.append("This benchmark did not include transcription; audio calls add transcription time.")
    return caveats
