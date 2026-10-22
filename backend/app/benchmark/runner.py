"""Latency benchmark (NFR-2, NFR-3).

Runs the REAL pipeline (mode FULL, models on) on the synthetic samples, or on the synthetic audio
clips when transcription is included, and stores:

- the first call of the run ("cold"), reported separately and excluded from the statistics;
- per concurrency level: n, mean, p50, p95 and max per stage, and calls per minute completed;
- the machine (only what can be detected) and the models used;
- the NFR-2 verdict: "REAL_TIME_CAPABLE" when the warm p95 total at concurrency 1 fits
  LIVE_ASSIST_BUDGET_S, otherwise "POST_CALL_WRAP_UP". If any call failed a stage, the verdict
  is "NOT_DETERMINED": a failed stage is reported, never hidden or averaged away.

Percentiles use the nearest-rank method: p = the value at rank ceil(p/100 * n) of the sorted list.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import platform
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.db.models import BenchmarkRunRecord
from app.db.repositories import utcnow
from app.samples import SAMPLES
from app.schemas.requests import ProcessingMode

logger = logging.getLogger(__name__)

STAGES = ("transcription", "detection", "policy", "protection", "local_ai", "cloud", "total")
# Samples that reach the local model under the default policies: the useful ones to time.
BENCHMARK_SAMPLES = ("appointment-standard", "appointment-healthcare", "contact-update", "billing-account",
                     "hinglish-triage", "reschedule-dob")
AUDIO_CLIPS = ("appointment.wav", "contact.wav", "clean.wav")
LOCAL_FAILURES = {"UNAVAILABLE", "MODEL_MISSING", "TIMEOUT", "INVALID_OUTPUT", "ERROR"}
CLOUD_FAILURES = {"VALIDATION_FAILED", "UNAVAILABLE", "REJECTED", "ERROR"}


class BenchmarkInProgress(Exception):
    """Only one benchmark may run at a time."""


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def stage_stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "n": len(values),
        "mean_ms": round(sum(values) / len(values), 2),
        "p50_ms": round(percentile(values, 50), 2),
        "p95_ms": round(percentile(values, 95), 2),
        "max_ms": round(max(values), 2),
    }


def machine_info() -> dict:
    """Only what can actually be detected; nothing is guessed."""
    info: dict = {"platform": platform.platform(), "cpu": _cpu_name(), "logical_cores": os.cpu_count()}
    try:
        import psutil

        info["physical_cores"] = psutil.cpu_count(logical=False)
        info["ram_gb"] = round(psutil.virtual_memory().total / 1024**3, 1)
    except Exception:  # noqa: BLE001
        info["physical_cores"] = None
        info["ram_gb"] = None
    return info


def _cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "not detected"


@dataclass
class CallMeasure:
    stages: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)  # stages that failed for this call


class BenchmarkRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        processing,  # ProcessingService
        controls,  # ControlsService
        transcriber_source,  # callable returning the current Transcriber
        models: dict,
        ollama_base_url: str,
        live_budget_s: float,
        audio_dir: Path,
        ollama_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sessions = sessions
        self._processing = processing
        self._controls = controls
        self._transcriber = transcriber_source
        self._models = models
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_transport = ollama_transport
        self.live_budget_s = live_budget_s
        self._audio_dir = audio_dir
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._mark_interrupted_runs()

    # ---- Starting a run --------------------------------------------------------------------

    def start(self, calls_per_level: int = 20, concurrency: list[int] | None = None,
              include_transcription: bool = False, dial: str | None = None) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise BenchmarkInProgress("A benchmark is already running.")
            run_id, config = self._create(calls_per_level, concurrency or [1, 2, 4], include_transcription, dial)
            self._thread = threading.Thread(target=self._execute, args=(run_id, config), name=run_id, daemon=True)
            self._thread.start()
        return run_id

    def run(self, calls_per_level: int = 20, concurrency: list[int] | None = None,
            include_transcription: bool = False, dial: str | None = None) -> str:
        """Execute synchronously (tests and scripts)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise BenchmarkInProgress("A benchmark is already running.")
            run_id, config = self._create(calls_per_level, concurrency or [1, 2, 4], include_transcription, dial)
        self._execute(run_id, config)
        return run_id

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _create(self, calls_per_level: int, concurrency: list[int], include_transcription: bool, dial: str | None):
        levels = sorted(set(concurrency))
        config = {
            "calls_per_level": calls_per_level,
            "concurrency": levels,
            "include_transcription": include_transcription,
            "dial": dial or self._controls.get().dial,
            "inputs": list(AUDIO_CLIPS) if include_transcription else list(BENCHMARK_SAMPLES),
        }
        run_id = f"bench-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        with self._sessions.begin() as s:
            s.add(BenchmarkRunRecord(
                run_id=run_id, status="RUNNING", created_at=utcnow(), config=config, machine=machine_info(),
                models=dict(self._models), levels=[], budget_s=self.live_budget_s,
                progress_done=0, progress_total=1 + calls_per_level * len(levels),
            ))
        return run_id, config

    # ---- Executing ------------------------------------------------------------------------------

    def _execute(self, run_id: str, config: dict) -> None:
        started = time.perf_counter()
        try:
            asyncio.run(self._measure(run_id, config, started))
        except Exception as exc:  # noqa: BLE001 - recorded on the run; never reported as a result
            logger.error("benchmark failed", extra={"run_id": run_id, "error_type": type(exc).__name__})
            self._update(run_id, status="FAILED", finished_at=utcnow(), duration_s=round(time.perf_counter() - started, 2),
                         error=f"The benchmark stopped with an error ({type(exc).__name__}).")

    async def _measure(self, run_id: str, config: dict, started: float) -> None:
        models = {**self._models, **await self._ollama_details()}
        inputs = self._inputs(config)
        counter = {"done": 0, "seq": 0}

        cold = await self._call(run_id, config, inputs[0], counter)
        counter["done"] += 1
        self._update(run_id, progress_done=counter["done"], models=models,
                     cold={"stages": cold.stages, "failures": cold.failures})

        levels = []
        for concurrency in config["concurrency"]:
            calls = [inputs[i % len(inputs)] for i in range(config["calls_per_level"])]
            gate = asyncio.Semaphore(concurrency)
            measures: list[CallMeasure] = []

            async def one(item):
                async with gate:
                    measure = await self._call(run_id, config, item, counter)
                    measures.append(measure)
                    counter["done"] += 1
                    self._update(run_id, progress_done=counter["done"])

            level_started = time.perf_counter()
            await asyncio.gather(*(one(item) for item in calls))
            wall_s = time.perf_counter() - level_started
            failures: dict[str, int] = {}
            for m in measures:
                for stage in m.failures:
                    failures[stage] = failures.get(stage, 0) + 1
            levels.append({
                "concurrency": concurrency,
                "n_calls": len(measures),
                "wall_s": round(wall_s, 2),
                "calls_per_minute": round(len(measures) / wall_s * 60, 2) if wall_s > 0 else None,
                "stages": {s: stage_stats([m.stages[s] for m in measures if s in m.stages]) for s in STAGES},
                "failures": failures,
            })

        verdict, reason = self._verdict(levels)
        self._update(run_id, status="COMPLETED", finished_at=utcnow(), levels=levels, verdict=verdict,
                     verdict_reason=reason, duration_s=round(time.perf_counter() - started, 2))

    def _verdict(self, levels: list[dict]) -> tuple[str, str]:
        level = next((lv for lv in levels if lv["concurrency"] == 1), levels[0])
        if any(lv["failures"] for lv in levels):
            failed = sorted({s for lv in levels for s in lv["failures"]})
            return "NOT_DETERMINED", f"Some calls failed a stage ({', '.join(failed)}), so no latency claim is made."
        total = level["stages"]["total"]
        p95_s = total["p95_ms"] / 1000
        label = f"warm p95 total {p95_s:.2f} s at concurrency {level['concurrency']} (n={total['n']})"
        if p95_s <= self.live_budget_s:
            return "REAL_TIME_CAPABLE", f"{label} is within the {self.live_budget_s:g} s live-assist budget."
        return "POST_CALL_WRAP_UP", (
            f"{label} exceeds the {self.live_budget_s:g} s live-assist budget: present this as fast post-call "
            "wrap-up, not real-time agent assist."
        )

    def _inputs(self, config: dict) -> list:
        if config["include_transcription"]:
            paths = [self._audio_dir / name for name in config["inputs"]]
            missing = [p.name for p in paths if not p.exists()]
            if missing:
                raise FileNotFoundError(", ".join(missing))
            return paths
        samples = {s.id: s for s in SAMPLES}
        return [samples[i] for i in config["inputs"]]

    async def _call(self, run_id: str, config: dict, item, counter: dict) -> CallMeasure:
        counter["seq"] += 1
        measure = CallMeasure()
        audio = None
        if isinstance(item, Path):
            try:
                transcript = await run_in_threadpool(self._transcriber().transcribe, item)
            except Exception:  # noqa: BLE001 - a failed stage is recorded, never hidden
                measure.failures.append("transcription")
                return measure
            measure.stages["transcription"] = transcript.transcription_ms
            text, profile, channel = transcript.text, "standard", "voice"
            audio = {"format": "wav", "duration_s": transcript.duration_s, "model": transcript.model,
                     "transcription_ms": transcript.transcription_ms}
        else:
            text, profile, channel = item.transcript, item.profile, item.channel
        try:
            result = await self._processing.run(
                request_id=f"{run_id}-c{counter['seq']}", transcript=text, profile=profile, channel=channel,
                mode=ProcessingMode.FULL, operation="PROCESS", dial=config["dial"], audio=audio,
            )
        except Exception:  # noqa: BLE001
            measure.failures.append("pipeline")
            return measure
        lat = result.latency
        for stage in ("detection", "policy", "protection", "local_ai", "cloud"):
            value = getattr(lat, f"{stage}_ms")
            if value is not None:
                measure.stages[stage] = value
        measure.stages["total"] = lat.total_ms + (measure.stages.get("transcription") or 0)
        if result.summary.status in LOCAL_FAILURES:
            measure.failures.append("local_ai")
        if result.outbound.status in CLOUD_FAILURES:
            measure.failures.append("cloud")
        if result.status == "FAILED":
            measure.failures.append("pipeline")
        return measure

    async def _ollama_details(self) -> dict:
        """Ollama version and whether a loaded model uses GPU memory. Absent data stays absent."""
        details: dict = {"ollama_version": None, "gpu": "not detected"}
        try:
            async with httpx.AsyncClient(base_url=self._ollama_base_url, timeout=3.0, transport=self._ollama_transport) as c:
                version = await c.get("/api/version")
                if version.status_code == 200:
                    details["ollama_version"] = version.json().get("version")
                running = await c.get("/api/ps")
                if running.status_code == 200:
                    vram = sum(int(m.get("size_vram") or 0) for m in running.json().get("models", []))
                    if vram > 0:
                        details["gpu"] = f"used by Ollama ({vram / 1024**3:.1f} GB VRAM)"
        except (httpx.HTTPError, ValueError):
            pass
        return details

    # ---- Persistence -----------------------------------------------------------------------

    def _update(self, run_id: str, **values) -> None:
        with self._sessions.begin() as s:
            record = s.get(BenchmarkRunRecord, run_id)
            if record is not None:
                for key, value in values.items():
                    setattr(record, key, value)

    def _mark_interrupted_runs(self) -> None:
        with self._sessions.begin() as s:
            for record in s.scalars(select(BenchmarkRunRecord).where(BenchmarkRunRecord.status == "RUNNING")):
                record.status = "FAILED"
                record.error = "The backend stopped before this run finished."
                record.finished_at = utcnow()

    def list(self) -> list[BenchmarkRunRecord]:
        with self._sessions() as s:
            return list(s.scalars(select(BenchmarkRunRecord).order_by(BenchmarkRunRecord.created_at.desc())).all())

    def get(self, run_id: str) -> BenchmarkRunRecord | None:
        with self._sessions() as s:
            return s.get(BenchmarkRunRecord, run_id)

    def latest(self, completed_only: bool = False) -> BenchmarkRunRecord | None:
        query = select(BenchmarkRunRecord).order_by(BenchmarkRunRecord.created_at.desc()).limit(1)
        if completed_only:
            query = query.where(BenchmarkRunRecord.status == "COMPLETED")
        with self._sessions() as s:
            return s.scalars(query).first()
