"""Sensitive-data analyzer built on Microsoft Presidio plus custom recognizers."""

from __future__ import annotations

import logging
import threading
import time

import regex

from app.detection.entities import DetectedEntity
from app.detection.normalizer import map_span, normalize_numbers
from app.detection.recognizers import ContextualPatternRecognizer, DetectionConfig

logger = logging.getLogger(__name__)

# Firewall tokens: "[PERSON_1]", and the bare "PERSON_1" form a model may write back.
PLACEHOLDER_PATTERN = regex.compile(
    r"\[[A-Z][A-Z0-9_]{1,39}\]|(?<![A-Za-z0-9_])[A-Z][A-Z_]{1,30}_\d{1,4}(?![A-Za-z0-9_])"
)
REPEAT_RECOGNIZER = "firewall-repeated-value"
# spaCy labels words such as "hours" or "today" as DATE/TIME. Keep a statistical date only
# when it contains a digit or a weekday or month name.
_CONCRETE_DATE = regex.compile(
    r"\d|\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    regex.IGNORECASE,
)


class DetectionError(Exception):
    """Detection could not be completed. Callers must fail closed."""


class SensitiveDataAnalyzer:
    """Wraps a Presidio AnalyzerEngine and maps its results to firewall categories."""

    def __init__(
        self,
        config: DetectionConfig,
        spacy_model: str,
        score_threshold: float,
        low_confidence_threshold: float,
    ) -> None:
        self.config = config
        self.spacy_model = spacy_model
        self.score_threshold = score_threshold
        self.low_confidence_threshold = low_confidence_threshold
        self._engine = None
        self._lock = threading.Lock()
        self.status = "NOT_LOADED"
        self.message = "Detection engine has not been loaded."
        self.load_seconds: float | None = None

    @property
    def ready(self) -> bool:
        return self._engine is not None

    @property
    def categories(self) -> set[str]:
        return set(self.config.categories)

    @property
    def _custom_names(self) -> set[str]:
        return {r.name for r in self.config.custom_recognizers}

    def load(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            started = time.perf_counter()
            try:
                from presidio_analyzer import AnalyzerEngine
                from presidio_analyzer.nlp_engine import NlpEngineProvider

                logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
                provider = NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [{"lang_code": "en", "model_name": self.spacy_model}],
                    }
                )
                engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
                for rec in self.config.custom_recognizers:
                    engine.registry.add_recognizer(ContextualPatternRecognizer(rec))
                self._engine = engine
                self.load_seconds = round(time.perf_counter() - started, 2)
                self.status = "READY"
                self.message = f"Presidio loaded with spaCy model {self.spacy_model}."
                logger.info("detection engine ready", extra={"load_seconds": self.load_seconds})
            except Exception as exc:  # noqa: BLE001 - reported as unavailable, requests fail closed
                self.status = "UNAVAILABLE"
                self.message = (
                    f"Detection engine failed to load ({type(exc).__name__}). "
                    f"Check that the spaCy model '{self.spacy_model}' is installed."
                )
                logger.error("detection engine failed to load", extra={"error_type": type(exc).__name__})

    def analyze(self, text: str, resolve_overlaps: bool = True, normalize: bool = False) -> list[DetectedEntity]:
        """Detect entities in ``text``. Raises DetectionError on any failure.

        ``resolve_overlaps=False`` returns every raw detection; outbound checks use it so an
        overlap decision can never hide a restricted value.

        ``normalize=True`` runs detection on the spoken-number normalized text ("P four eight
        two" -> "P482") and maps every span back, so values always come from the ORIGINAL text.
        """
        if self._engine is None:
            raise DetectionError("Detection engine is not available.")
        try:
            norm = normalize_numbers(text) if normalize else None
        except Exception as exc:  # noqa: BLE001 - fail closed: no detection result, no processing
            raise DetectionError("Spoken-number normalization failed.") from exc
        target = norm.text if norm is not None and norm.changed else text
        try:
            presidio_entities = list(self.config.presidio_entities)
            custom_entities = sorted({r.entity for r in self.config.custom_recognizers})
            results = self._engine.analyze(
                text=target,
                language="en",
                entities=presidio_entities + custom_entities,
                score_threshold=self.score_threshold,
            )
        except Exception as exc:  # noqa: BLE001
            raise DetectionError("Detection engine raised an error.") from exc

        mapped: list[DetectedEntity] = []
        for r in results:
            category = self.config.presidio_entities.get(r.entity_type, r.entity_type)
            if category not in self.config.categories:
                continue
            recognizer = (r.recognition_metadata or {}).get("recognizer_name", "presidio")
            if category == "DATE_TIME" and recognizer == "SpacyRecognizer" and not _CONCRETE_DATE.search(target[r.start : r.end]):
                continue
            start, end = (r.start, r.end) if target is text else map_span(norm, r.start, r.end)
            mapped.append(
                DetectedEntity(
                    entity_type=category,
                    start=start,
                    end=end,
                    score=round(float(r.score), 3),
                    value=text[start:end],
                    recognizer=recognizer,
                    low_confidence=float(r.score) < self.low_confidence_threshold,
                    normalized=target is not text and text[start:end] != target[r.start : r.end],
                )
            )
        if not resolve_overlaps:
            return sorted(mapped, key=lambda e: (e.start, e.end))
        resolved = self._resolve_overlaps(mapped)
        return self._propagate_repeated_values(text, resolved)

    def scan(self, text: str, resolve_overlaps: bool = True) -> list[DetectedEntity]:
        """Detect entities while ignoring firewall tokens such as [PERSON_1]."""
        placeholders = [m.span() for m in PLACEHOLDER_PATTERN.finditer(text)]
        return [
            e
            for e in self.analyze(text, resolve_overlaps=resolve_overlaps)
            if not any(e.start < p_end and p_start < e.end for p_start, p_end in placeholders)
        ]

    def _resolve_overlaps(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Keep a deterministic, non-overlapping set of spans.

        Preference: custom (deterministic, context-aware) recognizers first, then higher
        score, then longer span, then category name. Custom recognizers win so that a
        statistical fragment (spaCy tagging "+91" as a place) can never knock out a full
        identifier and leave the rest of it in clear text. The same input always produces
        the same output.
        """
        custom = self._custom_names

        def preference(e: DetectedEntity) -> tuple:
            return (0 if e.recognizer in custom else 1, -e.score, -e.length, e.entity_type, e.start)

        accepted: list[DetectedEntity] = []
        for candidate in sorted(entities, key=preference):
            if candidate.length <= 0:
                continue
            if any(candidate.start < a.end and a.start < candidate.end for a in accepted):
                continue
            accepted.append(candidate)
        return sorted(accepted, key=lambda e: (e.start, e.end))

    @staticmethod
    def _propagate_repeated_values(text: str, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Also flag later repetitions of a detected value that the detector missed."""
        result = list(entities)
        for entity in entities:
            value = entity.value.strip()
            if len(value) < 3:
                continue
            pattern = regex.compile(r"(?<!\w)" + regex.escape(value) + r"(?!\w)", regex.IGNORECASE)
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < e.end and e.start < end for e in result):
                    continue
                result.append(
                    DetectedEntity(
                        entity_type=entity.entity_type,
                        start=start,
                        end=end,
                        score=entity.score,
                        value=text[start:end],
                        recognizer=REPEAT_RECOGNIZER,
                        low_confidence=entity.low_confidence,
                    )
                )
        return sorted(result, key=lambda e: (e.start, e.end))

    def describe(self) -> list[dict]:
        sources: dict[str, list[str]] = {c: [] for c in self.config.categories}
        for presidio_name, category in self.config.presidio_entities.items():
            sources[category].append(f"Presidio {presidio_name}")
        for rec in self.config.custom_recognizers:
            sources[rec.entity].append(f"Custom {rec.name}")
        return [
            {
                "category": name,
                "description": info.description,
                "limitations": info.limitations,
                "sources": sources[name],
            }
            for name, info in self.config.categories.items()
        ]
