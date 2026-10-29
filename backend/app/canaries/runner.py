"""Leak-canary runner (Feature 5, FR-8).

Every canary call goes through the REAL pipeline (ProcessingService -> FirewallService ->
router -> outbound validation -> mock CloudLink). Two numbers come out:

- Detection recall: a planted value counts as detected when every one of its spans overlaps
  a detected entity of any type.
- Leak rate at the receiver: read from what the mock receiver actually logged
  (RECEIVED_LOG_FILE), never from what the firewall believes it sent. A planted value leaked
  when any surface part appears in a received payload (case-insensitive), or, for numbers,
  its digits appear once spaces and hyphens are stripped.

The receiver log must account for every payload the firewall reports as delivered; if it
does not (for example the receiver writes a different file), the run fails instead of
reporting a leak rate of zero that was never measured.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import secrets
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import regex
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.canaries.models import (
    HOLDOUT_FILE,
    NUMERIC_TYPES,
    CanaryCall,
    CanarySet,
    PlantedValue,
    load_canary_set,
    random_canary_set,
)
from app.db.models import CanaryRunRecord
from app.db.repositories import utcnow
from app.detection.normalizer import NATIVE_DIGITS
from app.schemas.requests import ProcessingMode

logger = logging.getLogger(__name__)

RUN_DIAL = "max_quality"  # tokenizes only what policy requires, so the cloud path is exercised
PAYLOAD_FIELDS = ("sanitized_transcript", "sanitized_summary")
_STRIP = regex.compile(r"[\s\-]+")


class RunInProgress(Exception):
    """Only one canary run may execute at a time."""


def machine_description() -> str:
    return f"{platform.platform()} ({os.cpu_count()} CPUs)"


def rule_version(detection_config_file: Path, policy_version: str) -> str:
    """Ties a run to the exact detection rules and policy set that produced it."""
    digest = hashlib.sha256(detection_config_file.read_bytes() + policy_version.encode("utf-8")).hexdigest()
    return f"rules-{digest[:12]}"


def _digits(text: str) -> str:
    return _STRIP.sub("", text.translate(NATIVE_DIGITS))


def _canonical_digits(value: PlantedValue) -> str:
    return "".join(c for c in value.canonical if c.isdigit())


@dataclass
class CallOutcome:
    call: CanaryCall
    detected: list[bool] = field(default_factory=list)  # per planted value
    route: str = "NONE"
    route_reason: str = "error"
    sent: bool = False
    error: bool = False


class CanaryRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        processing,  # ProcessingService
        controls,  # ControlsService
        received_log_file: Path,
        low_confidence_threshold: float,
        default_normalize: bool,
        rule_version_source: Callable[[], str],
        canary_set_loader: Callable[[], CanarySet] = load_canary_set,
        holdout_set_loader: Callable[[], CanarySet] = lambda: load_canary_set(HOLDOUT_FILE),
        random_set_loader: Callable[[], CanarySet] = random_canary_set,
    ) -> None:
        self._sessions = sessions
        self._processing = processing
        self._controls = controls
        self._received_log_file = received_log_file
        self._low_confidence_threshold = low_confidence_threshold
        self._default_normalize = default_normalize
        self._rule_version_source = rule_version_source
        self._loader = canary_set_loader
        self._holdout_loader = holdout_set_loader
        self._random_loader = random_set_loader
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # Called with the run ID when a completed run measured leaks (auto-drafts a breach report).
        self.on_leaks: Callable[[str], object] | None = None
        self._mark_interrupted_runs()

    # ---- Canary set ---------------------------------------------------------------------

    def canary_set(self, name: str = "main") -> CanarySet:
        """``main`` (the 200-call set), ``holdout`` (new templates, checks for overfitting) or
        ``random`` (freshly generated on every call; its seed is in the version)."""
        if name not in ("main", "holdout", "random"):
            raise ValueError(f"Unknown canary set {name}.")
        if name == "random":
            return self._random_loader()
        return self._holdout_loader() if name == "holdout" else self._loader()

    # ---- Starting and executing a run --------------------------------------------------------

    def start(self, rule_version: str | None = None, normalize_on: bool | None = None, set_name: str = "main") -> str:
        """Create the run record and execute it in a background thread. Returns the run ID."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RunInProgress("A canary run is already in progress.")
            run_id, canary_set, normalize = self._create(rule_version, normalize_on, set_name)
            self._thread = threading.Thread(
                target=self._execute_in_thread, args=(run_id, canary_set, normalize), name=f"canary-{run_id}", daemon=True
            )
            self._thread.start()
        return run_id

    def run(self, rule_version: str | None = None, normalize_on: bool | None = None, set_name: str = "main") -> str:
        """Execute a run synchronously (tests and scripts). Returns the run ID."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RunInProgress("A canary run is already in progress.")
            run_id, canary_set, normalize = self._create(rule_version, normalize_on, set_name)
        self._execute_in_thread(run_id, canary_set, normalize)
        return run_id

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _create(self, rule_version: str | None, normalize_on: bool | None, set_name: str) -> tuple[str, CanarySet, bool]:
        canary_set = self.canary_set(set_name)
        normalize = self._default_normalize if normalize_on is None else normalize_on
        run_id = f"canary-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        with self._sessions.begin() as s:
            s.add(CanaryRunRecord(
                run_id=run_id,
                status="RUNNING",
                created_at=utcnow(),
                canary_set_version=canary_set.version,
                rule_version=rule_version or self._rule_version_source(),
                normalize_on=normalize,
                low_confidence_threshold=self._low_confidence_threshold,
                dial=RUN_DIAL,
                kill_switch_on=self._controls.kill_switch_on(),
                machine=machine_description(),
                progress_done=0,
                progress_total=len(canary_set.calls),
                misses=[],
                leaks=[],
            ))
        return run_id, canary_set, normalize

    def _execute_in_thread(self, run_id: str, canary_set: CanarySet, normalize: bool) -> None:
        started = time.perf_counter()
        try:
            outcomes = asyncio.run(self._process_all(run_id, canary_set, normalize))
            metrics, misses, leaks, error = self._measure(run_id, outcomes)
            self._finish(run_id, "FAILED" if error else "COMPLETED", started, metrics, misses, leaks, error)
            if leaks and not error and self.on_leaks is not None:
                try:
                    self.on_leaks(run_id)
                except Exception as exc:  # noqa: BLE001 - the measurement stands; drafting can be retried by hand
                    logger.error("breach report auto-draft failed", extra={"run_id": run_id, "error_type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001 - recorded on the run; never reported as a result
            logger.error("canary run failed", extra={"run_id": run_id, "error_type": type(exc).__name__})
            self._finish(run_id, "FAILED", started, None, [], [], f"The run stopped with an error ({type(exc).__name__}).")

    async def _process_all(self, run_id: str, canary_set: CanarySet, normalize: bool) -> list[CallOutcome]:
        outcomes: list[CallOutcome] = []
        for index, call in enumerate(canary_set.calls, start=1):
            outcome = CallOutcome(call=call)
            try:
                result = await self._processing.run(
                    request_id=f"{run_id}-{call.call_id}",
                    transcript=call.text,
                    profile=call.profile,
                    channel="voice",
                    mode=ProcessingMode.FULL,
                    operation="PROCESS",
                    dial=RUN_DIAL,
                    run_models=False,
                    normalize=normalize,
                )
                spans = [(e.start, e.end) for e in result.entities]
                outcome.detected = [
                    all(any(s < e_end and e_start < e for e_start, e_end in spans) for s, e in value.spans)
                    for value in call.planted
                ]
                outcome.route = result.routing.route
                outcome.route_reason = result.routing.reason
                outcome.sent = result.outbound.reached_receiver
            except Exception:  # noqa: BLE001 - counted as missed; leaks are still read from the receiver
                outcome.detected = [False] * len(call.planted)
                outcome.error = True
            outcomes.append(outcome)
            self._progress(run_id, index)
        return outcomes

    # ---- Measuring -------------------------------------------------------------------------

    def _received(self, run_id: str) -> dict[str, list[dict]]:
        """Payloads the receiver logged for this run, keyed by request ID."""
        prefix = f"{run_id}-"
        received: dict[str, list[dict]] = {}
        try:
            lines = self._received_log_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return received
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            request_id = str(entry.get("request_id", ""))
            if request_id.startswith(prefix):
                received.setdefault(request_id, []).append(entry)
        return received

    def _measure(self, run_id: str, outcomes: list[CallOutcome]):
        received = self._received(run_id)
        received_lines = sum(len(v) for v in received.values())
        payloads_sent = sum(o.sent for o in outcomes)

        rows: list[dict] = []  # one per planted value
        misses: list[dict] = []
        leaks: list[dict] = []
        for outcome in outcomes:
            call = outcome.call
            entries = received.get(f"{run_id}-{call.call_id}", [])
            for value, detected in zip(call.planted, outcome.detected):
                leak_field = self._leak_field(call, value, entries)
                base = {"call_id": call.call_id, "type": value.type, "difficulty": call.difficulty,
                        "language": call.language, "script": call.script, "surface": " … ".join(call.surfaces(value))}
                if not detected:
                    misses.append(base)
                if leak_field:
                    leaks.append({**base, "field": leak_field})
                rows.append({**base, "detected": detected, "leaked": bool(leak_field)})

        metrics = {
            "overall": _bucket("all", rows, outcomes, lambda r: True, lambda o: True),
            "by_type": _buckets(rows, outcomes, lambda r: r["type"], None),
            "by_difficulty": _buckets(rows, outcomes, lambda r: r["difficulty"], lambda o: o.call.difficulty),
            "by_language": _buckets(rows, outcomes, lambda r: r["language"], lambda o: o.call.language),
            "by_script": _buckets(rows, outcomes, lambda r: f"{r['language']}/{r['script']}",
                                  lambda o: f"{o.call.language}/{o.call.script}"),
            "route_counts": dict(sorted(Counter(o.route for o in outcomes).items())),
            "route_reasons": dict(sorted(Counter(o.route_reason for o in outcomes).items())),
            "payloads_sent": payloads_sent,
            "received_lines": received_lines,
            "low_confidence_holds": sum(o.route_reason == "low_confidence_entity" for o in outcomes),
            "call_errors": sum(o.error for o in outcomes),
        }
        error = None
        if received_lines != payloads_sent:
            error = (
                f"The receiver log has {received_lines} payload(s) for this run but the firewall delivered "
                f"{payloads_sent}. Check that the mock receiver writes to the same RECEIVED_LOG_FILE "
                f"({self._received_log_file}); the leak rate was not measured."
            )
        return metrics, misses, leaks, error

    @staticmethod
    def _leak_field(call: CanaryCall, value: PlantedValue, entries: list[dict]) -> str | None:
        surfaces = [s.lower() for s in call.surfaces(value) if s.strip()]
        digits = _canonical_digits(value) if value.type in NUMERIC_TYPES else ""
        for entry in entries:
            for name in PAYLOAD_FIELDS:
                text = entry.get(name)
                if not isinstance(text, str) or not text:
                    continue
                if any(s in text.lower() for s in surfaces):
                    return name
                if digits and digits in _digits(text):
                    return name
        return None

    # ---- Persistence -----------------------------------------------------------------------

    def _progress(self, run_id: str, done: int) -> None:
        with self._sessions.begin() as s:
            record = s.get(CanaryRunRecord, run_id)
            if record is not None:
                record.progress_done = done

    def _finish(self, run_id, status, started, metrics, misses, leaks, error) -> None:
        with self._sessions.begin() as s:
            record = s.get(CanaryRunRecord, run_id)
            if record is None:
                return
            record.status = status
            record.finished_at = utcnow()
            record.duration_s = round(time.perf_counter() - started, 2)
            record.metrics = metrics
            record.misses = misses
            record.leaks = leaks
            record.error = error

    def _mark_interrupted_runs(self) -> None:
        """A RUNNING row left by a stopped process can never finish."""
        with self._sessions.begin() as s:
            for record in s.scalars(select(CanaryRunRecord).where(CanaryRunRecord.status == "RUNNING")):
                record.status = "FAILED"
                record.error = "The backend stopped before this run finished."
                record.finished_at = utcnow()

    def list(self) -> list[CanaryRunRecord]:
        with self._sessions() as s:
            return list(s.scalars(select(CanaryRunRecord).order_by(CanaryRunRecord.created_at.desc())).all())

    def get(self, run_id: str) -> CanaryRunRecord | None:
        with self._sessions() as s:
            return s.get(CanaryRunRecord, run_id)

    def latest_completed(self) -> CanaryRunRecord | None:
        with self._sessions() as s:
            return s.scalars(
                select(CanaryRunRecord)
                .where(CanaryRunRecord.status == "COMPLETED")
                .order_by(CanaryRunRecord.created_at.desc())
                .limit(1)
            ).first()


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _bucket(key: str, rows: list[dict], outcomes: list[CallOutcome], row_filter, call_filter) -> dict:
    selected = [r for r in rows if row_filter(r)]
    detected = sum(r["detected"] for r in selected)
    leaked = sum(r["leaked"] for r in selected)
    n_calls = sum(1 for o in outcomes if call_filter(o)) if call_filter else len({r["call_id"] for r in selected})
    return {
        "key": key, "n_calls": n_calls, "n_planted": len(selected), "detected": detected,
        "recall": _rate(detected, len(selected)), "leaked": leaked, "leak_rate": _rate(leaked, len(selected)),
    }


def _buckets(rows: list[dict], outcomes: list[CallOutcome], row_key, call_key) -> list[dict]:
    keys = sorted({row_key(r) for r in rows})
    return [
        _bucket(
            k, rows, outcomes,
            lambda r, k=k: row_key(r) == k,
            (lambda o, k=k: call_key(o) == k) if call_key else None,
        )
        for k in keys
    ]
