"""Dial quality score (Feature 4, FR-7).

For each synthetic sample:

1. Reference: the RAW transcript summarized by the reference model with the same prompt as the
   firewall's summarizer. The samples are synthetic, so summarizing raw text locally is
   allowed; raw text never goes to the mock cloud. Cached by sha256(model + prompt + text).
2. Candidate per dial position: the real pipeline (ProcessingService, mode FULL, that dial
   position) and the summary the agent sees (re-hydrated locally).
3. Score: cosine similarity between Ollama embeddings of reference and candidate.

A position's score is the mean over samples that produced a summary, with n. A sample with
no summary is recorded as null, never 0. If the embedding model is missing the run fails
with a clear message; a score is never invented.

The score measures how close the protected summary is to the summary of the raw text. It is a
similarity number, not a human quality rating.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import secrets
import threading
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.ollama_client import OllamaClient, OllamaError
from app.ai.summarizer import MAX_SUMMARY_CHARS, build_prompt, clean_output
from app.canaries.runner import machine_description
from app.db.models import QualityReferenceRecord, QualityRunRecord
from app.db.repositories import utcnow
from app.policy.dial import DIAL_POSITIONS
from app.samples import SAMPLES
from app.schemas.requests import ProcessingMode

logger = logging.getLogger(__name__)

# Nothing to summarize (clean-question) or blocked outright (government-id).
EXCLUDED_SAMPLES = frozenset({"clean-question", "government-id"})
POSITION_CODES = {"max_privacy": "mp", "balanced": "bal", "max_quality": "mq"}  # keeps request IDs short


class QualityRunInProgress(Exception):
    """Only one quality run may execute at a time."""


class QualityMeasurementError(Exception):
    """The measurement cannot produce a real number (for example the embedding model is missing)."""


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise QualityMeasurementError("Embedding vectors have different or zero length.")
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        raise QualityMeasurementError("An embedding vector has zero length.")
    return dot / norm


def default_samples() -> list[str]:
    return [s.id for s in SAMPLES if s.id not in EXCLUDED_SAMPLES]


@dataclass(frozen=True)
class QualityModels:
    reference: str
    local: str
    cloud: str | None
    embed: str


class QualityService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        processing,  # ProcessingService
        controls,  # ControlsService
        models: QualityModels,
        ollama_base_url: str,
        timeout_seconds: float,
        ollama_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sessions = sessions
        self._processing = processing
        self._controls = controls
        self.models = models
        self._base_url = ollama_base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = ollama_transport
        self._reference = OllamaClient(ollama_base_url, models.reference, timeout_seconds, ollama_transport)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._mark_interrupted_runs()

    # ---- Starting a run --------------------------------------------------------------------

    def start(self, sample_ids: list[str] | None = None) -> str:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise QualityRunInProgress("A quality measurement is already in progress.")
            run_id, samples = self._create(sample_ids)
            self._thread = threading.Thread(target=self._execute, args=(run_id, samples), name=run_id, daemon=True)
            self._thread.start()
        return run_id

    def run(self, sample_ids: list[str] | None = None) -> str:
        """Execute synchronously (tests and scripts)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise QualityRunInProgress("A quality measurement is already in progress.")
            run_id, samples = self._create(sample_ids)
        self._execute(run_id, samples)
        return run_id

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _create(self, sample_ids: list[str] | None) -> tuple[str, list]:
        wanted = sample_ids or default_samples()
        known = {s.id: s for s in SAMPLES}
        unknown = [i for i in wanted if i not in known]
        if unknown:
            raise ValueError(f"Unknown sample id(s): {', '.join(unknown)}.")
        samples = [known[i] for i in wanted]
        run_id = f"quality-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        with self._sessions.begin() as s:
            s.add(QualityRunRecord(
                run_id=run_id, status="RUNNING", created_at=utcnow(), sample_ids=wanted,
                reference_model=self.models.reference, local_model=self.models.local, cloud_model=self.models.cloud,
                embed_model=self.models.embed, kill_switch_on=self._controls.kill_switch_on(),
                machine=machine_description(), progress_done=0,
                progress_total=len(samples) * (1 + len(DIAL_POSITIONS)), positions=[], samples=[],
            ))
        return run_id, samples

    # ---- Executing ------------------------------------------------------------------------------

    def _execute(self, run_id: str, samples: list) -> None:
        started = time.perf_counter()
        try:
            positions, rows = asyncio.run(self._measure(run_id, samples))
            self._finish(run_id, "COMPLETED", started, positions, rows, None)
        except QualityMeasurementError as exc:
            self._finish(run_id, "FAILED", started, [], [], str(exc))
        except Exception as exc:  # noqa: BLE001 - recorded on the run; never reported as a score
            logger.error("quality run failed", extra={"run_id": run_id, "error_type": type(exc).__name__})
            self._finish(run_id, "FAILED", started, [], [], f"The run stopped with an error ({type(exc).__name__}).")

    async def _measure(self, run_id: str, samples: list) -> tuple[list[dict], list[dict]]:
        await self._check_embed_model()
        done = 0
        rows: list[dict] = []
        for index, sample in enumerate(samples, start=1):
            reference = await self._reference_summary(sample.transcript)
            done += 1
            self._progress(run_id, done)
            for position in DIAL_POSITIONS:
                result = await self._processing.run(
                    request_id=f"{run_id}-s{index}-{POSITION_CODES[position]}",
                    transcript=sample.transcript,
                    profile=sample.profile,
                    channel=sample.channel,
                    mode=ProcessingMode.FULL,
                    operation="PROCESS",
                    dial=position,
                )
                candidate = result.agent_view.summary
                similarity = None
                if candidate:
                    reference_vec, candidate_vec = await self._embed([reference, candidate])
                    similarity = round(cosine(reference_vec, candidate_vec), 4)
                rows.append({
                    "sample_id": sample.id, "title": sample.title, "position": position, "similarity": similarity,
                    "decision": result.decision, "route": result.routing.route, "source": result.agent_view.source,
                    "summary_status": result.agent_view.status,
                })
                done += 1
                self._progress(run_id, done)

        positions = []
        for position in DIAL_POSITIONS:
            values = [r["similarity"] for r in rows if r["position"] == position and r["similarity"] is not None]
            positions.append({
                "position": position,
                "score": round(sum(values) / len(values), 2) if values else None,
                "n": len(values),
                "n_null": sum(1 for r in rows if r["position"] == position and r["similarity"] is None),
            })
        return positions, rows

    async def _check_embed_model(self) -> None:
        hint = f"Run: ollama pull {self.models.embed}"
        try:
            async with self._client(5.0) as client:
                response = await client.get("/api/tags")
            names = [m.get("name", "") for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            raise QualityMeasurementError("Ollama is not reachable, so no quality score can be measured.") from None
        wanted = self.models.embed if ":" in self.models.embed else f"{self.models.embed}:latest"
        if self.models.embed not in names and wanted not in names:
            raise QualityMeasurementError(f"Embedding model '{self.models.embed}' is not installed. {hint}")

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with self._client(self._timeout) as client:
                response = await client.post("/api/embed", json={"model": self.models.embed, "input": texts})
        except httpx.HTTPError:
            raise QualityMeasurementError("The embedding request to Ollama failed.") from None
        if response.status_code == 404:
            raise QualityMeasurementError(
                f"Embedding model '{self.models.embed}' is not installed. Run: ollama pull {self.models.embed}"
            )
        try:
            vectors = response.json()["embeddings"]
        except (ValueError, KeyError, TypeError):
            raise QualityMeasurementError(f"Ollama returned no embeddings (HTTP {response.status_code}).") from None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise QualityMeasurementError("Ollama returned the wrong number of embeddings.")
        return vectors

    async def _reference_summary(self, transcript: str) -> str:
        prompt = build_prompt(transcript)
        key = hashlib.sha256((self.models.reference + "\n" + prompt + "\n" + transcript).encode("utf-8")).hexdigest()
        with self._sessions() as s:
            cached = s.get(QualityReferenceRecord, key)
        if cached is not None:
            return cached.summary
        try:
            result = await self._reference.generate(prompt, max_tokens=220)
        except OllamaError as exc:
            raise QualityMeasurementError(f"Reference model '{self.models.reference}': {exc.message}") from None
        text = clean_output(result.text)
        if not text or len(text) > MAX_SUMMARY_CHARS:
            raise QualityMeasurementError(f"Reference model '{self.models.reference}' returned no usable summary.")
        with self._sessions.begin() as s:
            if s.get(QualityReferenceRecord, key) is None:
                s.add(QualityReferenceRecord(cache_key=key, model=self.models.reference, summary=text, created_at=utcnow()))
        return text

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=timeout, transport=self._transport)

    # ---- Persistence -----------------------------------------------------------------------

    def _progress(self, run_id: str, done: int) -> None:
        with self._sessions.begin() as s:
            record = s.get(QualityRunRecord, run_id)
            if record is not None:
                record.progress_done = done

    def _finish(self, run_id, status, started, positions, rows, error) -> None:
        with self._sessions.begin() as s:
            record = s.get(QualityRunRecord, run_id)
            if record is None:
                return
            record.status = status
            record.finished_at = utcnow()
            record.duration_s = round(time.perf_counter() - started, 2)
            record.positions = positions
            record.samples = rows
            record.error = error

    def _mark_interrupted_runs(self) -> None:
        with self._sessions.begin() as s:
            for record in s.scalars(select(QualityRunRecord).where(QualityRunRecord.status == "RUNNING")):
                record.status = "FAILED"
                record.error = "The backend stopped before this run finished."
                record.finished_at = utcnow()

    def get(self, run_id: str) -> QualityRunRecord | None:
        with self._sessions() as s:
            return s.get(QualityRunRecord, run_id)

    def latest(self, completed_only: bool = False) -> QualityRunRecord | None:
        query = select(QualityRunRecord).order_by(QualityRunRecord.created_at.desc()).limit(1)
        if completed_only:
            query = query.where(QualityRunRecord.status == "COMPLETED")
        with self._sessions() as s:
            return s.scalars(query).first()
