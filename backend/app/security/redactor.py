"""Deterministic redaction using Presidio Anonymizer, verified independently."""

from __future__ import annotations

import regex

from app.detection.entities import DetectedEntity


class RedactionError(Exception):
    """Redaction could not be completed or verified. Callers must fail closed."""


def placeholder(entity_type: str) -> str:
    return f"[{entity_type}]"


class Redactor:
    def __init__(self) -> None:
        from presidio_anonymizer import AnonymizerEngine

        self._engine = AnonymizerEngine()

    def redact(self, text: str, entities: list[DetectedEntity]) -> str:
        if not entities:
            return text
        self._check_spans(text, entities)
        try:
            from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

            results = [RecognizerResult(e.entity_type, e.start, e.end, e.score) for e in entities]
            operators = {
                e.entity_type: OperatorConfig("replace", {"new_value": placeholder(e.entity_type)})
                for e in entities
            }
            anonymized = self._engine.anonymize(
                text=text,
                analyzer_results=results,
                operators=operators,
                merge_entities_with_spaces=False,
            ).text
        except Exception as exc:  # noqa: BLE001
            raise RedactionError("Anonymizer failed.") from exc

        expected = self._reference_redaction(text, entities)
        if anonymized != expected:
            raise RedactionError("Anonymizer output did not match the expected span replacement.")
        self._verify_no_values_remain(anonymized, entities)
        return anonymized

    @staticmethod
    def _check_spans(text: str, entities: list[DetectedEntity]) -> None:
        ordered = sorted(entities, key=lambda e: e.start)
        previous_end = -1
        for e in ordered:
            if e.start < 0 or e.end > len(text) or e.start >= e.end:
                raise RedactionError("Entity span is outside the transcript.")
            if e.start < previous_end:
                raise RedactionError("Entity spans overlap.")
            if text[e.start : e.end] != e.value:
                raise RedactionError("Entity span does not match the detected value.")
            previous_end = e.end

    @staticmethod
    def _reference_redaction(text: str, entities: list[DetectedEntity]) -> str:
        result = text
        for e in sorted(entities, key=lambda e: e.start, reverse=True):
            result = result[: e.start] + placeholder(e.entity_type) + result[e.end :]
        return result

    @staticmethod
    def _verify_no_values_remain(redacted: str, entities: list[DetectedEntity]) -> None:
        for e in entities:
            if contains_value(redacted, e.value):
                raise RedactionError("A redacted value is still present in the output.")


def contains_value(text: str, value: str) -> bool:
    """Case-insensitive whole-token search used by redaction and outbound checks."""
    value = value.strip()
    if len(value) < 3:
        return False
    pattern = regex.compile(r"(?<!\w)" + regex.escape(value) + r"(?!\w)", regex.IGNORECASE)
    return pattern.search(text) is not None
